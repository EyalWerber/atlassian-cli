from pathlib import Path
from typing import Optional

from pydantic import ValidationError, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
import typer
from rich.console import Console
from rich.table import Table

_GLOBAL_ENV = Path.home() / ".atlassian-cli" / ".env"


def _make_settings_class(env_dir: Path | None = None) -> type:
    env_files: list[str] = [str(_GLOBAL_ENV)]
    if env_dir is not None:
        env_files.append(str(env_dir / ".env"))
    else:
        env_files.append(".env")

    class _Settings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=env_files,
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )

        atlassian_url: str
        atlassian_email: str
        atlassian_api_token: SecretStr
        jira_project: str
        confluence_space: str

        ollama_host: str = "http://localhost:11434"
        ollama_model: str = "llama3.2"
        memory_db_path: str = "memory/atlassian.db"
        memory_vector_path: str = "memory/vectors/"
        ollama_embed_model: str = "nomic-embed-text"
        qa_base_url: str = ""
        memory_backend: str  # required — must be "local" or "turso" in .env
        turso_url: Optional[str] = None
        turso_auth_token: Optional[str] = None

    return _Settings


class Settings(_make_settings_class()):  # type: ignore[misc]
    pass

    atlassian_url: str
    atlassian_email: str
    atlassian_api_token: SecretStr
    jira_project: str
    confluence_space: str

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    memory_db_path: str = "~/.atlassian-cli/memory.db"
    memory_vector_path: str = "~/.atlassian-cli/vectors/"
    ollama_embed_model: str = "nomic-embed-text"
    qa_base_url: str = ""
    memory_backend: str  # required — must be "local" or "turso" in .env
    turso_url: Optional[str] = None
    turso_auth_token: Optional[str] = None


def get_settings(env_dir: Path | None = None) -> Settings:
    SettingsClass = _make_settings_class(env_dir)
    try:
        return SettingsClass()
    except ValidationError as e:
        console = Console(force_terminal=True, legacy_windows=False)
        table = Table(title="[red]X Missing required configuration[/red]", show_header=True)
        table.add_column("Variable", style="yellow")
        table.add_column("Status", style="red")

        for err in e.errors():
            if err["type"] == "missing":
                var_name = str(err["loc"][0]).upper()
                table.add_row(var_name, "not set")

        console.print(table)
        console.print("\nRun: [bold]atlassian project init[/bold] to create your .env file.")
        raise typer.Exit(1)
