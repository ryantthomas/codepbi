# Shared dbt schema YAML parser. Every generator/sync function that needs column or
# table metadata calls `load_schema` from here instead of parsing schema YAML
# itself -- schema YAML is the single source of truth for column metadata, so
# there is exactly one reader for it.

import yaml

from . import tom_utils
from .config import TmdlProjectConfig

# schema YAML data_type -> TMDL sourceProviderType + formatString.
# 'format' is only the default for a bare data_type; meta.format_string overrides it.
# double has no default format on purpose: a money column must declare one, or it
# renders as a raw number with no totals.
DATATYPE_MAP = {
    "int64": {"provider": "int", "format": "0"},
    "string": {"provider": "nvarchar(255)", "format": None},
    "dateTime": {"provider": "datetime2", "format": "General Date"},
    "boolean": {"provider": "bit", "format": '"TRUE";"TRUE";"FALSE"'},
    "double": {"provider": "float", "format": None},
}

# meta.summarize_by -> TOM AggregateFunction member name. 'none' makes a numeric column
# behave as an attribute: no implicit aggregation and no totals row. That is correct for
# semi-additive snapshots (a point-in-time balance must not be summed across periods) and
# wrong for an ordinary money column.
SUMMARIZE_MAP = {
    "none": "None", "default": "Default", "sum": "Sum", "average": "Average",
    "count": "Count", "distinctCount": "DistinctCount", "min": "Min", "max": "Max",
}

# TOM DataType name -> schema YAML data_type, for the drift check in sync_descriptions.
TOM_TO_YAML = {"String": "string", "Int64": "int64", "DateTime": "dateTime",
               "Double": "double", "Boolean": "boolean"}


def aggregate_function(value, source):
    from Microsoft.AnalysisServices.Tabular import AggregateFunction

    if value not in SUMMARIZE_MAP:
        raise SystemExit(
            f"Unknown summarize_by {value!r} for column {source!r}. "
            f"Must be one of: {sorted(SUMMARIZE_MAP)}"
        )
    return getattr(AggregateFunction, SUMMARIZE_MAP[value])


def _model_blocks(config: TmdlProjectConfig):
    """Every `models:` entry across the configured schema YAML glob, sorted by model name.

    Lets schema YAML be split across multiple files (e.g. per layer) without every
    caller needing to know the split. semantic_models_subdir and any `sources.yml`
    are excluded: they are different documents that also carry a top-level `models`-
    shaped key we would otherwise misread.
    """
    sm_dir = config.semantic_models_dir
    blocks, seen = [], {}
    for path in sorted(config.dbt_project_dir.glob(config.models_glob)):
        if sm_dir in path.parents or path.name == "sources.yml":
            continue
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        for model in doc.get("models", []) or []:
            name = model.get("name")
            if name in seen:
                raise SystemExit(
                    f"duplicate model {name!r} in schema YAML: "
                    f"{seen[name]} and {path}. "
                    "A silent last-write-wins here loses a model's column metadata."
                )
            seen[name] = path
            blocks.append(model)
    blocks.sort(key=lambda m: m.get("name") or "")
    return blocks


def load_schema(config: TmdlProjectConfig) -> dict:
    """Schema YAML -> {pbi_table: {'entity','grain','columns': [colinfo]}}.

    colinfo carries everything TMDL needs; the schema YAML is the only source of truth.
    """
    out = {}
    for model in _model_blocks(config):
        meta = model.get("meta", {}) or {}
        pbi_table = tom_utils.pbi_table_of(meta)
        if not pbi_table:
            continue
        cols = []
        for col in model.get("columns", []):
            cm = col.get("meta", {}) or {}
            cols.append({
                "source": col["name"],
                "display": cm.get("display_name", col["name"]),
                "desc": col.get("description", ""),
                "folder": cm.get("displayFolder", ""),
                "hidden": bool(cm.get("hidden", False)),
                "data_type": cm.get("data_type"),
                # None means "not declared" -> leave whatever TMDL has. Declaring these
                # is what makes a money column survive a table rebuild.
                "format_string": cm.get("format_string"),
                "summarize_by": cm.get("summarize_by"),
            })
        out[pbi_table] = {
            "entity": meta.get("entity", ""),
            "grain": meta.get("grain", ""),
            # The dbt model name, so generators can emit ref() without reading the
            # TMDL partition to find out which model backs the table.
            "model": model["name"],
            "columns": cols,
        }
    return out


def model_to_table(config: TmdlProjectConfig) -> dict:
    return {spec["model"]: name for name, spec in load_schema(config).items()}


def iter_semantic_models(config: TmdlProjectConfig):
    """Yield (path, doc, sm, table_name) for every semantic-model YAML file with a
    table resolvable via schema YAML. Shared by every function that reads
    entities/measures out of those files, so the glob-and-parse loop exists once."""
    m2t = model_to_table(config)
    for path in sorted(config.semantic_models_dir.glob("*.yml")):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        for sm in doc.get("semantic_models") or []:
            dbt_model = sm["model"][len("ref('"):-len("')")]
            table_name = m2t.get(dbt_model)
            if table_name:
                yield path, doc, sm, table_name
