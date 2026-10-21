#!/usr/bin/env python3
"""Generate a migration-drift audit SQL script.

Parses every supabase/migrations/*.sql, extracts the schema objects each one
declares (tables, ALTER-added columns, indexes, functions, policies, types,
triggers, and graph_outbox CHECK-constraint operation values), and emits ONE
SQL query that returns only the objects MISSING from the target database — i.e.
the drift. Run the emitted SQL against prod (Supabase SQL editor or psql).

Parsing is regex-based and intentionally conservative: it favors objects that
are the usual drift risk (ALTER ADD COLUMN, CREATE INDEX/FUNCTION/POLICY/TYPE)
over re-deriving full CREATE TABLE column lists (covered by the table check).
"""
from __future__ import annotations

import re
from pathlib import Path

MIG_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
OUT = Path(__file__).resolve().parent / "_migration_audit.sql"

# (kind, ident-parts..., migration)
tables: list[tuple[str, str]] = []        # (qualified_name, migration)
columns: list[tuple[str, str, str]] = []  # (table, column, migration)
indexes: list[tuple[str, str]] = []       # (index_name, migration)
functions: list[tuple[str, str]] = []     # (func_name, migration)
policies: list[tuple[str, str, str]] = [] # (policy_name, table, migration)
types: list[tuple[str, str]] = []         # (type_name, migration)
triggers: list[tuple[str, str]] = []      # (trigger_name, migration)
gobx_ops: list[tuple[str, str]] = []      # (operation_value, migration)

RE_TABLE = re.compile(r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?\"?([a-zA-Z_][\w]*)\"?", re.I)
RE_ALTER = re.compile(r"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?:public\.)?\"?([a-zA-Z_][\w]*)\"?(.*?)(?=;)", re.I | re.S)
RE_ADDCOL = re.compile(r"\bADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?([a-zA-Z_][\w]*)\"?", re.I)
RE_INDEX = re.compile(r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?\"?([a-zA-Z_][\w]*)\"?", re.I)
RE_FUNC = re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?\"?([a-zA-Z_][\w]*)\"?", re.I)
RE_POLICY = re.compile(r'\bCREATE\s+POLICY\s+"?([^"\n]+?)"?\s+ON\s+(?:public\.)?"?([a-zA-Z_][\w]*)"?', re.I)
RE_TYPE = re.compile(r"\bCREATE\s+TYPE\s+(?:public\.)?\"?([a-zA-Z_][\w]*)\"?", re.I)
RE_TRIGGER = re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+\"?([a-zA-Z_][\w]*)\"?", re.I)
# graph_outbox operation CHECK: capture quoted operation literals inside a CHECK
# touching graph_outbox_operation_check / operation IN (...).
RE_GOBX_BLOCK = re.compile(r"graph_outbox_operation_check.*?CHECK\s*\((.*?)\)\s*(?:NOT\s+VALID)?\s*;", re.I | re.S)
RE_STRLIT = re.compile(r"'([a-z0-9_]+)'", re.I)
# DROP tracking — an object created by one migration and dropped by a later one
# is NOT expected to exist (e.g. an index superseded by a renamed replacement).
RE_DROP_INDEX = re.compile(r"\bDROP\s+INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+EXISTS\s+)?(?:public\.)?\"?([a-zA-Z_][\w]*)\"?", re.I)
RE_DROP_TABLE = re.compile(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?\"?([a-zA-Z_][\w]*)\"?", re.I)
_dropped_indexes: set[str] = set()
_dropped_tables: set[str] = set()


def strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return sql


for path in sorted(MIG_DIR.glob("*.sql")):
    mig = path.name
    raw = path.read_text(encoding="utf-8", errors="ignore")
    sql = strip_sql_comments(raw)

    for m in RE_TABLE.finditer(sql):
        tables.append((f"public.{m.group(1)}", mig))
    for atable, body in ((m.group(1), m.group(2)) for m in RE_ALTER.finditer(sql)):
        for col in RE_ADDCOL.finditer(body):
            columns.append((atable, col.group(1), mig))
    for m in RE_INDEX.finditer(sql):
        indexes.append((m.group(1), mig))
        _dropped_indexes.discard(m.group(1))  # re-created: expect it again
    for m in RE_DROP_INDEX.finditer(sql):
        _dropped_indexes.add(m.group(1))
    for m in RE_TABLE.finditer(sql):
        _dropped_tables.discard(m.group(1))
    for m in RE_DROP_TABLE.finditer(sql):
        _dropped_tables.add(m.group(1))
    for m in RE_FUNC.finditer(sql):
        functions.append((m.group(1), mig))
    for m in RE_POLICY.finditer(sql):
        policies.append((m.group(1).strip(), m.group(2), mig))
    for m in RE_TYPE.finditer(sql):
        types.append((m.group(1), mig))
    for m in RE_TRIGGER.finditer(sql):
        triggers.append((m.group(1), mig))
    for block in RE_GOBX_BLOCK.finditer(sql):
        for lit in RE_STRLIT.finditer(block.group(1)):
            gobx_ops.append((lit.group(1), mig))


