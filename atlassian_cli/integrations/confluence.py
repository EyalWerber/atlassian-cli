from atlassian import Confluence
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from atlassian_cli.config import Settings
from atlassian_cli.models.prd import PRD

if TYPE_CHECKING:
    from atlassian_cli.models.qa import QAPlan
    from atlassian_cli.models.feature import Feature


_STATUS_MESSAGES = {
    401: "Invalid credentials. Check ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN.",
    403: "Permission denied. Check your account has access to this Confluence space.",
    404: "Resource not found. Check CONFLUENCE_SPACE value.",
}


def _friendly_error(e: Exception) -> str:
    resp = getattr(e, "response", None)
    if resp is not None:
        status = getattr(resp, "status_code", None)
        if status in _STATUS_MESSAGES:
            return _STATUS_MESSAGES[status]
    return str(e)


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
    )


def _section_anchor(name: str) -> str:
    """Convert PRD section name to Confluence heading anchor.
    e.g. 'Functional Requirements' -> 'Functional-Requirements'
         'Non-Functional Requirements' -> 'Non-Functional-Requirements'
    """
    return "-".join(
        word[0].upper() + word[1:] if word else ""
        for word in name.split()
    )


def prd_to_storage_format(prd: PRD) -> str:
    """Convert a PRD to Confluence Storage Format (XHTML)."""
    sections = [
        ("Executive Summary", prd.summary),
        ("Problem Statement", prd.problem),
        ("User Personas", prd.personas),
        ("User Stories", prd.stories),
        ("Business Value", prd.business_value),
        ("Functional Requirements", prd.requirements),
        ("Non-Functional Requirements", prd.nfr),
        ("Technical Considerations", prd.considerations),
        ("Risks", prd.risks),
        ("Success Metrics", prd.metrics),
        ("Out of Scope", prd.out_of_scope),
    ]
    if prd.future_enhancements:
        sections.append(("Future Enhancements", prd.future_enhancements))

    parts = []
    for heading, content in sections:
        if content:
            parts.append(f"<h2>{heading}</h2><p>{_esc(content)}</p>")
    return "\n".join(parts)


