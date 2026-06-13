# atlassian-cli

AI-native Atlassian delivery CLI — operates as a tool for Claude Code.

## What it does

A locally-installed Python CLI that Claude Code uses to manage software delivery in Jira and Confluence:

- **Features** — create/track features as Jira Initiatives
- **PRDs** — generate and publish Product Requirements Docs to Confluence
- **Plans** — decompose PRDs into Jira Epic→Story→Task hierarchies via Ollama
- **QA** — generate test scenarios from PRDs, file Jira bugs with screenshots and video

## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) running locally (`qwen3` or `llama3.2`)
- Atlassian account with API token
- Next-gen (team-managed) Jira project

## Installation

```bash
pip install -e .
```

## Configuration

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

```env
# Required
ATLASSIAN_URL=https://yourorg.atlassian.net
ATLASSIAN_EMAIL=you@example.com
ATLASSIAN_API_TOKEN=your_api_token
JIRA_PROJECT=MYAPP
CONFLUENCE_SPACE=MYSPACE

# Optional — Ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3

# Optional — QA target URL
QA_BASE_URL=http://localhost:3000
```

Get your API token at: https://id.atlassian.com/manage-profile/security/api-tokens

## Usage

### Features

```bash
atlassian feature create                          # interactive prompts
atlassian feature show FEAT-001
atlassian feature list
```

### PRDs

```bash
atlassian prd create FEAT-001                     # generate PRD from feature
atlassian prd show PRD-001
atlassian prd list
atlassian prd publish PRD-001                     # push to Confluence
```

### Plans (Jira decomposition)

```bash
atlassian plan create FEAT-001 [--save]           # Ollama → Epic/Story/Task
atlassian plan show PLAN-001
atlassian plan list
```

`--save` persists the plan to `~/.atlassian-cli/plans/`. Without it, the plan is only shown and optionally pushed to Jira.

### QA

```bash
atlassian qa create FEAT-001                      # Ollama → test scenarios
atlassian qa show QA-001
atlassian qa list
```

After Claude Code runs a scenario through Playwright and finds a bug:

```bash
atlassian qa bug QA-001 \
  --scenario "Login happy path" \
  --actual "Page shows 500 error" \
  --expected "Redirect to /dashboard" \
  --error "TypeError: Cannot read properties of undefined" \
  --screenshot /tmp/shot.png \
  --video /tmp/video.webm
```

This creates a Jira Bug with a structured description, attaches the artifacts, and links the bug key back to the scenario in the QA plan.

### Memory

```bash
atlassian memory add "Chose JWT over sessions for stateless mobile auth" \
  --type decision --tag auth --feature FEAT-001

atlassian memory add "Auth service is temporarily using Redis fallback" \
  --type context --tag auth

atlassian memory list                        # all memories, newest first
atlassian memory list --type decision        # filter by type
atlassian memory list --feature FEAT-001     # filter by feature
atlassian memory list --tag auth             # filter by tag

atlassian memory search "authentication approach"   # semantic search
atlassian memory search "auth" --feature FEAT-001   # scoped to feature

atlassian memory show MEM-001               # full record in a panel
atlassian memory delete MEM-001             # prompts for confirmation
```

> `list` queries SQLite directly — no Ollama required.  
> `add` and `search` require Ollama running with `nomic-embed-text` pulled (`ollama pull nomic-embed-text`).

## Local storage

All data is stored at `~/.atlassian-cli/`:

```
~/.atlassian-cli/
├── features/    FEAT-001.json ...
├── prds/        PRD-001.json  ...
├── plans/       PLAN-001.json ...
├── qa/          QA-001.json   ...
├── memory.db    SQLite — full memory records
└── vectors/     ChromaDB — semantic search index
```

## How Claude Code uses this

Claude Code treats this CLI as a tool — it calls commands, reads the output, and orchestrates the full delivery workflow:

```
atlassian feature create
  → atlassian prd create FEAT-001
  → atlassian prd publish PRD-001
  → atlassian plan create FEAT-001 --save
  → atlassian qa create FEAT-001
  → [Claude Code drives Playwright MCP through each scenario]
  → atlassian qa bug QA-001 --scenario "..." ...
```

## Architecture

```
atlassian_cli/
├── commands/       feature.py  prd.py  plan.py  qa.py
├── integrations/   jira.py  confluence.py  ollama.py
├── models/         feature.py  prd.py  plan.py  qa.py
├── storage/        local.py
├── config.py
└── main.py
```
