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
                "description": description,
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

    def search_issues(self, jql: str, fields: Optional[list[str]] = None) -> list:
        try:
            body: dict = {"jql": jql, "maxResults": 100}
            if fields:
                body["fields"] = fields
            else:
                body["fields"] = ["summary", "status", "issuetype", "priority"]
            result = self._jira.post("rest/api/3/search/jql", data=body)
            return result.get("issues", [])
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def get_comments(self, key: str) -> list[dict]:
        try:
            result = self._jira.get(f"rest/api/3/issue/{key}/comment")
            return result.get("comments", [])
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
            "description": description,
            "issuetype": {"name": "Epic THPA"},
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
                "description": description,
                "issuetype": {"name": "Story THPA"},
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
                "description": description,
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
            result = self._jira.get(f"rest/api/2/issue/{issue_key}/transitions")
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
            self._jira.post(
                f"rest/api/2/issue/{issue_key}/transitions",
                data={"transition": {"id": match["id"]}},
            )
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def get_project_statuses(self, project_key: Optional[str] = None) -> list[dict]:
        """Return statuses for the project, deduplicated, ordered by category.

        Each entry: {"name": str, "category_key": str, "category_name": str}
        category_key values: "new" (To Do), "indeterminate" (In Progress), "done" (Done)
        """
        key = project_key or self.project
        try:
            issue_types = self._jira.get(f"rest/api/2/project/{key}/statuses")
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

        _ORDER = {"new": 0, "indeterminate": 1, "done": 2}
        seen: dict[str, dict] = {}
        for itype in issue_types:
            for s in itype.get("statuses", []):
                name = s["name"]
                if name not in seen:
                    cat = s.get("statusCategory", {})
                    seen[name] = {
                        "name": name,
                        "category_key": cat.get("key", ""),
                        "category_name": cat.get("name", ""),
                    }

        return sorted(seen.values(), key=lambda s: (_ORDER.get(s["category_key"], 99), s["name"]))

    def list_links(self, issue_key: str) -> list[dict]:
        try:
            fields = self._jira.issue(issue_key, fields="issuelinks")["fields"]
            links = []
            for lnk in fields.get("issuelinks", []):
                inward = lnk.get("inwardIssue", {})
                outward = lnk.get("outwardIssue", {})
                links.append({
                    "id": lnk["id"],
                    "type": lnk["type"]["name"],
                    "inward_key": inward.get("key", ""),
                    "inward_summary": inward.get("fields", {}).get("summary", ""),
                    "outward_key": outward.get("key", ""),
                    "outward_summary": outward.get("fields", {}).get("summary", ""),
                })
            return links
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def remove_link(self, link_id: str) -> None:
        try:
            self._jira.delete(f"rest/api/2/issueLink/{link_id}")
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def add_link(self, inward_key: str, link_type: str, outward_key: str) -> None:
        try:
            self._jira.create_issue_link(data={
                "type": {"name": link_type},
                "inwardIssue": {"key": inward_key},
                "outwardIssue": {"key": outward_key},
            })
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def create_issue(
        self,
        summary: str,
        description: str,
        issue_type: str,
        parent_key: Optional[str] = None,
    ) -> str:
        fields: dict = {
            "project": {"key": self.project},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
        }
        if parent_key:
            fields["parent"] = {"key": parent_key}
        try:
            issue = self._jira.create_issue(fields=fields)
            return issue["key"]
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def update_description(self, issue_key: str, description: str) -> None:
        try:
            self._jira.put(
                f"rest/api/2/issue/{issue_key}",
                data={"fields": {"description": description}},
            )
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e
