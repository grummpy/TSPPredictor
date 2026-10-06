"""Command line: update, build, serve, check, journal."""

from __future__ import annotations

import functools
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import typer

from tsppredictor import NOT_ADVICE, __version__
from tsppredictor.paths import dist_dir, user_dir

app = typer.Typer(add_completion=False, no_args_is_help=True)
journal_app = typer.Typer(add_completion=False, no_args_is_help=True)
app.add_typer(journal_app, name="journal")

BIND_HOST = "127.0.0.1"


def make_server(port: int) -> ThreadingHTTPServer:
    """HTTP server bound to the loopback interface only."""
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(dist_dir()))
    return ThreadingHTTPServer((BIND_HOST, port), handler)


@app.callback()
def main() -> None:
    """Educational TSP decision support. Not financial advice."""


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command()
def update(
    force: bool = typer.Option(False, "--force", help="Refresh even if a refresh already succeeded today."),
    extras: bool = typer.Option(False, "--extras", help="Also fetch Tier B/C files into data/cache/."),
    news: bool = typer.Option(False, "--news", help="With --extras, also fetch the optional GDELT tone file."),
) -> None:
    """Refresh TSP.gov files. Optional extras stay in the gitignored cache."""
    from tsppredictor.data.ingest_macro import fetch_optional
    from tsppredictor.data.ingest_tsp import update_tsp

    result = update_tsp(force=force)
    typer.echo(json.dumps(result, indent=2))
    if extras:
        fetched = fetch_optional(include_news=news)
        typer.echo(json.dumps(fetched, indent=2))


@app.command()
def build() -> None:
    """Run the walk-forward models and write dist/."""
    from tsppredictor.build import run_build

    result = run_build()
    today = result["today"]
    typer.echo(f"data_as_of {result['meta']['data_as_of']} signal {today['fund']} stance {today['stance']}")
    typer.echo(NOT_ADVICE)


@app.command()
def serve(port: int = typer.Option(8765, help="Loopback port.")) -> None:
    """Serve dist/ on 127.0.0.1 only."""
    httpd = make_server(port)
    typer.echo(f"Serving dist on {BIND_HOST} port {port}. Local only. Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


@app.command()
def check() -> None:
    """Compare today's signal with the last check and write dist/data/alert.json."""
    today_path = dist_dir() / "data" / "today.json"
    if not today_path.exists():
        typer.echo("No dist/data/today.json. Run tsp build first.")
        raise typer.Exit(code=1)
    today = json.loads(today_path.read_text())
    last_path = user_dir() / "last_signal.json"
    previous = json.loads(last_path.read_text()) if last_path.exists() else None
    flipped = previous is not None and previous.get("fund") != today.get("fund")
    if previous is None:
        message = f"First check. Signal is {today.get('fund')} ({today.get('stance')}) as of {today.get('signal_date')}."
    elif flipped:
        message = (
            f"Signal changed from {previous.get('fund')} to {today.get('fund')} "
            f"({today.get('stance')}) as of {today.get('signal_date')}."
        )
    else:
        message = f"Signal is still {today.get('fund')} ({today.get('stance')}) as of {today.get('signal_date')}."
    alert = {
        "schema_version": 1,
        "data_as_of": today.get("data_as_of"),
        "flipped": flipped,
        "message": message,
        "fund": today.get("fund"),
        "previous_fund": None if previous is None else previous.get("fund"),
    }
    alert_path = dist_dir() / "data" / "alert.json"
    alert_path.parent.mkdir(parents=True, exist_ok=True)
    alert_path.write_text(json.dumps(alert, indent=2))
    last_path.write_text(json.dumps({"fund": today.get("fund"), "signal_date": today.get("signal_date")}, indent=2))
    typer.echo(message)


@journal_app.command("add")
def journal_add(
    date: str = typer.Option(..., help="Decision date YYYY-MM-DD."),
    fund: str = typer.Option(..., help="Fund the user chose: G, F, C, S, or I."),
    reason: str = typer.Option("", help="Why the user made the choice."),
    confidence: float = typer.Option(0.0, help="User's own confidence from 0 to 1."),
) -> None:
    """Append a decision to data/user/journal.jsonl. That directory is gitignored."""
    fund = fund.upper()
    if fund not in {"G", "F", "C", "S", "I"}:
        typer.echo("fund must be G, F, C, S, or I")
        raise typer.Exit(code=1)
    row = {"date": date, "fund": fund, "reason": reason, "confidence": confidence}
    path = user_dir() / "journal.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    typer.echo(f"Appended to {path}")
