# Phase 4b: ADR System + Bug→Memory Auto-link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a formal Architecture Decision Record (ADR) command group and automatically save a memory note every time `atlassian qa bug` successfully files a Jira bug.

**Architecture:** ADRs are JSON files (LocalStorage, like all other entities) with an auto-linked memory note (type=decision) saved best-effort via MemoryStore. The `bug` command gains a best-effort memory auto-save after filing — Ollama down means memory skipped, not bug filing failed. A new `atlassian adr publish` subcommand pushes an ADR to Confluence using the existing `ConfluenceClient.create_page()`.

**Tech Stack:** Python 3.10+, Typer, Rich, Pydantic v2, pytest 8, pytest-mock 3, existing LocalStorage/MemoryStore/ConfluenceClient infrastructure.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `atlassian_cli/models/adr.py` | `ADR`, `AdrStatus` Pydantic models |
| Create | `atlassian_cli/commands/adr.py` | `atlassian adr add/list/show/publish` |
| Create | `tests/__init__.py` | marks tests as package |
| Create | `tests/test_phase4b.py` | all Phase 4b tests |
| Modify | `atlassian_cli/storage/local.py:9-16` | add `adrs` directory to `__init__` |
| Modify | `atlassian_cli/commands/qa.py:1-16,209-213` | add memory imports + auto-save in `bug()` |
| Modify | `atlassian_cli/main.py:10,23` | register `adr` typer |
| Modify | `pyproject.toml` | add `pytest>=8`, `pytest-mock>=3` dev deps |

---

## Task 1: ADR Model + Test Infrastructure

**Files:**
- Create: `atlassian_cli/models/adr.py`
- Create: `tests/__init__.py`
- Create: `tests/test_phase4b.py` (model + storage tests only)
- Modify: `atlassian_cli/storage/local.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pytest to pyproject.toml**

Open `pyproject.toml` and add after the `[project]` block:

```toml
[project.optional-dependencies]
dev = ["pytest>=8", "pytest-mock>=3"]
```

- [ ] **Step 2: Install dev deps**

```bash
pip install pytest>=8 pytest-mock>=3
```

Expected: packages install without error.

- [ ] **Step 3: Create `tests/__init__.py`**

Create an empty file at `tests/__init__.py`.

- [ ] **Step 4: Write failing tests for ADR model and storage**

Create `tests/test_phase4b.py`:

```python
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from atlassian_cli.storage.local import LocalStorage


# ──────────────────────────────────────────────
# Task 1: ADR Model + Storage
# ──────────────────────────────────────────────

class TestADRModel:
    def test_defaults(self):
        from atlassian_cli.models.adr import ADR, AdrStatus
        now = datetime.now(timezone.utc)
        adr = ADR(
            id="ADR-001",
            title="Use SQLite",
            context="Need persistent storage without a server",
            decision="Use Python stdlib sqlite3",
            consequences="Simple deployment; single-user only",
            created_at=now,
            updated_at=now,
        )
        assert adr.status == AdrStatus.proposed
        assert adr.feature_id is None
        assert adr.memory_id is None
        assert adr.confluence_url is None

    def test_status_values(self):
        from atlassian_cli.models.adr import AdrStatus
        assert AdrStatus.proposed.value == "proposed"
        assert AdrStatus.accepted.value == "accepted"
        assert AdrStatus.deprecated.value == "deprecated"
        assert AdrStatus.superseded.value == "superseded"

    def test_roundtrip_json(self):
        from atlassian_cli.models.adr import ADR, AdrStatus
        now = datetime.now(timezone.utc)
        adr = ADR(
            id="ADR-001",
            title="Use SQLite",
            context="ctx",
            decision="decided",
            consequences="cons",
            feature_id="FEAT-001",
            memory_id="MEM-001",
            status=AdrStatus.accepted,
            created_at=now,
            updated_at=now,
        )
        restored = ADR.model_validate_json(adr.model_dump_json())
        assert restored.id == "ADR-001"
        assert restored.status == AdrStatus.accepted
        assert restored.memory_id == "MEM-001"
        assert restored.feature_id == "FEAT-001"


