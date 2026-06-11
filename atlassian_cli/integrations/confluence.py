from atlassian import Confluence
from atlassian_cli.config import Settings
from atlassian_cli.models.prd import PRD


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
            safe = (
                content
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br/>")
            )
            parts.append(f"<h2>{heading}</h2><p>{safe}</p>")
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
