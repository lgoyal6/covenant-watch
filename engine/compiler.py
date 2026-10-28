"""Definition trees -> executable interval graphs.

Every node evaluates to an interval [lo, hi]. A sourced leaf is a point. An
unsourced addback is [0, +inf), tightened by any cap above it (low case: the
addback is zero; high case: it hits its cap). A partial leaf (reported line is
a floor for the term) is [value, +inf). Required leaves (the base of a sum,
the debt in a leverage ratio) cannot be bounded; missing them refuses the quarter.

Ops, applied in contract order (children first, caps after their `of` node):
  sum       sum of children
  subtract  first child minus the rest
  ratio     first child / second child
  cap       min(sum of children, cap) where cap is pct_of another node or abs USD
  floor     max(sum of children, floor) where floor defaults to 0
  leaf      a sourced value
"""

import math
from dataclasses import dataclass, field

from shared.schema import TermNode

INF = math.inf
Interval = tuple[float, float]


class CompileError(ValueError):
    pass


@dataclass
class LeafValue:
    value: float | None  # None = unsourced
    partial: bool = False


@dataclass
class Graph:
    nodes: dict[str, TermNode]
    order: list[str]  # topological, dependencies first
    required: set[str] = field(default_factory=set)  # leaves that cannot be bounded

    def leaves(self, root: str) -> list[str]:
        seen, out = set(), []

        def walk(n):
            if n in seen:
                return
            seen.add(n)
            t = self.nodes[n]
            if t.op == "leaf":
                out.append(n)
            for ch in t.children:
                walk(ch)
            if t.cap and t.cap.get("kind") == "pct_of":
                walk(t.cap["of"])

        walk(root)
        return out


def compile_terms(terms: list[TermNode], roots: list[str]) -> Graph:
    nodes = {t.id: t for t in terms}
    for r in roots:
        if r not in nodes:
            raise CompileError(f"covenant term {r} is not defined")
    order: list[str] = []
    state: dict[str, int] = {}  # 1 visiting, 2 done

    def deps(t: TermNode) -> list[str]:
        d = list(t.children)
        if t.cap and t.cap.get("kind") == "pct_of":
            d.append(t.cap["of"])
        return d

    def visit(n: str, path: list[str]):
        if n not in nodes:
            raise CompileError(f"{path[-1] if path else '?'} references undefined term {n}")
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            raise CompileError("definition cycle: " + " -> ".join([*path, n]))
        state[n] = 1
        t = nodes[n]
        if t.op == "leaf" and t.children:
            raise CompileError(f"leaf {n} has children")
        if t.op in ("sum", "subtract", "cap", "floor") and not t.children:
            raise CompileError(f"{t.op} node {n} has no children")
        if t.op == "ratio" and len(t.children) != 2:
            raise CompileError(f"ratio node {n} needs exactly 2 children")
        if t.op == "cap" and not t.cap:
            raise CompileError(f"cap node {n} has no cap")
        for d in deps(t):
            visit(d, [*path, n])
        state[n] = 2
        order.append(n)

    for r in roots:
        visit(r, [])

    # Required leaves: a covenant term that is itself a leaf, and the first child of
    # every sum/subtract chain (the base the adjustments are made to), followed down.
    required: set[str] = set()

    def base(n: str):
        t = nodes[n]
        if t.op == "leaf":
            required.add(n)
        elif t.op in ("sum", "subtract", "floor") and t.children:
            base(t.children[0])
        elif t.op == "ratio":
            for ch in t.children:
                base(ch)

    for r in roots:
        base(r)
    return Graph(nodes, order, required)


def _add(a: Interval, b: Interval) -> Interval:
    return (a[0] + b[0], a[1] + b[1])


def _sub(a: Interval, b: Interval) -> Interval:
    return (a[0] - b[1], a[1] - b[0])


def divide(n: Interval, d: Interval) -> Interval | None:
    """Interval division; None when the denominator can be zero or negative."""
    if d[0] <= 0:
        return None
    cands = [x / y for x in n for y in d if not (math.isinf(x) and math.isinf(y))]
    if math.isinf(d[1]):
        cands.append(0.0)
    cands = [c for c in cands if not math.isnan(c)]
    return (min(cands), max(cands))


def evaluate(g: Graph, leaves: dict[str, LeafValue]) -> tuple[dict[str, Interval], list[str]]:
    """Evaluate every node. Returns intervals and the leaves with no source."""
    val: dict[str, Interval] = {}
    missing: list[str] = []
    for n in g.order:
        t = g.nodes[n]
        if t.op == "leaf":
            lv = leaves.get(n, LeafValue(None))
            if lv.value is None:
                missing.append(n)
                val[n] = (0.0, INF)
            elif lv.partial:
                val[n] = (lv.value, INF)
            else:
                val[n] = (lv.value, lv.value)
        elif t.op == "sum":
            acc = (0.0, 0.0)
            for ch in t.children:
                acc = _add(acc, val[ch])
            val[n] = acc
        elif t.op == "subtract":
            acc = val[t.children[0]]
            for ch in t.children[1:]:
                acc = _sub(acc, val[ch])
            val[n] = acc
        elif t.op == "ratio":
            r = divide(val[t.children[0]], val[t.children[1]])
            val[n] = r if r else (-INF, INF)
        elif t.op in ("cap", "floor"):
            acc = (0.0, 0.0)
            for ch in t.children:
                acc = _add(acc, val[ch])
            spec = t.cap or {}
            if spec.get("kind") == "pct_of":
                of = val[spec["of"]]
                pct = float(spec["pct"])
                bound = (max(0.0, pct * of[0]), max(0.0, pct * of[1]))  # a cap on negative EBITDA allows nothing
            elif spec.get("kind") == "abs":
                bound = (float(spec["usd"]), float(spec["usd"]))
            else:
                bound = (0.0, 0.0)  # floor with no spec floors at zero
            if t.op == "cap":
                val[n] = (min(acc[0], bound[0]), min(acc[1], bound[1]))
            else:
                val[n] = (max(acc[0], bound[0]), max(acc[1], bound[1]))
    return val, missing
