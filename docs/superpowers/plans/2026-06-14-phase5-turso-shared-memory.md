# Phase 5: Turso Shared Memory Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional Turso backend so teams can share memories across machines, while local SQLite remains the default and always works offline.

**Architecture:** `MEMORY_BACKEND=local` (default) keeps the existing SQLite + ChromaDB store. `MEMORY_BACKEND=turso` routes all memory reads/writes directly to Turso (libsql). In either mode, three new commands are available when `TURSO_URL` is set: `push` (local→Turso), `pull` (Turso→local + re-embed), and `status` (shows which backend is active, counts, and connectivity). ChromaDB always stays local for fast semantic search.

**Tech Stack:** Python 3.10+, Typer, Rich, Pydantic v2, libsql-experimental (Turso Python SDK), existing MemoryStore/LocalStorage/OllamaClient infrastructure, pytest 8.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `atlassian_cli/config.py` | Add `memory_backend`, `turso_url`, `turso_auth_token` |
| Modify | `atlassian_cli/integrations/ollama.py` | Add `ping() -> bool` |
| Modify | `atlassian_cli/storage/memory_store.py` | Turso mode, `_rows()/_row()` helpers, `push_to_turso()`, `pull_from_turso()`, `sync_vectors()` |
| Modify | `atlassian_cli/commands/memory.py` | Update `_get_store()`, add `status`, `push`, `pull` commands |
| Modify | `atlassian_cli/commands/qa.py` | Pass turso config to MemoryStore |
| Modify | `atlassian_cli/commands/adr.py` | Pass turso config to MemoryStore |
| Modify | `pyproject.toml` | Add `libsql-experimental` dependency |
| Modify | `.env.example` | Document new env vars |
| Modify | `README.md` | Document backend modes + new commands |
| Create | `tests/test_phase5.py` | All Phase 5 tests |

---

## Task 1: Config + MemoryStore Turso mode

**Files:**
- Modify: `atlassian_cli/config.py`
- Modify: `atlassian_cli/integrations/ollama.py`
- Modify: `atlassian_cli/storage/memory_store.py`
- Modify: `atlassian_cli/commands/qa.py`
- Modify: `atlassian_cli/commands/adr.py`
- Modify: `pyproject.toml`
- Create: `tests/test_phase5.py`

- [ ] **Step 1: Write failing tests in `tests/test_phase5.py`**

