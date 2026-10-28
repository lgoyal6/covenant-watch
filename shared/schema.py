"""The contract between contracts/ (Laksh) and engine/, validation/, api/, web/ (Dat).

Frozen after kickoff. Changes: Laksh only, bump SCHEMA_VERSION, log in notes/laksh.md.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = "1.0"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Span(Model):
    """Every claim points to real text. `text` must be an exact substring of the document."""

    accession: str
    url: str
    section: str | None = None
    char_start: int
    char_end: int
    text: str


class Company(Model):
    cik: str
    name: str
    ticker: str | None = None
    sic: str | None = None


class Agreement(Model):
    accession: str
    url: str
    filed: date
    kind: Literal["original", "amendment", "restatement"]
    redacted: bool


class TermNode(Model):
    """One node in a definition tree."""

    id: str
    label: str
    op: Literal["sum", "subtract", "ratio", "leaf", "cap", "floor"]
    children: list[str] = []
    # {"kind": "pct_of", "of": node_id, "pct": 0.10} or {"kind": "abs", "usd": 25000000}
    cap: dict | None = None
    span: Span


class Threshold(Model):
    effective_from: date
    effective_to: date | None = None
    value: float
    source: Span


class Covenant(Model):
    id: str
    kind: Literal[
        "max_leverage",
        "min_interest_coverage",
        "min_fixed_charge_coverage",
        "max_senior_leverage",
        "min_liquidity",
        "other",
    ]
    direction: Literal["max", "min"]
    numerator_term: str
    denominator_term: str | None = None
    test_period: Literal["ttm", "quarter", "point_in_time"]
    thresholds: list[Threshold]  # already reflect amendments
    agreement_accession: str
    span: Span


class Refusal(Model):
    scope: Literal["company", "agreement", "covenant", "quarter"]
    ref: str
    reason: Literal[
        "redacted",
        "ambiguous_definition",
        "missing_filing",
        "unmapped_term",
        "pro_forma_adjustment",
        "currency_or_units",
        "other",
    ]
    detail: str


# ---- written by Laksh: data/contracts/{cik}.json ----


class ContractExtraction(Model):
    schema_version: str
    generated_at: datetime
    company: Company
    agreements: list[Agreement]
    terms: list[TermNode]  # amendments already applied
    covenants: list[Covenant]
    refusals: list[Refusal]  # contract-level only
    extraction_notes: list[str] = []


# ---- written by Dat: data/artifacts/{cik}.json ----


class Input(Model):
    """One leaf value used in a computation."""

    term_node: str
    value: float | None = None
    xbrl_concept: str | None = None  # e.g. "us-gaap:InterestExpense"
    fact_accession: str | None = None
    period_start: date | None = None
    period_end: date
    mapping_confidence: float
    validated: bool
    validation_note: str | None = None


class QuarterResult(Model):
    covenant_id: str
    period_end: date
    ratio_low: float | None = None
    ratio_high: float | None = None
    threshold: float | None = None
    headroom_low: float | None = None  # signed distance to threshold, worst case
    headroom_high: float | None = None  # best case
    status: Literal["ok", "warning", "breach", "indeterminate", "refused"]
    inputs: list[Input] = []
    missing: list[str] = []  # TermNode ids with no source


class CovenantArtifact(Model):
    schema_version: str
    generated_at: datetime
    contract: ContractExtraction  # carried through unchanged
    quarters: list[QuarterResult]
    refusals: list[Refusal]  # contract-level + engine-level


# ---- written by Dat: ground truth, universe, eval ----


class DisclosedRatio(Model):
    cik: str
    period_end: date
    covenant_kind: str
    reported_value: float
    reported_threshold: float | None = None
    span: Span


class CovenantEvent(Model):
    cik: str
    date: date
    kind: Literal["waiver", "amendment_loosening", "default", "acceleration"]
    span: Span


class UniverseEntry(Model):
    cik: str
    role: Literal["disclosed", "event", "peer", "dev"]
    peer_of: str | None = None


class GroundTruth(Model):
    """Shape of fixtures/groundtruth_example.json; on disk Dat writes disclosed.json and events.json separately."""

    disclosed: list[DisclosedRatio]
    events: list[CovenantEvent]
    universe: list[UniverseEntry]


class EvalReport(Model):
    schema_version: str
    generated_at: datetime
    extraction: dict  # field-level precision/recall vs gold labels
    ratio_accuracy: dict  # median abs error, % reported inside computed range
    early_warning: dict  # lead quarters, hit rate, false alarm rate vs peers
    refusals: dict  # counts by reason
    per_company: list[dict]
