# Phase 4a: Memory Subsystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent memory subsystem — `atlassian memory add/search/list/show/delete` — backed by SQLite (structured queries) and ChromaDB (semantic vector search via Ollama embeddings).

**Architecture:** Memories are stored in SQLite as the source of truth for full records, and in ChromaDB as a vector index for semantic search. On `add`, content is embedded via Ollama's `nomic-embed-text` model and upserted to both stores. On `search`, the query is embedded, ChromaDB returns ranked IDs, then SQLite fetches the full records. On `list`, SQLite is queried directly (no Ollama required).

**Tech Stack:** `chromadb>=0.4` (embedded vector store), `sqlite3` (stdlib), `pydantic` (model validation), `typer` + `rich` (CLI), Ollama `/api/embeddings` endpoint.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `atlassian_cli/models/memory.py` | `Memory` Pydantic model, `MemoryType` enum |
| Create | `atlassian_cli/storage/memory_store.py` | `MemoryStore` — owns SQLite + ChromaDB |
| Create | `atlassian_cli/commands/memory.py` | All 5 memory commands |
| Modify | `atlassian_cli/integrations/ollama.py` | Add `embed_model` attr + `embed()` method |
| Modify | `atlassian_cli/config.py` | Add `memory_vector_path`, `ollama_embed_model` |
| Modify | `atlassian_cli/main.py` | Register `memory` sub-app |
| Modify | `.env.example` | Document new optional vars |
| Modify | `pyproject.toml` | Add `chromadb>=0.4` dependency |
| Modify | `README.md` | Document memory commands and local storage |

---

## Task 1: Memory Model + Config + Dependencies

**Files:**
- Create: `atlassian_cli/models/memory.py`
- Modify: `atlassian_cli/config.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`

- [ ] **Step 1: Create the Memory model**

Create `atlassian_cli/models/memory.py` with this exact content:

```python
from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class MemoryType(str, Enum):
    decision = "decision"
    context = "context"
    note = "note"


class Memory(BaseModel):
    id: str
    content: str
    type: MemoryType = MemoryType.note
    tags: list[str] = []
    feature_id: Optional[str] = None
    prd_id: Optional[str] = None
    plan_id: Optional[str] = None
    qa_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: Add config fields to `atlassian_cli/config.py`**

Add two lines after the `memory_db_path` line (line 24):

```python
    memory_db_path: str = "~/.atlassian-cli/memory.db"
    memory_vector_path: str = "~/.atlassian-cli/vectors/"
    ollama_embed_model: str = "nomic-embed-text"
```

- [ ] **Step 3: Add chromadb dependency to `pyproject.toml`**

In the `dependencies` list, add after `"pyyaml>=6"`:

```toml
    "chromadb>=0.4",
```

- [ ] **Step 4: Document new vars in `.env.example`**

Append to the end of `.env.example`:

```
# --- Phase 4 (Memory) ---
# MEMORY_VECTOR_PATH=~/.atlassian-cli/vectors/
# OLLAMA_EMBED_MODEL=nomic-embed-text
```

- [ ] **Step 5: Install chromadb**

```bash
pip install -e .
```

Expected: installs chromadb and its dependencies without errors.

- [ ] **Step 6: Verify import**

```bash
python -c "from atlassian_cli.models.memory import Memory, MemoryType; from datetime import datetime; m = Memory(id='MEM-001', content='test', created_at=datetime.now(), updated_at=datetime.now()); print(m.id, m.type)"
```

Expected output: `MEM-001 note`

- [ ] **Step 7: Commit**

```bash
git add atlassian_cli/models/memory.py atlassian_cli/config.py pyproject.toml .env.example
git commit -m "feat: add Memory model, config fields, chromadb dep"
git push origin main
```

---

## Task 2: Ollama `embed()` Method

**Files:**
- Modify: `atlassian_cli/integrations/ollama.py`

- [ ] **Step 1: Add `embed_model` to `OllamaClient.__init__`**

In `atlassian_cli/integrations/ollama.py`, update `__init__` (currently lines 67-69):

```python
    def __init__(self, settings: Settings):
        self.host = settings.ollama_host
        self.model = settings.ollama_model
        self.embed_model = settings.ollama_embed_model
