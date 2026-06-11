# atlassian-cli Phase 3 Design

**Date:** 2026-06-10
**Status:** Approved
**Author:** Claude Code + Eyal Werber

---

## Overview

Phase 3 adds a **QA planning agent** that generates human-readable test scenarios from a PRD (via Ollama), then provides tooling for Claude Code to file Jira bugs with full artifact attachments after running those scenarios through Playwright MCP.

The architecture is **agent-centric**: the CLI is a data tool (generate, store, file). Claude Code is the orchestrator (read scenarios, drive Playwright MCP, call `qa bug`).

---

## Architecture

| Role | Who does it |
|---|---|
| Generate test scenarios | CLI via Ollama |
| Store QA plan locally | CLI |
| Run browser tests | Claude Code via Playwright MCP |
| File Jira bugs with artifacts | CLI (`atlassian qa bug`) |

---

## New Files

| File | Responsibility |
|---|---|
| `atlassian_cli/models/qa.py` | `QAPlan`, `QAScenario` Pydantic models |
| `atlassian_cli/commands/qa.py` | `atlassian qa create/show/list/bug` |

**Existing files touched:**

| File | Change |
|---|---|
| `atlassian_cli/integrations/ollama.py` | Add `generate_qa_scenarios(prd)` method |
| `atlassian_cli/integrations/jira.py` | Add `create_bug` + `attach_file` methods |
| `atlassian_cli/config.py` | Add `qa_base_url: str = ""` setting |
| `atlassian_cli/storage/local.py` | Add `qa/` directory init |
| `atlassian_cli/main.py` | `app.add_typer(qa.app, name="qa")` |

---

## Data Models (`models/qa.py`)

```python
class QAPlanStatus(str, Enum):
    draft = "draft"        # scenarios generated, not yet tested
    executed = "executed"  # Claude Code has run the tests

class QAScenario(BaseModel):
    title: str
    steps: list[str]           # human-readable steps for Claude Code to execute
    expected_result: str
    bug_key: Optional[str] = None   # Jira key if a bug was filed
    log_path: Optional[str] = None  # scaffolded — open idea, product-specific

class QAPlan(BaseModel):
    id: str             # QA-001
    feature_id: str
    prd_id: str
    scenarios: list[QAScenario]
    status: QAPlanStatus = QAPlanStatus.draft
    created_at: datetime
    updated_at: datetime
```

`QAPlan` is stored at `~/.atlassian-cli/qa/QA-001.json`. Scenarios are nested inside it. `bug_key` starts as `None` and is populated when `qa bug` is called. No separate `QABug` model — bug details flow directly to Jira.

---

## Commands

### `atlassian qa create <feature-id>`

```bash
atlassian qa create FEAT-001
```

1. Load Feature → get `prd_id` → load PRD
2. `settings = get_settings()`
3. Spinner: "Generating QA scenarios with Ollama..."
4. `OllamaClient.generate_qa_scenarios(prd)` → validate into `list[QAScenario]`
5. Build `QAPlan` with auto-incremented ID (`QA-001`, `QA-002`, ...)
6. Save `~/.atlassian-cli/qa/QA-001.json`
7. Print Rich tree of all scenarios + their steps

### `atlassian qa show <qa-id>`

```bash
atlassian qa show QA-001
```

Rich tree output:
```
QA-001 — FEAT-001 [draft]
├── Login happy path
│   ├── 1. Navigate to /login
│   ├── 2. Enter valid credentials
│   ├── 3. Click Submit
│   └── Expected: Redirect to /dashboard
│   └── Bug: —
└── Login with wrong password
    ├── 1. Navigate to /login
    ├── 2. Enter invalid credentials
    └── Expected: Show error message
    └── Bug: APP-42
```

### `atlassian qa list`

Rich table: `ID | Feature | Status | Scenarios | Created`

### `atlassian qa bug <qa-id>`

```bash
atlassian qa bug QA-001 \
  --scenario "Login happy path" \
  --actual "Page shows 500 error" \
  --expected "Redirect to /dashboard" \
  --error "TypeError: Cannot read properties of undefined" \
  --screenshot /tmp/shot.png \
  --video /tmp/video.webm
```

Flags:

| Flag | Required | Description |
|---|---|---|
| `--scenario` | yes | Scenario title to link bug to |
| `--actual` | yes | Actual results text |
| `--expected` | yes | Expected results text |
| `--error` | no | Error/stack trace text |
| `--screenshot` | no | Path to screenshot file |
| `--video` | no | Path to video file |

