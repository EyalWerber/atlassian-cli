import typer
from rich.console import Console
from rich.table import Table

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.jira import JiraClient

app = typer.Typer(help="Manage Jira issues")
console = Console()


@app.command("transition")
def transition(
    key: str = typer.Argument(..., help="Issue key, e.g. SI-42"),
    status: str = typer.Argument(..., help="Target status, e.g. 'In Progress'"),
) -> None:
    settings = get_settings()
    jira = JiraClient(settings)
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
    settings = get_settings()
    jira = JiraClient(settings)
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
        table.add_row(
            t.get("id", ""),
            t.get("name", ""),
            t.get("to", {}).get("name", ""),
        )
    console.print(table)
