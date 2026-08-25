from pathlib import Path

import pytest

from atlassian_cli import provisioning as p

BASE_VALUES = {
    "atlassian_url": "https://test.atlassian.net",
    "atlassian_email": "test@example.com",
    "atlassian_api_token": "mytoken",
    "jira_project": "SI",
    "confluence_space": "SIDEV",
    "ollama_host": "http://localhost:11434",
    "ollama_model": "llama3.2",
    "ollama_embed_model": "nomic-embed-text",
    "qa_base_url": "",
    "memory_backend": "local",
}


def test_render_env_local_backend():
    out = p.render_env(BASE_VALUES)
    assert "ATLASSIAN_URL=https://test.atlassian.net" in out
    assert "ATLASSIAN_API_TOKEN=mytoken" in out
    assert "JIRA_PROJECT=SI" in out
    assert "MEMORY_BACKEND=local" in out
    assert "TURSO_URL" not in out
    assert out.endswith("\n")


def test_render_env_turso_backend():
    values = {**BASE_VALUES, "memory_backend": "turso",
              "turso_url": "libsql://x.turso.io", "turso_auth_token": "tok"}
    out = p.render_env(values)
    assert "MEMORY_BACKEND=turso" in out
    assert "TURSO_URL=libsql://x.turso.io" in out
    assert "TURSO_AUTH_TOKEN=tok" in out


def test_ensure_gitignored_creates_file(tmp_path):
    (tmp_path / ".git").mkdir()
    added = p.ensure_gitignored(tmp_path, [".env", "memory/"])
    assert added == [".env", "memory/"]
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".env\nmemory/\n"


def test_ensure_gitignored_is_idempotent(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    added = p.ensure_gitignored(tmp_path, [".env", "memory/"])
    assert added == ["memory/"]
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".env\nmemory/\n"


def test_ensure_gitignored_appends_newline_when_missing(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("build/", encoding="utf-8")
    p.ensure_gitignored(tmp_path, [".env"])
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "build/\n.env\n"


def test_ensure_gitignored_accepts_equivalent_env_patterns(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("*.env\n", encoding="utf-8")
    assert p.ensure_gitignored(tmp_path, [".env"]) == []


def test_ensure_gitignored_noop_outside_git_repo(tmp_path):
    assert p.ensure_gitignored(tmp_path, [".env"]) == []
    assert not (tmp_path / ".gitignore").exists()


def test_errors_are_provisioning_errors():
    for cls in (p.AuthError, p.JiraError, p.ConfluenceError):
        assert issubclass(cls, p.ProvisioningError)


import base64
from unittest.mock import MagicMock, patch


class _FakeClient:
    def __init__(self, url, cloud):
        self.url = url
        self.cloud = cloud
        self._session = MagicMock()
        self._session.headers = {}


def test_session_sets_utf8_basic_auth():
    client = p.session(_FakeClient, "https://x.atlassian.net/", "ü@example.com", "tok")
    expected = base64.b64encode("ü@example.com:tok".encode("utf-8")).decode("ascii")
    assert client._session.headers["Authorization"] == f"Basic {expected}"
    assert client._session.auth is None


def test_api_session_sets_json_headers():
    s = p.api_session("https://x.atlassian.net", "a@b.c", "tok")
    assert s.headers["Accept"] == "application/json"
    assert s.headers["Content-Type"] == "application/json"
    assert s.headers["Authorization"].startswith("Basic ")


def test_verify_credentials_returns_account_id():
    jira = MagicMock()
    jira.myself.return_value = {"accountId": "abc-123"}
    assert p.verify_credentials(jira) == "abc-123"


def test_verify_credentials_raises_auth_error_on_401():
    jira = MagicMock()
    jira.myself.side_effect = Exception("401 Unauthorized")
    with pytest.raises(p.AuthError) as exc:
        p.verify_credentials(jira)
    assert "token" in str(exc.value).lower()


def test_verify_credentials_raises_auth_error_on_connection_failure():
    jira = MagicMock()
    jira.myself.side_effect = Exception("connection refused")
    with pytest.raises(p.AuthError):
        p.verify_credentials(jira)


def test_ollama_list_models_returns_names():
    resp = MagicMock()
    resp.json.return_value = {"models": [{"name": "llama3.2"}, {"name": "nomic-embed-text"}]}
    with patch("atlassian_cli.provisioning.requests.get", return_value=resp):
        assert p.ollama_list_models("http://h") == ["llama3.2", "nomic-embed-text"]


def test_ollama_list_models_returns_empty_when_unreachable():
    with patch("atlassian_cli.provisioning.requests.get", side_effect=OSError("down")):
        assert p.ollama_list_models("http://h") == []


def test_turso_available_false_when_missing():
    with patch("atlassian_cli.provisioning.subprocess.run", side_effect=FileNotFoundError):
        assert p.turso_available() is False


def test_turso_create_db_returns_url_and_token():
    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["turso", "db", "create"]:
            return MagicMock(returncode=0, stdout="")
        if "--url" in cmd:
            return MagicMock(returncode=0, stdout="libsql://db.turso.io\n")
        return MagicMock(returncode=0, stdout="tok-123\n")

    with patch("atlassian_cli.provisioning.subprocess.run", side_effect=fake_run):
        assert p.turso_create_db("db") == ("libsql://db.turso.io", "tok-123")
