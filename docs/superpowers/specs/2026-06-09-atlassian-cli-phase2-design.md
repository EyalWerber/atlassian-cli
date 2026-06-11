# atlassian-cli Phase 2 Design

**Date:** 2026-06-09
**Status:** Approved
**Author:** Claude Code + Eyal Werber

---

## Overview

Phase 2 adds an **Ollama-powered planning agent** that takes a Feature (and its linked PRD) and decomposes it into a three-level Jira hierarchy: Epic → Story → Task.

The CLI does **not** call Claude API. Claude Code is the agent operating the CLI. Ollama (Qwen 3) is the local LLM used for decomposition.

---

## Hierarchy

| Level | Meaning | Jira type |
|---|---|---|
| **Epic** | A version / release milestone | Epic |
| **Story** | A feature within that version | Story |
| **Task** | An implementation unit | Task |

Every Story has at least one Task. Every Epic has at least one Story.

---

## Command

```bash
atlassian plan create FEAT-001 [--save]
```

`FEAT-001` resolves to its linked PRD. The PRD content is sent to Ollama. The result is a `Plan` containing the full three-level hierarchy.

### Flow

1. Load Feature by ID → validate `prd_id` is set → load PRD (exits with clear error if either missing)
2. Spinner: "Generating plan with Ollama..."
3. `OllamaClient.decompose_prd(prd)` → validate into `Plan` Pydantic model
4. CLI prompts: **"Review plan before creating in Jira? [Y/n]"**
   - **Y**: write plan as YAML to a temp file → open `$EDITOR` (falls back to `notepad` on Windows, `nano` elsewhere) → read back → re-validate
   - **N**: proceed directly
5. If `--save`: persist `PLAN-001.json` to `~/.atlassian-cli/plans/`
6. CLI prompts: **"Create issues in Jira? [Y/n]"**
   - **Y**: create Epics → Stories → Tasks in Jira (see Jira Creation below)
   - **N**: exit cleanly (plan is saved locally if `--save` was used)

### Supporting commands

```bash
atlassian plan show PLAN-001   # Rich panel with full hierarchy + Jira keys
atlassian plan list            # Table: ID, feature, #epics, #stories, #tasks, status
```

`show` and `list` require `--save` to have been used when the plan was created.

---

## New Files

| File | Responsibility |
|---|---|
| `atlassian_cli/models/plan.py` | `Plan`, `Epic`, `Story`, `Task` Pydantic models |
| `atlassian_cli/integrations/ollama.py` | Ollama HTTP wrapper — sends PRD, returns structured JSON |
| `atlassian_cli/commands/plan.py` | `atlassian plan create/show/list` |

**Existing files touched:**
- `atlassian_cli/main.py` — one line: `app.add_typer(plan.app, name="plan")`
- `atlassian_cli/integrations/jira.py` — three new methods: `create_epic`, `create_story`, `create_task`

Everything else in Phase 1 is untouched.

---

## Data Models (`models/plan.py`)

```python
class PlanStatus(str, Enum):
    draft = "draft"
    created = "created"   # all Jira issues created

class Task(BaseModel):
    title: str
    description: str
    jira_key: Optional[str] = None

class Story(BaseModel):
    title: str
    description: str
    tasks: list[Task]
    jira_key: Optional[str] = None

class Epic(BaseModel):
    title: str          # version name
    description: str
    stories: list[Story]
    jira_key: Optional[str] = None

class Plan(BaseModel):
    id: str             # PLAN-001
    feature_id: str
    prd_id: str
    epics: list[Epic]
    status: PlanStatus = PlanStatus.draft
    created_at: datetime
    updated_at: datetime
```

`Plan` is the only model with a local ID. Epics/Stories/Tasks are nested inside it. `jira_key` fields start as `None` and are populated during Jira creation. If `--save` is used, the plan JSON is updated after each Epic completes so a partial run is not lost.

---

## Ollama Integration (`integrations/ollama.py`)

**Single public method:** `decompose_prd(prd: PRD) -> dict`

