# Shared TOM (Tabular Object Model) utilities via pythonnet.
#
# Requires the Microsoft.AnalysisServices .NET DLLs (NuGet package
# Microsoft.AnalysisServices.NetCore.retail.amd64) at config.tom_lib_dir. Not
# redistributed by this package -- obtain them yourself and point tom_lib_dir
# at the folder you placed them in.

import re

from .config import TmdlProjectConfig

_DLLS = [
    "Microsoft.AnalysisServices.Core.dll",
    "Microsoft.AnalysisServices.Tabular.dll",
    "Microsoft.AnalysisServices.Tabular.Json.dll",
]

_loaded = False


def _ensure_loaded(config: TmdlProjectConfig) -> None:
    global _loaded
    if _loaded:
        return

    import clr

    for name in _DLLS:
        dll = config.tom_lib_dir / name
        if dll.exists():
            clr.AddReference(str(dll))

    try:
        from Microsoft.AnalysisServices.Tabular import TmdlSerializer  # noqa: F401
    except ImportError:
        raise SystemExit(
            f"TOM DLLs not found in {config.tom_lib_dir}. Install the "
            f"Microsoft.AnalysisServices.NetCore.retail.amd64 NuGet package and point "
            f"tom_lib_dir at its lib folder."
        )

    _loaded = True


def load_model(config: TmdlProjectConfig):
    _ensure_loaded(config)
    from Microsoft.AnalysisServices.Tabular import TmdlSerializer

    db = TmdlSerializer.DeserializeDatabaseFromFolder(str(config.semantic_model_definition_dir))
    return db, db.Model


def save_model(config: TmdlProjectConfig, db) -> None:
    _ensure_loaded(config)
    from Microsoft.AnalysisServices.Tabular import TmdlSerializer

    TmdlSerializer.SerializeDatabaseToFolder(db, str(config.semantic_model_definition_dir))


def set_if_changed(obj, attr, want, normalize=lambda v: (v or "")):
    """Set obj.attr to want if it differs (after normalize); return whether it changed.

    Shared shape behind every sync's per-property TOM update: compare, set, flag.
    normalize handles the None-vs-'' and .strip() variations between properties
    (an Expression is stripped, FormatString/DisplayFolder are not).
    """
    if normalize(getattr(obj, attr)) != want:
        setattr(obj, attr, want)
        return True
    return False


def pbi_table_of(meta: dict) -> str | None:
    """Derive the PBI table name from schema YAML meta {entity, grain}."""
    if not meta:
        return None
    entity = meta.get("entity")
    if not entity:
        return None
    grain = meta.get("grain")
    return f"{entity} - {grain}" if grain else entity


_ITEM_RE = re.compile(r'Item="([^"]+)"')


def _source_model(table) -> str | None:
    """dbt model name behind a table, read from its M partition expression."""
    for p in table.Partitions:
        expr = getattr(p.Source, "Expression", None)
        if expr:
            m = _ITEM_RE.search(str(expr))
            if m:
                return m.group(1)
    return None


def read_tables(config: TmdlProjectConfig, skip: bool = True) -> dict:
    """Read the model into plain dicts: {table_name: {model, columns}}.

    columns maps display name -> {source, hidden, folder, desc, data_type}.
    Loads the whole model once via TOM rather than parsing TMDL text.
    """
    _, model = load_model(config)
    out = {}
    for table in model.Tables:
        if skip and table.Name in config.skip_tables:
            continue
        columns = {}
        for col in table.Columns:
            dt = str(col.DataType)
            columns[col.Name] = {
                "source": col.SourceColumn or None,
                "hidden": bool(col.IsHidden),
                "folder": col.DisplayFolder or "",
                "desc": col.Description or "",
                "data_type": dt[0].lower() + dt[1:],
            }
        out[table.Name] = {"model": _source_model(table), "columns": columns}
    return out
