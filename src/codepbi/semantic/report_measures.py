# Write one metric group's measures into a thin report as report-level measures.
#
# A metric in a dbt group belongs to that group's report, not the shared model: it is
# written to the report's PBIR definition/reportExtensions.json. Measures written here
# carry a "codepbi" annotation; report measures added by hand are left alone.

import json
import re
from pathlib import Path

from .config import TmdlProjectConfig
from .sync_measures import load_by_table

SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
          "reportExtension/1.0.0/schema.json")
MARK = {"name": "codepbi", "value": "synced"}


def build(by_table: dict, existing: dict, model_of: dict = None) -> dict:
    """by_table (load_by_table's shape) + the current reportExtensions.json -> the new one. model_of: model
    measure name -> table. Each measure lists the measures its DAX uses, which Power BI needs to resolve
    one report measure inside another."""
    entities = {e["name"]: [m for m in e.get("measures") or [] if MARK not in (m.get("annotations") or [])]
                for e in existing.get("entities") or []}
    for table, entries in by_table.items():
        entities.setdefault(table, []).extend({
            "name": e["name"],
            "dataType": "Integer" if e.get("agg") in ("count", "count_distinct") else "Double",
            "expression": e["dax"],
            "formatString": e["formatString"],
            "displayFolder": e["displayFolder"],
            "description": e["description"],
            "annotations": [MARK],
        } for e in entries)
    name = existing.get("name", "extension")
    ext_of = {m["name"]: t for t, ms in entities.items() for m in ms}
    for ms in entities.values():
        for m in ms:
            if MARK not in (m.get("annotations") or []):
                continue
            refs = []
            for used in dict.fromkeys(re.findall(r"\[([^\]]+)\]", m["expression"])):
                if used in ext_of:
                    refs.append({"schema": name, "entity": ext_of[used], "name": used})
                elif used in (model_of or {}):
                    refs.append({"entity": model_of[used], "name": used})
            if refs:
                m["references"] = {"measures": refs}
    return {
        "$schema": SCHEMA,
        "name": name,
        "entities": [{"name": t, "measures": ms} for t, ms in sorted(entities.items()) if ms],
    }


def sync(config: TmdlProjectConfig, report_definition_dir: Path, group: str):
    """Write the metrics of dbt group `group` into the report at report_definition_dir (its PBIR
    `definition` folder) as report-level measures."""
    path = Path(report_definition_dir) / "reportExtensions.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    by_table = load_by_table(config, {group})
    model_of = {e["name"]: t for t, es in load_by_table(config).items() for e in es}
    new = build(by_table, existing, model_of)
    if new != existing:
        path.write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
    print(f"Report measures: {sum(len(v) for v in by_table.values())} from group {group} in {path}")
