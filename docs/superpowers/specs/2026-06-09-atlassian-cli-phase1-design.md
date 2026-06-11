# atlassian-cli Phase 1 Design

**Date:** 2026-06-09
**Status:** Approved
**Author:** Claude Code + Eyal Werber

---

## Overview

`atlassian-cli` is an AI-native software delivery operating system built as a local Python CLI. It is designed to be used **by Claude Code as a tool** — Claude generates content (PRDs, features, plans) in conversation, then uses this CLI to store, publish, and manage that content in Atlassian Jira and Confluence.

The CLI does **not** call the Claude API directly. Claude is the agent operating the CLI.

This document covers Phase 1 only. Subsequent phases (Ollama planning, QA/Playwright, memory, ADR, CLAUDE.md automation) each get their own spec.

---

## Installation & Invocation

```bash
pip install -e .
atlassian <command>
```

Registered via `pyproject.toml`:
```toml
[project.scripts]
atlassian = "atlassian_cli.main:app"
```

Available from any terminal (cmd, PowerShell, bash) after install.

---

## Environment Variables

Loaded from `.env` via `pydantic-settings`. Required fields are validated at startup on every command — missing vars print a clear error table and exit immediately.

### Required

| Variable | Description |
|---|---|
| `ATLASSIAN_URL` | e.g. `https://yourcompany.atlassian.net` |
| `ATLASSIAN_EMAIL` | Atlassian account email |
| `ATLASSIAN_API_TOKEN` | From id.atlassian.com/manage-profile/security |
| `JIRA_PROJECT` | Jira project key, e.g. `MYAPP` |
| `CONFLUENCE_SPACE` | Confluence space key, e.g. `DEV` |

### Optional (used in later phases)

| Variable | Default | Phase |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | 2 |
| `OLLAMA_MODEL` | `llama3.2` | 2 |
| `MEMORY_DB_PATH` | `~/.atlassian-cli/memory.db` | 4 |

No `ANTHROPIC_API_KEY` — Claude is the caller, not the callee.

---

## Project Structure

```
atlassian-cli/
├── atlassian_cli/
│   ├── __init__.py
│   ├── main.py                  # Typer app, sub-app registration
│   ├── config.py                # pydantic-settings config, startup validation
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── feature.py           # atlassian feature create/show/list
│   │   └── prd.py               # atlassian prd create/update/publish/show/list
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── jira.py              # Jira REST wrapper (atlassian-python-api)
│   │   └── confluence.py        # Confluence REST wrapper
│   ├── models/
│   │   ├── __init__.py
│   │   ├── feature.py           # Feature Pydantic model
│   │   └── prd.py               # PRD Pydantic model
│   └── storage/
│       ├── __init__.py
│       └── local.py             # JSON file store at ~/.atlassian-cli/
├── .env.example
├── pyproject.toml
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-06-09-atlassian-cli-phase1-design.md
```

**Architecture:** Domain-driven modules. New phases add to `commands/` and `integrations/` without touching existing code.

---

## Storage

Local persistence at `~/.atlassian-cli/`:

```
~/.atlassian-cli/
├── features/
│   └── FEAT-001.json
└── prds/
    └── PRD-001.json
```

JSON files containing all model fields + Atlassian IDs + timestamps. No database in Phase 1. SQLite + ChromaDB land in Phase 4.

IDs are auto-incrementing with prefix (`FEAT-001`, `PRD-001`).

---

## Commands

### Feature Commands

#### `atlassian feature create`

Creates a feature record locally and optionally a Jira Initiative.

**Flags mode (Claude-driven):**
```bash
atlassian feature create \
  --name "User Authentication" \
  --type new-feature \
  --description "Allow users to register and log in" \
  --prd-id PRD-001 \
  [--no-jira]        # skip Jira Initiative creation
```

**Feature types:** `new-feature`, `enhancement`, `bug`, `refactor`, `tech-debt`, `research`, `docs`, `architecture`

**Output:**
```
✓ Feature created  [FEAT-001]
✓ Jira Initiative created  [MYAPP-42]
```

**Local model fields:**
- `id` (FEAT-XXX)
- `name`
- `type`
- `description`
- `prd_id` (optional link)
- `jira_key` (optional, set after Jira creation)
- `status` (draft / active / completed)
- `created_at`, `updated_at`

#### `atlassian feature show <id>`

Prints feature details as a Rich panel including linked PRD and Jira issue key.

#### `atlassian feature list`

Rich table of all features: ID, name, type, status, linked PRD, Jira key.

