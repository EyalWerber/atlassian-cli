# atlassian-cli Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally-installed Python CLI (`atlassian`) that Claude Code can use as a tool to create/manage features and PRDs, storing them locally and publishing to Atlassian Jira and Confluence.

**Architecture:** Domain-driven modules — `commands/`, `integrations/`, `models/`, `storage/` — each file has one clear responsibility and scales into Phases 2–5 without touching existing code. Claude Code operates the CLI; the CLI does not call Claude API.

**Tech Stack:** Python 3.11+, Typer, Rich, Pydantic v2, pydantic-settings, atlassian-python-api, python-dotenv

> **Note on tests:** Per the spec, no automated tests in Phase 1. Integration layers are all I/O against external Atlassian systems; tests land in a later phase. Each task has a manual verification step instead.

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package config, dependencies, `atlassian` entry point |
| `.env.example` | Credential template |
| `atlassian_cli/__init__.py` | Package marker |
| `atlassian_cli/main.py` | Typer app, sub-app registration |
| `atlassian_cli/config.py` | pydantic-settings config, startup validation, clean error table |
| `atlassian_cli/commands/__init__.py` | Package marker |
| `atlassian_cli/commands/feature.py` | `atlassian feature create/show/list` |
| `atlassian_cli/commands/prd.py` | `atlassian prd create/update/publish/show/list` |
| `atlassian_cli/integrations/__init__.py` | Package marker |
| `atlassian_cli/integrations/jira.py` | Jira REST wrapper (create_initiative, get, search, comment, remote link) |
| `atlassian_cli/integrations/confluence.py` | Confluence REST wrapper (create, update, get, label) |
| `atlassian_cli/models/__init__.py` | Package marker |
| `atlassian_cli/models/feature.py` | Feature Pydantic model + FeatureType/FeatureStatus enums |
| `atlassian_cli/models/prd.py` | PRD Pydantic model + PRDStatus enum |
| `atlassian_cli/storage/__init__.py` | Package marker |
| `atlassian_cli/storage/local.py` | JSON file store at `~/.atlassian-cli/`, auto-increment IDs |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `atlassian_cli/__init__.py`
- Create: `atlassian_cli/commands/__init__.py`
- Create: `atlassian_cli/integrations/__init__.py`
- Create: `atlassian_cli/models/__init__.py`
- Create: `atlassian_cli/storage/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "atlassian-cli"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "typer[all]>=0.12",
    "rich>=13",
    "pydantic>=2",
    "pydantic-settings>=2",
    "atlassian-python-api>=3.41",
    "python-dotenv>=1.0",
]

[project.scripts]
atlassian = "atlassian_cli.main:app"

[tool.setuptools.packages.find]
where = ["."]
include = ["atlassian_cli*"]
```

- [ ] **Step 2: Create `.env.example`**

```ini
# Atlassian Cloud base URL (no trailing slash)
ATLASSIAN_URL=https://yourcompany.atlassian.net

# Atlassian account email
ATLASSIAN_EMAIL=you@yourcompany.com

# API token from https://id.atlassian.com/manage-profile/security/api-tokens
ATLASSIAN_API_TOKEN=your_token_here

# Jira project key (e.g. MYAPP)
JIRA_PROJECT=MYAPP

# Confluence space key (e.g. DEV)
CONFLUENCE_SPACE=DEV

# --- Phase 2+ (optional, leave defaults) ---
# OLLAMA_HOST=http://localhost:11434
# OLLAMA_MODEL=llama3.2
# MEMORY_DB_PATH=~/.atlassian-cli/memory.db
```

- [ ] **Step 3: Create all empty `__init__.py` files**

Create these files, each with empty content:
- `atlassian_cli/__init__.py`
- `atlassian_cli/commands/__init__.py`
- `atlassian_cli/integrations/__init__.py`
- `atlassian_cli/models/__init__.py`
- `atlassian_cli/storage/__init__.py`

- [ ] **Step 4: Verify directory structure**

Run:
```
ls atlassian_cli/
```
Expected: `__init__.py  commands/  integrations/  models/  storage/`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .env.example atlassian_cli/
git commit -m "chore: scaffold atlassian-cli package structure"
```

---

## Task 2: Config Module

**Files:**
- Create: `atlassian_cli/config.py`

- [ ] **Step 1: Write `atlassian_cli/config.py`**

```python
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
import typer
from rich.console import Console
from rich.table import Table


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    atlassian_url: str
    atlassian_email: str
    atlassian_api_token: str
    jira_project: str
    confluence_space: str

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    memory_db_path: str = "~/.atlassian-cli/memory.db"


