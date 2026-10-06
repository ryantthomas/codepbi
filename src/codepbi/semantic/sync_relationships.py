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
                foreigns.append((e["name"], table_name, col_friendly, bool(meta.get("both_directions"))))

    rels = []
    for name, from_table, from_col, both_dir in foreigns:
        if name not in primaries:
            continue  # validate() already flags this
        to_table, to_col = primaries[name]
        row = {"from": from_table, "from_column": from_col, "to": to_table, "to_column": to_col}
        if both_dir:
            row["both_directions"] = True
        rels.append(row)
    return rels


def _key(r):
    return (r["from"], r["from_column"], r["to"], r["to_column"])


def export(config: TmdlProjectConfig):
    """Dump the current TMDL relationships into each table's semantic-model YAML,
    replacing only its `entities:` block -- dimensions/measures/description untouched.
    Use this to seed the files the first time, or to recover if TMDL and the YAML
    ever disagree about what 'current' means."""
    schema = load_schema(config)
    table_to_model = {name: spec["model"] for name, spec in schema.items()}

    _, model = tom_utils.load_model(config)

    entities_by_table = {}  # table -> {entity_name: entity dict}
    for r in model.Relationships:
        to_table, to_col = r.ToTable.Name, r.ToColumn.Name
        from_table, from_col = r.FromTable.Name, r.FromColumn.Name
        name = _entity_name(to_col)

        entities_by_table.setdefault(to_table, {})[name] = {
            "name": name, "type": "primary", "expr": to_col,
        }
        foreign_entity = {"name": name, "type": "foreign", "expr": from_col}
        if str(r.CrossFilteringBehavior) != "OneDirection":
            foreign_entity["config"] = {"meta": {"both_directions": True}}
        entities_by_table.setdefault(from_table, {})[name] = foreign_entity

    written = 0
    for table_name, entities in entities_by_table.items():
        dbt_model = table_to_model.get(table_name)
        if not dbt_model:
            print(f'  WARNING: "{table_name}" has TMDL relationships but no schema YAML entry, skipping')
            continue
        out_file = config.semantic_models_dir / f"{re.sub(r'[^A-Za-z0-9]+', '_', table_name).strip('_').lower()}.yml"
        if not out_file.exists():
            print(f'  WARNING: no semantic model file for "{table_name}" at {out_file.name}, skipping')
            continue
        with open(out_file, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        ordered = sorted(entities.values(), key=lambda e: e["name"])
        doc["semantic_models"][0]["entities"] = ordered
        text = yaml.safe_dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True, width=200)
        out_file.write_text(text, encoding="utf-8")
        written += 1

    print(f"Exported {len(model.Relationships)} relationship(s) across {written} file(s)")


def sync(config: TmdlProjectConfig):
    """Apply semantic-model YAML entities to TMDL: add/remove/update so TMDL matches."""
    wanted_rows = load(config)
    errors = validate(config)
    if errors:
        for e in errors:
            print(f"RELATIONSHIPS: {e}")
        raise SystemExit(f"semantic-model YAML relationship validation failed: {len(errors)} issue(s)")

    wanted = {_key(r): r for r in wanted_rows}

    # load_model() triggers tom_utils._ensure_loaded(), which adds the CLR
    # references -- this import must come after, or it fails with
    # ModuleNotFoundError: No module named 'Microsoft'.
    db, model = tom_utils.load_model(config)
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
        if k in existing:
            r = existing[k]
            if r.CrossFilteringBehavior != want_cf:
                r.CrossFilteringBehavior = want_cf
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
        rel.IsActive = True
        model.Relationships.Add(rel)
        added += 1

    tom_utils.save_model(config, db)
    print(f"RELATIONSHIPS: {removed} removed, {added} added, {updated} updated.")
