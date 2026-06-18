# Phase 6: Issue Lifecycle Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `atlassian issue` subcommands so Claude can fully manage Jira issue lifecycle — transition status, comment, show details, and manage blocking links — all without raw Python or API calls.

**Architecture:** New commands land in the existing `atlassian_cli/commands/issue.py` scaffold (already registered in `main.py`). Two bugs in `JiraClient` must be fixed first: `get_transitions` calls `.get("transitions", [])` on a raw list (returns empty), and `transition_issue` delegates to `self._jira.issue_transition()` which is broken in the atlassian-python-api library. Both are replaced with direct `self._jira.post/get` REST calls. New JiraClient methods (`list_links`, `remove_link`, `add_link`) follow the same pattern.

**Tech Stack:** Python 3.10+, Typer, Rich, atlassian-python-api (for auth/session only — REST calls done directly), pytest 8.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `atlassian_cli/integrations/jira.py` | Fix `get_transitions`, fix `transition_issue`, add `list_links`, `remove_link`, `add_link` |
| Modify | `atlassian_cli/commands/issue.py` | Add `comment`, `show`, `link`, `unlink` commands; fix `transition` + `transitions` |
| Modify | `README.md` | Document Phase 6 commands under `### Issues` section |
| Create | `tests/test_phase6.py` | Unit tests with mocked JiraClient |

---

## Task 1: Fix JiraClient — `get_transitions` and `transition_issue`

**Files:**
- Modify: `atlassian_cli/integrations/jira.py`
- Create: `tests/test_phase6.py`

The `atlassian-python-api` library's `get_issue_transitions` returns a **list** directly, not a dict — so `.get("transitions", [])` always returns `[]`. And `issue_transition()` in the library mangles the transition ID. Both must use raw REST calls.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_phase6.py
from unittest.mock import MagicMock, patch
import pytest
from atlassian_cli.integrations.jira import JiraClient
from atlassian_cli.config import Settings


def _client() -> JiraClient:
    settings = MagicMock(spec=Settings)
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
```

- [ ] **Step 2: Run tests — expect FAIL**

```
pytest tests/test_phase6.py -v
```

Expected: FAIL — `get_transitions` returns `[]`, `transition_issue` calls wrong method.

- [ ] **Step 3: Fix `get_transitions` and `transition_issue` in `jira.py`**

Replace the two methods (lines 171–193) with:

```python
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
```

- [ ] **Step 4: Run tests — expect PASS**

```
pytest tests/test_phase6.py::test_get_transitions_returns_list tests/test_phase6.py::test_transition_issue_posts_correct_payload tests/test_phase6.py::test_transition_issue_raises_on_unknown_status -v
```

- [ ] **Step 5: Commit**

```bash
git add atlassian_cli/integrations/jira.py tests/test_phase6.py
git commit -m "fix: get_transitions and transition_issue use direct REST calls"
```

---

## Task 2: Add `list_links`, `remove_link`, `add_link` to JiraClient

**Files:**
- Modify: `atlassian_cli/integrations/jira.py`
- Modify: `tests/test_phase6.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_phase6.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect FAIL**

```
pytest tests/test_phase6.py::test_list_links_returns_parsed_links tests/test_phase6.py::test_remove_link_calls_delete tests/test_phase6.py::test_add_link_creates_blocks_relationship -v
```

Expected: FAIL — methods don't exist yet.

- [ ] **Step 3: Add methods to `JiraClient` (append after `attach_file`)**

```python
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
```

- [ ] **Step 4: Run tests — expect PASS**

```
pytest tests/test_phase6.py -v
```

- [ ] **Step 5: Commit**

```bash
git add atlassian_cli/integrations/jira.py tests/test_phase6.py
git commit -m "feat: add list_links, remove_link, add_link to JiraClient"
```

---

## Task 3: Complete `issue.py` commands

**Files:**
- Modify: `atlassian_cli/commands/issue.py`
- Modify: `tests/test_phase6.py`

Add `comment`, `show`, `link`, `unlink` commands. The `transition` and `transitions` commands already exist in the scaffold — they work correctly once the JiraClient methods are fixed in Task 1.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_phase6.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect FAIL**

```
pytest tests/test_phase6.py::test_issue_comment_command tests/test_phase6.py::test_issue_show_command tests/test_phase6.py::test_issue_link_command tests/test_phase6.py::test_issue_unlink_command_removes_matching_link -v
```

Expected: FAIL — commands don't exist yet.

- [ ] **Step 3: Replace `atlassian_cli/commands/issue.py` with full implementation**

