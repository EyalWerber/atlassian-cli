# atlassian-cli Phase 4a Design — Memory Subsystem

**Date:** 2026-06-13
**Status:** Approved
**Author:** Claude Code + Eyal Werber

---

## Overview

Phase 4a adds a **persistent memory subsystem** so Claude Code accumulates project knowledge across sessions. Memories are structured records (decisions, context, notes) stored in SQLite for structured queries and ChromaDB for semantic (vector) search. Ollama generates the vector embeddings locally.

This is the foundation layer for Phase 4b (ADR system) and Phase 4c (CLAUDE.md automation), which will write into and read from this store.

---

## Core Concept

Without memory, every Claude Code session starts from zero — re-reading the codebase, re-deriving decisions, losing context. With memory:

```bash
atlassian memory add "Chose JWT over sessions for stateless mobile auth" \
  --type decision --feature FEAT-001 --tag auth

# weeks later, new session:
atlassian memory search "authentication approach"
# → finds the above memory by meaning, not by keyword match
```

CLAUDE.md (Phase 4c) will be a committed, human-triggered snapshot generated from this store — not auto-updating. Claude Code reads it at session start; humans regenerate it when it goes stale.

---

## Scale Boundary

This design targets teams up to ~20 developers and projects up to a few hundred features. Beyond that, the SQLite/ChromaDB local store would need to be replaced with a backend service — but the `MemoryStore` interface is designed so that swap is a storage-layer change only, not a command change.

---

## New Files

| Action | Path | Responsibility |
|---|---|---|
| Create | `atlassian_cli/models/memory.py` | `Memory`, `MemoryType` Pydantic models |
| Create | `atlassian_cli/storage/memory_store.py` | `MemoryStore` — owns SQLite + ChromaDB |
| Create | `atlassian_cli/commands/memory.py` | `atlassian memory add/search/list/show/delete` |

**Existing files touched:**

| File | Change |
|---|---|
| `atlassian_cli/integrations/ollama.py` | Add `embed(text) -> list[float]` method |
| `atlassian_cli/config.py` | Add `memory_vector_path`, `ollama_embed_model` |
| `atlassian_cli/main.py` | `app.add_typer(memory.app, name="memory")` |
| `.env.example` | Document new optional vars |

---

## Data Models (`models/memory.py`)

```python
class MemoryType(str, Enum):
    decision = "decision"   # why something was built a certain way
    context  = "context"    # current state, blockers, in-progress info
    note     = "note"       # free-form

class Memory(BaseModel):
    id: str                           # MEM-001
    content: str                      # the memory text
    type: MemoryType = MemoryType.note
    tags: list[str] = []
    feature_id: Optional[str] = None
    prd_id:     Optional[str] = None
    plan_id:    Optional[str] = None
    qa_id:      Optional[str] = None
    created_at: datetime
    updated_at: datetime
```

`Memory` is the only model in this phase. Memories are not stored as JSON files — they live in SQLite. The Pydantic model is used for validation and serialisation between layers only.

---

## Storage (`storage/memory_store.py`)

`MemoryStore` is the single interface to both databases. Commands never touch SQLite or ChromaDB directly.

### SQLite schema

```sql
CREATE TABLE IF NOT EXISTS memories (
    id         TEXT PRIMARY KEY,
    content    TEXT NOT NULL,
    type       TEXT NOT NULL DEFAULT 'note',
    tags       TEXT NOT NULL DEFAULT '[]',   -- JSON-encoded list[str]
    feature_id TEXT,
    prd_id     TEXT,
    plan_id    TEXT,
    qa_id      TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
    USING fts5(id UNINDEXED, content);
```

### ChromaDB

- One persistent collection named `"memories"`
- Document = `memory.content`
- ID = `memory.id` (e.g. `"MEM-001"`)
- Metadata mirrors all structured fields for vector-level filtering:
  `{"type": "decision", "feature_id": "FEAT-001", "tags": "[\"auth\"]", ...}`

### Public interface

```python
class MemoryStore:
    def __init__(self, db_path: str, vector_path: str, ollama: OllamaClient): ...

    def add(self, memory: Memory) -> Memory:
        # INSERT into SQLite
        # embed content via ollama.embed()
        # upsert into ChromaDB

    def search(self, query: str, limit: int = 5, **filters) -> list[Memory]:
        # embed query via ollama.embed()
        # query ChromaDB (with optional metadata filters)
        # fetch full records from SQLite by returned IDs

    def list(self, type: Optional[MemoryType] = None,
             feature_id: Optional[str] = None,
             tag: Optional[str] = None,
             limit: int = 50) -> list[Memory]:
        # structured SELECT from SQLite

    def get(self, id: str) -> Optional[Memory]:
        # SELECT from SQLite by ID

    def delete(self, id: str) -> bool:
        # DELETE from SQLite
        # delete from ChromaDB by ID
        # returns False if ID not found

    def next_id(self) -> str:
        # SELECT MAX numeric suffix → "MEM-001", "MEM-002", ...
```

