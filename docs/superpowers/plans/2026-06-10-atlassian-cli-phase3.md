# Phase 3: QA Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `atlassian qa` commands that generate human-readable test scenarios from a PRD via Ollama, then let Claude Code file Jira bugs with screenshot/video attachments after running scenarios through Playwright MCP.

**Architecture:** Agent-centric — CLI generates/stores QA plans and files bugs; Claude Code reads the scenarios and drives Playwright MCP. Five tasks, each commits independently. No changes to Phase 1/2 behavior.

**Tech Stack:** Python 3.10+, Typer, Rich, Pydantic v2, pydantic-settings, atlassian-python-api, requests, PyYAML (already installed).

**Spec:** `docs/superpowers/specs/2026-06-10-atlassian-cli-phase3-design.md`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `atlassian_cli/models/qa.py` | `QAPlanStatus`, `QAScenario`, `QAPlan` models |
| Create | `atlassian_cli/commands/qa.py` | `atlassian qa create/show/list/bug` commands |
| Modify | `atlassian_cli/config.py` | Add `qa_base_url: str = ""` |
| Modify | `atlassian_cli/storage/local.py` | Add `qa/` directory init |
| Modify | `atlassian_cli/integrations/ollama.py` | Add `generate_qa_scenarios(prd)` method |
| Modify | `atlassian_cli/integrations/jira.py` | Add `create_bug` + `attach_file` methods |
| Modify | `atlassian_cli/main.py` | Register `qa` sub-app |

---

## Task 1: QA models, config, and storage

**Files:**
- Create: `atlassian_cli/models/qa.py`
- Modify: `atlassian_cli/config.py`
- Modify: `atlassian_cli/storage/local.py`

- [ ] **Step 1: Create `atlassian_cli/models/qa.py`**

```python
from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class QAPlanStatus(str, Enum):
    draft = "draft"
    executed = "executed"


class QAScenario(BaseModel):
    title: str
    steps: list[str]
    expected_result: str
    bug_key: Optional[str] = None
    log_path: Optional[str] = None  # scaffolded — open idea, product-specific


class QAPlan(BaseModel):
    id: str
    feature_id: str
    prd_id: str
    qa_base_url: str
    scenarios: list[QAScenario]
    status: QAPlanStatus = QAPlanStatus.draft
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: Add `qa_base_url` to `atlassian_cli/config.py`**

Add one line after `ollama_model`:

```python
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    memory_db_path: str = "~/.atlassian-cli/memory.db"
    qa_base_url: str = ""
```

- [ ] **Step 3: Add `qa/` directory init to `atlassian_cli/storage/local.py`**

Add one line after the `plans` mkdir:

```python
        (self.base_dir / "features").mkdir(exist_ok=True)
        (self.base_dir / "prds").mkdir(exist_ok=True)
        (self.base_dir / "plans").mkdir(exist_ok=True)
        (self.base_dir / "qa").mkdir(exist_ok=True)
```

- [ ] **Step 4: Verify the imports work**

```powershell
python -c "from atlassian_cli.models.qa import QAPlan, QAScenario, QAPlanStatus; print('OK')"
```

Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git add atlassian_cli/models/qa.py atlassian_cli/config.py atlassian_cli/storage/local.py
git commit -m "feat: add QA models, qa_base_url config, qa storage directory"
```

---

## Task 2: Ollama QA scenario generation

**Files:**
- Modify: `atlassian_cli/integrations/ollama.py`

- [ ] **Step 1: Add module-level schema and system prompt constants**

Add after the existing `_SYSTEM_PROMPT` constant (before the `OllamaClient` class):

```python
_QA_SCENARIO_SCHEMA = """{
  "scenarios": [
    {
      "title": "<short scenario name>",
      "steps": [
        "<action step, e.g. Navigate to /login>",
        "<action step, e.g. Enter 'test@example.com' in the email field>"
      ],
      "expected_result": "<what should happen if the scenario passes>"
    }
  ]
}"""

_QA_SYSTEM_PROMPT = f"""You are a QA planning agent. Given a Product Requirements Document (PRD), \
generate comprehensive test scenarios.

Return ONLY valid JSON matching this schema exactly:
{_QA_SCENARIO_SCHEMA}

Rules:
- Cover happy path, edge cases, and error states
- Steps must be human-readable browser actions (what to click, navigate, enter)
- Each step should be one clear action
- expected_result describes what a passing test looks like
- Do not include code, selectors, or technical implementation details in steps"""
```

