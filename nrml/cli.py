"""Command line entry point: python -m nrml run --edition morning --input run.json"""

import argparse
import json
from datetime import date
from pathlib import Path

from nrml.personas import ClaudeBackend
from nrml.pipeline import Newsroom
from nrml.runlog import RunLog


def render_email(package) -> str:
    sections = [s.markdown for s in package.email.html_sections]
    header = f"Subject: {package.email.subject}\nPreheader: {package.email.preheader}\n"
    return header + "\n\n" + "\n\n---\n\n".join(sections) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="nrml")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run one edition through the newsroom")
    run.add_argument("--edition", choices=["morning", "evening"], required=True)
    run.add_argument("--date", default=date.today().isoformat())
    run.add_argument("--input", type=Path, required=True,
                     help="JSON file with items and optional recent_clusters, recent_editions, "
                          "open_series, corrections, gap_requests")
    run.add_argument("--out", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)

    inputs = json.loads(args.input.read_text())
    log = RunLog(args.out / f"{args.date}-{args.edition}")
    result = Newsroom(ClaudeBackend(), log).run_edition(
        edition=args.edition,
        date=args.date,
        items=inputs["items"],
        recent_clusters=inputs.get("recent_clusters"),
        recent_editions=inputs.get("recent_editions"),
        open_series=inputs.get("open_series"),
        corrections=inputs.get("corrections"),
        gap_requests=inputs.get("gap_requests"),
    )

    if result.package:
        (log.dir / "email.md").write_text(render_email(result.package))
        (log.dir / "blog.md").write_text(result.package.blog_post.markdown + "\n")

    for story in result.stories:
        line = f"{story.story_id}: {story.status}"
        print(line + (f" ({story.reason})" if story.reason else ""))
    print(f"Run written to {log.dir}")
    return 0