```python
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from atlassian_cli.storage.local import LocalStorage


# ──────────────────────────────────────────────
# Task 1: Config + MemoryStore Turso mode
# ──────────────────────────────────────────────

class TestConfig:
    def test_memory_backend_defaults_to_local(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ATLASSIAN_URL", "https://x.atlassian.net")
        monkeypatch.setenv("ATLASSIAN_EMAIL", "a@b.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
        monkeypatch.setenv("JIRA_PROJECT", "TEST")
        monkeypatch.setenv("CONFLUENCE_SPACE", "DEV")
        monkeypatch.delenv("MEMORY_BACKEND", raising=False)

        from atlassian_cli.config import Settings
        s = Settings()
        assert s.memory_backend == "local"
        assert s.turso_url is None
        assert s.turso_auth_token is None

    def test_turso_settings_read_from_env(self, monkeypatch):
        monkeypatch.setenv("ATLASSIAN_URL", "https://x.atlassian.net")
        monkeypatch.setenv("ATLASSIAN_EMAIL", "a@b.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
        monkeypatch.setenv("JIRA_PROJECT", "TEST")
        monkeypatch.setenv("CONFLUENCE_SPACE", "DEV")
        monkeypatch.setenv("MEMORY_BACKEND", "turso")
        monkeypatch.setenv("TURSO_URL", "libsql://my-db.turso.io")
        monkeypatch.setenv("TURSO_AUTH_TOKEN", "my-token")

        from atlassian_cli.config import Settings
        s = Settings()
        assert s.memory_backend == "turso"
        assert s.turso_url == "libsql://my-db.turso.io"
        assert s.turso_auth_token == "my-token"


class TestOllamaClientPing:
    def test_ping_returns_true_when_ollama_up(self, monkeypatch):
        from atlassian_cli.integrations.ollama import OllamaClient
        mock_settings = MagicMock()
        mock_settings.ollama_host = "http://localhost:11434"
        mock_settings.ollama_model = "llama3.2"
        mock_settings.ollama_embed_model = "nomic-embed-text"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        monkeypatch.setattr("atlassian_cli.integrations.ollama.requests.get", lambda *a, **kw: mock_resp)

        client = OllamaClient(mock_settings)
        assert client.ping() is True

    def test_ping_returns_false_when_ollama_down(self, monkeypatch):
        import requests as req
        from atlassian_cli.integrations.ollama import OllamaClient
        mock_settings = MagicMock()
        mock_settings.ollama_host = "http://localhost:11434"
        mock_settings.ollama_model = "llama3.2"
        mock_settings.ollama_embed_model = "nomic-embed-text"

        def raise_conn(*a, **kw):
            raise req.exceptions.ConnectionError()
        monkeypatch.setattr("atlassian_cli.integrations.ollama.requests.get", raise_conn)

        client = OllamaClient(mock_settings)
        assert client.ping() is False


class TestMemoryStoreLocalMode:
    def test_local_mode_is_default(self, tmp_path):
        from atlassian_cli.storage.memory_store import MemoryStore
        mock_ollama = MagicMock()
        store = MemoryStore(
            db_path=str(tmp_path / "mem.db"),
            vector_path=str(tmp_path / "vectors"),
            ollama=mock_ollama,
        )
        assert not store._is_turso

    def test_local_mode_add_and_list(self, tmp_path):
        from atlassian_cli.storage.memory_store import MemoryStore
        from atlassian_cli.models.memory import Memory, MemoryType
        mock_ollama = MagicMock()
        mock_ollama.embed.return_value = [0.1] * 768
        store = MemoryStore(
            db_path=str(tmp_path / "mem.db"),
            vector_path=str(tmp_path / "vectors"),
            ollama=mock_ollama,
        )
        now = datetime.now(timezone.utc)
        mem = Memory(id="MEM-001", content="test", type=MemoryType.note,
                     tags=[], created_at=now, updated_at=now)
        store.add(mem)
        results = store.list()
        assert len(results) == 1
        assert results[0].id == "MEM-001"


class TestMemoryStoreTursoMode:
    def test_turso_mode_calls_libsql_connect(self, tmp_path, monkeypatch):
        mock_libsql = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value = MagicMock(fetchone=lambda: (1,), fetchall=lambda: [], description=[])
        mock_libsql.connect.return_value = mock_conn
        monkeypatch.setattr("atlassian_cli.storage.memory_store.libsql", mock_libsql)

        from atlassian_cli.storage.memory_store import MemoryStore
        mock_ollama = MagicMock()
        store = MemoryStore(
            db_path=str(tmp_path / "mem.db"),
            vector_path=str(tmp_path / "vectors"),
            ollama=mock_ollama,
            turso_url="libsql://my-db.turso.io",
            turso_auth_token="my-token",
        )
        mock_libsql.connect.assert_called_once_with(
            database="libsql://my-db.turso.io",
            auth_token="my-token",
        )
        assert store._is_turso


class TestPushToTurso:
    def test_push_uploads_only_new_memories(self, tmp_path, monkeypatch):
        from atlassian_cli.storage.memory_store import MemoryStore
        from atlassian_cli.models.memory import Memory, MemoryType
        mock_ollama = MagicMock()
        mock_ollama.embed.return_value = [0.1] * 768
        store = MemoryStore(
            db_path=str(tmp_path / "mem.db"),
            vector_path=str(tmp_path / "vectors"),
            ollama=mock_ollama,
        )
        now = datetime.now(timezone.utc)
        for i in range(1, 3):
            store.add(Memory(
                id=f"MEM-00{i}", content=f"memory {i}", type=MemoryType.note,
                tags=[], created_at=now, updated_at=now,
            ))

        # Remote already has MEM-001
        mock_remote = MagicMock()
        mock_remote.execute.return_value = MagicMock(
            fetchall=lambda: [("MEM-001",)],
            description=[("id",)],
        )
        mock_libsql = MagicMock()
        mock_libsql.connect.return_value = mock_remote
        monkeypatch.setattr("atlassian_cli.storage.memory_store.libsql", mock_libsql)

        count = store.push_to_turso("libsql://db.turso.io", "token")

        assert count == 1  # Only MEM-002 is new
        # Verify INSERT was called for MEM-002
        insert_calls = [c for c in mock_remote.execute.call_args_list
                        if "INSERT" in str(c)]
        assert len(insert_calls) == 1

    def test_push_returns_zero_when_all_synced(self, tmp_path, monkeypatch):
        from atlassian_cli.storage.memory_store import MemoryStore
        from atlassian_cli.models.memory import Memory, MemoryType
        mock_ollama = MagicMock()
        mock_ollama.embed.return_value = [0.1] * 768
        store = MemoryStore(
            db_path=str(tmp_path / "mem.db"),
            vector_path=str(tmp_path / "vectors"),
            ollama=mock_ollama,
        )
        now = datetime.now(timezone.utc)
        store.add(Memory(id="MEM-001", content="test", type=MemoryType.note,
                         tags=[], created_at=now, updated_at=now))

        mock_remote = MagicMock()
        mock_remote.execute.return_value = MagicMock(
            fetchall=lambda: [("MEM-001",)],
            description=[("id",)],
        )
        mock_libsql = MagicMock()
        mock_libsql.connect.return_value = mock_remote
        monkeypatch.setattr("atlassian_cli.storage.memory_store.libsql", mock_libsql)

        count = store.push_to_turso("libsql://db.turso.io", "token")
        assert count == 0


class TestPullFromTurso:
    def test_pull_inserts_new_remote_memories(self, tmp_path, monkeypatch):
        from atlassian_cli.storage.memory_store import MemoryStore
        from atlassian_cli.models.memory import Memory, MemoryType
        mock_ollama = MagicMock()
        mock_ollama.embed.return_value = [0.1] * 768
        store = MemoryStore(
            db_path=str(tmp_path / "mem.db"),
            vector_path=str(tmp_path / "vectors"),
            ollama=mock_ollama,
        )
        now = datetime.now(timezone.utc).isoformat()

        # Remote has MEM-001 and MEM-002; local has MEM-001
        store_now = datetime.now(timezone.utc)
        store.add(Memory(id="MEM-001", content="existing", type=MemoryType.note,
                         tags=[], created_at=store_now, updated_at=store_now))

        remote_row = ("MEM-002", "new memory", "note", "[]", None, None, None, None, now, now)
        mock_cursor = MagicMock()
        mock_cursor.description = [
            ("id",), ("content",), ("type",), ("tags",),
            ("feature_id",), ("prd_id",), ("plan_id",), ("qa_id",),
            ("created_at",), ("updated_at",),
        ]
        mock_cursor.fetchall.return_value = [remote_row]
        mock_remote = MagicMock()
        mock_remote.execute.return_value = mock_cursor
        mock_libsql = MagicMock()
        mock_libsql.connect.return_value = mock_remote
        monkeypatch.setattr("atlassian_cli.storage.memory_store.libsql", mock_libsql)

        count = store.pull_from_turso("libsql://db.turso.io", "token")

        assert count == 1
        assert store.get("MEM-002") is not None
        assert store.get("MEM-002").content == "new memory"


class TestSyncVectors:
    def test_sync_vectors_embeds_missing(self, tmp_path):
        from atlassian_cli.storage.memory_store import MemoryStore
        from atlassian_cli.models.memory import Memory, MemoryType
        mock_ollama = MagicMock()
        mock_ollama.embed.return_value = [0.1] * 768
        store = MemoryStore(
            db_path=str(tmp_path / "mem.db"),
            vector_path=str(tmp_path / "vectors"),
            ollama=mock_ollama,
        )
        now = datetime.now(timezone.utc)
        store.add(Memory(id="MEM-001", content="first", type=MemoryType.note,
                         tags=[], created_at=now, updated_at=now))
        store.add(Memory(id="MEM-002", content="second", type=MemoryType.note,
                         tags=[], created_at=now, updated_at=now))

        # Manually remove MEM-002 from ChromaDB to simulate it being missing
        store._collection.delete(ids=["MEM-002"])
        assert store._collection.count() == 1

        count = store.sync_vectors()
        assert count == 1
        assert store._collection.count() == 2

    def test_sync_vectors_returns_zero_when_all_synced(self, tmp_path):
        from atlassian_cli.storage.memory_store import MemoryStore
        from atlassian_cli.models.memory import Memory, MemoryType
        mock_ollama = MagicMock()
        mock_ollama.embed.return_value = [0.1] * 768
        store = MemoryStore(
            db_path=str(tmp_path / "mem.db"),
            vector_path=str(tmp_path / "vectors"),
            ollama=mock_ollama,
        )
        now = datetime.now(timezone.utc)
        store.add(Memory(id="MEM-001", content="synced", type=MemoryType.note,
                         tags=[], created_at=now, updated_at=now))

        count = store.sync_vectors()
        assert count == 0
```

