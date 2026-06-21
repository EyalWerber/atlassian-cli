import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from atlassian_cli.commands.project import (
    _ollama_list_models,
    _turso_create_db,
    _write_env,
    app,
)

runner = CliRunner()


# ── Helper unit tests ────────────────────────────────────────────────────────

def test_write_env_local_backend(tmp_path):
    values = {
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
    out = tmp_path / ".env"
    _write_env(values, out)
    content = out.read_text()
    assert "ATLASSIAN_URL=https://test.atlassian.net" in content
    assert "ATLASSIAN_EMAIL=test@example.com" in content
    assert "ATLASSIAN_API_TOKEN=mytoken" in content
    assert "JIRA_PROJECT=SI" in content
    assert "CONFLUENCE_SPACE=SIDEV" in content
    assert "OLLAMA_MODEL=llama3.2" in content
    assert "MEMORY_BACKEND=local" in content
    assert "TURSO_URL" not in content


def test_write_env_turso_backend(tmp_path):
    values = {
        "atlassian_url": "https://test.atlassian.net",
        "atlassian_email": "test@example.com",
        "atlassian_api_token": "mytoken",
        "jira_project": "SI",
        "confluence_space": "SIDEV",
        "ollama_host": "http://localhost:11434",
        "ollama_model": "llama3.2",
        "ollama_embed_model": "nomic-embed-text",
        "qa_base_url": "",
        "memory_backend": "turso",
        "turso_url": "libsql://mydb.turso.io",
        "turso_auth_token": "tok123",
    }
    out = tmp_path / ".env"
    _write_env(values, out)
    content = out.read_text()
    assert "MEMORY_BACKEND=turso" in content
    assert "TURSO_URL=libsql://mydb.turso.io" in content
    assert "TURSO_AUTH_TOKEN=tok123" in content


def test_ollama_list_models_returns_names(requests_mock):
    requests_mock.get(
        "http://localhost:11434/api/tags",
        json={"models": [{"name": "llama3.2"}, {"name": "qwen3"}]},
    )
    models = _ollama_list_models("http://localhost:11434")
    assert models == ["llama3.2", "qwen3"]


def test_ollama_list_models_empty_on_error():
    with patch("atlassian_cli.commands.project.requests.get", side_effect=Exception("down")):
        assert _ollama_list_models("http://localhost:11434") == []


def test_turso_create_db_calls_correct_subprocesses(monkeypatch):
    calls = []

    def mock_run(cmd, **kwargs):
        calls.append(list(cmd))
        result = MagicMock()
        if "--url" in cmd:
            result.stdout = "libsql://mydb.turso.io\n"
        elif "tokens" in cmd:
            result.stdout = "tok123\n"
        return result

    monkeypatch.setattr("atlassian_cli.commands.project.subprocess.run", mock_run)
    url, token = _turso_create_db("mydb")
    assert calls[0] == ["turso", "db", "create", "mydb"]
    assert calls[1] == ["turso", "db", "show", "mydb", "--url"]
    assert calls[2] == ["turso", "db", "tokens", "create", "mydb"]
    assert url == "libsql://mydb.turso.io"
    assert token == "tok123"


# ── CLI wizard tests ─────────────────────────────────────────────────────────

def _base_patches():
    """Return a list of context managers for the happy-path (no-models, local backend)."""
    return [
        patch("atlassian_cli.commands.project._Jira"),
        patch("atlassian_cli.commands.project._Confluence"),
        patch("atlassian_cli.commands.project._ollama_list_models", return_value=[]),
        patch("atlassian_cli.commands.project._ollama_pull", return_value=True),
        patch("atlassian_cli.commands.project.OllamaClient"),
    ]


def test_init_existing_project_local_backend_writes_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Input sequence (one entry per typer.prompt / typer.confirm call):
    # URL, email, token, confirm-token, jira-choice(e), proj-key,
    # conf-choice(e), space-key,
    # ollama-host, model-name (no models installed), embed-model, pull-embed?(n), qa-url,
    # backend(l)
    user_input = "\n".join([
        "https://test.atlassian.net",
        "test@example.com",
        "mytoken",
        "mytoken",      # confirm
        "e",
        "SI",
        "e",
        "SIDEV",
        "",              # ollama host default
        "llama3.2",     # model (else branch, no list)
        "",              # embed model default
        "n",            # don't pull embed
        "",              # qa_base_url empty
        "l",            # local backend
    ])

    with patch("atlassian_cli.commands.project._Jira") as MockJira, \
         patch("atlassian_cli.commands.project._Confluence") as MockConf, \
         patch("atlassian_cli.commands.project._ollama_list_models", return_value=[]), \
         patch("atlassian_cli.commands.project._ollama_pull", return_value=True), \
         patch("atlassian_cli.commands.project.OllamaClient") as MockOllama:
        MockOllama.return_value.ping.return_value = True
        result = runner.invoke(app, ["init"], input=user_input)

    assert result.exit_code == 0, result.output
    content = (tmp_path / ".env").read_text()
    assert "ATLASSIAN_URL=https://test.atlassian.net" in content
    assert "JIRA_PROJECT=SI" in content
    assert "CONFLUENCE_SPACE=SIDEV" in content
    assert "OLLAMA_MODEL=llama3.2" in content
    assert "MEMORY_BACKEND=local" in content
    assert "TURSO_URL" not in content


def test_init_model_selected_by_number(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # When models are available, user enters "2" to pick the second model
    user_input = "\n".join([
        "https://test.atlassian.net",
        "test@example.com",
        "mytoken",
        "mytoken",      # confirm
        "e",
        "SI",
        "e",
        "SIDEV",
        "",
        "2",            # pick second model by number
        "",             # embed model default (nomic-embed-text not in ["llama3.2","qwen3"])
        "n",            # don't pull embed
        "",
        "l",
    ])

    with patch("atlassian_cli.commands.project._Jira"), \
         patch("atlassian_cli.commands.project._Confluence"), \
         patch("atlassian_cli.commands.project._ollama_list_models", return_value=["llama3.2", "qwen3"]), \
         patch("atlassian_cli.commands.project._ollama_pull", return_value=True), \
         patch("atlassian_cli.commands.project.OllamaClient") as MockOllama:
        MockOllama.return_value.ping.return_value = False
        result = runner.invoke(app, ["init"], input=user_input)

    assert result.exit_code == 0, result.output
    content = (tmp_path / ".env").read_text()
    assert "OLLAMA_MODEL=qwen3" in content


def test_init_turso_auto_create(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    user_input = "\n".join([
        "https://test.atlassian.net",
        "test@example.com",
        "mytoken",
        "mytoken",      # confirm
        "e",
        "SI",
        "e",
        "SIDEV",
        "",
        "llama3.2",
        "",
        "n",
        "",
        "t",                    # turso backend
        "n",                    # create new db
        "atlassian-memory",     # db name
    ])

    with patch("atlassian_cli.commands.project._Jira"), \
         patch("atlassian_cli.commands.project._Confluence"), \
         patch("atlassian_cli.commands.project._ollama_list_models", return_value=[]), \
         patch("atlassian_cli.commands.project._ollama_pull", return_value=True), \
         patch("atlassian_cli.commands.project._turso_available", return_value=True), \
         patch("atlassian_cli.commands.project._turso_create_db",
               return_value=("libsql://atlassian-memory.turso.io", "tok999")), \
         patch("atlassian_cli.commands.project.OllamaClient") as MockOllama:
        MockOllama.return_value.ping.return_value = False
        result = runner.invoke(app, ["init"], input=user_input)

    assert result.exit_code == 0, result.output
    content = (tmp_path / ".env").read_text()
    assert "MEMORY_BACKEND=turso" in content
    assert "TURSO_URL=libsql://atlassian-memory.turso.io" in content
    assert "TURSO_AUTH_TOKEN=tok999" in content


def test_init_turso_manual_entry_when_cli_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    user_input = "\n".join([
        "https://test.atlassian.net",
        "test@example.com",
        "mytoken",
        "mytoken",      # confirm
        "e",
        "SI",
        "e",
        "SIDEV",
        "",
        "llama3.2",
        "",
        "n",
        "",
        "t",                            # turso backend
        "libsql://mydb.turso.io",       # manual URL (turso CLI not found)
        "manualtoken",                  # manual token
    ])

    with patch("atlassian_cli.commands.project._Jira"), \
         patch("atlassian_cli.commands.project._Confluence"), \
         patch("atlassian_cli.commands.project._ollama_list_models", return_value=[]), \
         patch("atlassian_cli.commands.project._ollama_pull", return_value=True), \
         patch("atlassian_cli.commands.project._turso_available", return_value=False), \
         patch("atlassian_cli.commands.project.OllamaClient") as MockOllama:
        MockOllama.return_value.ping.return_value = False
        result = runner.invoke(app, ["init"], input=user_input)

    assert result.exit_code == 0, result.output
    content = (tmp_path / ".env").read_text()
    assert "TURSO_URL=libsql://mydb.turso.io" in content
    assert "TURSO_AUTH_TOKEN=manualtoken" in content


def test_init_aborts_when_env_exists_and_user_declines(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("existing=content")
    result = runner.invoke(app, ["init"], input="n\n")
    assert result.exit_code == 0
    assert (tmp_path / ".env").read_text() == "existing=content"


def test_init_overwrites_env_when_user_confirms(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("old=content")
    user_input = "\n".join([
        "y",                            # overwrite existing .env
        "https://test.atlassian.net",
        "test@example.com",
        "mytoken",
        "mytoken",      # confirm
        "e",
        "SI",
        "e",
        "SIDEV",
        "",
        "llama3.2",
        "",
        "n",
        "",
        "l",
    ])

    with patch("atlassian_cli.commands.project._Jira"), \
         patch("atlassian_cli.commands.project._Confluence"), \
         patch("atlassian_cli.commands.project._ollama_list_models", return_value=[]), \
         patch("atlassian_cli.commands.project._ollama_pull", return_value=True), \
         patch("atlassian_cli.commands.project.OllamaClient") as MockOllama:
        MockOllama.return_value.ping.return_value = False
        result = runner.invoke(app, ["init"], input=user_input)

    assert result.exit_code == 0, result.output
    assert "old=content" not in (tmp_path / ".env").read_text()
    assert "JIRA_PROJECT=SI" in (tmp_path / ".env").read_text()


# ── _ensure_gitignored tests ─────────────────────────────────────────────────

def test_ensure_gitignored_appends_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    from atlassian_cli.commands.project import _ensure_gitignored
    _ensure_gitignored(tmp_path / ".env")
    assert ".env" in (tmp_path / ".gitignore").read_text()


def test_ensure_gitignored_skips_when_already_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    from atlassian_cli.commands.project import _ensure_gitignored
    _ensure_gitignored(tmp_path / ".env")
    assert (tmp_path / ".gitignore").read_text().count(".env") == 1


def test_ensure_gitignored_skips_outside_git_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from atlassian_cli.commands.project import _ensure_gitignored
    _ensure_gitignored(tmp_path / ".env")
    assert not (tmp_path / ".gitignore").exists()
