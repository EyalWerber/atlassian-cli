# atlassian-cli Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Ollama-powered planning agent (`atlassian plan create FEAT-001`) that decomposes a PRD into a three-level Jira hierarchy (Epic → Story → Task) with interactive YAML review before creation.

**Architecture:** Three new files following Phase 1 patterns (`models/plan.py`, `integrations/ollama.py`, `commands/plan.py`), minimal additions to `integrations/jira.py` and `main.py`, plus `pyyaml` dependency for the editor review flow. No existing Phase 1 code is broken.

**Tech Stack:** Python 3.11+, Typer, Rich, Pydantic v2, pyyaml, requests (transitive), Ollama HTTP API (Qwen 3), atlassian-python-api

> **Note on tests:** Per the spec, no automated tests in Phase 2. Each task has a manual verification step instead.

---

## File Map

| File | Change | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | Add `pyyaml>=6` dependency |
| `atlassian_cli/storage/local.py` | Modify | Create `plans/` directory on init |
| `atlassian_cli/models/plan.py` | Create | `Plan`, `Epic`, `Story`, `Task` Pydantic models |
| `atlassian_cli/integrations/ollama.py` | Create | Ollama HTTP wrapper — sends PRD, returns structured JSON |
| `atlassian_cli/integrations/jira.py` | Modify | Add `_adf_paragraph` helper + `create_epic`, `create_story`, `create_task` |
| `atlassian_cli/commands/plan.py` | Create | `atlassian plan create/show/list` commands |
| `atlassian_cli/main.py` | Modify | Register `plan` sub-app |

---

## Task 1: Add pyyaml + Plans Storage Directory

**Files:**
- Modify: `pyproject.toml`
- Modify: `atlassian_cli/storage/local.py`

The editor review flow writes the plan as YAML for human editing. `pyyaml` is not currently in dependencies — add it explicitly. `LocalStorage.__init__` only creates `features/` and `prds/` — add `plans/` so `next_id` and `save` work without a missing-directory error.

- [ ] **Step 1: Add pyyaml to `pyproject.toml`**

Replace the `dependencies` list:

```toml
dependencies = [
    "typer[all]>=0.12",
    "rich>=13",
    "pydantic>=2",
    "pydantic-settings>=2",
    "atlassian-python-api>=3.41",
    "python-dotenv>=1.0",
    "pyyaml>=6",
]
```

- [ ] **Step 2: Add plans directory to `atlassian_cli/storage/local.py`**

Replace the `__init__` method body (lines 9–13):

```python
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path.home() / ".atlassian-cli"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "features").mkdir(exist_ok=True)
        (self.base_dir / "prds").mkdir(exist_ok=True)
        (self.base_dir / "plans").mkdir(exist_ok=True)
```

- [ ] **Step 3: Reinstall and verify**

```bash
pip install -e .
python -c "import yaml; from atlassian_cli.storage.local import LocalStorage; s = LocalStorage(); print('plans dir:', (s.base_dir / 'plans').exists())"
```

Expected: `plans dir: True`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml atlassian_cli/storage/local.py
git commit -m "feat: add pyyaml dependency and plans storage directory"
```

---

## Task 2: Plan Model

**Files:**
- Create: `atlassian_cli/models/plan.py`

`Task`, `Story`, `Epic` are nested inside `Plan`. Only `Plan` gets a local ID (`PLAN-001`). `jira_key` fields start as `None` and are populated during Jira creation.

- [ ] **Step 1: Create `atlassian_cli/models/plan.py`**

```python
from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PlanStatus(str, Enum):
    draft = "draft"
    created = "created"


class Task(BaseModel):
    title: str
    description: str
    jira_key: Optional[str] = None


class Story(BaseModel):
    title: str
    description: str
    tasks: list[Task]
    jira_key: Optional[str] = None


class Epic(BaseModel):
    title: str
    description: str
    stories: list[Story]
    jira_key: Optional[str] = None


class Plan(BaseModel):
    id: str
    feature_id: str
    prd_id: str
    epics: list[Epic]
    status: PlanStatus = PlanStatus.draft
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: Verify models parse correctly**

```bash
python -c "
from atlassian_cli.models.plan import Plan, Epic, Story, Task, PlanStatus
from datetime import datetime, timezone

now = datetime.now(timezone.utc)
task = Task(title='Implement JWT', description='Add JWT middleware')
story = Story(title='Login flow', description='Handle login', tasks=[task])
epic = Epic(title='v1.0 - Auth', description='Auth release', stories=[story])
plan = Plan(id='PLAN-001', feature_id='FEAT-001', prd_id='PRD-001',
            epics=[epic], created_at=now, updated_at=now)
print(plan.model_dump_json(indent=2))
"
```

