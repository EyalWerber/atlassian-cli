# Phase 6b: Issue Update Description Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `atlassian issue update KEY --description "..."` so Claude can write the Confluence PRD URL back into a Jira issue's description field after publishing.

**Architecture:** One new `update_description(key, description)` method on `JiraClient` using a raw PUT to `rest/api/2/issue/{key}`. One new `update` subcommand on the existing `issue` Typer app in `commands/issue.py`. No new files.

**Tech Stack:** Python 3.10+, Typer, atlassian-python-api (raw PUT), pytest 8.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `atlassian_cli/integrations/jira.py` | Add `update_description(key, description)` |
| Modify | `atlassian_cli/commands/issue.py` | Add `update` subcommand with `--description` option |
| Modify | `tests/test_phase6.py` | Add two new tests |

---

## Task 1: Add `update_description` to JiraClient

**Files:**
- Modify: `atlassian_cli/integrations/jira.py`
- Modify: `tests/test_phase6.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_phase6.py`:

```python
def test_update_description_puts_correct_payload():
    client = _client()
    client._jira.put.return_value = None
    client.update_description("SI-5", "PRD: https://eyal-werber.atlassian.net/wiki/spaces/SIDEV/pages/123")
    client._jira.put.assert_called_once_with(
        "rest/api/2/issue/SI-5",
        data={"fields": {"description": "PRD: https://eyal-werber.atlassian.net/wiki/spaces/SIDEV/pages/123"}},
    )
```

- [ ] **Step 2: Run test — expect FAIL**

```
pytest tests/test_phase6.py::test_update_description_puts_correct_payload -v
```

Expected: `AttributeError: Mock object has no attribute 'update_description'`

- [ ] **Step 3: Add method to JiraClient (append after `add_link`)**

```python
def update_description(self, issue_key: str, description: str) -> None:
    try:
        self._jira.put(
            f"rest/api/2/issue/{issue_key}",
            data={"fields": {"description": description}},
        )
    except Exception as e:
        raise RuntimeError(_friendly_error(e)) from e
```

- [ ] **Step 4: Run test — expect PASS**

```
pytest tests/test_phase6.py::test_update_description_puts_correct_payload -v
```

- [ ] **Step 5: Commit**

```bash
git add atlassian_cli/integrations/jira.py tests/test_phase6.py
git commit -m "feat: add update_description to JiraClient"
```

---

## Task 2: Add `atlassian issue update` command

**Files:**
- Modify: `atlassian_cli/commands/issue.py`
- Modify: `tests/test_phase6.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_phase6.py`:

```python
def test_issue_update_description_command():
    with patch("atlassian_cli.commands.issue.JiraClient") as MockJira, \
         patch("atlassian_cli.commands.issue.get_settings"):
        MockJira.return_value.update_description.return_value = None
        result = runner.invoke(issue_app, [
            "update", "SI-5",
            "--description", "PRD: https://confluence.example.com/page/123",
        ])
        assert result.exit_code == 0
        assert "SI-5" in result.output
        MockJira.return_value.update_description.assert_called_once_with(
            "SI-5", "PRD: https://confluence.example.com/page/123"
        )
```

- [ ] **Step 2: Run test — expect FAIL**

```
pytest tests/test_phase6.py::test_issue_update_description_command -v
```

Expected: `SystemExit(2)` — command doesn't exist yet.

- [ ] **Step 3: Add `update` command to `atlassian_cli/commands/issue.py`**

Add after the `show` command:

```python
@app.command("update")
def update(
    key: str = typer.Argument(..., help="Issue key, e.g. SI-5"),
    description: Optional[str] = typer.Option(None, "--description", help="New description text"),
) -> None:
    """Update fields on a Jira issue."""
    if description is None:
        console.print("[red]✗[/red]  Nothing to update. Use --description \"...\"")
        raise typer.Exit(1)
    jira = JiraClient(get_settings())
    try:
        jira.update_description(key, description)
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] {key} description updated")
```

- [ ] **Step 4: Run all Phase 6 tests — expect PASS**

```
pytest tests/test_phase6.py -v
```

Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add atlassian_cli/commands/issue.py tests/test_phase6.py
git commit -m "feat: add issue update --description command (Phase 6b)"
```

---

## Self-Review

**Spec coverage:** ✅ `update_description` on JiraClient, ✅ `atlassian issue update KEY --description`, ✅ tests for both, ✅ no placeholders.

**Type consistency:** `update_description(issue_key: str, description: str) -> None` matches usage in the command.
