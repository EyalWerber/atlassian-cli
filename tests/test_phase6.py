from unittest.mock import MagicMock, patch
import pytest
from atlassian_cli.integrations.jira import JiraClient
from atlassian_cli.config import Settings


def _client() -> JiraClient:
    settings = MagicMock()
    settings.atlassian_url = "https://test.atlassian.net"
    settings.atlassian_email = "test@example.com"
    settings.atlassian_api_token.get_secret_value.return_value = "token"
    settings.jira_project = "SI"
    with patch("atlassian_cli.integrations.jira.Jira"):
        return JiraClient(settings)


def test_get_transitions_returns_list():
    client = _client()
    client._jira.get.return_value = {
        "transitions": [
            {"id": "11", "name": "To Do", "to": {"name": "To Do"}},
            {"id": "41", "name": "Done", "to": {"name": "Done"}},
        ]
    }
    result = client.get_transitions("SI-1")
    assert len(result) == 2
    assert result[0]["name"] == "To Do"


def test_transition_issue_posts_correct_payload():
    client = _client()
    client._jira.get.return_value = {
        "transitions": [{"id": "41", "name": "Done", "to": {"name": "Done"}}]
    }
    client._jira.post.return_value = None
    client.transition_issue("SI-1", "Done")
    client._jira.post.assert_called_once_with(
        "rest/api/2/issue/SI-1/transitions",
        data={"transition": {"id": "41"}},
    )


def test_transition_issue_raises_on_unknown_status():
    client = _client()
    client._jira.get.return_value = {
        "transitions": [{"id": "41", "name": "Done", "to": {"name": "Done"}}]
    }
    with pytest.raises(RuntimeError, match="not found"):
        client.transition_issue("SI-1", "Nonexistent")


def test_list_links_returns_parsed_links():
    client = _client()
    client._jira.issue.return_value = {
        "fields": {
            "issuelinks": [
                {
                    "id": "10001",
                    "type": {"name": "Blocks"},
                    "outwardIssue": {"key": "SI-8", "fields": {"summary": "Wet fart"}},
                },
            ]
        }
    }
    links = client.list_links("SI-11")
    assert len(links) == 1
    assert links[0]["id"] == "10001"
    assert links[0]["outward_key"] == "SI-8"


def test_remove_link_calls_delete():
    client = _client()
    client._jira.delete.return_value = None
    client.remove_link("10001")
    client._jira.delete.assert_called_once_with("rest/api/2/issueLink/10001")


def test_add_link_creates_blocks_relationship():
    client = _client()
    client._jira.create_issue_link.return_value = None
    client.add_link("SI-11", "Blocks", "SI-8")
    client._jira.create_issue_link.assert_called_once_with(data={
        "type": {"name": "Blocks"},
        "inwardIssue": {"key": "SI-11"},
        "outwardIssue": {"key": "SI-8"},
    })


from typer.testing import CliRunner
from atlassian_cli.commands.issue import app as issue_app

runner = CliRunner()


def test_issue_comment_command():
    with patch("atlassian_cli.commands.issue.JiraClient") as MockJira, \
         patch("atlassian_cli.commands.issue.get_settings"):
        MockJira.return_value.add_comment.return_value = None
        result = runner.invoke(issue_app, ["comment", "SI-11", "Fixed it"])
        assert result.exit_code == 0
        assert "SI-11" in result.output
        MockJira.return_value.add_comment.assert_called_once_with("SI-11", "Fixed it")


def test_issue_show_command():
    with patch("atlassian_cli.commands.issue.JiraClient") as MockJira, \
         patch("atlassian_cli.commands.issue.get_settings"):
        MockJira.return_value.get_issue.return_value = {
            "key": "SI-11",
            "fields": {
                "summary": "Diarrhea",
                "status": {"name": "Done"},
                "issuetype": {"name": "Bug"},
                "assignee": None,
                "priority": {"name": "Medium"},
                "issuelinks": [],
            }
        }
        result = runner.invoke(issue_app, ["show", "SI-11"])
        assert result.exit_code == 0
        assert "Diarrhea" in result.output
        assert "Done" in result.output


def test_issue_link_command():
    with patch("atlassian_cli.commands.issue.JiraClient") as MockJira, \
         patch("atlassian_cli.commands.issue.get_settings"):
        MockJira.return_value.add_link.return_value = None
        result = runner.invoke(issue_app, ["link", "SI-11", "--blocks", "SI-8"])
        assert result.exit_code == 0
        MockJira.return_value.add_link.assert_called_once_with("SI-11", "Blocks", "SI-8")


def test_issue_unlink_command_removes_matching_link():
    with patch("atlassian_cli.commands.issue.JiraClient") as MockJira, \
         patch("atlassian_cli.commands.issue.get_settings"):
        MockJira.return_value.list_links.return_value = [
            {"id": "10001", "type": "Blocks", "inward_key": "SI-11",
             "outward_key": "SI-8", "inward_summary": "", "outward_summary": ""}
        ]
        MockJira.return_value.remove_link.return_value = None
        result = runner.invoke(issue_app, ["unlink", "SI-11", "--blocks", "SI-8"])
        assert result.exit_code == 0
        MockJira.return_value.remove_link.assert_called_once_with("10001")


def test_update_description_puts_correct_payload():
    client = _client()
    client._jira.put.return_value = None
    client.update_description("SI-5", "PRD: https://eyal-werber.atlassian.net/wiki/spaces/SIDEV/pages/123")
    client._jira.put.assert_called_once_with(
        "rest/api/2/issue/SI-5",
        data={"fields": {"description": "PRD: https://eyal-werber.atlassian.net/wiki/spaces/SIDEV/pages/123"}},
    )
