import pytest

from src.api.routes.admin import SETTING_METADATA
from src.runtime_settings import (
    NON_SECRET_SETTING_KEYS,
    decode_setting_value,
    encode_setting_value,
    encrypt_setting_value,
)


@pytest.fixture()
def encryption_key(monkeypatch):
    monkeypatch.setenv("APP_SETTINGS_ENCRYPTION_KEY", "unit-test-encryption-secret")


@pytest.fixture()
def no_encryption_key(monkeypatch):
    monkeypatch.delenv("APP_SETTINGS_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("BACKEND_AUTH_SECRET", raising=False)
    monkeypatch.delenv("BETTER_AUTH_SECRET", raising=False)


def test_non_secret_setting_is_stored_as_marked_plaintext(no_encryption_key):
    stored = encode_setting_value("TRANSCRIPTION_PROVIDER", "whisperx")

    assert stored == "plain:whisperx"
    assert decode_setting_value("TRANSCRIPTION_PROVIDER", stored) == "whisperx"


def test_non_secret_setting_does_not_require_encryption_key(no_encryption_key):
    # Must not raise even though no encryption secret is configured.
    for setting_key in NON_SECRET_SETTING_KEYS:
        stored = encode_setting_value(setting_key, "some-value")
        assert decode_setting_value(setting_key, stored) == "some-value"


def test_secret_setting_is_encrypted(encryption_key):
    stored = encode_setting_value("ASSEMBLY_AI_API_KEY", "super-secret")

    assert stored.startswith("v1:")
    assert "super-secret" not in stored
    assert decode_setting_value("ASSEMBLY_AI_API_KEY", stored) == "super-secret"


def test_secret_setting_requires_encryption_key(no_encryption_key):
    with pytest.raises(RuntimeError, match="APP_SETTINGS_ENCRYPTION_KEY"):
        encode_setting_value("ASSEMBLY_AI_API_KEY", "super-secret")


def test_plaintext_marker_is_rejected_for_secret_settings(encryption_key):
    # A plain: row planted for a secret setting (e.g. via a raw DB write) must
    # not bypass AES-GCM authenticity — decode refuses instead of trusting it.
    with pytest.raises(ValueError, match="ASSEMBLY_AI_API_KEY"):
        decode_setting_value("ASSEMBLY_AI_API_KEY", "plain:planted-value")


def test_legacy_encrypted_row_still_decodes_for_non_secret_setting(encryption_key):
    # Rows written before the plaintext tier existed are encrypted even for
    # non-secret settings; decode must keep handling them.
    legacy = encrypt_setting_value("assemblyai")

    assert decode_setting_value("TRANSCRIPTION_PROVIDER", legacy) == "assemblyai"


def test_non_secret_tier_matches_admin_metadata():
    # Tier membership must not drift from the admin UI's classification:
    # a setting is non-secret exactly when it is not a password-type input.
    non_password_keys = {
        key
        for key, metadata in SETTING_METADATA.items()
        if metadata["input_type"] != "password"
    }
    assert non_password_keys == set(NON_SECRET_SETTING_KEYS)
