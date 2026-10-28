"""Definition leaf -> XBRL concept, proposed then validated.

Proposers, in order:
  1. claude-sonnet-5-5 (when ANTHROPIC_API_KEY is set): reads the leaf label and its
     clause text and picks from the concepts this company actually reports.
  2. A deterministic table of label patterns -> candidate us-gaap concepts.
Every proposal must pass the deterministic validator (USD, duration vs instant,
sign, availability across quarters). Anything that fails stays unmapped; the
engine then bounds it or refuses. A wrong mapping is worse than none.

Some contract terms are broader than any single XBRL line ("non-cash charges").
Those map as PARTIAL: the reported line is a floor for the term, never its value,
so the engine uses it for the low case only.
"""

import json
import os
import re
from dataclasses import dataclass, field

from engine.xbrl import CompanyFacts

MODEL = "claude-sonnet-5-5"
MIN_QUARTERS = 4


@dataclass
class Mapping:
    term_node: str
    concept: str | None
    kind: str  # "ttm" | "quarter" | "instant"
    confidence: float
    validated: bool
    partial: bool = False  # concept is a lower bound of the term, not the term
    sign: int = 1  # multiply reported values by this (e.g. a reported benefit stored negative)
    note: str | None = None
    proposer: str = "table"
    alternates: list[str] = field(default_factory=list)  # validated fallbacks for periods the primary concept lacks


