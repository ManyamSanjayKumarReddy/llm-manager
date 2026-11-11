"""What an API key may do on the OpenAI-compatible endpoint."""

from tests.conftest import StackFactory


async def test_missing_or_bad_key_is_401_in_openai_format(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = stack.anonymous()
    for headers in ({}, {"Authorization": "Bearer lm_wrong"}, {"Authorization": "Basic abc"}):
        response = await client.get("/v1/models", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"


async def test_session_cookie_does_not_work_on_v1(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    browser = await stack.login()
    assert (await browser.get("/v1/models")).status_code == 401


async def test_models_are_filtered_by_the_allow_list(make_stack: StackFactory) -> None:
    stack = await make_stack()
    token = await stack.api_key(allowed_models=["a", "b"])
    response = await stack.anonymous().get(
        "/v1/models", headers={"Authorization": f"Bearer {token}"}
    )
    assert [m["id"] for m in response.json()["data"]] == ["a", "b"]
    assert not stack.fakes["a"].served  # listing models never wakes anything


async def test_a_model_outside_the_allow_list_is_403(make_stack: StackFactory) -> None:
    stack = await make_stack()
    token = await stack.api_key(allowed_models=["a"])
    response = await stack.chat(token, "b")
    assert response.status_code == 403
    assert stack.fakes["b"].served == 0


async def test_unknown_model_is_404_and_bad_body_is_400(make_stack: StackFactory) -> None:
    stack = await make_stack()
    token = await stack.api_key()
    assert (await stack.chat(token, "ghost")).status_code == 404
    response = await stack.anonymous().post(
        "/v1/chat/completions", headers={"Authorization": f"Bearer {token}"}, content=b"nope"
    )
    assert response.status_code == 400


async def test_requests_per_minute_limit(make_stack: StackFactory) -> None:
    stack = await make_stack()
    token = await stack.api_key(rpm_limit=2)
    codes = [(await stack.chat(token, "a")).status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429]
    other = await stack.api_key("other")
    assert (await stack.chat(other, "a")).status_code == 200  # limits are per key


async def test_request_gets_the_name_vllm_expects(make_stack: StackFactory) -> None:
    stack = await make_stack()
    token = await stack.api_key()
    assert (await stack.chat(token, "a")).status_code == 200
    assert stack.fakes["a"].last_model == "org/a"
