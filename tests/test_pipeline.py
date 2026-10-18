"""Pipeline tests. A scripted backend stands in for Claude, so these never call the API."""

from collections import defaultdict

import pytest

from nrml import schemas
from nrml.personas import PersonaError
from nrml.pipeline import MAX_ROUNDS, Newsroom
from nrml.runlog import RunLog

ITEMS = [
    {"source_id": "S1", "title": "Council passes rent rule", "outlet": "City of Inglewood",
     "url": "https://example.org/s1", "published": "2026-10-17", "text": "...", "source_type": "primary"},
    {"source_id": "S2", "title": "Clinic hours change", "outlet": "LA County DHS",
     "url": "https://example.org/s2", "published": "2026-10-17", "text": "...", "source_type": "primary"},
]


def cluster(cid, source_ids, signals=()):
    return schemas.Cluster(
        cluster_id=cid, is_follow_up=False, title=cid, summary="Summary.", source_ids=source_ids,
        beat="housing", geography="inglewood", core_beat=True, primary_available=True, signals=list(signals),
    )


def assignment(story_id, cluster_id, position=1, policy_angle=False, hold=False):
    return schemas.Assignment(
        story_id=story_id, cluster_id=cluster_id, format="brief", beat="housing", geography="inglewood",
        position=position, angle="What changed?", why_it_matters="Rent.", policy_angle=policy_angle, hold=hold,
    )


def draft(payload):
    return schemas.BeatReporterOutput(
        story_id=payload["story_id"], round=payload["round"], headline=f"Headline r{payload['round']}",
        dek="Dek.", body="Body [S1].", people_mentioned=[], gaps=[], responses=[],
    )


def fact_check(payload, verdict="pass", blocking_on=None):
    claims = []
    if blocking_on:
        claims.append(schemas.Claim(
            location=blocking_on, text="x", cited=["S1"], status="overstated", severity="blocking",
            problem="p", source_says="s", suggested_fix="f",
        ))
    return schemas.FactCheckerOutput(
        story_id=payload["story_id"], round=payload["round"], verdict=verdict,
        summary="Summary.", claims=claims, concerns=[],
    )


def standards(payload, verdict="approve", hold_triggers=(), section="news"):
    objections = []
    if verdict == "revise":
        objections.append(schemas.Objection(
            section=section, quote="finally", rule="Opinion creep", severity="blocking",
            problem="p", suggested_fix="f",
        ))
    return schemas.StandardsEditorOutput(
        story_id=payload["story_id"], round=payload["round"], verdict=verdict, reason="Reason.",
        hold_triggers=list(hold_triggers), objections=objections,
    )


def policy(payload, write_take=False):
    return schemas.PolicyDeskOutput(
        story_id="", mode="take", write_take=write_take, decline_reason="" if write_take else "No policy choice.",
        brief=schemas.PolicyBrief(
            problem="", options=[], evidence_summary="", strongest_counterargument="",
            response_to_counterargument="", common_ground="", story_opening="",
        ),
        gaps=[],
    )


def take(payload):
    return schemas.ColumnistOutput(
        story_id="", mode="take", round=payload["round"], headline="",
        text=f"The take, from Norm: r{payload['round']}", people_mentioned=[], gaps=[], responses=[],
    )


def package(payload):
    return schemas.FormatDeskOutput(
        edition=payload["edition"], date=payload["date"],
        email=schemas.Email(subject="s", preheader="p", html_sections=[]),
        blog_post=schemas.BlogPost(title="t", markdown="m"),
        video_scripts=[], skipped_for_video=[], trims=[],
    )


