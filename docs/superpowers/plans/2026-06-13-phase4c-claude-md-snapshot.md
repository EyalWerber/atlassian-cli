# Phase 4c: CLAUDE.md Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `atlassian memory snapshot` to generate a `CLAUDE.md` file in the current directory from stored memories and ADRs, giving Claude Code a project context file at session start.

**Architecture:** A new `snapshot` subcommand on the existing `memory` Typer app reads ADRs from LocalStorage and memories from MemoryStore (SQLite only — `list()` never calls Ollama). MemoryStore init is wrapped in try/except so the command falls back to ADRs-only if ChromaDB is unavailable. If `./CLAUDE.md` already exists, the user is prompted to confirm overwrite. The markdown builder is a pure function (`_build_claude_md`) that skips empty sections.

**Tech Stack:** Python 3.10+, Typer, Rich, Pydantic v2, existing LocalStorage / MemoryStore / ADR infrastructure, pytest 8.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `atlassian_cli/commands/memory.py` | Add `snapshot` command + `_build_claude_md()` helper |
| Create | `tests/test_phase4c.py` | All Phase 4c tests |
| Modify | `README.md` | Add `snapshot` to Memory section |

---

## Task 1: Snapshot command + tests

**Files:**
- Modify: `atlassian_cli/commands/memory.py`
- Create: `tests/test_phase4c.py`

- [ ] **Step 1: Write failing tests in `tests/test_phase4c.py`**

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from atlassian_cli.storage.local import LocalStorage


