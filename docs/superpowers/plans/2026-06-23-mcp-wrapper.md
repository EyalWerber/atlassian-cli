# MCP Wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `atlassian-mcp` entry point that exposes Jira and memory operations as MCP tools so Claude can call them automatically mid-conversation.

**Architecture:** One new file `atlassian_cli/mcp.py` imports the existing `JiraClient`, `MemoryStore`, and `get_settings()` directly — no logic duplication. Tool handler functions are plain Python (easy to unit test). The MCP server wraps them with `@server.list_tools()` and `@server.call_tool()` decorators. Transport is stdio — Claude Code spawns the process automatically per session.

**Tech Stack:** `mcp` Python SDK (Anthropic), `asyncio`, existing `JiraClient` + `MemoryStore` + `OllamaClient`.

## Global Constraints

- Python ≥ 3.10 (already required by project)
- `mcp>=1.0.0` added as a project dependency (not dev-only)
- Entry point name: `atlassian-mcp` (matches settings.json config)
- MCP server name string: `"atlassian-cli"`
- All tool handler functions live at module level in `atlassian_cli/mcp.py` — no classes
- Read-only tools annotated with `ToolAnnotations(readOnlyHint=True)`
- Tool errors returned as `{"error": "..."}` JSON — never crash the server process
- Catch `SystemExit` (raised by `typer.Exit` when `.env` is missing) and return friendly error message
- Run all tests with: `python -m pytest tests/ -x -q`
- Commit after every task

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `atlassian_cli/mcp.py` | Create | MCP server: tool handler functions + MCP wiring + `main()` |
| `tests/test_mcp.py` | Create | Unit tests for all 8 tool handler functions |
| `pyproject.toml` | Modify | Add `mcp>=1.0.0` dependency + `atlassian-mcp` script entry point |
| `.claude/settings.json` | Create | Register `atlassian-mcp` server with Claude Code |
| `CLAUDE.md` | Modify | Add note that atlassian-mcp runs automatically |

---

### Task 1: Add `mcp` dependency, entry point, and server scaffold

**Files:**
- Modify: `pyproject.toml`
- Create: `atlassian_cli/mcp.py`

**Interfaces:**
- Produces: `atlassian_cli.mcp:main` callable, importable without error

- [ ] **Step 1: Write a failing import test**

```python
# tests/test_mcp.py
def test_mcp_module_imports():
    import atlassian_cli.mcp  # noqa: F401
```

- [ ] **Step 2: Run it to confirm it fails**

```
python -m pytest tests/test_mcp.py::test_mcp_module_imports -v
```

Expected: `ModuleNotFoundError: No module named 'atlassian_cli.mcp'`

- [ ] **Step 3: Add `mcp` to `pyproject.toml` dependencies and add the entry point**

Replace the `[project.scripts]` and `dependencies` sections:

```toml
dependencies = [
    "typer[all]>=0.12",
    "rich>=13",
    "pydantic>=2",
    "pydantic-settings>=2",
    "atlassian-python-api>=3.41",
    "python-dotenv>=1.0",
    "pyyaml>=6",
    "chromadb>=0.4",
    "mcp>=1.0.0",
]

[project.scripts]
atlassian = "atlassian_cli.main:app"
atlassian-mcp = "atlassian_cli.mcp:main"
```

- [ ] **Step 4: Create `atlassian_cli/mcp.py` with server scaffold only**

```python
"""MCP server for atlassian-cli — exposes Jira and memory tools to Claude."""
from __future__ import annotations

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool, ToolAnnotations

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.jira import JiraClient
from atlassian_cli.integrations.ollama import OllamaClient
from atlassian_cli.models.memory import Memory, MemoryType
from atlassian_cli.storage.memory_store import MemoryStore
from datetime import datetime, timezone

server = Server("atlassian-cli")


def _get_jira() -> JiraClient:
    return JiraClient(get_settings())


def _get_store() -> MemoryStore:
    s = get_settings()
    return MemoryStore(
        db_path=s.memory_db_path,
        vector_path=s.memory_vector_path,
        ollama=OllamaClient(s),
        turso_url=s.turso_url if s.memory_backend == "turso" else None,
        turso_auth_token=s.turso_auth_token if s.memory_backend == "turso" else None,
    )


@server.list_tools()
async def list_tools() -> list[Tool]:
    return []


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


async def _async_main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    asyncio.run(_async_main())
```

