from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.confluence import ConfluenceClient, prd_to_storage_format
from atlassian_cli.integrations.jira import JiraClient
from atlassian_cli.models.feature import Feature
from atlassian_cli.models.prd import PRD, PRDStatus
from atlassian_cli.storage.local import LocalStorage

app = typer.Typer(help="Manage PRDs")
console = Console()


def _publish(prd: PRD, storage: LocalStorage) -> PRD:
    """Publish or re-publish a PRD to Confluence. Returns updated PRD."""
    settings = get_settings()
    conf = ConfluenceClient(settings)
    body = prd_to_storage_format(prd)

    if prd.confluence_page_id:
        conf.update_page(page_id=prd.confluence_page_id, title=prd.title, body=body)
        updated = prd.model_copy(update={"updated_at": datetime.now(timezone.utc)})
        storage.save(updated, "prds")
        console.print(f"[green]✓[/green] Confluence page updated: {prd.confluence_url}")
    else:
        page_id, url = conf.create_page(title=prd.title, body=body)
        updated = prd.model_copy(update={
            "confluence_page_id": page_id,
            "confluence_url": url,
            "status": PRDStatus.published,
            "updated_at": datetime.now(timezone.utc),
        })
        storage.save(updated, "prds")
        console.print(f"[green]✓[/green] Published to Confluence: {url}")

    if updated.feature_id and updated.confluence_url:
        feature = storage.load(Feature, "features", updated.feature_id)
        if feature and feature.jira_key:
            try:
                jira = JiraClient(settings)
                jira.add_remote_link(feature.jira_key, updated.confluence_url, updated.title)
                console.print(f"[green]✓[/green] Linked {feature.jira_key} → Confluence PRD")
            except RuntimeError as e:
                console.print(f"[yellow]⚠[/yellow]  Jira remote link failed: {e}")

    return updated


@app.command("create")
def create(
    title: str = typer.Option(..., prompt=True, help="PRD title"),
    summary: str = typer.Option(..., prompt=True, help="Executive summary"),
    problem: str = typer.Option(..., prompt=True, help="Problem statement"),
    personas: str = typer.Option(..., prompt=True, help="User personas"),
    stories: str = typer.Option(..., prompt=True, help="User stories"),
    business_value: str = typer.Option(..., prompt=True, help="Business value"),
    requirements: str = typer.Option(..., prompt=True, help="Functional requirements"),
    nfr: str = typer.Option(..., prompt=True, help="Non-functional requirements"),
    considerations: str = typer.Option("", help="Technical considerations"),
    risks: str = typer.Option(..., prompt=True, help="Risks"),
    metrics: str = typer.Option(..., prompt=True, help="Success metrics"),
    out_of_scope: str = typer.Option(..., prompt=True, help="Out of scope"),
    future_enhancements: str = typer.Option("", help="Future enhancements"),
    feature_id: Optional[str] = typer.Option(None, help="Linked Feature ID (e.g. FEAT-001)"),
) -> None:
    storage = LocalStorage()
    prd_id = storage.next_id("PRD", "prds")
    now = datetime.now(timezone.utc)

    prd = PRD(
        id=prd_id,
        title=title,
        summary=summary,
        problem=problem,
        personas=personas,
        stories=stories,
        business_value=business_value,
        requirements=requirements,
        nfr=nfr,
        considerations=considerations,
        risks=risks,
        metrics=metrics,
        out_of_scope=out_of_scope,
        future_enhancements=future_enhancements,
        feature_id=feature_id,
        status=PRDStatus.draft,
        created_at=now,
        updated_at=now,
    )

    storage.save(prd, "prds")
    console.print(f"[green]✓[/green] PRD saved locally  [{prd_id}]")

    with console.status("[bold green]Publishing to Confluence...[/bold green]"):
        try:
            prd = _publish(prd, storage)
        except RuntimeError as e:
            console.print(f"[yellow]⚠[/yellow]  Confluence publish failed: {e}")
            console.print(f"[dim]Run [bold]atlassian prd publish {prd_id}[/bold] to retry.[/dim]")


@app.command("publish")
def publish(id: str = typer.Argument(..., help="PRD ID (e.g. PRD-001)")) -> None:
    storage = LocalStorage()
    prd = storage.load(PRD, "prds", id)

    if not prd:
        console.print(f"[red]✗[/red]  PRD [bold]{id}[/bold] not found")
        raise typer.Exit(1)

    with console.status("[bold green]Publishing to Confluence...[/bold green]"):
        try:
            _publish(prd, storage)  # saves updated PRD internally on create
        except RuntimeError as e:
            console.print(f"[red]✗[/red]  {e}")
            raise typer.Exit(1)