- [ ] **Step 2: Add `generate_qa_scenarios` method to `OllamaClient`**

Add this method after `decompose_prd`:

```python
    def generate_qa_scenarios(self, prd: PRD) -> dict:
        user_content = "\n\n".join([
            f"PRD Title: {prd.title}",
            f"Executive Summary: {prd.summary}",
            f"Problem Statement: {prd.problem}",
            f"User Personas: {prd.personas}",
            f"User Stories: {prd.stories}",
            f"Business Value: {prd.business_value}",
            f"Functional Requirements: {prd.requirements}",
            f"Non-Functional Requirements: {prd.nfr}",
            f"Technical Considerations: {prd.considerations}",
            f"Risks: {prd.risks}",
            f"Success Metrics: {prd.metrics}",
            f"Out of Scope: {prd.out_of_scope}",
            f"Future Enhancements: {prd.future_enhancements}",
        ])

        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": _QA_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "format": "json",
                    "stream": False,
                },
                timeout=120,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"Ollama not available at {self.host}. Is it running?")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama request failed: {e}")

        try:
            content = response.json()["message"]["content"]
            return json.loads(content)
        except (KeyError, ValueError) as e:
            raise RuntimeError(f"Ollama returned unexpected response format: {e}")
```

- [ ] **Step 3: Verify the import works**

```powershell
python -c "from atlassian_cli.integrations.ollama import OllamaClient; print('OK')"
```

Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
git add atlassian_cli/integrations/ollama.py
git commit -m "feat: add generate_qa_scenarios to OllamaClient"
```

---

## Task 3: Jira bug filing and attachment

**Files:**
- Modify: `atlassian_cli/integrations/jira.py`

- [ ] **Step 1: Add ADF node helpers after the existing `_adf_paragraph` function**

Add these three functions after `_adf_paragraph`:

```python
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
```

- [ ] **Step 2: Add `create_bug` method to `JiraClient`**

Add after `create_task`:

```python
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
```

- [ ] **Step 3: Add `attach_file` method to `JiraClient`**

Add after `create_bug`:

```python
    def attach_file(self, issue_key: str, path: str) -> None:
        try:
            self._jira.issue_attach_file(issue_key, path)
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e
```

- [ ] **Step 4: Verify the import works**

```powershell
python -c "from atlassian_cli.integrations.jira import JiraClient; print('OK')"
```

Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git add atlassian_cli/integrations/jira.py
git commit -m "feat: add create_bug and attach_file to JiraClient"
```

---

## Task 4: QA commands — create, show, list

**Files:**
- Create: `atlassian_cli/commands/qa.py` (partial — bug command added in Task 5)

- [ ] **Step 1: Create `atlassian_cli/commands/qa.py` with helpers and `create` command**

```python
from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.ollama import OllamaClient
from atlassian_cli.models.feature import Feature
from atlassian_cli.models.prd import PRD
from atlassian_cli.models.qa import QAPlan, QAPlanStatus, QAScenario
from atlassian_cli.storage.local import LocalStorage

app = typer.Typer(help="Generate and manage QA plans")
console = Console()


def _build_scenarios(scenarios_data: list[dict]) -> list[QAScenario]:
    return [
        QAScenario(
            title=s["title"],
            steps=s["steps"],
            expected_result=s["expected_result"],
        )
        for s in scenarios_data
    ]


def _build_qa_plan(
    raw: dict, feature_id: str, prd_id: str, qa_base_url: str, storage: LocalStorage
) -> QAPlan:
    now = datetime.now(timezone.utc)
    plan_id = storage.next_id("QA", "qa")
    return QAPlan(
        id=plan_id,
        feature_id=feature_id,
        prd_id=prd_id,
        qa_base_url=qa_base_url,
        scenarios=_build_scenarios(raw["scenarios"]),
        created_at=now,
        updated_at=now,
    )


@app.command("create")
def create(
    feature_id: str = typer.Argument(..., help="Feature ID (e.g. FEAT-001)"),
) -> None:
    storage = LocalStorage()

    feature = storage.load(Feature, "features", feature_id)
    if not feature:
        console.print(f"[red]✗[/red]  Feature [bold]{feature_id}[/bold] not found")
        raise typer.Exit(1)

    if not feature.prd_id:
        console.print(
            f"[red]✗[/red]  Feature [bold]{feature_id}[/bold] has no linked PRD."
        )
        raise typer.Exit(1)

    prd = storage.load(PRD, "prds", feature.prd_id)
    if not prd:
        console.print(f"[red]✗[/red]  PRD [bold]{feature.prd_id}[/bold] not found")
        raise typer.Exit(1)

    settings = get_settings()

    with console.status("[bold green]Generating QA scenarios with Ollama...[/bold green]"):
        try:
            ollama = OllamaClient(settings)
            raw = ollama.generate_qa_scenarios(prd)
        except RuntimeError as e:
            console.print(f"[red]✗[/red]  {e}")
            raise typer.Exit(1)

    try:
        plan = _build_qa_plan(raw, feature_id, feature.prd_id, settings.qa_base_url, storage)
    except (ValueError, KeyError, TypeError):
        console.print("[red]✗[/red]  Ollama returned invalid QA scenarios. Try again.")
        raise typer.Exit(1)

    storage.save(plan, "qa")
    console.print(f"[green]✓[/green] QA Plan saved  [{plan.id}]")
    if plan.qa_base_url:
        console.print(f"[dim]Target URL: {plan.qa_base_url}[/dim]")

    tree = Tree(f"[cyan]{plan.id}[/cyan] — [white]{plan.feature_id}[/white]")
    for scenario in plan.scenarios:
        branch = tree.add(f"[bold]{scenario.title}[/bold]")
        for i, step in enumerate(scenario.steps, 1):
            branch.add(f"[dim]{i}.[/dim] {step}")
        branch.add(f"[green]Expected:[/green] {scenario.expected_result}")
    console.print(tree)
```

