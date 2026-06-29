import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.ollama import OllamaClient
from atlassian_cli.models.memory import Memory, MemoryType
from atlassian_cli.storage.memory_store import MemoryStore
from atlassian_cli.models.adr import ADR, AdrStatus
from atlassian_cli.storage.local import LocalStorage

from atlassian_cli.integrations.turso import TursoHttpClient

app = typer.Typer(help="Manage project memory")
console = Console()


def _build_mem_store(settings) -> MemoryStore:
    backend = settings.memory_backend
    if backend not in ("local", "turso"):
        console.print(
            f"[red]✗[/red]  MEMORY_BACKEND={backend!r} is not valid. "
            "Set it to [bold]local[/bold] or [bold]turso[/bold] in .env."
        )
        raise typer.Exit(1)
    if backend == "turso" and not settings.turso_url:
        console.print(
            "[red]✗[/red]  MEMORY_BACKEND=turso requires TURSO_URL in .env.\n"
            "  Run [bold]atlassian project init[/bold] to reconfigure."
        )
        raise typer.Exit(1)
    return MemoryStore(
        db_path=settings.memory_db_path,
        vector_path=settings.memory_vector_path,
        ollama=OllamaClient(settings),
        turso_url=settings.turso_url if backend == "turso" else None,
        turso_auth_token=settings.turso_auth_token if backend == "turso" else None,
    )


def _get_store() -> MemoryStore:
    settings = get_settings()
    try:
        return _build_mem_store(settings)
    except Exception as e:
        console.print(f"[red]✗[/red]  Failed to initialize memory store: {e}")
        raise typer.Exit(1)


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
        tags=[t for raw in (tag or []) for t in raw.split(",") if t],
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
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Memory saved  [{memory.id}]")