def stp_to_storage_format(
    plan: "QAPlan",
    feature: "Feature",
    prd: PRD,
    atlassian_url: str,
    jira_project: str,
) -> str:
    """Convert a QAPlan to Confluence Storage Format (XHTML) for a Software Test Plan."""
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if feature.jira_key:
        feature_link = (
            f'<a href="{atlassian_url}/browse/{feature.jira_key}">'
            f'{feature.jira_key} – {_esc(feature.name)}</a>'
        )
    else:
        feature_link = _esc(feature.name)

    if prd.confluence_url:
        prd_link = f'<a href="{prd.confluence_url}">{_esc(prd.title)}</a>'
    else:
        prd_link = _esc(prd.title)

    parts = [
        '<ac:structured-macro ac:name="info" ac:schema-version="1">',
        '  <ac:rich-text-body>',
        f'    <p><strong>Feature:</strong> {feature_link}</p>',
        f'    <p><strong>PRD:</strong> {prd_link}</p>',
        f'    <p><strong>Date:</strong> {date}</p>',
        f'    <p><strong>Status:</strong> {plan.status.value.title()}</p>',
        '  </ac:rich-text-body>',
        '</ac:structured-macro>',
        '',
        '<h2>1. Introduction</h2>',
        f'<p>{_esc(feature.description)}</p>',
        '',
        '<h2>2. Test Objectives</h2>',
        '<p>Verify that all requirements defined in the PRD are met: functional correctness, '
        'non-functional constraints, and user story acceptance criteria.</p>',
        '',
        '<h2>3. Scope</h2>',
        '<h3>In Scope</h3>',
        f'<p>{_esc(prd.requirements)}</p>',
        '<h3>Out of Scope</h3>',
        f'<p>{_esc(prd.out_of_scope)}</p>',
        '',
        '<h2>4. Test Strategy</h2>',
        '<p>End-to-end scenarios exercising the feature from a user perspective. '
        'Bugs are filed in Jira against the feature. Regression is re-run on each fix.</p>',
        '',
        '<h2>5. Entry / Exit Criteria</h2>',
        '<h3>Entry Criteria</h3>',
        '<ul>',
        '  <li>Feature deployed to test environment</li>',
        '  <li>PRD accepted</li>',
        '  <li>QA plan generated</li>',
        '</ul>',
        '<h3>Exit Criteria</h3>',
        '<ul>',
        '  <li>All test cases executed</li>',
        '  <li>No open critical or blocker bugs</li>',
        f'  <li>Success metrics met: {_esc(prd.metrics)}</li>',
        '</ul>',
        '',
        '<h2>6. Test Cases</h2>',
        '<table>',
        '  <thead>',
        '    <tr>',
        '      <th>#</th><th>Test Case</th><th>PRD Section</th>',
        '      <th>Steps</th><th>Expected Result</th><th>Status</th><th>Bug</th>',
        '    </tr>',
        '  </thead>',
        '  <tbody>',
    ]

    for i, scenario in enumerate(plan.scenarios, 1):
        steps_html = (
            "<ol>" +
            "".join(f"<li>{_esc(s)}</li>" for s in scenario.steps) +
            "</ol>"
        )
        if scenario.prd_section and prd.confluence_url:
            anchor = _section_anchor(scenario.prd_section)
            prd_section_html = (
                f'<a href="{prd.confluence_url}#{anchor}">'
                f'{_esc(scenario.prd_section)}</a>'
            )
        else:
            prd_section_html = _esc(scenario.prd_section) if scenario.prd_section else "—"

        bug_html = _esc(scenario.bug_key) if scenario.bug_key else "—"
        parts.append(
            f'    <tr>'
            f'<td>{i}</td>'
            f'<td>{_esc(scenario.title)}</td>'
            f'<td>{prd_section_html}</td>'
            f'<td>{steps_html}</td>'
            f'<td>{_esc(scenario.expected_result)}</td>'
            f'<td>—</td>'
            f'<td>{bug_html}</td>'
            f'</tr>'
        )

    parts += [
        '  </tbody>',
        '</table>',
        '',
        '<h2>7. Defect Management</h2>',
        f'<p>Bugs are filed in Jira project '
        f'<a href="{atlassian_url}/jira/software/projects/{jira_project}">{jira_project}</a> '
        f'using <code>atlassian qa bug {plan.id} --scenario "..." ...</code>. '
        f'Severity: Critical (feature unusable), Major (significant impact), '
        f'Minor (workaround exists).</p>',
        '',
        '<h2>8. Risks</h2>',
        f'<p>{_esc(prd.risks)}</p>',
    ]

    return "\n".join(parts)


class ConfluenceClient:
    def __init__(self, settings: Settings):
        self._conf = Confluence(
            url=settings.atlassian_url,
            username=settings.atlassian_email,
            password=settings.atlassian_api_token.get_secret_value(),
            cloud=True,
        )
        self.space = settings.confluence_space

    def create_page(self, title: str, body: str) -> tuple[str, str]:
        """Create a page. Returns (page_id, page_url)."""
        try:
            page = self._conf.create_page(
                space=self.space,
                title=title,
                body=body,
                representation="storage",
            )
            page_id = str(page["id"])
            url = page["_links"]["base"] + page["_links"]["webui"]
            return page_id, url
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def update_page(self, page_id: str, title: str, body: str) -> None:
        try:
            self._conf.update_page(
                page_id=page_id,
                title=title,
                body=body,
                representation="storage",
            )
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def get_page_by_title(self, title: str) -> dict | None:
        try:
            return self._conf.get_page_by_title(space=self.space, title=title)
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e

    def add_label(self, page_id: str, label: str) -> None:
        try:
            self._conf.set_page_label(page_id, label)
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e
