import sys
import typer

# Ensure stdout/stderr use UTF-8 on Windows so Rich can render Unicode symbols.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from atlassian_cli.commands import feature, prd, plan, qa, memory

app = typer.Typer(
    name="atlassian",
    help="AI-native Atlassian delivery CLI — operates as a tool for Claude Code.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(feature.app, name="feature")
app.add_typer(prd.app, name="prd")
app.add_typer(plan.app, name="plan")
app.add_typer(qa.app, name="qa")
app.add_typer(memory.app, name="memory")

if __name__ == "__main__":
    app()
