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
    return Plan(
        id=plan_id,
        feature_id=feature_id,
        prd_id=prd_id,
        epics=_build_epics(raw["epics"]),
        created_at=now,
        updated_at=now,
    )


def _build_epics(epics_data: list[dict]) -> list[Epic]:
    epics = []
    for e in epics_data:
        stories = []
        for s in e["stories"]:
            tasks = [Task(title=t["title"], description=t["description"]) for t in s["tasks"]]
            stories.append(Story(title=s["title"], description=s["description"], tasks=tasks))
        epics.append(Epic(title=e["title"], description=e["description"], stories=stories))
    return epics


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
    return plan.model_copy(
        update={"epics": _build_epics(data["epics"]), "updated_at": datetime.now(timezone.utc)}
    )


def _editor_review(plan: Plan) -> Plan:
    yaml_data = _plan_to_yaml_dict(plan)
    with tempfile.NamedTemporaryFile(
        suffix=".yaml", mode="w", delete=False, encoding="utf-8"
    ) as f:
        yaml.dump(yaml_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        tmp_path = f.name

    editor = os.environ.get("EDITOR", "notepad" if os.name == "nt" else "nano")
    try:
        subprocess.run([editor, tmp_path], check=False)
    except FileNotFoundError:
        console.print(f"[yellow]⚠[/yellow]  Editor '{editor}' not found. Set $EDITOR to a valid editor. Using original plan.")
        return plan

    try:
        with open(tmp_path, encoding="utf-8") as f:
            edited = yaml.safe_load(f)
        return _yaml_dict_to_plan(edited, plan)
    except Exception as e:  # yaml.YAMLError, KeyError, TypeError — all mean unusable edit
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

    settings = get_settings()
    with console.status("[bold green]Generating plan with Ollama...[/bold green]"):
        try:
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
