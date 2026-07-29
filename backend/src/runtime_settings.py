from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Mapping

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

RUNTIME_SETTING_KEYS: tuple[str, ...] = (
    "ASSEMBLY_AI_API_KEY",
    "TRANSCRIPTION_PROVIDER",
    "HF_TOKEN",
    "LLM",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "OLLAMA_BASE_URL",
    "OLLAMA_API_KEY",
    "YOUTUBE_DATA_API_KEY",
    "APIFY_API_TOKEN",
    "PEXELS_API_KEY",
)

PROCESS_ENV_SETTING_KEYS = frozenset(
    {
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "OLLAMA_BASE_URL",
        "OLLAMA_API_KEY",
    }
)

# Non-secret settings (plain configuration values, not credentials) are stored
# as marked plaintext so admins can manage them without configuring
# APP_SETTINGS_ENCRYPTION_KEY. Everything else stays AES-GCM encrypted.
NON_SECRET_SETTING_KEYS = frozenset(
    {
        "TRANSCRIPTION_PROVIDER",
        "LLM",
        "OLLAMA_BASE_URL",
    }
)

# Marker prefix distinguishing plaintext rows from "v1:" encrypted rows.
_PLAINTEXT_PREFIX = "plain:"

_settings_cache: dict[str, str] = {}
_prefer_admin_value_cache: set[str] = set()
_original_env_values = {key: os.getenv(key) for key in RUNTIME_SETTING_KEYS}
_applied_process_env_keys: set[str] = set()


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _get_encryption_secret() -> str:
    secret = (
        os.getenv("APP_SETTINGS_ENCRYPTION_KEY")
        or os.getenv("BACKEND_AUTH_SECRET")
        or os.getenv("BETTER_AUTH_SECRET")
    )
    if not secret or len(secret.strip()) < 16:
        raise RuntimeError(
            "APP_SETTINGS_ENCRYPTION_KEY must be set to save encrypted admin settings "
            "(or provide a strong BACKEND_AUTH_SECRET fallback)."
        )
    return secret.strip()


def _get_aesgcm() -> AESGCM:
    key = hashlib.sha256(_get_encryption_secret().encode("utf-8")).digest()
    return AESGCM(key)


def encrypt_setting_value(value: str) -> str:
    nonce = os.urandom(12)
    encrypted = _get_aesgcm().encrypt(nonce, value.encode("utf-8"), None)
    ciphertext, tag = encrypted[:-16], encrypted[-16:]
    return "v1:" + ":".join(
        [_b64url_encode(nonce), _b64url_encode(tag), _b64url_encode(ciphertext)]
    )


def decrypt_setting_value(encrypted_value: str) -> str:
    parts = encrypted_value.split(":")
    if len(parts) != 4 or parts[0] != "v1":
        raise ValueError("Unsupported encrypted setting format")
    nonce = _b64url_decode(parts[1])
    tag = _b64url_decode(parts[2])
    ciphertext = _b64url_decode(parts[3])
    decrypted = _get_aesgcm().decrypt(nonce, ciphertext + tag, None)
    return decrypted.decode("utf-8")


def encode_setting_value(setting_key: str, value: str) -> str:
    """Prepare a setting value for storage in app_settings.

    Non-secret settings are stored as marked plaintext (no encryption key
    needed); secrets are AES-GCM encrypted as before.
    """
    if setting_key in NON_SECRET_SETTING_KEYS:
        return _PLAINTEXT_PREFIX + value
    return encrypt_setting_value(value)


def decode_setting_value(stored_value: str) -> str:
    """Decode a stored setting value, plaintext-marked or encrypted.

    Encrypted rows always decrypt regardless of the setting's current tier, so
    a setting flipped from encrypted to plaintext keeps working until rewritten.
    """
    if stored_value.startswith(_PLAINTEXT_PREFIX):
        return stored_value[len(_PLAINTEXT_PREFIX):]
    return decrypt_setting_value(stored_value)


async def load_runtime_settings_cache(db: AsyncSession) -> None:
    rows = await db.execute(
        text(
            """
            SELECT setting_key, encrypted_value, prefer_admin_value
            FROM app_settings
            WHERE setting_key = ANY(CAST(:setting_keys AS text[]))
            """
        ),
        {"setting_keys": list(RUNTIME_SETTING_KEYS)},
    )

    loaded: dict[str, str] = {}
    prefer_admin_keys: set[str] = set()
    for row in rows.mappings():
        setting_key = row["setting_key"]
        encrypted_value = row["encrypted_value"]
        if bool(row["prefer_admin_value"]):
            prefer_admin_keys.add(setting_key)
        if not encrypted_value:
            continue
        try:
            value = decode_setting_value(encrypted_value).strip()
        except Exception as exc:
            logger.warning("Unable to decode runtime setting %s: %s", setting_key, exc)
            continue
        if value:
            loaded[setting_key] = value

    _settings_cache.clear()
    _settings_cache.update(loaded)
    _prefer_admin_value_cache.clear()
    _prefer_admin_value_cache.update(prefer_admin_keys)
    logger.info("Loaded %s runtime settings", len(_settings_cache))


def get_cached_setting(name: str) -> str | None:
    return _settings_cache.get(name)


def setting_prefers_admin(name: str) -> bool:
    return name in _prefer_admin_value_cache


def apply_settings_to_process_env(resolved_settings: Mapping[str, str | None]) -> None:
    for key in PROCESS_ENV_SETTING_KEYS:
        value = resolved_settings.get(key)
        if value:
            os.environ[key] = value
            _applied_process_env_keys.add(key)
        elif _original_env_values.get(key):
            os.environ[key] = _original_env_values[key] or ""
        elif key in _applied_process_env_keys:
            os.environ.pop(key, None)
            _applied_process_env_keys.discard(key)


async def get_runtime_setting_rows(db: AsyncSession) -> dict[str, dict[str, object]]:
    rows = await db.execute(
        text(
            """
            SELECT setting_key, encrypted_value, prefer_admin_value, updated_at
            FROM app_settings
            WHERE setting_key = ANY(CAST(:setting_keys AS text[]))
            """
        ),
        {"setting_keys": list(RUNTIME_SETTING_KEYS)},
    )
    return {
        row["setting_key"]: {
            "encrypted_value": row["encrypted_value"],
            "prefer_admin_value": row["prefer_admin_value"],
            "updated_at": row["updated_at"],
        }
        for row in rows.mappings()
    }
