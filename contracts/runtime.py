"""Durable request checkpoints and conservative per-run dollar reservations."""

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from html.parser import HTMLParser
from pathlib import Path

import httpx
import anthropic

from contracts.verify import fingerprint

PRICING_URL = 'https://platform.claude.com/docs/en/about-claude/pricing'
MODEL_LABELS = {'claude-sonnet-5-5': 'Claude Sonnet 5.5', 'claude-opus-5-5': 'Claude Opus 5.5'}


class BudgetError(RuntimeError):
    pass


class UncertainRequest(BudgetError):
    pass


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.stem + '-', suffix='.tmp', delete=False) as handle:
            temp = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
    finally:
        if temp and temp.exists():
            temp.unlink()


@dataclass(frozen=True)
class Price:
    input: Decimal
    output: Decimal
    cache_write: Decimal
    cache_read: Decimal

    def cost(self, inputs, outputs, writes=0, reads=0):
        return ((self.input * inputs + self.output * outputs + self.cache_write * writes +
                 self.cache_read * reads) / 1_000_000).quantize(Decimal('0.000001'), rounding=ROUND_CEILING)


class PriceTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.row, self.rows = None, []

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []

    def handle_data(self, text):
        if self.row is not None:
            self.row.append(text)

    def handle_endtag(self, tag):
        if tag == 'tr' and self.row is not None:
            self.rows.append(' '.join(self.row))
            self.row = None


def current_prices():
    """Read the standard model table, not fast-mode or batch-discount tables."""
    import re
    response = httpx.get(PRICING_URL, follow_redirects=True, timeout=30)
    response.raise_for_status()
    if not str(response.url).startswith('https://platform.claude.com/'):
        raise BudgetError('Pricing redirect left the official documentation host')
    table = PriceTable()
    table.feed(response.text)
    prices, evidence = {}, {}
    for model, label in MODEL_LABELS.items():
        # Standard rows include input, output, 5m write, 1h write and read prices.
        for row in table.rows:
            amounts = re.findall(r'\$\s*([\d,.]+)', row)
            if row.startswith(label + ' ') and len(amounts) == 5:
                values = [Decimal(value.replace(',', '')) for value in amounts]
                if any(not value.is_finite() or value <= 0 for value in values):
                    raise BudgetError('Invalid model pricing')
                prices[model] = Price(values[0], values[1], max(values[2:4]), values[4])
                evidence[model] = row
                break
    if set(prices) != set(MODEL_LABELS):
        raise BudgetError('Could not verify standard prices for both required models; inference disabled')
    proof = dict(url=PRICING_URL, checked_at=datetime.now(timezone.utc).isoformat(),
                 page_sha256=hashlib.sha256(response.content).hexdigest(), rows=evidence)
    return prices, proof


