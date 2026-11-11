"""User and API-key administration, and the audit trail."""

import pytest

from llm_manager.core.errors import InvalidInputError
from llm_manager.db.models import ApiKey, AuditLog, Role, Session, User
from tests.conftest import ADMIN_PASSWORD, StackFactory

NEW_PASSWORD = "another-long-passphrase"


async def test_admin_creates_a_viewer_who_can_log_in(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    admin = await stack.login()
    created = await admin.post(
        "/api/users", json={"username": "Alice", "password": NEW_PASSWORD, "role": "viewer"}
    )
    assert created.status_code == 201
    assert created.json()["username"] == "alice"  # normalised
    assert "password" not in created.text
    alice = await stack.login("alice", NEW_PASSWORD)
    assert (await alice.get("/api/status")).status_code == 200


async def test_weak_and_duplicate_accounts_are_refused(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    admin = await stack.login()
    weak = await admin.post("/api/users", json={"username": "bob", "password": "short"})
    assert weak.status_code == 422
    same_as_name = await admin.post(
        "/api/users", json={"username": "bobbybobbybobby", "password": "bobbybobbybobby"}
    )
    assert same_as_name.status_code == 422
    ok = {"username": "carol", "password": NEW_PASSWORD}
    assert (await admin.post("/api/users", json=ok)).status_code == 201
    assert (await admin.post("/api/users", json=ok)).status_code == 422  # duplicate


async def test_unknown_fields_are_rejected(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    admin = await stack.login()
    response = await admin.post(
        "/api/users",
        json={"username": "mallory", "password": NEW_PASSWORD, "is_superuser": True},
    )
    assert response.status_code == 422


async def test_disabling_a_user_ends_their_sessions(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    viewer = await stack.create_user("viewer1", Role.VIEWER, NEW_PASSWORD)
    admin = await stack.login()
    viewer_client = await stack.login("viewer1", NEW_PASSWORD)
    assert (await viewer_client.get("/api/status")).status_code == 200

    response = await admin.patch(f"/api/users/{viewer.id}", json={"is_active": False})
    assert response.status_code == 200
    assert (await viewer_client.get("/api/status")).status_code == 401
    assert await Session.filter(user_id=viewer.id).count() == 0
    relogin = await stack.anonymous().post(
        "/api/auth/login", json={"username": "viewer1", "password": NEW_PASSWORD}
    )
    assert relogin.status_code == 401


async def test_an_admin_cannot_lock_themselves_out(make_stack: StackFactory) -> None:
    stack = await make_stack()
    me = await stack.create_user()
    admin = await stack.login()
    for body in ({"is_active": False}, {"role": "viewer"}):
        assert (await admin.patch(f"/api/users/{me.id}", json=body)).status_code == 400


async def test_the_last_active_admin_is_protected(make_stack: StackFactory) -> None:
    stack = await make_stack()
    first = await stack.create_user("admin1")
    await stack.create_user("admin2")
    admin2 = await stack.login("admin2")
    # admin2 may demote admin1 (one admin remains) ...
    assert (
        await admin2.patch(f"/api/users/{first.id}", json={"role": "viewer"})
    ).status_code == 200
    # ... but the service refuses to remove the very last one
    last = await User.get(username="admin2")
    with pytest.raises(InvalidInputError):
        await stack.container.users.update(
            last.id, is_active=False, role=None, actor="test", ip=None
        )
    assert await User.filter(role=Role.ADMIN, is_active=True).count() == 1


async def test_password_reset_logs_the_user_out_everywhere(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    viewer = await stack.create_user("viewer1", Role.VIEWER, NEW_PASSWORD)
    admin = await stack.login()
    viewer_client = await stack.login("viewer1", NEW_PASSWORD)

    reset = await admin.post(
        f"/api/users/{viewer.id}/password", json={"new_password": ADMIN_PASSWORD}
    )
    assert reset.status_code == 204
    assert (await viewer_client.get("/api/status")).status_code == 401
    assert (await stack.login("viewer1", ADMIN_PASSWORD)).headers


async def test_viewers_cannot_use_admin_endpoints(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user("viewer1", Role.VIEWER, NEW_PASSWORD)
    viewer = await stack.login("viewer1", NEW_PASSWORD)
    assert (await viewer.get("/api/users")).status_code == 403
    assert (await viewer.get("/api/keys")).status_code == 403
    assert (await viewer.get("/api/audit")).status_code == 403
    assert (await viewer.post("/api/keys", json={"label": "x"})).status_code == 403


async def test_api_key_lifecycle(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    admin = await stack.login()
    created = await admin.post("/api/keys", json={"label": "ci", "allowed_models": ["a"]})
    assert created.status_code == 201
    token = created.json()["token"]
    assert token.startswith("lm_")

    listed = (await admin.get("/api/keys")).json()["items"]
    assert len(listed) == 1
    assert "token" not in listed[0]
    assert listed[0]["created_by"] == "admin"
    # only a digest is stored
    stored = await ApiKey.get(label="ci")
    assert token not in (stored.key_hash, stored.prefix)
    assert len(stored.key_hash) == 64

    assert (await stack.chat(token, "a")).status_code == 200
    revoked = await admin.delete(f"/api/keys/{listed[0]['id']}")
    assert revoked.status_code == 204
    assert (await stack.chat(token, "a")).status_code == 401
    assert (await admin.delete(f"/api/keys/{listed[0]['id']}")).status_code == 404


async def test_api_key_for_unknown_model_is_refused(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    admin = await stack.login()
    response = await admin.post("/api/keys", json={"label": "x", "allowed_models": ["nope"]})
    assert response.status_code == 422


async def test_changes_are_audited(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    admin = await stack.login()
    await admin.post("/api/keys", json={"label": "ci"})
    await admin.post("/api/users", json={"username": "dave", "password": NEW_PASSWORD})
    actions = {e.action async for e in AuditLog.all()}
    assert {"user.create", "apikey.create", "login.ok"} <= actions
    trail = (await admin.get("/api/audit")).json()["items"]
    assert trail
    assert all("password" not in str(entry).lower() for entry in trail)
