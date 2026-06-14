from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.confluence import ConfluenceClient
from atlassian_cli.integrations.ollama import OllamaClient
from atlassian_cli.models.adr import ADR, AdrStatus
from atlassian_cli.models.memory import Memory, MemoryType
from atlassian_cli.storage.local import LocalStorage
from atlassian_cli.storage.memory_store import MemoryStore
from atlassian_cli.commands.memory import _build_mem_store

app = typer.Typer(help="Manage Architecture Decision Records")
console = Console()


def _adr_to_confluence_body(adr: ADR) -> str:
    def safe(text: str) -> str:
        return (
            text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br/>")
        )
    return "\n".join([
        f"<h2>Status</h2><p>{safe(adr.status.value)}</p>",
        f"<h2>Context</h2><p>{safe(adr.context)}</p>",
        f"<h2>Decision</h2><p>{safe(adr.decision)}</p>",
        f"<h2>Consequences</h2><p>{safe(adr.consequences)}</p>",
        f"<p><em>Feature: {adr.feature_id or '—'}  ·  ADR: {adr.id}</em></p>",
    ])


@app.command("add")
def add(
    title: str = typer.Option(..., "--title", help="Short title for this decision"),
    context: str = typer.Option(..., "--context", help="Why was this decision needed"),
    decision: str = typer.Option(..., "--decision", help="What was decided"),
    consequences: str = typer.Option(..., "--consequences", help="Trade-offs and implications"),
    feature: Optional[str] = typer.Option(None, "--feature", help="e.g. FEAT-001"),
    status: AdrStatus = typer.Option(AdrStatus.proposed, "--status"),
) -> None:
    settings = get_settings()
    storage = LocalStorage()
    now = datetime.now(timezone.utc)
    adr_id = storage.next_id("ADR", "adrs")

    memory_id: Optional[str] = None
    try:
        mem_store = _build_mem_store(settings)
        memory_id = mem_store.next_id()
        mem = Memory(
            id=memory_id,
            content=f"ADR {adr_id}: {title}. Decision: {decision}. Consequences: {consequences}.",
            type=MemoryType.decision,
            tags=["adr"],
            feature_id=feature,
            created_at=now,
            updated_at=now,
        )
        mem_store.add(mem)
    except Exception:
        memory_id = None
        console.print("[dim]  (memory auto-save skipped — Ollama not available)[/dim]")

    adr = ADR(
        id=adr_id,
        title=title,
        status=status,
        context=context,
        decision=decision,
        consequences=consequences,
        feature_id=feature,
        memory_id=memory_id,
        created_at=now,
        updated_at=now,
    )
    storage.save(adr, "adrs")

    mem_suffix = f"  →  memory [{memory_id}]" if memory_id else ""
    console.print(f"[green]✓[/green] ADR saved  [{adr_id}]{mem_suffix}")


@app.command("list")
def list_adrs(
    feature: Optional[str] = typer.Option(None, "--feature"),
    status: Optional[AdrStatus] = typer.Option(None, "--status"),
) -> None:
    storage = LocalStorage()
    adrs = storage.list_all(ADR, "adrs")
    if feature:
        adrs = [a for a in adrs if a.feature_id == feature]
    if status:
        adrs = [a for a in adrs if a.status == status]
    if not adrs:
        console.print("[dim]No ADRs found.[/dim]")
        return
    table = Table(title="ADRs", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Feature")
    table.add_column("Memory")
    table.add_column("Created")
    for a in adrs:
        status_color = (
            "green" if a.status == AdrStatus.accepted
            else "yellow" if a.status == AdrStatus.proposed
            else "dim"
        )
        table.add_row(
            a.id,
            a.title[:60] + "..." if len(a.title) > 60 else a.title,
            f"[{status_color}]{a.status.value}[/{status_color}]",
            a.feature_id or "—",
            a.memory_id or "—",
            a.created_at.strftime("%Y-%m-%d"),
        )
    console.print(table)


@app.command("show")
def show(id: str = typer.Argument(..., help="ADR ID (e.g. ADR-001)")) -> None:
    storage = LocalStorage()
    adr = storage.load(ADR, "adrs", id)
    if not adr:
        console.print(f"[red]✗[/red]  ADR [bold]{id}[/bold] not found")
        raise typer.Exit(1)
    lines = [
        f"[bold]Title:[/bold]        {adr.title}",
        f"[bold]Status:[/bold]       {adr.status.value}",
        f"[bold]Context:[/bold]      {adr.context}",
        f"[bold]Decision:[/bold]     {adr.decision}",
        f"[bold]Consequences:[/bold] {adr.consequences}",
    ]
    if adr.feature_id:
        lines.append(f"[bold]Feature:[/bold]      {adr.feature_id}")
    if adr.memory_id:
        lines.append(f"[bold]Memory:[/bold]       {adr.memory_id}")
    if adr.confluence_url:
        lines.append(f"[bold]Confluence:[/bold]   {adr.confluence_url}")
    lines.append(f"[bold]Created:[/bold]      {adr.created_at.strftime('%Y-%m-%d %H:%M UTC')}")
    console.print(Panel("\n".join(lines), title=f"[cyan]{adr.id}[/cyan]"))


@app.command("publish")
def publish(id: str = typer.Argument(..., help="ADR ID (e.g. ADR-001)")) -> None:
    storage = LocalStorage()
    adr = storage.load(ADR, "adrs", id)
    if not adr:
        console.print(f"[red]✗[/red]  ADR [bold]{id}[/bold] not found")
        raise typer.Exit(1)

    settings = get_settings()
    confluence = ConfluenceClient(settings)
    body = _adr_to_confluence_body(adr)

    try:
        _, url = confluence.create_page(title=f"ADR: {adr.title}", body=body)
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)

    updated = adr.model_copy(update={
        "confluence_url": url,
        "updated_at": datetime.now(timezone.utc),
    })
    storage.save(updated, "adrs")
    console.print(f"[green]✓[/green] ADR published  [{id}]  →  {url}")