- [ ] **Step 2: Run tests — expect failures**

```bash
pytest tests/test_phase5.py -v
```

Expected: multiple failures — `memory_backend` not in Settings, `ping()` not on OllamaClient, `_is_turso` not on MemoryStore, etc.

- [ ] **Step 3: Add Turso config to `atlassian_cli/config.py`**

Add `from typing import Optional` at the top, then add three optional fields to `Settings`:

```python
from typing import Optional
from pydantic import ValidationError, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
import typer
from rich.console import Console
from rich.table import Table


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    atlassian_url: str
    atlassian_email: str
    atlassian_api_token: SecretStr
    jira_project: str
    confluence_space: str

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    memory_db_path: str = "~/.atlassian-cli/memory.db"
    memory_vector_path: str = "~/.atlassian-cli/vectors/"
    ollama_embed_model: str = "nomic-embed-text"
    qa_base_url: str = ""

    memory_backend: str = "local"
    turso_url: Optional[str] = None
    turso_auth_token: Optional[str] = None
```

- [ ] **Step 4: Add `ping()` to `atlassian_cli/integrations/ollama.py`**

Add after the `embed()` method (at the end of the class):

```python
    def ping(self) -> bool:
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=3)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
```

- [ ] **Step 5: Update `atlassian_cli/storage/memory_store.py`**

Replace the entire file with:

