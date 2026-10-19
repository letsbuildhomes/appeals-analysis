"""The release's tables, laid out from the value types in a graph description.

Nothing here names a field. Each value type has one rule, applied to every
field and derived value in the order the graph lists them:

    one of         a text column whose values are the options ("not stated" is one of them)
    true or false  a boolean column
    count, integer an integer column; NULL means not stated
    text, name     a text column; NULL means not stated
    date           the date as stated, plus <name>_precision (day, month or year); NULL means not stated
    record         one column per key, named <name>_<key>; a record whose keys all share one
                   set of options (a yes/no set) becomes a long table instead
    or not stated  the inner value's columns, all NULL when the whole value is not stated

    list           a long table with one row per item, plus <name>_count on the wide table
                   (NULL when the list was never established, 0 when it is empty)
    counts by      a long table with one row per option that occurs

The wide table is `appeals`, one row per docket in scope. `all_dockets` adds
the dockets out of scope, with only the scope topic's columns, since those are
all the pipeline answers for them. The pipeline's scope value (its `in_scope`
derived value, true or false) is the fixed `all_dockets.in_scope` column
rather than a column of its own. Long tables hold appeals in scope only.

A type with no rule stops the build, so a new kind of value gets a rule here
once, not a mapping per field.
"""
from dataclasses import dataclass, field
import re

from appeals.graph.nodes import SCOPE
from appeals.graph.values import NOT_STATED, OUT_OF_SCOPE

# The tables every release has, whatever the graph, and their fixed columns. A node may not take these names.
APPEAL_COLUMNS = ['docket', 'documents', 'first_posted', 'last_posted']
ALL_DOCKET_COLUMNS = ['docket', 'in_scope', 'documents', 'first_posted', 'last_posted']
FIXED_TABLES = {'appeals', 'all_dockets', 'documents', 'all_documents', 'docket_links', 'all_docket_links'}
PRECISION = {'day': 'Stated to the day (YYYY-MM-DD).', 'month': 'Stated to the month (YYYY-MM).',
             'year': 'Stated to the year (YYYY).'}


class LayoutError(Exception):
    pass


@dataclass
class Column:
    name: str
    sql: str                 # DuckDB type
    node: str                # the field or derived value it comes from
    path: tuple = ()         # keys inside the node's value
    kind: str = ''           # the value type's name, or "precision", "count of items", "item", "option"
    options: dict | None = None
    meaning: str = ''

    def describe(self):
        """What a reader of the column needs: its name, SQL type, options and meaning."""
        d = {'name': self.name, 'type': self.sql}
        if self.options:
            d['options'] = self.options
        if self.meaning:
            d['meaning'] = self.meaning
        return d


@dataclass
class Table:
    """A long table for one node's multi-valued part: a yes/no set, a list or counts by option."""
    name: str
    form: str                # set | list | counts
    node: str
    path: tuple
    columns: list = field(default_factory=list)


@dataclass
class Layout:
    wide: list               # research columns on `appeals`, after APPEAL_COLUMNS
    tables: list             # long tables
    nodes: dict              # node id -> its description

    def scope(self):
        """The wide columns `all_dockets` also has: the scope topic's, answered for every docket."""
        return [c for c in self.wide if self.nodes[c.node]['topic'] == SCOPE]

    def columns(self):
        """Every research column, wide and long, with its table name."""
        out = [('appeals', c) for c in self.wide]
        for t in self.tables:
            out += [(t.name, c) for c in t.columns]
        return out


def identifier(text):
    return re.sub(r'\W+', '_', text).strip('_')


def is_set(d):
    """A record whose keys all share one set of options: a yes/no set asked item by item."""
    kinds = list(d['fields'].values())
    return (len(kinds) > 1 and all(k['type'] == 'one of' for k in kinds)
            and all(k['options'] == kinds[0]['options'] for k in kinds))