- [ ] **Step 2: Add `show` command to `atlassian_cli/commands/qa.py`**

Append to the file:

```python
@app.command("show")
def show(id: str = typer.Argument(..., help="QA Plan ID (e.g. QA-001)")) -> None:
    storage = LocalStorage()
    plan = storage.load(QAPlan, "qa", id)
    if not plan:
        console.print(f"[red]✗[/red]  QA Plan [bold]{id}[/bold] not found")
        raise typer.Exit(1)

    status_color = "green" if plan.status == QAPlanStatus.executed else "yellow"
    header = (
        f"[cyan]{plan.id}[/cyan]  [white]{plan.feature_id}[/white]  "
        f"[{status_color}]{plan.status.value}[/{status_color}]"
    )
    if plan.qa_base_url:
        header += f"  [dim]{plan.qa_base_url}[/dim]"
    tree = Tree(header)

    for scenario in plan.scenarios:
        bug_label = (
            f"  [red]{scenario.bug_key}[/red]"
            if scenario.bug_key
            else "  [dim]no bug[/dim]"
        )
        branch = tree.add(f"[bold]{scenario.title}[/bold]{bug_label}")
        for i, step in enumerate(scenario.steps, 1):
            branch.add(f"[dim]{i}.[/dim] {step}")
        branch.add(f"[green]Expected:[/green] {scenario.expected_result}")

    console.print(tree)
```

- [ ] **Step 3: Add `list` command to `atlassian_cli/commands/qa.py`**

Append to the file:

```python
@app.command("list")
def list_plans() -> None:
    storage = LocalStorage()
    plans = storage.list_all(QAPlan, "qa")
    if not plans:
        console.print("[dim]No QA plans found.[/dim]")
        return

    table = Table(title="QA Plans", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Feature")
    table.add_column("Status")
    table.add_column("Scenarios", justify="right")
    table.add_column("Created")

    for p in plans:
        status_str = (
            f"[green]{p.status.value}[/green]"
            if p.status == QAPlanStatus.executed
            else p.status.value
        )
        table.add_row(
            p.id,
            p.feature_id,
            status_str,
            str(len(p.scenarios)),
            p.created_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)
```

- [ ] **Step 4: Verify the import works**

```powershell
python -c "from atlassian_cli.commands.qa import app; print('OK')"
```

Expected output: `OK`

- [ ] **Step 5: Commit**

```bash
git add atlassian_cli/commands/qa.py
git commit -m "feat: add qa create/show/list commands"
```

---

## Task 5: QA bug command + wire main.py

**Files:**
- Modify: `atlassian_cli/commands/qa.py` (add `bug` command + `JiraClient` import)
- Modify: `atlassian_cli/main.py`

- [ ] **Step 1: Add `JiraClient` import to the top of `atlassian_cli/commands/qa.py`**

The existing imports block becomes:

