from src.config import Config


def test_app_base_url_falls_back_to_published_docker_port(monkeypatch):
    # `app_base_url` is the base for links in outbound email. With no explicit
    # setting, stock Docker serves the frontend on host port 3001, so the
    # fallback has to match or the emailed links will not resolve.
    monkeypatch.delenv("NEXT_PUBLIC_APP_URL", raising=False)

    assert Config().app_base_url == "http://localhost:3001"


def test_app_base_url_prefers_env_var_and_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("NEXT_PUBLIC_APP_URL", "https://app.example.com/")

    assert Config().app_base_url == "https://app.example.com"
