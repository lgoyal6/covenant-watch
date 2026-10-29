"""Engine-level refusals. Each one says what could not be computed and why."""

from shared.schema import Refusal


def no_xbrl(cik: str, detail: str) -> Refusal:
    return Refusal(scope="company", ref=cik, reason="missing_filing", detail=f"No usable XBRL financial data: {detail}")


def no_usd(cik: str) -> Refusal:
    return Refusal(scope="company", ref=cik, reason="currency_or_units", detail="Company reports no USD-denominated XBRL facts.")


def bad_definition(cov_id: str, detail: str) -> Refusal:
    return Refusal(scope="covenant", ref=cov_id, reason="ambiguous_definition", detail=f"Definition tree cannot be compiled: {detail}")


def unsupported(cov_id: str, detail: str) -> Refusal:
    return Refusal(scope="covenant", ref=cov_id, reason="other", detail=detail)


def unmapped(cov_id: str, term_id: str, label: str, note: str | None, required: bool) -> Refusal:
    effect = ("required term: every quarter of this covenant is refused" if required
              else "bounded instead of computed: low case 0, high case its cap (or unbounded if uncapped)")
    return Refusal(scope="covenant", ref=cov_id, reason="pro_forma_adjustment" if note and "contract-specific" in note else "unmapped_term",
                   detail=f'"{label}" ({term_id}) has no validated XBRL source ({note or "no match"}); {effect}.')


def unfiled(period_end: str, detail: str) -> Refusal:
    return Refusal(scope="quarter", ref=period_end, reason="missing_filing", detail=detail)
