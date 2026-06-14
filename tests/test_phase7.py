from datetime import datetime, timezone
from atlassian_cli.models.qa import QAScenario, QAPlan, QAPlanStatus


def _now():
    return datetime.now(timezone.utc)


def test_qa_scenario_accepts_prd_section():
    s = QAScenario(
        title="Login happy path",
        steps=["Navigate to /login", "Submit form"],
        expected_result="Redirect to /dashboard",
        prd_section="Functional Requirements",
    )
    assert s.prd_section == "Functional Requirements"


def test_qa_scenario_prd_section_defaults_none():
    s = QAScenario(
        title="No section",
        steps=["Do thing"],
        expected_result="Thing done",
    )
    assert s.prd_section is None


def test_qa_plan_accepts_confluence_fields():
    plan = QAPlan(
        id="QA-001",
        feature_id="FEAT-001",
        prd_id="PRD-001",
        qa_base_url="http://localhost:3000",
        scenarios=[],
        created_at=_now(),
        updated_at=_now(),
        confluence_page_id="123456",
        confluence_url="https://example.atlassian.net/wiki/spaces/SI/pages/123456",
    )
    assert plan.confluence_page_id == "123456"
    assert plan.confluence_url is not None


def test_qa_plan_confluence_fields_default_none():
    plan = QAPlan(
        id="QA-001",
        feature_id="FEAT-001",
        prd_id="PRD-001",
        qa_base_url="",
        scenarios=[],
        created_at=_now(),
        updated_at=_now(),
    )
    assert plan.confluence_page_id is None
    assert plan.confluence_url is None


from atlassian_cli.integrations.ollama import _QA_SCENARIO_SCHEMA, _QA_SYSTEM_PROMPT
from atlassian_cli.commands.qa import _build_scenarios


def test_qa_schema_includes_prd_section():
    assert "prd_section" in _QA_SCENARIO_SCHEMA


def test_qa_system_prompt_mentions_prd_section():
    assert "prd_section" in _QA_SYSTEM_PROMPT


def test_build_scenarios_passes_prd_section():
    raw = [
        {
            "title": "Login happy path",
            "prd_section": "Functional Requirements",
            "steps": ["Navigate to /login"],
            "expected_result": "Dashboard shown",
        }
    ]
    scenarios = _build_scenarios(raw)
    assert scenarios[0].prd_section == "Functional Requirements"


def test_build_scenarios_prd_section_optional():
    raw = [
        {
            "title": "No section scenario",
            "steps": ["Do thing"],
            "expected_result": "Thing done",
        }
    ]
    scenarios = _build_scenarios(raw)
    assert scenarios[0].prd_section is None