class ScriptedBackend:
    """Calls a handler per persona and records every payload it was sent."""

    def __init__(self, clusters, assignments, one_thing=None, **handlers):
        self.calls = defaultdict(list)
        self.handlers = {
            "wire_desk": lambda p: schemas.WireDeskOutput(run=p["run"], clusters=clusters, gap_answers=[], discarded=[]),
            "assignment_editor": lambda p: schemas.AssignmentEditorOutput(
                edition=p["edition"], date=p["date"], assignments=assignments,
                one_thing_you_can_do=one_thing or schemas.OneThing(cluster_id="", action=""), skipped=[],
            ),
            "beat_reporter": draft,
            "fact_checker": fact_check,
            "standards_editor": standards,
            "policy_desk": policy,
            "columnist": take,
            "format_desk": package,
            **handlers,
        }

    def call(self, persona, payload):
        self.calls[persona].append(payload)
        return self.handlers[persona](payload)


def run(tmp_path, backend):
    return Newsroom(backend, RunLog(tmp_path)).run_edition("morning", "2026-10-18", ITEMS)


def by_id(result):
    return {s.story_id: s for s in result.stories}


def test_clean_story_is_approved_and_packaged(tmp_path):
    backend = ScriptedBackend([cluster("c1", ["S1"])], [assignment("st1", "c1")])
    result = run(tmp_path, backend)

    story = by_id(result)["st1"]
    assert story.status == "approved"
    assert [s["source_id"] for s in story.sources] == ["S1"]
    assert len(backend.calls["beat_reporter"]) == 1
    assert "policy_desk" not in backend.calls
    sent = backend.calls["format_desk"][0]["stories"]
    assert [s["story_id"] for s in sent] == ["st1"]
    assert sent[0]["sources"] == [{"id": "S1", "title": "Council passes rent rule", "url": "https://example.org/s1"}]
    # reporter draft + fact check + standards
    assert len((tmp_path / "debate" / "st1.jsonl").read_text().splitlines()) == 3


def test_revision_round_sends_objections_and_previous_draft(tmp_path):
    verdicts = iter(["revise", "approve"])
    backend = ScriptedBackend(
        [cluster("c1", ["S1"])], [assignment("st1", "c1")],
        standards_editor=lambda p: standards(p, next(verdicts)),
    )
    result = run(tmp_path, backend)

    assert by_id(result)["st1"].status == "approved"
    revision = backend.calls["beat_reporter"][1]
    assert revision["round"] == 1
    assert revision["previous_draft"]["headline"] == "Headline r0"
    assert revision["objections"]["standards_editor"][0]["rule"] == "Opinion creep"
    assert backend.calls["standards_editor"][1]["prior_rounds"][0]["round"] == 1


def test_unresolved_after_max_rounds_is_held(tmp_path):
    backend = ScriptedBackend(
        [cluster("c1", ["S1"])], [assignment("st1", "c1")],
        fact_checker=lambda p: fact_check(p, "flags", blocking_on="body"),
    )
    result = run(tmp_path, backend)

    story = by_id(result)["st1"]
    assert story.status == "held"
    assert "unresolved" in story.reason
    assert len(backend.calls["fact_checker"]) == MAX_ROUNDS
    assert len(backend.calls["beat_reporter"]) == MAX_ROUNDS  # first draft + two revisions
    assert "format_desk" not in backend.calls


def test_unverifiable_claim_holds_immediately(tmp_path):
    backend = ScriptedBackend(
        [cluster("c1", ["S1"])], [assignment("st1", "c1")],
        fact_checker=lambda p: fact_check(p, "unverifiable"),
    )
    story = by_id(run(tmp_path, backend))["st1"]
    assert story.status == "held"
    assert "fact_checker_unverifiable" in story.hold_triggers


def test_hold_signals_keep_approved_story_out_of_edition(tmp_path):
    backend = ScriptedBackend(
        [cluster("c1", ["S1"], signals=["named_accusation"]), cluster("c2", ["S2"])],
        [assignment("st1", "c1"), assignment("st2", "c2", position=2)],
    )
    result = run(tmp_path, backend)

    stories = by_id(result)
    assert stories["st1"].status == "held"
    assert stories["st1"].hold_triggers == ["named_accusation"]
    assert stories["st2"].status == "approved"
    assert [s["story_id"] for s in backend.calls["format_desk"][0]["stories"]] == ["st2"]
    assert "st1" in (tmp_path / "holds.json").read_text()


