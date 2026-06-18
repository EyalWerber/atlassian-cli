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


from atlassian_cli.integrations.confluence import stp_to_storage_format
from atlassian_cli.models.prd import PRD, PRDStatus
from atlassian_cli.models.feature import Feature, FeatureType, FeatureStatus


def _make_plan_for_conf(scenarios=None):
    now = datetime.now(timezone.utc)
    return QAPlan(
        id="QA-001",
        feature_id="FEAT-001",
        prd_id="PRD-001",
        qa_base_url="",
        scenarios=scenarios or [
            QAScenario(
                title="Login happy path",
                steps=["Navigate to /login", "Enter credentials", "Submit"],
                expected_result="Redirect to /dashboard",
                prd_section="Functional Requirements",
            )
        ],
        created_at=now,
        updated_at=now,
    )


def _make_feature_for_conf():
    now = datetime.now(timezone.utc)
    return Feature(
        id="FEAT-001",
        name="Auth Service",
        type=FeatureType.new_feature,
        description="Handle user authentication",
        jira_key="SI-5",
        status=FeatureStatus.draft,
        created_at=now,
        updated_at=now,
    )


def _make_prd_for_conf():
    now = datetime.now(timezone.utc)
    return PRD(
        id="PRD-001",
        title="Auth PRD",
        summary="Auth system",
        problem="Users can't log in",
        personas="End users",
        stories="As a user I want to log in",
        business_value="Retention",
        requirements="Must support email/password login",
        nfr="Response under 200ms",
        considerations="",
        risks="Session hijacking",
        metrics="99% login success rate",
        out_of_scope="SSO",
        future_enhancements="",
        feature_id="FEAT-001",
        status=PRDStatus.published,
        confluence_url="https://example.atlassian.net/wiki/spaces/SI/pages/100",
        confluence_page_id="100",
        created_at=now,
        updated_at=now,
    )


def test_stp_contains_feature_jira_link():
    html = stp_to_storage_format(
        _make_plan_for_conf(), _make_feature_for_conf(), _make_prd_for_conf(),
        atlassian_url="https://example.atlassian.net",
        jira_project="SI",
    )
    assert "SI-5" in html
    assert "https://example.atlassian.net/browse/SI-5" in html


def test_stp_contains_prd_confluence_link():
    html = stp_to_storage_format(
        _make_plan_for_conf(), _make_feature_for_conf(), _make_prd_for_conf(),
        atlassian_url="https://example.atlassian.net",
        jira_project="SI",
    )
    assert "https://example.atlassian.net/wiki/spaces/SI/pages/100" in html
    assert "Auth PRD" in html


def test_stp_contains_section_headings():
    html = stp_to_storage_format(
        _make_plan_for_conf(), _make_feature_for_conf(), _make_prd_for_conf(),
        atlassian_url="https://example.atlassian.net",
        jira_project="SI",
    )
    for heading in ["Introduction", "Test Objectives", "Scope", "Test Strategy",
                    "Entry", "Test Cases", "Defect Management", "Risks"]:
        assert heading in html, f"Missing heading: {heading}"


def test_stp_test_cases_table_has_prd_section_link():
    html = stp_to_storage_format(
        _make_plan_for_conf(), _make_feature_for_conf(), _make_prd_for_conf(),
        atlassian_url="https://example.atlassian.net",
        jira_project="SI",
    )
    assert "Login happy path" in html
    assert "FunctionalRequirements" in html
    assert "https://example.atlassian.net/wiki/spaces/SI/pages/100#FunctionalRequirements" in html


def test_stp_test_cases_show_bug_key_when_present():
    plan = _make_plan_for_conf(scenarios=[
        QAScenario(
            title="Fails on bad password",
            steps=["Navigate", "Enter wrong password", "Submit"],
            expected_result="Error shown",
            prd_section="Functional Requirements",
            bug_key="SI-42",
        )
    ])
    html = stp_to_storage_format(
        plan, _make_feature_for_conf(), _make_prd_for_conf(),
        atlassian_url="https://example.atlassian.net",
        jira_project="SI",
    )
    assert "SI-42" in html


def test_stp_handles_missing_jira_key():
    feature = _make_feature_for_conf()
    feature = feature.model_copy(update={"jira_key": None})
    html = stp_to_storage_format(
        _make_plan_for_conf(), feature, _make_prd_for_conf(),
        atlassian_url="https://example.atlassian.net",
        jira_project="SI",
    )
    assert "Auth Service" in html
    assert "/browse/None" not in html


def test_stp_handles_unpublished_prd():
    prd = _make_prd_for_conf()
    prd = prd.model_copy(update={"confluence_url": None, "confluence_page_id": None})
    html = stp_to_storage_format(
        _make_plan_for_conf(), _make_feature_for_conf(), prd,
        atlassian_url="https://example.atlassian.net",
        jira_project="SI",
    )
    assert "Auth PRD" in html
    assert "FunctionalRequirements" not in html


