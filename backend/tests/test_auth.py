"""Login, sessions, lockout, CSRF and cross-site protection."""

from datetime import UTC, datetime, timedelta

from llm_manager.db.models import Role, Session
from tests.conftest import ADMIN_PASSWORD, StackFactory


async def test_login_sets_a_hardened_cookie(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    response = await stack.anonymous().post(
        "/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("__host-lm_session=")
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie
    assert "domain" not in cookie  # required by the __Host- prefix


async def test_wrong_password_and_unknown_user_look_identical(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    client = stack.anonymous()
    wrong = await client.post("/api/auth/login", json={"username": "admin", "password": "x" * 14})
    unknown = await client.post(
        "/api/auth/login", json={"username": "nobody", "password": "x" * 14}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_account_locks_after_repeated_failures(make_stack: StackFactory) -> None:
    stack = await make_stack(lockout_attempts=3)
    await stack.create_user()
    client = stack.anonymous()
    for _ in range(3):
        await client.post("/api/auth/login", json={"username": "admin", "password": "x" * 14})
    # Even the right password is refused while locked
    right = await client.post(
        "/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert right.status_code == 401
    assert await stack.container.users.unlock("admin", actor="test")
    assert (await stack.login()).headers  # logs in again


async def test_login_is_rate_limited_per_ip(make_stack: StackFactory) -> None:
    stack = await make_stack(login_ip_limit_per_min=3)
    await stack.create_user()
    client = stack.anonymous()
    codes = [
        (await client.post("/api/auth/login", json={"username": "x", "password": "y"})).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [401, 401, 401]
    assert codes[3:] == [429, 429]


async def test_disabled_account_cannot_log_in(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    viewer = await stack.create_user("viewer", Role.VIEWER)
    await stack.container.users.update(viewer.id, is_active=False, role=None, actor="test", ip=None)
    response = await stack.anonymous().post(
        "/api/auth/login", json={"username": "viewer", "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 401


async def test_endpoints_need_a_session(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = stack.anonymous()
    for path in (
        "/api/status",
        "/api/stats",
        "/api/events",
        "/api/auth/me",
        "/api/users",
        "/api/keys",
        "/api/audit",
    ):
        assert (await client.get(path)).status_code == 401, path


async def test_logout_ends_the_session(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    client = await stack.login()
    assert (await client.get("/api/auth/me")).status_code == 200
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_idle_and_expired_sessions_are_rejected(make_stack: StackFactory) -> None:
    stack = await make_stack(session_idle_minutes=30)
    await stack.create_user()
    client = await stack.login()
    await Session.all().update(last_seen_at=datetime.now(UTC) - timedelta(minutes=31))
    assert (await client.get("/api/auth/me")).status_code == 401

    client = await stack.login()
    await Session.all().update(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_state_changes_need_the_csrf_token(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    client = await stack.login()
    token = client.headers.pop("X-CSRF-Token")
    assert (await client.post("/api/auth/logout")).status_code == 403
    assert (
        await client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"})
    ).status_code == 403
    assert (
        await client.post("/api/auth/logout", headers={"X-CSRF-Token": token})
    ).status_code == 204


async def test_cross_site_writes_are_blocked(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    client = await stack.login()
    evil = await client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    cross = await client.post("/api/auth/logout", headers={"Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    assert (await client.get("/api/auth/me")).status_code == 200  # still logged in
    same = await client.post("/api/auth/logout", headers={"Origin": "https://testserver"})
    assert same.status_code == 204


async def test_viewers_cannot_use_admin_endpoints(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    await stack.create_user("viewer", Role.VIEWER)
    viewer = await stack.login("viewer")
    assert (await viewer.get("/api/status")).status_code == 200
    assert (await viewer.get("/api/users")).status_code == 403
    assert (await viewer.get("/api/keys")).status_code == 403
    assert (await viewer.get("/api/audit")).status_code == 403
    assert (await viewer.post("/api/keys", json={"label": "x"})).status_code == 403


async def test_changing_your_password_logs_out_other_sessions(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    first, second = await stack.login(), await stack.login()
    new_password = "a-completely-new-passphrase"
    wrong = await first.post(
        "/api/auth/password", json={"current_password": "nope" * 4, "new_password": new_password}
    )
    assert wrong.status_code == 401
    changed = await first.post(
        "/api/auth/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": new_password},
    )
    assert changed.status_code == 204
    assert (await first.get("/api/auth/me")).status_code == 200  # the session that changed it stays
    assert (await second.get("/api/auth/me")).status_code == 401
    old = await stack.anonymous().post(
        "/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert old.status_code == 401
    assert (await stack.login("admin", new_password)).headers


async def test_secrets_are_not_stored_in_clear(make_stack: StackFactory) -> None:
    stack = await make_stack()
    user = await stack.create_user()
    client = await stack.login()
    cookie = client.cookies["__Host-lm_session"]
    session = await Session.get()
    assert user.password_hash.startswith("$argon2id$")
    assert ADMIN_PASSWORD not in user.password_hash
    assert session.token_hash != cookie
    assert len(session.token_hash) == 64  # SHA-256 hex digest


async def test_hardening_headers_and_no_api_docs(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    client = await stack.login()
    health = await client.get("/healthz")
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"
    assert health.headers["referrer-policy"] == "no-referrer"
    assert (await client.get("/api/status")).headers["cache-control"] == "no-store"
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert (await client.get(path)).status_code == 404
