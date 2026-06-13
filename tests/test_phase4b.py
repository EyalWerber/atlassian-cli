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