```

- [ ] **Step 2: Add the `embed()` method**

Append the following method to the `OllamaClient` class (after `generate_qa_scenarios`, before the end of the class):

```python
    def embed(self, text: str) -> list[float]:
        try:
            response = requests.post(
                f"{self.host}/api/embeddings",
                json={"model": self.embed_model, "prompt": text},
                timeout=30,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"Ollama not available at {self.host}. Is it running?")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama request failed: {e}")
        try:
            return response.json()["embedding"]
        except (KeyError, ValueError) as e:
            raise RuntimeError(f"Ollama returned unexpected response format: {e}")
```

- [ ] **Step 3: Verify `embed_model` attribute loads from config**

```bash
python -c "
from unittest.mock import patch, MagicMock
import os
os.environ.setdefault('ATLASSIAN_URL', 'https://x.atlassian.net')
os.environ.setdefault('ATLASSIAN_EMAIL', 'x@x.com')
os.environ.setdefault('ATLASSIAN_API_TOKEN', 'x')
os.environ.setdefault('JIRA_PROJECT', 'X')
os.environ.setdefault('CONFLUENCE_SPACE', 'X')
from atlassian_cli.config import Settings
from atlassian_cli.integrations.ollama import OllamaClient
s = Settings()
c = OllamaClient(s)
print('embed_model:', c.embed_model)
print('has embed method:', callable(c.embed))
"
```

Expected output:
```
embed_model: nomic-embed-text
has embed method: True
```

- [ ] **Step 4: Commit**

```bash
git add atlassian_cli/integrations/ollama.py
git commit -m "feat: add embed() method to OllamaClient"
git push origin main
```

---

## Task 3: MemoryStore — Full Implementation

**Files:**
- Create: `atlassian_cli/storage/memory_store.py`

- [ ] **Step 1: Create `atlassian_cli/storage/memory_store.py`**

```python
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from atlassian_cli.integrations.ollama import OllamaClient
from atlassian_cli.models.memory import Memory, MemoryType