class TestMemorySnapshot:
    def test_snapshot_writes_claude_md(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import memory as mem_cmd
        from atlassian_cli.models.adr import ADR, AdrStatus

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "atlassian_cli.commands.memory.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        storage = LocalStorage(base_dir=tmp_path)
        now = datetime.now(timezone.utc)
        storage.save(ADR(
            id="ADR-001", title="Use SQLite", context="c", decision="d",
            consequences="q", status=AdrStatus.accepted, created_at=now, updated_at=now,
        ), "adrs")

        mock_store = MagicMock()
        def mock_list(type=None, tag=None, limit=50):
            if type and type.value == "decision":
                return [MagicMock(id="MEM-001", content="Chose JWT over sessions")]
            if type and type.value == "context":
                return [MagicMock(id="MEM-002", content="Auth uses Redis fallback")]
            if tag == "bug":
                return [MagicMock(id="MEM-003", content="Bug BUG-123 filed: login 500")]
            return []
        mock_store.list.side_effect = mock_list
        monkeypatch.setattr("atlassian_cli.commands.memory.MemoryStore", lambda **kwargs: mock_store)
        mock_settings = MagicMock()
        monkeypatch.setattr("atlassian_cli.commands.memory.get_settings", lambda: mock_settings)

        runner = CliRunner()
        result = runner.invoke(mem_cmd.app, ["snapshot"])

        assert result.exit_code == 0, result.output
        assert "CLAUDE.md" in result.output

        content = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert "# Project Context" in content
        assert "ADR-001" in content
        assert "Use SQLite" in content
        assert "accepted" in content
        assert "MEM-001" in content
        assert "Chose JWT" in content
        assert "MEM-002" in content
        assert "Redis fallback" in content
        assert "MEM-003" in content
        assert "BUG-123" in content

    def test_snapshot_skips_empty_sections(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import memory as mem_cmd

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "atlassian_cli.commands.memory.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        mock_store = MagicMock()
        mock_store.list.return_value = []
        monkeypatch.setattr("atlassian_cli.commands.memory.MemoryStore", lambda **kwargs: mock_store)
        mock_settings = MagicMock()
        monkeypatch.setattr("atlassian_cli.commands.memory.get_settings", lambda: mock_settings)

        runner = CliRunner()
        result = runner.invoke(mem_cmd.app, ["snapshot"])

        assert result.exit_code == 0, result.output
        content = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert "# Project Context" in content
        assert "## Architecture Decisions" not in content
        assert "## Decision Log" not in content
        assert "## Recent Bugs" not in content

    def test_snapshot_aborts_when_file_exists_and_user_declines(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import memory as mem_cmd

        monkeypatch.chdir(tmp_path)
        existing = tmp_path / "CLAUDE.md"
        existing.write_text("original content", encoding="utf-8")

        monkeypatch.setattr(
            "atlassian_cli.commands.memory.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        mock_store = MagicMock()
        mock_store.list.return_value = []
        monkeypatch.setattr("atlassian_cli.commands.memory.MemoryStore", lambda **kwargs: mock_store)
        mock_settings = MagicMock()
        monkeypatch.setattr("atlassian_cli.commands.memory.get_settings", lambda: mock_settings)

        runner = CliRunner()
        result = runner.invoke(mem_cmd.app, ["snapshot"], input="n\n")

        assert result.exit_code == 0
        assert existing.read_text(encoding="utf-8") == "original content"

    def test_snapshot_overwrites_on_confirm(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import memory as mem_cmd

        monkeypatch.chdir(tmp_path)
        existing = tmp_path / "CLAUDE.md"
        existing.write_text("original content", encoding="utf-8")

        monkeypatch.setattr(
            "atlassian_cli.commands.memory.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        mock_store = MagicMock()
        mock_store.list.return_value = []
        monkeypatch.setattr("atlassian_cli.commands.memory.MemoryStore", lambda **kwargs: mock_store)
        mock_settings = MagicMock()
        monkeypatch.setattr("atlassian_cli.commands.memory.get_settings", lambda: mock_settings)

        runner = CliRunner()
        result = runner.invoke(mem_cmd.app, ["snapshot"], input="y\n")

        assert result.exit_code == 0
        content = existing.read_text(encoding="utf-8")
        assert content != "original content"
        assert "# Project Context" in content

    def test_snapshot_writes_adrs_when_memory_store_fails(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import memory as mem_cmd
        from atlassian_cli.models.adr import ADR

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "atlassian_cli.commands.memory.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        storage = LocalStorage(base_dir=tmp_path)
        now = datetime.now(timezone.utc)
        storage.save(ADR(
            id="ADR-001", title="Use SQLite", context="c", decision="d",
            consequences="q", created_at=now, updated_at=now,
        ), "adrs")

        def failing_store(**kwargs):
            raise RuntimeError("ChromaDB unavailable")
        monkeypatch.setattr("atlassian_cli.commands.memory.MemoryStore", failing_store)
        mock_settings = MagicMock()
        monkeypatch.setattr("atlassian_cli.commands.memory.get_settings", lambda: mock_settings)

        runner = CliRunner()
        result = runner.invoke(mem_cmd.app, ["snapshot"])

        assert result.exit_code == 0, result.output
        content = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert "ADR-001" in content
        assert "Use SQLite" in content
```

- [ ] **Step 2: Run tests — expect failures**

```bash
pytest tests/test_phase4c.py -v
```

Expected: `AttributeError` — `snapshot` command not found on `memory.app`

- [ ] **Step 3: Add imports to `atlassian_cli/commands/memory.py`**

At the top of the file, add `Path` to the imports and add the ADR + LocalStorage imports. The current imports start with:

```python
from datetime import datetime, timezone
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.ollama import OllamaClient
from atlassian_cli.models.memory import Memory, MemoryType
from atlassian_cli.storage.memory_store import MemoryStore
```

Replace with:

```python
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.ollama import OllamaClient
from atlassian_cli.models.adr import ADR, AdrStatus
from atlassian_cli.models.memory import Memory, MemoryType
from atlassian_cli.storage.local import LocalStorage
from atlassian_cli.storage.memory_store import MemoryStore
```

- [ ] **Step 4: Append `_build_claude_md()` and `snapshot` command to `atlassian_cli/commands/memory.py`**

Add at the end of the file (after the `delete` command):

```python
def _build_claude_md(
    adrs: list[ADR],
    decisions: list[Memory],
    contexts: list[Memory],
    bugs: list[Memory],
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts = [
        "# Project Context",
        f"> Generated {now} · Regenerate: `atlassian memory snapshot`",
        "",
    ]
    if adrs:
        parts.append("## Architecture Decisions (ADRs)")
        for adr in adrs:
            parts.append(f"- **{adr.id}** {adr.title} — *{adr.status.value}*")
        parts.append("")
    if decisions:
        parts.append("## Decision Log")
        for m in decisions:
            parts.append(f"- [{m.id}] {m.content}")
        parts.append("")
    if contexts:
        parts.append("## Context Notes")
        for m in contexts:
            parts.append(f"- [{m.id}] {m.content}")
        parts.append("")
    if bugs:
        parts.append("## Recent Bugs")
        for m in bugs:
            parts.append(f"- [{m.id}] {m.content}")
        parts.append("")
    return "\n".join(parts)


@app.command("snapshot")
def snapshot() -> None:
    output = Path("CLAUDE.md")
    if output.exists():
        if not typer.confirm("CLAUDE.md already exists. Overwrite?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            return

    settings = get_settings()
    storage = LocalStorage()
    adrs = storage.list_all(ADR, "adrs")

    decisions: list[Memory] = []
    contexts: list[Memory] = []
    bugs: list[Memory] = []
    try:
        mem_store = MemoryStore(
            db_path=settings.memory_db_path,
            vector_path=settings.memory_vector_path,
            ollama=OllamaClient(settings),
        )
        decisions = mem_store.list(type=MemoryType.decision, limit=50)
        contexts = mem_store.list(type=MemoryType.context, limit=50)
        bugs = mem_store.list(type=MemoryType.note, tag="bug", limit=10)
    except Exception:
        console.print("[dim]  (memory store unavailable — CLAUDE.md will contain ADRs only)[/dim]")

    content = _build_claude_md(adrs, decisions, contexts, bugs)
    output.write_text(content, encoding="utf-8")
    console.print(f"[green]✓[/green] CLAUDE.md written  ({len(content.splitlines())} lines)")
```

- [ ] **Step 5: Run tests — expect all pass**

```bash
pytest tests/test_phase4c.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -v
```

Expected: `22 passed` (17 existing + 5 new)

- [ ] **Step 7: Commit**

```bash
git add atlassian_cli/commands/memory.py tests/test_phase4c.py
git commit -m "feat(4c): atlassian memory snapshot generates CLAUDE.md"
git push origin main
```

---

## Task 2: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the Memory section in `README.md`**

In the `### Memory` section, add `atlassian memory snapshot` after `atlassian memory delete MEM-001`:

```bash
atlassian memory delete MEM-001             # prompts for confirmation

# Generate CLAUDE.md from memory + ADRs (no Ollama required)
atlassian memory snapshot
```

Then update the existing Ollama note (currently after the command block):

Change:
```
> `list` queries SQLite directly — no Ollama required.  
> `add` and `search` require Ollama running with `nomic-embed-text` pulled (`ollama pull nomic-embed-text`).
```

To:
```
> `list` and `snapshot` query SQLite/LocalStorage directly — no Ollama required.  
> `add` and `search` require Ollama running with `nomic-embed-text` pulled (`ollama pull nomic-embed-text`).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(4c): add memory snapshot to README"
git push origin main
```

---

## Self-Review

**Spec coverage:**
- ✓ `atlassian memory snapshot` command added to `memory.py`
- ✓ Writes `./CLAUDE.md` in current working directory
- ✓ Reads all ADRs via `LocalStorage.list_all(ADR, "adrs")`
- ✓ Reads `type=decision` memories (limit 50) via `MemoryStore.list()`
- ✓ Reads `type=context` memories (limit 50) via `MemoryStore.list()`
- ✓ Reads `type=note, tag=bug` memories (limit 10) via `MemoryStore.list()`
- ✓ Empty sections skipped (no heading rendered if list is empty)
- ✓ Existing `CLAUDE.md` → confirm overwrite; "n" aborts without touching the file
- ✓ MemoryStore failure → ADRs still written (best-effort)
- ✓ No Ollama required (`list()` is SQLite-only)
- ✓ README updated

**Placeholder scan:** None found — all steps have complete code.

**Type consistency:**
- `_build_claude_md(adrs, decisions, contexts, bugs)` — parameter types match the callers in `snapshot()` ✓
- `mem_store.list(type=MemoryType.decision, limit=50)` matches `MemoryStore.list(type, feature_id, tag, limit)` ✓
- `mem_store.list(type=MemoryType.note, tag="bug", limit=10)` — `tag` is a valid keyword arg ✓
- `storage.list_all(ADR, "adrs")` matches `LocalStorage.list_all(model_cls, collection)` ✓
- `adr.id`, `adr.title`, `adr.status.value` — all valid fields on `ADR` model ✓
- `m.id`, `m.content` — valid fields on `Memory` model ✓
