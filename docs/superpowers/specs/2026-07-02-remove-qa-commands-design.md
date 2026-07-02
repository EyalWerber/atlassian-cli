# atlassian-cli — Remove QA Scenario Generation & STP Publishing

**Date:** 2026-07-02
**Status:** Approved
**Author:** Claude Code + Eyal Werber
**Related ADRs:** ADR-007, ADR-008, ADR-009, ADR-010
**Companion spec:** QA-memory-mcp's `2026-07-02-qa-scenario-generation-design.md`

---

## Overview

QA scenario generation, QA-plan storage, and STP-to-Confluence publishing have moved to QA-memory-mcp (ADR-007). This spec removes the now-redundant code from atlassian-cli and points its docs/prompts at QA-memory-mcp instead.

**This must land after QA-memory-mcp's replacement ships**, not before — atlassian-cli's `qa bug` command (Jira filing) and the underlying `JiraClient.create_bug` stay; only the generation/storage/publishing surface goes.

## What's Removed

| File | Change |
|---|---|
| `atlassian_cli/commands/qa.py` | Delete `create`, `show`, `list`, `stp` commands and their helpers (`_build_scenarios`, `_build_qa_plan`). **Keep** `bug` — that's Jira issue filing with attachments, unrelated to generation/storage, and explicitly stays here per ADR-007. |
| `atlassian_cli/integrations/ollama.py` | Delete `generate_qa_scenarios`, `_QA_SYSTEM_PROMPT`, `_QA_SCENARIO_SCHEMA`. Keep `summarize_issue`, `decompose_prd`, `embed`, `warmup`, `ping` — unrelated. |
| `atlassian_cli/integrations/confluence.py` | Delete `stp_to_storage_format`. Keep `prd_to_storage_format`, `ConfluenceClient` — unrelated (`ConfluenceClient` is still imported by QA-memory-mcp). |
| `atlassian_cli/models/qa.py` | Delete entirely (`QAPlan`, `QAScenario`, `QAPlanStatus`) — nothing else in atlassian-cli references these once `commands/qa.py`'s generation path is gone. |
| `atlassian_cli/main.py` | Remove `app.add_typer(qa.app, name="qa")`... but see "What's Kept" below — `qa.py` isn't deleted, only trimmed, so this stays, pointing at the trimmed module. |

## What's Kept

`atlassian_cli/commands/qa.py` is **trimmed, not deleted** — the `bug` command (file a Jira bug with attachments, best-effort memory auto-save) stays exactly as-is, since bug filing is explicitly atlassian-cli's permanent responsibility (ADR-007). The `qa` Typer sub-app stays registered in `main.py`; it just loses 4 of its 5 commands.

`atlassian_cli/models/memory.py`'s `Memory.qa_id` field stays — it's now used by QA-memory-mcp's bug-request handoff (ADR-010) to link a memory entry to a `QAScenario.id` that lives in QA-memory-mcp's own database, not atlassian-cli's. This is a field on a shared model now referenced by an external consumer; do not remove it even though nothing in atlassian-cli itself sets it post-removal.

## Test Changes

Delete or trim any existing tests in atlassian-cli's suite that exercise `qa create`/`qa show`/`qa list`/`qa stp`, `generate_qa_scenarios`, or `stp_to_storage_format` — check `tests/` for coverage of these before removal and confirm nothing else depends on them (e.g., a fixture used by an unrelated test). Tests for `qa bug` stay and must still pass unmodified.

## Documentation Changes

- **`CLAUDE.md`** (or `README.md`, wherever atlassian-cli documents its command surface): remove references to `atlassian qa create/show/list/stp`; add a note that QA scenario generation and Software Test Plan publishing now live in QA-memory-mcp, with a pointer to that project.
- **`.env.example`**: `QA_BASE_URL` (if still referenced only by the removed `create` command) — check whether `qa_base_url` in `config.py`/`Settings` is used anywhere else (it was passed into `QAPlan.qa_base_url` in the removed code); if `qa_base_url` becomes fully unused after removal, remove the setting too. If anything else reads `settings.qa_base_url`, leave it.

## Verification

- Full test suite passes after removal, with pristine output (no orphaned imports, no skipped tests referencing deleted modules).
- `atlassian qa --help` still works and shows only `bug`.
- `atlassian qa bug` still works end-to-end (unchanged behavior) — this is the one command in this file that must not regress.
- Grep the codebase for any remaining reference to `QAPlan`, `QAScenario`, `generate_qa_scenarios`, `stp_to_storage_format` outside of git history — none should remain.

## Out of Scope

- Migrating any existing locally-stored `QAPlan`/`QAScenario` JSON files (`~/.atlassian-cli/qa/*.json`) into QA-memory-mcp's database — those are left in place as historical artifacts; no migration tool is built.
- Any change to `qa bug`'s behavior, Jira filing logic, or the `Memory`/`MemoryStore` classes themselves (beyond the `qa_id` field staying, unmodified).
