"""Structured Claude extraction, exact quotation binding, and independent verification."""

import json
import re
from pathlib import Path

import anthropic
from pydantic import ValidationError

from shared.schema import Model, Refusal, Span
from contracts.models import DocumentResult, Reading, SourceDocument
from contracts.segment import Segment, chunks
from contracts.verify import EvidenceError, VerificationStats, bind_quote, disagreements, semantic, verify_number, verify_node_number

SONNET = 'claude-sonnet-5-5'
OPUS = 'claude-opus-5-5'
PROMPTS = Path(__file__).parent / 'prompts'


class ExtractionError(RuntimeError):
    pass


class Identity(Model):
    facility_id: str
    facility_source: Span
    effective_date: str
    effective_date_source: Span


def _items(reading: Reading, source: SourceDocument, chunk: Segment | None) -> dict:
    items = {}
    for term in reading.terms:
        # model_validate against shared types after replacing wire quotes.
        from shared.schema import TermNode
        data = term.model_dump()
        data['span'] = bind_quote(term.span, source, chunk)
        bound = TermNode.model_validate(data)
        verify_node_number(bound)
        items['term:' + term.id] = bound
    for covenant in reading.covenants:
        from shared.schema import Covenant
        if covenant.agreement_accession != source.agreement.accession:
            raise EvidenceError('model supplied a foreign agreement accession')
        data = covenant.model_dump()
        data['span'] = bind_quote(covenant.span, source, chunk)
        for threshold, raw in zip(data['thresholds'], covenant.thresholds):
            threshold['source'] = bind_quote(raw.source, source, chunk)
            verify_number(threshold['value'], threshold['source'].text)
        items['covenant:' + covenant.id] = Covenant.model_validate(data)
    for removal in reading.removed_covenants:
        items['remove:' + removal.covenant_id] = bind_quote(removal.source, source, chunk)
    metadata = (reading.facility_id, reading.facility_source, reading.effective_date, reading.effective_date_source)
    if all(value is not None for value in metadata):
        if not re.fullmatch(r'[a-z0-9][a-z0-9_\-]*', reading.facility_id):
            raise EvidenceError('invalid facility identity slug')
        items['identity'] = Identity(facility_id=reading.facility_id,
            facility_source=bind_quote(reading.facility_source, source, chunk),
            effective_date=reading.effective_date.isoformat(),
            effective_date_source=bind_quote(reading.effective_date_source, source, chunk))
    if any(r.scope == 'quarter' for r in reading.refusals):
        raise EvidenceError('contract extraction cannot issue quarter-level refusals')
    if len(items) != len(reading.terms) + len(reading.covenants) + len(reading.removed_covenants) + ('identity' in items):
        raise EvidenceError('duplicate extraction ids in one response')
    return items


def _hard(reading: Reading) -> bool:
    if reading.refusals or any(n.op in {'cap', 'floor'} for n in reading.terms):
        return True
    nodes = {n.id: n for n in reading.terms}

    def depth(key, seen):
        if key in seen:
            return 10
        node = nodes.get(key)
        return 0 if node is None else 1 + max((depth(k, seen | {key}) for k in node.children), default=0)

    return any(depth(key, set()) >= 4 for key in nodes)


