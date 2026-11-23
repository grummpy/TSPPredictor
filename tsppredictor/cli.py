"""Command line: update, build, serve, check, journal."""

from __future__ import annotations

import functools
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import typer

from tsppredictor import NOT_ADVICE, __version__
from tsppredictor.journal import (
    JournalError,
    append_entry,
    export_journal,
    import_interchange,
    new_entry,
    preview_import,
)
from tsppredictor.paths import dist_dir, user_dir

app = typer.Typer(add_completion=False, no_args_is_help=True)
journal_app = typer.Typer(add_completion=False, no_args_is_help=True)
app.add_typer(journal_app, name="journal")
ift_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Personal IFT diary (never submits anything).")
app.add_typer(ift_app, name="ift")
export_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Local exports (Obsidian, Evidence.dev, LocalSend).")
app.add_typer(export_app, name="export")

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
    release_calendar: bool = typer.Option(
        False, "--release-calendar", help="Refresh display-only CPI/jobs dates from the official BLS schedule ICS."
    ),
    ics_file: Path = typer.Option(None, "--ics-file", help="Import a downloaded BLS schedule ICS offline (calendar only)."),
    h15: bool = typer.Option(False, "--h15", help="Pull Treasury yields from the Fed H.15 Data Download Program."),
    alfred: bool = typer.Option(False, "--alfred", help="Pull ALFRED first-print CPI/unemployment (needs FRED_API_KEY)."),
    skip_tsp: bool = typer.Option(False, "--skip-tsp", help="Only run the connector pulls requested above."),
) -> None:
    """Refresh TSP.gov files. Optional extras stay in the gitignored cache."""
    from tsppredictor.data.ingest_macro import fetch_optional
    from tsppredictor.data.ingest_tsp import update_tsp

    if ics_file and (extras or news or h15 or alfred or force):
        raise typer.BadParameter("--ics-file is offline and cannot be combined with other refresh options")
    if not skip_tsp and not ics_file:
        result = update_tsp(force=force)
        typer.echo(json.dumps(result, indent=2))
    if extras:
        fetched = fetch_optional(include_news=news)
        typer.echo(json.dumps(fetched, indent=2))
    if release_calendar or ics_file:
        from tsppredictor.data import release_calendar as rc

        try:
            if ics_file:
                with ics_file.open("rb") as handle:
                    payload = handle.read(rc.MAX_ICS_BYTES + 1)
                if len(payload) > rc.MAX_ICS_BYTES:
                    raise ValueError("Calendar exceeds the supported size")
                text = payload.decode("utf-8")
            else:
                text = rc.fetch_ics()
            typer.echo(json.dumps(rc.cache_schedule(text, source="local-ics" if ics_file else rc.ICS_URL), indent=2))
        except Exception as exc:
            typer.echo(f"Release schedule not updated ({exc}); previous schedule retained; the schedule refresh does not write the model snapshot.", err=True)
            raise typer.Exit(code=1) from exc
    if h15:
        from tsppredictor.connectors import h15 as h15_connector

        try:
            typer.echo(json.dumps(h15_connector.fetch(), indent=2))
        except Exception as exc:
            typer.echo(f"H.15 pull failed ({exc}); the bundled H.15 snapshot stays in use.")
    if alfred:
        from tsppredictor.connectors import alfred as alfred_connector

        if not alfred_connector.enabled():
            typer.echo("ALFRED connector is off: set FRED_API_KEY to enable it.")
        else:
            for series in alfred_connector.SERIES:
                try:
                    frame = alfred_connector.fetch_first_print(series)
                    typer.echo(f"{series}: {len(frame)} first-print rows cached")
                except Exception as exc:
                    typer.echo(f"{series}: ALFRED pull failed ({exc})")


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
    from tsppredictor.paths import snapshot_dir
    from tsppredictor.provenance import write_provenance_badge

    if (dist_dir() / "data" / "build-manifest.json").exists():
        badge = write_provenance_badge(dist_dir(), snapshot_dir())
        typer.echo("Build verified." if badge["verified"] else f"Build NOT verified: {badge['problems'][:3]}")
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
    from tsppredictor.data.release_calendar import upcoming_display

    rows, _schedule = upcoming_display(days=7)
    for item in rows:
        label = "CPI" if item.series == "bls_cpi" else "Jobs report"
        typer.echo(f"Release day: {label} for {item.reference_month} on {item.release_date.isoformat()} (display only; {item.source}).")


