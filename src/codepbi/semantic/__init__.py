"""Sync a Power BI TMDL semantic model from a dbt project.

Treats dbt's schema YAML (`meta.entity` / `meta.grain` / `meta.display_name` / ...)
as the source of truth for columns, and a dbt-semantic-layer-style
`semantic_models/*.yml` (entities + measures) as the source of truth for joins
and DAX measures. Applies both to TMDL via the Tabular Object Model (TOM), so
Power BI Desktop keeps working normally against the result.

Typical flow:

    from codepbi.semantic import TmdlProjectConfig, check_drift, sync_descriptions, \\
        sync_measures, sync_relationships

    config = TmdlProjectConfig(
        dbt_project_dir="path/to/dbt_project",
        semantic_model_definition_dir="path/to/Model.SemanticModel/definition",
        tom_lib_dir="path/to/analysis-services-dlls",
    )

    sync_measures.sync(config)
    sync_descriptions.sync(config)       # also runs validate_tmdl at the end
    sync_relationships.sync(config)
    check_drift.check(config)
"""

from . import (
    check_drift,
    check_schema_vs_sql,
    schema_loader,
    sync_descriptions,
    sync_measures,
    sync_relationships,
    tom_utils,
    validate_tmdl,
)
from .config import TmdlProjectConfig

__all__ = [
    "TmdlProjectConfig",
    "check_drift",
    "check_schema_vs_sql",
    "schema_loader",
    "sync_descriptions",
    "sync_measures",
    "sync_relationships",
    "tom_utils",
    "validate_tmdl",
]