class TestLocalStorageADR:
    def test_adrs_dir_created(self, tmp_path):
        LocalStorage(base_dir=tmp_path)
        assert (tmp_path / "adrs").is_dir()

    def test_save_and_load(self, tmp_path):
        from atlassian_cli.models.adr import ADR
        storage = LocalStorage(base_dir=tmp_path)
        now = datetime.now(timezone.utc)
        adr = ADR(
            id="ADR-001",
            title="Use ChromaDB",
            context="Need semantic search",
            decision="Use ChromaDB embedded 0.4+",
            consequences="No server needed; local only",
            feature_id="FEAT-001",
            created_at=now,
            updated_at=now,
        )
        storage.save(adr, "adrs")
        loaded = storage.load(ADR, "adrs", "ADR-001")
        assert loaded is not None
        assert loaded.title == "Use ChromaDB"
        assert loaded.feature_id == "FEAT-001"

    def test_next_id_sequence(self, tmp_path):
        from atlassian_cli.models.adr import ADR
        storage = LocalStorage(base_dir=tmp_path)
        assert storage.next_id("ADR", "adrs") == "ADR-001"
        now = datetime.now(timezone.utc)
        storage.save(ADR(id="ADR-001", title="t", context="c", decision="d", consequences="q", created_at=now, updated_at=now), "adrs")
        assert storage.next_id("ADR", "adrs") == "ADR-002"
```

- [ ] **Step 5: Run tests — expect failures**

```bash
pytest tests/test_phase4b.py::TestADRModel tests/test_phase4b.py::TestLocalStorageADR -v
```

Expected: `ModuleNotFoundError: No module named 'atlassian_cli.models.adr'`

- [ ] **Step 6: Create `atlassian_cli/models/adr.py`**

```python
from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class AdrStatus(str, Enum):
    proposed = "proposed"
    accepted = "accepted"
    deprecated = "deprecated"
    superseded = "superseded"


class ADR(BaseModel):
    id: str
    title: str
    status: AdrStatus = AdrStatus.proposed
    context: str
    decision: str
    consequences: str
    feature_id: Optional[str] = None
    memory_id: Optional[str] = None
    confluence_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 7: Add `adrs` directory to `atlassian_cli/storage/local.py`**

Current `__init__` (lines 9–16):

```python
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path.home() / ".atlassian-cli"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "features").mkdir(exist_ok=True)
        (self.base_dir / "prds").mkdir(exist_ok=True)
        (self.base_dir / "plans").mkdir(exist_ok=True)
        (self.base_dir / "qa").mkdir(exist_ok=True)
```

Replace with:

```python
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path.home() / ".atlassian-cli"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "features").mkdir(exist_ok=True)
        (self.base_dir / "prds").mkdir(exist_ok=True)
        (self.base_dir / "plans").mkdir(exist_ok=True)
        (self.base_dir / "qa").mkdir(exist_ok=True)
        (self.base_dir / "adrs").mkdir(exist_ok=True)
```

- [ ] **Step 8: Run tests — expect all pass**

```bash
pytest tests/test_phase4b.py::TestADRModel tests/test_phase4b.py::TestLocalStorageADR -v
```

Expected: `7 passed`

- [ ] **Step 9: Commit**

```bash
git add atlassian_cli/models/adr.py atlassian_cli/storage/local.py tests/__init__.py tests/test_phase4b.py pyproject.toml
git commit -m "feat(4b): ADR model + test infrastructure"
git push origin main
```

---

## Task 2: Bug → Memory Auto-link

**Files:**
- Modify: `atlassian_cli/commands/qa.py`
- Modify: `tests/test_phase4b.py` (add bug memory tests)

- [ ] **Step 1: Add bug memory tests to `tests/test_phase4b.py`**

Append this class after `TestLocalStorageADR`:

