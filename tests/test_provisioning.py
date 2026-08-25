from pathlib import Path

import pytest

from atlassian_cli import provisioning as p

BASE_VALUES = {
    "atlassian_url": "https://test.atlassian.net",
    "atlassian_email": "test@example.com",
    "atlassian_api_token": "mytoken",
    "jira_project": "SI",
    "confluence_space": "SIDEV",
    "ollama_host": "http://localhost:11434",
    "ollama_model": "llama3.2",
    "ollama_embed_model": "nomic-embed-text",
    "qa_base_url": "",
    "memory_backend": "local",
}


def test_render_env_local_backend():
    out = p.render_env(BASE_VALUES)
    assert "ATLASSIAN_URL=https://test.atlassian.net" in out
    assert "ATLASSIAN_API_TOKEN=mytoken" in out
    assert "JIRA_PROJECT=SI" in out
    assert "MEMORY_BACKEND=local" in out
    assert "TURSO_URL" not in out
    assert out.endswith("\n")


def test_render_env_turso_backend():
    values = {**BASE_VALUES, "memory_backend": "turso",
              "turso_url": "libsql://x.turso.io", "turso_auth_token": "tok"}
    out = p.render_env(values)
    assert "MEMORY_BACKEND=turso" in out
    assert "TURSO_URL=libsql://x.turso.io" in out
    assert "TURSO_AUTH_TOKEN=tok" in out


def test_ensure_gitignored_creates_file(tmp_path):
    (tmp_path / ".git").mkdir()
    added = p.ensure_gitignored(tmp_path, [".env", "memory/"])
    assert added == [".env", "memory/"]
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".env\nmemory/\n"