Expected: JSON output with the full nested structure.

- [ ] **Step 3: Commit**

```bash
git add atlassian_cli/models/plan.py
git commit -m "feat: add Plan/Epic/Story/Task Pydantic models"
```

---

## Task 3: Ollama Integration

**Files:**
- Create: `atlassian_cli/integrations/ollama.py`

One public method: `decompose_prd(prd: PRD) -> dict`. Uses `requests` (transitive dep via `atlassian-python-api`) — no new HTTP dependency. Sends the PRD sections as labeled text with the expected JSON schema embedded in the system prompt. `"format": "json"` on the request body ensures Qwen 3 returns valid JSON.

- [ ] **Step 1: Create `atlassian_cli/integrations/ollama.py`**

```python
import json
import requests
from atlassian_cli.config import Settings
from atlassian_cli.models.prd import PRD


_SCHEMA = """{
  "epics": [
    {
      "title": "<version name, e.g. v1.0 - Feature Name>",
      "description": "<version goal>",
      "stories": [
        {
          "title": "<feature name>",
          "description": "<what to build>",
          "tasks": [
            { "title": "<task name>", "description": "<implementation detail>" }
          ]
        }
      ]
    }
  ]
}"""

_SYSTEM_PROMPT = f"""You are a software planning agent. Given a Product Requirements Document (PRD), \
decompose it into a structured implementation plan.

Return ONLY valid JSON matching this schema exactly:
{_SCHEMA}

Rules:
- Each Epic represents a version or release milestone
- Each Story represents a feature within that version
- Each Task is a concrete implementation unit
- Every Story must have at least one Task
- Every Epic must have at least one Story
- Do not include jira_key fields"""


class OllamaClient:
    def __init__(self, settings: Settings):
        self.host = settings.ollama_host
        self.model = settings.ollama_model

    def decompose_prd(self, prd: PRD) -> dict:
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
                        {"role": "system", "content": _SYSTEM_PROMPT},
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

        content = response.json()["message"]["content"]
        return json.loads(content)
```

- [ ] **Step 2: Verify import (no Ollama running needed)**

```bash
python -c "from atlassian_cli.integrations.ollama import OllamaClient; print('Ollama import OK')"
```

Expected: `Ollama import OK`

- [ ] **Step 3: Commit**

```bash
git add atlassian_cli/integrations/ollama.py
git commit -m "feat: add Ollama integration wrapper for PRD decomposition"
```

---

## Task 4: Jira Integration Additions

**Files:**
- Modify: `atlassian_cli/integrations/jira.py`

Extract the repeated ADF inline dict into a module-level `_adf_paragraph` helper, update `create_initiative` to use it, then add `create_epic`, `create_story`, `create_task`. All three new methods use the `parent` field (next-gen/team-managed Jira). If `parent_key` is `None` (feature created with `--no-jira`), `create_epic` skips the parent field rather than failing.

- [ ] **Step 1: Add `_adf_paragraph` helper and refactor `create_initiative`**

Add the helper function after `_friendly_error` (before the `JiraClient` class):

```python
def _adf_paragraph(text: str) -> dict:
    return {
        "version": 1,
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }
```

Then update `create_initiative` inside `JiraClient` to use it:

```python
    def create_initiative(self, summary: str, description: str) -> str:
        """Create an Initiative issue. Returns the issue key."""
        try:
            issue = self._jira.create_issue(fields={
                "project": {"key": self.project},
                "summary": summary,
                "description": _adf_paragraph(description),
                "issuetype": {"name": "Initiative"},
            })
            return issue["key"]
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e
```

- [ ] **Step 2: Add `create_epic`, `create_story`, `create_task` to `JiraClient`**

Append these three methods to the `JiraClient` class (after `add_remote_link`):

```python
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
```

Also add `Optional` to the import at the top of `jira.py`:

```python
from typing import Optional
```

- [ ] **Step 3: Verify import**

```bash
python -c "from atlassian_cli.integrations.jira import JiraClient; print('Jira import OK')"
```

Expected: `Jira import OK`

- [ ] **Step 4: Commit**

```bash
git add atlassian_cli/integrations/jira.py
git commit -m "feat: add create_epic/story/task to JiraClient, extract _adf_paragraph helper"
```

---

## Task 5: Plan Commands

**Files:**
- Create: `atlassian_cli/commands/plan.py`

