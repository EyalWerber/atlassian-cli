# Project Context

This repo IS the `atlassian` CLI itself. When working in other projects that use this tool, run commands like `atlassian feature create` — never call the Python internals directly.

## The `atlassian` CLI

The installed CLI (`pip install -e .`) is the primary interface for all Jira/Confluence work:

```bash
atlassian feature create / show / list
atlassian prd create / publish
atlassian plan create
atlassian qa create / bug / stp / list
atlassian memory add / list / search / snapshot / push / pull
atlassian issue list [--status X] [--jql "..."]
atlassian project init              # setup wizard
atlassian project standardize       # apply Feature type + workflow to all projects
atlassian adr create / list
```

## Dev rules

- Run tests: `python -m pytest`
- After every commit: `git push` immediately
- Never call Python methods/Atlassian APIs directly — always use `atlassian <command>`
- The skill `/atlassian-cli` has the full command reference

## MCP Server

`atlassian-mcp` starts automatically when Claude Code opens this project (configured in `.claude/settings.json`).

Read-only tools (Claude calls freely, no permission prompt):
- `search_memory(query, limit)` — semantic search across project memory
- `list_memories(type, feature, limit)` — browse by type or feature ID
- `get_issue(key)` — fetch a Jira issue
- `list_issues(jql, status)` — query Jira issues

Write tools (Claude asks permission per call):
- `add_memory(content, type, tags, feature_id)`
- `create_issue(summary, type, description, parent_key)`
- `transition_issue(key, status)`
- `add_comment(key, body)`