```python
# ──────────────────────────────────────────────
# Task 2: Bug → Memory Auto-link
# ──────────────────────────────────────────────

@pytest.fixture
def qa_storage(tmp_path):
    for d in ("features", "prds", "plans", "qa", "adrs"):
        (tmp_path / d).mkdir()
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "id": "QA-001",
        "feature_id": "FEAT-001",
        "prd_id": "PRD-001",
        "qa_base_url": "http://localhost",
        "scenarios": [
            {
                "title": "Login test",
                "steps": ["Navigate to /login", "Enter credentials"],
                "expected_result": "Dashboard shown",
                "bug_key": None,
                "log_path": None,
            }
        ],
        "status": "draft",
        "created_at": now,
        "updated_at": now,
    }
    (tmp_path / "qa" / "QA-001.json").write_text(json.dumps(data))
    return tmp_path


class TestBugMemoryAutoLink:
    def test_bug_auto_saves_memory(self, qa_storage, monkeypatch):
        from atlassian_cli.commands import qa as qa_cmd

        monkeypatch.setattr(
            "atlassian_cli.commands.qa.LocalStorage",
            lambda: LocalStorage(base_dir=qa_storage),
        )
        mock_jira = MagicMock()
        mock_jira.create_bug.return_value = "BUG-123"
        monkeypatch.setattr("atlassian_cli.commands.qa.JiraClient", lambda s: mock_jira)

        mock_store = MagicMock()
        mock_store.next_id.return_value = "MEM-001"
        monkeypatch.setattr(
            "atlassian_cli.commands.qa.MemoryStore", lambda **kwargs: mock_store
        )
        mock_settings = MagicMock()
        mock_settings.memory_db_path = "~/.atlassian-cli/memory.db"
        mock_settings.memory_vector_path = "~/.atlassian-cli/vectors/"
        monkeypatch.setattr("atlassian_cli.commands.qa.get_settings", lambda: mock_settings)

        runner = CliRunner()
        result = runner.invoke(qa_cmd.app, [
            "bug", "QA-001",
            "--scenario", "Login test",
            "--actual", "500 Internal Server Error",
            "--expected", "Dashboard shown",
        ])

        assert result.exit_code == 0, result.output
        assert "BUG-123" in result.output
        assert "MEM-001" in result.output

        mock_store.add.assert_called_once()
        mem_arg = mock_store.add.call_args[0][0]
        assert mem_arg.feature_id == "FEAT-001"
        assert mem_arg.qa_id == "QA-001"
        assert "bug" in mem_arg.tags
        assert "BUG-123" in mem_arg.content

    def test_bug_succeeds_when_ollama_down(self, qa_storage, monkeypatch):
        from atlassian_cli.commands import qa as qa_cmd

        monkeypatch.setattr(
            "atlassian_cli.commands.qa.LocalStorage",
            lambda: LocalStorage(base_dir=qa_storage),
        )
        mock_jira = MagicMock()
        mock_jira.create_bug.return_value = "BUG-999"
        monkeypatch.setattr("atlassian_cli.commands.qa.JiraClient", lambda s: mock_jira)

        def failing_store(**kwargs):
            raise RuntimeError("Ollama not available at http://localhost:11434. Is it running?")
        monkeypatch.setattr("atlassian_cli.commands.qa.MemoryStore", failing_store)

        mock_settings = MagicMock()
        monkeypatch.setattr("atlassian_cli.commands.qa.get_settings", lambda: mock_settings)

        runner = CliRunner()
        result = runner.invoke(qa_cmd.app, [
            "bug", "QA-001",
            "--scenario", "Login test",
            "--actual", "500 error",
            "--expected", "Dashboard",
        ])

        assert result.exit_code == 0, result.output
        assert "BUG-999" in result.output
        assert "skipped" in result.output
```

- [ ] **Step 2: Run tests — expect failures**

```bash
pytest tests/test_phase4b.py::TestBugMemoryAutoLink -v
```

Expected: `AttributeError` — `MemoryStore` not imported in `qa.py`

- [ ] **Step 3: Modify `atlassian_cli/commands/qa.py` — add imports**

Add these two lines after the existing imports at the top of the file (after line 15 `from atlassian_cli.storage.local import LocalStorage`):

```python
from atlassian_cli.models.memory import Memory, MemoryType
from atlassian_cli.storage.memory_store import MemoryStore
```

- [ ] **Step 4: Modify `atlassian_cli/commands/qa.py` — add memory auto-save to `bug()`**

At the very end of the `bug()` function, after `console.print(f"[green]✓[/green] QA Plan updated  [{qa_id}]")`, append:

```python
    # Auto-save memory note (best-effort — bug filing must never fail because Ollama is down)
    try:
        mem_store = MemoryStore(
            db_path=settings.memory_db_path,
            vector_path=settings.memory_vector_path,
            ollama=OllamaClient(settings),
        )
        now_mem = datetime.now(timezone.utc)
        mem = Memory(
            id=mem_store.next_id(),
            content=(
                f"Bug {bug_key} filed: [{qa_id}] scenario '{scenario}'. "
                f"Actual: {actual}. Expected: {expected}."
            ),
            type=MemoryType.note,
            tags=["bug"],
            feature_id=plan.feature_id,
            qa_id=qa_id,
            created_at=now_mem,
            updated_at=now_mem,
        )
        mem_store.add(mem)
        console.print(f"[green]✓[/green] Memory auto-saved  [{mem.id}]")
    except Exception:
        console.print("[dim]  (memory auto-save skipped — Ollama not available)[/dim]")
```

- [ ] **Step 5: Run tests — expect all pass**

```bash
pytest tests/test_phase4b.py::TestBugMemoryAutoLink -v
```

Expected: `2 passed`

- [ ] **Step 6: Run full suite**

```bash
pytest tests/test_phase4b.py -v
```

Expected: `9 passed`

- [ ] **Step 7: Commit**

```bash
git add atlassian_cli/commands/qa.py tests/test_phase4b.py
git commit -m "feat(4b): auto-save memory note when atlassian qa bug is filed"
git push origin main
```

---

## Task 3: ADR add / list / show Commands

**Files:**
- Create: `atlassian_cli/commands/adr.py`
- Modify: `atlassian_cli/main.py`
- Modify: `tests/test_phase4b.py` (add ADR command tests)

- [ ] **Step 1: Add ADR command tests to `tests/test_phase4b.py`**

Append after `TestBugMemoryAutoLink`:

