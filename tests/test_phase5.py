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

        import importlib
        import atlassian_cli.config as config_module
        importlib.reload(config_module)
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

        import importlib
        import atlassian_cli.config as config_module
        importlib.reload(config_module)
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
        mock_get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr("atlassian_cli.integrations.ollama.requests.get", mock_get)

        client = OllamaClient(mock_settings)
        assert client.ping() is True
        mock_get.assert_called_once_with("http://localhost:11434/api/tags", timeout=3)

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


@pytest.fixture
def mock_chromadb(monkeypatch):
    """Mock ChromaDB PersistentClient to avoid Rust extension crashes on Windows."""
    mock_collection = MagicMock()
    mock_collection.count.return_value = 0
    mock_collection.get.return_value = {"ids": []}
    mock_collection.query.return_value = {"ids": [[]]}

    # Track upserted items to simulate real behavior
    upserted_ids = []

    def fake_upsert(ids, embeddings, documents, metadatas):
        for id_ in ids:
            if id_ not in upserted_ids:
                upserted_ids.append(id_)
        mock_collection.count.return_value = len(upserted_ids)

    def fake_delete(ids):
        for id_ in ids:
            if id_ in upserted_ids:
                upserted_ids.remove(id_)
        mock_collection.count.return_value = len(upserted_ids)

    def fake_get():
        return {"ids": list(upserted_ids)}

    mock_collection.upsert.side_effect = fake_upsert
    mock_collection.delete.side_effect = fake_delete
    mock_collection.get.side_effect = fake_get

    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    import chromadb
    monkeypatch.setattr(chromadb, "PersistentClient", lambda path: mock_client)

    return mock_collection, upserted_ids


class TestMemoryStoreLocalMode:
    def test_local_mode_is_default(self, tmp_path, mock_chromadb):
        from atlassian_cli.storage.memory_store import MemoryStore
        mock_ollama = MagicMock()
        store = MemoryStore(
            db_path=str(tmp_path / "mem.db"),
            vector_path=str(tmp_path / "vectors"),
            ollama=mock_ollama,
        )
        assert not store._is_turso

    def test_local_mode_add_and_list(self, tmp_path, mock_chromadb):
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
    def test_turso_mode_calls_libsql_connect(self, tmp_path, mock_chromadb, monkeypatch):
        mock_libsql = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_cursor.fetchall.return_value = []
        mock_cursor.description = [("id",)]
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_cursor
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
    def test_push_uploads_only_new_memories(self, tmp_path, mock_chromadb, monkeypatch):
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
        mock_remote_cursor = MagicMock()
        mock_remote_cursor.fetchall.return_value = [("MEM-001",)]
        mock_remote = MagicMock()
        mock_remote.execute.return_value = mock_remote_cursor
        mock_libsql = MagicMock()
        mock_libsql.connect.return_value = mock_remote
        monkeypatch.setattr("atlassian_cli.storage.memory_store.libsql", mock_libsql)

        count = store.push_to_turso("libsql://db.turso.io", "token")

        assert count == 1
        insert_calls = [c for c in mock_remote.execute.call_args_list
                        if "INSERT" in str(c)]
        assert len(insert_calls) == 1

    def test_push_returns_zero_when_all_synced(self, tmp_path, mock_chromadb, monkeypatch):
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

        mock_remote_cursor = MagicMock()
        mock_remote_cursor.fetchall.return_value = [("MEM-001",)]
        mock_remote = MagicMock()
        mock_remote.execute.return_value = mock_remote_cursor
        mock_libsql = MagicMock()
        mock_libsql.connect.return_value = mock_remote
        monkeypatch.setattr("atlassian_cli.storage.memory_store.libsql", mock_libsql)

        count = store.push_to_turso("libsql://db.turso.io", "token")
        assert count == 0


class TestPullFromTurso:
    def test_pull_inserts_new_remote_memories(self, tmp_path, mock_chromadb, monkeypatch):
        from atlassian_cli.storage.memory_store import MemoryStore
        from atlassian_cli.models.memory import Memory, MemoryType
        mock_ollama = MagicMock()
        mock_ollama.embed.return_value = [0.1] * 768
        store = MemoryStore(
            db_path=str(tmp_path / "mem.db"),
            vector_path=str(tmp_path / "vectors"),
            ollama=mock_ollama,
        )
        store_now = datetime.now(timezone.utc)
        store.add(Memory(id="MEM-001", content="existing", type=MemoryType.note,
                         tags=[], created_at=store_now, updated_at=store_now))

        now = datetime.now(timezone.utc).isoformat()
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
    def test_sync_vectors_embeds_missing(self, tmp_path, mock_chromadb):
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

        store._collection.delete(ids=["MEM-002"])
        assert store._collection.count() == 1

        count = store.sync_vectors()
        assert count == 1
        assert store._collection.count() == 2

    def test_sync_vectors_returns_zero_when_all_synced(self, tmp_path, mock_chromadb):
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
