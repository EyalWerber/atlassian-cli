# MCP Wrapper for atlassian-cli — Design Spec

## Goal

Expose atlassian-cli capabilities as MCP tools so Claude can call them automatically mid-conversation — searching memory, querying Jira, creating issues — without the user issuing CLI commands manually.

## Architecture

One new file (`atlassian_cli/mcp.py`) and one new entry point (`atlassian-mcp`) added to `pyproject.toml`. No new logic — the MCP server imports the same `JiraClient`, `MemoryStore`, `OllamaClient`, and `get_settings()` the CLI already uses.

```
atlassian_cli/
  mcp.py          ← NEW: MCP server, all tool definitions
  commands/       ← unchanged
  integrations/   ← unchanged
  storage/        ← unchanged

pyproject.toml    ← add entry point: atlassian-mcp = "atlassian_cli.mcp:main"
```

Transport: **stdio**. Claude Code spawns `atlassian-mcp` as a subprocess and communicates via JSON over stdin/stdout. No ports, no HTTP, no long-running process to manage.

### One-time setup

Add to `.claude/settings.json` in the project (or global `~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "atlassian": {
      "command": "atlassian-mcp"
    }
  }
}
```

After that the server starts automatically every Claude Code session. No manual step required.

### Dependency

Add `mcp` (Anthropic's MCP Python SDK) to `pyproject.toml` dependencies.

## Tools

### Read-only (marked `readOnlyHint: true` — Claude calls freely, no permission prompt)

| Tool | Parameters | Returns |
|------|-----------|---------|
| `search_memory` | `query: str`, `limit: int = 5` | List of memory objects `{id, content, type, tags, feature_id}` |
| `list_memories` | `type: str = None`, `feature: str = None`, `limit: int = 20` | List of memory objects |
| `get_issue` | `key: str` | Issue object `{key, summary, status, type, assignee, description}` |
| `list_issues` | `jql: str = None`, `status: str = None` | List of issue objects `{key, summary, status}`. `jql` takes precedence over `status` if both provided. |

### Write (require user permission per call)

| Tool | Parameters | Returns |
|------|-----------|---------|
| `add_memory` | `content: str`, `type: str`, `tags: list[str] = []`, `feature_id: str = None` | `{id, content}` |
| `create_issue` | `summary: str`, `type: str`, `description: str = ""`, `parent_key: str = None` | `{key}` |
| `transition_issue` | `key: str`, `status: str` | `{key, status}` |
| `add_comment` | `key: str`, `body: str` | `{key}` |

### Type values for `add_memory`

`decision` | `context` | `note` | `bug` | `plan`

### Type values for `create_issue`

`Feature` | `Bug` | `Task` | `Story` | `Epic` | `Sub-task`

## Data Flow

```
Claude needs context
  → calls search_memory("vibration alert")   [no prompt, readOnly]
  → MCP server: MemoryStore.search(query)
  → returns [{id, content, ...}, ...]
  → Claude reads relevant chunks, continues

Claude wants to file a bug
  → calls create_issue("Login 500", "Bug", "POST /login returns 500")
  → Claude Code prompts user: "Allow create_issue?"
  → on approval: JiraClient.create_issue(...)
  → returns {key: "ACLI-13"}
```

## Error Handling

- If `.env` is missing or invalid: tool returns `{"error": "Not configured — run atlassian project init"}` instead of crashing the server.
- If Jira API returns 401: tool returns `{"error": "Auth failed — refresh API token at https://id.atlassian.com/manage-profile/security/api-tokens"}`.
- If Ollama is unreachable during `search_memory` (vector path): falls back to FTS search silently.
- The MCP server never exits on a tool error — it catches exceptions and returns them as structured error responses so Claude can report them to the user.

## Testing

- Unit tests mock `JiraClient` and `MemoryStore` and call tool handler functions directly (no MCP protocol needed for unit tests).
- One integration smoke test: start server via subprocess, send a valid `tools/call` JSON request over stdin, assert valid response on stdout.

## Files Changed

| File | Change |
|------|--------|
| `atlassian_cli/mcp.py` | New — MCP server entry point and all tool definitions |
| `pyproject.toml` | Add `mcp` dependency + `atlassian-mcp` script entry point |
| `.claude/settings.json` | New — MCP server configuration for this project |
| `tests/test_mcp.py` | New — unit tests for each tool handler |
| `CLAUDE.md` | Update to mention `atlassian-mcp` server |
