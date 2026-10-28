import json
from datetime import date

from contracts.discover import Discovery
from contracts.extract import Extractor
from contracts.models import SourceDocument
from contracts.run import build_contract, main, process_company, universe_ciks
from contracts.tests.test_extract import FakeExtractor, reading
from contracts.tests.test_integrity import source
from shared.schema import Company, Refusal


def discovery(source):
    return Discovery(Company(cik='0000000001', name='Synthetic Test Borrower'), [source])


def test_publication_round_trip_and_idempotency(source, tmp_path):
    extractor = FakeExtractor(lambda s, r, k, n: reading(s))
    output, cached = process_company(discovery(source), extractor, tmp_path)
    assert not cached and len(output.covenants) == 1
    path = tmp_path / '0000000001.json'
    before = path.read_bytes(), path.stat().st_mtime_ns
    again, cached = process_company(discovery(source), extractor, tmp_path)
    assert cached and again == output
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert len(extractor.calls) == 2
    # Tampering with a valid JSON field cannot pass the manifest integrity check.
    tampered = json.loads(path.read_text())
    tampered['covenants'][0]['thresholds'][0]['value'] = 999
    path.write_text(json.dumps(tampered))
    output, cached = process_company(discovery(source), extractor, tmp_path)
    assert not cached and output.covenants[0].thresholds[0].value == 4.5


def test_source_change_invalidates_cache(source, tmp_path):
    extractor = FakeExtractor(lambda s, r, k, n: reading(s))
    process_company(discovery(source), extractor, tmp_path)
    changed = SourceDocument(source.agreement, source.text + '\nNew appendix.')
    _, cached = process_company(discovery(changed), extractor, tmp_path)
    assert not cached and len(extractor.calls) == 4


def test_incomplete_discovery_and_redaction_never_publish_computable_covenants(source):
    extractor = FakeExtractor(lambda *args: (_ for _ in ()).throw(AssertionError('must not call Claude')))
    found = discovery(source)
    found.refusals.append(Refusal(scope='company', ref='1', reason='missing_filing', detail='One amendment unavailable.'))
    output = build_contract(found, extractor)
    assert not output.covenants and output.refusals[0].reason == 'missing_filing'
    redacted = SourceDocument(source.agreement.model_copy(update={'redacted': True}), source.text)
    output = build_contract(discovery(redacted), extractor)
    assert not output.covenants and output.refusals[0].reason == 'redacted'


def test_cli_environment_checks_and_single_cik(monkeypatch, source, tmp_path, capsys):
    import contracts.run as run
    monkeypatch.delenv('SEC_USER_AGENT', raising=False)
    assert main(['--cik', '1']) == 2
    monkeypatch.setenv('SEC_USER_AGENT', 'Covenant Watch test@example.org')
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    assert main(['--cik', '1']) == 2
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-test-key')
    extractor = FakeExtractor(lambda s, r, k, n: reading(s))
    monkeypatch.setattr(extractor, 'preflight', lambda: None)
    monkeypatch.setattr(run, 'Extractor', lambda **kwargs: extractor)
    monkeypatch.setattr(run, 'discover', lambda cik: discovery(source))
    real_process = run.process_company
    monkeypatch.setattr(run, 'process_company', lambda d, e: real_process(d, e, tmp_path))
    assert main(['--cik', '1', '--max-cost-usd', '1']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['companies'] == 1 and report['companies_with_covenants'] == 1
    assert report['verifier_disagreement_rate'] == 0


def test_universe_is_read_only_with_five_company_fallback(monkeypatch, tmp_path):
    import contracts.run as run
    path = tmp_path / 'universe.json'
    monkeypatch.setattr(run, 'UNIVERSE', path)
    monkeypatch.setattr(run, 'dev_companies', lambda: [Company(cik=str(i), name='Synthetic') for i in range(1, 6)])
    assert universe_ciks() == ['1', '2', '3', '4', '5']
    assert not path.exists()
    path.write_text(json.dumps([{'cik': '1', 'role': 'dev'}, {'cik': '1', 'role': 'dev'}, {'cik': '2', 'role': 'peer', 'peer_of': '1'}]))
    original = path.read_bytes()
    assert universe_ciks() == ['0000000001', '0000000002']
    assert path.read_bytes() == original


def test_cli_budget_required_before_constructing_client(monkeypatch):
    import contracts.run as run
    monkeypatch.setenv('SEC_USER_AGENT', 'Covenant Watch test@example.org')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'unused-test-value')
    monkeypatch.setattr(run, 'Extractor', lambda **kw: (_ for _ in ()).throw(AssertionError('no client')))
    assert main(['--cik', '1']) == 2
    assert main(['--cik', '1', '--max-cost-usd', '-1']) == 2


def test_plan_only_needs_no_key_and_never_constructs_model_client(monkeypatch, source, capsys):
    import contracts.run as run
    monkeypatch.setenv('SEC_USER_AGENT', 'Covenant Watch test@example.org')
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.setattr(run, 'Extractor', lambda **kw: (_ for _ in ()).throw(AssertionError('no client')))
    monkeypatch.setattr(run, 'discover', lambda cik: discovery(source))
    assert main(['--cik', '1', '--pilot', '--plan-only']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['inference_started'] is False and len(report['plans']) == 1


def test_pilot_outputs_are_separate_and_contain_at_most_one_covenant(source, tmp_path):
    import contracts.run as run
    from contracts.models import QuotedCovenant
    def respond(s, r, k, n):
        response = reading(s)
        response.covenants.append(response.covenants[0].model_copy(update={'id': 'another'}))
        return response
    extractor = FakeExtractor(respond)
    selected = run.pilot_discovery(discovery(source))
    contract, _ = process_company(selected, extractor, tmp_path / '_pilots', pilot=True)
    assert len(contract.covenants) == 1
    assert not list(tmp_path.glob('*.json'))
    assert (tmp_path / '_pilots' / '0000000001.json').exists()
    assert any('PILOT ONLY' in note for note in contract.extraction_notes)


def test_pilot_skips_documents_without_locally_retrievable_financial_clauses(source):
    import contracts.run as run
    selected = discovery(source)
    newer = SourceDocument(source.agreement.model_copy(update={'filed': date(2025, 1, 1),
                        'url': 'https://www.sec.gov/newer'}), 'Administrative agreement, no financial test.')
    selected.documents.append(newer)
    assert run.pilot_discovery(selected).documents == [source]
