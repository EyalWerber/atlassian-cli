from datetime import datetime, timezone
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.jira import JiraClient

app = typer.Typer(help="Manage Jira issue lifecycle")
console = Console()

_CATEGORY_STYLE = {
    "new": "dim",           # To Do
    "indeterminate": "yellow",  # In Progress, In QA, In Review, …
    "done": "green",        # Done
}


def _status_style(status_field: dict) -> str:
    """Return a Rich style string for a Jira status object (includes statusCategory)."""
    cat_key = (status_field.get("statusCategory") or {}).get("key", "")
    return _CATEGORY_STYLE.get(cat_key, "white")


@app.command("list")
def list_issues(
    status: Optional[str] = typer.Option(
        None, "--status", "-s",
        help="Filter by status: 'open' (not done), 'done', or any Jira status name. Omit for all.",
    ),
    jql: Optional[str] = typer.Option(
        None, "--jql",
        help="Custom JQL to override the default query.",
    ),
) -> None:
    """List Jira issues in the configured project."""
    settings = get_settings()
    project = settings.jira_project

    if jql:
        query = jql
    elif status and status.lower() == "open":
        query = f"project={project} AND statusCategory != Done ORDER BY created DESC"
    elif status and status.lower() == "done":
        query = f"project={project} AND statusCategory = Done ORDER BY updated DESC"
    elif status:
        query = f"project={project} AND status = \"{status}\" ORDER BY created DESC"
    else:
        query = f"project={project} ORDER BY created DESC"

    jira = JiraClient(settings)
    try:
        issues = jira.search_issues(query)
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)

    if not issues:
        console.print("[yellow]No issues found.[/yellow]")
        return

    table = Table(show_lines=False, expand=False)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Summary")

    for issue in issues:
        fields = issue["fields"]
        key = issue["key"]
        status_name = fields["status"]["name"]
        style = _status_style(fields["status"])
        summary = fields.get("summary", "")
        table.add_row(key, f"[{style}]{status_name}[/{style}]", summary)

    console.print(table)


@app.command("transition")
def transition(
    key: str = typer.Argument(..., help="Issue key, e.g. SI-42"),
    status: str = typer.Argument(..., help="Target status name, e.g. 'In Progress', 'In QA', 'Done'. Run 'workflow' to see valid values."),
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


@app.command("workflow")
def workflow() -> None:
    """Show all statuses in the project's workflow, coloured by category."""
    settings = get_settings()
    jira = JiraClient(settings)
    try:
        statuses = jira.get_project_statuses()
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)

    table = Table(title=f"Workflow: {settings.jira_project}", show_lines=False)
    table.add_column("Status", no_wrap=True)
    table.add_column("Category", no_wrap=True)
    for s in statuses:
        style = _CATEGORY_STYLE.get(s["category_key"], "white")
        table.add_row(
            f"[{style}]{s['name']}[/{style}]",
            f"[{style}]{s['category_name']}[/{style}]",
        )
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


@app.command("link")
def link(
    key: str = typer.Argument(..., help="Source issue key, e.g. SI-11"),
    blocks: Optional[str] = typer.Option(None, "--blocks", help="Issue key this blocks, e.g. SI-8"),
) -> None:
    """Add a link between issues (supports --blocks)."""
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


def _adf_to_text(node: object) -> str:
    """Recursively extract plain text from an Atlassian Document Format node."""
    if not node or isinstance(node, str):
        return node or ""
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return node.get("text", "")
    parts = [_adf_to_text(child) for child in node.get("content", [])]
    return " ".join(p for p in parts if p)


@app.command("ingest")
def ingest(
    key: str = typer.Argument("", help="Issue key, e.g. SI-42 (omit with --all)"),
    all_bugs: bool = typer.Option(False, "--all", help="Ingest all Bug issues in the project"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-ingest even if already saved"),
) -> None:
    """Read a Jira issue's comments into memory for bug pattern recognition."""
    from atlassian_cli.integrations.ollama import OllamaClient
    from atlassian_cli.models.memory import Memory, MemoryType
    from atlassian_cli.storage.memory_store import MemoryStore

    settings = get_settings()
    jira = JiraClient(settings)

    if all_bugs:
        project = settings.jira_project
        try:
            issues = jira.search_issues(
                f"project={project} AND issuetype=Bug ORDER BY created DESC",
                fields=["summary"],
            )
        except RuntimeError as e:
            console.print(f"[red]✗[/red]  {e}")
            raise typer.Exit(1)
        keys = [i["key"] for i in issues]
        if not keys:
            console.print("[yellow]No Bug issues found.[/yellow]")
            return
    elif key:
        keys = [key]
    else:
        console.print("[red]✗[/red]  Provide an issue key or use --all")
        raise typer.Exit(1)

    ollama = OllamaClient(settings)
    mem_store = MemoryStore(
        db_path=settings.memory_db_path,
        vector_path=settings.memory_vector_path,
        ollama=ollama,
        turso_url=settings.turso_url if settings.memory_backend == "turso" else None,
        turso_auth_token=settings.turso_auth_token if settings.memory_backend == "turso" else None,
    )

    ingested = skipped = 0
    for k in keys:
        if not force:
            existing = mem_store.list(tag=k, limit=1)
            if existing:
                skipped += 1
                console.print(f"[dim]  {k}: already ingested (--force to overwrite)[/dim]")
                continue

        try:
            issue = jira.get_issue(k)
            comments = jira.get_comments(k)
        except RuntimeError as e:
            console.print(f"[red]✗[/red]  {k}: {e}")
            continue

        fields = issue["fields"]
        title = fields.get("summary", "")
        description = _adf_to_text(fields.get("description") or {})
        comment_texts = [_adf_to_text(c.get("body") or {}) for c in comments]

        try:
            summary = ollama.summarize_issue(k, title, description, comment_texts)
        except RuntimeError as e:
            console.print(f"[yellow]⚠[/yellow]  {k}: Ollama unavailable — saving title only ({e})")
            summary = f"{k}: {title}"

        now = datetime.now(timezone.utc)
        memory = Memory(
            id=mem_store.next_id(),
            content=summary,
            type=MemoryType.bug,
            tags=[k, "ingested"],
            created_at=now,
            updated_at=now,
        )
        mem_store.add(memory)
        ingested += 1
        console.print(f"[green]✓[/green] {k}: saved as {memory.id}")

    if all_bugs or len(keys) > 1:
        console.print(f"\n[bold]{ingested} ingested, {skipped} skipped[/bold]")