This is the largest file. It contains three commands (`create`, `show`, `list`) and three private helpers (`_build_plan`, `_plan_to_yaml_dict` + `_yaml_dict_to_plan`, `_editor_review`, `_create_in_jira`).

**`create` flow:**
1. Load Feature → resolve PRD
2. Call Ollama → validate into `Plan`
3. Prompt: review in editor? → if yes, open `$EDITOR` with temp YAML
4. If `--save`, persist to `~/.atlassian-cli/plans/`
5. Prompt: create in Jira? → if yes, create Epic → Story → Task with live output, save after each Epic

**`show`:** Rich tree with jira_keys displayed inline.

**`list`:** Table with Epic/Story/Task counts.

- [ ] **Step 1: Create `atlassian_cli/commands/plan.py`**

```python
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from atlassian_cli.config import Settings, get_settings
from atlassian_cli.integrations.jira import JiraClient
from atlassian_cli.integrations.ollama import OllamaClient
from atlassian_cli.models.feature import Feature
from atlassian_cli.models.plan import Epic, Plan, PlanStatus, Story, Task
from atlassian_cli.models.prd import PRD
from atlassian_cli.storage.local import LocalStorage

app = typer.Typer(help="Generate and manage plans")
console = Console()


def _build_plan(raw: dict, feature_id: str, prd_id: str, storage: LocalStorage) -> Plan:
    now = datetime.now(timezone.utc)
    plan_id = storage.next_id("PLAN", "plans")
    epics = []
    for e in raw["epics"]:
        stories = []
        for s in e["stories"]:
            tasks = [Task(title=t["title"], description=t["description"]) for t in s["tasks"]]
            stories.append(Story(title=s["title"], description=s["description"], tasks=tasks))
        epics.append(Epic(title=e["title"], description=e["description"], stories=stories))
    return Plan(
        id=plan_id,
        feature_id=feature_id,
        prd_id=prd_id,
        epics=epics,
        created_at=now,
        updated_at=now,
    )


def _plan_to_yaml_dict(plan: Plan) -> dict:
    return {
        "epics": [
            {
                "title": epic.title,
                "description": epic.description,
                "stories": [
                    {
                        "title": story.title,
                        "description": story.description,
                        "tasks": [
                            {"title": task.title, "description": task.description}
                            for task in story.tasks
                        ],
                    }
                    for story in epic.stories
                ],
            }
            for epic in plan.epics
        ]
    }


def _yaml_dict_to_plan(data: dict, plan: Plan) -> Plan:
    epics = []
    for e in data["epics"]:
        stories = []
        for s in e["stories"]:
            tasks = [Task(title=t["title"], description=t["description"]) for t in s["tasks"]]
            stories.append(Story(title=s["title"], description=s["description"], tasks=tasks))
        epics.append(Epic(title=e["title"], description=e["description"], stories=stories))
    return plan.model_copy(update={"epics": epics, "updated_at": datetime.now(timezone.utc)})


def _editor_review(plan: Plan) -> Plan:
    yaml_data = _plan_to_yaml_dict(plan)
    with tempfile.NamedTemporaryFile(
        suffix=".yaml", mode="w", delete=False, encoding="utf-8"
    ) as f:
        yaml.dump(yaml_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        tmp_path = f.name

    editor = os.environ.get("EDITOR", "notepad" if os.name == "nt" else "nano")
    subprocess.run([editor, tmp_path], check=False)

    try:
        with open(tmp_path, encoding="utf-8") as f:
            edited = yaml.safe_load(f)
        return _yaml_dict_to_plan(edited, plan)
    except Exception as e:
        console.print(f"[yellow]⚠[/yellow]  Could not parse edited YAML ({e}). Using original plan.")
        return plan
    finally:
        os.unlink(tmp_path)


def _create_in_jira(
    plan: Plan, feature: Feature, settings: Settings, storage: LocalStorage, save: bool
) -> None:
    jira = JiraClient(settings)

    for epic in plan.epics:
        try:
            epic_key = jira.create_epic(epic.title, epic.description, feature.jira_key)
            epic.jira_key = epic_key
            console.print(f"[green]✓[/green] Epic: {epic.title}  [{epic_key}]")
        except RuntimeError as e:
            console.print(f"[yellow]⚠[/yellow]  Epic failed: {e}")
            continue

        for story in epic.stories:
            try:
                story_key = jira.create_story(story.title, story.description, epic_key)
                story.jira_key = story_key
                console.print(f"  [green]✓[/green] Story: {story.title}  [{story_key}]")
            except RuntimeError as e:
                console.print(f"  [yellow]⚠[/yellow]  Story failed: {e}")
                continue

            for task in story.tasks:
                try:
                    task_key = jira.create_task(task.title, task.description, story_key)
                    task.jira_key = task_key
                    console.print(f"    [green]✓[/green] Task: {task.title}  [{task_key}]")
                except RuntimeError as e:
                    console.print(f"    [yellow]⚠[/yellow]  Task failed: {e}")

        if save:
            storage.save(
                plan.model_copy(update={"updated_at": datetime.now(timezone.utc)}),
                "plans",
            )


@app.command("create")
def create(
    feature_id: str = typer.Argument(..., help="Feature ID (e.g. FEAT-001)"),
    save: bool = typer.Option(False, "--save", help="Persist plan to ~/.atlassian-cli/plans/"),
) -> None:
    storage = LocalStorage()

    feature = storage.load(Feature, "features", feature_id)
    if not feature:
        console.print(f"[red]✗[/red]  Feature [bold]{feature_id}[/bold] not found")
        raise typer.Exit(1)

    if not feature.prd_id:
        console.print(
            f"[red]✗[/red]  Feature [bold]{feature_id}[/bold] has no linked PRD. "
            "Recreate it with [bold]--prd-id[/bold]."
        )
        raise typer.Exit(1)

    prd = storage.load(PRD, "prds", feature.prd_id)
    if not prd:
        console.print(f"[red]✗[/red]  PRD [bold]{feature.prd_id}[/bold] not found")
        raise typer.Exit(1)

    with console.status("[bold green]Generating plan with Ollama...[/bold green]"):
        try:
            settings = get_settings()
            ollama = OllamaClient(settings)
            raw = ollama.decompose_prd(prd)
        except RuntimeError as e:
            console.print(f"[red]✗[/red]  {e}")
            raise typer.Exit(1)

    try:
        plan = _build_plan(raw, feature_id, feature.prd_id, storage)
    except (ValueError, KeyError, TypeError):
        console.print("[red]✗[/red]  Ollama returned invalid plan structure. Try again.")
        raise typer.Exit(1)

    if typer.confirm("Review plan before creating in Jira?", default=True):
        plan = _editor_review(plan)

    if save:
        storage.save(plan, "plans")
        console.print(f"[green]✓[/green] Plan saved  [{plan.id}]")

    if typer.confirm("Create issues in Jira?", default=True):
        _create_in_jira(plan, feature, settings, storage, save)
        if save:
            storage.save(
                plan.model_copy(
                    update={"status": PlanStatus.created, "updated_at": datetime.now(timezone.utc)}
                ),
                "plans",
            )
            console.print(f"[green]✓[/green] Plan updated  [{plan.id}]")


@app.command("show")
def show(id: str = typer.Argument(..., help="Plan ID (e.g. PLAN-001)")) -> None:
    storage = LocalStorage()
    plan = storage.load(Plan, "plans", id)
    if not plan:
        console.print(f"[red]✗[/red]  Plan [bold]{id}[/bold] not found")
        raise typer.Exit(1)

    status_color = "green" if plan.status == PlanStatus.created else "yellow"
    tree = Tree(
        f"[cyan]{plan.id}[/cyan]  [white]{plan.feature_id}[/white]  "
        f"[{status_color}]{plan.status.value}[/{status_color}]"
    )
    for epic in plan.epics:
        epic_label = f"[bold]Epic:[/bold] {epic.title}"
        if epic.jira_key:
            epic_label += f"  [dim]{epic.jira_key}[/dim]"
        epic_branch = tree.add(epic_label)
        for story in epic.stories:
            story_label = f"[bold]Story:[/bold] {story.title}"
            if story.jira_key:
                story_label += f"  [dim]{story.jira_key}[/dim]"
            story_branch = epic_branch.add(story_label)
            for task in story.tasks:
                task_label = f"Task: {task.title}"
                if task.jira_key:
                    task_label += f"  [dim]{task.jira_key}[/dim]"
                story_branch.add(task_label)

    console.print(tree)


@app.command("list")
def list_plans() -> None:
    storage = LocalStorage()
    plans = storage.list_all(Plan, "plans")
    if not plans:
        console.print("[dim]No plans found.[/dim]")
        return

    table = Table(title="Plans", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Feature")
    table.add_column("Epics", justify="right")
    table.add_column("Stories", justify="right")
    table.add_column("Tasks", justify="right")
    table.add_column("Status")

    for p in plans:
        n_epics = len(p.epics)
        n_stories = sum(len(e.stories) for e in p.epics)
        n_tasks = sum(len(s.tasks) for e in p.epics for s in e.stories)
        status_str = (
            f"[green]{p.status.value}[/green]"
            if p.status == PlanStatus.created
            else p.status.value
        )
        table.add_row(p.id, p.feature_id, str(n_epics), str(n_stories), str(n_tasks), status_str)

    console.print(table)
```