- [ ] **Step 5: Install and verify import**

```
pip install -e .
python -m pytest tests/test_mcp.py::test_mcp_module_imports -v
```

Expected: PASS

- [ ] **Step 6: Run full test suite — must still be green**

```
python -m pytest tests/ -x -q
```

Expected: all existing tests pass + 1 new

- [ ] **Step 7: Commit**

```
git add pyproject.toml atlassian_cli/mcp.py tests/test_mcp.py
git commit -m "feat(mcp): scaffold MCP server entry point with mcp dependency"
git push
```

---

### Task 2: Read-only tool handlers

**Files:**
- Modify: `atlassian_cli/mcp.py`
- Modify: `tests/test_mcp.py`

**Interfaces:**
- Produces: `search_memory(query, limit) -> list[dict]`, `list_memories(type, feature, limit) -> list[dict]`, `get_issue(key) -> dict`, `list_issues(jql, status) -> list[dict]`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_mcp.py  (append to existing file)
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest
from atlassian_cli.models.memory import Memory, MemoryType


def _mem(id="MEM-001", content="test", type=MemoryType.note, tags=None, feature_id=None):
    now = datetime.now(timezone.utc)
    return Memory(id=id, content=content, type=type, tags=tags or [],
                  feature_id=feature_id, created_at=now, updated_at=now)


@pytest.fixture
def mock_store():
    with patch("atlassian_cli.mcp._get_store") as m:
        store = MagicMock()
        m.return_value = store
        yield store


@pytest.fixture
def mock_jira():
    with patch("atlassian_cli.mcp._get_jira") as m:
        jira = MagicMock()
        m.return_value = jira
        yield jira


class TestSearchMemory:
    def test_returns_serialized_memories(self, mock_store):
        mock_store.search.return_value = [_mem(content="Bug in login")]
        from atlassian_cli.mcp import search_memory
        result = search_memory("login bug", limit=3)
        mock_store.search.assert_called_once_with("login bug", limit=3)
        assert result[0]["content"] == "Bug in login"
        assert "id" in result[0] and "type" in result[0] and "tags" in result[0]

    def test_empty_result(self, mock_store):
        mock_store.search.return_value = []
        from atlassian_cli.mcp import search_memory
        assert search_memory("nothing") == []


class TestListMemories:
    def test_filters_by_type(self, mock_store):
        mock_store.list.return_value = [_mem(type=MemoryType.bug)]
        from atlassian_cli.mcp import list_memories
        result = list_memories(type="bug")
        mock_store.list.assert_called_once_with(type=MemoryType.bug, feature_id=None, limit=20)
        assert result[0]["type"] == "bug"

    def test_no_filters(self, mock_store):
        mock_store.list.return_value = []
        from atlassian_cli.mcp import list_memories
        list_memories()
        mock_store.list.assert_called_once_with(type=None, feature_id=None, limit=20)

    def test_filters_by_feature(self, mock_store):
        mock_store.list.return_value = []
        from atlassian_cli.mcp import list_memories
        list_memories(feature="ACLI-4")
        mock_store.list.assert_called_once_with(type=None, feature_id="ACLI-4", limit=20)


class TestGetIssue:
    def test_returns_flattened_issue(self, mock_jira):
        mock_jira.get_issue.return_value = {
            "key": "ACLI-4",
            "fields": {
                "summary": "Memory System",
                "status": {"name": "Done"},
                "issuetype": {"name": "Feature"},
                "assignee": None,
                "description": None,
            }
        }
        from atlassian_cli.mcp import get_issue
        result = get_issue("ACLI-4")
        assert result == {
            "key": "ACLI-4", "summary": "Memory System", "status": "Done",
            "type": "Feature", "assignee": "", "description": "",
        }