- `POST /api/chat` to `OLLAMA_HOST` with `"format": "json"` and model `OLLAMA_MODEL` (default: `qwen3`)
- System prompt includes the exact JSON schema expected:

```
System:
You are a software planning agent. Return ONLY valid JSON matching this schema:
{
  "epics": [
    {
      "title": "<version name>",
      "description": "<version goal>",
      "stories": [
        {
          "title": "<feature name>",
          "description": "<what to build>",
          "tasks": [
            { "title": "<task name>", "description": "<implementation detail>" }
          ]
        }
      ]
    }
  ]
}
Each Story must have at least one Task. Each Epic must have at least one Story.

User:
<PRD sections formatted as labeled text blocks>
```

- Returns the raw dict — the command layer validates it into Pydantic models
- Uses `requests` (already a transitive dep via atlassian-python-api) — no new dependencies
- If Ollama is unreachable: `RuntimeError("Ollama not available at <host>. Is it running?")`

---

## Jira Creation (`integrations/jira.py` additions)

Three new methods added to `JiraClient`:

```python
create_epic(summary, description, parent_key) -> str    # parent = Initiative key
create_story(summary, description, epic_key) -> str
create_task(summary, description, parent_key) -> str    # parent = Story key
```

All use the `parent` field (team-managed / next-gen Jira projects).

**Creation order with live Rich output:**
```
✓ Epic: v1.0 - Auth  [MYAPP-10]
  ✓ Story: Login flow  [MYAPP-11]
    ✓ Task: Implement JWT middleware  [MYAPP-12]
    ✓ Task: Add refresh token endpoint  [MYAPP-13]
  ✓ Story: Registration flow  [MYAPP-14]
    ✓ Task: Add email validation  [MYAPP-15]
```

If any individual creation fails, the CLI prints the error and continues — partial Jira work is retained. `jira_key` is written back to the in-memory Plan model as each issue is created. If `--save` was used, the plan JSON on disk is updated after each Epic.

---

## Configuration

No new environment variables. Phase 1 already defined:

| Variable | Default | Used for |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API base URL |
| `OLLAMA_MODEL` | `llama3.2` | Model name — set to `qwen3` in `.env` |

---

## Local Storage

Plans saved at `~/.atlassian-cli/plans/PLAN-001.json` when `--save` flag is used.

The Plan JSON is the single source of truth for Jira keys created during planning. The Feature JSON retains the Initiative `jira_key` from Phase 1 — it is not modified by the plan command.

---

## Error Handling

| Condition | Behavior |
|---|---|
| Feature not found | Exit 1 with clear message |
| Feature has no linked PRD | Exit 1: "Feature FEAT-001 has no linked PRD. Recreate it with `--prd-id`." |
| PRD not found | Exit 1 with clear message |
| Ollama unreachable | Exit 1: "Ollama not available at \<host\>. Is it running?" |
| Ollama returns invalid JSON | Exit 1: "Ollama returned invalid plan structure. Try again." |
| Jira creation fails (single issue) | Print warning, continue with remaining issues |
| Jira creation fails (all issues) | Print error summary, exit 1 |

---

## Phase Roadmap (updated)

| Phase | Scope |
|---|---|
| **1 ✓** | CLI framework, Atlassian integration, PRD management, Confluence publishing |
| **2 (this doc)** | Ollama planning agent, Jira Epic/Story/Task decomposition |
| 3 | QA planning, Playwright integration, bug generation |
| 4 | Memory subsystem (SQLite + ChromaDB), ADR system, CLAUDE.md automation |
| 5 | Autonomous workflows, Docker, CI/CD agent mode |

---

## Out of Scope for Phase 2

- Claude API calls
- Multi-turn Ollama conversations / iterative refinement
- Editing individual Epics/Stories/Tasks after creation (edit the YAML before creation)
- Jira Epic/Story/Task updates (only creation)
- Classic Jira project support (uses `parent` field, next-gen only)
- Tests (land in a later phase)
