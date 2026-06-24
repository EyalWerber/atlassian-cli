from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from atlassian_cli.integrations.ollama import OllamaClient
from atlassian_cli.integrations.turso import TursoHttpClient
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
            self._conn = TursoHttpClient(
                url=turso_url,
                auth_token=turso_auth_token or "",
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
        if sys.platform == "win32":
            self._collection = None
            return
        try:
            import chromadb
            self._vector_path.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(self._vector_path))
            self._collection = client.get_or_create_collection("memories")
        except Exception:
            self._collection = None

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
            query += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_memory(r) for r in self._rows(query, tuple(params))]

    def search(self, query: str, limit: int = 5, feature_id: Optional[str] = None) -> list[Memory]:
        if self._collection is not None:
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
                ids = results["ids"][0]
                return [m for id in ids if (m := self.get(id)) is not None]
            except Exception:
                pass
        # FTS fallback (SQLite local only)
        if not self._is_turso:
            rows = self._rows(
                "SELECT m.* FROM memories m JOIN memories_fts f ON m.id = f.id WHERE memories_fts MATCH ? LIMIT ?",
                (query, limit),
            )
            return [self._row_to_memory(r) for r in rows]
        return self.list(limit=limit, feature_id=feature_id)

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
        if self._is_turso:
            raise RuntimeError("push_to_turso() requires local mode (MEMORY_BACKEND=local)")
        remote = TursoHttpClient(url=turso_url, auth_token=turso_auth_token)
        remote.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY, content TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'note', tags TEXT NOT NULL DEFAULT '[]',
                feature_id TEXT, prd_id TEXT, plan_id TEXT, qa_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
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
        return count

    def pull_from_turso(self, turso_url: str, turso_auth_token: str) -> int:
        if self._is_turso:
            raise RuntimeError("pull_from_turso() requires local mode (MEMORY_BACKEND=local)")
        remote = TursoHttpClient(url=turso_url, auth_token=turso_auth_token)
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
                self._conn.execute(
                    "INSERT INTO memories_fts(id, content) VALUES (?, ?)",
                    (row["id"], row["content"]),
                )
                count += 1
        if count:
            self._conn.commit()
        return count

    def sync_vectors(self) -> int:
        if self._collection is None:
            return 0
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
