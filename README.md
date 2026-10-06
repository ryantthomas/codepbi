# codepbi

Code-first Power BI. Define pages and visuals in Python, get a working PBIP/PBIR
report that opens and edits normally in Power BI Desktop.

```python
from codepbi import Field, Filter, Position, Report

report = Report(name="Sales Overview", semantic_model_path="../Sales.SemanticModel")
page = report.add_page("Overview")
page.add_slicer(Field("Orders", "Region"), Position(x=0, y=0, width=200, height=400))
page.add_table(
    fields=[Field("Orders", "Region"), Field("Orders", "Order Amount")],
    position=Position(x=220, y=0, width=800, height=400),
    filters=[Filter.equals("Orders", "Status", "Active")],
)
report.save("output_dir")
```

## `codepbi.semantic`

A separate module for the other half of the workflow: syncing a Power BI TMDL
semantic model *from* a dbt project, via the Tabular Object Model (TOM). Treats
dbt's schema YAML as the source of truth for columns, and a dbt-semantic-layer-
style `semantic_models/*.yml` (entities + measures) as the source of truth for
joins and DAX measures.

```python
from codepbi.semantic import TmdlProjectConfig, sync_descriptions, sync_measures, sync_relationships

config = TmdlProjectConfig(
    dbt_project_dir="path/to/dbt_project",
    semantic_model_definition_dir="path/to/Model.SemanticModel/definition",
    tom_lib_dir="path/to/analysis-services-dlls",
)

sync_measures.sync(config)
sync_descriptions.sync(config)   # also validates the resulting model
sync_relationships.sync(config)
```

Requires the `semantic` extra (`pip install codepbi[semantic]`) plus the
`Microsoft.AnalysisServices.NetCore.retail.amd64` NuGet package's DLLs, obtained
separately and pointed at via `tom_lib_dir` (not redistributed here).

## Install

```bash
pip install -e .           # report/visual builder only
pip install -e ".[semantic]"  # + the dbt-to-TMDL sync module
```

## Lessons learned

PBIR/TMDL quirks found by generating reports and actually opening them in Power BI
Desktop -- see [LESSONS_LEARNED.md](LESSONS_LEARNED.md).

## License

MIT