```python
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import libsql_experimental as libsql
except ImportError:
    libsql = None  # type: ignore[assignment]

from atlassian_cli.integrations.ollama import OllamaClient
from atlassian_cli.models.memory import Memory, MemoryType


class MemoryStore:
    def __init__(
        self,
        db_path: str,
        vector_path: str,
        ollama: OllamaClient,
        turso_url: Optional[str] = None,
        turso_auth_token: Optional[str] = None,
    ):
        self._ollama = ollama
        self._is_turso = bool(turso_url)

        if self._is_turso:
            if libsql is None:
                raise RuntimeError(
                    "libsql-experimental is required for Turso mode. "
                    "Run: pip install libsql-experimental"
                )
            self._conn = libsql.connect(
                database=turso_url,
                auth_token=turso_auth_token,
            )
        else:
            self._db_path = Path(db_path).expanduser()
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row

        self._vector_path = Path(vector_path).expanduser()
        self._init_db()
        self._init_chroma()

    def _init_db(self) -> None:
        create_memories = """
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
            )
        """
        if self._is_turso:
            self._conn.execute(create_memories)
            self._conn.commit()
        else:
            self._conn.executescript(f"""
                {create_memories};
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                    USING fts5(id UNINDEXED, content);
            """)
            self._conn.commit()

    def _init_chroma(self) -> None:
        import chromadb
        self._vector_path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(self._vector_path))
        self._collection = client.get_or_create_collection("memories")

    def _rows(self, query: str, params: tuple = ()) -> list:
        cursor = self._conn.execute(query, params)
        if self._is_turso:
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        return cursor.fetchall()

    def _row(self, query: str, params: tuple = ()) -> Optional[dict]:
        cursor = self._conn.execute(query, params)
        if self._is_turso:
            cols = [d[0] for d in cursor.description]
            row = cursor.fetchone()
            return dict(zip(cols, row)) if row else None
        return cursor.fetchone()

    def next_id(self) -> str:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTR(id, 5) AS INTEGER)), 0) + 1 FROM memories"
        ).fetchone()
        return f"MEM-{row[0]:03d}"

    def add(self, memory: Memory) -> Memory:
        vector = self._ollama.embed(memory.content)
        metadata = {
            "type": memory.type.value,
            "tags": json.dumps(memory.tags),
            "feature_id": memory.feature_id or "",
            "prd_id": memory.prd_id or "",
            "plan_id": memory.plan_id or "",
            "qa_id": memory.qa_id or "",
        }
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
        if not self._is_turso:
            self._conn.execute(
                "INSERT INTO memories_fts(id, content) VALUES (?, ?)",
                (memory.id, memory.content),
            )
        self._collection.upsert(
            ids=[memory.id],
            embeddings=[vector],
            documents=[memory.content],
            metadatas=[metadata],
        )
        self._conn.commit()
        return memory

    def get(self, id: str) -> Optional[Memory]:
        row = self._row("SELECT * FROM memories WHERE id = ?", (id,))
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
            escaped = tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query += ' AND tags LIKE ? ESCAPE "\\"'
            params.append(f'%"{escaped}"%')
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_memory(r) for r in self._rows(query, tuple(params))]

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
        if not self._is_turso:
            self._conn.execute("DELETE FROM memories_fts WHERE id = ?", (id,))
        self._conn.commit()
        try:
            self._collection.delete(ids=[id])
        except Exception:
            pass
        return True

    def push_to_turso(self, turso_url: str, turso_auth_token: str) -> int:
        if libsql is None:
            raise RuntimeError(
                "libsql-experimental is required: pip install libsql-experimental"
            )
        remote = libsql.connect(database=turso_url, auth_token=turso_auth_token)
        remote.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY, content TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'note', tags TEXT NOT NULL DEFAULT '[]',
                feature_id TEXT, prd_id TEXT, plan_id TEXT, qa_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        remote.commit()

        remote_ids = {row[0] for row in remote.execute("SELECT id FROM memories").fetchall()}
        local_memories = self.list(limit=100_000)

        count = 0
        for mem in local_memories:
            if mem.id not in remote_ids:
                remote.execute(
                    "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (mem.id, mem.content, mem.type.value, json.dumps(mem.tags),
                     mem.feature_id, mem.prd_id, mem.plan_id, mem.qa_id,
                     mem.created_at.isoformat(), mem.updated_at.isoformat()),
                )
                count += 1
        if count:
            remote.commit()
        return count

    def pull_from_turso(self, turso_url: str, turso_auth_token: str) -> int:
        if libsql is None:
            raise RuntimeError(
                "libsql-experimental is required: pip install libsql-experimental"
            )
        remote = libsql.connect(database=turso_url, auth_token=turso_auth_token)
        cursor = remote.execute("SELECT * FROM memories")
        cols = [d[0] for d in cursor.description]
        remote_rows = [dict(zip(cols, row)) for row in cursor.fetchall()]

        local_ids = {row[0] for row in self._conn.execute("SELECT id FROM memories").fetchall()}

        count = 0
        for row in remote_rows:
            if row["id"] not in local_ids:
                self._conn.execute(
                    "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (row["id"], row["content"], row["type"], row["tags"],
                     row["feature_id"], row["prd_id"], row["plan_id"], row["qa_id"],
                     row["created_at"], row["updated_at"]),
                )
                if not self._is_turso:
                    self._conn.execute(
                        "INSERT INTO memories_fts(id, content) VALUES (?, ?)",
                        (row["id"], row["content"]),
                    )
                vector = self._ollama.embed(row["content"])
                tags_raw = row["tags"] if isinstance(row["tags"], str) else json.dumps(row["tags"])
                self._collection.upsert(
                    ids=[row["id"]],
                    embeddings=[vector],
                    documents=[row["content"]],
                    metadatas=[{
                        "type": row["type"], "tags": tags_raw,
                        "feature_id": row["feature_id"] or "",
                        "prd_id": row["prd_id"] or "",
                        "plan_id": row["plan_id"] or "",
                        "qa_id": row["qa_id"] or "",
                    }],
                )
                count += 1
        if count:
            self._conn.commit()
        return count

    def sync_vectors(self) -> int:
        all_memories = self.list(limit=100_000)
        existing_ids = set(self._collection.get()["ids"])
        count = 0
        for mem in all_memories:
            if mem.id not in existing_ids:
                vector = self._ollama.embed(mem.content)
                self._collection.upsert(
                    ids=[mem.id],
                    embeddings=[vector],
                    documents=[mem.content],
                    metadatas=[{
                        "type": mem.type.value,
                        "tags": json.dumps(mem.tags),
                        "feature_id": mem.feature_id or "",
                        "prd_id": mem.prd_id or "",
                        "plan_id": mem.plan_id or "",
                        "qa_id": mem.qa_id or "",
                    }],
                )
                count += 1
        return count

    def _row_to_memory(self, row) -> Memory:
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

- [ ] **Step 6: Update MemoryStore callers in `atlassian_cli/commands/memory.py`**

In the existing `_get_store()` function, replace:

```python
def _get_store() -> MemoryStore:
    settings = get_settings()
    try:
        return MemoryStore(
            db_path=settings.memory_db_path,
            vector_path=settings.memory_vector_path,
            ollama=OllamaClient(settings),
        )
    except Exception as e:
        console.print(f"[red]✗[/red]  Failed to initialize memory store: {e}")
        raise typer.Exit(1)
