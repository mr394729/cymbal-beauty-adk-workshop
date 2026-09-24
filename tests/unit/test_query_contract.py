"""Task labels retain identities, cardinality and scope without model lookups."""
import sqlite3
from types import SimpleNamespace

import pytest
from google.adk.tools import FunctionTool

from agents.cymbal_store_ops.tools import report_delivery, store_query
from agents.cymbal_store_ops.tools.operations_tools import concurrent_read
from tests.conftest import FakeToolContext


def context(role='store_manager', user='U-M014'):
    return FakeToolContext({'user:role': role, 'user:user_id': user, 'user:store_id': 'S-014'})


@pytest.mark.parametrize('function,empty', [
    (store_query.query_store_data, False), (store_query.describe_store_data, True),
    (report_delivery.query_store_data, False), (report_delivery.describe_store_data, True),
    (report_delivery.deliver_store_report, False),
])
def test_adk_publishes_exact_resource_vocabulary_through_concurrent_wrapper(function, empty):
    declaration = FunctionTool(concurrent_read(function))._get_declaration()
    schema = declaration.model_dump(mode='json', exclude_none=True)['parameters_json_schema']
    resource = schema['properties']['resource']
    assert resource['type'] == 'string'
    assert set(resource['enum']) == set(store_query.RESOURCES) | ({''} if empty else set())
    assert 'associates' not in resource['enum']


def test_unknown_resource_and_denied_resource_are_distinct(fake_backend):
    missing = store_query.describe_store_data('associates', tool_context=context())
    assert missing['code'] == 'invalid_resource' and 'roster' in missing['available_resources']
    denied = store_query.describe_store_data('loss', tool_context=context('associate', 'A-1004'))
    assert denied['code'] == 'forbidden'
    assert fake_backend.calls == []


def changed_task_dimensions(backend):
    task = next(t for t in backend.tasks if t['store_id'] == 'S-014' and t.get('assignee_id') and t.get('product_id'))
    person = next(a for a in backend.associates if a['store_id'] == 'S-014' and a['associate_id'] == task['assignee_id'])
    product = next(p for p in backend.products if p['product_id'] == task['product_id'])
    person['first_name'] = 'Changed local owner'
    product['name'] = 'Changed catalog label'
    backend.associates.append(dict(person, store_id='S-099', first_name='Other store person'))
    backend.associates.append(dict(person))
    backend.products.append(dict(product))
    base = dict(task)
    backend.tasks = [base,
        dict(base, task_id='T-MISSING', assignee_id='A-NO-RECORD', product_id='P-NO-RECORD'),
        dict(base, task_id='T-NULL', assignee_id=None, product_id=None),
        dict(base, task_id='T-OTHER', store_id='S-099')]
    return base, person, product


def test_changed_labels_preserve_missing_ids_and_duplicate_dimension_counts(fake_backend):
    task, _, _ = changed_task_dimensions(fake_backend)
    result = store_query.query_store_data('tasks', tool_context=context())
    assert result['total_matching'] == 3
    rows = {r['task_id']: r for r in result['rows']}
    assert rows[task['task_id']]['assignee_name'] == 'Changed local owner'
    assert rows[task['task_id']]['product_name'] == 'Changed catalog label'
    assert rows['T-MISSING']['assignee_id'] == 'A-NO-RECORD'
    assert rows['T-MISSING']['product_id'] == 'P-NO-RECORD'
    assert rows['T-MISSING']['assignee_name'] is rows['T-MISSING']['product_name'] is None
    assert rows['T-NULL']['assignee_id'] is rows['T-NULL']['product_id'] is None
    counts = store_query.query_store_data('tasks', measures=[{'operation': 'count'}], tool_context=context())
    assert counts['rows'] == [{'count_records': 3}]


def test_conflicting_labels_do_not_choose_an_arbitrary_name_or_change_identity(fake_backend):
    task, person, product = changed_task_dimensions(fake_backend)
    fake_backend.associates.append(dict(person, first_name='Conflicting owner label'))
    fake_backend.products.append(dict(product, name='Conflicting product label'))
    result = store_query.query_store_data('tasks', filters=[{'field': 'task_id', 'value': task['task_id']}], tool_context=context())
    row = result['rows'][0]
    assert row['assignee_name'] is row['product_name'] is None
    assert row['assignee_id'] == task['assignee_id'] and row['product_id'] == task['product_id']
    assert result['total_matching'] == 1


def test_joined_labels_preserve_associate_self_scope_and_report_count(fake_backend):
    task, _, _ = changed_task_dimensions(fake_backend)
    own = context('associate', task['assignee_id'])
    response = store_query.query_store_data('tasks', delivery='report', tool_context=own)
    assert response['row_count'] == response['total_matching'] == 1
    row = own.state['ui:report']['rows'][0]
    assert row['task_id'] == task['task_id'] and row['assignee_name'] == 'Changed local owner'
    assert store_query.query_store_data('tasks', store_id='S-099', tool_context=own)['code'] == 'forbidden'
    filtered = store_query.query_store_data('tasks', filters=[{'field': 'assignee_name', 'value': 'Other store person'}], tool_context=own)
    assert filtered['rows'] == []


@pytest.mark.parametrize('conflicting', [False, True])
def test_bigquery_source_matches_fake_relational_results_on_changed_dimensions(fake_backend, conflicting):
    _, person, product = changed_task_dimensions(fake_backend)
    if conflicting:
        fake_backend.associates.append(dict(person, first_name='Conflicting owner label'))
        fake_backend.products.append(dict(product, name='Conflicting product label'))
    spec = store_query.RESOURCES['tasks']
    source = store_query._bq_source(SimpleNamespace(_t=lambda name: name), spec)
    assert 'r.store_id = a.store_id AND r.assignee_id = a.associate_id' in source
    assert 'WHERE store_id = @scope_store' in source
    assert 'S-014' not in source
    # Execute the generated BigQuery task relation over real changed rows using
    # SQLite's equivalent IF function. No mocked query answers or live calls.
    with sqlite3.connect(':memory:') as connection:
        connection.row_factory = sqlite3.Row
        connection.create_function('IF', 3, lambda condition, yes, no: yes if condition else no)
        tables = [
            ('store_tasks', ['store_id', *[f for f in spec.fields if f not in {'assignee_name', 'product_name'}]], fake_backend.tasks),
            ('associates', ['store_id', 'associate_id', 'first_name'], fake_backend.associates),
            ('products', ['product_id', 'name'], fake_backend.products),
        ]
        for table, columns, rows in tables:
            connection.execute(f'CREATE TABLE {table} ({", ".join(columns)})')
            connection.executemany(f'INSERT INTO {table} VALUES ({", ".join("?" for _ in columns)})',
                                   ([r.get(c) for c in columns] for r in rows))
        fields = ['task_id', 'assignee_id', 'assignee_name', 'product_id', 'product_name']
        bq_rows = [dict(r) for r in connection.execute(f'SELECT {", ".join(fields)} FROM ({source}) ORDER BY task_id', {'scope_store': 'S-014'})]
    actual = store_query.query_store_data('tasks', fields=fields, order_by=[{'field': 'task_id'}], tool_context=context())
    assert actual['rows'] == bq_rows
    assert actual['total_matching'] == len(bq_rows) == 3
