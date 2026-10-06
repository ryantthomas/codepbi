from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TmdlProjectConfig:
    """Points the semantic-sync tooling at a specific dbt project + TMDL semantic model.

    dbt_project_dir: the dbt project root (contains dbt_project.yml, models/, seeds/).
    semantic_model_definition_dir: the `<Model>.SemanticModel/definition` folder PBI Desktop
        reads/writes (contains model.tmdl, tables/, relationships.tmdl).
    tom_lib_dir: folder containing the Microsoft.AnalysisServices .NET DLLs (from the
        `Microsoft.AnalysisServices.NetCore.retail.amd64` NuGet package) that pythonnet
        loads to talk to TOM. Not redistributed here — obtain separately.
    models_glob: glob (relative to dbt_project_dir) for schema YAML files to read.
        Excludes anything under semantic_models_subdir and any `sources.yml` automatically.
    semantic_models_subdir: relative path to the folder of per-table semantic model YAML
        files (entities + measures, dbt-semantic-layer style) that are the join and
        DAX-measure authority.
    skip_tables: TMDL table names to ignore entirely (e.g. a reference/glossary table with
        no backing dbt model).
    extra_column_meta: additional `meta.*` keys to pass through verbatim on each column dict
        (key -> default value used when a column doesn't declare it), for callers that track
        extra per-column metadata (e.g. data-governance fields) beyond what TMDL sync needs.
        Unused by anything in this package; purely a passthrough so callers don't have to
        re-parse schema YAML themselves just to read one more field.
    extra_table_meta: same idea as extra_column_meta, but for per-table `meta.*` keys.
    """

    dbt_project_dir: Path
    semantic_model_definition_dir: Path
    tom_lib_dir: Path
    models_glob: str = "models/**/*.yml"
    semantic_models_subdir: str = "models/semantic_models"
    skip_tables: set[str] = field(default_factory=set)
    extra_column_meta: dict[str, str] = field(default_factory=dict)
    extra_table_meta: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.dbt_project_dir = Path(self.dbt_project_dir)
        self.semantic_model_definition_dir = Path(self.semantic_model_definition_dir)
        self.tom_lib_dir = Path(self.tom_lib_dir)

    @property
    def tables_dir(self) -> Path:
        return self.semantic_model_definition_dir / "tables"

    @property
    def semantic_models_dir(self) -> Path:
        return self.dbt_project_dir / self.semantic_models_subdir
