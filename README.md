# NRML

A news-first AI newsroom for everyday people.

## Agent prompts

Each newsroom role is a persona prompt in `personas/`. A story moves through them in this order:

1. `wire_desk.md`: clusters and labels the raw wire
2. `assignment_editor.md`: picks what the edition covers
3. `beat_reporter.md`: writes the news section
4. `fact_checker.md`: checks every claim against its source
5. `standards_editor.md`: checks tone, framing, and fairness
6. `policy_desk.md`: researches progressive options when there's a policy angle
7. `columnist.md`: Norm, who writes the take box
8. `format_desk.md`: packages approved stories for email, blog, and video

Every persona expects `charter/rules.md` (and most expect `charter/where_we_stand.md`) to be appended below it.

## Running the pipeline

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
export ANTHROPIC_API_KEY=...
.venv/bin/python -m nrml run --edition morning --date 2026-10-18 --input run.json
```

`run.json` holds the fetched wire items and optional context:

```json
{
  "items": [
    {"source_id": "S1", "title": "...", "outlet": "...", "url": "...",
     "published": "2026-10-17", "text": "cached text", "source_type": "primary"}
  ],
  "recent_clusters": [], "recent_editions": [], "open_series": [],
  "corrections": [], "gap_requests": []
}
```

Everything lands in `runs/<date>-<edition>/`: each persona's output, one file per story, `holds.json` for Tim, the full debate log in `debate/<story_id>.jsonl`, and `email.md` / `blog.md` from the Format Desk.

Tests use a scripted stand-in for Claude, so they don't call the API: `.venv/bin/python -m pytest`

Settings: `NRML_MODEL` (default `claude-opus-5-5`) and `NRML_EFFORT` (default `high`).

### How the pipeline handles the parts the prompts leave open

- **Debate rounds.** Each story gets up to 3 review rounds. In a round the Fact Checker checks the latest draft, then the Standards Editor reviews it with the fact check in hand. If anything is still blocking, the author revises and the next round starts. If it's still blocking after round 3, the story goes to Tim. That means an author revises at most twice.
- **Revisions see their own draft.** The Beat Reporter and Columnist get a `previous_draft` field on revision rounds so they know what they're fixing.
- **The take gets its own debate.** After the news section is approved, the Policy Desk decides whether there's a take. If there is, Norm's take goes through the same Fact Checker and Standards Editor loop. If a reviewer flags the already approved news section during that loop, the story goes to Tim, since Norm can't fix the news.
- **Holds.** A story is held for Tim if the Assignment Editor set `hold`, the Wire Desk flagged `breaking_tragedy` or `named_accusation`, the Standards Editor listed any hold trigger or escalated, or the Fact Checker returned `unverifiable`. Held stories still finish the debate so Tim gets a complete draft, but they never reach the Format Desk.
- **"One thing you can do"** only runs if the story it came from made the edition.

### Not built yet

- RSS and API fetching (the input file stands in for it)
- Sending Beat Reporter `gaps` back to the Wire Desk
- Tim's review step for held stories
- Proof of Concept series mode
- Sending the email and posting to Substack
