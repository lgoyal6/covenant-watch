from decimal import Decimal
from types import SimpleNamespace

import pytest

from contracts.runtime import BudgetError, Price, Runtime, UncertainRequest, current_prices


PAYLOAD = dict(model='claude-sonnet-5-5', max_tokens=100, system='Read the clause.',
               messages=[{'role': 'user', 'content': 'Debt <= 4.5'}], tools=[], tool_choice={'type': 'auto'})
PRICES = {'claude-sonnet-5-5': Price(Decimal(2), Decimal(10), Decimal(4), Decimal('.1'))}


class Client:
    def __init__(self, crash=False):
        self.messages = self
        self.paid = self.counted = 0
        self.crash = crash

    def count_tokens(self, **kwargs):
        self.counted += 1
        return SimpleNamespace(input_tokens=50)

    def create(self, **kwargs):
        self.paid += 1
        if self.crash:
            raise KeyboardInterrupt()
        return SimpleNamespace(stop_reason='tool_use', content=[SimpleNamespace(type='tool_use',
            name='record_extraction', input={'is_credit_agreement': True})],
            usage=SimpleNamespace(input_tokens=50, output_tokens=20))


def test_missing_budget_and_insufficient_budget_never_send_inference(tmp_path):
    client = Client()
    with pytest.raises(BudgetError, match='explicit'):
        Runtime(tmp_path).perform(client, PAYLOAD, 'source')
    with pytest.raises(BudgetError, match='remaining budget'):
        Runtime(tmp_path, '.0001', prices=PRICES).perform(client, PAYLOAD, 'source')
    assert client.paid == 0


def test_spend_is_durable_and_resume_reuses_response_without_billing(tmp_path):
    client = Client()
    runtime = Runtime(tmp_path, '.1', prices=PRICES)
    key, response = runtime.perform(client, PAYLOAD, 'source')
    assert client.paid == 1
    assert runtime.charged == Decimal('.000300')
    assert runtime.ledger_path.exists()
    # A fresh process can reuse a completed response even without a new budget.
    assert Runtime(tmp_path).perform(client, PAYLOAD, 'source') == (key, response)
    assert client.paid == 1
    runtime.mark(key, 'verified')
    assert runtime.cached(key)['status'] == 'verified'


def test_interruption_keeps_reservation_and_blocks_blind_replay(tmp_path):
    client = Client(crash=True)
    runtime = Runtime(tmp_path, '.1', prices=PRICES)
    with pytest.raises(KeyboardInterrupt):
        runtime.perform(client, PAYLOAD, 'source')
    assert runtime.charged > 0
    with pytest.raises(UncertainRequest):
        Runtime(tmp_path, '.1', prices=PRICES).perform(client, PAYLOAD, 'source')
    assert client.paid == 1


def test_source_or_prompt_change_cannot_reuse_old_checkpoint(tmp_path):
    client = Client()
    runtime = Runtime(tmp_path, '1', prices=PRICES)
    runtime.perform(client, PAYLOAD, 'source')
    runtime.perform(client, PAYLOAD, 'changed source')
    runtime.perform(client, PAYLOAD | {'system': 'Different prompt'}, 'source')
    assert client.paid == 3


def test_tampered_checkpoint_is_not_ignored_and_rebilled(tmp_path):
    import json
    client = Client()
    runtime = Runtime(tmp_path, '1', prices=PRICES)
    key, _ = runtime.perform(client, PAYLOAD, 'source')
    record = json.loads(runtime.checkpoint_path(key).read_text())
    record['data']['response']['content'] = []
    runtime.checkpoint_path(key).write_text(json.dumps(record))
    with pytest.raises(BudgetError, match='integrity'):
        runtime.perform(client, PAYLOAD, 'source')
    assert client.paid == 1


