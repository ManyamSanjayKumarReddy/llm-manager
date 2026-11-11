"""Every list endpoint is paginated on the server, with totals, filters and sane limits."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from llm_manager.db.models import ApiKey, AuditLog, Event, RequestLog, Role
from tests.conftest import Stack, StackFactory

PASSWORD = "a-long-passphrase"


async def admin(stack: Stack) -> httpx.AsyncClient:
    await stack.create_user()
    return await stack.login()


async def test_page_envelope_and_slicing(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    for i in range(12):
        await stack.create_user(f"member{i:02d}", Role.VIEWER, PASSWORD)  # 13 users with admin

    first = (await client.get("/api/users?page=1&page_size=5")).json()
    assert (first["total"], first["page"], first["page_size"], first["pages"]) == (13, 1, 5, 3)
    assert [u["username"] for u in first["items"]] == [
        "admin",
        "member00",
        "member01",
        "member02",
        "member03",
    ]
    last = (await client.get("/api/users?page=3&page_size=5")).json()
    assert [u["username"] for u in last["items"]] == ["member09", "member10", "member11"]


async def test_pages_do_not_overlap_and_cover_everything(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    for i in range(7):
        await stack.api_key(f"key-{i}")
    seen: list[str] = []
    for page in (1, 2, 3, 4):
        body = (await client.get(f"/api/keys?page={page}&page_size=2")).json()
        seen += [k["id"] for k in body["items"]]
    assert len(seen) == len(set(seen)) == 7


async def test_a_page_past_the_end_is_empty_but_reports_the_total(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    body = (await client.get("/api/users?page=99&page_size=10")).json()
    assert body["items"] == []
    assert body["total"] == 1
    assert body["pages"] == 1


@pytest.mark.parametrize(
    "query",
    [
        "page=0",
        "page=-1",
        "page=abc",
        "page_size=0",
        "page_size=101",
        "page_size=100000",
        "page=9999999",
    ],
)
async def test_bad_paging_parameters_are_rejected(make_stack: StackFactory, query: str) -> None:
    stack = await make_stack()
    client = await admin(stack)
    for path in ("/api/users", "/api/keys", "/api/audit", "/api/events", "/api/stats"):
        response = await client.get(f"{path}?{query}")
        assert response.status_code == 422, (path, query)


async def test_default_page_size_is_bounded(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    body = (await client.get("/api/audit")).json()
    assert body["page_size"] == 25


async def test_user_search_and_role_filter(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await stack.create_user("alice", Role.VIEWER, PASSWORD)
    await stack.create_user("alina", Role.ADMIN, PASSWORD)
    await stack.create_user("bob", Role.VIEWER, PASSWORD)

    found = (await client.get("/api/users?q=ALI")).json()
    assert [u["username"] for u in found["items"]] == ["alice", "alina"]
    assert found["total"] == 2
    admins = (await client.get("/api/users?role=admin")).json()
    assert [u["username"] for u in admins["items"]] == ["admin", "alina"]
    both = (await client.get("/api/users?q=ali&role=viewer")).json()
    assert [u["username"] for u in both["items"]] == ["alice"]
    assert (await client.get("/api/users?role=root")).status_code == 422


async def test_search_treats_wildcards_as_plain_text(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await stack.api_key("plain")
    await stack.api_key("100%_done")
    for term, expected in (("%", 1), ("_", 1), ("%_", 1), ("zzz", 0)):
        body = (await client.get("/api/keys", params={"q": term})).json()
        assert body["total"] == expected, term


async def test_key_status_filter(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await stack.api_key("live")
    await stack.api_key("dead")
    await ApiKey.filter(label="dead").update(revoked_at=datetime.now(UTC))
    active = (await client.get("/api/keys?status=active")).json()
    revoked = (await client.get("/api/keys?status=revoked")).json()
    everything = (await client.get("/api/keys")).json()
    assert [k["label"] for k in active["items"]] == ["live"]
    assert [k["label"] for k in revoked["items"]] == ["dead"]
    assert everything["total"] == 2
    assert (await client.get("/api/keys?status=maybe")).status_code == 422


async def test_keys_are_newest_first_and_show_their_creator(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await client.post("/api/keys", json={"label": "older"})
    await client.post("/api/keys", json={"label": "newer"})
    items = (await client.get("/api/keys")).json()["items"]
    assert [k["label"] for k in items] == ["newer", "older"]
    assert items[0]["created_by"] == "admin"


async def test_audit_is_paginated_searchable_and_newest_first(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    for i in range(30):
        await AuditLog.create(actor="robot", action="thing.done", target=f"item-{i}")
    page1 = (await client.get("/api/audit?page_size=10")).json()
    assert page1["total"] >= 31  # the 30 plus the admin's own sign-in
    assert page1["pages"] >= 4
    assert page1["items"][0]["target"] == "item-29"
    only = (await client.get("/api/audit?q=item-1&page_size=100")).json()
    assert {e["target"] for e in only["items"]} == {"item-1"} | {f"item-1{d}" for d in range(10)}
    by_actor = (await client.get("/api/audit?q=ROBOT")).json()
    assert by_actor["total"] == 30


async def test_events_filter_by_model_and_kind(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    now = datetime.now(UTC)
    await Event.bulk_create(
        [
            Event(
                ts=now - timedelta(seconds=i),
                model="a" if i % 2 else "b",
                kind="woke",
                detail=str(i),
            )
            for i in range(8)
        ]
        + [Event(ts=now, model="a", kind="wake_failed", detail="boom")]
    )
    everything = (await client.get("/api/events?page_size=100")).json()
    assert everything["total"] >= 9
    only_a = (await client.get("/api/events?model=a&page_size=100")).json()
    assert {e["model"] for e in only_a["items"]} == {"a"}
    failed = (await client.get("/api/events?kind=wake_failed")).json()
    assert [e["detail"] for e in failed["items"]] == ["boom"]
    small = (await client.get("/api/events?model=a&page_size=2&page=2")).json()
    assert len(small["items"]) == 2
    assert small["page"] == 2


async def test_stats_models_are_paginated(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await RequestLog.bulk_create(
        [
            RequestLog(model=m, status=200, duration_ms=100 * (i + 1), queue_wait_ms=5)
            for m in ("a", "b", "c")
            for i in range(3)
        ]
    )
    page1 = (await client.get("/api/stats?hours=1&page_size=2")).json()
    page2 = (await client.get("/api/stats?hours=1&page_size=2&page=2")).json()
    assert (page1["total"], page1["pages"]) == (3, 2)
    assert [m["model"] for m in page1["items"]] == ["a", "b"]
    assert [m["model"] for m in page2["items"]] == ["c"]
    assert page1["items"][0]["requests"] == 3
    assert page1["items"][0]["p50_ms"] == 200


async def test_viewers_cannot_page_through_admin_lists(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user("viewer1", Role.VIEWER, PASSWORD)
    viewer = await stack.login("viewer1", PASSWORD)
    for path in ("/api/users", "/api/keys", "/api/audit"):
        assert (await viewer.get(f"{path}?page=1&page_size=5")).status_code == 403
    assert (await viewer.get("/api/events")).status_code == 200
