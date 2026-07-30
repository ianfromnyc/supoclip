import importlib.util

import pytest
from sqlalchemy import text

from src.runtime_settings import load_runtime_settings_cache
from tests.fixtures.factories import create_user


@pytest.mark.asyncio
async def test_admin_route_requires_admin_user(client, db_session, auth_headers):
    await create_user(
        db_session,
        user_id="user-1",
        email="owner@example.com",
        is_admin=False,
    )

    response = await client.get(
        "/admin/health",
        headers=auth_headers,
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_runtime_settings_reject_unknown_transcription_provider(
    client, db_session, auth_headers
):
    await create_user(
        db_session,
        user_id="user-1",
        email="owner@example.com",
        is_admin=True,
    )
    await db_session.commit()

    response = await client.patch(
        "/admin/runtime-settings",
        headers=auth_headers,
        json={"updates": {"TRANSCRIPTION_PROVIDER": "bogus"}},
    )

    assert response.status_code == 400
    assert "assemblyai" in response.json()["detail"]


async def test_runtime_settings_reject_unknown_openai_service_tier(
    client, db_session, auth_headers
):
    await create_user(
        db_session,
        user_id="user-1",
        email="owner@example.com",
        is_admin=True,
    )
    await db_session.commit()

    response = await client.patch(
        "/admin/runtime-settings",
        headers=auth_headers,
        json={"updates": {"OPENAI_SERVICE_TIER": "turbo"}},
    )

    assert response.status_code == 400
    assert "turbo" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.skipif(
    importlib.util.find_spec("whisperx") is not None,
    reason="whisperx extra is installed, so selecting it is valid",
)
async def test_runtime_settings_reject_whisperx_when_extra_not_installed(
    client, db_session, auth_headers
):
    # When the backend is installed without the whisperx extra, selecting
    # whisperx must fail fast with an actionable message.
    await create_user(
        db_session,
        user_id="user-1",
        email="owner@example.com",
        is_admin=True,
    )
    await db_session.commit()

    response = await client.patch(
        "/admin/runtime-settings",
        headers=auth_headers,
        json={"updates": {"TRANSCRIPTION_PROVIDER": "whisperx"}},
    )

    assert response.status_code == 400
    assert "uv sync --extra whisperx" in response.json()["detail"]


@pytest.mark.asyncio
async def test_non_secret_setting_is_saved_without_encryption_key(
    client, db_session, auth_headers, monkeypatch
):
    # With no encryption secret available, non-secret settings must still save
    # (stored as marked plaintext), while the API reports them as non-secret.
    monkeypatch.delenv("APP_SETTINGS_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("BACKEND_AUTH_SECRET", raising=False)
    monkeypatch.delenv("BETTER_AUTH_SECRET", raising=False)

    await create_user(
        db_session,
        user_id="user-1",
        email="owner@example.com",
        is_admin=True,
    )
    await db_session.commit()

    try:
        response = await client.patch(
            "/admin/runtime-settings",
            headers=auth_headers,
            json={"updates": {"TRANSCRIPTION_PROVIDER": "assemblyai"}},
        )

        assert response.status_code == 200
        setting = next(
            item
            for item in response.json()["settings"]
            if item["key"] == "TRANSCRIPTION_PROVIDER"
        )
        assert setting["secret"] is False
        assert setting["has_admin_value"] is True

        stored = await db_session.execute(
            text(
                "SELECT encrypted_value FROM app_settings "
                "WHERE setting_key = 'TRANSCRIPTION_PROVIDER'"
            )
        )
        assert stored.scalar_one() == "plain:assemblyai"
    finally:
        await db_session.execute(
            text(
                "DELETE FROM app_settings "
                "WHERE setting_key = 'TRANSCRIPTION_PROVIDER'"
            )
        )
        await db_session.commit()
        # The PATCH handler refreshed the module-global settings cache from the
        # saved row; reload after cleanup so no state leaks into other tests.
        await load_runtime_settings_cache(db_session)
        # Release the connection the reload SELECT opened so the fixture
        # teardown (which runs on the session-scoped event loop) has nothing
        # left to roll back on this loop's connection.
        await db_session.rollback()


@pytest.mark.asyncio
async def test_feedback_rejects_invalid_category(client, auth_headers):
    response = await client.post(
        "/feedback",
        headers=auth_headers,
        json={"category": "unknown", "message": "hi"},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_performance_metrics_require_admin(client, db_session, auth_headers):
    await create_user(
        db_session,
        user_id="user-1",
        email="owner@example.com",
        is_admin=False,
    )

    response = await client.get("/tasks/metrics/performance", headers=auth_headers)

    assert response.status_code == 403
