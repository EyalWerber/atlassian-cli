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

    def set_parent(self, issue_key: str, parent_key: Optional[str]) -> None:
        """Re-parent an issue, or detach it when parent_key is None.

        update_issue cannot do this: Jira treats parent as a structural field
        rather than an ordinary editable one. A child must sit at a lower
        hierarchy level than its parent — an Epic (level 1) may parent a Story,
        Task or Feature (level 0), and those may parent a Subtask (level -1),
        but two level-0 issues cannot be nested.
        """
        try:
            self._jira.update_issue_field(
                issue_key, {"parent": {"key": parent_key} if parent_key else None}
            )
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def current_account_id(self) -> str:
        try:
            return self._jira.get("rest/api/3/myself")["accountId"]
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def list_projects(self) -> list[dict]:
        try:
            return [
                {
                    "key": p["key"],
                    "name": p.get("name", ""),
                    "id": p["id"],
                    "style": p.get("style", ""),
                    "type": p.get("projectTypeKey", ""),
                }
                for p in self._jira.projects()
            ]
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def get_project(self, key: str) -> dict:
        try:
            p = self._jira.get(f"rest/api/3/project/{key}")
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e
        return {
            "key": p["key"],
            "name": p.get("name", ""),
            "id": p["id"],
            "style": p.get("style", ""),
            "issue_types": [t["name"] for t in p.get("issueTypes", [])],
        }

    def create_project(
        self,
        key: str,
        name: str,
        share_with: Optional[str] = None,
        description: str = "",
        lead_account_id: Optional[str] = None,
    ) -> dict:
        """Create a Jira project.

        share_with is the key of an existing CLASSIC project whose configuration —
        issue types, workflows, screens — the new project should reuse. Sharing
        copies permission schemes, which the Jira free plan forbids, so it fails
        there with "Changing permission schemes is not allowed". Without
        share_with the default team-managed software template is used, which on
        most sites already includes Epic, Feature, Story, Task, Subtask and Bug.
        """
        lead = lead_account_id or self.current_account_id()
        if share_with:
            source = self.get_project(share_with)
            if source["style"] != "classic":
                raise RuntimeError(
                    f"Cannot share configuration with {share_with}: it is a "
                    f"{source['style']} (team-managed) project. Shared configuration "
                    "requires a classic (company-managed) source project."
                )
            try:
                self._jira.post(
                    f"rest/project-templates/1.0/createshared/{source['id']}",
                    data={
                        "name": name,
                        "key": key,
                        "leadAccountId": lead,
                        "description": description,
                    },
                )
            except Exception as e:
                raise RuntimeError(_friendly_error(e)) from e
        else:
            try:
                self._jira.post(
                    "rest/api/3/project",
                    data={
                        "key": key,
                        "name": name,
                        "leadAccountId": lead,
                        "projectTypeKey": "software",
                        "projectTemplateKey":
                            "com.pyxis.greenhopper.jira:gh-simplified-agility-scrum",
                        "description": description,
                        "assigneeType": "PROJECT_LEAD",
                    },
                )
            except Exception as e:
                raise RuntimeError(_friendly_error(e)) from e
        return self.get_project(key)

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
        priority: Optional[str] = None,
    ) -> str:
        fields: dict = {
            "project": {"key": self.project},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
        }
        if parent_key:
            fields["parent"] = {"key": parent_key}
        if priority:
            fields["priority"] = {"name": priority}
        try:
            issue = self._jira.create_issue(fields=fields)
            new_key = issue["key"]
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

        # If a parent was given and it's a Feature, link the new issue to it.
        # Jira Cloud won't allow Feature→Story parent-child (same hierarchy level),
        # so we use the "implements" link type as a workaround.
        if parent_key and issue_type.lower() in ("story", "bug", "task"):
            try:
                parent_data = self._jira.issue(parent_key, fields="issuetype")
                parent_type = parent_data["fields"]["issuetype"]["name"].lower()
                if parent_type == "feature":
                    self._jira.create_issue_link(data={
                        "type": {"name": "implements"},
                        "inwardIssue": {"key": new_key},
                        "outwardIssue": {"key": parent_key},
                    })
            except Exception:
                pass  # link is best-effort; don't fail the whole create

        return new_key

    def update_issue(
        self,
        issue_key: str,
        priority: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        update_fields: dict = {}
        if priority is not None:
            update_fields["priority"] = {"name": priority}
        if description is not None:
            update_fields["description"] = description
        if not update_fields:
            return
        try:
            self._jira.put(
                f"rest/api/2/issue/{issue_key}",
                data={"fields": update_fields},
            )
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def update_description(self, issue_key: str, description: str) -> None:
        self.update_issue(issue_key, description=description)