def test_standards_hold_trigger_and_assignment_hold(tmp_path):
    backend = ScriptedBackend(
        [cluster("c1", ["S1"]), cluster("c2", ["S2"])],
        [assignment("st1", "c1"), assignment("st2", "c2", position=2, hold=True)],
        standards_editor=lambda p: standards(p, hold_triggers=["active election"] if p["story_id"] == "st1" else []),
    )
    stories = by_id(run(tmp_path, backend))
    assert stories["st1"].status == "held"
    assert stories["st2"].status == "held"
    assert stories["st2"].hold_triggers == ["assignment_editor_hold"]


def test_kill(tmp_path):
    backend = ScriptedBackend(
        [cluster("c1", ["S1"])], [assignment("st1", "c1")],
        standards_editor=lambda p: standards(p, "kill"),
    )
    result = run(tmp_path, backend)
    assert by_id(result)["st1"].status == "killed"
    assert result.package is None


def test_take_debate_revises_and_packages_take(tmp_path):
    take_verdicts = iter(["approve", "revise", "approve"])  # news round 1, then take rounds 1 and 2
    backend = ScriptedBackend(
        [cluster("c1", ["S1"])], [assignment("st1", "c1", policy_angle=True)],
        policy_desk=lambda p: policy(p, write_take=True),
        standards_editor=lambda p: standards(p, next(take_verdicts), section="take"),
    )
    result = run(tmp_path, backend)

    story = by_id(result)["st1"]
    assert story.status == "approved"
    assert story.take.text == "The take, from Norm: r1"
    assert backend.calls["fact_checker"][1]["take_box"] == "The take, from Norm: r0"
    assert backend.calls["columnist"][1]["previous_draft"]["round"] == 0
    assert backend.calls["format_desk"][0]["stories"][0]["take_box"] == "The take, from Norm: r1"


def test_news_flag_during_take_review_goes_to_tim(tmp_path):
    rounds = iter(["pass", "flags"])
    backend = ScriptedBackend(
        [cluster("c1", ["S1"])], [assignment("st1", "c1", policy_angle=True)],
        policy_desk=lambda p: policy(p, write_take=True),
        fact_checker=lambda p: fact_check(p, v := next(rounds), blocking_on="body" if v == "flags" else None),
    )
    story = by_id(run(tmp_path, backend))["st1"]
    assert story.status == "held"
    assert "news section" in story.reason


def test_persona_error_fails_one_story_only(tmp_path):
    def reporter(p):
        if p["story_id"] == "st1":
            raise PersonaError("beat_reporter refused")
        return draft(p)

    backend = ScriptedBackend(
        [cluster("c1", ["S1"]), cluster("c2", ["S2"])],
        [assignment("st1", "c1"), assignment("st2", "c2", position=2)],
        beat_reporter=reporter,
    )
    stories = by_id(run(tmp_path, backend))
    assert stories["st1"].status == "failed"
    assert stories["st2"].status == "approved"


def test_action_item_dropped_when_its_story_does_not_run(tmp_path):
    backend = ScriptedBackend(
        [cluster("c1", ["S1"], signals=["breaking_tragedy"]), cluster("c2", ["S2"])],
        [assignment("st1", "c1"), assignment("st2", "c2", position=2)],
        one_thing=schemas.OneThing(cluster_id="c1", action="Apply by Friday."),
    )
    run(tmp_path, backend)
    assert backend.calls["format_desk"][0]["one_thing_you_can_do"] == ""


@pytest.mark.parametrize("persona", ["wire_desk", "fact_checker", "format_desk"])
def test_system_prompts_load(persona):
    from nrml.personas import system_prompt
    prompt = system_prompt(persona)
    assert "# NRML Newsroom Rules" in prompt
    assert ("# Where we stand" in prompt) == (persona == "format_desk")