def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as e:
        console = Console()
        table = Table(title="[red]✗ Missing required configuration[/red]", show_header=True)
        table.add_column("Variable", style="yellow")
        table.add_column("Status", style="red")

        for err in e.errors():
            if err["type"] == "missing":
                var_name = str(err["loc"][0]).upper()
                table.add_row(var_name, "not set")

        console.print(table)
        console.print("\nRun: [bold]cp .env.example .env[/bold]  and fill in the values.")
        raise typer.Exit(1)
```

- [ ] **Step 2: Manually verify config loads**

Temporarily create a `.env` with one missing field, then run:
```bash
python -c "from atlassian_cli.config import get_settings; get_settings()"
```
Expected: Rich table showing the missing variable with "not set".

Restore `.env` with all fields set — rerun and expect no output (no error).

- [ ] **Step 3: Commit**

```bash
git add atlassian_cli/config.py
git commit -m "feat: add config module with pydantic-settings validation"
```

---

## Task 3: Models

**Files:**
- Create: `atlassian_cli/models/feature.py`
- Create: `atlassian_cli/models/prd.py`

- [ ] **Step 1: Write `atlassian_cli/models/feature.py`**

```python
from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class FeatureType(str, Enum):
    new_feature = "new-feature"
    enhancement = "enhancement"
    bug = "bug"
    refactor = "refactor"
    tech_debt = "tech-debt"
    research = "research"
    docs = "docs"
    architecture = "architecture"


class FeatureStatus(str, Enum):
    draft = "draft"
    active = "active"
    completed = "completed"


class Feature(BaseModel):
    id: str
    name: str
    type: FeatureType
    description: str
    prd_id: Optional[str] = None
    jira_key: Optional[str] = None
    status: FeatureStatus = FeatureStatus.draft
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: Write `atlassian_cli/models/prd.py`**

```python
from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PRDStatus(str, Enum):
    draft = "draft"
    published = "published"


class PRD(BaseModel):
    id: str
    title: str
    summary: str
    problem: str
    personas: str
    stories: str
    business_value: str
    requirements: str
    nfr: str
    considerations: str = ""
    risks: str
    metrics: str
    out_of_scope: str
    future_enhancements: str = ""
    feature_id: Optional[str] = None
    confluence_page_id: Optional[str] = None
    confluence_url: Optional[str] = None
    status: PRDStatus = PRDStatus.draft
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 3: Verify models parse correctly**

```bash
python -c "
from atlassian_cli.models.feature import Feature, FeatureType, FeatureStatus
from atlassian_cli.models.prd import PRD, PRDStatus
from datetime import datetime, timezone

now = datetime.now(timezone.utc)
f = Feature(id='FEAT-001', name='Test', type=FeatureType.new_feature,
            description='desc', created_at=now, updated_at=now)
print(f.model_dump_json(indent=2))

p = PRD(id='PRD-001', title='Test PRD', summary='s', problem='p',
        personas='u', stories='s', business_value='bv', requirements='r',
        nfr='n', risks='r', metrics='m', out_of_scope='o',
        created_at=now, updated_at=now)
print(p.model_dump_json(indent=2))
"
```
Expected: JSON output for both models with all fields populated.

- [ ] **Step 4: Commit**

```bash
git add atlassian_cli/models/
git commit -m "feat: add Feature and PRD Pydantic models"
```

---

## Task 4: Local Storage

**Files:**
- Create: `atlassian_cli/storage/local.py`

- [ ] **Step 1: Write `atlassian_cli/storage/local.py`**

```python
from pathlib import Path
from typing import TypeVar, Type, Optional
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LocalStorage:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path.home() / ".atlassian-cli"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "features").mkdir(exist_ok=True)
        (self.base_dir / "prds").mkdir(exist_ok=True)

    def save(self, model: BaseModel, collection: str) -> None:
        path = self.base_dir / collection / f"{model.id}.json"  # type: ignore[attr-defined]
        path.write_text(model.model_dump_json(indent=2), encoding="utf-8")

    def load(self, model_cls: Type[T], collection: str, id: str) -> Optional[T]:
        path = self.base_dir / collection / f"{id}.json"
        if not path.exists():
            return None
        return model_cls.model_validate_json(path.read_text(encoding="utf-8"))

    def list_all(self, model_cls: Type[T], collection: str) -> list[T]:
        dir_path = self.base_dir / collection
        return [
            model_cls.model_validate_json(f.read_text(encoding="utf-8"))
            for f in sorted(dir_path.glob("*.json"))
        ]

    def next_id(self, prefix: str, collection: str) -> str:
        dir_path = self.base_dir / collection
        count = len(list(dir_path.glob("*.json")))
        return f"{prefix}-{count + 1:03d}"
