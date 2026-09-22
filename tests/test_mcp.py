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
            issue_type="Feature", parent_key=None, priority=None,
        )

    def test_passes_parent_key(self, mock_jira):
        mock_jira.create_issue.return_value = "ACLI-16"
        from atlassian_cli.mcp import create_issue
        create_issue("Subtask", type="Sub-task", parent_key="ACLI-4")
        mock_jira.create_issue.assert_called_once_with(
            summary="Subtask", description="",
            issue_type="Sub-task", parent_key="ACLI-4", priority=None,
        )

    def test_defaults_to_task_type(self, mock_jira):
        mock_jira.create_issue.return_value = "ACLI-17"
        from atlassian_cli.mcp import create_issue
        create_issue("Quick task")
        mock_jira.create_issue.assert_called_once_with(
            summary="Quick task", description="",
            issue_type="Task", parent_key=None, priority=None,
        )

    def test_passes_priority(self, mock_jira):
        mock_jira.create_issue.return_value = "ACLI-18"
        from atlassian_cli.mcp import create_issue
        create_issue("Urgent task", priority="High")
        mock_jira.create_issue.assert_called_once_with(
            summary="Urgent task", description="",
            issue_type="Task", parent_key=None, priority="High",
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


class TestLinkIssues:
    def test_creates_link_with_default_type(self, mock_jira):
        from atlassian_cli.mcp import link_issues
        result = link_issues("YDMC-493", "YDMC-492")
        mock_jira.add_link.assert_called_once_with("YDMC-493", "Relates", "YDMC-492")
        assert result == {
            "inward_key": "YDMC-493",
            "link_type": "Relates",
            "outward_key": "YDMC-492",
        }

    def test_honours_explicit_link_type(self, mock_jira):
        from atlassian_cli.mcp import link_issues
        link_issues("SI-11", "SI-8", link_type="Blocks")
        mock_jira.add_link.assert_called_once_with("SI-11", "Blocks", "SI-8")


class TestListIssueLinks:
    def test_passes_through_client_links(self, mock_jira):
        mock_jira.list_links.return_value = [
            {"id": "10001", "type": "Relates", "inward_key": "YDMC-493",
             "inward_summary": "", "outward_key": "YDMC-492", "outward_summary": ""},
        ]
        from atlassian_cli.mcp import list_issue_links
        result = list_issue_links("YDMC-493")
        mock_jira.list_links.assert_called_once_with("YDMC-493")
        assert result[0]["id"] == "10001"
        assert result[0]["outward_key"] == "YDMC-492"

    def test_empty(self, mock_jira):
        mock_jira.list_links.return_value = []
        from atlassian_cli.mcp import list_issue_links
        assert list_issue_links("YDMC-1") == []


class TestUnlinkIssues:
    def test_removes_by_link_id_without_lookup(self, mock_jira):
        from atlassian_cli.mcp import unlink_issues
        result = unlink_issues("YDMC-493", link_id="10001")
        mock_jira.list_links.assert_not_called()
        mock_jira.remove_link.assert_called_once_with("10001")
        assert result == {"key": "YDMC-493", "removed_link_id": "10001"}

    def test_looks_up_link_by_counterpart_key(self, mock_jira):
        mock_jira.list_links.return_value = [
            {"id": "10001", "type": "Blocks", "inward_key": "YDMC-493", "outward_key": "YDMC-999"},
            {"id": "10002", "type": "Relates", "inward_key": "YDMC-493", "outward_key": "YDMC-492"},
        ]
        from atlassian_cli.mcp import unlink_issues
        result = unlink_issues("YDMC-493", other_key="YDMC-492")
        mock_jira.remove_link.assert_called_once_with("10002")
        assert result["removed_link_id"] == "10002"

    def test_matches_counterpart_on_inward_side(self, mock_jira):
        mock_jira.list_links.return_value = [
            {"id": "10003", "type": "Relates", "inward_key": "YDMC-492", "outward_key": "YDMC-493"},
        ]
        from atlassian_cli.mcp import unlink_issues
        unlink_issues("YDMC-493", other_key="YDMC-492")
        mock_jira.remove_link.assert_called_once_with("10003")

    def test_requires_other_key_or_link_id(self, mock_jira):
        from atlassian_cli.mcp import unlink_issues
        with pytest.raises(ValueError, match="link_id"):
            unlink_issues("YDMC-493")
        mock_jira.remove_link.assert_not_called()

    def test_raises_when_no_matching_link(self, mock_jira):
        mock_jira.list_links.return_value = [
            {"id": "10001", "type": "Blocks", "inward_key": "YDMC-493", "outward_key": "YDMC-999"},
        ]
        from atlassian_cli.mcp import unlink_issues
        with pytest.raises(ValueError, match="No 'Relates' link"):
            unlink_issues("YDMC-493", other_key="YDMC-492")
        mock_jira.remove_link.assert_not_called()


class TestLinkToolsRegistered:
    def test_tools_and_handlers_are_wired(self):
        from atlassian_cli.mcp import _HANDLERS, _TOOLS
        names = {t.name for t in _TOOLS}
        for tool in ("link_issues", "list_issue_links", "unlink_issues"):
            assert tool in names
            assert tool in _HANDLERS

    def test_handlers_apply_defaults(self, mock_jira):
        from atlassian_cli.mcp import _HANDLERS
        _HANDLERS["link_issues"]({"inward_key": "A-1", "outward_key": "A-2"})
        mock_jira.add_link.assert_called_once_with("A-1", "Relates", "A-2")


class TestListProjects:
    def test_passes_through(self, mock_jira):
        mock_jira.list_projects.return_value = [
            {"key": "MC", "name": "Mission Control", "id": "10364",
             "style": "classic", "type": "software"},
        ]
        from atlassian_cli.mcp import list_projects
        result = list_projects()
        mock_jira.list_projects.assert_called_once_with()
        assert result[0]["key"] == "MC"


class TestGetProject:
    def test_returns_issue_types(self, mock_jira):
        mock_jira.get_project.return_value = {
            "key": "MC", "name": "Mission Control", "id": "10364",
            "style": "classic", "issue_types": ["Task", "Epic", "Feature"],
        }
        from atlassian_cli.mcp import get_project
        result = get_project("MC")
        mock_jira.get_project.assert_called_once_with("MC")
        assert "Feature" in result["issue_types"]


class TestCreateProject:
    def test_creates_with_shared_config(self, mock_jira):
        mock_jira.create_project.return_value = {
            "key": "CONA", "issue_types": ["Epic", "Feature", "Story", "Sub-task"],
        }
        from atlassian_cli.mcp import create_project
        result = create_project("CONA", "Construction Assistant", share_with="MC")
        mock_jira.create_project.assert_called_once_with(
            key="CONA", name="Construction Assistant", share_with="MC", description="",
        )
        assert result["key"] == "CONA"

    def test_defaults_share_with_to_none(self, mock_jira):
        from atlassian_cli.mcp import create_project
        create_project("ZZZ", "Standalone")
        mock_jira.create_project.assert_called_once_with(
            key="ZZZ", name="Standalone", share_with=None, description="",
        )

    def test_handler_wires_arguments(self, mock_jira):
        from atlassian_cli.mcp import _HANDLERS
        _HANDLERS["create_project"]({"key": "AAA", "name": "A", "share_with": "MC"})
        mock_jira.create_project.assert_called_once_with(
            key="AAA", name="A", share_with="MC", description="",
        )

    def test_project_tools_registered(self):
        from atlassian_cli.mcp import _HANDLERS, _TOOLS
        names = {t.name for t in _TOOLS}
        for tool in ("list_projects", "get_project", "create_project"):
            assert tool in names and tool in _HANDLERS


class TestSetParent:
    def test_sets_parent(self, mock_jira):
        from atlassian_cli.mcp import set_parent
        result = set_parent("CONA-3", "CONA-1")
        mock_jira.set_parent.assert_called_once_with("CONA-3", "CONA-1")
        assert result == {"key": "CONA-3", "parent": "CONA-1"}

    def test_detaches_when_parent_omitted(self, mock_jira):
        from atlassian_cli.mcp import set_parent
        result = set_parent("CONA-3")
        mock_jira.set_parent.assert_called_once_with("CONA-3", None)
        assert result["parent"] is None

    def test_registered_and_wired(self, mock_jira):
        from atlassian_cli.mcp import _HANDLERS, _TOOLS
        assert "set_parent" in {t.name for t in _TOOLS}
        _HANDLERS["set_parent"]({"key": "A-2", "parent_key": "A-1"})
        mock_jira.set_parent.assert_called_once_with("A-2", "A-1")