@app.command()
def verify(
    dist: Path = typer.Option(None, "--dist", help="Built folder to verify (default dist/)."),
) -> None:
    """Recheck every SHA-256 in dist/data/build-manifest.json."""
    from tsppredictor.paths import snapshot_dir
    from tsppredictor.provenance import verify_build_manifest

    result = verify_build_manifest(dist or dist_dir(), snapshot_dir())
    typer.echo(json.dumps(result, indent=2))
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command()
def reproduce(
    reference: Path = typer.Option(None, "--reference", help="Old dist/ to reproduce (default dist/)."),
    work_dir: Path = typer.Option(Path("data/cache/reproduce"), "--work-dir", help="Where the rebuild goes."),
) -> None:
    """Rebuild from the current snapshot and confirm the outputs match a reference build."""
    from tsppredictor.provenance import reproduce as run_reproduce

    reference = Path(reference or dist_dir()).resolve()
    work_dir = work_dir.resolve()
    if work_dir == reference:
        typer.echo("The work dir must differ from the reference build.")
        raise typer.Exit(code=2)
    result = run_reproduce(reference, work_dir)
    typer.echo(json.dumps(result, indent=2))
    if not result["reproduced"]:
        raise typer.Exit(code=1)


@app.command("vintage-replay")
def vintage_replay() -> None:
    """Vintage Replay Lab: compare monthly rules on revised vs first-print macro data."""
    from tsppredictor.vintage_replay import replay

    typer.echo(json.dumps(replay(), indent=2))


@app.command("releases")
def releases(days: int = typer.Option(30, help="Days ahead to list.")) -> None:
    """Upcoming CPI/jobs releases, with an optional display-only schedule."""
    from tsppredictor.data.release_calendar import coverage, upcoming_display

    releases, schedule = upcoming_display(days=days)
    rows = [{"series": r.series, "month": r.reference_month, "date": r.release_date.isoformat(), "source": r.source}
            for r in releases]
    typer.echo(json.dumps({"upcoming": rows, "coverage": coverage(), "schedule": schedule}, indent=2))


@journal_app.command("add")
def journal_add(
    date: str = typer.Option(..., help="Decision date YYYY-MM-DD."),
    fund: str = typer.Option(..., help="Fund the user chose: G, F, C, S, or I."),
    reason: str = typer.Option("", help="Why the user made the choice."),
    confidence: float = typer.Option(0.0, help="User's own confidence from 0 to 1."),
    tags: str = typer.Option("", help="Comma-separated free tags, e.g. ift-limit,news."),
) -> None:
    """Append a decision to data/user/journal.jsonl. That directory is gitignored."""
    try:
        row = new_entry(decision_date=date, fund=fund, reason=reason, confidence=confidence,
                        tags=[t for t in tags.split(",") if t.strip()])
    except JournalError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)
    path = user_dir() / "journal.jsonl"
    append_entry(path, row)
    typer.echo(f"Appended to {path}")


@journal_app.command("export")
def journal_export(
    path: Path = typer.Option(..., "--path", help="Destination JSON interchange file."),
) -> None:
    """Export disk notes to the portable browser/CLI interchange format."""
    try:
        result = export_journal(user_dir() / "journal.jsonl", path)
    except JournalError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)
    typer.echo(json.dumps(result, indent=2))


@journal_app.command("preview")
def journal_preview(
    path: Path = typer.Option(..., "--path", help="Source JSON interchange file."),
) -> None:
    """Preview additions, duplicates, and conflicts without changing the disk journal."""
    try:
        result = preview_import(user_dir() / "journal.jsonl", path)
    except JournalError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)
    typer.echo(json.dumps(result, indent=2))


@journal_app.command("import")
def journal_import(
    path: Path = typer.Option(..., "--path", help="Source JSON interchange file."),
    on_conflict: str = typer.Option(
        "keep-local",
        "--on-conflict",
        help="keep-local imports only new notes; prefer-incoming replaces conflicting local notes "
        "(after a backup); error leaves the journal unchanged if conflicts exist.",
    ),
) -> None:
    """Append previewed notes and retain a timestamped local backup before changes."""
    try:
        result = import_interchange(user_dir() / "journal.jsonl", path, on_conflict=on_conflict)
    except JournalError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)
    typer.echo(json.dumps(result, indent=2))


def _prices():
    from tsppredictor.data.snapshot import core_prices, load_snapshot

    return core_prices(load_snapshot())


def _entries():
    from tsppredictor.journal import read_journal

    try:
        return read_journal(user_dir() / "journal.jsonl")
    except JournalError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)


@journal_app.command("diff")
def journal_diff_cmd(
    other: Path = typer.Option(..., "--path", help="Interchange file to compare with the disk journal."),
) -> None:
    """Entries only on disk, only in the file, and same-id conflicts."""
    from tsppredictor.journal import journal_diff, read_interchange

    try:
        typer.echo(json.dumps(journal_diff(_entries(), read_interchange(other)), indent=2))
    except JournalError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)


@journal_app.command("stats")
def journal_stats(path: Path = typer.Option(..., "--path", help="Interchange file.")) -> None:
    """Count, date range and funds in an interchange file."""
    from tsppredictor.journal import interchange_stats

    try:
        typer.echo(json.dumps(interchange_stats(path), indent=2))
    except JournalError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)


