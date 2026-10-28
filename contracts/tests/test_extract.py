from types import SimpleNamespace

from contracts.extract import Extractor, OPUS, SONNET
from contracts.models import Quote, QuotedCovenant, QuotedTerm, QuotedThreshold, Reading
from contracts.tests.test_integrity import source  # pytest fixture


def reading(source, *, amount=4.5, bad_quote=False):
    return Reading(is_credit_agreement=True, facility_id='borrower_agent_20220315',
        facility_source=Quote(text='ARTICLE I'), effective_date='2022-03-15',
        effective_date_source=Quote(text='SECTION 1.01 Definitions'),
        terms=[QuotedTerm(id='debt', label='total borrowings', op='leaf',
                          span=Quote(text='invented' if bad_quote else 'total borrowings'))],
        covenants=[QuotedCovenant(id='lev', kind='max_leverage', direction='max', numerator_term='debt',
            test_period='point_in_time', agreement_accession='a', span=Quote(text='Maximum leverage 4.50 to 1.00.'),
            thresholds=[QuotedThreshold(effective_from='2022-03-15', value=amount,
                                        source=Quote(text='Maximum leverage 4.50 to 1.00.' if amount != 5.0
                                                         else 'Alternative maximum leverage 5.00 to 1.00.'))])])


class FakeExtractor(Extractor):
    def __init__(self, callback):
        super().__init__(client=object())
        self.callback = callback
        self.calls = []

    def _request(self, source, ranges, **kwargs):
        self.calls.append(kwargs)
        return self.callback(source, ranges, kwargs, len(self.calls))


def test_two_independent_passes_agree(source):
    extractor = FakeExtractor(lambda s, r, k, n: reading(s))
    result = extractor.read(source)
    assert len(result.terms) == len(result.covenants) == 1
    assert len(extractor.calls) == 2
    assert extractor.stats.compared == 3 and extractor.stats.disagreed == 0
    assert not result.refusals


def test_invalid_quotes_are_discarded_and_retried(source):
    extractor = FakeExtractor(lambda s, r, k, n: reading(s, bad_quote=n == 1))
    result = extractor.read(source)
    assert not result.refusals
    assert extractor.stats.span_retries == 1
    assert result.terms[0].span.text == 'total borrowings'


def test_disagreement_resolved_by_verifier(source):
    from contracts.models import SourceDocument
    source = SourceDocument(source.agreement, source.text + '\nAlternative maximum leverage 5.00 to 1.00.')
    extractor = FakeExtractor(lambda s, r, k, n: reading(s, amount=5.0 if n == 2 else 4.5))
    result = extractor.read(source)
    assert not result.refusals
    assert result.covenants[0].thresholds[0].value == 4.5
    assert extractor.stats.disagreed == 1
    assert extractor.stats.verifier_calls == 1
    assert extractor.calls[-1]['verifier'] and extractor.calls[-1]['model'] == OPUS


def test_verifier_cannot_invent_compromise(source):
    from contracts.models import SourceDocument
    source = SourceDocument(source.agreement, source.text + '\nAlternative maximum leverage 5.00 to 1.00.')
    extractor = FakeExtractor(lambda s, r, k, n: reading(s, amount={1: 4.5, 2: 5.0}.get(n, 4.75)))
    result = extractor.read(source)
    assert not result.covenants
    assert result.refusals[0].reason == 'ambiguous_definition'
    assert any('Unresolved verifier disagreement' in n for n in result.notes)


def test_hard_definitions_escalate_to_opus(source):
    from contracts.models import SourceDocument
    source = SourceDocument(source.agreement, source.text + '\nRestructuring charges capped at $100.')
    def respond(s, r, kwargs, n):
        output = reading(s)
        output.terms.append(QuotedTerm(id='capped', label='capped debt', op='cap', children=['debt'],
            cap={'kind': 'abs', 'usd': 100}, span=Quote(text='Restructuring charges capped at $100.')))
        return output
    extractor = FakeExtractor(respond)
    extractor.read(source)
    assert [c['model'] for c in extractor.calls] == [SONNET, OPUS, SONNET, OPUS]


def test_structured_api_transport_uses_required_model_and_tool(source):
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(stop_reason='tool_use', content=[SimpleNamespace(
            type='tool_use', name='record_extraction', input=reading(source).model_dump(mode='json'))])
    extractor = Extractor(SimpleNamespace(messages=SimpleNamespace(create=create)))
    result = extractor.read(source)
    assert not result.refusals
    assert all(r['model'] == SONNET for r in requests)
    assert requests[0]['tool_choice'] == {'type': 'auto'}
    assert 'EXACT, contiguous substring' in requests[0]['system']
