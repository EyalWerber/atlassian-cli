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

# Optional — Turso shared memory (Phase 5)
# MEMORY_BACKEND=local        # "local" (default) or "turso"
# TURSO_URL=libsql://your-db.turso.io
# TURSO_AUTH_TOKEN=your-turso-token
```

Get your API token at: https://id.atlassian.com/manage-profile/security/api-tokens

## Usage

### `atlassian project init`

Interactive setup wizard. Run once per project to create a local `.env` file.

```sh
cd my-project/
atlassian project init
```

The wizard will:
1. Ask for your Atlassian URL, email, and API token
2. Connect to an existing Jira project or create a new one
3. Connect to an existing Confluence space or create a new one
4. List installed Ollama models — pick one or pull a new model on the spot
5. Ask for a memory backend: local SQLite (default) or Turso
   - If Turso is chosen and the `turso` CLI is present, it can create the database automatically
6. Write `.env` in the current directory and verify all connections

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

### Issues

```bash
# Show issue details and links
atlassian issue show SI-42

# Transition status (available: To Do, In Progress, In Review, Done)
atlassian issue transition SI-42 "In Progress"

# List available transitions
atlassian issue transitions SI-42

# Add a comment
atlassian issue comment SI-42 "Fixed by refactoring the auth middleware."

# Add a blocking link (SI-11 blocks SI-8)
atlassian issue link SI-11 --blocks SI-8

# Remove a blocking link
atlassian issue unlink SI-11 --blocks SI-8

# Update issue description (e.g. write Confluence PRD URL back into Jira)
atlassian issue update SI-12 --description "PRD: https://confluence.example.com/wiki/spaces/X/pages/123"
```

### QA

```bash
atlassian qa create FEAT-001                      # Ollama → test scenarios
atlassian qa show QA-001
atlassian qa list
```

```bash
# Publish a Software Test Plan to Confluence
# Requires the QA plan to have a linked PRD published to Confluence
atlassian qa stp QA-001
```

This creates (or updates) a Confluence STP page containing:
- Header panel with links to the Jira feature ticket and PRD
- Introduction, objectives, scope, test strategy, entry/exit criteria
- Test cases table — each row links to the PRD section it exercises
- Defect management guidance and risks

The STP page URL is saved to the QA plan locally and linked back to the Jira feature issue as a remote link.

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

# Generate CLAUDE.md from memory + ADRs (no Ollama required)
atlassian memory snapshot

# Show backend status, memory counts, and connectivity
atlassian memory status

# Sync local memories → Turso (requires TURSO_URL in .env)
atlassian memory push

# Sync Turso → local + re-embed (requires TURSO_URL + Ollama)
atlassian memory pull
```

> `list`, `snapshot`, and `status` query SQLite/LocalStorage directly — no Ollama required.  
> `add` and `search` require Ollama running with `nomic-embed-text` pulled (`ollama pull nomic-embed-text`).  
> `pull` also requires Ollama to re-embed memories fetched from Turso.

**Backends:**
- `MEMORY_BACKEND=local` (default) — local SQLite, works offline. Use `push`/`pull` to sync with team.
- `MEMORY_BACKEND=turso` — Turso as primary store. Use `pull` to re-sync local search index.

#### Turso setup

**1. Install the CLI** (Turso support is built-in — no extra build tools needed):
```bash
pip install -e .
```

**2. Create a Turso database:**
```bash
npm install -g turso
turso auth login
turso db create atlassian-memory
turso db show atlassian-memory --url      # copy → TURSO_URL
turso db tokens create atlassian-memory   # copy → TURSO_AUTH_TOKEN
```

**3. Add to `.env`:**
```env
TURSO_URL=libsql://atlassian-memory-<your-org>.turso.io
TURSO_AUTH_TOKEN=<token>
MEMORY_BACKEND=local   # or "turso" to use Turso as primary store
```

**4. Verify and sync:**
```bash
atlassian memory status   # shows connectivity
atlassian memory push     # push local memories → Turso
```

### ADR (Architecture Decision Records)

```bash
# Record a decision (auto-saves to memory as type=decision)
atlassian adr add \
  --title "Use SQLite for local storage" \
  --context "Need persistent records without requiring a server" \
  --decision "Use Python stdlib sqlite3 module" \
  --consequences "Simple deployment; not suitable for concurrent multi-user access" \
  --feature FEAT-001

# List all ADRs
atlassian adr list
atlassian adr list --feature FEAT-001 --status accepted

# Show full detail
atlassian adr show ADR-001

# Publish to Confluence
atlassian adr publish ADR-001
```

Requires Ollama for memory auto-save (`ollama pull nomic-embed-text`). If Ollama is unavailable, the ADR is still saved locally — memory save is skipped with a warning.

## Local storage

All data is stored at `~/.atlassian-cli/`:

```
~/.atlassian-cli/
├── features/    FEAT-001.json ...
├── prds/        PRD-001.json  ...
├── plans/       PLAN-001.json ...
├── qa/          QA-001.json   ...
├── adrs/        ADR-001.json  ...
├── memory.db    SQLite — full memory records  (local mode only)
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