Both databases are initialised (tables created, collection created) in `__init__` on first use.

---

## Ollama Integration (`integrations/ollama.py` addition)

New method on `OllamaClient`:

```python
def embed(self, text: str) -> list[float]:
    # POST {host}/api/embeddings
    # model = settings.ollama_embed_model (default: "nomic-embed-text")
    # returns list[float] (768 dimensions for nomic-embed-text)
    # raises RuntimeError on connection error or unexpected response
```

This is a separate Ollama endpoint (`/api/embeddings`) from the chat endpoint (`/api/chat`) used in Phases 2–3.

---

## Commands (`commands/memory.py`)

### `atlassian memory add`

```bash
atlassian memory add "<content>" \
  [--type decision|context|note] \
  [--tag TAG ...]            \   # repeatable
  [--feature FEAT-001]       \
  [--prd PRD-001]            \
  [--plan PLAN-001]          \
  [--qa QA-001]
```

- Saves immediately — no confirmation, no `--save` flag
- Prints: `✓ Memory saved  [MEM-001]`

### `atlassian memory search`

```bash
atlassian memory search "<query>" [--feature FEAT-001] [--limit 5]
```

- Semantic search via ChromaDB → fetch from SQLite
- Output: Rich table with columns `Rank | ID | Type | Content (snippet) | Links`
- If Ollama unreachable: exit 1 with friendly error

### `atlassian memory list`

```bash
atlassian memory list [--type decision|context|note] \
                      [--feature FEAT-001] \
                      [--tag auth] \
                      [--limit 20]
```

- Structured SQLite query — no Ollama required
- Output: Rich table `ID | Type | Tags | Content (snippet) | Feature | Created`

### `atlassian memory show`

```bash
atlassian memory show MEM-001
```

- Output: Rich panel with full content + all metadata

### `atlassian memory delete`

```bash
atlassian memory delete MEM-001
```

- Prompts `Delete MEM-001? [y/N]` before proceeding
- Removes from both SQLite and ChromaDB
- Prints: `✓ Memory deleted  [MEM-001]`

---

## Configuration

Two new settings added to `Settings` in `config.py`:

| Variable | Default | Purpose |
|---|---|---|
| `MEMORY_DB_PATH` | `~/.atlassian-cli/memory.db` | SQLite file ← **already present** |
| `MEMORY_VECTOR_PATH` | `~/.atlassian-cli/vectors/` | ChromaDB persistence directory |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model name |

`.env.example` addition:
```env
# --- Phase 4 (Memory) ---
# MEMORY_DB_PATH=~/.atlassian-cli/memory.db
# MEMORY_VECTOR_PATH=~/.atlassian-cli/vectors/
# OLLAMA_EMBED_MODEL=nomic-embed-text
```

**One-time user setup** before first use:
```bash
ollama pull nomic-embed-text
```

Both the SQLite DB and ChromaDB directory are auto-created on first `memory add`.

---

## New pip dependencies

| Package | Purpose |
|---|---|
| `chromadb>=0.4` | Embedded vector store |

No server required — ChromaDB runs in-process, persists to `~/.atlassian-cli/vectors/`.

---

## Error Handling

| Condition | Behavior |
|---|---|
| Ollama unreachable on `add` | Exit 1: "Ollama not available at \<host\>. Is it running?" |
| Ollama unreachable on `search` | Exit 1 with same message |
| `memory show` / `delete` ID not found | Exit 1: "Memory MEM-001 not found." |
| ChromaDB / SQLite init failure | Exit 1 with error details |
| `list` returns empty | Print `[dim]No memories found.[/dim]` |

`memory list` does NOT require Ollama — it queries SQLite directly.

---

## Out of Scope for Phase 4a

- Auto-updating CLAUDE.md on every `memory add`
- Memory expiry / TTL
- Shared/remote memory store (multi-user, Phase 5+)
- Ollama summarisation of old memories ("epoch summaries")
- Exporting memories to Confluence
- Editing existing memories (delete + re-add)

---

## Phase Roadmap (updated)

| Phase | Scope |
|---|---|
| **1 ✓** | CLI framework, Atlassian integration, PRD management, Confluence publishing |
| **2 ✓** | Ollama planning agent, Jira Epic/Story/Task decomposition |
| **3 ✓** | QA planning, Playwright integration, Jira bug filing with attachments |
| **4a (this doc)** | Memory subsystem — SQLite + ChromaDB + Ollama embeddings |
| **4b** | ADR system — formal decision records → memory + Confluence |
| **4c** | CLAUDE.md automation — curated briefing from memory + project state |
| **5** | Autonomous workflows, Docker, CI/CD agent mode |
