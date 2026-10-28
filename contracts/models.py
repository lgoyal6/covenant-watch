"""Private extraction transport models. The shared on-disk schema stays frozen."""

from dataclasses import dataclass
from datetime import date

from pydantic import Field

from shared.schema import Agreement, Covenant, Model, Refusal, Span, TermNode, Threshold


@dataclass(frozen=True)
class SourceDocument:
    agreement: Agreement
    text: str  # Exact UTF-8 decoded HTTP body, including HTML markup.

    @property
    def key(self) -> str:
        return self.agreement.url


class Quote(Model):
    text: str = Field(min_length=1)
    section: str | None = None
    char_start: int | None = None  # Optional absolute hint for repeated quotations.


class QuotedTerm(TermNode):
    span: Quote


class QuotedThreshold(Threshold):
    source: Quote


class QuotedCovenant(Covenant):
    span: Quote
    thresholds: list[QuotedThreshold]


class Removal(Model):
    covenant_id: str
    source: Quote


class Reading(Model):
    is_credit_agreement: bool
    # Stable slug of original facility date, borrower, and administrative agent.
    facility_id: str | None = None
    facility_source: Quote | None = None
    effective_date: date | None = None
    effective_date_source: Quote | None = None
    terms: list[QuotedTerm] = []
    covenants: list[QuotedCovenant] = []
    removed_covenants: list[Removal] = []
    refusals: list[Refusal] = []
    extraction_notes: list[str] = []


@dataclass
class DocumentResult:
    source: SourceDocument
    facility_id: str | None
    facility_source: Span | None
    effective_date: date | None
    effective_date_source: Span | None
    terms: list[TermNode]
    covenants: list[Covenant]
    removed_covenants: dict[str, Span]
    refusals: list[Refusal]
    notes: list[str]
    is_credit_agreement: bool = True
