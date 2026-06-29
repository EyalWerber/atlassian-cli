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
            if type and type.value == "bug":
                return [MagicMock(id="MEM-003", content="Bug BUG-123 filed: login 500")]
            return []
        mock_store.list.side_effect = mock_list
        monkeypatch.setattr("atlassian_cli.commands.memory.MemoryStore", lambda **kwargs: mock_store)
        mock_settings = MagicMock()
        mock_settings.memory_backend = "local"
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
        mock_settings.memory_backend = "local"
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
