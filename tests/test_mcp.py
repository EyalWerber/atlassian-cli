"""Unit tests for MCP tool handler functions."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from atlassian_cli.models.memory import Memory, MemoryType


def test_mcp_module_imports():
    import atlassian_cli.mcp  # noqa: F401


def _mem(id="MEM-001", content="test", type=MemoryType.note, tags=None, feature_id=None):
    now = datetime.now(timezone.utc)
    return Memory(
        id=id, content=content, type=type, tags=tags or [],
        feature_id=feature_id, created_at=now, updated_at=now,
    )


@pytest.fixture
def mock_store():
    with patch("atlassian_cli.mcp._get_store") as m:
        store = MagicMock()
        m.return_value = store
        yield store


@pytest.fixture
def mock_jira():
    with patch("atlassian_cli.mcp._get_jira") as m:
        jira = MagicMock()
        m.return_value = jira
        yield jira


class TestSearchMemory:
    def test_returns_serialized_memories(self, mock_store):
        mock_store.search.return_value = [_mem(content="Bug in login")]
        from atlassian_cli.mcp import search_memory
        result = search_memory("login bug", limit=3)
        mock_store.search.assert_called_once_with("login bug", limit=3)
        assert result[0]["content"] == "Bug in login"
        assert "id" in result[0] and "type" in result[0] and "tags" in result[0]

    def test_empty_result(self, mock_store):
        mock_store.search.return_value = []
        from atlassian_cli.mcp import search_memory
        assert search_memory("nothing") == []


class TestListMemories:
    def test_filters_by_type(self, mock_store):
        mock_store.list.return_value = [_mem(type=MemoryType.bug)]
        from atlassian_cli.mcp import list_memories
        result = list_memories(type="bug")
        mock_store.list.assert_called_once_with(type=MemoryType.bug, feature_id=None, limit=20)
        assert result[0]["type"] == "bug"

    def test_no_filters(self, mock_store):
        mock_store.list.return_value = []
        from atlassian_cli.mcp import list_memories
        list_memories()
        mock_store.list.assert_called_once_with(type=None, feature_id=None, limit=20)

    def test_filters_by_feature(self, mock_store):
        mock_store.list.return_value = []
        from atlassian_cli.mcp import list_memories
        list_memories(feature="ACLI-4")
        mock_store.list.assert_called_once_with(type=None, feature_id="ACLI-4", limit=20)


class TestGetIssue:
    def test_returns_flattened_issue(self, mock_jira):
        mock_jira.get_issue.return_value = {
            "key": "ACLI-4",
            "fields": {
                "summary": "Memory System",
                "status": {"name": "Done"},
                "issuetype": {"name": "Feature"},
                "assignee": None,
                "description": None,
            },
        }
        from atlassian_cli.mcp import get_issue
        result = get_issue("ACLI-4")
        assert result == {
            "key": "ACLI-4", "summary": "Memory System", "status": "Done",
            "type": "Feature", "assignee": "", "description": "",
        }


class TestListIssues:
    def test_uses_jql_when_provided(self, mock_jira):
        mock_jira.search_issues.return_value = []
        with patch("atlassian_cli.mcp.get_settings") as ms:
            ms.return_value.jira_project = "ACLI"
            from atlassian_cli.mcp import list_issues
            list_issues(jql="project=ACLI AND assignee=currentUser()")
        mock_jira.search_issues.assert_called_once_with("project=ACLI AND assignee=currentUser()")

    def test_status_open_maps_to_jql(self, mock_jira):
        mock_jira.search_issues.return_value = []
        with patch("atlassian_cli.mcp.get_settings") as ms:
            ms.return_value.jira_project = "ACLI"
            from atlassian_cli.mcp import list_issues
            list_issues(status="open")
        query = mock_jira.search_issues.call_args[0][0]
        assert "statusCategory != Done" in query

    def test_status_done_maps_to_jql(self, mock_jira):
        mock_jira.search_issues.return_value = []
        with patch("atlassian_cli.mcp.get_settings") as ms:
            ms.return_value.jira_project = "ACLI"
            from atlassian_cli.mcp import list_issues
            list_issues(status="done")
        query = mock_jira.search_issues.call_args[0][0]
        assert "statusCategory = Done" in query

    def test_returns_flattened_issues(self, mock_jira):
        mock_jira.search_issues.return_value = [
            {"key": "ACLI-1", "fields": {"summary": "Feature PRD", "status": {"name": "Done"}}}
        ]
        with patch("atlassian_cli.mcp.get_settings") as ms:
            ms.return_value.jira_project = "ACLI"
            from atlassian_cli.mcp import list_issues
            result = list_issues()
        assert result == [{"key": "ACLI-1", "summary": "Feature PRD", "status": "Done"}]


class TestAddMemory:
    def test_creates_and_saves_memory(self, mock_store):
        mock_store.next_id.return_value = "MEM-010"
        from atlassian_cli.mcp import add_memory
        result = add_memory("Architecture decision", type="decision", tags=["arch"])
        saved: Memory = mock_store.add.call_args[0][0]
        assert saved.type == MemoryType.decision
        assert saved.tags == ["arch"]
        assert saved.content == "Architecture decision"
        assert result == {"id": "MEM-010", "content": "Architecture decision"}

    def test_defaults_to_note_type(self, mock_store):
        mock_store.next_id.return_value = "MEM-011"
        from atlassian_cli.mcp import add_memory
        add_memory("plain note")
        saved: Memory = mock_store.add.call_args[0][0]
        assert saved.type == MemoryType.note

    def test_empty_tags_default(self, mock_store):
        mock_store.next_id.return_value = "MEM-012"
        from atlassian_cli.mcp import add_memory
        add_memory("note")
        saved: Memory = mock_store.add.call_args[0][0]
        assert saved.tags == []


class TestCreateIssue:
    def test_returns_key(self, mock_jira):
        mock_jira.create_issue.return_value = "ACLI-15"
        from atlassian_cli.mcp import create_issue
        result = create_issue("New feature", type="Feature", description="desc")
        assert result == {"key": "ACLI-15"}
        mock_jira.create_issue.assert_called_once_with(
            summary="New feature", description="desc",
            issue_type="Feature", parent_key=None,
        )

    def test_passes_parent_key(self, mock_jira):
        mock_jira.create_issue.return_value = "ACLI-16"
        from atlassian_cli.mcp import create_issue
        create_issue("Subtask", type="Sub-task", parent_key="ACLI-4")
        mock_jira.create_issue.assert_called_once_with(
            summary="Subtask", description="",
            issue_type="Sub-task", parent_key="ACLI-4",
        )

    def test_defaults_to_task_type(self, mock_jira):
        mock_jira.create_issue.return_value = "ACLI-17"
        from atlassian_cli.mcp import create_issue
        create_issue("Quick task")
        mock_jira.create_issue.assert_called_once_with(
            summary="Quick task", description="",
            issue_type="Task", parent_key=None,
        )


class TestTransitionIssue:
    def test_calls_transition_and_returns_status(self, mock_jira):
        from atlassian_cli.mcp import transition_issue
        result = transition_issue("ACLI-4", "Done")
        mock_jira.transition_issue.assert_called_once_with("ACLI-4", "Done")
        assert result == {"key": "ACLI-4", "status": "Done"}


class TestAddComment:
    def test_calls_add_comment(self, mock_jira):
        from atlassian_cli.mcp import add_comment
        result = add_comment("ACLI-4", "Fixed in latest commit")
        mock_jira.add_comment.assert_called_once_with("ACLI-4", "Fixed in latest commit")
        assert result == {"key": "ACLI-4"}
