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
from .schema_loader import iter_semantic_models
from .tom_utils import load_model, save_model, set_if_changed

_DAX_RE = re.compile(r"DAX:\s*(.*)$", re.DOTALL)


def _split_description(description):
    """'prose DAX: expr' -> (prose, expr), both stripped; no marker -> (description, '')."""
    description = description or ""
    m = _DAX_RE.search(description)
    if not m:
        return description.strip(), ""
    return description[:m.start()].strip(), m.group(1).strip()


def load_by_table(config: TmdlProjectConfig) -> dict:
    """semantic-model YAML -> {tmdl_table_name: [{name, dax, formatString, displayFolder}]}."""
    by_table = {}
    for _path, _doc, sm, table_name in iter_semantic_models(config):
        for m in sm.get("measures") or []:
            meta = ((m.get("config") or {}).get("meta")) or {}
            _, dax = _split_description(m.get("description"))
            by_table.setdefault(table_name, []).append({
                "name": m.get("label") or m["name"],
                "dax": dax,
                "formatString": meta.get("format_string", ""),
                "displayFolder": meta.get("displayFolder", "Calculations"),
            })
    return by_table


def export_measures(entries: list[dict], measures: list[dict]) -> list[dict]:
    """Merge TMDL measures ({name, dax, formatString, displayFolder}) into a table's YAML
    `measures:` entries, matched by label or name. A match keeps its name, agg and prose and
    gets the DAX, format_string and displayFolder updated; a new measure gets a snake_case
    name from its label and goes last; an entry with no TMDL measure is dropped."""
    by_name = {m["name"]: m for m in measures}
    pairs = []
    for e in entries:
        key = e.get("label") if e.get("label") in by_name else e["name"]
        if key in by_name:
            pairs.append((dict(e), by_name.pop(key)))
    for m in by_name.values():
        name = re.sub(r"[^A-Za-z0-9]+", "_", m["name"]).strip("_").lower()
        pairs.append(({"name": name, "agg": "sum", "label": m["name"]}, m))

    out = []
    for entry, m in pairs:
        prose, _ = _split_description(entry.get("description"))
        entry["description"] = f"{prose} DAX: {m['dax']}" if prose else f"DAX: {m['dax']}"
        config = dict(entry.get("config") or {})
        meta = dict(config.get("meta") or {})
        if m["formatString"] or "format_string" in meta:
            meta["format_string"] = m["formatString"]
        meta["displayFolder"] = m["displayFolder"]
        entry["config"] = {**config, "meta": meta}
        out.append(entry)
    return out


def export(config: TmdlProjectConfig):
    """Write the current TMDL measures back into the semantic-model YAML `measures:` blocks
    of this model's tables -- entities/dimensions/description untouched."""
    _, model = load_model(config)
    files, sms = {}, {}
    for path, doc, sm, table_name in iter_semantic_models(config):
        files[path] = doc
        sms[table_name] = sm

    total = 0
    for table in model.Tables:
        measures = [{
            "name": m.Name,
            "dax": (m.Expression or "").strip(),
            "formatString": m.FormatString or "",
            "displayFolder": m.DisplayFolder or "Calculations",
        } for m in table.Measures]
        sm = sms.get(table.Name)
        if sm is None:
            if measures:
                print(f'  WARNING: "{table.Name}" has TMDL measures but no semantic-model YAML, '
                      f"skipping")
            continue
        merged = export_measures(sm.get("measures") or [], measures)
        if merged or "measures" in sm:
            sm["measures"] = merged
        total += len(measures)

    written = 0
    for path, doc in files.items():
        if doc != yaml.safe_load(path.read_text(encoding="utf-8")):
            text = yaml.safe_dump(doc, default_flow_style=False, sort_keys=False,
                                  allow_unicode=True, width=200)
            path.write_text(text, encoding="utf-8")
            written += 1
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
