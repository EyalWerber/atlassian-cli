"""The wizard's create-new branches, which `test_project_init.py` does not reach.

`ensure_jira_project(create=True)` and `ensure_confluence_space(create=True)`
probe before they create and return `created=False` when the thing is already
there — an improvement on the old hard failure, but the wizard used to announce
"Created" either way. These pin the message to the returned flag.
"""

from unittest.mock import patch

from typer.testing import CliRunner

from atlassian_cli.commands.project import app

runner = CliRunner()


def _create_new_input() -> str:
    """Answers for a run that picks "create new" for both Jira and Confluence."""
    return "\n".join([
        "https://test.atlassian.net",
        "test@example.com",
        "mytoken",
        "mytoken",      # confirm token
        "n",            # Jira: create new
        "My App",       # project name
        "MYAPP",        # project key
        "n",            # Confluence: create new
        "My Space",     # space name
        "DEV",          # space key
        "",             # ollama host default
        "llama3.2",     # model
        "",             # embed model default
        "n",            # don't pull embed
        "",             # qa_base_url
        "l",            # local memory backend
    ])


def _run(tmp_path, monkeypatch, *, jira_created: bool, space_created: bool):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "atlassian_cli.provisioning.ensure_jira_project",
        lambda *a, **kw: {"key": "MYAPP", "created": jira_created, "id": "1"},
    )
    monkeypatch.setattr(
        "atlassian_cli.provisioning.ensure_issue_types",
        lambda *a, **kw: [],
    )
    monkeypatch.setattr(
        "atlassian_cli.provisioning.ensure_confluence_space",
        lambda *a, **kw: {"key": "DEV", "created": space_created},
    )
    with patch("atlassian_cli.commands.project._Jira"), \
         patch("atlassian_cli.commands.project._Confluence"), \
         patch("atlassian_cli.commands.project._ollama_list_models", return_value=[]), \
         patch("atlassian_cli.commands.project._ollama_pull", return_value=True), \
         patch("atlassian_cli.commands.project.OllamaClient") as MockOllama:
        MockOllama.return_value.ping.return_value = True
        result = runner.invoke(app, ["init"], input=_create_new_input())
    assert result.exit_code == 0, result.output
    return result.output


def test_wizard_says_created_when_it_created(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, jira_created=True, space_created=True)
    assert "Created Jira project: MYAPP" in out
    assert "Created Confluence space: DEV" in out


def test_wizard_says_found_when_the_thing_already_existed(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, jira_created=False, space_created=False)
    assert "Found existing Jira project: MYAPP" in out
    assert "Found existing Confluence space: DEV" in out
    assert "Created Jira project" not in out
    assert "Created Confluence space" not in out
