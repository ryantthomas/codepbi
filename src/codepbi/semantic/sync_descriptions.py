# Sync schema YAML -> TMDL columns, descriptions, folders, hidden flags, format,
# summarization. Inserts columns that don't exist yet. Descriptions are tagged
# [synced] so hand-written ones (untagged) are never overwritten.
#
# TMDL is read and written through TOM (see tom_utils) -- never regex.

import uuid

from . import tom_utils
from .config import TmdlProjectConfig
from .schema_loader import DATATYPE_MAP, TOM_TO_YAML, aggregate_function, load_schema
from .validate_tmdl import validate_tmdl

SYNCED_TAG = "[synced]"


def _new_column(info):
    """Build a TOM DataColumn from a schema YAML column entry."""
    from Microsoft.AnalysisServices.Tabular import AggregateFunction, Annotation, DataColumn, DataType

    data_type = info["data_type"]
    if data_type not in DATATYPE_MAP:
        raise SystemExit(
            f"Unknown data_type {data_type!r} for column {info['source']!r}. "
            f"Must be one of: {sorted(DATATYPE_MAP)}"
        )
    spec = DATATYPE_MAP[data_type]

    col = DataColumn()
    col.Name = info["display"]
    col.DataType = getattr(DataType, data_type[0].upper() + data_type[1:])
    col.SourceColumn = info["source"]
    col.SourceProviderType = spec["provider"]
    fmt = info["format_string"] or spec["format"]
    if fmt:
        col.FormatString = fmt
    if info["folder"]:
        col.DisplayFolder = info["folder"]
    if info["hidden"]:
        col.IsHidden = True
    if info["desc"]:
        col.Description = info["desc"]
    col.LineageTag = str(uuid.uuid4())
    col.SummarizeBy = (
        aggregate_function(info["summarize_by"], info["source"])
        if info["summarize_by"]
        else getattr(AggregateFunction, "None")
    )

    ann = Annotation()
    ann.Name = "SummarizationSetBy"
    ann.Value = "Automatic"
    col.Annotations.Add(ann)
    return col


def sync(config: TmdlProjectConfig):
    """Sync schema YAML -> TMDL: display names, descriptions, folders, hidden flags.

    Inserts columns that don't exist yet. Applies schema YAML first, then validates
    the result -- validating first would deadlock, since the fix for a TMDL error
    often lives in schema YAML and can only land by syncing.
    """
    wanted = load_schema(config)
    db, model = tom_utils.load_model(config)

    inserts, renames, updates = [], [], 0
    type_drift = []

    for pbi_table, spec in wanted.items():
        if not model.Tables.ContainsName(pbi_table):
            continue
        table = model.Tables[pbi_table]
        by_source = {c.SourceColumn: c for c in table.Columns if c.SourceColumn}

        for info in spec["columns"]:
            col = by_source.get(info["source"])

            # A column's type is only ever set at creation, so a declaration that
            # disagrees with TMDL is silently inert. This also catches Power BI
            # Desktop retyping a column behind your back (it does this sometimes
            # when a view's inferred type looks different on refresh).
            if col is not None and info["data_type"]:
                actual = TOM_TO_YAML.get(str(col.DataType))
                if actual and actual != info["data_type"]:
                    type_drift.append(
                        f"{pbi_table}.{info['display']} ({info['source']}): "
                        f"schema YAML says {info['data_type']}, TMDL has {actual}"
                    )

            if col is None:
                if not info["data_type"]:
                    raise SystemExit(
                        f"{pbi_table}: new column {info['source']!r} missing "
                        f"meta.data_type in schema YAML (required for auto-insert)"
                    )
                table.Columns.Add(_new_column(info))
                inserts.append(f"{pbi_table}.{info['source']}")
                continue

            if col.Name != info["display"]:
                renames.append(f"{pbi_table}: {col.Name!r} -> {info['display']!r}")
                col.Name = info["display"]

            # Only manage descriptions this sync owns -- leave untagged ones alone.
            current = col.Description or ""
            if info["desc"] and (not current or SYNCED_TAG in current):
                updates += tom_utils.set_if_changed(col, "Description", f"{SYNCED_TAG} {info['desc']}")

            updates += tom_utils.set_if_changed(col, "IsHidden", info["hidden"], bool)

            if info["folder"]:
                updates += tom_utils.set_if_changed(col, "DisplayFolder", info["folder"])

            # Only touch these where schema YAML declares them -- applying a default to
            # every column would strip the format off columns that already carry one.
            if info["format_string"]:
                updates += tom_utils.set_if_changed(col, "FormatString", info["format_string"])

            if info["summarize_by"]:
                want = aggregate_function(info["summarize_by"], info["source"])
                updates += tom_utils.set_if_changed(col, "SummarizeBy", want, lambda v: v)

    tom_utils.save_model(config, db)

    print(f"TMDL: {len(inserts)} new column(s) inserted.")
    for i in inserts:
        print(f"  inserted {i}")
    print(f"TMDL: {updates} property update(s).")
    if renames:
        print(f"TMDL: {len(renames)} column display-name rename(s):")
        for r in renames:
            print(f"  {r}")
        print("Review DAX/relationship/role refs -- sync only renames the column header.")

    if type_drift:
        print(f"\nERROR: {len(type_drift)} column data_type mismatch(es):")
        for d in type_drift:
            print(f"  {d}")
        print("\nA column type is only applied when the column is first created, so one "
              "of the two is wrong and neither will change on its own.")
        print("Check what the underlying SQL actually returns, then fix whichever side "
              "disagrees with it. Only dataType is checked -- sourceProviderType is left "
              "to Power BI Desktop, which legitimately refines it (e.g. datetime2 -> date).")
        raise SystemExit(1)

    validate_tmdl(config)