def test_section_anchor_handles_hyphenated_names():
    from atlassian_cli.integrations.confluence import _section_anchor
    assert _section_anchor("Functional Requirements") == "FunctionalRequirements"
    assert _section_anchor("Non-Functional Requirements") == "Non-FunctionalRequirements"
    assert _section_anchor("User Stories") == "UserStories"


from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from atlassian_cli.commands.qa import app as qa_app

_runner = CliRunner()


def _mock_settings():
    s = MagicMock()
    s.atlassian_url = "https://example.atlassian.net"
    s.atlassian_api_token.get_secret_value.return_value = "token"
    s.jira_project = "SI"
    s.qa_base_url = ""
    s.memory_backend = "local"
    s.turso_url = None
    return s


def _make_models():
    from atlassian_cli.models.qa import QAPlan, QAScenario
    from atlassian_cli.models.feature import Feature, FeatureType, FeatureStatus
    from atlassian_cli.models.prd import PRD, PRDStatus
    now = datetime.now(timezone.utc)
    plan = QAPlan(
        id="QA-001", feature_id="FEAT-001", prd_id="PRD-001",
        qa_base_url="", scenarios=[], created_at=now, updated_at=now,
    )
    feature = Feature(
        id="FEAT-001", name="Auth", type=FeatureType.new_feature,
        description="Auth service", jira_key="SI-5",
        status=FeatureStatus.draft, created_at=now, updated_at=now,
    )
    prd = PRD(
        id="PRD-001", title="Auth PRD", summary="s", problem="p",
        personas="pe", stories="st", business_value="bv", requirements="req",
        nfr="nfr", considerations="", risks="r", metrics="m",
        out_of_scope="oos", future_enhancements="", feature_id="FEAT-001",
        status=PRDStatus.published, confluence_page_id="100",
        confluence_url="https://example.atlassian.net/wiki/spaces/SI/pages/100",
        created_at=now, updated_at=now,
    )
    return plan, feature, prd


def test_qa_stp_creates_confluence_page():
    plan, feature, prd = _make_models()
    from atlassian_cli.models.qa import QAPlan
    from atlassian_cli.models.feature import Feature
    from atlassian_cli.models.prd import PRD

    with patch("atlassian_cli.commands.qa.get_settings", return_value=_mock_settings()), \
         patch("atlassian_cli.commands.qa.LocalStorage") as MockStorage, \
         patch("atlassian_cli.commands.qa.ConfluenceClient") as MockConf, \
         patch("atlassian_cli.commands.qa.JiraClient"):

        mock_storage = MagicMock()
        MockStorage.return_value = mock_storage
        mock_storage.load.side_effect = lambda model, folder, id: {
            (QAPlan, "qa", "QA-001"): plan,
            (Feature, "features", "FEAT-001"): feature,
            (PRD, "prds", "PRD-001"): prd,
        }.get((model, folder, id))

        MockConf.return_value.create_page.return_value = (
            "999", "https://example.atlassian.net/wiki/spaces/SI/pages/999"
        )

        result = _runner.invoke(qa_app, ["stp", "QA-001"])

        assert result.exit_code == 0, result.output
        MockConf.return_value.create_page.assert_called_once()
        mock_storage.save.assert_called()


def test_qa_stp_updates_existing_page():
    _, feature, prd = _make_models()
    from atlassian_cli.models.qa import QAPlan
    from atlassian_cli.models.feature import Feature
    from atlassian_cli.models.prd import PRD
    now = datetime.now(timezone.utc)
    plan_with_page = QAPlan(
        id="QA-001", feature_id="FEAT-001", prd_id="PRD-001",
        qa_base_url="", scenarios=[], created_at=now, updated_at=now,
        confluence_page_id="999",
        confluence_url="https://example.atlassian.net/wiki/spaces/SI/pages/999",
    )

    with patch("atlassian_cli.commands.qa.get_settings", return_value=_mock_settings()), \
         patch("atlassian_cli.commands.qa.LocalStorage") as MockStorage, \
         patch("atlassian_cli.commands.qa.ConfluenceClient") as MockConf, \
         patch("atlassian_cli.commands.qa.JiraClient"):

        mock_storage = MagicMock()
        MockStorage.return_value = mock_storage
        mock_storage.load.side_effect = lambda model, folder, id: {
            (QAPlan, "qa", "QA-001"): plan_with_page,
            (Feature, "features", "FEAT-001"): feature,
            (PRD, "prds", "PRD-001"): prd,
        }.get((model, folder, id))

        result = _runner.invoke(qa_app, ["stp", "QA-001"])

        assert result.exit_code == 0, result.output
        MockConf.return_value.update_page.assert_called_once()
        MockConf.return_value.create_page.assert_not_called()


