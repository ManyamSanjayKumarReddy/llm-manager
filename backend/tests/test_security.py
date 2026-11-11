"""Unit tests for the password, token and limiter helpers."""

import pytest

from llm_manager.core import security


def test_password_hash_roundtrip() -> None:
    hashed = security.hash_password("correct-horse-battery")
    assert hashed.startswith("$argon2id$")
    assert security.verify_password(hashed, "correct-horse-battery")
    assert not security.verify_password(hashed, "wrong")
    assert not security.verify_password("not a hash", "anything")


def test_hashes_are_salted() -> None:
    assert security.hash_password("same-password-1") != security.hash_password("same-password-1")


@pytest.mark.parametrize(
    ("password", "fragment"),
    [
        ("short", "at least"),
        ("a" * 20, "repetitive"),
        ("johnsmith-johnsmith", "username"),
        ("x" * 300, "long"),
    ],
)
def test_weak_passwords_are_described(password: str, fragment: str) -> None:
    problem = security.password_problem(password, "johnsmith", 12)
    assert problem is not None
    assert fragment in problem.lower()


def test_good_password_is_accepted() -> None:
    assert security.password_problem("correct-horse-battery", "johnsmith", 12) is None


@pytest.mark.parametrize("name", ["abc", "a.b_c-d", "user01"])
def test_valid_usernames(name: str) -> None:
    assert security.USERNAME_PATTERN.match(name)


@pytest.mark.parametrize("name", ["ab", "-abc", "has space", "UPPER", "semi;colon", "a" * 65])
def test_invalid_usernames(name: str) -> None:
    assert not security.USERNAME_PATTERN.match(name)


def test_tokens_are_unique_prefixed_and_hash_to_sha256() -> None:
    first, second = security.new_token("lm_"), security.new_token("lm_")
    assert first != second
    assert first.startswith("lm_")
    assert len(first) > 40
    assert len(security.digest(first)) == 64
    assert security.digest(first) == security.digest(first)


def test_sliding_window_limiter() -> None:
    limiter = security.SlidingWindowLimiter(2, 60)
    assert limiter.check("k")[0]
    assert limiter.check("k")[0]
    allowed, retry_after = limiter.check("k")
    assert not allowed
    assert 1 <= retry_after <= 60
    assert limiter.check("other")[0]