Flow:
1. Load QAPlan
2. Find scenario by title (exit 1 if not found)
3. `settings = get_settings()`
4. `JiraClient.create_bug(summary, actual, expected, error)` → get key
5. `JiraClient.attach_file(key, screenshot)` if provided
6. `JiraClient.attach_file(key, video)` if provided
7. Patch `scenario.bug_key = key` in QAPlan
8. Save updated plan
9. Print `[green]Bug filed: {key}[/green]`

---

## Ollama Integration (`integrations/ollama.py` addition)

**New method:** `generate_qa_scenarios(prd: PRD) -> list[dict]`

- Same pattern as `decompose_prd`: `POST /api/chat` with `"format": "json"`, `"stream": False`, timeout=120
- System prompt:

```
You are a QA planning agent. Read the PRD and return ONLY valid JSON matching this schema:
{
  "scenarios": [
    {
      "title": "string",
      "steps": ["string", ...],
      "expected_result": "string"
    }
  ]
}
Cover: happy path, edge cases, error states. Steps must be human-readable instructions
(e.g. "Navigate to /login", "Enter email field with value 'test@example.com'").
```

- Number of scenarios: Ollama decides based on PRD complexity
- Returns raw list — command layer validates into `list[QAScenario]`
- Error handling identical to `decompose_prd`: `try/except (KeyError, ValueError)` → `RuntimeError`

---

## Jira Integration (`integrations/jira.py` additions)

### `create_bug(summary, actual, expected, error) -> str`

```python
def create_bug(
    self,
    summary: str,
    actual: str,
    expected: str,
    error: Optional[str] = None,
) -> str:
```

- `issuetype: Bug`
- ADF description with structured headings:
  - `h3: Actual Results` → paragraph(actual)
  - `h3: Expected Results` → paragraph(expected)
  - `h3: Error` → paragraph(error) — omitted if `None`
- Returns issue key

### `attach_file(issue_key, path) -> None`

```python
def attach_file(self, issue_key: str, path: str) -> None:
```

- Calls `self._jira.issue_attach_file(issue_key, path)`
- Wraps in `try/except` → `RuntimeError(_friendly_error(e))`

---

## Configuration

One new setting added to `config.py`:

| Variable | Default | Used for |
|---|---|---|
| `QA_BASE_URL` | `""` | Target URL for Playwright tests — stored on QAPlan at creation |

`qa_base_url` is included on `QAPlan` at creation time (read from settings). Claude Code reads it from `qa show` output when driving Playwright.

---

## Local Storage

QA plans saved at `~/.atlassian-cli/qa/QA-001.json`.

Auto-increment follows the same pattern as plans: scan existing files, find highest number, increment.

---

## Error Handling

| Condition | Behavior |
|---|---|
| Feature not found | Exit 1 with clear message |
| Feature has no linked PRD | Exit 1: "Feature FEAT-001 has no linked PRD." |
| PRD not found | Exit 1 with clear message |
| Ollama unreachable | Exit 1: "Ollama not available at \<host\>. Is it running?" |
| Ollama returns invalid JSON | Exit 1: "Ollama returned unexpected response format." |
| `qa bug` scenario title not found | Exit 1: "Scenario '\<title\>' not found in QA-001." |
| Jira bug creation fails | Exit 1 with friendly error |
| File attachment fails | Print warning, continue (bug is already filed) |

---

## Out of Scope for Phase 3

- Claude API calls
- Playwright code generation (Claude Code drives MCP directly from human-readable steps)
- Log collection (scaffolded as `log_path: Optional[str]` on `QAScenario` — open idea)
- Re-running failed scenarios automatically
- Linking QA plan to a `Plan` (Phase 2 plan)
- Classic Jira project support
- Tests

---

## Phase Roadmap (updated)

| Phase | Scope |
|---|---|
| **1 ✓** | CLI framework, Atlassian integration, PRD management, Confluence publishing |
| **2 ✓** | Ollama planning agent, Jira Epic/Story/Task decomposition |
| **3 (this doc)** | QA planning, Playwright integration, Jira bug filing with attachments |
| 4 | Memory subsystem (SQLite + ChromaDB), ADR system, CLAUDE.md automation |
| 5 | Autonomous workflows, Docker, CI/CD agent mode |
