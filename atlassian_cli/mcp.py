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


def set_parent(key: str, parent_key: str | None = None) -> dict:
    _get_jira().set_parent(key, parent_key)
    return {"key": key, "parent": parent_key}


def list_projects() -> list[dict]:
    return _get_jira().list_projects()


def get_project(key: str) -> dict:
    return _get_jira().get_project(key)


def create_project(
    key: str,
    name: str,
    share_with: str | None = None,
    description: str = "",
) -> dict:
    return _get_jira().create_project(
        key=key, name=name, share_with=share_with, description=description,
    )


def link_issues(
    inward_key: str,
    outward_key: str,
    link_type: str = "Relates",
) -> dict:
    _get_jira().add_link(inward_key, link_type, outward_key)
    return {"inward_key": inward_key, "link_type": link_type, "outward_key": outward_key}


def list_issue_links(key: str) -> list[dict]:
    return _get_jira().list_links(key)


def unlink_issues(
    key: str,
    other_key: str | None = None,
    link_type: str = "Relates",
    link_id: str | None = None,
) -> dict:
    jira = _get_jira()
    if link_id is None:
        if not other_key:
            raise ValueError("Provide either link_id, or other_key together with link_type.")
        match = next(
            (lnk for lnk in jira.list_links(key)
             if lnk["type"] == link_type
             and other_key in (lnk["outward_key"], lnk["inward_key"])),
            None,
        )
        if not match:
            raise ValueError(f"No '{link_type}' link between {key} and {other_key} found.")
        link_id = match["id"]
    jira.remove_link(link_id)
    return {"key": key, "removed_link_id": link_id}


