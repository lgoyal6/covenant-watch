"""Lineage: every leaf value used in a computation becomes an Input record."""

from datetime import date

from engine.mapping import Mapping
from engine.xbrl import Value
from shared.schema import Input


def input_for(m: Mapping, v: Value | None, period_end: date) -> Input:
    if m.concept is None:
        return Input(term_node=m.term_node, period_end=period_end, mapping_confidence=0.0, validated=False,
                     validation_note=m.note or "unmapped")
    if v is None:
        return Input(term_node=m.term_node, xbrl_concept=m.concept, period_end=period_end, mapping_confidence=m.confidence,
                     validated=False, validation_note=f"{m.concept} not reported for this period")
    alt = f"fallback concept (primary {m.concept} not reported this period)" if v.concept != m.concept else None
    notes = [n for n in (m.note, alt, v.note(), f"proposer: {m.proposer}") if n]
    return Input(
        term_node=m.term_node, value=v.value * m.sign, xbrl_concept=v.concept, fact_accession=v.accession,
        period_start=v.start, period_end=v.end, mapping_confidence=m.confidence, validated=m.validated,
        validation_note="; ".join(notes),
    )
