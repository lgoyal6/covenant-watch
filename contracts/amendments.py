"""Apply verified document deltas within a cited, stable facility lineage."""

import math
from datetime import timedelta

from shared.schema import Covenant, Refusal, TermNode, Threshold
from contracts.models import DocumentResult


class AmendmentError(ValueError):
    pass


def validate_schedule(thresholds: list[Threshold]) -> list[Threshold]:
    if not thresholds:
        raise AmendmentError('covenant has no threshold')
    ordered = sorted(thresholds, key=lambda t: t.effective_from)
    for i, threshold in enumerate(ordered):
        if not math.isfinite(threshold.value):
            raise AmendmentError('non-finite threshold')
        if threshold.effective_to is not None and threshold.effective_to < threshold.effective_from:
            raise AmendmentError('threshold ends before it starts')
        if i and (ordered[i - 1].effective_to is None or ordered[i - 1].effective_to >= threshold.effective_from):
            raise AmendmentError('overlapping threshold intervals')
    return ordered


def overlay(old: list[Threshold], new: list[Threshold], effective_date) -> list[Threshold]:
    new = validate_schedule(new)
    old = validate_schedule(old)
    if new[0].effective_from != effective_date:
        raise AmendmentError('replacement schedule must start on cited effective date')
    # New intervals replace only their stated intervals. Temporary waivers preserve
    # the original schedule afterwards, including original future step-downs.
    remaining = old
    for replacement in new:
        next_remaining = []
        for prior in remaining:
            if ((prior.effective_to is not None and prior.effective_to < replacement.effective_from)
                    or (replacement.effective_to is not None and prior.effective_from > replacement.effective_to)):
                next_remaining.append(prior)
                continue
            if prior.effective_from < replacement.effective_from:
                next_remaining.append(prior.model_copy(update={'effective_to': replacement.effective_from - timedelta(days=1)}))
            if replacement.effective_to is not None and (prior.effective_to is None or prior.effective_to > replacement.effective_to):
                next_remaining.append(prior.model_copy(update={'effective_from': replacement.effective_to + timedelta(days=1)}))
        remaining = next_remaining
    return validate_schedule(remaining + new)


def apply_amendments(results: list[DocumentResult]) -> tuple[list[TermNode], list[Covenant], list[Refusal], list[str]]:
    facilities = {}
    refusals = []
    notes = []
    # Filed order is discovery order; operative order is supported by effective-date citations.
    ordered = sorted(results, key=lambda r: (r.effective_date or r.source.agreement.filed,
                                            r.source.agreement.filed, r.source.key))
    for result in ordered:
        agreement = result.source.agreement
        refusals.extend(result.refusals)
        notes.extend(result.notes)
        if not result.is_credit_agreement:
            continue
        facility = result.facility_id
        if (not facility or not result.facility_source or result.effective_date is None
                or not result.effective_date_source):
            refusals.append(Refusal(scope='agreement', ref=agreement.url, reason='ambiguous_definition',
                                    detail='Missing cited facility identity or operative effective date.'))
            # Cannot prove which facility the unknown amendment affects.
            for state in facilities.values():
                state['blocked'] = True
            continue
        state = facilities.setdefault(facility, dict(terms={}, covenants={}, initialized=False, blocked=False))
        if agreement.kind == 'amendment' and not state['initialized']:
            state['blocked'] = True
            refusals.append(Refusal(scope='agreement', ref=agreement.url, reason='missing_filing',
                                    detail='Amendment has no verified original or restated facility.'))
            continue
        if agreement.kind == 'amendment' and not (result.terms or result.covenants or result.removed_covenants):
            state['blocked'] = True
            refusals.append(Refusal(scope='agreement', ref=agreement.url, reason='ambiguous_definition',
                                    detail='No supported amendment delta; absence of extraction does not prove unchanged financial terms.'))
            continue
        # Any unresolved agreement or covenant can affect the in-force result.
        if result.refusals:
            state['blocked'] = True
            continue
        if agreement.kind in {'original', 'restatement'}:
            if agreement.kind == 'original' and state['initialized']:
                state['blocked'] = True
                refusals.append(Refusal(scope='agreement', ref=agreement.url, reason='ambiguous_definition',
                                        detail='Two originals claim the same facility identity.'))
                continue
            state.update(terms={}, covenants={}, initialized=True, blocked=False)
        try:
            patched = dict(state['covenants'])
            for covenant in result.covenants:
                schedule = validate_schedule(covenant.thresholds)
                if covenant.id in patched and agreement.kind == 'amendment':
                    previous = patched[covenant.id]
                    schedule = overlay(previous.thresholds, schedule, result.effective_date)
                    fields = ('kind', 'direction', 'numerator_term', 'denominator_term', 'test_period')
                    if all(getattr(previous, key) == getattr(covenant, key) for key in fields):
                        covenant = previous
                patched[covenant.id] = covenant.model_copy(update={'thresholds': schedule})
            for key in result.removed_covenants:
                if key not in patched:
                    raise AmendmentError(f'deletion references unknown covenant: {key}')
                del patched[key]
            state['terms'].update({t.id: t for t in result.terms})
            state['covenants'] = patched
        except AmendmentError as error:
            state['blocked'] = True
            refusals.append(Refusal(scope='agreement', ref=agreement.url, reason='ambiguous_definition', detail=str(error)))
    terms = []
    covenants = []
    for facility, state in sorted(facilities.items()):
        if state['blocked']:
            continue
        prefix = facility + ':'
        for node in state['terms'].values():
            cap = dict(node.cap) if node.cap else None
            if cap and cap.get('kind') == 'pct_of':
                cap['of'] = prefix + cap['of']
            terms.append(node.model_copy(update={'id': prefix + node.id,
                         'children': [prefix + key for key in node.children], 'cap': cap}))
        for covenant in state['covenants'].values():
            covenants.append(covenant.model_copy(update={'id': prefix + covenant.id,
                'numerator_term': prefix + covenant.numerator_term,
                'denominator_term': prefix + covenant.denominator_term if covenant.denominator_term else None}))
    return terms, covenants, refusals, notes