# Exclude objects whose final action across all migrations was DROP.
indexes = [(n, m) for (n, m) in indexes if n not in _dropped_indexes]
tables = [(t, m) for (t, m) in tables if t.split(".")[-1] not in _dropped_tables]


def sql_lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def values(rows: list[tuple], n: int) -> str:
    seen = set()
    out = []
    for r in rows:
        key = tuple(r[:n])
        if key in seen:
            continue
        seen.add(key)
        out.append("(" + ",".join(sql_lit(str(x)) for x in r) + ")")
    return ",\n  ".join(out)


parts = []
_sections: list[tuple[list, str]] = []

if tables:
    parts.append(f"""-- MISSING TABLES
SELECT 'table' AS kind, t.ident AS object, t.migration
FROM (VALUES
  {values(tables, 2)}
) AS t(ident, migration)
WHERE to_regclass(t.ident) IS NULL""")

if columns:
    parts.append(f"""-- MISSING COLUMNS (ALTER ADD COLUMN)
SELECT 'column', c.tbl || '.' || c.col, c.migration
FROM (VALUES
  {values(columns, 3)}
) AS c(tbl, col, migration)
WHERE NOT EXISTS (
  SELECT 1 FROM information_schema.columns ic
  WHERE ic.table_schema='public' AND ic.table_name=c.tbl AND ic.column_name=c.col
)""")

if indexes:
    parts.append(f"""-- MISSING INDEXES
SELECT 'index', i.name, i.migration
FROM (VALUES
  {values(indexes, 2)}
) AS i(name, migration)
WHERE NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname=i.name)""")

if functions:
    parts.append(f"""-- MISSING FUNCTIONS
SELECT 'function', f.name, f.migration
FROM (VALUES
  {values(functions, 2)}
) AS f(name, migration)
WHERE NOT EXISTS (
  SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname=f.name
)""")

if policies:
    parts.append(f"""-- MISSING POLICIES (by name+table; a renamed policy shows as missing)
SELECT 'policy', p.name || ' ON ' || p.tbl, p.migration
FROM (VALUES
  {values(policies, 3)}
) AS p(name, tbl, migration)
WHERE NOT EXISTS (
  SELECT 1 FROM pg_policies pp
  WHERE pp.schemaname='public' AND pp.tablename=p.tbl AND pp.policyname=p.name
)""")

if types:
    parts.append(f"""-- MISSING TYPES
SELECT 'type', ty.name, ty.migration
FROM (VALUES
  {values(types, 2)}
) AS ty(name, migration)
WHERE NOT EXISTS (
  SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
  WHERE n.nspname='public' AND t.typname=ty.name
)""")

if triggers:
    parts.append(f"""-- MISSING TRIGGERS
SELECT 'trigger', tg.name, tg.migration
FROM (VALUES
  {values(triggers, 2)}
) AS tg(name, migration)
WHERE NOT EXISTS (SELECT 1 FROM pg_trigger WHERE NOT tgisinternal AND tgname=tg.name)""")

if gobx_ops:
    parts.append(f"""-- MISSING graph_outbox operation enum values (CHECK constraint drift)
SELECT 'gobx_op', g.op, g.migration
FROM (VALUES
  {values(gobx_ops, 2)}
) AS g(op, migration)
WHERE NOT EXISTS (
  SELECT 1 FROM pg_constraint c
  WHERE c.conname='graph_outbox_operation_check'
    AND pg_get_constraintdef(c.oid) LIKE '%''' || g.op || '''%'
)""")

audit = "\n\nUNION ALL\n\n".join(parts) + "\nORDER BY 1, 3, 2;\n"

header = (
    "-- Migration drift audit — objects declared in supabase/migrations/ that are\n"
    "-- MISSING from the target DB. Empty result = no drift. Run in Supabase SQL\n"
    "-- editor (prod project) or via psql. Generated by scripts/_gen_migration_audit.py\n\n"
)
OUT.write_text(header + audit, encoding="utf-8")

print(f"parsed {len(list(MIG_DIR.glob('*.sql')))} migrations")
print(
    f"objects: tables={len(set(t[:1] for t in tables))} "
    f"columns={len(set((c[0],c[1]) for c in columns))} "
    f"indexes={len(set(i[0] for i in indexes))} functions={len(set(f[0] for f in functions))} "
    f"policies={len(set((p[0],p[1]) for p in policies))} types={len(set(t[0] for t in types))} "
    f"triggers={len(set(t[0] for t in triggers))} gobx_ops={len(set(g[0] for g in gobx_ops))}"
)
print(f"wrote {OUT}")