```

With:

```python
def _get_store() -> MemoryStore:
    settings = get_settings()
    try:
        return MemoryStore(
            db_path=settings.memory_db_path,
            vector_path=settings.memory_vector_path,
            ollama=OllamaClient(settings),
            turso_url=settings.turso_url if settings.memory_backend == "turso" else None,
            turso_auth_token=settings.turso_auth_token if settings.memory_backend == "turso" else None,
        )
    except Exception as e:
        console.print(f"[red]✗[/red]  Failed to initialize memory store: {e}")
        raise typer.Exit(1)
```

- [ ] **Step 7: Update MemoryStore instantiation in `atlassian_cli/commands/qa.py`**

In the `bug()` function, find the block:
```python
            mem_store = MemoryStore(
                db_path=settings.memory_db_path,
                vector_path=settings.memory_vector_path,
                ollama=OllamaClient(settings),
            )
```

Replace with:
```python
            mem_store = MemoryStore(
                db_path=settings.memory_db_path,
                vector_path=settings.memory_vector_path,
                ollama=OllamaClient(settings),
                turso_url=settings.turso_url if settings.memory_backend == "turso" else None,
                turso_auth_token=settings.turso_auth_token if settings.memory_backend == "turso" else None,
            )
```

- [ ] **Step 8: Update MemoryStore instantiation in `atlassian_cli/commands/adr.py`**

In the `add()` function, find:
```python
        mem_store = MemoryStore(
            db_path=settings.memory_db_path,
            vector_path=settings.memory_vector_path,
            ollama=OllamaClient(settings),
        )
```

Replace with:
```python
        mem_store = MemoryStore(
            db_path=settings.memory_db_path,
            vector_path=settings.memory_vector_path,
            ollama=OllamaClient(settings),
            turso_url=settings.turso_url if settings.memory_backend == "turso" else None,
            turso_auth_token=settings.turso_auth_token if settings.memory_backend == "turso" else None,
        )
```

- [ ] **Step 9: Add `libsql-experimental` to `pyproject.toml`**

In the `dependencies` list, add after `"chromadb>=0.4"`:

```toml
    "libsql-experimental>=0.0.9",
```

- [ ] **Step 10: Run tests — expect all pass**

```bash
pytest tests/test_phase5.py -v
```

Expected: all Task 1 tests pass (12 tests).

- [ ] **Step 11: Run full test suite**

```bash
pytest tests/ -v
```

Expected: 34 passed (22 existing + 12 new).

- [ ] **Step 12: Commit**

```bash
git add atlassian_cli/config.py atlassian_cli/integrations/ollama.py atlassian_cli/storage/memory_store.py atlassian_cli/commands/memory.py atlassian_cli/commands/qa.py atlassian_cli/commands/adr.py pyproject.toml tests/test_phase5.py
git commit -m "feat(5): Turso mode for MemoryStore + ping() + push/pull/sync_vectors methods"
git push origin main
```

---

## Task 2: status, push, pull commands

**Files:**
- Modify: `atlassian_cli/commands/memory.py`
- Modify: `tests/test_phase5.py`

- [ ] **Step 1: Append Task 2 tests to `tests/test_phase5.py`**

Append after the existing test classes:

```python
# ──────────────────────────────────────────────
# Task 2: status / push / pull commands
# ──────────────────────────────────────────────