def resolve_bug(
    key: str,
    solution: str,
    bug_memory_id: str | None = None,
) -> dict:
    """Transition a bug to Done, create a solution memory, and cross-link the original bug memory."""
    jira = _get_jira()
    store = _get_store()
    now = datetime.now(timezone.utc)

    # 1. Transition the issue to Done
    jira.transition_issue(key, "Done")

    # 2. Create solution memory tagged with the issue key
    solution_mem = Memory(
        id=store.next_id(),
        content=f"Solution [{key}]: {solution}",
        type=MemoryType("bug"),
        tags=[key, "solution"],
        feature_id=None,
        created_at=now,
        updated_at=now,
    )
    store.add(solution_mem)

    # 3. Find the original bug memory and append a back-reference
    linked_id: str | None = None
    if bug_memory_id:
        target = store.get(bug_memory_id)
    else:
        # Search memories tagged with this issue key, excluding solution memories
        candidates = [
            m for m in store.list(tag=key, limit=20)
            if "solution" not in m.tags and m.id != solution_mem.id
        ]
        target = candidates[0] if candidates else None

    if target:
        updated_content = target.content.rstrip() + f"\n\n→ Solution: [{solution_mem.id}]"
        store.update(target.id, updated_content)
        linked_id = target.id

    return {
        "key": key,
        "status": "Done",
        "solution_memory": solution_mem.id,
        "updated_bug_memory": linked_id,
    }


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
    Tool(
        name="resolve_bug",
        description=(
            "Mark a bug as Done, save a solution memory, and cross-link it to the original bug memory. "
            "Use this instead of transition_issue when closing a bug so the fix is documented. "
            "Creates a new memory (type=bug, tags=[key, 'solution']) and appends '→ Solution: [MEM-XXX]' "
            "to any existing bug memory tagged with the same issue key."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Jira issue key, e.g. TC-11"},
                "solution": {
                    "type": "string",
                    "description": "How the bug was fixed — root cause, files changed, and what the fix does.",
                },
                "bug_memory_id": {
                    "type": "string",
                    "description": "Optional. MEM-XXX ID of the existing bug memory to cross-link. "
                                   "If omitted, the tool searches for a memory tagged with the issue key.",
                },
            },
            "required": ["key", "solution"],
        },
    ),
    Tool(
        name="set_parent",
        description=(
            "Re-parent an existing issue, or detach it by omitting parent_key. update_issue "
            "cannot do this. A child must sit at a LOWER hierarchy level than its parent: an "
            "Epic (level 1) can parent a Story, Task or Feature (level 0), and those can parent "
            "a Subtask (level -1). Two level-0 issues cannot be nested — to associate a Story "
            "with a Feature, use link_issues instead, and parent both to the Epic."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Issue to re-parent, e.g. CONA-3"},
                "parent_key": {"type": "string", "description": "New parent, e.g. CONA-1. Omit to detach."},
            },
            "required": ["key"],
        },
    ),
    Tool(
        name="list_projects",
        description="List every Jira project on the site with its key, name, id, style and type.",
        inputSchema={"type": "object", "properties": {}},
        annotations=ToolAnnotations(readOnlyHint=True),
    ),
    Tool(
        name="get_project",
        description=(
            "Fetch one Jira project: key, name, id, style (classic vs next-gen) and the "
            "issue types available in it. Use this to confirm a project offers the issue "
            "types you need — e.g. 'Feature' — before creating issues in it."
        ),
        inputSchema={
            "type": "object",
            "properties": {"key": {"type": "string", "description": "Project key, e.g. YDMC"}},
            "required": ["key"],
        },
        annotations=ToolAnnotations(readOnlyHint=True),
    ),
    Tool(
        name="create_project",
        description=(
            "Create a new Jira project. Omit share_with for the default team-managed "
            "software template, which on most sites already provides Epic, Feature, Story, "
            "Task, Subtask and Bug — check with get_project afterwards. Pass share_with with "
            "the key of an existing CLASSIC project to copy its configuration instead; note "
            "that sharing copies permission schemes and therefore FAILS on the Jira free plan."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "New project key, e.g. CONA"},
                "name": {"type": "string", "description": "Human-readable project name"},
                "share_with": {
                    "type": "string",
                    "description": "Key of an existing classic project to copy configuration from, e.g. MC",
                },
                "description": {"type": "string"},
            },
            "required": ["key", "name"],
        },
    ),
    Tool(
        name="link_issues",
        description=(
            "Create a link between two existing Jira issues. Use this to associate issues that "
            "cannot be parented to each other — for example linking a Story to a Feature, since "
            "a Feature cannot contain Stories. For parent/child nesting (Epic→Feature, "
            "Story→Sub-task) pass parent_key to create_issue instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "inward_key": {"type": "string", "description": "Source issue key, e.g. YDMC-493"},
                "outward_key": {"type": "string", "description": "Target issue key, e.g. YDMC-492"},
                "link_type": {
                    "type": "string",
                    "description": "Link type name as configured in Jira. Common values: "
                                   "'Relates', 'Blocks', 'Duplicate', 'Cloners'. Defaults to 'Relates'.",
                },
            },
            "required": ["inward_key", "outward_key"],
        },
    ),
    Tool(
        name="list_issue_links",
        description="List every issue link on a Jira issue, with each link's id, type and both endpoints.",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Issue key, e.g. YDMC-492"},
            },
            "required": ["key"],
        },
        annotations=ToolAnnotations(readOnlyHint=True),
    ),
    Tool(
        name="unlink_issues",
        description=(
            "Remove a link between two Jira issues. Either pass link_id directly (from "
            "list_issue_links), or pass other_key with link_type to look the link up."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Issue key that owns the link, e.g. YDMC-493"},
                "other_key": {"type": "string", "description": "The issue at the other end of the link"},
                "link_type": {"type": "string", "description": "Defaults to 'Relates'"},
                "link_id": {"type": "string", "description": "Link id from list_issue_links; skips lookup"},
            },
            "required": ["key"],
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
    "resolve_bug": lambda a: resolve_bug(a["key"], a["solution"], a.get("bug_memory_id")),
    "set_parent": lambda a: set_parent(a["key"], a.get("parent_key")),
    "list_projects": lambda a: list_projects(),
    "get_project": lambda a: get_project(a["key"]),
    "create_project": lambda a: create_project(a["key"], a["name"], a.get("share_with"), a.get("description", "")),
    "link_issues": lambda a: link_issues(a["inward_key"], a["outward_key"], a.get("link_type", "Relates")),
    "list_issue_links": lambda a: list_issue_links(a["key"]),
    "unlink_issues": lambda a: unlink_issues(a["key"], a.get("other_key"), a.get("link_type", "Relates"), a.get("link_id")),
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
