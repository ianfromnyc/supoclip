from src.config import Config


def test_app_base_url_falls_back_to_local_dev_port(monkeypatch):
    # `app_base_url` is the base for links in outbound email. Docker compose
    # always injects NEXT_PUBLIC_APP_URL, so this fallback only applies to the
    # local non-Docker path, where the frontend runs on 3107.
    monkeypatch.delenv("NEXT_PUBLIC_APP_URL", raising=False)

    assert Config().app_base_url == "http://localhost:3107"


def test_app_base_url_prefers_env_var_and_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("NEXT_PUBLIC_APP_URL", "https://app.example.com/")

    assert Config().app_base_url == "https://app.example.com"