def test_ensure_gitignored_is_idempotent(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    added = p.ensure_gitignored(tmp_path, [".env", "memory/"])
    assert added == ["memory/"]
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".env\nmemory/\n"


def test_ensure_gitignored_appends_newline_when_missing(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("build/", encoding="utf-8")
    p.ensure_gitignored(tmp_path, [".env"])
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "build/\n.env\n"


def test_ensure_gitignored_accepts_equivalent_env_patterns(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("*.env\n", encoding="utf-8")
    assert p.ensure_gitignored(tmp_path, [".env"]) == []


def test_ensure_gitignored_noop_outside_git_repo(tmp_path):
    assert p.ensure_gitignored(tmp_path, [".env"]) == []
    assert not (tmp_path / ".gitignore").exists()


def test_errors_are_provisioning_errors():
    for cls in (p.AuthError, p.JiraError, p.ConfluenceError):
        assert issubclass(cls, p.ProvisioningError)


import base64
import subprocess
from unittest.mock import MagicMock, patch


class _FakeClient:
    def __init__(self, url, cloud):
        self.url = url
        self.cloud = cloud
        self._session = MagicMock()
        self._session.headers = {}


def test_session_sets_utf8_basic_auth():
    client = p.session(_FakeClient, "https://x.atlassian.net/", "ü@example.com", "tok")
    expected = base64.b64encode("ü@example.com:tok".encode("utf-8")).decode("ascii")
    assert client._session.headers["Authorization"] == f"Basic {expected}"
    assert client._session.auth is None


def test_api_session_sets_json_headers():
    s = p.api_session("https://x.atlassian.net", "a@b.c", "tok")
    assert s.headers["Accept"] == "application/json"
    assert s.headers["Content-Type"] == "application/json"
    assert s.headers["Authorization"].startswith("Basic ")


def test_verify_credentials_returns_account_id():
    jira = MagicMock()
    jira.myself.return_value = {"accountId": "abc-123"}
    assert p.verify_credentials(jira) == "abc-123"


def test_verify_credentials_raises_auth_error_on_401():
    jira = MagicMock()
    jira.myself.side_effect = Exception("401 Unauthorized")
    with pytest.raises(p.AuthError) as exc:
        p.verify_credentials(jira)
    assert "token" in str(exc.value).lower()


def test_verify_credentials_raises_auth_error_on_connection_failure():
    jira = MagicMock()
    jira.myself.side_effect = Exception("connection refused")
    with pytest.raises(p.AuthError):
        p.verify_credentials(jira)


def test_ollama_list_models_returns_names():
    resp = MagicMock()
    resp.json.return_value = {"models": [{"name": "llama3.2"}, {"name": "nomic-embed-text"}]}
    with patch("atlassian_cli.provisioning.requests.get", return_value=resp):
        assert p.ollama_list_models("http://h") == ["llama3.2", "nomic-embed-text"]


def test_ollama_list_models_returns_empty_when_unreachable():
    with patch("atlassian_cli.provisioning.requests.get", side_effect=OSError("down")):
        assert p.ollama_list_models("http://h") == []


def test_ollama_pull_returns_true_on_success():
    with patch("atlassian_cli.provisioning.subprocess.run", return_value=MagicMock(returncode=0)):
        assert p.ollama_pull("llama3.2") is True


def test_ollama_pull_returns_false_on_nonzero_exit():
    with patch("atlassian_cli.provisioning.subprocess.run", return_value=MagicMock(returncode=1)):
        assert p.ollama_pull("llama3.2") is False


def test_ollama_pull_returns_false_when_binary_missing():
    with patch("atlassian_cli.provisioning.subprocess.run", side_effect=FileNotFoundError):
        assert p.ollama_pull("llama3.2") is False


def test_ollama_pull_returns_false_on_timeout():
    with patch(
        "atlassian_cli.provisioning.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ollama", timeout=300),
    ):
        assert p.ollama_pull("llama3.2") is False


def test_turso_available_false_when_missing():
    with patch("atlassian_cli.provisioning.subprocess.run", side_effect=FileNotFoundError):
        assert p.turso_available() is False


def test_turso_create_db_returns_url_and_token():
    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["turso", "db", "create"]:
            return MagicMock(returncode=0, stdout="")
        if "--url" in cmd:
            return MagicMock(returncode=0, stdout="libsql://db.turso.io\n")
        return MagicMock(returncode=0, stdout="tok-123\n")

    with patch("atlassian_cli.provisioning.subprocess.run", side_effect=fake_run):
        assert p.turso_create_db("db") == ("libsql://db.turso.io", "tok-123")


def test_issue_types_cover_the_full_hierarchy():
    names = [t[0] for t in p.ISSUE_TYPES]
    assert names == ["Epic", "Feature", "Story", "Task", "Sub-task", "Bug"]


def test_ensure_jira_project_verifies_existing():
    jira = MagicMock()
    jira.project.return_value = {"id": "10001", "key": "SI"}
    out = p.ensure_jira_project(jira, MagicMock(), "https://x", "si", create=False)
    assert out == {"key": "SI", "created": False, "id": "10001"}
    jira.create_project_from_raw_json.assert_not_called()


def test_ensure_jira_project_raises_when_missing_and_not_creating():
    jira = MagicMock()
    jira.project.side_effect = Exception("404")
    with pytest.raises(p.JiraError):
        p.ensure_jira_project(jira, MagicMock(), "https://x", "SI", create=False)


def test_ensure_jira_project_creates_with_lead():
    jira = MagicMock()
    jira.project.side_effect = [Exception("404"), {"id": "10002", "key": "NEW"}]
    out = p.ensure_jira_project(
        jira, MagicMock(), "https://x", "new",
        name="New Thing", create=True, account_id="acct-1",
    )
    payload = jira.create_project_from_raw_json.call_args[0][0]
    assert payload == {
        "key": "NEW", "name": "New Thing",
        "projectTypeKey": "software", "leadAccountId": "acct-1",
    }
    assert out == {"key": "NEW", "created": True, "id": "10002"}


def test_ensure_jira_project_wraps_creation_failure():
    jira = MagicMock()
    jira.project.side_effect = Exception("404")
    jira.create_project_from_raw_json.side_effect = Exception("key taken")
    with pytest.raises(p.JiraError) as exc:
        p.ensure_jira_project(jira, MagicMock(), "https://x", "SI", name="S", create=True)
    assert "key taken" in str(exc.value)


def _issue_type_api(project_types, global_types):
    """Fake api_session whose GETs answer the two endpoints ensure_issue_types uses."""
    api = MagicMock()

    def get(url, params=None):
        resp = MagicMock()
        if url.endswith("/rest/api/3/issuetype"):
            resp.json.return_value = global_types
        elif "/issuetypescheme/project" in url:
            resp.json.return_value = {"values": [{"issueTypeScheme": {"id": "77"}}]}
        else:
            resp.json.return_value = {"id": "10001", "issueTypes": project_types}
        return resp

    api.get.side_effect = get
    api.put.return_value = MagicMock(text="{}", json=lambda: {})
    api.post.return_value = MagicMock(json=lambda: {"id": "999"})
    return api


def test_ensure_issue_types_adds_only_missing():
    api = _issue_type_api(
        project_types=[{"id": "1", "name": "Task"}, {"id": "2", "name": "Bug"}],
        global_types=[
            {"id": "10", "name": "Epic"}, {"id": "11", "name": "Feature"},
            {"id": "12", "name": "Story"}, {"id": "13", "name": "Sub-task"},
        ],
    )
    added = p.ensure_issue_types(api, "https://x", "SI")
    assert added == ["Epic", "Feature", "Story", "Sub-task"]
    sent = api.put.call_args.kwargs["json"]["issueTypeIds"]
    assert sent == ["10", "11", "12", "13"]


def test_ensure_issue_types_noop_when_all_present():
    api = _issue_type_api(
        project_types=[{"id": str(i), "name": n} for i, n in enumerate(
            ["Epic", "Feature", "Story", "Task", "Sub-task", "Bug"])],
        global_types=[],
    )
    assert p.ensure_issue_types(api, "https://x", "SI") == []
    api.put.assert_not_called()


def test_ensure_issue_types_ignores_project_scoped_globals():
    api = _issue_type_api(
        project_types=[],
        global_types=[{"id": "10", "name": "Epic", "scope": {"type": "PROJECT"}}],
    )
    p.ensure_issue_types(api, "https://x", "SI")
    # scoped type is unusable, so a fresh global one is created instead
    assert api.post.called


def test_ensure_issue_types_raises_when_no_scheme():
    api = _issue_type_api(
        project_types=[{"id": "1", "name": "Task"}],
        global_types=[{"id": "10", "name": "Epic"}],
    )

    def get(url, params=None):
        resp = MagicMock()
        if url.endswith("/rest/api/3/issuetype"):
            resp.json.return_value = [{"id": "10", "name": "Epic"}]
        elif "/issuetypescheme/project" in url:
            resp.json.return_value = {"values": []}
        else:
            resp.json.return_value = {"id": "10001", "issueTypes": [{"id": "1", "name": "Task"}]}
        return resp

    api.get.side_effect = get
    with pytest.raises(p.JiraError):
        p.ensure_issue_types(api, "https://x", "SI")


def test_ensure_confluence_space_verifies_existing():
    conf = MagicMock()
    out = p.ensure_confluence_space(conf, "dev", create=False)
    assert out == {"key": "DEV", "created": False}
    conf.get_space.assert_called_once_with("DEV")
    conf.create_space.assert_not_called()


def test_ensure_confluence_space_creates():
    conf = MagicMock()
    conf.get_space.side_effect = Exception("404")
    out = p.ensure_confluence_space(conf, "dev", name="Dev Space", create=True)
    conf.create_space.assert_called_once_with("DEV", "Dev Space")
    assert out == {"key": "DEV", "created": True}


def test_ensure_confluence_space_wraps_creation_failure():
    conf = MagicMock()
    conf.get_space.side_effect = Exception("404")
    conf.create_space.side_effect = Exception("space key in use")
    with pytest.raises(p.ConfluenceError) as exc:
        p.ensure_confluence_space(conf, "dev", name="Dev Space", create=True)
    assert "space key in use" in str(exc.value)


def test_ensure_confluence_space_raises_when_missing_and_not_creating():
    conf = MagicMock()
    conf.get_space.side_effect = Exception("404")
    with pytest.raises(p.ConfluenceError):
        p.ensure_confluence_space(conf, "DEV", create=False)