```python
# ──────────────────────────────────────────────
# Task 3: ADR add / list / show
# ──────────────────────────────────────────────

class TestADRCommands:
    def test_add_saves_adr_and_memory(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import adr as adr_cmd
        from atlassian_cli.models.adr import ADR, AdrStatus

        monkeypatch.setattr(
            "atlassian_cli.commands.adr.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        mock_store = MagicMock()
        mock_store.next_id.return_value = "MEM-001"
        monkeypatch.setattr(
            "atlassian_cli.commands.adr.MemoryStore", lambda **kwargs: mock_store
        )
        mock_settings = MagicMock()
        monkeypatch.setattr("atlassian_cli.commands.adr.get_settings", lambda: mock_settings)

        runner = CliRunner()
        result = runner.invoke(adr_cmd.app, [
            "add",
            "--title", "Use SQLite for persistence",
            "--context", "Need to store records locally without a server",
            "--decision", "Use Python stdlib sqlite3 module",
            "--consequences", "Simple deployment; single-user only",
            "--feature", "FEAT-001",
        ])

        assert result.exit_code == 0, result.output
        assert "ADR-001" in result.output
        assert "MEM-001" in result.output

        loaded = LocalStorage(base_dir=tmp_path).load(ADR, "adrs", "ADR-001")
        assert loaded is not None
        assert loaded.title == "Use SQLite for persistence"
        assert loaded.memory_id == "MEM-001"
        assert loaded.feature_id == "FEAT-001"
        assert loaded.status == AdrStatus.proposed

        mock_store.add.assert_called_once()
        mem_arg = mock_store.add.call_args[0][0]
        assert mem_arg.type.value == "decision"
        assert "adr" in mem_arg.tags
        assert "ADR-001" in mem_arg.content

    def test_add_without_memory_when_ollama_down(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import adr as adr_cmd
        from atlassian_cli.models.adr import ADR

        monkeypatch.setattr(
            "atlassian_cli.commands.adr.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        def failing_store(**kwargs):
            raise RuntimeError("Ollama not available")
        monkeypatch.setattr("atlassian_cli.commands.adr.MemoryStore", failing_store)
        mock_settings = MagicMock()
        monkeypatch.setattr("atlassian_cli.commands.adr.get_settings", lambda: mock_settings)

        runner = CliRunner()
        result = runner.invoke(adr_cmd.app, [
            "add",
            "--title", "Offline decision",
            "--context", "ctx",
            "--decision", "decided",
            "--consequences", "cons",
        ])

        assert result.exit_code == 0, result.output
        assert "ADR-001" in result.output
        assert "skipped" in result.output

        loaded = LocalStorage(base_dir=tmp_path).load(ADR, "adrs", "ADR-001")
        assert loaded is not None
        assert loaded.memory_id is None

    def test_list_shows_all_adrs(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import adr as adr_cmd
        from atlassian_cli.models.adr import ADR

        monkeypatch.setattr(
            "atlassian_cli.commands.adr.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        storage = LocalStorage(base_dir=tmp_path)
        now = datetime.now(timezone.utc)
        for i in range(1, 3):
            storage.save(ADR(
                id=f"ADR-00{i}", title=f"Decision {i}", context="c",
                decision="d", consequences="q",
                feature_id="FEAT-001" if i == 1 else None,
                created_at=now, updated_at=now,
            ), "adrs")

        runner = CliRunner()
        result = runner.invoke(adr_cmd.app, ["list"])
        assert result.exit_code == 0
        assert "ADR-001" in result.output
        assert "ADR-002" in result.output

    def test_list_filters_by_feature(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import adr as adr_cmd
        from atlassian_cli.models.adr import ADR

        monkeypatch.setattr(
            "atlassian_cli.commands.adr.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        storage = LocalStorage(base_dir=tmp_path)
        now = datetime.now(timezone.utc)
        storage.save(ADR(id="ADR-001", title="D1", context="c", decision="d", consequences="q", feature_id="FEAT-001", created_at=now, updated_at=now), "adrs")
        storage.save(ADR(id="ADR-002", title="D2", context="c", decision="d", consequences="q", feature_id="FEAT-002", created_at=now, updated_at=now), "adrs")

        runner = CliRunner()
        result = runner.invoke(adr_cmd.app, ["list", "--feature", "FEAT-001"])
        assert result.exit_code == 0
        assert "ADR-001" in result.output
        assert "ADR-002" not in result.output

    def test_show_prints_all_fields(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import adr as adr_cmd
        from atlassian_cli.models.adr import ADR, AdrStatus

        monkeypatch.setattr(
            "atlassian_cli.commands.adr.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        storage = LocalStorage(base_dir=tmp_path)
        now = datetime.now(timezone.utc)
        storage.save(ADR(
            id="ADR-001",
            title="Use ChromaDB",
            context="Need semantic search",
            decision="Use ChromaDB 0.4+",
            consequences="Local only; 768-dim vectors",
            feature_id="FEAT-001",
            memory_id="MEM-001",
            status=AdrStatus.accepted,
            created_at=now,
            updated_at=now,
        ), "adrs")

        runner = CliRunner()
        result = runner.invoke(adr_cmd.app, ["show", "ADR-001"])
        assert result.exit_code == 0
        assert "Use ChromaDB" in result.output
        assert "accepted" in result.output
        assert "FEAT-001" in result.output
        assert "MEM-001" in result.output

    def test_show_not_found(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import adr as adr_cmd

        monkeypatch.setattr(
            "atlassian_cli.commands.adr.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        runner = CliRunner()
        result = runner.invoke(adr_cmd.app, ["show", "ADR-999"])
        assert result.exit_code == 1
        assert "not found" in result.output
```

- [ ] **Step 2: Run tests — expect failures**

```bash
pytest tests/test_phase4b.py::TestADRCommands -v
```

Expected: `ModuleNotFoundError: No module named 'atlassian_cli.commands.adr'`

- [ ] **Step 3: Create `atlassian_cli/commands/adr.py`**

