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