@journal_app.command("list")
def journal_list(tag: str = typer.Option("", help="Only entries with this tag.")) -> None:
    """List disk entries with their 21/63-session outcomes."""
    from tsppredictor.journal import filter_by_tag
    from tsppredictor.journal_insights import with_outcomes

    entries = _entries()
    if tag:
        entries = filter_by_tag(entries, tag)
    typer.echo(json.dumps(with_outcomes(entries, _prices()), indent=2))
    typer.echo(NOT_ADVICE)


@journal_app.command("review")
def journal_review(month: str = typer.Option(..., help="Month YYYY-MM.")) -> None:
    """Decision Journal Reviewer: a month's entries and how they turned out."""
    from tsppredictor.journal_insights import monthly_review

    typer.echo(monthly_review(_entries(), _prices(), month)["markdown"])


@journal_app.command("calibration")
def journal_calibration(
    html: Path = typer.Option(None, "--html", help="Also write the one-page Calibration Card here."),
) -> None:
    """Hit rate grouped by the confidence you gave."""
    from tsppredictor.journal_insights import calibration_card_html, confidence_calibration

    result = confidence_calibration(_entries(), _prices())
    typer.echo(json.dumps(result, indent=2))
    if html:
        html.write_text(calibration_card_html(result), encoding="utf-8")
        typer.echo(f"Wrote {html}")


@journal_app.command("sync")
def journal_sync(
    folder: Path = typer.Option(..., "--folder", help="A folder you picked (USB, NAS, synced folder)."),
    on_conflict: str = typer.Option("keep-local", "--on-conflict"),
) -> None:
    """Journal File Sync: import the shared file from the folder, then export back to it."""
    from tsppredictor.journal import sync_folder

    try:
        typer.echo(json.dumps(sync_folder(user_dir() / "journal.jsonl", folder, on_conflict=on_conflict), indent=2))
    except JournalError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)


@ift_app.command("log")
def ift_log(
    date: str = typer.Option(..., help="Actual posting date YYYY-MM-DD (not request date)."),
    from_mix: str = typer.Option(..., "--from", help="Mix before, e.g. '100 C'."),
    to_mix: str = typer.Option(..., "--to", help="Mix after, e.g. '100 G'."),
    reason: str = typer.Option("", help="Why."),
    g_only: bool = typer.Option(False, "--g-only", help="User-confirmed move only into G. Still counts if one of the first two that month."),
) -> None:
    """Log one interfund transfer with your reason (diary only)."""
    from datetime import date as _date

    from tsppredictor.journal_insights import record_ift

    try:
        row = record_ift(user_dir(), when=_date.fromisoformat(date), from_mix=from_mix, to_mix=to_mix,
                         reason=reason, g_only=g_only)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)
    typer.echo(json.dumps(row, indent=2))


@ift_app.command("summary")
def ift_summary(month: str = typer.Option(..., help="Month YYYY-MM.")) -> None:
    """Transfers logged for a month and how many unrestricted ones remain."""
    from tsppredictor.journal_insights import ift_month_summary

    typer.echo(json.dumps(ift_month_summary(user_dir(), month), indent=2))


@export_app.command("obsidian")
def export_obsidian_cmd(vault: Path = typer.Option(..., "--vault", help="Your Obsidian vault folder.")) -> None:
    """Write journal entries as Markdown notes into a vault you choose."""
    from tsppredictor.connectors.exports import export_obsidian
    from tsppredictor.journal_insights import with_outcomes

    typer.echo(json.dumps(export_obsidian(with_outcomes(_entries(), _prices()), vault), indent=2))


@export_app.command("evidence")
def export_evidence_cmd(output: Path = typer.Option(..., "--output", help="Folder for the Evidence.dev project.")) -> None:
    """Write an Evidence.dev project over the built scoreboard."""
    from tsppredictor.connectors.exports import export_evidence_project

    path = dist_dir() / "data" / "scoreboard.json"
    if not path.exists():
        typer.echo("No dist/data/scoreboard.json. Run tsp build first.")
        raise typer.Exit(code=1)
    rows = json.loads(path.read_text())["rows"]
    typer.echo(json.dumps(export_evidence_project(rows, output), indent=2))


@export_app.command("localsend")
def export_localsend(
    host: str = typer.Option(..., "--host", help="Your other device's LAN address (private ranges only)."),
    port: int = typer.Option(53317, "--port"),
    https: bool = typer.Option(False, "--https", help="Use HTTPS (LocalSend's default encrypted mode)."),
) -> None:
    """Send the journal interchange file to your own device running LocalSend."""
    import tempfile

    from tsppredictor.connectors.localsend import send_file

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tsp-journal.json"
        try:
            export_journal(user_dir() / "journal.jsonl", path)
            typer.echo(json.dumps(send_file(path, host, port=port, https=https), indent=2))
        except (JournalError, ValueError) as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1)
