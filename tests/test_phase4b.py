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
