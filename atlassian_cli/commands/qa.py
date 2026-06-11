from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.jira import JiraClient
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
