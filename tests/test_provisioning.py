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