```python
from atlassian_cli.config import get_settings
from atlassian_cli.integrations.jira import JiraClient
from atlassian_cli.integrations.ollama import OllamaClient
from atlassian_cli.models.feature import Feature
from atlassian_cli.models.prd import PRD
from atlassian_cli.models.qa import QAPlan, QAPlanStatus, QAScenario
from atlassian_cli.storage.local import LocalStorage
```

- [ ] **Step 2: Append `bug` command to `atlassian_cli/commands/qa.py`**

```python
@app.command("bug")
def bug(
    qa_id: str = typer.Argument(..., help="QA Plan ID (e.g. QA-001)"),
    scenario: str = typer.Option(..., "--scenario", help="Scenario title to link bug to"),
    actual: str = typer.Option(..., "--actual", help="Actual results"),
    expected: str = typer.Option(..., "--expected", help="Expected results"),
    error: Optional[str] = typer.Option(None, "--error", help="Error or stack trace text"),
    screenshot: Optional[str] = typer.Option(None, "--screenshot", help="Path to screenshot file"),
    video: Optional[str] = typer.Option(None, "--video", help="Path to video file"),
) -> None:
    storage = LocalStorage()
    plan = storage.load(QAPlan, "qa", qa_id)
    if not plan:
        console.print(f"[red]✗[/red]  QA Plan [bold]{qa_id}[/bold] not found")
        raise typer.Exit(1)

    matched = next((s for s in plan.scenarios if s.title == scenario), None)
    if matched is None:
        console.print(f"[red]✗[/red]  Scenario '{scenario}' not found in {qa_id}.")
        raise typer.Exit(1)

    settings = get_settings()
    jira = JiraClient(settings)

    try:
        bug_key = jira.create_bug(
            summary=f"[{qa_id}] {scenario}",
            actual=actual,
            expected=expected,
            error=error,
        )
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] Bug filed: {bug_key}")

    for label, path in [("screenshot", screenshot), ("video", video)]:
        if path:
            try:
                jira.attach_file(bug_key, path)
                console.print(f"[green]✓[/green] {label.capitalize()} attached")
            except RuntimeError as e:
                console.print(f"[yellow]⚠[/yellow]  Failed to attach {label}: {e}")

    matched.bug_key = bug_key
    storage.save(
        plan.model_copy(update={"updated_at": datetime.now(timezone.utc)}),
        "qa",
    )
    console.print(f"[green]✓[/green] QA Plan updated  [{qa_id}]")
```

- [ ] **Step 3: Register `qa` sub-app in `atlassian_cli/main.py`**

The imports line becomes:

```python
from atlassian_cli.commands import feature, prd, plan, qa
```

Add after `app.add_typer(plan.app, name="plan")`:

```python
app.add_typer(qa.app, name="qa")
```

- [ ] **Step 4: Verify CLI is wired correctly**

```powershell
atlassian qa --help
```

Expected output (roughly):
```
 Usage: atlassian qa [OPTIONS] COMMAND [ARGS]...

 Generate and manage QA plans

╭─ Commands ───────────────────────────────────────────────╮
│ bug     │
│ create  │
│ list    │
│ show    │
╰──────────────────────────────────────────────────────────╯
```

```powershell
atlassian qa bug --help
```

Expected: shows `--scenario`, `--actual`, `--expected`, `--error`, `--screenshot`, `--video` options.

- [ ] **Step 5: Commit**

```bash
git add atlassian_cli/commands/qa.py atlassian_cli/main.py
git commit -m "feat: add qa bug command, register qa sub-app in main"
```

- [ ] **Step 6: Push to origin**

```bash
git push origin master
```

---

## How Claude Code uses Phase 3

After implementation, the workflow for Claude Code is:

```bash
# 1. Generate QA scenarios for a feature
atlassian qa create FEAT-001

# 2. Read the plan to get scenarios + target URL
atlassian qa show QA-001

# 3. For each scenario: drive Playwright MCP through the steps
#    (Claude Code reads steps and navigates/clicks/types accordingly)
#    If the scenario fails after 3 retries, call:
atlassian qa bug QA-001 \
  --scenario "Login happy path" \
  --actual "Page shows 500 error" \
  --expected "Redirect to /dashboard" \
  --error "TypeError: Cannot read properties of undefined" \
  --screenshot /tmp/shot.png \
  --video /tmp/video.webm

# 4. After all scenarios tested, mark plan as executed (future: atlassian qa done QA-001)
```