```python
from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.confluence import ConfluenceClient
from atlassian_cli.integrations.ollama import OllamaClient
from atlassian_cli.models.adr import ADR, AdrStatus
from atlassian_cli.models.memory import Memory, MemoryType
from atlassian_cli.storage.local import LocalStorage
from atlassian_cli.storage.memory_store import MemoryStore

app = typer.Typer(help="Manage Architecture Decision Records")
console = Console()


def _adr_to_confluence_body(adr: ADR) -> str:
    def safe(text: str) -> str:
        return (
            text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br/>")
        )
    return "\n".join([
        f"<h2>Status</h2><p>{adr.status.value}</p>",
        f"<h2>Context</h2><p>{safe(adr.context)}</p>",
        f"<h2>Decision</h2><p>{safe(adr.decision)}</p>",
        f"<h2>Consequences</h2><p>{safe(adr.consequences)}</p>",
        f"<p><em>Feature: {adr.feature_id or '—'}  ·  ADR: {adr.id}</em></p>",
    ])


@app.command("add")
def add(
    title: str = typer.Option(..., "--title", help="Short title for this decision"),
    context: str = typer.Option(..., "--context", help="Why was this decision needed"),
    decision: str = typer.Option(..., "--decision", help="What was decided"),
    consequences: str = typer.Option(..., "--consequences", help="Trade-offs and implications"),
    feature: Optional[str] = typer.Option(None, "--feature", help="e.g. FEAT-001"),
    status: AdrStatus = typer.Option(AdrStatus.proposed, "--status"),
) -> None:
    settings = get_settings()
    storage = LocalStorage()
    now = datetime.now(timezone.utc)
    adr_id = storage.next_id("ADR", "adrs")

    memory_id: Optional[str] = None
    try:
        mem_store = MemoryStore(
            db_path=settings.memory_db_path,
            vector_path=settings.memory_vector_path,
            ollama=OllamaClient(settings),
        )
        memory_id = mem_store.next_id()
        mem = Memory(
            id=memory_id,
            content=f"ADR {adr_id}: {title}. Decision: {decision}. Consequences: {consequences}.",
            type=MemoryType.decision,
            tags=["adr"],
            feature_id=feature,
            created_at=now,
            updated_at=now,
        )
        mem_store.add(mem)
    except Exception:
        memory_id = None
        console.print("[dim]  (memory auto-save skipped — Ollama not available)[/dim]")

    adr = ADR(
        id=adr_id,
        title=title,
        status=status,
        context=context,
        decision=decision,
        consequences=consequences,
        feature_id=feature,
        memory_id=memory_id,
        created_at=now,
        updated_at=now,
    )
    storage.save(adr, "adrs")

    mem_suffix = f"  →  memory [{memory_id}]" if memory_id else ""
    console.print(f"[green]✓[/green] ADR saved  [{adr_id}]{mem_suffix}")


@app.command("list")
def list_adrs(
    feature: Optional[str] = typer.Option(None, "--feature"),
    status: Optional[AdrStatus] = typer.Option(None, "--status"),
) -> None:
    storage = LocalStorage()
    adrs = storage.list_all(ADR, "adrs")
    if feature:
        adrs = [a for a in adrs if a.feature_id == feature]
    if status:
        adrs = [a for a in adrs if a.status == status]
    if not adrs:
        console.print("[dim]No ADRs found.[/dim]")
        return
    table = Table(title="ADRs", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Feature")
    table.add_column("Memory")
    table.add_column("Created")
    for a in adrs:
        status_color = (
            "green" if a.status == AdrStatus.accepted
            else "yellow" if a.status == AdrStatus.proposed
            else "dim"
        )
        table.add_row(
            a.id,
            a.title[:60] + "..." if len(a.title) > 60 else a.title,
            f"[{status_color}]{a.status.value}[/{status_color}]",
            a.feature_id or "—",
            a.memory_id or "—",
            a.created_at.strftime("%Y-%m-%d"),
        )
    console.print(table)


@app.command("show")
def show(id: str = typer.Argument(..., help="ADR ID (e.g. ADR-001)")) -> None:
    storage = LocalStorage()
    adr = storage.load(ADR, "adrs", id)
    if not adr:
        console.print(f"[red]✗[/red]  ADR [bold]{id}[/bold] not found")
        raise typer.Exit(1)
    lines = [
        f"[bold]Title:[/bold]        {adr.title}",
        f"[bold]Status:[/bold]       {adr.status.value}",
        f"[bold]Context:[/bold]      {adr.context}",
        f"[bold]Decision:[/bold]     {adr.decision}",
        f"[bold]Consequences:[/bold] {adr.consequences}",
    ]
    if adr.feature_id:
        lines.append(f"[bold]Feature:[/bold]      {adr.feature_id}")
    if adr.memory_id:
        lines.append(f"[bold]Memory:[/bold]       {adr.memory_id}")
    if adr.confluence_url:
        lines.append(f"[bold]Confluence:[/bold]   {adr.confluence_url}")
    lines.append(f"[bold]Created:[/bold]      {adr.created_at.strftime('%Y-%m-%d %H:%M UTC')}")
    console.print(Panel("\n".join(lines), title=f"[cyan]{adr.id}[/cyan]"))


@app.command("publish")
def publish(id: str = typer.Argument(..., help="ADR ID (e.g. ADR-001)")) -> None:
    storage = LocalStorage()
    adr = storage.load(ADR, "adrs", id)
    if not adr:
        console.print(f"[red]✗[/red]  ADR [bold]{id}[/bold] not found")
        raise typer.Exit(1)

    settings = get_settings()
    confluence = ConfluenceClient(settings)
    body = _adr_to_confluence_body(adr)

    try:
        _, url = confluence.create_page(title=f"ADR: {adr.title}", body=body)
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)

    updated = adr.model_copy(update={
        "confluence_url": url,
        "updated_at": datetime.now(timezone.utc),
    })
    storage.save(updated, "adrs")
    console.print(f"[green]✓[/green] ADR published  [{id}]  →  {url}")
```

