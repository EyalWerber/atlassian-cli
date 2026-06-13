from __future__ import annotations

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
