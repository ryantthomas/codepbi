# MetricFlow metric -> DAX measure expression, for metrics read from dbt's compiled semantic manifest.
#
# Simple metrics over one column, ratio and derived metrics render mechanically; anything else (a SQL `expr`
# that is not a bare column, a `filter`, cumulative or conversion metrics) returns None, and the metric must carry
# hand-written DAX after "DAX:" in its description instead.

import re

AGG_DAX = {"sum": "SUM", "count_distinct": "DISTINCTCOUNT", "count": "COUNT", "average": "AVERAGE",
           "min": "MIN", "max": "MAX"}


def render(metric: dict, table_of: dict, display_of: dict, label_of: dict) -> str | None:
    """table_of: semantic model name -> TMDL table; display_of: (TMDL table, source column) -> column name;
    label_of: metric name -> measure name."""
    params = metric.get("type_params") or {}
    kind = metric.get("type")
    if metric.get("filter"):
        return None
    if kind == "simple":
        agg = params.get("metric_aggregation_params") or {}
        table, expr = table_of.get(agg.get("semantic_model")), params.get("expr")
        if not table or agg.get("agg") not in AGG_DAX or not expr or not re.fullmatch(r"\w+", expr):
            return None
        column = display_of.get((table, expr))
        return f"{AGG_DAX[agg['agg']]}('{table}'[{column}])" if column else None
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
