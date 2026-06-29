# `atlassian project init` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `atlassian project init` — an interactive wizard that collects Atlassian credentials, wires up a Jira project and Confluence space (new or existing), picks an Ollama model, chooses a memory backend, and writes a local `.env` file.

**Architecture:** A new `atlassian_cli/commands/project.py` module exposes a `typer.Typer` app with a single `init` command. The command uses `typer.prompt()` / `typer.confirm()` for all input, calls the raw `atlassian` library (not the `JiraClient` wrapper) because Settings don't exist yet, then writes the `.env` and verifies connections. Pure-function helpers (`_write_env`, `_ollama_list_models`, `_turso_create_db`) are unit-testable in isolation; the full wizard flow is tested via `typer.testing.CliRunner` with mocked external calls.

**Tech Stack:** typer, rich, atlassian-python-api, requests, subprocess (for ollama pull + turso CLI), pytest, monkeypatch

## Global Constraints

- Python ≥ 3.11
- No new dependencies — everything used is already in `pyproject.toml`
- Follow existing code style: no comments unless WHY is non-obvious, no docstrings
- Patch target rule: when an import is at module level in `project.py`, patch via `atlassian_cli.commands.project.<name>`; when inside the function body, patch via the source module
- After every commit: `git push origin main`

---

### Task 1: `atlassian project init` wizard

**Files:**
- Create: `atlassian_cli/commands/project.py`
- Modify: `atlassian_cli/main.py:10,25` — import + register `project` typer
- Create: `tests/test_project_init.py`
- Modify: `.env.example` — add `QA_BASE_URL` line (currently missing)

**Interfaces:**
- Produces: `app = typer.Typer(...)` exported from `project.py`; helpers `_write_env(values: dict, path: Path) -> None`, `_ollama_list_models(host: str) -> list[str]`, `_turso_create_db(db_name: str) -> tuple[str, str]` importable for tests

---

- [ ] **Step 1: Write failing tests**

Create `tests/test_project_init.py`:

```python
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
    # URL, email, token, jira-choice(e), proj-key,
    # conf-choice(e), space-key,
    # ollama-host, model-name (no models installed), embed-model, pull-embed?(n), qa-url,
    # backend(l)
    user_input = "\n".join([
        "https://test.atlassian.net",
        "test@example.com",
        "mytoken",
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
```

- [ ] **Step 2: Run tests to verify they all fail**

```
pytest tests/test_project_init.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `atlassian_cli.commands.project` does not exist yet.

- [ ] **Step 3: Create `atlassian_cli/commands/project.py`**

```python
from __future__ import annotations

import shutil
import subprocess
import types
from pathlib import Path

import requests
import typer
from atlassian import Confluence as _Confluence
from atlassian import Jira as _Jira
from rich.console import Console
from rich.panel import Panel

from atlassian_cli.integrations.ollama import OllamaClient

app = typer.Typer(help="Initialize and configure a project")
console = Console()


def _ollama_list_models(host: str) -> list[str]:
    try:
        resp = requests.get(f"{host}/api/tags", timeout=5)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        return []


def _ollama_pull(model: str) -> bool:
    try:
        result = subprocess.run(["ollama", "pull", model], timeout=300)
        return result.returncode == 0
    except Exception:
        return False


def _turso_available() -> bool:
    return shutil.which("turso") is not None