class MemoryStore:
    def __init__(self, db_path: str, vector_path: str, ollama: OllamaClient):
        self._db_path = Path(db_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._vector_path = Path(vector_path).expanduser()
        self._ollama = ollama
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_db()
        self._init_chroma()

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id         TEXT PRIMARY KEY,
                content    TEXT NOT NULL,
                type       TEXT NOT NULL DEFAULT 'note',
                tags       TEXT NOT NULL DEFAULT '[]',
                feature_id TEXT,
                prd_id     TEXT,
                plan_id    TEXT,
                qa_id      TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(id UNINDEXED, content);
        """)
        self._conn.commit()

    def _init_chroma(self) -> None:
        import chromadb
        self._vector_path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(self._vector_path))
        self._collection = client.get_or_create_collection("memories")

    def next_id(self) -> str:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTR(id, 5) AS INTEGER)), 0) + 1 FROM memories"
        ).fetchone()
        return f"MEM-{row[0]:03d}"

    def add(self, memory: Memory) -> Memory:
        self._conn.execute(
            """INSERT INTO memories
               (id, content, type, tags, feature_id, prd_id, plan_id, qa_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memory.id, memory.content, memory.type.value, json.dumps(memory.tags),
                memory.feature_id, memory.prd_id, memory.plan_id, memory.qa_id,
                memory.created_at.isoformat(), memory.updated_at.isoformat(),
            ),
        )
        self._conn.execute(
            "INSERT INTO memories_fts(id, content) VALUES (?, ?)",
            (memory.id, memory.content),
        )
        self._conn.commit()
        vector = self._ollama.embed(memory.content)
        self._collection.upsert(
            ids=[memory.id],
            embeddings=[vector],
            documents=[memory.content],
            metadatas=[{
                "type": memory.type.value,
                "tags": json.dumps(memory.tags),
                "feature_id": memory.feature_id or "",
                "prd_id": memory.prd_id or "",
                "plan_id": memory.plan_id or "",
                "qa_id": memory.qa_id or "",
            }],
        )
        return memory

    def get(self, id: str) -> Optional[Memory]:
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id = ?", (id,)
        ).fetchone()
        return self._row_to_memory(row) if row else None

    def list(
        self,
        type: Optional[MemoryType] = None,
        feature_id: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
    ) -> list[Memory]:
        query = "SELECT * FROM memories WHERE 1=1"
        params: list = []
        if type is not None:
            query += " AND type = ?"
            params.append(type.value)
        if feature_id is not None:
            query += " AND feature_id = ?"
            params.append(feature_id)
        if tag is not None:
            query += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_memory(r) for r in self._conn.execute(query, params).fetchall()]

    def search(self, query: str, limit: int = 5, feature_id: Optional[str] = None) -> list[Memory]:
        vector = self._ollama.embed(query)
        total = self._collection.count()
        if total == 0:
            return []
        n = min(limit, total)
        where = {"feature_id": {"$eq": feature_id}} if feature_id else None
        try:
            results = self._collection.query(
                query_embeddings=[vector],
                n_results=n,
                where=where,
            )
        except Exception:
            return []
        ids = results["ids"][0]
        return [m for id in ids if (m := self.get(id)) is not None]

    def delete(self, id: str) -> bool:
        if not self._conn.execute("SELECT id FROM memories WHERE id = ?", (id,)).fetchone():
            return False
        self._conn.execute("DELETE FROM memories WHERE id = ?", (id,))
        self._conn.execute("DELETE FROM memories_fts WHERE id = ?", (id,))
        self._conn.commit()
        try:
            self._collection.delete(ids=[id])
        except Exception:
            pass
        return True

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"],
            content=row["content"],
            type=MemoryType(row["type"]),
            tags=json.loads(row["tags"]),
            feature_id=row["feature_id"],
            prd_id=row["prd_id"],
            plan_id=row["plan_id"],
            qa_id=row["qa_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
```

- [ ] **Step 2: Verify MemoryStore imports cleanly**

```bash
python -c "from atlassian_cli.storage.memory_store import MemoryStore; print('MemoryStore imported OK')"
```

Expected output: `MemoryStore imported OK`

- [ ] **Step 3: Commit**

```bash
git add atlassian_cli/storage/memory_store.py
git commit -m "feat: add MemoryStore with SQLite + ChromaDB"
git push origin main
```

---

## Task 4: Memory Commands + Wire `main.py`

**Files:**
- Create: `atlassian_cli/commands/memory.py`
- Modify: `atlassian_cli/main.py`

- [ ] **Step 1: Create `atlassian_cli/commands/memory.py`**

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

app = typer.Typer(help="Manage project memory")
console = Console()


def _get_store() -> MemoryStore:
    settings = get_settings()
    return MemoryStore(
        db_path=settings.memory_db_path,
        vector_path=settings.memory_vector_path,
        ollama=OllamaClient(settings),
    )


@app.command("add")
def add(
    content: str = typer.Argument(..., help="Memory content"),
    type: MemoryType = typer.Option(MemoryType.note, "--type", help="Memory type"),
    tag: Optional[List[str]] = typer.Option(None, "--tag", help="Tag (repeatable)"),
    feature: Optional[str] = typer.Option(None, "--feature", help="e.g. FEAT-001"),
    prd: Optional[str] = typer.Option(None, "--prd", help="e.g. PRD-001"),
    plan: Optional[str] = typer.Option(None, "--plan", help="e.g. PLAN-001"),
    qa: Optional[str] = typer.Option(None, "--qa", help="e.g. QA-001"),
) -> None:
    store = _get_store()
    now = datetime.now(timezone.utc)
    memory = Memory(
        id=store.next_id(),
        content=content,
        type=type,
        tags=list(tag) if tag else [],
        feature_id=feature,
        prd_id=prd,
        plan_id=plan,
        qa_id=qa,
        created_at=now,
        updated_at=now,
    )
    try:
        store.add(memory)
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Memory saved  [{memory.id}]")


@app.command("show")
def show(id: str = typer.Argument(..., help="e.g. MEM-001")) -> None:
    store = _get_store()
    memory = store.get(id)
    if not memory:
        console.print(f"[red]✗[/red]  Memory [bold]{id}[/bold] not found")
        raise typer.Exit(1)
    lines = [
        f"[bold]Content:[/bold]  {memory.content}",
        f"[bold]Type:[/bold]     {memory.type.value}",
        f"[bold]Tags:[/bold]     {', '.join(memory.tags) or '—'}",
    ]
    if memory.feature_id:
        lines.append(f"[bold]Feature:[/bold]  {memory.feature_id}")
    if memory.prd_id:
        lines.append(f"[bold]PRD:[/bold]      {memory.prd_id}")
    if memory.plan_id:
        lines.append(f"[bold]Plan:[/bold]     {memory.plan_id}")
    if memory.qa_id:
        lines.append(f"[bold]QA:[/bold]       {memory.qa_id}")
    lines.append(f"[bold]Created:[/bold]  {memory.created_at.strftime('%Y-%m-%d %H:%M UTC')}")
    console.print(Panel("\n".join(lines), title=f"[cyan]{memory.id}[/cyan]"))


@app.command("list")
def list_memories(
    type: Optional[MemoryType] = typer.Option(None, "--type"),
    feature: Optional[str] = typer.Option(None, "--feature"),
    tag: Optional[str] = typer.Option(None, "--tag"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    store = _get_store()
    memories = store.list(type=type, feature_id=feature, tag=tag, limit=limit)
    if not memories:
        console.print("[dim]No memories found.[/dim]")
        return
    table = Table(show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Type")
    table.add_column("Content", max_width=60)
    table.add_column("Tags")
    table.add_column("Feature")
    table.add_column("Created")
    for m in memories:
        snippet = m.content[:57] + "..." if len(m.content) > 60 else m.content
        table.add_row(
            m.id,
            m.type.value,
            snippet,
            ", ".join(m.tags) or "—",
            m.feature_id or "—",
            m.created_at.strftime("%Y-%m-%d"),
        )
    console.print(table)


@app.command("search")
def search(
    query: str = typer.Argument(..., help="Search query"),
    feature: Optional[str] = typer.Option(None, "--feature"),
    limit: int = typer.Option(5, "--limit"),
) -> None:
    store = _get_store()
    try:
        memories = store.search(query, limit=limit, feature_id=feature)
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
    if not memories:
        console.print("[dim]No relevant memories found.[/dim]")
        return
    table = Table(show_lines=False)
    table.add_column("#", style="dim", justify="right")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Type")
    table.add_column("Content", max_width=60)
    table.add_column("Feature")
    for i, m in enumerate(memories, 1):
        snippet = m.content[:57] + "..." if len(m.content) > 60 else m.content
        table.add_row(str(i), m.id, m.type.value, snippet, m.feature_id or "—")
    console.print(table)


@app.command("delete")
def delete(id: str = typer.Argument(..., help="e.g. MEM-001")) -> None:
    store = _get_store()
    memory = store.get(id)
    if not memory:
        console.print(f"[red]✗[/red]  Memory [bold]{id}[/bold] not found")
        raise typer.Exit(1)
    snippet = memory.content[:60] + "..." if len(memory.content) > 60 else memory.content
    console.print(f"[dim]{snippet}[/dim]")
    if not typer.confirm(f"Delete {id}?", default=False):
        console.print("[dim]Cancelled.[/dim]")
        return
    store.delete(id)
    console.print(f"[green]✓[/green] Memory deleted  [{id}]")
```

- [ ] **Step 2: Register the memory sub-app in `atlassian_cli/main.py`**

Add the import and `add_typer` call. The full updated file:

```python
import sys
import typer

# Ensure stdout/stderr use UTF-8 on Windows so Rich can render Unicode symbols.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from atlassian_cli.commands import feature, prd, plan, qa, memory

app = typer.Typer(
    name="atlassian",
    help="AI-native Atlassian delivery CLI — operates as a tool for Claude Code.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(feature.app, name="feature")
app.add_typer(prd.app, name="prd")
app.add_typer(plan.app, name="plan")
app.add_typer(qa.app, name="qa")
app.add_typer(memory.app, name="memory")

if __name__ == "__main__":
    app()
```

- [ ] **Step 3: Verify help text shows memory commands**

```bash
atlassian memory --help
```

Expected output shows subcommands: `add`, `show`, `list`, `search`, `delete`

- [ ] **Step 4: Commit**

```bash
git add atlassian_cli/commands/memory.py atlassian_cli/main.py
git commit -m "feat: add memory commands (add/show/list/search/delete)"
git push origin main
```

---

## Task 5: README Update + Smoke Tests

**Files:**
- Modify: `README.md`

**Prerequisites:** Ollama must be running with `nomic-embed-text` pulled. Run once before smoke testing:
```bash
ollama pull nomic-embed-text
```

- [ ] **Step 1: Add memory section to README**

In `README.md`, add after the QA section and before `## Local storage`:

```markdown
### Memory

```bash
atlassian memory add "Chose JWT over sessions for stateless mobile auth" \
  --type decision --tag auth --feature FEAT-001

atlassian memory add "Auth service is temporarily using Redis fallback" \
  --type context --tag auth

atlassian memory list                        # all memories, newest first
atlassian memory list --type decision        # filter by type
atlassian memory list --feature FEAT-001     # filter by feature
atlassian memory list --tag auth             # filter by tag

atlassian memory search "authentication approach"   # semantic search
atlassian memory search "auth" --feature FEAT-001   # scoped to feature

atlassian memory show MEM-001               # full record in a panel
atlassian memory delete MEM-001             # prompts for confirmation
```

> `list` queries SQLite directly — no Ollama required.
> `add` and `search` require Ollama running with `nomic-embed-text` pulled (`ollama pull nomic-embed-text`).
```

Also update the local storage section to include the memory files:

```markdown
## Local storage

All data is stored at `~/.atlassian-cli/`:

```
~/.atlassian-cli/
├── features/    FEAT-001.json ...
├── prds/        PRD-001.json  ...
├── plans/       PLAN-001.json ...
├── qa/          QA-001.json   ...
├── memory.db    SQLite — full memory records
└── vectors/     ChromaDB — semantic search index
```
```

- [ ] **Step 2: Smoke test — add two memories**

With Ollama running:

```bash
atlassian memory add "Chose JWT over sessions for stateless mobile auth" --type decision --tag auth
```

Expected: `✓ Memory saved  [MEM-001]`

```bash
atlassian memory add "Auth service is temporarily using Redis fallback" --type context --tag auth
```

Expected: `✓ Memory saved  [MEM-002]`

- [ ] **Step 3: Smoke test — list**

```bash
atlassian memory list
```

Expected: Rich table showing MEM-002 and MEM-001 (newest first).

- [ ] **Step 4: Smoke test — show**

```bash
atlassian memory show MEM-001
```

Expected: Rich panel showing full content, type=decision, tags=[auth].

- [ ] **Step 5: Smoke test — search**

```bash
atlassian memory search "authentication approach"
```

Expected: Table with MEM-001 ranked first (JWT/sessions content matches "authentication approach").

- [ ] **Step 6: Smoke test — delete**

```bash
atlassian memory delete MEM-002
```

Expected: Shows content snippet, prompts `Delete MEM-002? [y/N]`. Enter `y`.
Expected: `✓ Memory deleted  [MEM-002]`

Verify it's gone:

```bash
atlassian memory list
```

Expected: only MEM-001 in the table.

- [ ] **Step 7: Smoke test — not-found error**

```bash
atlassian memory show MEM-999
```

Expected: `✗  Memory MEM-999 not found` and exit code 1.

- [ ] **Step 8: Commit**

```bash
git add README.md
git commit -m "docs: add memory commands to README, update local storage section"
git push origin main
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| `memory add` with type/tags/feature/prd/plan/qa links | Task 4 `add` command |
| `memory search` — semantic via ChromaDB → SQLite | Task 3 `search()`, Task 4 `search` command |
| `memory list` — structured SQLite, no Ollama needed | Task 3 `list()`, Task 4 `list_memories` command |
| `memory show` — full panel with all metadata | Task 4 `show` command |
| `memory delete` — confirmation prompt, both stores | Task 3 `delete()`, Task 4 `delete` command |
| SQLite schema with FTS5 virtual table | Task 3 `_init_db()` |
| ChromaDB persistent collection | Task 3 `_init_chroma()` |
| `Memory` Pydantic model with `MemoryType` enum | Task 1 |
| `embed()` on `OllamaClient` via `/api/embeddings` | Task 2 |
| `memory_vector_path`, `ollama_embed_model` config | Task 1 |
| `chromadb>=0.4` dependency | Task 1 |
| `.env.example` documentation | Task 1 |
| `main.py` wiring | Task 4 |
| Error: Ollama unreachable → exit 1 | Task 4 `add` + `search` commands |
| Error: ID not found → exit 1 | Task 4 `show` + `delete` commands |
| `next_id()` — MEM-001, MEM-002, ... | Task 3 |
| README updated | Task 5 |

All spec requirements covered. No gaps found.