```

- [ ] **Step 2: Verify storage round-trips**

```bash
python -c "
from atlassian_cli.storage.local import LocalStorage
from atlassian_cli.models.feature import Feature, FeatureType
from datetime import datetime, timezone
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as tmp:
    store = LocalStorage(Path(tmp))
    now = datetime.now(timezone.utc)
    id_ = store.next_id('FEAT', 'features')
    f = Feature(id=id_, name='Test', type=FeatureType.new_feature,
                description='desc', created_at=now, updated_at=now)
    store.save(f, 'features')
    loaded = store.load(Feature, 'features', id_)
    assert loaded.name == 'Test', 'Load failed'
    all_items = store.list_all(Feature, 'features')
    assert len(all_items) == 1, 'List failed'
    print('Storage: all checks passed')
"
```
Expected: `Storage: all checks passed`

- [ ] **Step 3: Commit**

```bash
git add atlassian_cli/storage/local.py
git commit -m "feat: add local JSON storage with auto-increment IDs"
```

---

## Task 5: Jira Integration

**Files:**
- Create: `atlassian_cli/integrations/jira.py`

- [ ] **Step 1: Write `atlassian_cli/integrations/jira.py`**

```python
from atlassian import Jira
from atlassian_cli.config import Settings


_STATUS_MESSAGES = {
    401: "Invalid credentials. Check ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN.",
    403: "Permission denied. Check your account has access to this Jira project.",
    404: "Resource not found. Check JIRA_PROJECT value.",
}


def _friendly_error(e: Exception) -> str:
    resp = getattr(e, "response", None)
    if resp is not None:
        status = getattr(resp, "status_code", None)
        if status in _STATUS_MESSAGES:
            return _STATUS_MESSAGES[status]
    return str(e)


class JiraClient:
    def __init__(self, settings: Settings):
        self._jira = Jira(
            url=settings.atlassian_url,
            username=settings.atlassian_email,
            password=settings.atlassian_api_token,
            cloud=True,
        )
        self.project = settings.jira_project

    def create_initiative(self, summary: str, description: str) -> str:
        """Create an Initiative issue. Returns the issue key."""
        try:
            issue = self._jira.create_issue(fields={
                "project": {"key": self.project},
                "summary": summary,
                "description": {
                    "version": 1,
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": description}],
                        }
                    ],
                },
                "issuetype": {"name": "Initiative"},
            })
            return issue["key"]
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def get_issue(self, key: str) -> dict:
        try:
            return self._jira.issue(key)
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def search_issues(self, jql: str) -> list:
        try:
            return self._jira.jql(jql).get("issues", [])
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def add_comment(self, key: str, body: str) -> None:
        try:
            self._jira.issue_add_comment(key, body)
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def add_remote_link(self, key: str, url: str, title: str) -> None:
        try:
            self._jira.create_or_update_issue_remote_links(
                issue_key=key,
                link_url=url,
                title=title,
            )
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e
```

- [ ] **Step 2: Verify import (no credentials needed)**

```bash
python -c "from atlassian_cli.integrations.jira import JiraClient; print('Jira import OK')"
```
Expected: `Jira import OK`

- [ ] **Step 3: Commit**

```bash
git add atlassian_cli/integrations/jira.py
git commit -m "feat: add Jira integration wrapper"
```

---

## Task 6: Confluence Integration

**Files:**
- Create: `atlassian_cli/integrations/confluence.py`

- [ ] **Step 1: Write `atlassian_cli/integrations/confluence.py`**

```python
from atlassian import Confluence
from atlassian_cli.config import Settings
from atlassian_cli.models.prd import PRD


