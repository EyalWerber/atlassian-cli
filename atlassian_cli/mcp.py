"""MCP server for atlassian-cli — exposes Jira and memory tools to Claude."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool, ToolAnnotations

from atlassian_cli.config import get_settings
from atlassian_cli.integrations.jira import JiraClient
from atlassian_cli.integrations.ollama import OllamaClient
from atlassian_cli.models.memory import Memory, MemoryType
from atlassian_cli.storage.memory_store import MemoryStore

server = Server("atlassian-cli")

_project_dir: Path | None = None
_roots_fetched: bool = False


async def _resolve_project_dir() -> Path | None:
    """Fetch workspace roots from the MCP client on first call and cache the result."""
    global _project_dir, _roots_fetched
    if _roots_fetched:
        return _project_dir
    _roots_fetched = True
    try:
        result = await server.request_context.session.list_roots()
        if result.roots:
            uri = str(result.roots[0].uri)
            path = Path(uri.removeprefix("file:///").removeprefix("file://"))
            if path.is_dir():
                _project_dir = path
    except Exception:
        pass
    return _project_dir


def _get_jira() -> JiraClient:
    return JiraClient(get_settings(env_dir=_project_dir))


def _get_store() -> MemoryStore:
    s = get_settings(env_dir=_project_dir)
    backend = s.memory_backend
    if backend not in ("local", "turso"):
        raise RuntimeError(
            f"MEMORY_BACKEND={backend!r} is not valid. Set it to 'local' or 'turso' in .env."
        )
    if backend == "turso" and not s.turso_url:
        raise RuntimeError(
            "MEMORY_BACKEND=turso requires TURSO_URL in .env. "
            "Run 'atlassian project init' to reconfigure."
        )
    return MemoryStore(
        db_path=s.memory_db_path,
        vector_path=s.memory_vector_path,
        ollama=OllamaClient(s),
        turso_url=s.turso_url if backend == "turso" else None,
        turso_auth_token=s.turso_auth_token if backend == "turso" else None,
    )


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
    priority: str | None = None,
) -> dict:
    key = _get_jira().create_issue(
        summary=summary,
        description=description,
        issue_type=type,
        parent_key=parent_key,
        priority=priority,
    )
    return {"key": key}


def update_issue(
    key: str,
    priority: str | None = None,
    description: str | None = None,
) -> dict:
    _get_jira().update_issue(key, priority=priority, description=description)
    updated = []
    if priority is not None:
        updated.append(f"priority={priority}")
    if description is not None:
        updated.append("description")
    return {"key": key, "updated": updated}


def transition_issue(key: str, status: str) -> dict:
    _get_jira().transition_issue(key, status)
    return {"key": key, "status": status}


def add_comment(key: str, body: str) -> dict:
    _get_jira().add_comment(key, body)
    return {"key": key}


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
                "priority": {"type": "string", "description": "Highest, High, Medium, Low, or Lowest"},
            },
            "required": ["summary"],
        },
    ),
    Tool(
        name="update_issue",
        description="Update fields on an existing Jira issue.",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Issue key, e.g. ACLI-4"},
                "priority": {"type": "string", "description": "Highest, High, Medium, Low, or Lowest"},
                "description": {"type": "string"},
            },
            "required": ["key"],
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
]

_HANDLERS: dict = {
    "search_memory": lambda a: search_memory(a["query"], a.get("limit", 5)),
    "list_memories": lambda a: list_memories(a.get("type"), a.get("feature"), a.get("limit", 20)),
    "get_issue": lambda a: get_issue(a["key"]),
    "list_issues": lambda a: list_issues(a.get("jql"), a.get("status")),
    "add_memory": lambda a: add_memory(a["content"], a.get("type", "note"), a.get("tags"), a.get("feature_id")),
    "create_issue": lambda a: create_issue(a["summary"], a.get("type", "Task"), a.get("description", ""), a.get("parent_key"), a.get("priority")),
    "update_issue": lambda a: update_issue(a["key"], a.get("priority"), a.get("description")),
    "transition_issue": lambda a: transition_issue(a["key"], a["status"]),
    "add_comment": lambda a: add_comment(a["key"], a["body"]),
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return _TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    await _resolve_project_dir()
    handler = _HANDLERS.get(name)
    if not handler:
        result: dict = {"error": f"Unknown tool: {name}"}
    else:
        try:
            result = handler(arguments)
        except SystemExit:
            result = {
                "error": "Not configured",
                "action": "Run 'atlassian project init' in your project directory to create the required .env file with Atlassian credentials and memory backend settings.",
            }
        except Exception as e:
            result = {"error": str(e)}
    return [TextContent(type="text", text=json.dumps(result))]


def _check_startup_env() -> None:
    """Warn on stderr if .env is missing or incomplete at server start."""
    import sys

    env_path = Path(".env")
    if not env_path.exists():
        print(
            "[atlassian-mcp] No .env found in current directory — "
            "run 'atlassian project init' to configure credentials.",
            file=sys.stderr,
            flush=True,
        )
        return
    text = env_path.read_text(encoding="utf-8")
    required = [
        "ATLASSIAN_URL", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN",
        "JIRA_PROJECT", "CONFLUENCE_SPACE", "MEMORY_BACKEND",
    ]
    missing = [k for k in required if k + "=" not in text]
    if missing:
        print(
            f"[atlassian-mcp] .env is missing required fields: {', '.join(missing)} — "
            "run 'atlassian project init' to reconfigure.",
            file=sys.stderr,
            flush=True,
        )


async def _async_main() -> None:
    _check_startup_env()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    asyncio.run(_async_main())