class Runtime:
    def __init__(self, directory: Path, max_usd=None, *, prices=None, pricing_proof=None):
        self.directory = Path(directory)
        try:
            self.cap = Decimal(str(max_usd)) if max_usd is not None else None
        except InvalidOperation as error:
            raise BudgetError('Budget must be a finite positive dollar amount') from error
        if self.cap is not None and (not self.cap.is_finite() or self.cap <= 0):
            raise BudgetError('Budget must be a finite positive dollar amount')
        self.prices, self.proof = prices, pricing_proof
        self.run_id = uuid.uuid4().hex
        self.calls = []
        self.halted = False

    @property
    def ledger_path(self):
        return self.directory / '_runs' / (self.run_id + '.json')

    @property
    def charged(self):
        return sum((Decimal(call['charged_usd']) for call in self.calls), Decimal(0))

    def persist(self):
        atomic_json(self.ledger_path, dict(run_id=self.run_id, max_usd=str(self.cap),
                    charged_or_reserved_usd=str(self.charged), halted=self.halted, pricing=self.proof, calls=self.calls))

    def checkpoint_path(self, key):
        return self.directory / '_checkpoints' / (key + '.json')

    def store(self, key, data):
        atomic_json(self.checkpoint_path(key), dict(data=data, checksum=fingerprint(data)))

    def cached(self, key):
        path = self.checkpoint_path(key)
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text())
        except (ValueError, OSError) as error:
            raise BudgetError(f'Unreadable checkpoint; no automatic replay: {path}') from error
        if record.get('checksum') != fingerprint(record.get('data')):
            raise BudgetError(f'Checkpoint integrity failed: {path}')
        data = record['data']
        if data.get('request_hash') != key:
            raise BudgetError('Checkpoint request identity mismatch')
        if data['status'] == 'pending':
            raise UncertainRequest(f'Request may already have been billed. No automatic replay: {path}')
        return data

    def claim(self, key, data):
        path = self.checkpoint_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents concurrent runs from billing the same request.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(dict(data=data, checksum=fingerprint(data)), handle, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())

    def mark(self, key, status):
        data = self.cached(key)
        if data is not None:
            data['status'] = status
            self.store(key, data)

    def perform(self, client, payload, source_hash):
        key = fingerprint(dict(source_sha256=source_hash, payload=payload))
        cached = self.cached(key)
        if cached is not None:
            return key, cached['response']
        if self.halted:
            raise BudgetError('Run is halted for billing review')
        if self.cap is None:
            raise BudgetError('Paid extraction requires an explicit --max-cost-usd budget')
        if self.prices is None:
            self.prices, self.proof = current_prices()
        model = payload['model']
        if model not in self.prices:
            raise BudgetError('No verified pricing for requested model')
        if hasattr(client, 'base_url') and str(client.base_url).rstrip('/') != 'https://api.anthropic.com':
            raise BudgetError('Verified pricing covers the official Anthropic API only')
        token_payload = {k: payload[k] for k in ('model', 'system', 'messages', 'tools', 'tool_choice')}
        counted = client.messages.count_tokens(**token_payload).input_tokens
        if isinstance(counted, bool) or not isinstance(counted, int) or counted < 0:
            raise BudgetError('Token-count endpoint returned invalid usage')
        # Counting is approximate. UTF-8 request bytes plus tool-format headroom is
        # deliberately conservative, and is never smaller than the server estimate.
        upper = max(counted, len(json.dumps(token_payload, ensure_ascii=False).encode('utf-8')) + 4096)
        if upper > 200000:
            raise BudgetError('Input exceeds the supported standard-context pricing envelope')
        price = self.prices[model]
        reserve = ((max(price.input, price.cache_write) * upper + price.output * payload['max_tokens'])
                   / 1_000_000).quantize(Decimal('0.000001'), rounding=ROUND_CEILING)
        if self.charged + reserve > self.cap:
            raise BudgetError(f'Next {model} request reserves ${reserve}; remaining budget is ${self.cap - self.charged}')
        call = dict(request_hash=key, model=model, input_estimate=counted, input_upper_bound=upper,
                    max_output_tokens=payload['max_tokens'], reserved_usd=str(reserve),
                    charged_usd=str(reserve), status='pending')
        pending = dict(request_hash=key, status='pending', run_id=self.run_id,
                       source_sha256=source_hash, request=payload)
        try:
            self.claim(key, pending)
        except FileExistsError:
            completed = self.cached(key)
            if completed is None:
                raise BudgetError('Concurrent checkpoint disappeared; no replay')
            return key, completed['response']
        self.calls.append(call)
        self.persist()  # Reserve before inference; unknown outcomes retain this charge.
        guarded_client = client.with_options(max_retries=0) if isinstance(client, anthropic.Anthropic) else client
        response = guarded_client.messages.create(**payload)
        blocks = []
        for block in response.content:
            if block.type == 'tool_use':
                blocks.append(dict(type='tool_use', name=block.name, input=block.input))
            elif block.type == 'text':
                blocks.append(dict(type='text', text=block.text))
        usage = getattr(response, 'usage', None)
        values = {name: getattr(usage, name, 0) or 0 for name in
                  ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')}
        data = dict(stop_reason=response.stop_reason, content=blocks, usage=values)
        self.store(key, dict(request_hash=key, status='received', run_id=self.run_id,
                             source_sha256=source_hash, request=payload, response=data))
        if usage is not None and all(hasattr(usage, name) for name in ('input_tokens', 'output_tokens')) and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in values.values()):
            actual = price.cost(values['input_tokens'], values['output_tokens'],
                                values['cache_creation_input_tokens'], values['cache_read_input_tokens'])
            call.update(charged_usd=str(actual), usage=values, status='received')
            self.halted = actual > reserve
            self.persist()
            if self.halted:
                # Do not permit another call if provider-reported usage exceeds our bound.
                raise BudgetError('Provider usage exceeded its reservation; run stopped for billing review')
        return key, data