# (pattern on label, candidates in preference order, instant?, partial?, sign)
# Candidates are tried in order; the first one that validates for this company wins.
TABLE: list[tuple[str, list[str], bool, bool, int]] = [
    (r"\bnet income\b|net earnings|\bnet (income )?\(?loss\)?", ["us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss", "us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic"], False, False, 1),
    (r"interest expense|interest charges|\binterest\b(?!.*income)", ["us-gaap:InterestExpense", "us-gaap:InterestAndDebtExpense", "us-gaap:InterestExpenseNonoperating", "us-gaap:InterestExpenseDebt", "us-gaap:InterestPaidNet", "us-gaap:InterestExpenseNet"], False, False, 1),
    (r"interest income", ["us-gaap:InvestmentIncomeInterest", "us-gaap:InterestIncomeOther", "us-gaap:InterestAndOtherIncome"], False, False, 1),
    (r"(provision for|income) tax|taxes (based on|on|measured by) income|\btaxes\b", ["us-gaap:IncomeTaxExpenseBenefit", "us-gaap:IncomeTaxesPaidNet"], False, False, 1),
    (r"depreciation and amortization|depreciation, depletion|d&a", ["us-gaap:DepreciationDepletionAndAmortization", "us-gaap:DepreciationAmortizationAndAccretionNet", "us-gaap:DepreciationAndAmortization",
        "us-gaap:Depreciation+us-gaap:OtherDepreciationAndAmortization", "us-gaap:Depreciation+us-gaap:AmortizationOfIntangibleAssets", "us-gaap:DepreciationDepletionAndAmortization+us-gaap:AmortizationOfIntangibleAssets"], False, False, 1),
    (r"^depreciation$|depreciation expense", ["us-gaap:Depreciation", "us-gaap:DepreciationNonproduction"], False, False, 1),
    (r"amortization( expense)?( of intangible)?", ["us-gaap:AmortizationOfIntangibleAssets"], False, False, 1),
    (r"stock[- ]based compensation|share[- ]based compensation|equity[- ]based compensation", ["us-gaap:ShareBasedCompensation", "us-gaap:AllocatedShareBasedCompensationExpense"], False, False, 1),
    (r"non-?cash (charges|expenses|losses)", ["us-gaap:ShareBasedCompensation"], False, True, 1),
    (r"restructuring", ["us-gaap:RestructuringCharges", "us-gaap:RestructuringCosts", "us-gaap:RestructuringSettlementAndImpairmentProvisions"], False, False, 1),
    (r"impairment", ["us-gaap:AssetImpairmentCharges", "us-gaap:GoodwillImpairmentLoss", "us-gaap:ImpairmentOfIntangibleAssetsExcludingGoodwill"], False, False, 1),
    (r"(loss|losses) on (the )?(extinguishment|early retirement) of debt", ["us-gaap:GainsLossesOnExtinguishmentOfDebt"], False, False, -1),
    (r"rent|lease expense", ["us-gaap:OperatingLeaseCost", "us-gaap:OperatingLeaseExpense"], False, False, 1),
    (r"capital expenditures?|capex", ["us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"], False, False, 1),
    (r"dividends?|restricted payments", ["us-gaap:PaymentsOfDividends", "us-gaap:PaymentsOfDividendsCommonStock"], False, False, 1),
    (r"principal payments|scheduled (principal )?(payments|repayments)", ["us-gaap:RepaymentsOfLongTermDebt"], False, False, 1),
    (r"(total |funded |consolidated )?(indebtedness|debt)\b|borrowed money", ["us-gaap:LongTermDebt", "us-gaap:DebtLongtermAndShorttermCombinedAmount", "us-gaap:LongTermDebtAndCapitalLeaseObligations", "us-gaap:DebtInstrumentCarryingAmount", "us-gaap:LongTermDebtNoncurrent"], True, False, 1),
    (r"unrestricted cash|cash and cash equivalents|\bcash\b", ["us-gaap:CashAndCashEquivalentsAtCarryingValue", "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"], True, False, 1),
    (r"(total )?revenues?|net sales", ["us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap:SalesRevenueNet"], False, False, 1),
    (r"operating income", ["us-gaap:OperatingIncomeLoss"], False, False, 1),
    (r"(tangible )?net worth|stockholders.? equity|shareholders.? equity", ["us-gaap:StockholdersEquity", "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], True, False, 1),
]

# Addbacks that are judgment calls under the contract; no public line measures them.
UNSOURCEABLE = re.compile(r"synerg|cost savings|run[- ]rate|pro forma|extraordinary|unusual|non-?recurring|one-?time|transaction (costs|expenses)|fees and expenses|other (non-?cash )?(items|adjustments)", re.I)


def is_instant_label(label: str) -> bool:
    label = re.sub(r"non-?cash", "", label, flags=re.I)
    return bool(re.search(r"indebtedness|debt|borrow|cash|liquidity|availability|net worth|equity|assets|liabilit", label, re.I))


def validate(cf: CompanyFacts, concept: str, kind: str) -> tuple[bool, str | None]:
    """Deterministic checks. Returns (ok, reason)."""
    if not cf.has(concept):
        return False, f"{concept} not reported in USD by this company"
    inst = cf.is_instant(concept)
    if kind == "instant" and not inst:
        return False, f"{concept} is a duration concept but the term is a balance"
    if kind != "instant" and inst:
        return False, f"{concept} is an instant concept but the term is a flow"
    s = cf.series(concept, kind)
    if len(s) < MIN_QUARTERS:
        return False, f"{concept} has only {len(s)} usable {kind} periods"
    vals = [v.value for v in s.values()]
    neg = sum(v < 0 for v in vals) / len(vals)
    signed_ok = re.search(r"NetIncome|ProfitLoss|IncomeTax|OperatingIncome|GainsLosses|InterestExpenseNet|StockholdersEquity", concept)
    if neg > 0.5 and not signed_ok:
        return False, f"{concept} is negative in {neg:.0%} of periods; sign convention unclear"
    return True, None


def table_map(cf: CompanyFacts, term_node: str, label: str, kind: str) -> Mapping:
    if UNSOURCEABLE.search(label):
        return Mapping(term_node, None, kind, 0.0, False, note="contract-specific adjustment with no public XBRL line")
    for pattern, cands, instant, partial, sign in TABLE:
        if not re.search(pattern, label, re.I):
            continue
        k = "instant" if instant else kind
        reasons, good = [], []
        for i, c in enumerate(cands):
            ok, why = validate(cf, c, k)
            if ok:
                good.append((i, c))
            else:
                reasons.append(why)
        if good:
            i, c = good[0]
            conf = (0.6 if partial else 0.9) - 0.1 * i
            note = "partial proxy: reported line is a floor for this term" if partial else None
            return Mapping(term_node, c, k, round(conf, 2), True, partial, sign, note, alternates=[g for _, g in good[1:]])
        return Mapping(term_node, None, k, 0.0, False, note="; ".join(r for r in reasons if r))
    return Mapping(term_node, None, kind, 0.0, False, note="no XBRL concept pattern for this label")


def _available(cf: CompanyFacts, kind: str, limit: int = 400) -> list[str]:
    out = []
    for c, fs in cf.facts.items():
        inst = sum(f.start is None for f in fs) > len(fs) / 2
        if (kind == "instant") == inst and len(fs) >= MIN_QUARTERS:
            out.append(c)
    return sorted(out)[:limit]


PROMPT = """You map one term from a loan agreement's financial definitions to the single XBRL concept that measures it in this company's SEC filings.

Term label: {label}
Clause text: {clause}
Required period type: {kind}

Concepts this company reports (choose ONLY from these, or null):
{concepts}

Rules:
- Pick the concept whose economic meaning equals the term. If the term is broader than any concept (e.g. "non-cash charges" vs share-based compensation), set partial=true.
- If no concept fits, return concept=null. Do not stretch.
- confidence is your probability that the mapping is correct (0 to 1)."""

SCHEMA = {
    "type": "object",
    "properties": {
        "concept": {"type": ["string", "null"]},
        "partial": {"type": "boolean"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["concept", "partial", "confidence", "reason"],
    "additionalProperties": False,
}


def llm_map(cf: CompanyFacts, term_node: str, label: str, clause: str, kind: str, client=None) -> Mapping | None:
    if not os.environ.get("ANTHROPIC_API_KEY") and client is None:
        return None
    import anthropic

    client = client or anthropic.Anthropic()
    concepts = _available(cf, kind)
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": PROMPT.format(label=label, clause=clause[:2000], kind=kind, concepts="\n".join(concepts))}],
        )
    except anthropic.APIError as e:
        return Mapping(term_node, None, kind, 0.0, False, note=f"LLM mapping failed: {type(e).__name__}", proposer="llm")
    if resp.stop_reason != "end_turn":
        return None
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        return None
    c = out.get("concept")
    if not c:
        return Mapping(term_node, None, kind, 0.0, False, note=f"LLM: no concept fits ({out.get('reason', '')})", proposer="llm")
    if c not in concepts:
        return Mapping(term_node, None, kind, 0.0, False, note=f"LLM proposed {c}, not among this company's concepts", proposer="llm")
    ok, why = validate(cf, c, kind)
    if not ok:
        return Mapping(term_node, None, kind, 0.0, False, note=f"LLM proposed {c}; validator rejected: {why}", proposer="llm")
    partial = bool(out.get("partial"))
    return Mapping(term_node, c, kind, round(min(max(float(out.get("confidence", 0)), 0), 1), 2), True, partial,
                   note=("partial proxy: " if partial else "") + out.get("reason", "")[:300], proposer="llm")


def map_leaf(cf: CompanyFacts, term_node: str, label: str, clause: str, flow_kind: str, client=None) -> Mapping:
    """flow_kind is the covenant's test period for flows ("ttm" or "quarter")."""
    kind = "instant" if is_instant_label(label) else flow_kind
    table = table_map(cf, term_node, label, kind)
    if UNSOURCEABLE.search(label):
        return table
    llm = llm_map(cf, term_node, label, clause, kind, client)
    if llm and llm.validated:
        # agreement between proposers raises confidence; disagreement is noted
        llm.alternates = [c for c in ([table.concept] if table.validated else []) + table.alternates if c and c != llm.concept]
        llm.sign = table.sign if table.concept == llm.concept else llm.sign
        if table.validated and table.concept == llm.concept:
            llm.confidence = max(llm.confidence, table.confidence)
            llm.note = (llm.note or "") + " [table agrees]"
        elif table.validated:
            llm.note = (llm.note or "") + f" [table proposed {table.concept}]"
        return llm
    if llm and table.validated:
        table.note = (table.note or "") + f" [LLM: {llm.note}]"
    return table