class TestListIssues:
    def test_uses_jql_when_provided(self, mock_jira):
        mock_jira.search_issues.return_value = []
        with patch("atlassian_cli.mcp.get_settings") as ms:
            ms.return_value.jira_project = "ACLI"
            from atlassian_cli.mcp import list_issues
            list_issues(jql="project=ACLI AND assignee=currentUser()")
        mock_jira.search_issues.assert_called_once_with("project=ACLI AND assignee=currentUser()")

    def test_status_open_maps_to_jql(self, mock_jira):
        mock_jira.search_issues.return_value = []
        with patch("atlassian_cli.mcp.get_settings") as ms:
            ms.return_value.jira_project = "ACLI"
            from atlassian_cli.mcp import list_issues
            list_issues(status="open")
        query = mock_jira.search_issues.call_args[0][0]
        assert "statusCategory != Done" in query

    def test_status_done_maps_to_jql(self, mock_jira):
        mock_jira.search_issues.return_value = []
        with patch("atlassian_cli.mcp.get_settings") as ms:
            ms.return_value.jira_project = "ACLI"
            from atlassian_cli.mcp import list_issues
            list_issues(status="done")
        query = mock_jira.search_issues.call_args[0][0]
        assert "statusCategory = Done" in query

    def test_returns_flattened_issues(self, mock_jira):
        mock_jira.search_issues.return_value = [
            {"key": "ACLI-1", "fields": {"summary": "Feature PRD", "status": {"name": "Done"}}}
        ]
        with patch("atlassian_cli.mcp.get_settings") as ms:
            ms.return_value.jira_project = "ACLI"
            from atlassian_cli.mcp import list_issues
            result = list_issues()
        assert result == [{"key": "ACLI-1", "summary": "Feature PRD", "status": "Done"}]
```

- [ ] **Step 2: Run tests — confirm they all fail**

```
python -m pytest tests/test_mcp.py -v -k "Search or ListMem or GetIssue or ListIssues"
```

Expected: `ImportError` or `AttributeError` — functions don't exist yet

- [ ] **Step 3: Implement the 4 read-only handler functions and register them as MCP tools**

Replace the scaffold `list_tools` and `call_tool` in `atlassian_cli/mcp.py` with the full implementation:

```python
# ── Tool handler functions ──────────────────────────────────────────────────

def search_memory(query: str, limit: int = 5) -> list[dict]:
    store = _get_store()
    memories = store.search(query, limit=limit)
    return [
        {"id": m.id, "content": m.content, "type": m.type.value,
         "tags": m.tags, "feature_id": m.feature_id}
        for m in memories
    ]


def list_memories(
    type: str | None = None,
    feature: str | None = None,
    limit: int = 20,
) -> list[dict]:
    store = _get_store()
    mem_type = MemoryType(type) if type else None
    memories = store.list(type=mem_type, feature_id=feature, limit=limit)
    return [
        {"id": m.id, "content": m.content, "type": m.type.value,
         "tags": m.tags, "feature_id": m.feature_id}
        for m in memories
    ]


def get_issue(key: str) -> dict:
    issue = _get_jira().get_issue(key)
    fields = issue["fields"]
    return {
        "key": issue["key"],
        "summary": fields.get("summary", ""),
        "status": fields.get("status", {}).get("name", ""),
        "type": fields.get("issuetype", {}).get("name", ""),
        "assignee": (fields.get("assignee") or {}).get("displayName", ""),
        "description": str(fields.get("description") or ""),
    }


def list_issues(jql: str | None = None, status: str | None = None) -> list[dict]:
    jira = _get_jira()
    project = get_settings().jira_project
    if jql:
        query = jql
    elif status and status.lower() == "open":
        query = f"project={project} AND statusCategory != Done ORDER BY created DESC"
    elif status and status.lower() == "done":
        query = f"project={project} AND statusCategory = Done ORDER BY updated DESC"
    elif status:
        query = f'project={project} AND status = "{status}" ORDER BY created DESC'
    else:
        query = f"project={project} ORDER BY created DESC"
    issues = jira.search_issues(query)
    return [
        {"key": i["key"], "summary": i["fields"].get("summary", ""),
         "status": i["fields"]["status"]["name"]}
        for i in issues
    ]


# ── MCP tool definitions ────────────────────────────────────────────────────