- [ ] **Step 2: Verify import**

```bash
python -c "from atlassian_cli.commands.plan import app; print('Plan commands: OK')"
```

Expected: `Plan commands: OK`

- [ ] **Step 3: Commit**

```bash
git add atlassian_cli/commands/plan.py
git commit -m "feat: add plan create/show/list commands with Ollama decomposition and editor review"
```

---

## Task 6: Wire main.py + End-to-End Smoke Test

**Files:**
- Modify: `atlassian_cli/main.py`

One import line and one `add_typer` call.

- [ ] **Step 1: Update `atlassian_cli/main.py`**

Add `plan` to the import:

```python
from atlassian_cli.commands import feature, prd, plan
```

Add the typer registration after the existing `add_typer` calls:

```python
app.add_typer(plan.app, name="plan")
```

The full file becomes:

```python
import sys
import typer

# Ensure stdout/stderr use UTF-8 on Windows so Rich can render Unicode symbols.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from atlassian_cli.commands import feature, prd, plan

app = typer.Typer(
    name="atlassian",
    help="AI-native Atlassian delivery CLI — operates as a tool for Claude Code.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(feature.app, name="feature")
app.add_typer(prd.app, name="prd")
app.add_typer(plan.app, name="plan")

if __name__ == "__main__":
    app()
```

