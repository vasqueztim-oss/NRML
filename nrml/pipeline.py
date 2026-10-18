"""The newsroom: runs an edition from raw wire items to packaged output.

Flow for one edition:

    Wire Desk -> Assignment Editor -> (per story, in parallel)
        news debate:  Beat Reporter <-> Fact Checker + Standards Editor
        take debate:  Policy Desk -> Columnist <-> Fact Checker + Standards Editor
    -> Format Desk (approved stories only)

A debate runs up to MAX_ROUNDS review rounds. Review round N looks at the
author's latest draft; if anything is still blocking, the author revises with
round number N and the next review round starts. Blocking objections still
open at round MAX_ROUNDS are escalated to Tim, per the charter.

Stories that hit an auto-hold trigger still go through the full debate, so Tim
gets a finished draft to review, but they never reach the Format Desk.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from nrml import schemas
from nrml.personas import Backend, PersonaError
from nrml.runlog import RunLog, to_jsonable

MAX_ROUNDS = 3
MAX_PARALLEL_STORIES = 4

# Wire Desk signals that always mean Tim has to sign off.
HOLD_SIGNALS = {"breaking_tragedy", "named_accusation"}


@dataclass
class StoryResult:
    assignment: schemas.Assignment
    status: str = "approved"  # approved | held | killed | failed
    reason: str = ""
    hold_triggers: list[str] = field(default_factory=list)
    news: schemas.BeatReporterOutput | None = None
    take: schemas.ColumnistOutput | None = None
    sources: list[dict] = field(default_factory=list)

    @property
    def story_id(self) -> str:
        return self.assignment.story_id

    def stop(self, status: str, reason: str) -> "StoryResult":
        self.status, self.reason = status, reason
        return self


@dataclass
class EditionResult:
    edition: str
    date: str
    wire: schemas.WireDeskOutput
    assignments: schemas.AssignmentEditorOutput
    stories: list[StoryResult]
    package: schemas.FormatDeskOutput | None


def news_section(news: schemas.BeatReporterOutput) -> dict:
    return {"headline": news.headline, "dek": news.dek, "body": news.body}


class Newsroom:
    def __init__(self, backend: Backend, log: RunLog):
        self.backend = backend
        self.log = log

    def _call(self, persona: str, payload: dict, story_id: str = "", stage: str = "", round: int = 0):
        output = self.backend.call(persona, to_jsonable(payload))
        if story_id:
            self.log.debate(story_id, stage, round, persona, output)
        return output

    # ---------- Edition ----------

    def run_edition(
        self,
        edition: str,
        date: str,
        items: list[dict],
        recent_clusters: list[dict] | None = None,
        recent_editions: list[dict] | None = None,
        open_series: list[dict] | None = None,
        corrections: list[dict] | None = None,
        gap_requests: list[dict] | None = None,
    ) -> EditionResult:
        wire = self._call("wire_desk", {
            "run": edition,
            "timestamp": date,
            "items": items,
            "recent_clusters": recent_clusters or [],
            "gap_requests": gap_requests or [],
        })
        self.log.write("wire_desk.json", wire)

        plan = self._call("assignment_editor", {
            "edition": edition,
            "date": date,
            "clusters": wire.clusters,
            "recent_editions": recent_editions or [],
            "open_series": open_series or [],
        })
        self.log.write("assignment_editor.json", plan)

        items_by_id = {item["source_id"]: item for item in items}
        clusters = {c.cluster_id: c for c in wire.clusters}
        assignments = sorted(plan.assignments, key=lambda a: a.position)

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_STORIES) as pool:
            stories = list(pool.map(
                lambda a: self._produce_safely(a, clusters, items_by_id), assignments
            ))
        for story in stories:
            self.log.write(f"stories/{story.story_id}.json", story)

        holds = [s for s in stories if s.status == "held"]
        self.log.write("holds.json", [
            {"story_id": s.story_id, "reason": s.reason, "hold_triggers": s.hold_triggers}
            for s in holds
        ])

        approved = [s for s in stories if s.status == "approved"]
        package = None
        if approved:
            package = self._call("format_desk", {
                "edition": edition,
                "date": date,
                "stories": [self._format_story(s) for s in approved],
                "one_thing_you_can_do": self._one_thing(plan, approved),
                "corrections": corrections or [],
            })
            self.log.write("format_desk.json", package)

        return EditionResult(edition, date, wire, plan, stories, package)

    def _one_thing(self, plan: schemas.AssignmentEditorOutput, approved: list[StoryResult]) -> str:
        # Only run the action item if its story made it through; otherwise it's unchecked.
        item = plan.one_thing_you_can_do
        if item.action and item.cluster_id in {s.assignment.cluster_id for s in approved}:
            return item.action
        return ""

    def _format_story(self, story: StoryResult) -> dict:
        return {
            "story_id": story.story_id,
            "format": story.assignment.format,
            **news_section(story.news),
            "take_box": story.take.text if story.take else "",
            "sources": [
                {"id": s["source_id"], "title": s.get("title", ""), "url": s.get("url", "")}
                for s in story.sources
            ],
        }

    # ---------- One story ----------

    def _produce_safely(self, assignment, clusters, items_by_id) -> StoryResult:
        story = StoryResult(assignment)
        try:
            return self._produce(story, clusters, items_by_id)
        except PersonaError as e:
            return story.stop("failed", str(e))

    def _produce(self, story: StoryResult, clusters, items_by_id) -> StoryResult:
        a = story.assignment
        cluster = clusters.get(a.cluster_id)
        if cluster is None:
            return story.stop("failed", f"Unknown cluster {a.cluster_id}")

        story.sources = [items_by_id[sid] for sid in cluster.source_ids if sid in items_by_id]
        if a.hold:
            story.hold_triggers.append("assignment_editor_hold")
        story.hold_triggers += sorted(HOLD_SIGNALS.intersection(cluster.signals))

        self._news_debate(story)
        if story.status == "approved" and a.policy_angle:
            self._take_debate(story)

        if story.status == "approved" and story.hold_triggers:
            story.stop("held", "Auto-hold: " + ", ".join(story.hold_triggers))
        return story

    def _review(self, story: StoryResult, stage: str, round: int, take_text: str, prior: list):
        """One review round: Fact Checker, then Standards Editor with the fact check in hand."""
        news = story.news
        people = list(news.people_mentioned) + (list(story.take.people_mentioned) if story.take else [])
        fc = self._call("fact_checker", {
            "story_id": story.story_id,
            "round": round,
            **news_section(news),
            "take_box": take_text,
            "people_mentioned": people,
            "sources": story.sources,
        }, story.story_id, stage, round)
        se = self._call("standards_editor", {
            "story_id": story.story_id,
            "round": round,
            "news_section": news_section(news),
            "take_box": take_text,
            "sources": story.sources,
            "fact_check_report": fc,
            "prior_rounds": prior,
        }, story.story_id, stage, round)
        story.hold_triggers += [t for t in se.hold_triggers if t not in story.hold_triggers]
        return fc, se

    def _verdict(self, story, fc, se, round, fc_blocking, se_blocking) -> str | None:
        """Shared rules for ending a debate. Returns None if the author should revise."""
        if fc.verdict == "unverifiable":
            story.hold_triggers.append("fact_checker_unverifiable")
            story.stop("held", fc.summary)
        elif se.verdict == "kill":
            story.stop("killed", se.reason)
        elif se.verdict == "escalate":
            story.stop("held", se.reason)
        elif fc.verdict == "pass" and se.verdict == "approve" and not fc_blocking and not se_blocking:
            return "approved"
        elif round == MAX_ROUNDS:
            story.stop("held", f"Blocking objections unresolved after round {MAX_ROUNDS}")
        else:
            return None
        return story.status

    def _news_debate(self, story: StoryResult) -> None:
        a = story.assignment
        base = {"story_id": a.story_id, "assignment": a, "sources": story.sources}
        story.news = self._call("beat_reporter", {**base, "round": 0, "objections": []},
                                a.story_id, "news", 0)
        prior: list[dict] = []
        for round in range(1, MAX_ROUNDS + 1):
            fc, se = self._review(story, "news", round, "", prior)
            fc_blocking = [c for c in fc.claims if c.severity == "blocking"]
            se_blocking = [o for o in se.objections if o.severity == "blocking"]
            if self._verdict(story, fc, se, round, fc_blocking, se_blocking):
                return
            objections = {
                "fact_checker": [c for c in fc.claims if c.severity in ("blocking", "nit")],
                "standards_editor": se.objections,
            }
            story.news = self._call("beat_reporter", {
                **base, "round": round, "objections": objections, "previous_draft": story.news,
            }, a.story_id, "news", round)
            prior.append({"round": round, "objections": se.objections, "responses": story.news.responses})

    def _take_debate(self, story: StoryResult) -> None:
        a = story.assignment
        brief = self._call("policy_desk", {
            "mode": "take",
            "story": news_section(story.news),
            "sources": story.sources,
            "assignment": a,
        }, a.story_id, "take", 0)
        if not brief.write_take:
            return

        base = {"mode": "take", "story": news_section(story.news), "brief": brief.brief, "sources": story.sources}
        story.take = self._call("columnist", {**base, "round": 0, "objections": []},
                                a.story_id, "take", 0)
        prior: list[dict] = []
        for round in range(1, MAX_ROUNDS + 1):
            fc, se = self._review(story, "take", round, story.take.text, prior)
            # The news section already passed. If a reviewer now finds a blocking
            # problem in it, the Columnist can't fix that, so send it to Tim.
            news_blocking = (
                [c for c in fc.claims if c.severity == "blocking" and c.location != "take"]
                + [o for o in se.objections if o.severity == "blocking" and o.section != "take"]
            )
            if news_blocking:
                story.stop("held", "Reviewers flagged the approved news section during take review")
                return
            fc_blocking = [c for c in fc.claims if c.severity == "blocking"]
            se_blocking = [o for o in se.objections if o.severity == "blocking"]
            if self._verdict(story, fc, se, round, fc_blocking, se_blocking):
                return
            objections = {
                "fact_checker": [c for c in fc.claims if c.location == "take" and c.severity in ("blocking", "nit")],
                "standards_editor": [o for o in se.objections if o.section == "take"],
            }
            story.take = self._call("columnist", {
                **base, "round": round, "objections": objections, "previous_draft": story.take,
            }, a.story_id, "take", round)
            prior.append({"round": round, "objections": se.objections, "responses": story.take.responses})