@app.command("show")
def show(id: str = typer.Argument(..., help="e.g. MEM-001")) -> None:
    store = _get_store()
    memory = store.get(id)
    if not memory:
        console.print(f"[red]✗[/red]  Memory [bold]{id}[/bold] not found")
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
    table = Table(title="Memories", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Type")
    table.add_column("Content", max_width=60)
    table.add_column("Tags")
    table.add_column("Feature")
    table.add_column("Created")
    for m in memories:
        snippet = m.content[:57] + "..." if len(m.content) > 57 else m.content
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
        console.print(f"[red]✗[/red]  {e}")
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
        snippet = m.content[:57] + "..." if len(m.content) > 57 else m.content
        table.add_row(str(i), m.id, m.type.value, snippet, m.feature_id or "—")
    console.print(table)


@app.command("delete")
def delete(id: str = typer.Argument(..., help="e.g. MEM-001")) -> None:
    store = _get_store()
    memory = store.get(id)
    if not memory:
        console.print(f"[red]✗[/red]  Memory [bold]{id}[/bold] not found")
        raise typer.Exit(1)
    snippet = memory.content[:57] + "..." if len(memory.content) > 57 else memory.content
    console.print(f"[dim]{snippet}[/dim]")
    if not typer.confirm(f"Delete {id}?", default=False):
        console.print("[dim]Cancelled.[/dim]")
        return
    try:
        store.delete(id)
    except Exception as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Memory deleted  [{id}]")


def _build_claude_md(
    adrs: list[ADR],
    decisions: list[Memory],
    contexts: list[Memory],
    bugs: list[Memory],
    plans: list[Memory],
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts = [
        "# Project Context",
        f"> Generated {now} · Regenerate: `atlassian memory snapshot`",
        "",
    ]
    if plans:
        parts.append("## Upcoming Work")
        for m in plans:
            parts.append(f"- [{m.id}] {m.content}")
        parts.append("")
    if adrs:
        parts.append("## Architecture Decisions (ADRs)")
        for adr in adrs:
            parts.append(f"- **{adr.id}** {adr.title} — *{adr.status.value}*")
        parts.append("")
    if decisions:
        parts.append("## Decision Log")
        for m in decisions:
            parts.append(f"- [{m.id}] {m.content}")
        parts.append("")
    if contexts:
        parts.append("## Context Notes")
        for m in contexts:
            parts.append(f"- [{m.id}] {m.content}")
        parts.append("")
    if bugs:
        parts.append("## Recent Bugs")
        for m in bugs:
            parts.append(f"- [{m.id}] {m.content}")
        parts.append("")
    return "\n".join(parts)


@app.command("snapshot")
def snapshot() -> None:
    output = Path("CLAUDE.md")
    if output.exists():
        if not typer.confirm("CLAUDE.md already exists. Overwrite?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            return

    settings = get_settings()
    storage = LocalStorage()
    adrs = storage.list_all(ADR, "adrs")

    decisions: list[Memory] = []
    contexts: list[Memory] = []
    bugs: list[Memory] = []
    plans: list[Memory] = []
    try:
        mem_store = _build_mem_store(settings)
        decisions = mem_store.list(type=MemoryType.decision, limit=50)
        contexts = mem_store.list(type=MemoryType.context, limit=50)
        bugs = mem_store.list(type=MemoryType.bug, limit=10)
        plans = mem_store.list(type=MemoryType.plan, limit=20)
    except Exception:
        console.print("[dim]  (memory store unavailable — CLAUDE.md will contain ADRs only)[/dim]")

    content = _build_claude_md(adrs, decisions, contexts, bugs, plans)
    output.write_text(content, encoding="utf-8")
    console.print(f"[green]✓[/green] CLAUDE.md written  ({len(content.splitlines())} lines)")


@app.command("status")
def status() -> None:
    settings = get_settings()
    backend = settings.memory_backend

    db_path = Path(settings.memory_db_path).expanduser()
    local_count = 0
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            local_count = row[0] if row else 0
            conn.close()
        except Exception:
            pass

    vector_count = 0
    if sys.platform != "win32":
        vector_path = Path(settings.memory_vector_path).expanduser()
        if vector_path.exists():
            try:
                import chromadb
                client = chromadb.PersistentClient(path=str(vector_path))
                col = client.get_or_create_collection("memories")
                vector_count = col.count()
            except Exception:
                pass

    ollama_ok = OllamaClient(settings).ping()
    ollama_icon = "[green]✓[/green]" if ollama_ok else "[red]✗[/red]"

    if backend == "local":
        console.print(f"[bold]Backend:[/bold]   local  [dim](set MEMORY_BACKEND=turso to use Turso)[/dim]")
        console.print(f"[bold]Store:[/bold]     {settings.memory_db_path}")
        console.print(f"[bold]Memories:[/bold]  {local_count}")
        not_embedded = max(0, local_count - vector_count)
        console.print(f"[bold]Vectors:[/bold]   {vector_count}  [dim]({not_embedded} not yet embedded)[/dim]")
        console.print(f"[bold]Ollama:[/bold]    {ollama_icon}  {settings.ollama_host}")
        if settings.turso_url:
            console.print(f"[bold]Turso:[/bold]     {settings.turso_url}  [dim](push/pull available)[/dim]")
        else:
            console.print(f"[bold]Turso:[/bold]     [dim]not configured  (set TURSO_URL to enable push/pull)[/dim]")
    else:
        if not settings.turso_url:
            console.print("[red]✗[/red]  TURSO_URL not configured. Set it in .env when using MEMORY_BACKEND=turso.")
            raise typer.Exit(1)
        turso_count = 0
        turso_ok = False
        try:
            remote = TursoHttpClient(
                url=settings.turso_url,
                auth_token=settings.turso_auth_token or "",
            )
            remote.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY, content TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'note', tags TEXT NOT NULL DEFAULT '[]',
                    feature_id TEXT, prd_id TEXT, plan_id TEXT, qa_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            row = remote.execute("SELECT COUNT(*) FROM memories").fetchone()
            turso_count = row[0] if row else 0
            turso_ok = True
        except Exception:
            pass
        turso_icon = "[green]✓[/green]" if turso_ok else "[red]✗[/red]"
        console.print(f"[bold]Backend:[/bold]   turso")
        console.print(f"[bold]Remote:[/bold]    {turso_icon}  {settings.turso_url or 'not configured'}")
        console.print(f"[bold]Memories:[/bold]  {turso_count}  [dim](Turso)[/dim]")
        console.print(f"[bold]Vectors:[/bold]   {vector_count}  [dim](local ChromaDB)[/dim]")
        console.print(f"[bold]Ollama:[/bold]    {ollama_icon}  {settings.ollama_host}")


@app.command("push")
def push() -> None:
    settings = get_settings()
    if not settings.turso_url:
        console.print("[red]✗[/red]  TURSO_URL not configured. Set it in .env to enable push.")
        raise typer.Exit(1)
    if settings.memory_backend == "turso":
        console.print("[dim]Backend is already Turso — memories are written directly to Turso.[/dim]")
        return
    store = _build_mem_store(settings)
    try:
        count = store.push_to_turso(settings.turso_url, settings.turso_auth_token or "")
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
    noun = "memory" if count == 1 else "memories"
    console.print(f"[green]✓[/green] Pushed {count} new {noun} to Turso")


@app.command("pull")
def pull() -> None:
    settings = get_settings()
    if not settings.turso_url:
        console.print("[red]✗[/red]  TURSO_URL not configured. Set it in .env to enable pull.")
        raise typer.Exit(1)
    store = _build_mem_store(settings)
    try:
        if settings.memory_backend == "turso":
            count = store.sync_vectors()
            noun = "memory" if count == 1 else "memories"
            console.print(f"[green]✓[/green] Synced {count} new {noun} to local search index")
        else:
            count = store.pull_from_turso(settings.turso_url, settings.turso_auth_token or "")
            noun = "memory" if count == 1 else "memories"
            console.print(f"[green]✓[/green] Pulled {count} new {noun} from Turso")
    except RuntimeError as e:
        console.print(f"[red]✗[/red]  {e}")
        raise typer.Exit(1)