class TestStatusCommand:
    def _base_patches(self, monkeypatch, tmp_path, backend="local", turso_url=None):
        monkeypatch.setattr(
            "atlassian_cli.commands.memory.LocalStorage",
            lambda: LocalStorage(base_dir=tmp_path),
        )
        mock_settings = MagicMock()
        mock_settings.memory_backend = backend
        mock_settings.turso_url = turso_url
        mock_settings.turso_auth_token = "token" if turso_url else None
        mock_settings.memory_db_path = str(tmp_path / "mem.db")
        mock_settings.memory_vector_path = str(tmp_path / "vectors")
        mock_settings.ollama_host = "http://localhost:11434"
        monkeypatch.setattr("atlassian_cli.commands.memory.get_settings", lambda: mock_settings)
        return mock_settings

    def test_status_local_mode_shows_local_info(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import memory as mem_cmd
        self._base_patches(monkeypatch, tmp_path, backend="local")

        # Create local DB with 2 memories
        db = sqlite3.connect(str(tmp_path / "mem.db"))
        db.execute("""CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY, content TEXT NOT NULL, type TEXT NOT NULL DEFAULT 'note',
            tags TEXT NOT NULL DEFAULT '[]', feature_id TEXT, prd_id TEXT, plan_id TEXT,
            qa_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        now = datetime.now(timezone.utc).isoformat()
        db.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?)",
                   ("MEM-001", "test", "note", "[]", None, None, None, None, now, now))
        db.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?)",
                   ("MEM-002", "test2", "note", "[]", None, None, None, None, now, now))
        db.commit()
        db.close()

        monkeypatch.setattr(
            "atlassian_cli.commands.memory.OllamaClient",
            lambda s: MagicMock(ping=lambda: True),
        )

        runner = CliRunner()
        result = runner.invoke(mem_cmd.app, ["status"])

        assert result.exit_code == 0, result.output
        assert "local" in result.output
        assert "2" in result.output  # memory count
        assert "MEMORY_BACKEND=turso" in result.output  # hint to switch

    def test_status_turso_mode_shows_turso_info(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import memory as mem_cmd
        self._base_patches(monkeypatch, tmp_path, backend="turso",
                           turso_url="libsql://my-db.turso.io")

        mock_remote = MagicMock()
        mock_remote.execute.return_value = MagicMock(fetchone=lambda: (5,))
        mock_libsql = MagicMock()
        mock_libsql.connect.return_value = mock_remote
        monkeypatch.setattr("atlassian_cli.commands.memory.libsql", mock_libsql)

        monkeypatch.setattr(
            "atlassian_cli.commands.memory.OllamaClient",
            lambda s: MagicMock(ping=lambda: False),
        )

        runner = CliRunner()
        result = runner.invoke(mem_cmd.app, ["status"])

        assert result.exit_code == 0, result.output
        assert "turso" in result.output
        assert "libsql://my-db.turso.io" in result.output

    def test_status_local_with_turso_configured_shows_push_pull_hint(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import memory as mem_cmd
        self._base_patches(monkeypatch, tmp_path, backend="local",
                           turso_url="libsql://my-db.turso.io")
        monkeypatch.setattr(
            "atlassian_cli.commands.memory.OllamaClient",
            lambda s: MagicMock(ping=lambda: True),
        )

        runner = CliRunner()
        result = runner.invoke(mem_cmd.app, ["status"])

        assert result.exit_code == 0, result.output
        assert "libsql://my-db.turso.io" in result.output
        assert "push" in result.output.lower() or "pull" in result.output.lower()


class TestPushCommand:
    def test_push_requires_turso_url(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import memory as mem_cmd
        mock_settings = MagicMock()
        mock_settings.memory_backend = "local"
        mock_settings.turso_url = None
        mock_settings.memory_db_path = str(tmp_path / "mem.db")
        mock_settings.memory_vector_path = str(tmp_path / "vectors")
        monkeypatch.setattr("atlassian_cli.commands.memory.get_settings", lambda: mock_settings)

        runner = CliRunner()
        result = runner.invoke(mem_cmd.app, ["push"])

        assert result.exit_code == 1
        assert "TURSO_URL" in result.output

    def test_push_noop_in_turso_mode(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import memory as mem_cmd
        mock_settings = MagicMock()
        mock_settings.memory_backend = "turso"
        mock_settings.turso_url = "libsql://db.turso.io"
        mock_settings.turso_auth_token = "tok"
        mock_settings.memory_db_path = str(tmp_path / "mem.db")
        mock_settings.memory_vector_path = str(tmp_path / "vectors")
        monkeypatch.setattr("atlassian_cli.commands.memory.get_settings", lambda: mock_settings)

        runner = CliRunner()
        result = runner.invoke(mem_cmd.app, ["push"])

        assert result.exit_code == 0
        assert "already" in result.output.lower() or "turso" in result.output.lower()

    def test_push_calls_push_to_turso(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import memory as mem_cmd
        mock_settings = MagicMock()
        mock_settings.memory_backend = "local"
        mock_settings.turso_url = "libsql://db.turso.io"
        mock_settings.turso_auth_token = "tok"
        mock_settings.memory_db_path = str(tmp_path / "mem.db")
        mock_settings.memory_vector_path = str(tmp_path / "vectors")
        monkeypatch.setattr("atlassian_cli.commands.memory.get_settings", lambda: mock_settings)

        mock_store = MagicMock()
        mock_store.push_to_turso.return_value = 3
        monkeypatch.setattr(
            "atlassian_cli.commands.memory.MemoryStore", lambda **kwargs: mock_store
        )

        runner = CliRunner()
        result = runner.invoke(mem_cmd.app, ["push"])

        assert result.exit_code == 0, result.output
        assert "3" in result.output
        mock_store.push_to_turso.assert_called_once_with("libsql://db.turso.io", "tok")


class TestPullCommand:
    def test_pull_requires_turso_url(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import memory as mem_cmd
        mock_settings = MagicMock()
        mock_settings.memory_backend = "local"
        mock_settings.turso_url = None
        mock_settings.memory_db_path = str(tmp_path / "mem.db")
        mock_settings.memory_vector_path = str(tmp_path / "vectors")
        monkeypatch.setattr("atlassian_cli.commands.memory.get_settings", lambda: mock_settings)

        runner = CliRunner()
        result = runner.invoke(mem_cmd.app, ["pull"])

        assert result.exit_code == 1
        assert "TURSO_URL" in result.output

    def test_pull_local_mode_calls_pull_from_turso(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import memory as mem_cmd
        mock_settings = MagicMock()
        mock_settings.memory_backend = "local"
        mock_settings.turso_url = "libsql://db.turso.io"
        mock_settings.turso_auth_token = "tok"
        mock_settings.memory_db_path = str(tmp_path / "mem.db")
        mock_settings.memory_vector_path = str(tmp_path / "vectors")
        monkeypatch.setattr("atlassian_cli.commands.memory.get_settings", lambda: mock_settings)

        mock_store = MagicMock()
        mock_store.pull_from_turso.return_value = 2
        monkeypatch.setattr(
            "atlassian_cli.commands.memory.MemoryStore", lambda **kwargs: mock_store
        )

        runner = CliRunner()
        result = runner.invoke(mem_cmd.app, ["pull"])

        assert result.exit_code == 0, result.output
        assert "2" in result.output
        mock_store.pull_from_turso.assert_called_once_with("libsql://db.turso.io", "tok")

    def test_pull_turso_mode_calls_sync_vectors(self, tmp_path, monkeypatch):
        from atlassian_cli.commands import memory as mem_cmd
        mock_settings = MagicMock()
        mock_settings.memory_backend = "turso"
        mock_settings.turso_url = "libsql://db.turso.io"
        mock_settings.turso_auth_token = "tok"
        mock_settings.memory_db_path = str(tmp_path / "mem.db")
        mock_settings.memory_vector_path = str(tmp_path / "vectors")
        monkeypatch.setattr("atlassian_cli.commands.memory.get_settings", lambda: mock_settings)

        mock_store = MagicMock()
        mock_store.sync_vectors.return_value = 4
        monkeypatch.setattr(
            "atlassian_cli.commands.memory.MemoryStore", lambda **kwargs: mock_store
        )

        runner = CliRunner()
        result = runner.invoke(mem_cmd.app, ["pull"])

        assert result.exit_code == 0, result.output
        assert "4" in result.output
        mock_store.sync_vectors.assert_called_once()
```

- [ ] **Step 2: Run tests — expect failures**

```bash
pytest tests/test_phase5.py::TestStatusCommand tests/test_phase5.py::TestPushCommand tests/test_phase5.py::TestPullCommand -v
```

Expected: failures because `status`, `push`, `pull` commands don't exist yet.

- [ ] **Step 3: Add `status`, `push`, `pull` to `atlassian_cli/commands/memory.py`**

First, add `import sqlite3` to the imports at the top of `memory.py` (it's not currently imported there, only in memory_store.py). Also add:

```python
import sqlite3
from pathlib import Path

try:
    import libsql_experimental as libsql
except ImportError:
    libsql = None  # type: ignore[assignment]
```

Then append the three commands at the end of the file:

```python
@app.command("status")
def status() -> None:
    settings = get_settings()
    backend = settings.memory_backend

    # Local memory count from SQLite
    db_path = Path(settings.memory_db_path).expanduser()
    local_count = 0
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            local_count = row[0] if row else 0
            conn.close()
        except Exception:
            pass

    # ChromaDB vector count
    vector_count = 0
    vector_path = Path(settings.memory_vector_path).expanduser()
    if vector_path.exists():
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(vector_path))
            col = client.get_or_create_collection("memories")
            vector_count = col.count()
        except Exception:
            pass

    ollama_ok = OllamaClient(settings).ping()
    ollama_icon = "[green]✓[/green]" if ollama_ok else "[red]✗[/red]"

    if backend == "local":
        console.print(f"[bold]Backend:[/bold]   local  [dim](set MEMORY_BACKEND=turso to use Turso)[/dim]")
        console.print(f"[bold]Store:[/bold]     {settings.memory_db_path}")
        console.print(f"[bold]Memories:[/bold]  {local_count}")
        not_embedded = max(0, local_count - vector_count)
        console.print(f"[bold]Vectors:[/bold]   {vector_count}  [dim]({not_embedded} not yet embedded)[/dim]")
        console.print(f"[bold]Ollama:[/bold]    {ollama_icon}  {settings.ollama_host}")
        if settings.turso_url:
            console.print(f"[bold]Turso:[/bold]     {settings.turso_url}  [dim](push/pull available)[/dim]")
        else:
            console.print(f"[bold]Turso:[/bold]     [dim]not configured  (set TURSO_URL to enable push/pull)[/dim]")
    else:
        turso_count = 0
        turso_ok = False
        if settings.turso_url and libsql is not None:
            try:
                remote = libsql.connect(
                    database=settings.turso_url,
                    auth_token=settings.turso_auth_token or "",
                )
                row = remote.execute("SELECT COUNT(*) FROM memories").fetchone()
                turso_count = row[0] if row else 0
                turso_ok = True
            except Exception:
                pass
        turso_icon = "[green]✓[/green]" if turso_ok else "[red]✗[/red]"
        console.print(f"[bold]Backend:[/bold]   turso")
        console.print(f"[bold]Remote:[/bold]    {turso_icon}  {settings.turso_url or 'not configured'}")
        console.print(f"[bold]Memories:[/bold]  {turso_count}  [dim](Turso)[/dim]")
        console.print(f"[bold]Vectors:[/bold]   {vector_count}  [dim](local ChromaDB)[/dim]")
        console.print(f"[bold]Ollama:[/bold]    {ollama_icon}  {settings.ollama_host}")


@app.command("push")
def push() -> None:
    settings = get_settings()
    if not settings.turso_url:
        console.print("[red]✗[/red]  TURSO_URL not configured. Set it in .env to enable push.")
        raise typer.Exit(1)
    if settings.memory_backend == "turso":
        console.print("[dim]Backend is already Turso — memories are written directly to Turso.[/dim]")
        return
    store = _get_store()
    try:
        count = store.push_to_turso(settings.turso_url, settings.turso_auth_token or "")
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
    noun = "memory" if count == 1 else "memories"
    console.print(f"[green]✓[/green] Pushed {count} new {noun} to Turso")


@app.command("pull")
def pull() -> None:
    settings = get_settings()
    if not settings.turso_url:
        console.print("[red]✗[/red]  TURSO_URL not configured. Set it in .env to enable pull.")
        raise typer.Exit(1)
    store = _get_store()
    try:
        if settings.memory_backend == "turso":
            count = store.sync_vectors()
            noun = "memory" if count == 1 else "memories"
            console.print(f"[green]✓[/green] Synced {count} new {noun} to local search index")
        else:
            count = store.pull_from_turso(settings.turso_url, settings.turso_auth_token or "")
            noun = "memory" if count == 1 else "memories"
            console.print(f"[green]✓[/green] Pulled {count} new {noun} from Turso")
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
```

- [ ] **Step 4: Run Task 2 tests**

```bash
pytest tests/test_phase5.py::TestStatusCommand tests/test_phase5.py::TestPushCommand tests/test_phase5.py::TestPullCommand -v
```

Expected: all pass.

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -v
```

Expected: `46 passed` (34 existing + 12 new).

- [ ] **Step 6: Commit**

```bash
git add atlassian_cli/commands/memory.py tests/test_phase5.py
git commit -m "feat(5): memory status/push/pull commands for Turso sync"
git push origin main
```

---

## Task 3: .env.example + README

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Update `.env.example`**

Add a new Phase 5 section at the end:

```
# --- Phase 5 (Shared memory with Turso) ---
# MEMORY_BACKEND=local        # "local" (default) or "turso"
# TURSO_URL=libsql://your-db.turso.io
# TURSO_AUTH_TOKEN=your-turso-token
# Get your token at: https://turso.tech
```

- [ ] **Step 2: Update `README.md`**

In the `### Memory` section, after the existing `atlassian memory snapshot` line and before the closing note, add:

```bash
# Show backend status, memory counts, and connectivity
atlassian memory status

# Sync local memories → Turso (requires TURSO_URL)
atlassian memory push

# Sync Turso → local + re-embed new memories (requires TURSO_URL + Ollama)
atlassian memory pull
```

Update the existing Ollama note block to include backend info:

```markdown
> `list`, `snapshot`, and `status` query SQLite/LocalStorage directly — no Ollama required.  
> `add` and `search` require Ollama running with `nomic-embed-text` pulled (`ollama pull nomic-embed-text`).  
> `pull` also requires Ollama to re-embed new memories from Turso.

**Backends:**
- `MEMORY_BACKEND=local` (default) — local SQLite, works offline. Use `push`/`pull` to sync with team.
- `MEMORY_BACKEND=turso` — Turso as primary store, all reads/writes go to the cloud. Use `pull` to re-sync local search index.
```

Also add to the `## Local storage` section the note that Turso replaces the local SQLite file when `MEMORY_BACKEND=turso`:

After the `memory.db` line:
```
├── memory.db    SQLite — full memory records  (local mode only)
```

- [ ] **Step 3: Commit**

```bash
git add .env.example README.md
git commit -m "docs(5): Turso backend docs and .env.example update"
git push origin main
```

---

## Self-Review

**Spec coverage:**
- ✓ `MEMORY_BACKEND=local` (default) — existing behavior unchanged
- ✓ `MEMORY_BACKEND=turso` — MemoryStore uses libsql, all ops go to Turso
- ✓ `TURSO_URL` + `TURSO_AUTH_TOKEN` env vars in Settings
- ✓ `OllamaClient.ping()` for connectivity check
- ✓ `MemoryStore.push_to_turso()` — syncs local→Turso, returns count
- ✓ `MemoryStore.pull_from_turso()` — syncs Turso→local+ChromaDB, returns count
- ✓ `MemoryStore.sync_vectors()` — re-embeds missing ChromaDB entries, returns count
- ✓ `memory status` — shows backend, counts, connectivity for both modes
- ✓ `memory push` — local mode syncs to Turso; no-op in Turso mode; exit 1 if no TURSO_URL
- ✓ `memory pull` — local mode pulls from Turso; Turso mode re-syncs ChromaDB; exit 1 if no TURSO_URL
- ✓ FTS5 table skipped in Turso mode (libsql may not support it)
- ✓ libsql import is optional (graceful ImportError → clear message)
- ✓ Tests cover both local and Turso backends for all new commands
- ✓ All 3 existing MemoryStore callers updated (memory.py, qa.py, adr.py)

**Placeholder scan:** None — all steps have complete code.

**Type consistency:**
- `push_to_turso(turso_url: str, turso_auth_token: str) -> int` matches callers in `push()` command ✓
- `pull_from_turso(turso_url: str, turso_auth_token: str) -> int` matches callers in `pull()` command ✓
- `sync_vectors() -> int` matches caller in `pull()` (Turso mode) ✓
- `_rows()` / `_row()` used in `get()`, `list()`, `sync_vectors()` — consistent ✓
- `settings.turso_auth_token or ""` safely handles `None` in all callers ✓