- [ ] **Step 2: Verify the app assembles without error**

```bash
python -c "from atlassian_cli.main import app; print('Main app: OK')"
```

Expected: `Main app: OK`

- [ ] **Step 3: Reinstall and verify help**

```bash
pip install -e .
atlassian --help
```

Expected output includes:
```
Commands:
  feature  Manage features
  plan     Generate and manage plans
  prd      Manage PRDs
```

- [ ] **Step 4: Verify plan subcommand help**

```bash
atlassian plan --help
```

Expected:
```
Usage: atlassian plan [OPTIONS] COMMAND [ARGS]...
...
Commands:
  create  Generate and manage plans
  list    ...
  show    ...
```

- [ ] **Step 5: Smoke test — list with no plans saved**

```bash
atlassian plan list
```

Expected: `No plans found.`

- [ ] **Step 6: (Live test — requires Ollama running with Qwen 3)**

With Ollama running (`ollama run qwen3` or `ollama serve`) and a `.env` pointing to it, and at least one Feature with a linked PRD in local storage:

```bash
atlassian plan create FEAT-001 --save
```

Expected flow:
```
Generating plan with Ollama...
Review plan before creating in Jira? [Y/n]: Y
# Editor opens with YAML — review and save
Create issues in Jira? [Y/n]: n
✓ Plan saved  [PLAN-001]
```

Then verify:
```bash
atlassian plan list
atlassian plan show PLAN-001
```

Expected: table with one row, then a Rich tree showing Epic → Story → Task hierarchy.

- [ ] **Step 7: (Live test — requires Ollama + .env with Atlassian creds)**

```bash
atlassian plan create FEAT-001 --save
# Answer Y to review, save YAML without changes, answer Y to Jira creation
```

Expected:
```
✓ Plan saved  [PLAN-001]
✓ Epic: v1.0 - ...  [MYAPP-XX]
  ✓ Story: ...  [MYAPP-XX]
    ✓ Task: ...  [MYAPP-XX]
...
✓ Plan updated  [PLAN-001]
```

- [ ] **Step 8: Final commit**

```bash
git add atlassian_cli/main.py
git commit -m "feat: register plan sub-app, Phase 2 complete"
```

---

## Phase 2 Complete

At this point `atlassian plan` is operational:

- `atlassian plan create FEAT-001` — Ollama decomposes the linked PRD into Epics/Stories/Tasks, optional YAML editor review, optional Jira creation
- `atlassian plan show PLAN-001` — Rich tree of the full hierarchy with Jira keys
- `atlassian plan list` — table of all saved plans
- `--save` flag persists plans locally at `~/.atlassian-cli/plans/`
- Partial Jira creation is safe — plan JSON updated after each Epic

**Next:** Phase 3 spec (QA planning, Playwright integration, bug generation).