_TOOLS: list[Tool] = [
    Tool(
        name="search_memory",
        description="Semantically search project memory. Call this BEFORE reading code files to find relevant context.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
            },
            "required": ["query"],
        },
        annotations=ToolAnnotations(readOnlyHint=True),
    ),
    Tool(
        name="list_memories",
        description="List memories filtered by type or feature ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["decision", "context", "note", "bug", "plan"]},
                "feature": {"type": "string", "description": "e.g. ACLI-4"},
                "limit": {"type": "integer"},
            },
        },
        annotations=ToolAnnotations(readOnlyHint=True),
    ),
    Tool(
        name="get_issue",
        description="Fetch a Jira issue by key.",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Issue key, e.g. ACLI-4"},
            },
            "required": ["key"],
        },
        annotations=ToolAnnotations(readOnlyHint=True),
    ),
    Tool(
        name="list_issues",
        description="List Jira issues. jql takes precedence over status if both provided.",
        inputSchema={
            "type": "object",
            "properties": {
                "jql": {"type": "string", "description": "Full JQL query"},
                "status": {"type": "string", "description": "Filter: status name, 'open', or 'done'"},
            },
        },
        annotations=ToolAnnotations(readOnlyHint=True),
    ),
]

_HANDLERS: dict = {
    "search_memory": lambda a: search_memory(a["query"], a.get("limit", 5)),
    "list_memories": lambda a: list_memories(a.get("type"), a.get("feature"), a.get("limit", 20)),
    "get_issue": lambda a: get_issue(a["key"]),
    "list_issues": lambda a: list_issues(a.get("jql"), a.get("status")),
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return _TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    handler = _HANDLERS.get(name)
    if not handler:
        result: dict = {"error": f"Unknown tool: {name}"}
    else:
        try:
            result = handler(arguments)
        except SystemExit:
            result = {"error": "Not configured — run 'atlassian project init' in your project directory"}
        except Exception as e:
            result = {"error": str(e)}
    return [TextContent(type="text", text=json.dumps(result))]
```

- [ ] **Step 4: Run the read-only tool tests**

```
python -m pytest tests/test_mcp.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Run full suite**

```
python -m pytest tests/ -x -q
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```
git add atlassian_cli/mcp.py tests/test_mcp.py
git commit -m "feat(mcp): add read-only tool handlers (search_memory, list_memories, get_issue, list_issues)"
git push
```

---

### Task 3: Write tool handlers

**Files:**
- Modify: `atlassian_cli/mcp.py`
- Modify: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `_get_jira() -> JiraClient`, `_get_store() -> MemoryStore` from Task 1
- Produces: `add_memory(content, type, tags, feature_id) -> dict`, `create_issue(summary, type, description, parent_key) -> dict`, `transition_issue(key, status) -> dict`, `add_comment(key, body) -> dict`

- [ ] **Step 1: Write failing tests — append to `tests/test_mcp.py`**

```python
class TestAddMemory:
    def test_creates_and_saves_memory(self, mock_store):
        mock_store.next_id.return_value = "MEM-010"
        from atlassian_cli.mcp import add_memory
        result = add_memory("Architecture decision", type="decision", tags=["arch"])
        saved: Memory = mock_store.add.call_args[0][0]
        assert saved.type == MemoryType.decision
        assert saved.tags == ["arch"]
        assert saved.content == "Architecture decision"
        assert result == {"id": "MEM-010", "content": "Architecture decision"}

    def test_defaults_to_note_type(self, mock_store):
        mock_store.next_id.return_value = "MEM-011"
        from atlassian_cli.mcp import add_memory
        add_memory("plain note")
        saved: Memory = mock_store.add.call_args[0][0]
        assert saved.type == MemoryType.note

    def test_empty_tags_default(self, mock_store):
        mock_store.next_id.return_value = "MEM-012"
        from atlassian_cli.mcp import add_memory
        add_memory("note")
        saved: Memory = mock_store.add.call_args[0][0]
        assert saved.tags == []


class TestCreateIssue:
    def test_returns_key(self, mock_jira):
        mock_jira.create_issue.return_value = "ACLI-15"
        from atlassian_cli.mcp import create_issue
        result = create_issue("New feature", type="Feature", description="desc")
        assert result == {"key": "ACLI-15"}
        mock_jira.create_issue.assert_called_once_with(
            summary="New feature", description="desc",
            issue_type="Feature", parent_key=None,
        )

    def test_passes_parent_key(self, mock_jira):
        mock_jira.create_issue.return_value = "ACLI-16"
        from atlassian_cli.mcp import create_issue
        create_issue("Subtask", type="Sub-task", parent_key="ACLI-4")
        mock_jira.create_issue.assert_called_once_with(
            summary="Subtask", description="",
            issue_type="Sub-task", parent_key="ACLI-4",
        )

    def test_defaults_to_task_type(self, mock_jira):
        mock_jira.create_issue.return_value = "ACLI-17"
        from atlassian_cli.mcp import create_issue
        create_issue("Quick task")
        mock_jira.create_issue.assert_called_once_with(
            summary="Quick task", description="",
            issue_type="Task", parent_key=None,
        )


class TestTransitionIssue:
    def test_calls_transition_and_returns_status(self, mock_jira):
        from atlassian_cli.mcp import transition_issue
        result = transition_issue("ACLI-4", "Done")
        mock_jira.transition_issue.assert_called_once_with("ACLI-4", "Done")
        assert result == {"key": "ACLI-4", "status": "Done"}


class TestAddComment:
    def test_calls_add_comment(self, mock_jira):
        from atlassian_cli.mcp import add_comment
        result = add_comment("ACLI-4", "Fixed in latest commit")
        mock_jira.add_comment.assert_called_once_with("ACLI-4", "Fixed in latest commit")
        assert result == {"key": "ACLI-4"}
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/test_mcp.py -v -k "AddMemory or CreateIssue or TransitionIssue or AddComment"
```

Expected: `ImportError` or `AttributeError`

- [ ] **Step 3: Add write handler functions to `atlassian_cli/mcp.py` — insert after `list_issues`**

```python
def add_memory(
    content: str,
    type: str = "note",
    tags: list[str] | None = None,
    feature_id: str | None = None,
) -> dict:
    store = _get_store()
    now = datetime.now(timezone.utc)
    memory = Memory(
        id=store.next_id(),
        content=content,
        type=MemoryType(type),
        tags=tags or [],
        feature_id=feature_id,
        created_at=now,
        updated_at=now,
    )
    store.add(memory)
    return {"id": memory.id, "content": memory.content}


def create_issue(
    summary: str,
    type: str = "Task",
    description: str = "",
    parent_key: str | None = None,
) -> dict:
    key = _get_jira().create_issue(
        summary=summary,
        description=description,
        issue_type=type,
        parent_key=parent_key,
    )
    return {"key": key}


def transition_issue(key: str, status: str) -> dict:
    _get_jira().transition_issue(key, status)
    return {"key": key, "status": status}


def add_comment(key: str, body: str) -> dict:
    _get_jira().add_comment(key, body)
    return {"key": key}
```

- [ ] **Step 4: Add write tools to `_TOOLS` list and `_HANDLERS` dict in `atlassian_cli/mcp.py`**

Append to `_TOOLS`:

```python
    Tool(
        name="add_memory",
        description="Save a memory entry to the project memory store.",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "type": {"type": "string", "enum": ["decision", "context", "note", "bug", "plan"]},
                "tags": {"type": "array", "items": {"type": "string"}},
                "feature_id": {"type": "string", "description": "e.g. ACLI-4"},
            },
            "required": ["content"],
        },
    ),
    Tool(
        name="create_issue",
        description="Create a Jira issue of any type in the configured project.",
        inputSchema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "type": {"type": "string", "enum": ["Feature", "Bug", "Task", "Story", "Epic", "Sub-task"]},
                "description": {"type": "string"},
                "parent_key": {"type": "string", "description": "Parent issue key, e.g. ACLI-4"},
            },
            "required": ["summary"],
        },
    ),
    Tool(
        name="transition_issue",
        description="Move a Jira issue to a new status.",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "status": {"type": "string", "description": "Target status, e.g. 'In Progress', 'Done'"},
            },
            "required": ["key", "status"],
        },
    ),
    Tool(
        name="add_comment",
        description="Add a comment to a Jira issue.",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["key", "body"],
        },
    ),
