# Apply semantic-model YAML `entities:` -> TMDL relationships, and export back
# the other way.
#
# semantic-model YAML `entities:` blocks are the source of truth for joins --
# the same role schema YAML plays for columns and each measure's own block plays
# for measures. A join is declared the way dbt/MetricFlow natively does it: a
# `primary` entity in the "one" side's file and a `foreign` entity of the same
# name in the "many" side's file. TMDL is the build artifact: Power BI still
# reads relationships.tmdl, this module is what keeps it in sync.
#
# Cardinality isn't declared here: every relationship this module creates is
# Many -> One. If your model needs other cardinalities, extend `sync()` with an
# explicit cardinality field rather than assuming.
#
# inactive (config.meta.inactive on the foreign entity): a relationship whose
# two tables already connect via a different active path. Analysis Services
# refuses to save a second *active* path between the same two tables (a real
# engine-level rejection, not something this module checks) -- inactive lets
# the join exist for DAX measures to opt into via USERELATIONSHIP, without
# fighting the existing default path.

import re
import uuid

import yaml

from . import tom_utils
from .config import TmdlProjectConfig
from .schema_loader import iter_semantic_models, load_schema


def _entity_name(column_friendly):
    name = re.sub(r"[^A-Za-z0-9]+", "_", column_friendly).strip("_").lower()
    if name.endswith("_id"):
        name = name[:-3]
    return name or "id"


def validate(config: TmdlProjectConfig) -> list[str]:
    """Every entity's expr must be a real column source on its table, every
    'foreign' entity must have a matching same-named 'primary' entity somewhere.

    Returns a list of error strings; empty means clean. Called both standalone
    (sync() refuses to touch TOM if this fails) and from validate_tmdl.
    """
    schema = load_schema(config)
    source_by_table = {t: {c["source"] for c in spec["columns"]} for t, spec in schema.items()}

    errors = []
    primaries = {}  # entity name -> table
    foreigns = []  # (entity name, table)

    for path, _doc, sm, table_name in iter_semantic_models(config):
        valid_sources = source_by_table.get(table_name, set())
        for e in sm.get("entities") or []:
            if e.get("expr") not in valid_sources:
                errors.append(
                    f"{path.name} entity {e['name']!r}: expr {e.get('expr')!r} "
                    f"is not a column on {table_name!r}"
                )
            if e["type"] == "primary":
                if e["name"] in primaries:
                    errors.append(
                        f"duplicate primary entity {e['name']!r}: "
                        f"{primaries[e['name']]!r} and {table_name!r}"
                    )
                primaries[e["name"]] = table_name
            elif e["type"] == "foreign":
                foreigns.append((e["name"], table_name))

    for name, table_name in foreigns:
        if name not in primaries:
            errors.append(
                f"foreign entity {name!r} on {table_name!r} has no matching "
                f"primary entity anywhere in the model"
            )
    return errors


def load(config: TmdlProjectConfig) -> list[dict]:
    """Reconstruct joins by pairing same-named primary/foreign entities across
    semantic-model YAML -> list of {from, from_column, to, to_column, both_directions?}."""
    schema = load_schema(config)
    display_by_source = {t: {c["source"]: c["display"] for c in spec["columns"]} for t, spec in schema.items()}

    primaries = {}  # entity name -> (table, column_friendly)
    foreigns = []  # (entity name, table, column_friendly, both_directions)

    for _path, _doc, sm, table_name in iter_semantic_models(config):
        col_lookup = display_by_source.get(table_name, {})
        for e in sm.get("entities") or []:
            col_friendly = col_lookup.get(e["expr"], e["expr"])
            if e["type"] == "primary":
                primaries[e["name"]] = (table_name, col_friendly)
            elif e["type"] == "foreign":
                meta = ((e.get("config") or {}).get("meta")) or {}
                foreigns.append((e["name"], table_name, col_friendly,
                                  bool(meta.get("both_directions")), bool(meta.get("inactive"))))

    rels = []
    for name, from_table, from_col, both_dir, inactive in foreigns:
        if name not in primaries:
            continue  # validate() already flags this
        to_table, to_col = primaries[name]
        row = {"from": from_table, "from_column": from_col, "to": to_table, "to_column": to_col}
        if both_dir:
            row["both_directions"] = True
        if inactive:
            row["inactive"] = True
        rels.append(row)
    return rels


def in_model(rels: list[dict], tables: set[str]) -> tuple[list[dict], int]:
    """Keep relationships whose two tables are both in this model.

    One dbt project can feed several semantic models, each holding a subset of
    its tables, so a relationship to a table another model owns is skipped, not
    an error -- the same way sync_measures skips measures of a missing table.
    """
    kept = [r for r in rels if r["from"] in tables and r["to"] in tables]
    return kept, len(rels) - len(kept)


def _key(r):
    return (r["from"], r["from_column"], r["to"], r["to_column"])


def _set_flags(entity, both_directions, inactive):
    config = dict(entity.get("config") or {})
    meta = {k: v for k, v in (config.get("meta") or {}).items()
            if k not in ("both_directions", "inactive")}
    if both_directions:
        meta["both_directions"] = True
    if inactive:
        meta["inactive"] = True
    config.pop("meta", None)
    if meta:
        config["meta"] = meta
    entity.pop("config", None)
    if config:
        entity["config"] = config