---

### PRD Commands

#### `atlassian prd create`

Creates a PRD, stores locally, and publishes to Confluence.

**Two calling modes** — when no flags are provided, defaults to interactive prompts:

**Interactive (human-driven):** CLI prompts for each field sequentially.

**Flags mode (Claude-driven):**
```bash
atlassian prd create \
  --title "User Authentication" \
  --summary "Enable users to register, log in, and manage sessions" \
  --problem "Users cannot currently authenticate..." \
  --personas "End User, Admin" \
  --stories "As a user I want to..." \
  --business-value "Enables user retention and personalization..." \
  --requirements "The system must support email+password login..." \
  --nfr "99.9% uptime, <200ms auth response..." \
  --considerations "OAuth2 integration possible in Phase 2..." \
  --risks "Session token management complexity..." \
  --metrics "Registration conversion rate, login success rate..." \
  --out-of-scope "SSO, MFA (Phase 2)" \
  --feature-id FEAT-001
```

**PRD sections stored:**
- Executive Summary
- Problem Statement
- User Personas
- User Stories
- Business Value (derived from summary)
- Functional Requirements
- Non-Functional Requirements
- Technical Considerations
- Risks
- Success Metrics
- Out of Scope
- Future Enhancements (optional)

**Output:**
```
✓ PRD saved locally  [PRD-001]
✓ Published to Confluence: https://yourcompany.atlassian.net/wiki/spaces/DEV/pages/12345
```

#### `atlassian prd publish <id>`

Republishes existing local PRD to Confluence. Creates page if it doesn't exist; updates in-place if it does (matched by Confluence page ID stored on the PRD record).

#### `atlassian prd update <id>`

Updates one or more fields on a saved PRD then republishes to Confluence.

```bash
atlassian prd update PRD-001 --risks "Updated risk analysis..."
```

#### `atlassian prd show <id>`

Prints PRD content to terminal with Rich formatting (sections as panels).

#### `atlassian prd list`

Rich table: ID, title, status (draft/published), feature ID, Confluence URL, created date.

---

## Integrations

### Jira (`integrations/jira.py`)

Wraps `atlassian-python-api`. Phase 1 operations:

- `create_initiative(summary, description)` → returns issue key
- `get_issue(key)` → returns issue dict
- `search_issues(jql)` → returns list
- `add_comment(key, body)`
- `add_remote_link(key, url, title)` — links Confluence page to Jira issue

Phase 2 adds: `create_epic`, `create_story`, `create_task`, `create_subtask`.

### Confluence (`integrations/confluence.py`)

Wraps `atlassian-python-api`. Phase 1 operations:

- `create_page(space, title, body)` → returns page ID + URL
- `update_page(page_id, title, body)`
- `get_page_by_title(space, title)`
- `add_label(page_id, label)`

PRD body is rendered as Confluence Storage Format (XHTML). Each PRD section maps to an `<h2>` heading with content below.

---

## Error Handling

### Startup

```
✗ Missing required configuration:
  ATLASSIAN_API_TOKEN   not set
  CONFLUENCE_SPACE      not set

Run: cp .env.example .env  and fill in the values.
```

### API Errors

| HTTP Status | User message |
|---|---|
| 401 | Invalid credentials. Check ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN. |
| 403 | Permission denied. Check your account has access to this project/space. |
| 404 | Resource not found. Check JIRA_PROJECT and CONFLUENCE_SPACE values. |
| 5xx / network | Retries once, then exits with actionable message. |

### Rich Output Conventions

- `✓` green = success
- `✗` red = failure
- Spinner during API calls
- Tables for `list` commands
- Panels for `show` commands

---

## Dependencies

```toml
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
```

---

## Phase Roadmap

| Phase | Scope |
|---|---|
| **1 (this doc)** | CLI framework, Atlassian integration, PRD management, Confluence publishing |
| 2 | Ollama planning agent, Jira Epic/Story/Task decomposition |
| 3 | QA planning, Playwright integration, bug generation |
| 4 | Memory subsystem (SQLite + ChromaDB), ADR system, CLAUDE.md automation |
| 5 | Autonomous workflows, Docker, CI/CD agent mode |

---

## Out of Scope for Phase 1

- Claude API calls (Claude operates the CLI, doesn't get called by it)
- Ollama integration
- QA plans or Playwright
- Memory/ADR/CLAUDE.md management
- Docker
- Tests (integration tests added in a later phase once structure is stable)
- Jira Epic/Story/Task creation (Phase 2)