_STATUS_MESSAGES = {
    401: "Invalid credentials. Check ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN.",
    403: "Permission denied. Check your account has access to this Confluence space.",
    404: "Resource not found. Check CONFLUENCE_SPACE value.",
}


def _friendly_error(e: Exception) -> str:
    resp = getattr(e, "response", None)
    if resp is not None:
        status = getattr(resp, "status_code", None)
        if status in _STATUS_MESSAGES:
            return _STATUS_MESSAGES[status]
    return str(e)


def prd_to_storage_format(prd: PRD) -> str:
    """Convert a PRD to Confluence Storage Format (XHTML)."""
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
    ]
    if prd.future_enhancements:
        sections.append(("Future Enhancements", prd.future_enhancements))

    parts = []
    for heading, content in sections:
        if content:
            safe = (
                content
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br/>")
            )
            parts.append(f"<h2>{heading}</h2><p>{safe}</p>")
    return "\n".join(parts)


class ConfluenceClient:
    def __init__(self, settings: Settings):
        self._conf = Confluence(
            url=settings.atlassian_url,
            username=settings.atlassian_email,
            password=settings.atlassian_api_token,
            cloud=True,
        )
        self.space = settings.confluence_space

    def create_page(self, title: str, body: str) -> tuple[str, str]:
        """Create a page. Returns (page_id, page_url)."""
        try:
            page = self._conf.create_page(
                space=self.space,
                title=title,
                body=body,
                representation="storage",
            )
            page_id = str(page["id"])
            url = page["_links"]["base"] + page["_links"]["webui"]
            return page_id, url
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def update_page(self, page_id: str, title: str, body: str) -> None:
        try:
            self._conf.update_page(
                page_id=page_id,
                title=title,
                body=body,
                representation="storage",
            )
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def get_page_by_title(self, title: str) -> dict | None:
        try:
            return self._conf.get_page_by_title(space=self.space, title=title)
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def add_label(self, page_id: str, label: str) -> None:
        try:
            self._conf.set_page_label(page_id, label)
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e
```

- [ ] **Step 2: Verify the PRD formatter produces valid output**

```bash
python -c "
from atlassian_cli.integrations.confluence import prd_to_storage_format
from atlassian_cli.models.prd import PRD
from datetime import datetime, timezone

now = datetime.now(timezone.utc)
prd = PRD(
    id='PRD-001', title='Test', summary='Summary here',
    problem='Problem here', personas='End User',
    stories='As a user...', business_value='High value',
    requirements='Must do X', nfr='99.9% uptime',
    risks='Some risk', metrics='DAU', out_of_scope='Nothing',
    created_at=now, updated_at=now,
)
body = prd_to_storage_format(prd)
assert '<h2>Executive Summary</h2>' in body
assert '<h2>Problem Statement</h2>' in body
print('Confluence formatter: OK')
print(body[:200])
"
```
Expected: `Confluence formatter: OK` and the first 200 chars of the rendered HTML.

- [ ] **Step 3: Commit**

```bash
git add atlassian_cli/integrations/confluence.py
git commit -m "feat: add Confluence integration wrapper + PRD storage formatter"
```

---

## Task 7: Feature Commands

**Files:**
- Create: `atlassian_cli/commands/feature.py`

- [ ] **Step 1: Write `atlassian_cli/commands/feature.py`**

```python
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
    settings = get_settings()
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
                jira = JiraClient(settings)
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
```

- [ ] **Step 2: Verify import**

```bash
python -c "from atlassian_cli.commands.feature import app; print('Feature commands: OK')"
```
Expected: `Feature commands: OK`

- [ ] **Step 3: Commit**

```bash
git add atlassian_cli/commands/feature.py
git commit -m "feat: add feature create/show/list commands"
```

---

## Task 8: PRD Commands

**Files:**
- Create: `atlassian_cli/commands/prd.py`

- [ ] **Step 1: Write `atlassian_cli/commands/prd.py`**

```python
from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.confluence import ConfluenceClient, prd_to_storage_format
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
        console.print(f"[green]✓[/green] Confluence page updated: {prd.confluence_url}")
        return prd
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
            _publish(prd, storage)
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
```

- [ ] **Step 2: Verify import**

```bash
python -c "from atlassian_cli.commands.prd import app; print('PRD commands: OK')"
```
Expected: `PRD commands: OK`

- [ ] **Step 3: Commit**

```bash
git add atlassian_cli/commands/prd.py
git commit -m "feat: add PRD create/update/publish/show/list commands"
```

---

## Task 9: CLI Entry Point

**Files:**
- Create: `atlassian_cli/main.py`

- [ ] **Step 1: Write `atlassian_cli/main.py`**

```python
import typer

