# Apply semantic-model YAML `measures:` -> TMDL, and export back the other way.
#
# semantic-model YAML is the measure authority -- DAX lives in each measure's
# `description` (after the trailing "DAX: " marker), format/folder in
# `config.meta`. Only touches measures -- columns, partitions, relationships,
# entities and dimensions untouched. Idempotent: rerun with same config = same
# output.

import re

import yaml

from .config import TmdlProjectConfig
from .schema_loader import iter_semantic_models, load_schema
from .tom_utils import load_model, save_model, set_if_changed

_DAX_RE = re.compile(r"DAX:\s*(.*)$", re.DOTALL)


def _dax_from_description(description):
    m = _DAX_RE.search(description or "")
    return m.group(1).strip() if m else ""


def load_by_table(config: TmdlProjectConfig) -> dict:
    """semantic-model YAML -> {tmdl_table_name: [{name, dax, formatString, displayFolder}]}."""
    by_table = {}
    for _path, _doc, sm, table_name in iter_semantic_models(config):
        for m in sm.get("measures") or []:
            meta = ((m.get("config") or {}).get("meta")) or {}
            by_table.setdefault(table_name, []).append({
                "name": m.get("label") or m["name"],
                "dax": _dax_from_description(m.get("description", "")),
                "formatString": meta.get("format_string", ""),
                "displayFolder": meta.get("displayFolder", "Calculations"),
            })
    return by_table


def export(config: TmdlProjectConfig):
    """Export TMDL measures back into each table's semantic-model YAML, replacing
    only its `measures:` block -- entities/dimensions/description untouched."""
    table_to_model = {name: spec["model"] for name, spec in load_schema(config).items()}

    db, model = load_model(config)
    by_table = {}
    for table in model.Tables:
        entries = []
        for m in table.Measures:
            entries.append({
                "name": m.Name,
                "agg": "sum",
                "label": m.Name,
                "description": f"DAX: {m.Expression.strip()}",
                "config": {"meta": {
                    "format_string": m.FormatString or "",
                    "displayFolder": m.DisplayFolder or "Calculations",
                }},
            })
        if entries:
            entries.sort(key=lambda e: e["name"])
            by_table[table.Name] = entries

    written = 0
    for table_name, measures in by_table.items():
        dbt_model = table_to_model.get(table_name)
        if not dbt_model:
            print(f'  WARNING: "{table_name}" has TMDL measures but no schema YAML entry, skipping')
            continue
        out_file = config.semantic_models_dir / f"{re.sub(r'[^A-Za-z0-9]+', '_', table_name).strip('_').lower()}.yml"
        if not out_file.exists():
            print(f'  WARNING: no semantic model file for "{table_name}" at {out_file.name}, skipping')
            continue
        with open(out_file, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        doc["semantic_models"][0]["measures"] = measures
        text = yaml.safe_dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True, width=200)
        out_file.write_text(text, encoding="utf-8")
        written += 1

    total = sum(len(v) for v in by_table.values())
    print(f"Exported {total} measure(s) across {written} file(s)")


def sync(config: TmdlProjectConfig):
    """Apply semantic-model YAML measures -> TMDL via TOM."""
    by_table = load_by_table(config)
    total = sum(len(v) for v in by_table.values())
    if not total:
        print("No measures found in semantic-model YAML")
        return

    db, model = load_model(config)
    from Microsoft.AnalysisServices.Tabular import Measure

    updated = created = 0

    for table_name, entries in by_table.items():
        table = model.Tables.Find(table_name)
        if table is None:
            print(f'  WARNING: table "{table_name}" not found, skipping its measures')
            continue

        for entry in entries:
            measure_name = entry["name"]
            dax = entry["dax"]
            fmt = entry.get("formatString", "")
            folder = entry.get("displayFolder", "Calculations")

            existing = table.Measures.Find(measure_name)
            if existing:
                changed = set_if_changed(existing, "Expression", dax.strip(), lambda v: (v or "").strip())
                changed |= set_if_changed(existing, "FormatString", fmt)
                changed |= set_if_changed(existing, "DisplayFolder", folder)
                if changed:
                    updated += 1
            else:
                m = Measure()
                m.Name = measure_name
                m.Expression = dax
                m.FormatString = fmt
                m.DisplayFolder = folder
                table.Measures.Add(m)
                created += 1

    save_model(config, db)
    print(f"Measures synced: {created} created, {updated} updated ({total} total in config)")