```

Add to `_HANDLERS`:

```python
    "add_memory": lambda a: add_memory(a["content"], a.get("type", "note"), a.get("tags"), a.get("feature_id")),
    "create_issue": lambda a: create_issue(a["summary"], a.get("type", "Task"), a.get("description", ""), a.get("parent_key")),
    "transition_issue": lambda a: transition_issue(a["key"], a["status"]),
    "add_comment": lambda a: add_comment(a["key"], a["body"]),
```

- [ ] **Step 5: Run all MCP tests**

```
python -m pytest tests/test_mcp.py -v
```

Expected: all tests PASS

- [ ] **Step 6: Run full suite**

```
python -m pytest tests/ -x -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```
git add atlassian_cli/mcp.py tests/test_mcp.py
git commit -m "feat(mcp): add write tool handlers (add_memory, create_issue, transition_issue, add_comment)"
git push
```

---

### Task 4: Wire Claude Code + create Jira ticket

**Files:**
- Create: `.claude/settings.json`
- Modify: `CLAUDE.md`
- Run: `atlassian issue create` to file the feature in ACLI

**Interfaces:**
- Consumes: `atlassian-mcp` entry point from Task 1

- [ ] **Step 1: Create `.claude/settings.json`**

```json
{
  "mcpServers": {
    "atlassian": {
      "command": "atlassian-mcp"
    }
  }
}
```