from atlassian_cli.commands import feature, prd

app = typer.Typer(
    name="atlassian",
    help="AI-native Atlassian delivery CLI — operates as a tool for Claude Code.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(feature.app, name="feature")
app.add_typer(prd.app, name="prd")

if __name__ == "__main__":
    app()
```

- [ ] **Step 2: Verify the app assembles without error**

```bash
python -c "from atlassian_cli.main import app; print('Main app: OK')"
```
Expected: `Main app: OK`

- [ ] **Step 3: Commit**

```bash
git add atlassian_cli/main.py
git commit -m "feat: wire CLI entry point, register feature + prd sub-apps"
```

---

## Task 10: Install and End-to-End Smoke Test

**Files:** none (just installation + manual test)

- [ ] **Step 1: Install the package**

```bash
pip install -e .
```
Expected: installs without errors, ends with `Successfully installed atlassian-cli-0.1.0`.

- [ ] **Step 2: Verify the `atlassian` command is available**

```bash
atlassian --help
```
Expected output includes:
```
Usage: atlassian [OPTIONS] COMMAND [ARGS]...
...
Commands:
  feature  Manage features
  prd      Manage PRDs
```

- [ ] **Step 3: Verify subcommand help**

```bash
atlassian feature --help
atlassian prd --help
```
Expected: each prints its own command list (`create`, `show`, `list` for feature; `create`, `update`, `publish`, `show`, `list` for prd).

- [ ] **Step 4: Verify config error handling (no .env)**

Run from a directory without a `.env` file:
```bash
cd /tmp
atlassian feature list
```
Expected: Rich table listing missing variables (`ATLASSIAN_URL`, `ATLASSIAN_EMAIL`, etc.) and the `cp .env.example .env` hint. Exit code 1.

- [ ] **Step 5: Create a feature with `--no-jira` (no Atlassian creds needed)**

```bash
atlassian feature create \
  --name "Test Feature" \
  --type new-feature \
  --description "A test feature to verify storage" \
  --no-jira
```
Expected:
```
✓ Feature created  [FEAT-001]
```

- [ ] **Step 6: Verify it was saved and is listable**

```bash
atlassian feature list
atlassian feature show FEAT-001
```
Expected: table with one row for `FEAT-001`, then a panel with its details.

- [ ] **Step 7: (Live test — requires .env) Create a feature with Jira Initiative**

With a valid `.env` in the working directory:
```bash
atlassian feature create \
  --name "Live Jira Test" \
  --type new-feature \
  --description "Testing live Jira integration"
```
Expected:
```
✓ Jira Initiative created  [MYAPP-XX]
✓ Feature created  [FEAT-002]
```

- [ ] **Step 8: (Live test — requires .env) Create and publish a PRD**

```bash
atlassian prd create \
  --title "Test PRD" \
  --summary "This is a test PRD summary" \
  --problem "We need to verify Confluence publishing works" \
  --personas "Developer" \
  --stories "As a developer I want to publish PRDs" \
  --business-value "Enables traceable requirements" \
  --requirements "Must publish to Confluence" \
  --nfr "Must complete in under 5 seconds" \
  --risks "API rate limits" \
  --metrics "PRDs published per sprint" \
  --out-of-scope "Nothing"
```
Expected:
```
✓ PRD saved locally  [PRD-001]
✓ Published to Confluence: https://yourcompany.atlassian.net/wiki/...
```

- [ ] **Step 9: Verify the Confluence page exists**

Open the URL printed above in a browser. Confirm it shows the PRD with all sections rendered as headings.

- [ ] **Step 10: Final commit**

```bash
git add .
git commit -m "chore: install verification complete, Phase 1 working"
```

---

## Phase 1 Complete

At this point `atlassian-cli` is installed and operational:

- `atlassian feature create/show/list` — local feature management + optional Jira Initiative creation
- `atlassian prd create/update/publish/show/list` — PRD management + Confluence publishing
- Clean error messages for missing config or Atlassian API failures
- All data persisted at `~/.atlassian-cli/`

**Next:** Phase 2 spec (Ollama planning agent, Jira Epic/Story/Task decomposition).
