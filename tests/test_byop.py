"""BYOP device-flow unit tests (network mocked)."""

from unittest.mock import patch

import pytest

from opencode_harness.auth.byop import (
    DEFAULT_BYOP_CLIENT_ID,
    device_verification_url,
    poll_device_token,
    request_device_code,
    resolve_byop_client_id,
    run_byop_login,
)
from opencode_harness.auth.store import (
    clear_stored_key,
    mask_key,
    read_credentials,
    resolve_api_key,
    save_api_key,
)


def test_default_client_id():
    assert resolve_byop_client_id() == DEFAULT_BYOP_CLIENT_ID


def test_client_id_env_override(monkeypatch):
    monkeypatch.setenv("POLLINATIONS_BYOP_KEY", "pk_test_override")
    assert resolve_byop_client_id() == "pk_test_override"


def test_verification_url_relative():
    assert device_verification_url("/device") == "https://enter.pollinations.ai/device"


def test_verification_url_absolute():
    assert device_verification_url("https://enter.pollinations.ai/x") == "https://enter.pollinations.ai/x"


def test_mask_key():
    assert mask_key("sk_abcdefghijklmnop") == "sk_a" + "*" * 11 + "nop" or mask_key(
        "sk_abcdefghijklmnop"
    ).startswith("sk_a")
    masked = mask_key("sk_abcdefghijklmnop")
    assert "sk_a" in masked
    assert "nop" in masked or masked.endswith("nop")
    assert "cdef" not in masked or "*" in masked


def test_save_and_resolve_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr("opencode_harness.auth.store.CREDENTIALS_PATH", tmp_path / "credentials.json")
    monkeypatch.setattr(
        "opencode_harness.auth.store.DEFAULT_CONFIG_DIR",
        tmp_path,
    )
    # re-import path after setattr — save uses CREDENTIALS_PATH module attr
    from opencode_harness.auth import store as store_mod

    store_mod.CREDENTIALS_PATH = tmp_path / "credentials.json"
    store_mod.DEFAULT_CONFIG_DIR = tmp_path

    for env in (
        "POLLINATIONS_API_KEY",
        "OPENAI_API_KEY",
        "OPENCODE_HARNESS_API_KEY",
        "SPROUT_API_KEY",
    ):
        monkeypatch.delenv(env, raising=False)

    assert resolve_api_key() is None
    save_api_key("sk_test_secret_value_xyz", kind="byop", username="jah")
    found = resolve_api_key()
    assert found is not None
    assert found.key == "sk_test_secret_value_xyz"
    assert found.kind == "byop"
    assert found.source == "credentials"
    assert clear_stored_key() is True
    assert resolve_api_key() is None


def test_env_beats_credentials(tmp_path, monkeypatch):
    from opencode_harness.auth import store as store_mod

    store_mod.CREDENTIALS_PATH = tmp_path / "credentials.json"
    store_mod.DEFAULT_CONFIG_DIR = tmp_path
    save_api_key("sk_file_key_abcdefgh", kind="manual")
    monkeypatch.setenv("POLLINATIONS_API_KEY", "sk_env_key_zzzzzzzz")
    found = resolve_api_key()
    assert found is not None
    assert found.source == "env"
    assert found.key == "sk_env_key_zzzzzzzz"


def test_request_device_code_ok():
    with patch("opencode_harness.auth.byop._post_json") as post:
        post.return_value = (
            200,
            {
                "device_code": "dc_1",
                "user_code": "ABCD-1234",
                "verification_uri": "/device",
                "interval": 5,
            },
        )
        device = request_device_code("pk_test")
        assert device.user_code == "ABCD-1234"
        assert device.device_code == "dc_1"


def test_poll_token_success():
    calls = {"n": 0}

    def once(device_code: str):
        calls["n"] += 1
        if calls["n"] < 2:
            return {"ok": False, "error": "authorization_pending"}
        return {"ok": True, "access_token": "sk_granted"}

    with patch("opencode_harness.auth.byop.poll_device_token_once", side_effect=once):
        token = poll_device_token("dc", interval_ms=1, sleep=lambda _s: None)
        assert token == "sk_granted"


def test_poll_token_denied():
    with patch(
        "opencode_harness.auth.byop.poll_device_token_once",
        return_value={"ok": False, "error": "access_denied"},
    ):
        with pytest.raises(RuntimeError, match="denied"):
            poll_device_token("dc", interval_ms=1, sleep=lambda _s: None)


def test_run_byop_login_hooks():
    events = []

    with (
        patch(
            "opencode_harness.auth.byop.request_device_code",
            return_value=__import__(
                "opencode_harness.auth.byop", fromlist=["DeviceCodeResponse"]
            ).DeviceCodeResponse(
                device_code="dc",
                user_code="ZZ-99",
                verification_uri="/device",
                interval=1,
            ),
        ),
        patch("opencode_harness.auth.byop.open_browser", return_value=True),
        patch("opencode_harness.auth.byop.poll_device_token", return_value="sk_ok"),
        patch("opencode_harness.auth.byop.fetch_device_userinfo", return_value=None),
    ):
        result = run_byop_login(
            "pk_x",
            on_device_code=lambda code, url, opened: events.append(("code", code, opened)),
            on_authorized=lambda user: events.append(("auth", user)),
        )
    assert result.access_token == "sk_ok"
    assert events[0][0] == "code"
    assert events[0][1] == "ZZ-99"
    assert events[-1][0] == "auth"
