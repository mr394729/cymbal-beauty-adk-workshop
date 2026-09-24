"""Evaluation-only missing-feed overlay and route-independent pickup evidence checks."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from functools import cache
from unittest.mock import patch

from google.adk.evaluation.eval_case import get_all_tool_calls, get_all_tool_responses

from agents.cymbal_store_ops import fixtures as F
from agents.cymbal_store_ops.tools.backends.bigquery import BigQueryBackend
from eval.metrics import _result


@contextmanager
def missing_pending_feed(fake_backend=None):
    """Filter read relations only; restore on every exit and never change stored data."""
    original = BigQueryBackend._t

    def table(backend, name):
        relation = original(backend, name)
        if name == 'bopis_orders':
            return f"(SELECT * FROM {relation} WHERE status IS DISTINCT FROM 'pending')"
        return relation

    with ExitStack() as stack:
        stack.enter_context(patch.object(BigQueryBackend, '_t', table))
        if fake_backend is not None:
            stack.enter_context(patch.object(fake_backend, 'orders', [row for row in fake_backend.orders
                                                                    if row['status'] != 'pending']))
        yield


@cache
def expected_totals():
    from data.generate import generate_all

    orders = [row for row in generate_all()['bopis_orders']
              if row['store_id'] == F.HERO_STORE_ID and row['status'] == 'pending']
    return len(orders), sum(row['qty'] for row in orders)


def pickup_counts_invariant(eval_metric, actual_invocations, expected_invocations=None, conversation_scenario=None):
    """Require matched scoped counts/units from native or composable reads.

    The semantic evaluator checks the answer itself. A correct guessed answer
    without actual source evidence cannot pass this invariant.
    """
    expected_count, expected_units = expected_totals()
    scores = []
    for index, actual in enumerate(actual_invocations):
        counts, units = [], []
        calls = list(get_all_tool_calls(actual.intermediate_data) or [])
        responses = list(get_all_tool_responses(actual.intermediate_data) or [])
        for call in calls:
            args = call.args or {}
            if args.get('store_id', F.HERO_STORE_ID) not in ('', F.HERO_STORE_ID):
                continue
            for response in responses:
                data = response.response
                if (not call.id or response.id != call.id or response.name != call.name
                        or data.get('status') != 'SUCCESS' or data.get('error_details')
                        or data.get('store_id', F.HERO_STORE_ID) != F.HERO_STORE_ID):
                    continue
                name = call.name.removeprefix('store_mcp_')
                rows = data.get('rows') or []
                if name == 'get_bopis_demand' and not args.get('product_id') and data.get('by_product_complete'):
                    counts.append(data.get('pending_count'))
                    units.append(data.get('units_total'))
                elif name == 'get_pickup_workload':
                    for row in rows:
                        counts.append(row.get('pending_order_count'))
                        units.append(row.get('pending_unit_count'))
                elif name == 'query_store_data' and args.get('resource') == 'orders':
                    filters = args.get('filters') or []
                    if any(f.get('field') != 'status' or f.get('operator', 'eq') != 'eq'
                           or f.get('value') != 'pending' for f in filters):
                        continue
                    pending_filter = bool(filters)
                    groups = args.get('group_by') or []
                    if groups not in ([], ['status']):
                        continue
                    measures = args.get('measures') or []
                    if measures:
                        for row in rows:
                            if not pending_filter and row.get('status') != 'pending':
                                continue
                            for measure in measures:
                                operation, field = measure.get('operation'), measure.get('field') or ''
                                alias = f'{operation}_{field or "records"}'
                                if operation == 'count' and field in ('', 'order_id'):
                                    counts.append(row.get(alias))
                                elif operation == 'sum' and field == 'qty':
                                    units.append(row.get(alias))
                    elif (data.get('offset', 0) == 0 and not data.get('has_more')
                          and data.get('total_matching') == len(rows)
                          and all('order_id' in row and 'status' in row and type(row.get('qty')) is int for row in rows)):
                        pending = [row for row in rows if row['status'] == 'pending']
                        counts.append(len(pending))
                        units.append(sum(row['qty'] for row in pending))
        ok = bool(counts and units) and all(type(v) in (int, float) and v == expected_count for v in counts)
        ok = ok and all(type(v) in (int, float) and v == expected_units for v in units)
        expected = expected_invocations[index] if expected_invocations and index < len(expected_invocations) else None
        scores.append((actual, expected, float(ok)))
    return _result(scores)
