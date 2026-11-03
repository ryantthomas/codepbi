# MetricFlow metric -> DAX measure expression, for metrics read from dbt's compiled semantic manifest.
#
# Simple metrics over one column (or `expr: 1`, a row count), optionally filtered by equality / IN / NOT IN
# conditions on dimensions joined with AND, plus ratio and derived metrics, render mechanically. A filter becomes
# KEEPFILTERS, so it narrows the report's own filters as MetricFlow does instead of replacing them. Anything else
# (another SQL `expr`, other filter shapes, cumulative or conversion metrics) returns None, and the metric must
# carry hand-written DAX after "DAX:" in its description instead.

import re

AGG_DAX = {"sum": "SUM", "count_distinct": "DISTINCTCOUNT", "count": "COUNT", "average": "AVERAGE",
           "min": "MIN", "max": "MAX"}


_CONDITION = re.compile(r"\{\{\s*Dimension\('(\w+)'\)\s*\}\}\s*(=|NOT IN|IN)\s*(.+)", re.IGNORECASE)


def _dax_value(text):
    text = text.strip()
    return '"' + text[1:-1].replace('"', '""') + '"' if text.startswith("'") and text.endswith("'") else text


def filter_conditions(where: str, column_of: dict) -> list[str] | None:
    """A MetricFlow where-filter ("{{ Dimension('entity__dim') }} = 'x' AND ...") as DAX conditions, or None.
    column_of: 'entity__dim' -> 'Table'[Column]."""
    out = []
    for part in re.split(r"\s+AND\s+", where.strip(), flags=re.IGNORECASE):
        m = _CONDITION.fullmatch(part.strip())
        if not m or m[1] not in column_of:
            return None
        column, op, value = column_of[m[1]], m[2].upper(), m[3].strip()
        if op == "=":
            out.append(f"{column} = {_dax_value(value)}")
            continue
        if not (value.startswith("(") and value.endswith(")")):
            return None
        items = ", ".join(_dax_value(v) for v in re.findall(r"'[^']*'|[^,\s]+", value[1:-1]))
        out.append(("NOT " if op == "NOT IN" else "") + f"{column} IN {{{items}}}")
    return out


def render(metric: dict, table_of: dict, display_of: dict, label_of: dict, column_of: dict = None) -> str | None:
    """table_of: semantic model name -> TMDL table; display_of: (TMDL table, source column) -> column name;
    label_of: metric name -> measure name; column_of: 'entity__dimension' -> 'Table'[Column] for filters."""
    params = metric.get("type_params") or {}
    kind = metric.get("type")
    wheres = [w.get("where_sql_template", "") for w in (metric.get("filter") or {}).get("where_filters") or []]
    if wheres and kind != "simple":
        return None
    if kind == "simple":
        agg = params.get("metric_aggregation_params") or {}
        table, expr = table_of.get(agg.get("semantic_model")), str(params.get("expr") or "")
        if not table or agg.get("agg") not in AGG_DAX:
            return None
        if expr == "1" and agg["agg"] == "sum":
            base = f"COUNTROWS('{table}')"
        elif re.fullmatch(r"\w+", expr) and display_of.get((table, expr)):
            base = f"{AGG_DAX[agg['agg']]}('{table}'[{display_of[(table, expr)]}])"
        else:
            return None
        conditions = []
        for where in wheres:
            found = filter_conditions(where, column_of or {})
            if found is None:
                return None
            conditions += found
        return f"CALCULATE({base}, " + ", ".join(f"KEEPFILTERS({c})" for c in conditions) + ")" if conditions else base
    if kind == "ratio":
        num, den = params.get("numerator") or {}, params.get("denominator") or {}
        if num.get("filter") or den.get("filter") or not num.get("name") or not den.get("name"):
            return None
        return f"DIVIDE([{label_of[num['name']]}], [{label_of[den['name']]}])"
    if kind == "derived":
        expr = params.get("expr") or ""
        inputs = params.get("metrics") or []
        if any(i.get("filter") or i.get("offset_window") or i.get("offset_to_grain") for i in inputs):
            return None
        names = {(i.get("alias") or i["name"]): i["name"] for i in inputs}
        return re.sub(r"\b(\w+)\b", lambda m: f"[{label_of[names[m[1]]]}]" if m[1] in names else m[1], expr)
    return None


def owner(metric: dict, owner_of: dict) -> str | None:
    """The semantic model a metric's measure belongs to: its own (simple) or its first input's."""
    params = metric.get("type_params") or {}
    if metric.get("type") == "simple":
        return (params.get("metric_aggregation_params") or {}).get("semantic_model")
    first = (params.get("numerator") or {}).get("name") or next(
        (i["name"] for i in params.get("metrics") or []), None)
    return owner_of.get(first)