def test_qa_stp_exits_on_missing_plan():
    with patch("atlassian_cli.commands.qa.get_settings", return_value=_mock_settings()), \
         patch("atlassian_cli.commands.qa.LocalStorage") as MockStorage:
        MockStorage.return_value.load.return_value = None
        result = _runner.invoke(qa_app, ["stp", "QA-999"])
        assert result.exit_code == 1
        assert "✗" in result.output


def test_qa_stp_exits_on_confluence_failure():
    plan, feature, prd = _make_models()
    from atlassian_cli.models.qa import QAPlan
    from atlassian_cli.models.feature import Feature
    from atlassian_cli.models.prd import PRD

    with patch("atlassian_cli.commands.qa.get_settings", return_value=_mock_settings()), \
         patch("atlassian_cli.commands.qa.LocalStorage") as MockStorage, \
         patch("atlassian_cli.commands.qa.ConfluenceClient") as MockConf, \
         patch("atlassian_cli.commands.qa.JiraClient"):

        mock_storage = MagicMock()
        MockStorage.return_value = mock_storage
        mock_storage.load.side_effect = lambda model, folder, id: {
            (QAPlan, "qa", "QA-001"): plan,
            (Feature, "features", "FEAT-001"): feature,
            (PRD, "prds", "PRD-001"): prd,
        }.get((model, folder, id))
        MockConf.return_value.create_page.side_effect = RuntimeError("Confluence unreachable")

        result = _runner.invoke(qa_app, ["stp", "QA-001"])
        assert result.exit_code == 1
        assert "✗" in result.output


def test_qa_stp_links_jira_after_publish():
    plan, feature, prd = _make_models()
    from atlassian_cli.models.qa import QAPlan
    from atlassian_cli.models.feature import Feature
    from atlassian_cli.models.prd import PRD

    with patch("atlassian_cli.commands.qa.get_settings", return_value=_mock_settings()), \
         patch("atlassian_cli.commands.qa.LocalStorage") as MockStorage, \
         patch("atlassian_cli.commands.qa.ConfluenceClient") as MockConf, \
         patch("atlassian_cli.commands.qa.JiraClient") as MockJira:

        mock_storage = MagicMock()
        MockStorage.return_value = mock_storage
        mock_storage.load.side_effect = lambda model, folder, id: {
            (QAPlan, "qa", "QA-001"): plan,
            (Feature, "features", "FEAT-001"): feature,
            (PRD, "prds", "PRD-001"): prd,
        }.get((model, folder, id))
        MockConf.return_value.create_page.return_value = (
            "999", "https://example.atlassian.net/wiki/spaces/SI/pages/999"
        )

        result = _runner.invoke(qa_app, ["stp", "QA-001"])

        assert result.exit_code == 0, result.output
        MockJira.return_value.add_remote_link.assert_called_once_with(
            "SI-5",
            "https://example.atlassian.net/wiki/spaces/SI/pages/999",
            "STP: Auth",
        )


def test_qa_stp_update_path_also_links_jira():
    _, feature, prd = _make_models()
    from atlassian_cli.models.qa import QAPlan
    from atlassian_cli.models.feature import Feature
    from atlassian_cli.models.prd import PRD
    now = datetime.now(timezone.utc)
    plan_with_page = QAPlan(
        id="QA-001", feature_id="FEAT-001", prd_id="PRD-001",
        qa_base_url="", scenarios=[], created_at=now, updated_at=now,
        confluence_page_id="999",
        confluence_url="https://example.atlassian.net/wiki/spaces/SI/pages/999",
    )

    with patch("atlassian_cli.commands.qa.get_settings", return_value=_mock_settings()), \
         patch("atlassian_cli.commands.qa.LocalStorage") as MockStorage, \
         patch("atlassian_cli.commands.qa.ConfluenceClient"), \
         patch("atlassian_cli.commands.qa.JiraClient") as MockJira:

        mock_storage = MagicMock()
        MockStorage.return_value = mock_storage
        mock_storage.load.side_effect = lambda model, folder, id: {
            (QAPlan, "qa", "QA-001"): plan_with_page,
            (Feature, "features", "FEAT-001"): feature,
            (PRD, "prds", "PRD-001"): prd,
        }.get((model, folder, id))

        result = _runner.invoke(qa_app, ["stp", "QA-001"])

        assert result.exit_code == 0, result.output
        MockJira.return_value.add_remote_link.assert_called_once_with(
            "SI-5",
            "https://example.atlassian.net/wiki/spaces/SI/pages/999",
            "STP: Auth",
        )
