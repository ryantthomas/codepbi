# Generic helpers for reading a dbt model's own compiled SELECT list, used by
# check_schema_vs_sql. Requires `dbt compile` (or `dbt run`) to have already
# produced target/manifest.json and target/compiled/... .

import json
from pathlib import Path

from sqlglot import exp, parse_one


def sql_exprs(sql: str, dialect: str = "tsql") -> dict:
    """A model's own SELECT list: {output column: raw SQL expression text}."""
    stmt = parse_one(sql, dialect=dialect)
    cte_map = {
        cte.alias.lower(): {
            s.alias_or_name.lower(): str(s.this if isinstance(s, exp.Alias) else s)
            for s in cte.this.selects if s.alias_or_name
        }
        for cte in stmt.find_all(exp.CTE)
    }
    result = {}
    for s in stmt.selects:
        alias = s.alias_or_name
        expr = s.this if isinstance(s, exp.Alias) else s
        if isinstance(expr, exp.Column) and not expr.table:
            result[alias] = next(
                (c[expr.name.lower()] for c in cte_map.values() if expr.name.lower() in c),
                str(expr),
            )
        else:
            result[alias] = str(expr)
    return result


def load_model_data(target_dir: Path) -> dict:
    """dbt model name -> {dbt_db, dbt_schema, sql, compiled_path, compiled_exists}.

    The compiled path comes from the manifest node's own `path` (relative to
    model-paths), not from the bare model name -- dbt writes to
    compiled/.../models/<subfolder>/<name>.sql, so a name-only lookup misses the
    moment models live in folders.

    The raw_code fallback is kept for models that genuinely have no compiled
    output, but it is Jinja, not SQL: sqlglot parses it into garbage rather than
    failing, which yields silently wrong results. compiled_exists lets callers
    refuse instead.
    """
    manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
    compiled_dir = target_dir / "compiled"
    result = {}
    for node in manifest["nodes"].values():
        if node.get("resource_type") != "model":
            continue
        p = compiled_dir / node.get("path", f"{node['name']}.sql")
        exists = p.exists()
        result[node["name"]] = {
            "dbt_db": node.get("database", ""),
            "dbt_schema": node.get("schema", ""),
            "sql": p.read_text(encoding="utf-8") if exists else node.get("raw_code", ""),
            "compiled_path": p,
            "compiled_exists": exists,
        }
    return result
