"""The API serves the built dashboard and adds the browser security headers."""

from pathlib import Path

import pytest

from tests.conftest import StackFactory

INDEX = "<!doctype html><title>app</title>"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX)
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("do not serve")
    return tmp_path


async def test_serves_the_app_shell_and_assets(make_stack: StackFactory, dist: Path) -> None:
    stack = await make_stack(web_dist_path=dist)
    client = stack.anonymous()
    root = await client.get("/")
    assert root.status_code == 200
    assert root.text == INDEX
    assert root.headers["cache-control"] == "no-cache"
    asset = await client.get("/assets/app-abc123.js")
    assert asset.status_code == 200
    assert "javascript" in asset.headers["content-type"]


async def test_unknown_pages_fall_back_to_the_app(make_stack: StackFactory, dist: Path) -> None:
    stack = await make_stack(web_dist_path=dist)
    response = await stack.anonymous().get("/some/page")
    assert response.status_code == 200
    assert response.text == INDEX


async def test_unknown_api_paths_are_not_rewritten(make_stack: StackFactory, dist: Path) -> None:
    stack = await make_stack(web_dist_path=dist)
    client = stack.anonymous()
    for path in ("/api/nope", "/v1/nope"):
        response = await client.get(path)
        assert response.status_code in {401, 404}, path
        assert INDEX not in response.text


async def test_files_outside_the_dashboard_are_not_reachable(
    make_stack: StackFactory, dist: Path
) -> None:
    stack = await make_stack(web_dist_path=dist)
    client = stack.anonymous()
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
        response = await client.get(path)
        assert "do not serve" not in response.text, path


async def test_security_headers_on_every_response(make_stack: StackFactory, dist: Path) -> None:
    stack = await make_stack(web_dist_path=dist)
    for path in ("/", "/healthz", "/api/status"):
        headers = (await stack.anonymous().get(path)).headers
        csp = headers["content-security-policy"]
        assert "script-src 'self'" in csp
        assert "unsafe-inline" not in csp
        assert "frame-ancestors 'none'" in csp
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert "max-age" in headers["strict-transport-security"]


async def test_no_hsts_over_plain_http_development(make_stack: StackFactory) -> None:
    stack = await make_stack(cookie_secure=False)
    headers = (await stack.anonymous().get("/healthz")).headers
    assert "strict-transport-security" not in headers


async def test_without_a_build_only_the_api_exists(make_stack: StackFactory) -> None:
    stack = await make_stack()
    assert (await stack.anonymous().get("/")).status_code == 404
