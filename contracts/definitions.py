"""Closed, reachable DAG normalization, with conservative leaf checks."""

import math
import re

from shared.schema import Covenant, TermNode
from contracts.segment import defined_terms, visible_text


class DefinitionError(ValueError):
    pass


def normalize(terms: list[TermNode], covenants: list[Covenant],
              source_texts: list[str] = ()) -> list[TermNode]:
    nodes = {}
    for node in terms:
        if node.id in nodes:
            raise DefinitionError(f'duplicate term id: {node.id}')
        nodes[node.id] = node
    definitions = {}
    for text in source_texts:
        definitions.update(defined_terms(text))
    state = {}
    order = []

    def visit(key):
        if key not in nodes:
            raise DefinitionError(f'missing term: {key}')
        if state.get(key) == 1:
            raise DefinitionError(f'cycle at term: {key}')
        if state.get(key) == 2:
            return
        state[key] = 1
        node = nodes[key]
        children = node.children
        if len(children) != len(set(children)):
            raise DefinitionError(f'duplicate operands: {key}')
        if node.op == 'leaf':
            if children or node.cap:
                raise DefinitionError(f'leaf has operands: {key}')
            body = definitions.get(node.label.casefold(), '')
            cited = visible_text(node.span.text).casefold()
            # A defined term may still be an atomic GAAP item, as in the fixture.
            # Any named dependency or calculation in its definition prevents that shortcut.
            for name in definitions:
                if name != node.label.casefold() and re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', body, re.I):
                    raise DefinitionError(f'unexpanded defined term in leaf {key}: {name}')
            if re.search(r'\b(?:plus|minus|sum of|less the|exclud(?:e|es|ing)|add(?:ing)? back|deduct(?:ing|ed)?)\b', cited):
                raise DefinitionError(f'non-atomic leaf: {key}')
            if re.search(r'\b(?:as defined|meaning (?:given|assigned)|pro forma)\b', cited):
                raise DefinitionError(f'unresolved leaf: {key}')
        else:
            if not children or (node.op in {'subtract', 'ratio'} and len(children) != 2):
                raise DefinitionError(f'invalid arity: {key}')
            if node.op in {'cap', 'floor'}:
                if len(children) != 1 or not node.cap:
                    raise DefinitionError(f'invalid cap/floor: {key}')
                cap = node.cap
                if cap.get('kind') == 'pct_of' and node.op == 'cap':
                    amount = cap.get('pct')
                    if set(cap) != {'kind', 'of', 'pct'} or not isinstance(cap['of'], str):
                        raise DefinitionError(f'invalid percentage cap: {key}')
                    visit(cap['of'])
                elif cap.get('kind') == 'abs':
                    amount = cap.get('usd')
                    if set(cap) != {'kind', 'usd'}:
                        raise DefinitionError(f'invalid absolute bound: {key}')
                else:
                    raise DefinitionError(f'unsupported cap/floor: {key}')
                if isinstance(amount, bool) or not isinstance(amount, (float, int)) or not math.isfinite(amount) or amount < 0:
                    raise DefinitionError(f'invalid bound amount: {key}')
            elif node.cap is not None:
                raise DefinitionError(f'cap on arithmetic node: {key}')
        for child in children:
            visit(child)
        state[key] = 2
        order.append(node)

    for covenant in covenants:
        visit(covenant.numerator_term)
        if covenant.denominator_term:
            visit(covenant.denominator_term)
    # Deliberately prune unreachable nodes rather than exposing unused definitions to Dat.
    return order