def test_official_pricing_parser_rejects_batch_only_rows(monkeypatch):
    import contracts.runtime as runtime
    rows = ('<tr><td>Claude Sonnet 5.5</td><td>$2</td><td>$10</td><td>$2.50</td><td>$4</td><td>$0.10</td></tr>'
            '<tr><td>Claude Opus 5.5</td><td>$4</td><td>$20</td><td>$5</td><td>$8</td><td>$0.20</td></tr>')
    response = SimpleNamespace(url=runtime.PRICING_URL, text=rows, content=rows.encode(), raise_for_status=lambda: None)
    monkeypatch.setattr(runtime.httpx, 'get', lambda *a, **k: response)
    prices, proof = current_prices()
    assert prices['claude-sonnet-5-5'].input == Decimal(2)
    assert proof['rows']['claude-opus-5-5'].startswith('Claude Opus 5.5')
    response.text = '<tr><td>Claude Sonnet 5.5</td><td>$1</td><td>$5</td></tr>'
    with pytest.raises(BudgetError, match='both'):
        current_prices()


def test_incomplete_usage_keeps_worst_case_reservation(tmp_path):
    client = Client()
    original = client.create
    def create(**kwargs):
        response = original(**kwargs)
        response.usage = SimpleNamespace()
        return response
    client.create = create
    runtime = Runtime(tmp_path, '1', prices=PRICES)
    key, _ = runtime.perform(client, PAYLOAD, 'source')
    assert runtime.charged == Decimal(runtime.calls[0]['reserved_usd'])
    assert runtime.cached(key)['request'] == PAYLOAD
    assert runtime.cached(key)['source_sha256'] == 'source'


def test_usage_exceeding_reservation_halts_run_and_preserves_response(tmp_path):
    client = Client()
    original = client.create
    def create(**kwargs):
        response = original(**kwargs)
        response.usage.input_tokens = 1_000_000
        return response
    client.create = create
    runtime = Runtime(tmp_path, '10', prices=PRICES)
    with pytest.raises(BudgetError, match='exceeded'):
        runtime.perform(client, PAYLOAD, 'source')
    assert runtime.halted
    with pytest.raises(BudgetError, match='halted'):
        runtime.perform(client, PAYLOAD | {'system': 'Another call'}, 'source')
    assert client.paid == 1


def test_repeated_reservations_cannot_exceed_budget(tmp_path):
    client = Client()
    original = client.create
    def create(**kwargs):
        response = original(**kwargs)
        del response.usage
        return response
    client.create = create
    runtime = Runtime(tmp_path, '.04', prices=PRICES)
    with pytest.raises(BudgetError, match='remaining budget'):
        for index in range(100):
            runtime.perform(client, PAYLOAD | {'system': str(index)}, 'source')
    assert 0 < runtime.charged <= runtime.cap
    assert client.paid < 100


def test_concurrent_claim_cannot_overwrite_existing_pending_request(tmp_path):
    import threading
    client = Client()
    entered, release = threading.Event(), threading.Event()
    original = client.create
    def create(**kwargs):
        entered.set()
        assert release.wait(3)
        return original(**kwargs)
    client.create = create
    first = Runtime(tmp_path, '1', prices=PRICES)
    errors = []
    def work():
        try:
            first.perform(client, PAYLOAD, 'source')
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=work)
    thread.start()
    try:
        assert entered.wait(3)
        with pytest.raises(UncertainRequest):
            Runtime(tmp_path, '1', prices=PRICES).perform(client, PAYLOAD, 'source')
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive() and not errors and client.paid == 1


def test_malformed_budget_and_unreadable_checkpoint_block_inference(tmp_path):
    with pytest.raises(BudgetError):
        Runtime(tmp_path, 'garbage', prices=PRICES)
    client = Client()
    runtime = Runtime(tmp_path, '1', prices=PRICES)
    key, _ = runtime.perform(client, PAYLOAD, 'source')
    runtime.checkpoint_path(key).write_text('{')
    with pytest.raises(BudgetError, match='Unreadable'):
        runtime.perform(client, PAYLOAD, 'source')
    assert client.paid == 1
