from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.jira import JiraClient
from atlassian_cli.models.feature import Feature, FeatureType, FeatureStatus
from atlassian_cli.storage.local import LocalStorage

app = typer.Typer(help="Manage features")
console = Console()


@app.command("create")
def create(
    name: str = typer.Option(..., prompt=True, help="Feature name"),
    type: FeatureType = typer.Option(..., prompt=True, help="Feature type"),
    description: str = typer.Option(..., prompt=True, help="Feature description"),
    prd_id: Optional[str] = typer.Option(None, help="Linked PRD ID (e.g. PRD-001)"),
    no_jira: bool = typer.Option(False, "--no-jira", help="Skip Jira Initiative creation"),
) -> None:
    storage = LocalStorage()

    feature_id = storage.next_id("FEAT", "features")
    now = datetime.now(timezone.utc)

    feature = Feature(
        id=feature_id,
        name=name,
        type=type,
        description=description,
        prd_id=prd_id,
        status=FeatureStatus.draft,
        created_at=now,
        updated_at=now,
    )

    if not no_jira:
        with console.status("[bold green]Creating Jira Initiative...[/bold green]"):
            try:
                jira = JiraClient(get_settings())
                jira_key = jira.create_initiative(name, description)
                feature = feature.model_copy(update={"jira_key": jira_key})
                console.print(f"[green]✓[/green] Jira Initiative created  [{jira_key}]")
            except RuntimeError as e:
                console.print(f"[yellow]⚠[/yellow]  Jira creation failed: {e}")

    storage.save(feature, "features")
    console.print(f"[green]✓[/green] Feature created  [{feature_id}]")


@app.command("show")
def show(id: str = typer.Argument(..., help="Feature ID (e.g. FEAT-001)")) -> None:
    storage = LocalStorage()
    feature = storage.load(Feature, "features", id)

    if not feature:
        console.print(f"[red]✗[/red]  Feature [bold]{id}[/bold] not found")
        raise typer.Exit(1)

    console.print(
        Panel(
            f"[bold]Name:[/bold]        {feature.name}\n"
            f"[bold]Type:[/bold]        {feature.type.value}\n"
            f"[bold]Status:[/bold]      {feature.status.value}\n"
            f"[bold]Description:[/bold] {feature.description}\n"
            f"[bold]PRD:[/bold]         {feature.prd_id or '—'}\n"
            f"[bold]Jira:[/bold]        {feature.jira_key or '—'}\n"
            f"[bold]Created:[/bold]     {feature.created_at.strftime('%Y-%m-%d %H:%M UTC')}",
            title=f"[cyan]{feature.id}[/cyan]  [white]{feature.name}[/white]",
        )
    )


@app.command("list")
def list_features() -> None:
    storage = LocalStorage()
    features = storage.list_all(Feature, "features")

    if not features:
        console.print("[dim]No features found.[/dim]")
        return

    table = Table(title="Features", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("PRD")
    table.add_column("Jira")

    for f in features:
        table.add_row(
            f.id,
            f.name,
            f.type.value,
            f.status.value,
            f.prd_id or "—",
            f.jira_key or "—",
        )

    console.print(table)