- [ ] **Step 4: Register `adr` in `atlassian_cli/main.py`**

Change line 10:
```python
from atlassian_cli.commands import feature, prd, plan, qa, memory
```
to:
```python
from atlassian_cli.commands import feature, prd, plan, qa, memory, adr
```

Add after `app.add_typer(memory.app, name="memory")` (line 23):
```python
app.add_typer(adr.app, name="adr")
```

- [ ] **Step 5: Run tests — expect all pass**

```bash
pytest tests/test_phase4b.py::TestADRCommands -v
```

Expected: `6 passed`

- [ ] **Step 6: Run full suite**

```bash
pytest tests/test_phase4b.py -v
```

Expected: `15 passed`

- [ ] **Step 7: Commit**

```bash
git add atlassian_cli/commands/adr.py atlassian_cli/main.py tests/test_phase4b.py
git commit -m "feat(4b): ADR add/list/show commands + register adr typer"
git push origin main
```

---

## Task 4: ADR publish Command + README

**Files:**
- Modify: `tests/test_phase4b.py` (add publish tests)
- Modify: `README.md`

Note: `publish` is already implemented in `commands/adr.py` from Task 3 — this task adds the tests and docs.

- [ ] **Step 1: Add publish tests to `tests/test_phase4b.py`**

Append after `TestADRCommands`:

```python
# ──────────────────────────────────────────────
# Task 4: ADR publish
# ──────────────────────────────────────────────

class TestADRPublish:
    def test_publish_creates_confluence_page(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import adr as adr_cmd
        from atlassian_cli.models.adr import ADR

        monkeypatch.setattr(
            "atlassian_cli.commands.adr.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        storage = LocalStorage(base_dir=tmp_path)
        now = datetime.now(timezone.utc)
        storage.save(ADR(
            id="ADR-001",
            title="Use SQLite",
            context="Need storage",
            decision="SQLite stdlib",
            consequences="Simple",
            created_at=now,
            updated_at=now,
        ), "adrs")

        mock_confluence = MagicMock()
        mock_confluence.create_page.return_value = (
            "page-123", "https://wiki.example.com/adr-use-sqlite"
        )
        monkeypatch.setattr(
            "atlassian_cli.commands.adr.ConfluenceClient", lambda s: mock_confluence
        )
        mock_settings = MagicMock()
        monkeypatch.setattr("atlassian_cli.commands.adr.get_settings", lambda: mock_settings)

        runner = CliRunner()
        result = runner.invoke(adr_cmd.app, ["publish", "ADR-001"])

        assert result.exit_code == 0, result.output
        assert "https://wiki.example.com/adr-use-sqlite" in result.output

        mock_confluence.create_page.assert_called_once()
        call_args = mock_confluence.create_page.call_args
        assert call_args.kwargs["title"] == "ADR: Use SQLite"
        assert "Status" in call_args.kwargs["body"]
        assert "Decision" in call_args.kwargs["body"]

        updated = LocalStorage(base_dir=tmp_path).load(ADR, "adrs", "ADR-001")
        assert updated.confluence_url == "https://wiki.example.com/adr-use-sqlite"

    def test_publish_not_found(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import adr as adr_cmd

        monkeypatch.setattr(
            "atlassian_cli.commands.adr.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        runner = CliRunner()
        result = runner.invoke(adr_cmd.app, ["publish", "ADR-999"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_publish_confluence_error(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import adr as adr_cmd
        from atlassian_cli.models.adr import ADR

        monkeypatch.setattr(
            "atlassian_cli.commands.adr.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        storage = LocalStorage(base_dir=tmp_path)
        now = datetime.now(timezone.utc)
        storage.save(ADR(
            id="ADR-001", title="t", context="c", decision="d", consequences="q",
            created_at=now, updated_at=now,
        ), "adrs")

        mock_confluence = MagicMock()
        mock_confluence.create_page.side_effect = RuntimeError("Permission denied. Check your account has access to this Confluence space.")
        monkeypatch.setattr(
            "atlassian_cli.commands.adr.ConfluenceClient", lambda s: mock_confluence
        )
        mock_settings = MagicMock()
        monkeypatch.setattr("atlassian_cli.commands.adr.get_settings", lambda: mock_settings)

        runner = CliRunner()
        result = runner.invoke(adr_cmd.app, ["publish", "ADR-001"])
        assert result.exit_code == 1
        assert "Permission denied" in result.output
```

- [ ] **Step 2: Run tests — expect pass (publish already implemented)**

```bash
pytest tests/test_phase4b.py::TestADRPublish -v
```

Expected: `3 passed`

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/test_phase4b.py -v
```

Expected: `18 passed`

- [ ] **Step 4: Update README.md — add ADR section**

In `README.md`, find the `### Memory` section and add after it:

```markdown
### ADR (Architecture Decision Records)

```bash
# Record a decision (auto-saves to memory as type=decision)
atlassian adr add \
  --title "Use SQLite for local storage" \
  --context "Need persistent records without requiring a server" \
  --decision "Use Python stdlib sqlite3 module" \
  --consequences "Simple deployment; not suitable for concurrent multi-user access" \
  --feature FEAT-001

# List all ADRs
atlassian adr list
atlassian adr list --feature FEAT-001 --status accepted

# Show full detail
atlassian adr show ADR-001

# Publish to Confluence
atlassian adr publish ADR-001
```

Requires Ollama for memory auto-save (`ollama pull nomic-embed-text`). If Ollama is unavailable, the ADR is still saved locally — memory save is skipped with a warning.
```

Also update `## Local storage` to add the adrs entry:
```
~/.atlassian-cli/adrs/      ADR-001.json, ADR-002.json ...
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase4b.py README.md
git commit -m "feat(4b): ADR publish tests + README docs"
git push origin main
```

---

## Self-Review

**Spec coverage:**
- ✓ ADR model with status enum (proposed/accepted/deprecated/superseded)
- ✓ `atlassian adr add` — saves to LocalStorage + memory best-effort
- ✓ `atlassian adr list` — with `--feature` and `--status` filters
- ✓ `atlassian adr show` — full panel output
- ✓ `atlassian adr publish` — Confluence page + confluence_url saved back
- ✓ Bug → memory auto-link in `atlassian qa bug`
- ✓ Ollama-down resilience for all best-effort memory saves
- ✓ Tests for all happy paths and error cases
- ✓ LocalStorage `adrs/` directory auto-created

**Placeholder scan:** None found — all steps have complete code.

**Type consistency:**
- `ADR.id` → used as `storage.next_id("ADR", "adrs")` → produces `ADR-001` ✓
- `ADR.memory_id` → set from `mem_store.next_id()` → produces `MEM-xxx` ✓
- `_adr_to_confluence_body(adr)` → called in `publish()` with same `ADR` type ✓
- `MemoryStore` constructor signature matches Task 4a implementation ✓