def _turso_create_db(db_name: str) -> tuple[str, str]:
    subprocess.run(["turso", "db", "create", db_name], check=True)
    url = subprocess.run(
        ["turso", "db", "show", db_name, "--url"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    token = subprocess.run(
        ["turso", "db", "tokens", "create", db_name],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return url, token


def _write_env(values: dict, path: Path) -> None:
    lines = [
        "# Generated by atlassian project init",
        f"ATLASSIAN_URL={values['atlassian_url']}",
        f"ATLASSIAN_EMAIL={values['atlassian_email']}",
        f"ATLASSIAN_API_TOKEN={values['atlassian_api_token']}",
        f"JIRA_PROJECT={values['jira_project']}",
        f"CONFLUENCE_SPACE={values['confluence_space']}",
        f"OLLAMA_HOST={values['ollama_host']}",
        f"OLLAMA_MODEL={values['ollama_model']}",
        f"OLLAMA_EMBED_MODEL={values['ollama_embed_model']}",
        "MEMORY_DB_PATH=~/.atlassian-cli/memory.db",
        "MEMORY_VECTOR_PATH=~/.atlassian-cli/vectors/",
        f"QA_BASE_URL={values.get('qa_base_url', '')}",
        f"MEMORY_BACKEND={values['memory_backend']}",
    ]
    if values.get("turso_url"):
        lines.append(f"TURSO_URL={values['turso_url']}")
    if values.get("turso_auth_token"):
        lines.append(f"TURSO_AUTH_TOKEN={values['turso_auth_token']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@app.command("init")
def init() -> None:
    """Interactive wizard to configure a new atlassian-cli project."""
    console.print(Panel(
        "Welcome to [bold]atlassian-cli[/bold] project setup.\n"
        "This wizard creates a [bold].env[/bold] file in the current directory.",
        title="[cyan]atlassian project init[/cyan]",
    ))

    env_path = Path(".env")
    if env_path.exists():
        if not typer.confirm("\n.env already exists. Overwrite?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

    collected: dict = {}

    # ── Step 1: Credentials ──────────────────────────────────────────────
    console.print("\n[bold]Step 1/5[/bold] — Atlassian Credentials")
    collected["atlassian_url"] = typer.prompt(
        "  Atlassian URL", default="https://yourorg.atlassian.net"
    ).rstrip("/")
    collected["atlassian_email"] = typer.prompt("  Email")
    collected["atlassian_api_token"] = typer.prompt("  API Token", hide_input=True)

    _jira = _Jira(
        url=collected["atlassian_url"],
        username=collected["atlassian_email"],
        password=collected["atlassian_api_token"],
        cloud=True,
    )
    _conf = _Confluence(
        url=collected["atlassian_url"],
        username=collected["atlassian_email"],
        password=collected["atlassian_api_token"],
        cloud=True,
    )

    # ── Step 2: Jira project ─────────────────────────────────────────────
    console.print("\n[bold]Step 2/5[/bold] — Jira Project")
    jira_choice = typer.prompt(
        "  (n) Create new project  (e) Use existing", default="e"
    ).strip().lower()

    if jira_choice == "n":
        proj_name = typer.prompt("  Project name")
        proj_key = typer.prompt("  Project key (e.g. MYAPP)").upper()
        with console.status("[bold green]Creating Jira project...[/bold green]"):
            try:
                _jira.create_project(key=proj_key, name=proj_name)
                console.print(f"[green]✓[/green] Created Jira project: {proj_key}")
            except Exception as exc:
                console.print(f"[red]✗[/red] Failed to create project: {exc}")
                raise typer.Exit(1)
        collected["jira_project"] = proj_key
    else:
        proj_key = typer.prompt("  Project key", default="MYAPP").upper()
        try:
            _jira.project(proj_key)
            console.print(f"[green]✓[/green] Found Jira project: {proj_key}")
        except Exception:
            console.print(f"[yellow]⚠[/yellow]  Could not verify project {proj_key} — continuing")
        collected["jira_project"] = proj_key

    # ── Step 3: Confluence space ─────────────────────────────────────────
    console.print("\n[bold]Step 3/5[/bold] — Confluence Space")
    conf_choice = typer.prompt(
        "  (n) Create new space  (e) Use existing", default="e"
    ).strip().lower()

    if conf_choice == "n":
        space_name = typer.prompt("  Space name")
        space_key = typer.prompt("  Space key (e.g. DEV)").upper()
        with console.status("[bold green]Creating Confluence space...[/bold green]"):
            try:
                _conf.create_space(space_name, space_key)
                console.print(f"[green]✓[/green] Created Confluence space: {space_key}")
            except Exception as exc:
                console.print(f"[red]✗[/red] Failed to create space: {exc}")
                raise typer.Exit(1)
        collected["confluence_space"] = space_key
    else:
        space_key = typer.prompt("  Space key", default="DEV").upper()
        try:
            _conf.get_space(space_key)
            console.print(f"[green]✓[/green] Found Confluence space: {space_key}")
        except Exception:
            console.print(f"[yellow]⚠[/yellow]  Could not verify space {space_key} — continuing")
        collected["confluence_space"] = space_key

    # ── Step 4: Ollama ───────────────────────────────────────────────────
    console.print("\n[bold]Step 4/5[/bold] — Ollama Model")
    collected["ollama_host"] = typer.prompt(
        "  Ollama host", default="http://localhost:11434"
    )
    models = _ollama_list_models(collected["ollama_host"])

    if models:
        console.print("  Available models:")
        for i, m in enumerate(models, 1):
            console.print(f"    {i}. {m}")
        console.print("  Enter a number to select, or type a model name to download it.")
        raw = typer.prompt("  Model", default="1")
        if raw.isdigit() and 1 <= int(raw) <= len(models):
            collected["ollama_model"] = models[int(raw) - 1]
        else:
            collected["ollama_model"] = raw
            if raw not in models:
                if typer.confirm(f"  Pull {raw}?", default=True):
                    with console.status(f"Pulling {raw}…"):
                        _ollama_pull(raw)
    else:
        console.print("  [dim](Ollama not reachable or no models installed)[/dim]")
        collected["ollama_model"] = typer.prompt("  Model name", default="llama3.2")

    embed_default = "nomic-embed-text"
    embed_hint = "[green]installed[/green]" if embed_default in models else "[yellow]not installed[/yellow]"
    collected["ollama_embed_model"] = typer.prompt(
        f"  Embed model  ({embed_hint})", default=embed_default
    )
    if collected["ollama_embed_model"] not in models:
        if typer.confirm(f"  Pull {collected['ollama_embed_model']}?", default=True):
            with console.status(f"Pulling {collected['ollama_embed_model']}…"):
                _ollama_pull(collected["ollama_embed_model"])

    collected["qa_base_url"] = typer.prompt(
        "  QA base URL (optional, for test runner)", default=""
    )

    # ── Step 5: Memory backend ───────────────────────────────────────────
    console.print("\n[bold]Step 5/5[/bold] — Memory Backend")
    console.print("  (l) Local SQLite — works offline")
    console.print("  (t) Turso        — shared across machines")
    backend_choice = typer.prompt("  Backend", default="l").strip().lower()

    if backend_choice == "t":
        collected["memory_backend"] = "turso"
        if _turso_available():
            console.print("  [green]turso CLI detected[/green]")
            turso_action = typer.prompt(
                "  (n) Create new database  (e) Use existing", default="n"
            ).strip().lower()
            if turso_action == "n":
                db_name = typer.prompt("  Database name", default="atlassian-memory")
                with console.status("[bold green]Creating Turso database...[/bold green]"):
                    try:
                        url, token = _turso_create_db(db_name)
                        collected["turso_url"] = url
                        collected["turso_auth_token"] = token
                        console.print("[green]✓[/green] Turso database created")
                        console.print(f"  [dim]URL: {url}[/dim]")
                    except Exception as exc:
                        console.print(f"[red]✗[/red] Turso creation failed: {exc}")
                        raise typer.Exit(1)
            else:
                collected["turso_url"] = typer.prompt("  TURSO_URL (libsql://...)")
                collected["turso_auth_token"] = typer.prompt(
                    "  TURSO_AUTH_TOKEN", hide_input=True
                )
        else:
            console.print(
                "  [yellow]turso CLI not found.[/yellow]  "
                "Install: [bold]npm install -g turso[/bold]"
            )
            collected["turso_url"] = typer.prompt("  TURSO_URL (libsql://...)")
            collected["turso_auth_token"] = typer.prompt(
                "  TURSO_AUTH_TOKEN", hide_input=True
            )
    else:
        collected["memory_backend"] = "local"

    # ── Write .env ───────────────────────────────────────────────────────
    _write_env(collected, env_path)
    console.print(f"\n[green]✓[/green] Written: {env_path.resolve()}")

    # ── Verify connections ───────────────────────────────────────────────
    console.print("\n[bold]Verifying connections…[/bold]")

    try:
        _jira.project(collected["jira_project"])
        console.print(f"[green]✓[/green] Jira ({collected['jira_project']})")
    except Exception:
        console.print(f"[red]✗[/red]  Jira ({collected['jira_project']})")

    try:
        _conf.get_space(collected["confluence_space"])
        console.print(f"[green]✓[/green] Confluence ({collected['confluence_space']})")
    except Exception:
        console.print(f"[red]✗[/red]  Confluence ({collected['confluence_space']})")

    _mock = types.SimpleNamespace(
        ollama_host=collected["ollama_host"],
        ollama_model=collected["ollama_model"],
        ollama_embed_model=collected["ollama_embed_model"],
    )
    if OllamaClient(_mock).ping():
        console.print(f"[green]✓[/green] Ollama ({collected['ollama_model']})")
    else:
        console.print(f"[red]✗[/red]  Ollama (not reachable at {collected['ollama_host']})")

    if collected.get("turso_url"):
        from atlassian_cli.integrations.turso import TursoHttpClient
        try:
            TursoHttpClient(
                collected["turso_url"], collected.get("turso_auth_token", "")
            ).execute("SELECT 1")
            console.print(f"[green]✓[/green] Turso ({collected['turso_url']})")
        except Exception:
            console.print("[red]✗[/red]  Turso (connection failed)")

    console.print(
        f"\n[green]Done![/green] Run [bold]atlassian feature create[/bold] to get started."
    )
```

- [ ] **Step 4: Wire `project` into `main.py`**

In `atlassian_cli/main.py`, change:
```python
from atlassian_cli.commands import feature, prd, plan, qa, memory, adr, issue
```
to:
```python
from atlassian_cli.commands import feature, prd, plan, qa, memory, adr, issue, project
```

And after `app.add_typer(issue.app, name="issue")`, add:
```python
app.add_typer(project.app, name="project")
```

- [ ] **Step 5: Add `QA_BASE_URL` to `.env.example`**

In `.env.example`, after the `MEMORY_BACKEND` line, add (before the Turso section):
```
QA_BASE_URL=
```

- [ ] **Step 6: Run all tests**

```
pytest tests/test_project_init.py -v
```

Expected: all tests pass.

Also run the full suite to catch regressions:
```
pytest -v
```

Expected: all existing tests still pass.

- [ ] **Step 7: Smoke-test the command exists**

```
atlassian project --help
atlassian project init --help
```

Expected output includes "Interactive wizard to configure a new atlassian-cli project."

- [ ] **Step 8: Update README**

In `README.md`, find the Commands section and add a new subsection for `project`. Place it before or after the `issue` section. Add:

```markdown
### `atlassian project init`

Interactive setup wizard. Run once per project to create a local `.env` file.

```sh
cd my-project/
atlassian project init
```

The wizard will:
1. Ask for your Atlassian URL, email, and API token
2. Connect to an existing Jira project or create a new one
3. Connect to an existing Confluence space or create a new one
4. List installed Ollama models — pick one or pull a new model on the spot
5. Ask for a memory backend: local SQLite (default) or Turso
   - If Turso is chosen and the `turso` CLI is present, it can create the database automatically
6. Write `.env` in the current directory and verify all connections
```

- [ ] **Step 9: Commit and push**

```bash
git add atlassian_cli/commands/project.py atlassian_cli/main.py tests/test_project_init.py .env.example README.md
git commit -m "feat: add atlassian project init interactive setup wizard"
git push origin main
```

---

## Self-Review

**Spec coverage:**
- ✓ Prompts for credentials (URL, email, token)
- ✓ Create new Jira project OR connect to existing
- ✓ Create new Confluence space OR connect to existing
- ✓ Lists local Ollama models (numbered) + pulls on demand
- ✓ Embed model with separate prompt, pull on demand
- ✓ Local SQLite vs Turso choice
- ✓ Turso auto-create via `turso` CLI if available; manual fallback
- ✓ `.env` written to CWD using `.env.example` values as template
- ✓ Warns if `.env` exists (confirm overwrite)
- ✓ Verifies Jira, Confluence, Ollama (and Turso if configured) with ✓/✗ summary
- ✓ QA_BASE_URL added to `.env.example`

**Placeholder scan:** None found.

**Type consistency:**
- `_write_env(values: dict, path: Path) -> None` — used identically in tests and implementation
- `_ollama_list_models(host: str) -> list[str]` — consistent
- `_turso_create_db(db_name: str) -> tuple[str, str]` — consistent
- `OllamaClient(_mock)` where `_mock` is `types.SimpleNamespace` with `ollama_host`, `ollama_model`, `ollama_embed_model` — matches `OllamaClient.__init__` which reads those three attributes