def layout(description):
    """The release's research tables for a graph description."""
    nodes = {n['id']: n for n in description['nodes'] if n['kind'] in ('field', 'derive')}
    wide, tables = [], []

    def scalar(node, d, path, name, nested):
        kind = d['type']
        if kind == 'one of':
            return [Column(name, 'VARCHAR', node, path, kind, d['options'])]
        if kind == 'true or false':
            return [Column(name, 'BOOLEAN', node, path, kind)]
        if kind in ('count', 'integer'):
            return [Column(name, 'BIGINT', node, path, kind)]
        if kind in ('text', 'name'):
            return [Column(name, 'VARCHAR', node, path, kind)]
        if kind == 'date':
            return [Column(name, 'VARCHAR', node, path, kind),
                    Column(f'{name}_precision', 'VARCHAR', node, path, 'precision', PRECISION)]
        if kind == 'or not stated':
            return scalar(node, d['value'], path, name, nested)
        if kind == 'record' and not (is_set(d) and not nested):
            return [c for key, v in d['fields'].items()
                    for c in scalar(node, v, path + (key,), f'{name}_{identifier(key)}', nested)]
        if nested:
            raise LayoutError(f'{node}: a {kind} inside a list has no place in a release table')
        if kind == 'record':                          # a yes/no set
            options = next(iter(d['fields'].values()))['options']
            tables.append(Table(name, 'set', node, path, [
                Column('item', 'VARCHAR', node, path, 'item', {k: '' for k in d['fields']}),
                Column('answer', 'VARCHAR', node, path, 'one of', options)]))
            return []
        if kind == 'list':
            item = d['item']
            columns = (scalar(node, item, (), 'value', True) if item['type'] != 'record'
                       else [c for key, v in item['fields'].items()
                             for c in scalar(node, v, (key,), identifier(key), True)])
            tables.append(Table(name, 'list', node, path, [Column('ordinal', 'BIGINT', node, (), 'ordinal'), *columns]))
            return [Column(f'{name}_count', 'BIGINT', node, path, 'count of items')]
        if kind == 'counts by':
            tables.append(Table(name, 'counts', node, path, [
                Column('option', 'VARCHAR', node, path, 'option', d['options']),
                Column('count', 'BIGINT', node, path, 'count')]))
            return []
        raise LayoutError(f'{node}: no release rule for value type {kind!r}')

    for node_id, node in nodes.items():
        if node_id != description.get('in_scope'):           # that one is all_dockets.in_scope
            wide += scalar(node_id, node['value_type'], (), identifier(node_id), False)

    names = [c.name for c in wide]
    clashes = {n for n in names if names.count(n) > 1} | (set(names) & set(ALL_DOCKET_COLUMNS))
    clashes |= {t.name for t in tables} & FIXED_TABLES
    if clashes:
        raise LayoutError(f'release names used twice: {sorted(clashes)}')
    return Layout(wide, tables, nodes)


# ---- values into rows ----------------------------------------------------------------

def _at(value, path):
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def precision(date):
    return {1: 'year', 2: 'month', 3: 'day'}[len(date.split('-'))]


def cell(column, value):
    """One column's value from a node's value: "not stated" becomes NULL except as an option. A record that is
    "not stated" as a whole is "not stated" in each of its columns."""
    v = NOT_STATED if value == NOT_STATED else _at(value, column.path)
    if v is None or v == OUT_OF_SCOPE:
        return None
    if column.kind == 'one of':
        return v
    if v == NOT_STATED:
        return None
    if column.kind == 'precision':
        return precision(v)
    if column.kind == 'count of items':
        return len(v) if isinstance(v, list) else None
    return v


def long_rows(table, docket, value):
    """A long table's rows for one docket's value of the table's node."""
    v = _at(value, table.path)
    if v is None or v in (NOT_STATED, OUT_OF_SCOPE):
        return []
    if table.form == 'set':
        return [(docket, item, answer) for item, answer in v.items()]
    if table.form == 'counts':
        return [(docket, option, count) for option, count in v.items()]
    return [(docket, n, *(cell(c, item) for c in table.columns[1:])) for n, item in enumerate(v, 1)]
