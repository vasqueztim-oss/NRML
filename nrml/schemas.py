"""Pydantic models for every persona's JSON output.

These mirror the "Output format" block in each persona prompt. They are passed
to the API as structured-output schemas, so the model can only return JSON
that fits them. If you change a prompt's output format, change it here too.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    # Structured outputs require additionalProperties: false on every object.
    model_config = ConfigDict(extra="forbid")


# ---------- Wire Desk ----------

class Cluster(Strict):
    cluster_id: str
    is_follow_up: bool
    title: str
    summary: str
    source_ids: list[str]
    beat: Literal["money", "housing", "health", "work", "government", "safety", "local", "other"]
    geography: Literal["national", "california", "la_county", "inglewood"]
    core_beat: bool
    primary_available: bool
    signals: list[Literal["trending_only", "hot_button", "breaking_tragedy", "named_accusation", "unconfirmed"]]


class GapAnswer(Strict):
    story_id: str
    gap: str
    found_in: list[str]
    fetch_suggestion: str


class Discard(Strict):
    source_id: str
    reason: str


class WireDeskOutput(Strict):
    run: Literal["morning", "evening"]
    clusters: list[Cluster]
    gap_answers: list[GapAnswer]
    discarded: list[Discard]


# ---------- Assignment Editor ----------

class Assignment(Strict):
    story_id: str
    cluster_id: str
    format: Literal["brief", "deep"]
    beat: str
    geography: str
    position: int
    angle: str
    why_it_matters: str
    policy_angle: bool
    hold: bool


class OneThing(Strict):
    cluster_id: str
    action: str


class Skip(Strict):
    cluster_id: str
    filter: str
    reason: str


class AssignmentEditorOutput(Strict):
    edition: Literal["morning", "evening"]
    date: str
    assignments: list[Assignment]
    one_thing_you_can_do: OneThing
    skipped: list[Skip]


# ---------- Shared revision pieces ----------

class Person(Strict):
    name: str
    role: str
    source_id: str


class Response(Strict):
    objection_quote: str
    action: Literal["fix", "defend"]
    new_text: str
    reason: str


# ---------- Beat Reporter ----------

class BeatReporterOutput(Strict):
    story_id: str
    round: int
    headline: str
    dek: str
    body: str
    people_mentioned: list[Person]
    gaps: list[str]
    responses: list[Response]


# ---------- Fact Checker ----------

class Claim(Strict):
    location: Literal["headline", "dek", "body", "take"]
    text: str
    cited: list[str]
    status: Literal["supported", "overstated", "unsupported", "contradicted", "wrong_source", "uncited"]
    severity: Literal["none", "blocking", "nit", "concern"]
    problem: str
    source_says: str
    suggested_fix: str


class FactCheckerOutput(Strict):
    story_id: str
    round: int
    verdict: Literal["pass", "flags", "unverifiable"]
    summary: str
    claims: list[Claim]
    concerns: list[str]


# ---------- Standards Editor ----------

class Objection(Strict):
    section: Literal["news", "take", "headline"]
    quote: str
    rule: str
    severity: Literal["blocking", "nit"]
    problem: str
    suggested_fix: str


class StandardsEditorOutput(Strict):
    story_id: str
    round: int
    verdict: Literal["approve", "revise", "kill", "escalate"]
    reason: str
    hold_triggers: list[str]
    objections: list[Objection]


# ---------- Policy Desk ----------

class PolicyOption(Strict):
    policy: str
    backed_by: str
    tried_in: str
    results: str
    cost: str


class PolicyBrief(Strict):
    problem: str
    options: list[PolicyOption]
    evidence_summary: str
    strongest_counterargument: str
    response_to_counterargument: str
    common_ground: str
    story_opening: str


class PolicyDeskOutput(Strict):
    story_id: str
    mode: Literal["take", "series"]
    write_take: bool
    decline_reason: str
    brief: PolicyBrief
    gaps: list[str]


# ---------- Columnist ----------

class ColumnistOutput(Strict):
    story_id: str
    mode: Literal["take", "series"]
    round: int
    headline: str
    text: str
    people_mentioned: list[Person]
    gaps: list[str]
    responses: list[Response]


# ---------- Format Desk ----------

class EmailSection(Strict):
    type: Literal["greeting", "correction", "brief", "action", "deep", "footer"]
    story_id: str
    markdown: str


class Email(Strict):
    subject: str
    preheader: str
    html_sections: list[EmailSection]


class BlogPost(Strict):
    title: str
    markdown: str


class VideoCard(Strict):
    text: str
    source: str


class VideoScript(Strict):
    story_id: str
    cards: list[VideoCard]


class VideoSkip(Strict):
    story_id: str
    reason: str


class Trim(Strict):
    story_id: str
    removed: str


class FormatDeskOutput(Strict):
    edition: Literal["morning", "evening"]
    date: str
    email: Email
    blog_post: BlogPost
    video_scripts: list[VideoScript]
    skipped_for_video: list[VideoSkip]
    trims: list[Trim]
