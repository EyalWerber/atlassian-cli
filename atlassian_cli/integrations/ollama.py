import json
import requests
from atlassian_cli.config import Settings
from atlassian_cli.models.prd import PRD


_SCHEMA = """{
  "epics": [
    {
      "title": "<version name, e.g. v1.0 - Feature Name>",
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
}"""

_SYSTEM_PROMPT = f"""You are a software planning agent. Given a Product Requirements Document (PRD), \
decompose it into a structured implementation plan.

Return ONLY valid JSON matching this schema exactly:
{_SCHEMA}

Rules:
- Each Epic represents a version or release milestone
- Each Story represents a feature within that version
- Each Task is a concrete implementation unit
- Every Story must have at least one Task
- Every Epic must have at least one Story
- Do not include jira_key fields"""

_QA_SCENARIO_SCHEMA = """{
  "scenarios": [
    {
      "title": "<short scenario name>",
      "steps": [
        "<action step, e.g. Navigate to /login>",
        "<action step, e.g. Enter 'test@example.com' in the email field>"
      ],
      "expected_result": "<what should happen if the scenario passes>"
    }
  ]
}"""

_QA_SYSTEM_PROMPT = f"""You are a QA planning agent. Given a Product Requirements Document (PRD), \
generate comprehensive test scenarios.

Return ONLY valid JSON matching this schema exactly:
{_QA_SCENARIO_SCHEMA}

Rules:
- Cover happy path, edge cases, and error states
- Steps must be human-readable browser actions (what to click, navigate, enter)
- Each step should be one clear action
- expected_result describes what a passing test looks like
- Do not include code, selectors, or technical implementation details in steps"""


class OllamaClient:
    def __init__(self, settings: Settings):
        self.host = settings.ollama_host
        self.model = settings.ollama_model
        self.embed_model = settings.ollama_embed_model

    def decompose_prd(self, prd: PRD) -> dict:
        user_content = "\n\n".join([
            f"PRD Title: {prd.title}",
            f"Executive Summary: {prd.summary}",
            f"Problem Statement: {prd.problem}",
            f"User Personas: {prd.personas}",
            f"User Stories: {prd.stories}",
            f"Business Value: {prd.business_value}",
            f"Functional Requirements: {prd.requirements}",
            f"Non-Functional Requirements: {prd.nfr}",
            f"Technical Considerations: {prd.considerations}",
            f"Risks: {prd.risks}",
            f"Success Metrics: {prd.metrics}",
            f"Out of Scope: {prd.out_of_scope}",
            f"Future Enhancements: {prd.future_enhancements}",
        ])

        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "format": "json",
                    "stream": False,
                },
                timeout=120,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"Ollama not available at {self.host}. Is it running?")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama request failed: {e}")

        try:
            content = response.json()["message"]["content"]
            return json.loads(content)
        except (KeyError, ValueError) as e:
            raise RuntimeError(f"Ollama returned unexpected response format: {e}")

    def generate_qa_scenarios(self, prd: PRD) -> dict:
        user_content = "\n\n".join([
            f"PRD Title: {prd.title}",
            f"Executive Summary: {prd.summary}",
            f"Problem Statement: {prd.problem}",
            f"User Personas: {prd.personas}",
            f"User Stories: {prd.stories}",
            f"Business Value: {prd.business_value}",
            f"Functional Requirements: {prd.requirements}",
            f"Non-Functional Requirements: {prd.nfr}",
            f"Technical Considerations: {prd.considerations}",
            f"Risks: {prd.risks}",
            f"Success Metrics: {prd.metrics}",
            f"Out of Scope: {prd.out_of_scope}",
            f"Future Enhancements: {prd.future_enhancements}",
        ])

        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": _QA_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "format": "json",
                    "stream": False,
                },
                timeout=120,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"Ollama not available at {self.host}. Is it running?")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama request failed: {e}")

        try:
            content = response.json()["message"]["content"]
            return json.loads(content)
        except (KeyError, ValueError) as e:
            raise RuntimeError(f"Ollama returned unexpected response format: {e}")

    def embed(self, text: str) -> list[float]:
        try:
            response = requests.post(
                f"{self.host}/api/embeddings",
                json={"model": self.embed_model, "prompt": text},
                timeout=30,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"Ollama not available at {self.host}. Is it running?")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama request failed: {e}")
        try:
            return response.json()["embedding"]
        except (KeyError, ValueError) as e:
            raise RuntimeError(f"Ollama returned unexpected response format: {e}")

    def ping(self) -> bool:
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=3)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