```python
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.jira import JiraClient

app = typer.Typer(help="Manage Jira issue lifecycle")
console = Console()


@app.command("transition")
def transition(
    key: str = typer.Argument(..., help="Issue key, e.g. SI-42"),
    status: str = typer.Argument(..., help="Target status: 'To Do', 'In Progress', 'In Review', 'Done'"),
) -> None:
    """Transition an issue to a new status."""
    jira = JiraClient(get_settings())
    try:
        jira.transition_issue(key, status)
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] {key} → {status}")


@app.command("transitions")
def transitions(
    key: str = typer.Argument(..., help="Issue key, e.g. SI-42"),
) -> None:
    """List available status transitions for an issue."""
    jira = JiraClient(get_settings())
    try:
        result = jira.get_transitions(key)
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
    table = Table(title=f"Transitions for {key}", show_lines=False)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Name")
    table.add_column("To Status")
    for t in result:
        table.add_row(t.get("id", ""), t.get("name", ""), t.get("to", {}).get("name", ""))
    console.print(table)


@app.command("comment")
def comment(
    key: str = typer.Argument(..., help="Issue key, e.g. SI-42"),
    body: str = typer.Argument(..., help="Comment text"),
) -> None:
    """Add a comment to a Jira issue."""
    jira = JiraClient(get_settings())
    try:
        jira.add_comment(key, body)
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Comment added to {key}")


@app.command("show")
def show(
    key: str = typer.Argument(..., help="Issue key, e.g. SI-42"),
) -> None:
    """Show details of a Jira issue including links."""
    jira = JiraClient(get_settings())
    try:
        issue = jira.get_issue(key)
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
    fields = issue["fields"]
    assignee = (fields.get("assignee") or {}).get("displayName", "—")
    priority = (fields.get("priority") or {}).get("name", "—")
    links = fields.get("issuelinks", [])
    link_lines = []
    for lnk in links:
        ltype = lnk["type"]["name"]
        if "outwardIssue" in lnk:
            other = lnk["outwardIssue"]
            link_lines.append(f"  {ltype} → {other['key']} {other['fields']['summary']}")
        if "inwardIssue" in lnk:
            other = lnk["inwardIssue"]
            link_lines.append(f"  ← {ltype} {other['key']} {other['fields']['summary']}")
    links_text = "\n".join(link_lines) if link_lines else "  —"
    console.print(Panel(
        f"[bold]Summary:[/bold]   {fields['summary']}\n"
        f"[bold]Type:[/bold]      {fields['issuetype']['name']}\n"
        f"[bold]Status:[/bold]    {fields['status']['name']}\n"
        f"[bold]Priority:[/bold]  {priority}\n"
        f"[bold]Assignee:[/bold]  {assignee}\n"
        f"[bold]Links:[/bold]\n{links_text}",
        title=f"[cyan]{key}[/cyan]",
    ))


@app.command("link")
def link(
    key: str = typer.Argument(..., help="Source issue key, e.g. SI-11"),
    blocks: Optional[str] = typer.Option(None, "--blocks", help="Issue key this blocks, e.g. SI-8"),
) -> None:
    """Add a link between issues (currently supports --blocks)."""
    if not blocks:
        console.print("[red]✗[/red]  Specify a link type: --blocks KEY")
        raise typer.Exit(1)
    jira = JiraClient(get_settings())
    try:
        jira.add_link(key, "Blocks", blocks)
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] {key} blocks {blocks}")


@app.command("unlink")
def unlink(
    key: str = typer.Argument(..., help="Source issue key, e.g. SI-11"),
    blocks: Optional[str] = typer.Option(None, "--blocks", help="Issue key to unblock, e.g. SI-8"),
) -> None:
    """Remove a link between issues."""
    if not blocks:
        console.print("[red]✗[/red]  Specify a link type to remove: --blocks KEY")
        raise typer.Exit(1)
    jira = JiraClient(get_settings())
    try:
        links = jira.list_links(key)
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
    match = next(
        (lnk for lnk in links
         if lnk["type"] == "Blocks" and lnk["outward_key"] == blocks),
        None,
    )
    if not match:
        console.print(f"[yellow]⚠[/yellow]  No 'Blocks' link from {key} to {blocks} found")
        raise typer.Exit(1)
    try:
        jira.remove_link(match["id"])
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Removed: {key} no longer blocks {blocks}")
```

- [ ] **Step 4: Run all Phase 6 tests — expect PASS**

```
pytest tests/test_phase6.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add atlassian_cli/commands/issue.py tests/test_phase6.py
git commit -m "feat: add issue comment/show/link/unlink commands (Phase 6)"
```

---

## Task 4: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add `### Issues` section to README after `### QA`**

```markdown
### Issues

```bash
# Show issue details and links
atlassian issue show SI-42

# Transition status (available: To Do, In Progress, In Review, Done)
atlassian issue transition SI-42 "In Progress"

# List available transitions
atlassian issue transitions SI-42

# Add a comment
atlassian issue comment SI-42 "Fixed by refactoring the auth middleware."

# Add a blocking link (SI-11 blocks SI-8)
atlassian issue link SI-11 --blocks SI-8

# Remove a blocking link
atlassian issue unlink SI-11 --blocks SI-8
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add Phase 6 issue lifecycle commands to README"
```

---

## Self-Review

**Spec coverage:**
- ✅ `transition` command (with bug fix)
- ✅ `comment` command
- ✅ `show` command with links
- ✅ `link --blocks` command
- ✅ `unlink --blocks` command
- ✅ `list_links`, `remove_link`, `add_link` in JiraClient
- ✅ Fix for broken `get_transitions` / `transition_issue`
- ✅ Tests for all new JiraClient methods and all CLI commands
- ✅ README updated

**Placeholder scan:** None found — all steps have exact code.

**Type consistency:** `list_links` returns `list[dict]` with keys `id`, `type`, `inward_key`, `outward_key`, `inward_summary`, `outward_summary` — used consistently in `unlink` command and tests.