class Extractor:
    def __init__(self, client=None):
        self.client = client if client is not None else anthropic.Anthropic(max_retries=2, timeout=120)
        self.stats = VerificationStats()

    def preflight(self):
        """Fail before expensive discovery if credentials or required models are unavailable."""
        available = {model.id for model in self.client.models.list(limit=100).data}
        missing = {name for name in (SONNET, OPUS)
                   if not any(model == name or model.startswith(name + '-') for model in available)}
        if missing:
            raise ExtractionError('Required model ids unavailable to this key: ' + ', '.join(sorted(missing)))

    def _request(self, source, ranges, *, model=SONNET, task='', verifier=False):
        prompt = (PROMPTS / 'extract.txt').read_text()
        if verifier:
            prompt += '\n' + (PROMPTS / 'verify.txt').read_text()
        content = json.dumps({'accession': source.agreement.accession, 'url': source.key,
                              'instrument_kind': source.agreement.kind, 'filed': str(source.agreement.filed)})
        content += '\n' + task
        for chunk in ranges:
            content += f'\nSOURCE RANGE [{chunk.start}, {chunk.end})\n{chunk.text}\nEND SOURCE RANGE\n'
        response = self.client.messages.create(model=model, max_tokens=12000, system=prompt,
            messages=[{'role': 'user', 'content': content}],
            tools=[{'name': 'record_extraction', 'description': 'Record only source-supported covenant evidence.',
                    'input_schema': Reading.model_json_schema()}],
            tool_choice={'type': 'tool', 'name': 'record_extraction'})
        records = [block for block in response.content if block.type == 'tool_use' and block.name == 'record_extraction']
        if response.stop_reason != 'tool_use' or len(records) != 1:
            raise EvidenceError('missing, multiple or truncated structured tool response')
        return Reading.model_validate(records[0].input)

    def _read_chunk(self, source, chunk, notes, ranges=None):
        failures = []
        # An invalid quote is discarded, never silently relocated or rewritten.
        for attempt, model in enumerate((SONNET, SONNET, OPUS)):
            try:
                reading = self._request(source, ranges or [chunk], model=model,
                    task='Retry rejected evidence: ' + '; '.join(failures) if failures else '')
                items = _items(reading, source, chunk)
                if model != OPUS and _hard(reading):
                    reading = self._request(source, ranges or [chunk], model=OPUS,
                        task='Hard definition review: reconstruct caps, deep dependencies and unsupported conditions.\n'
                             + reading.model_dump_json())
                    items = _items(reading, source, chunk)
                    notes.append(f'Escalated hard definitions in source range {chunk.start}:{chunk.end} to {OPUS}.')
                return items, reading.refusals, reading.extraction_notes
            except (EvidenceError, ValidationError) as error:
                self.stats.span_retries += 1
                failures.append(str(error)[:600])
        return {}, [Refusal(scope='agreement', ref=source.key, reason='ambiguous_definition',
                    detail=f'Invalid evidence after extraction retries at {chunk.start}:{chunk.end}: {failures[-1]}')], []

    def _pass(self, source, alternate, notes):
        candidates = {}
        refusals = []
        layout = chunks(source.text, alternate=alternate)
        for chunk in layout:
            ranges = None
            if alternate and len(layout) == 1 and len(source.text) > 1:
                # Small agreements still receive a second layout: two separately
                # delimited contiguous ranges in one independent extraction call.
                mid = len(source.text) // 2
                ranges = [Segment(0, mid, source.text[:mid]),
                          Segment(mid, len(source.text), source.text[mid:])]
            items, rejected, extracted_notes = self._read_chunk(source, chunk, notes, ranges)
            refusals.extend(rejected)
            notes.extend(extracted_notes)
            for key, item in items.items():
                versions = candidates.setdefault(key, [])
                if not any(semantic(item) == semantic(previous) for previous in versions):
                    versions.append(item)
        return candidates, refusals

    def _resolve(self, key, candidates, source):
        spans = []
        for candidate in candidates:
            if isinstance(candidate, Identity):
                spans += [candidate.facility_source, candidate.effective_date_source]
            else:
                spans.append(candidate if isinstance(candidate, Span) else candidate.span)
        lo = max(0, min(s.char_start for s in spans) - 12000)
        hi = min(len(source.text), max(s.char_end for s in spans) + 12000)
        if hi - lo > 120000:
            return None
        context = Segment(lo, hi, source.text[lo:hi])
        task = f'Disputed key: {key}\nCandidates:\n' + json.dumps([c.model_dump(mode='json') for c in candidates])
        self.stats.verifier_calls += 1
        try:
            reading = self._request(source, [context], model=OPUS, task=task, verifier=True)
            items = _items(reading, source, context)
            item = items.get(key)
            if reading.refusals or item is None or not any(semantic(item) == semantic(c) for c in candidates):
                return None
            return item
        except (EvidenceError, ValidationError):
            return None

    def read(self, source: SourceDocument) -> DocumentResult:
        notes = []
        first, refusals = self._pass(source, False, notes)
        second, more_refusals = self._pass(source, True, notes)
        refusals.extend(more_refusals)
        left = {key: values[0] for key, values in first.items()}
        right = {key: values[0] for key, values in second.items()}
        disputed = disagreements(left, right)
        disputed |= {key for key, values in first.items() if len(values) > 1}
        disputed |= {key for key, values in second.items() if len(values) > 1}
        self.stats.compared += len(left.keys() | right.keys())
        self.stats.disagreed += len(disputed)
        chosen = {key: value for key, value in left.items() if key not in disputed}
        for key in sorted(disputed):
            candidates = first.get(key, []) + second.get(key, [])
            resolved = self._resolve(key, candidates, source)
            if resolved is None:
                refusals.append(Refusal(scope='agreement' if key == 'identity' else 'covenant',
                    ref=source.key if key == 'identity' else key, reason='ambiguous_definition',
                    detail=f'Two chunk layouts disagree on {key}; verifier could not establish one supported reading.'))
                notes.append(f'Unresolved verifier disagreement: {key} in {source.key}.')
            else:
                chosen[key] = resolved
                notes.append(f'Verifier resolved disagreement: {key} in {source.key}.')
        identity = chosen.get('identity')
        if not identity and not refusals:
            refusals.append(Refusal(scope='agreement', ref=source.key, reason='ambiguous_definition',
                                    detail='No complete cited facility identity and effective date after both passes.'))
        from datetime import date
        return DocumentResult(source=source, facility_id=identity.facility_id if identity else None,
            facility_source=identity.facility_source if identity else None,
            effective_date=date.fromisoformat(identity.effective_date) if identity else None,
            effective_date_source=identity.effective_date_source if identity else None,
            terms=[value for key, value in chosen.items() if key.startswith('term:')],
            covenants=[value for key, value in chosen.items() if key.startswith('covenant:')],
            removed_covenants={key.removeprefix('remove:'): value for key, value in chosen.items() if key.startswith('remove:')},
            refusals=refusals, notes=notes)