@app.command("update")
def update(
    id: str = typer.Argument(..., help="PRD ID (e.g. PRD-001)"),
    title: Optional[str] = typer.Option(None),
    summary: Optional[str] = typer.Option(None),
    problem: Optional[str] = typer.Option(None),
    personas: Optional[str] = typer.Option(None),
    stories: Optional[str] = typer.Option(None),
    business_value: Optional[str] = typer.Option(None),
    requirements: Optional[str] = typer.Option(None),
    nfr: Optional[str] = typer.Option(None),
    considerations: Optional[str] = typer.Option(None),
    risks: Optional[str] = typer.Option(None),
    metrics: Optional[str] = typer.Option(None),
    out_of_scope: Optional[str] = typer.Option(None),
    future_enhancements: Optional[str] = typer.Option(None),
    feature_id: Optional[str] = typer.Option(None),
) -> None:
    storage = LocalStorage()
    prd = storage.load(PRD, "prds", id)

    if not prd:
        console.print(f"[red]✗[/red]  PRD [bold]{id}[/bold] not found")
        raise typer.Exit(1)

    updates: dict = {"updated_at": datetime.now(timezone.utc)}
    for field, value in {
        "title": title, "summary": summary, "problem": problem,
        "personas": personas, "stories": stories, "business_value": business_value,
        "requirements": requirements, "nfr": nfr, "considerations": considerations,
        "risks": risks, "metrics": metrics, "out_of_scope": out_of_scope,
        "future_enhancements": future_enhancements,
        "feature_id": feature_id,
    }.items():
        if value is not None:
            updates[field] = value

    prd = prd.model_copy(update=updates)
    storage.save(prd, "prds")
    console.print(f"[green]✓[/green] PRD [{id}] updated")

    if prd.confluence_page_id:
        with console.status("[bold green]Re-publishing to Confluence...[/bold green]"):
            try:
                _publish(prd, storage)
            except RuntimeError as e:
                console.print(f"[yellow]⚠[/yellow]  Confluence update failed: {e}")


@app.command("show")
def show(id: str = typer.Argument(..., help="PRD ID (e.g. PRD-001)")) -> None:
    storage = LocalStorage()
    prd = storage.load(PRD, "prds", id)

    if not prd:
        console.print(f"[red]✗[/red]  PRD [bold]{id}[/bold] not found")
        raise typer.Exit(1)

    sections = [
        ("Executive Summary", prd.summary),
        ("Problem Statement", prd.problem),
        ("User Personas", prd.personas),
        ("User Stories", prd.stories),
        ("Business Value", prd.business_value),
        ("Functional Requirements", prd.requirements),
        ("Non-Functional Requirements", prd.nfr),
        ("Technical Considerations", prd.considerations),
        ("Risks", prd.risks),
        ("Success Metrics", prd.metrics),
        ("Out of Scope", prd.out_of_scope),
        ("Future Enhancements", prd.future_enhancements),
    ]

    body = "\n\n".join(
        f"[bold]{h}[/bold]\n{c}" for h, c in sections if c
    )

    console.print(
        Panel(
            body,
            title=f"[cyan]{prd.id}[/cyan]  [white]{prd.title}[/white]  "
                  f"[{'green' if prd.status == PRDStatus.published else 'yellow'}]{prd.status.value}[/]",
        )
    )
    meta = f"[dim]Feature: {prd.feature_id or '—'}  |  Created: {prd.created_at.strftime('%Y-%m-%d %H:%M UTC')}  |  Updated: {prd.updated_at.strftime('%Y-%m-%d %H:%M UTC')}[/dim]"
    console.print(meta)
    if prd.confluence_url:
        console.print(f"[dim]Confluence: {prd.confluence_url}[/dim]")


@app.command("list")
def list_prds() -> None:
    storage = LocalStorage()
    prds = storage.list_all(PRD, "prds")

    if not prds:
        console.print("[dim]No PRDs found.[/dim]")
        return

    table = Table(title="PRDs", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Feature")
    table.add_column("Confluence")

    for p in prds:
        table.add_row(
            p.id,
            p.title,
            f"[green]{p.status.value}[/green]" if p.status == PRDStatus.published else p.status.value,
            p.feature_id or "—",
            p.confluence_url or "—",
        )

    console.print(table)
