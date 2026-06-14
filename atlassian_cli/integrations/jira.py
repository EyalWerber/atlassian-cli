from typing import Optional

from atlassian import Jira
from atlassian_cli.config import Settings


_STATUS_MESSAGES = {
    401: "Invalid credentials. Check ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN.",
    403: "Permission denied. Check your account has access to this Jira project.",
    404: "Resource not found. Check JIRA_PROJECT value.",
}


def _friendly_error(e: Exception) -> str:
    resp = getattr(e, "response", None)
    if resp is not None:
        status = getattr(resp, "status_code", None)
        if status in _STATUS_MESSAGES:
            return _STATUS_MESSAGES[status]
    return str(e)


def _adf_paragraph(text: str) -> dict:
    return {
        "version": 1,
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _adf_para_node(text: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def _adf_heading_node(text: str, level: int) -> dict:
    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": [{"type": "text", "text": text}],
    }


def _adf_bug_description(actual: str, expected: str, error: Optional[str]) -> dict:
    content: list[dict] = [
        _adf_heading_node("Actual Results", 3),
        _adf_para_node(actual),
        _adf_heading_node("Expected Results", 3),
        _adf_para_node(expected),
    ]
    if error:
        content += [_adf_heading_node("Error", 3), _adf_para_node(error)]
    return {"version": 1, "type": "doc", "content": content}


class JiraClient:
    def __init__(self, settings: Settings):
        self._jira = Jira(
            url=settings.atlassian_url,
            username=settings.atlassian_email,
            password=settings.atlassian_api_token.get_secret_value(),
            cloud=True,
        )
        self.project = settings.jira_project

    def create_initiative(self, summary: str, description: str) -> str:
        """Create an Initiative issue. Returns the issue key."""
        try:
            issue = self._jira.create_issue(fields={
                "project": {"key": self.project},
                "summary": summary,
                "description": _adf_paragraph(description),
                "issuetype": {"name": "Feature"},
            })
            return issue["key"]
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def get_issue(self, key: str) -> dict:
        try:
            return self._jira.issue(key)
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def search_issues(self, jql: str) -> list:
        try:
            return self._jira.jql(jql).get("issues", [])
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def add_comment(self, key: str, body: str) -> None:
        try:
            self._jira.issue_add_comment(key, body)
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def add_remote_link(self, key: str, url: str, title: str) -> None:
        try:
            self._jira.create_or_update_issue_remote_links(
                issue_key=key,
                link_url=url,
                title=title,
            )
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def create_epic(self, summary: str, description: str, parent_key: Optional[str]) -> str:
        fields: dict = {
            "project": {"key": self.project},
            "summary": summary,
            "description": _adf_paragraph(description),
            "issuetype": {"name": "Epic"},
        }
        if parent_key:
            fields["parent"] = {"key": parent_key}
        try:
            issue = self._jira.create_issue(fields=fields)
            return issue["key"]
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def create_story(self, summary: str, description: str, epic_key: str) -> str:
        try:
            issue = self._jira.create_issue(fields={
                "project": {"key": self.project},
                "summary": summary,
                "description": _adf_paragraph(description),
                "issuetype": {"name": "Story"},
                "parent": {"key": epic_key},
            })
            return issue["key"]
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def create_task(self, summary: str, description: str, parent_key: str) -> str:
        try:
            issue = self._jira.create_issue(fields={
                "project": {"key": self.project},
                "summary": summary,
                "description": _adf_paragraph(description),
                "issuetype": {"name": "Task"},
                "parent": {"key": parent_key},
            })
            return issue["key"]
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def create_bug(
        self,
        summary: str,
        actual: str,
        expected: str,
        error: Optional[str] = None,
    ) -> str:
        try:
            issue = self._jira.create_issue(fields={
                "project": {"key": self.project},
                "summary": summary,
                "description": _adf_bug_description(actual, expected, error),
                "issuetype": {"name": "Bug"},
            })
            return issue["key"]
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def attach_file(self, issue_key: str, path: str) -> None:
        try:
            self._jira.issue_attach_file(issue_key, path)
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def get_transitions(self, issue_key: str) -> list[dict]:
        try:
            result = self._jira.get_issue_transitions(issue_key)
            return result.get("transitions", [])
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def transition_issue(self, issue_key: str, status_name: str) -> None:
        transitions = self.get_transitions(issue_key)
        match = next(
            (t for t in transitions if t["name"].lower() == status_name.lower()),
            None,
        )
        if match is None:
            available = [t["name"] for t in transitions]
            raise RuntimeError(
                f"Transition '{status_name}' not found for {issue_key}. "
                f"Available: {available}"
            )
        try:
            self._jira.issue_transition(issue_key, match["id"])
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e
