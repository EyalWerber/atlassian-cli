from datetime import datetime, timezone
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.ollama import OllamaClient
from atlassian_cli.models.memory import Memory, MemoryType
from atlassian_cli.storage.memory_store import MemoryStore

app = typer.Typer(help="Manage project memory")
console = Console()


def _get_store() -> MemoryStore:
    settings = get_settings()
    return MemoryStore(
        db_path=settings.memory_db_path,
        vector_path=settings.memory_vector_path,
        ollama=OllamaClient(settings),
    )


@app.command("add")
def add(
    content: str = typer.Argument(..., help="Memory content"),
    type: MemoryType = typer.Option(MemoryType.note, "--type", help="Memory type"),
    tag: Optional[List[str]] = typer.Option(None, "--tag", help="Tag (repeatable)"),
    feature: Optional[str] = typer.Option(None, "--feature", help="e.g. FEAT-001"),
    prd: Optional[str] = typer.Option(None, "--prd", help="e.g. PRD-001"),
    plan: Optional[str] = typer.Option(None, "--plan", help="e.g. PLAN-001"),
    qa: Optional[str] = typer.Option(None, "--qa", help="e.g. QA-001"),
) -> None:
    store = _get_store()
    now = datetime.now(timezone.utc)
    memory = Memory(
        id=store.next_id(),
        content=content,
        type=type,
        tags=list(tag) if tag else [],
        feature_id=feature,
        prd_id=prd,
        plan_id=plan,
        qa_id=qa,
        created_at=now,
        updated_at=now,
    )
    try:
        store.add(memory)
    except RuntimeError as e:
        console.print(f"[red]x[/red]  {e}")
        raise typer.Exit(1)
    console.print(f"[green]v[/green] Memory saved  [{memory.id}]")


@app.command("show")
def show(id: str = typer.Argument(..., help="e.g. MEM-001")) -> None:
    store = _get_store()
    memory = store.get(id)
    if not memory:
        console.print(f"[red]x[/red]  Memory [bold]{id}[/bold] not found")
        raise typer.Exit(1)
    lines = [
        f"[bold]Content:[/bold]  {memory.content}",
        f"[bold]Type:[/bold]     {memory.type.value}",
        f"[bold]Tags:[/bold]     {', '.join(memory.tags) or '—'}",
    ]
    if memory.feature_id:
        lines.append(f"[bold]Feature:[/bold]  {memory.feature_id}")
    if memory.prd_id:
        lines.append(f"[bold]PRD:[/bold]      {memory.prd_id}")
    if memory.plan_id:
        lines.append(f"[bold]Plan:[/bold]     {memory.plan_id}")
    if memory.qa_id:
        lines.append(f"[bold]QA:[/bold]       {memory.qa_id}")
    lines.append(f"[bold]Created:[/bold]  {memory.created_at.strftime('%Y-%m-%d %H:%M UTC')}")
    console.print(Panel("\n".join(lines), title=f"[cyan]{memory.id}[/cyan]"))


@app.command("list")
def list_memories(
    type: Optional[MemoryType] = typer.Option(None, "--type"),
    feature: Optional[str] = typer.Option(None, "--feature"),
    tag: Optional[str] = typer.Option(None, "--tag"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    store = _get_store()
    memories = store.list(type=type, feature_id=feature, tag=tag, limit=limit)
    if not memories:
        console.print("[dim]No memories found.[/dim]")
        return
    table = Table(show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Type")
    table.add_column("Content", max_width=60)
    table.add_column("Tags")
    table.add_column("Feature")
    table.add_column("Created")
    for m in memories:
        snippet = m.content[:57] + "..." if len(m.content) > 60 else m.content
        table.add_row(
            m.id,
            m.type.value,
            snippet,
            ", ".join(m.tags) or "—",
            m.feature_id or "—",
            m.created_at.strftime("%Y-%m-%d"),
        )
    console.print(table)


@app.command("search")
def search(
    query: str = typer.Argument(..., help="Search query"),
    feature: Optional[str] = typer.Option(None, "--feature"),
    limit: int = typer.Option(5, "--limit"),
) -> None:
    store = _get_store()
    try:
        memories = store.search(query, limit=limit, feature_id=feature)
    except RuntimeError as e:
        console.print(f"[red]x[/red]  {e}")
        raise typer.Exit(1)
    if not memories:
        console.print("[dim]No relevant memories found.[/dim]")
        return
    table = Table(show_lines=False)
    table.add_column("#", style="dim", justify="right")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Type")
    table.add_column("Content", max_width=60)
    table.add_column("Feature")
    for i, m in enumerate(memories, 1):
        snippet = m.content[:57] + "..." if len(m.content) > 60 else m.content
        table.add_row(str(i), m.id, m.type.value, snippet, m.feature_id or "—")
    console.print(table)


@app.command("delete")
def delete(id: str = typer.Argument(..., help="e.g. MEM-001")) -> None:
    store = _get_store()
    memory = store.get(id)
    if not memory:
        console.print(f"[red]x[/red]  Memory [bold]{id}[/bold] not found")
        raise typer.Exit(1)
    snippet = memory.content[:60] + "..." if len(memory.content) > 60 else memory.content
    console.print(f"[dim]{snippet}[/dim]")
    if not typer.confirm(f"Delete {id}?", default=False):
        console.print("[dim]Cancelled.[/dim]")
        return
    store.delete(id)
    console.print(f"[green]v[/green] Memory deleted  [{id}]")