- [ ] **Step 2: Verify the entry point is reachable**

```
where atlassian-mcp
```

Expected: a path like `C:\Users\eyalv\miniconda3\Scripts\atlassian-mcp.exe`

If missing: `pip install -e .` and retry.

- [ ] **Step 3: Update `CLAUDE.md` — add MCP section after the dev rules**

Open `i:\I_do\Programing\Python\agentic_stuff\atlassian_cli\CLAUDE.md` and append:

```markdown
## MCP Server

`atlassian-mcp` runs automatically when Claude Code opens this project (configured in `.claude/settings.json`).

Claude can call these tools without being asked:
- `search_memory(query)` — search project memory before reading code
- `list_memories(type, feature)` — browse by type/feature
- `get_issue(key)` — fetch a Jira issue
- `list_issues(jql, status)` — query Jira

Write tools (Claude will ask for permission):
- `add_memory(content, type, tags, feature_id)`
- `create_issue(summary, type, description, parent_key)`
- `transition_issue(key, status)`
- `add_comment(key, body)`
```

- [ ] **Step 4: File the MCP feature in ACLI Jira**

```
cd i:\I_do\Programing\Python\agentic_stuff\atlassian_cli
atlassian feature create --name "MCP Server wrapper" --type new-feature --description "Expose atlassian-cli as an MCP server (atlassian-mcp entry point). Claude Code connects automatically via stdio. Read-only tools (search_memory, list_memories, get_issue, list_issues) called freely. Write tools (add_memory, create_issue, transition_issue, add_comment) require user approval."
```

- [ ] **Step 5: Run full test suite one final time**

```
python -m pytest tests/ -x -q
```

Expected: all tests pass

- [ ] **Step 6: Commit everything**

```
git add .claude/settings.json CLAUDE.md
git commit -m "feat(mcp): wire Claude Code MCP config and update CLAUDE.md"
git push
```

- [ ] **Step 7: Restart Claude Code to activate the MCP server**

Close and reopen Claude Code in this project. You should see `atlassian` listed in the MCP servers panel (bottom status bar or Tools menu). Claude can now call `search_memory`, `list_issues`, etc. without being asked.

---

## Self-Review

**Spec coverage:**
- ✅ One new file `atlassian_cli/mcp.py` — Task 1
- ✅ Entry point `atlassian-mcp` in `pyproject.toml` — Task 1
- ✅ `mcp>=1.0.0` dependency — Task 1
- ✅ 4 read-only tools with `readOnlyHint=True` — Task 2
- ✅ 4 write tools (no annotation) — Task 3
- ✅ `SystemExit` caught in `call_tool` — Task 2 (in the handler)
- ✅ `.claude/settings.json` — Task 4
- ✅ `CLAUDE.md` updated — Task 4
- ✅ Unit tests for all 8 tools — Tasks 2 & 3
- ✅ Jira ticket filed — Task 4

**Placeholder scan:** No TBDs, TODOs, or vague steps. All code is complete.

**Type consistency:** `_get_jira()` and `_get_store()` used consistently across all tasks. `MemoryType(type)` conversion used in both `list_memories` and `add_memory`. `jira.create_issue(summary, description, issue_type, parent_key)` matches the signature added to `JiraClient` earlier in this session.