def export_entities(sms: dict, rels: list[tuple], tables: set[str]) -> int:
    """Rewrite each in-model table's `entities:` (sms: {table: semantic model dict}, edited in
    place) to match rels: (from_table, from_source, to_table, to_source, both_directions,
    inactive), all source column names. Primary entities are kept; a foreign entity is replaced
    only if its primary sits in this model, so joins another model owns survive. Existing
    names, descriptions and order are kept. Returns the number of relationships skipped
    because a table has no semantic-model YAML."""
    primary_table = {e["name"]: t for t, sm in sms.items()
                     for e in sm.get("entities") or [] if e["type"] == "primary"}
    current = {t: list(sm.get("entities") or []) for t, sm in sms.items() if t in tables}
    foreigns = {t: [] for t in current}

    skipped = 0
    for from_table, from_src, to_table, to_src, both_directions, inactive in rels:
        if from_table not in current or to_table not in current:
            skipped += 1
            continue
        primary = next((e for e in current[to_table]
                        if e["type"] == "primary" and e["expr"] == to_src), None)
        if primary is None:
            primary = {"name": _entity_name(to_src), "type": "primary", "expr": to_src}
            current[to_table].append(primary)
        foreign = next((dict(e) for e in current[from_table] if e["type"] == "foreign"
                        and e["expr"] == from_src and e["name"] == primary["name"]),
                       {"name": primary["name"], "type": "foreign", "expr": from_src})
        _set_flags(foreign, both_directions, inactive)
        foreigns[from_table].append(foreign)

    for t, entities in current.items():
        out = []
        for e in entities:
            if e["type"] != "foreign" or primary_table.get(e["name"]) not in tables:
                out.append(e)
                continue
            match = next((f for f in foreigns[t]
                          if (f["name"], f["expr"]) == (e["name"], e["expr"])), None)
            if match:
                foreigns[t].remove(match)
                out.append(match)
        out += foreigns[t]
        if out:
            sms[t]["entities"] = out
        else:
            sms[t].pop("entities", None)
    return skipped


def export(config: TmdlProjectConfig):
    """Write the current TMDL relationships back into the semantic-model YAML `entities:`
    blocks of this model's tables -- dimensions/measures/description untouched. Use this to
    seed the files the first time, or to recover if TMDL and the YAML ever disagree."""
    _, model = tom_utils.load_model(config)

    def source(col):
        return getattr(col, "SourceColumn", None) or col.Name

    rels = [
        (r.FromTable.Name, source(r.FromColumn), r.ToTable.Name, source(r.ToColumn),
         str(r.CrossFilteringBehavior) != "OneDirection", not r.IsActive)
        for r in model.Relationships
    ]
    files, sms = {}, {}
    for path, doc, sm, table_name in iter_semantic_models(config):
        files[path] = doc
        sms[table_name] = sm
    skipped = export_entities(sms, rels, {t.Name for t in model.Tables})
    if skipped:
        print(f"RELATIONSHIPS: {skipped} skipped, a table has no semantic-model YAML.")

    written = 0
    for path, doc in files.items():
        if doc != yaml.safe_load(path.read_text(encoding="utf-8")):
            text = yaml.safe_dump(doc, default_flow_style=False, sort_keys=False,
                                  allow_unicode=True, width=200)
            path.write_text(text, encoding="utf-8")
            written += 1
    print(f"Exported {len(rels) - skipped} relationship(s) across {written} file(s)")


def sync(config: TmdlProjectConfig):
    """Apply semantic-model YAML entities to TMDL: add/remove/update so TMDL matches."""
    wanted_rows = load(config)
    errors = validate(config)
    if errors:
        for e in errors:
            print(f"RELATIONSHIPS: {e}")
        raise SystemExit(f"semantic-model YAML relationship validation failed: {len(errors)} issue(s)")

    # load_model() triggers tom_utils._ensure_loaded(), which adds the CLR
    # references -- this import must come after, or it fails with
    # ModuleNotFoundError: No module named 'Microsoft'.
    db, model = tom_utils.load_model(config)
    wanted_rows, skipped = in_model(wanted_rows, {t.Name for t in model.Tables})
    if skipped:
        print(f"RELATIONSHIPS: {skipped} skipped, a table is not in this model.")
    wanted = {_key(r): r for r in wanted_rows}
    from Microsoft.AnalysisServices.Tabular import (
        CrossFilteringBehavior, RelationshipEndCardinality, SingleColumnRelationship)

    existing = {}
    for r in model.Relationships:
        k = (r.FromTable.Name, r.FromColumn.Name, r.ToTable.Name, r.ToColumn.Name)
        existing[k] = r

    removed = added = updated = 0

    # Relationships out first -- same discipline as removing a column that one
    # still references, just applied to the relationship side.
    for k, r in list(existing.items()):
        if k not in wanted:
            model.Relationships.Remove(r)
            removed += 1

    for k, spec in wanted.items():
        want_cf = (CrossFilteringBehavior.BothDirections if spec.get("both_directions")
                   else CrossFilteringBehavior.OneDirection)
        want_active = not spec.get("inactive")
        if k in existing:
            r = existing[k]
            changed = False
            if r.CrossFilteringBehavior != want_cf:
                r.CrossFilteringBehavior = want_cf
                changed = True
            if r.IsActive != want_active:
                r.IsActive = want_active
                changed = True
            if changed:
                updated += 1
            continue

        from_table, from_col, to_table, to_col = k
        rel = SingleColumnRelationship()
        rel.Name = str(uuid.uuid4())
        rel.FromTable = model.Tables[from_table]
        rel.FromColumn = model.Tables[from_table].Columns[from_col]
        rel.ToTable = model.Tables[to_table]
        rel.ToColumn = model.Tables[to_table].Columns[to_col]
        rel.FromCardinality = RelationshipEndCardinality.Many
        rel.ToCardinality = RelationshipEndCardinality.One
        rel.CrossFilteringBehavior = want_cf
        rel.IsActive = want_active
        model.Relationships.Add(rel)
        added += 1

    tom_utils.save_model(config, db)
    print(f"RELATIONSHIPS: {removed} removed, {added} added, {updated} updated.")
