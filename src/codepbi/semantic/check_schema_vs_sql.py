# Drift detection check_drift can't do: it only compares schema YAML against
# TMDL, so if schema YAML itself is wrong (a column moved/renamed in a model's
# SQL without schema YAML being updated to match), TMDL happily syncs to the
# same wrong name and both "agree" on a column that doesn't exist -- the bug
# only surfaces later when Power BI queries it live. This checks schema YAML's
# declared columns against what each model's own compiled SQL actually SELECTs.
# Requires `dbt compile` (or `dbt run`) to have already produced target/compiled/....

from .config import TmdlProjectConfig
from .dbt_sql import load_model_data, sql_exprs
from .schema_loader import load_schema


def check(config: TmdlProjectConfig) -> int:
    if config.dbt_manifest_path is None or config.dbt_compiled_dir is None:
        raise SystemExit(
            "check_schema_vs_sql requires config.dbt_manifest_path and "
            "config.dbt_compiled_dir to be set."
        )
    schema = load_schema(config)
    model_data = load_model_data(config.dbt_manifest_path, config.dbt_compiled_dir)
    errors = []
    checked = 0

    for table_name, spec in sorted(schema.items()):
        dbt_model = spec["model"]
        if not dbt_model:
            continue

        if not model_data.get(dbt_model, {}).get("compiled_exists"):
            errors.append(f'{table_name}: no compiled SQL found for model "{dbt_model}" '
                          f'(did `dbt compile` run?)')
            continue

        try:
            exprs = sql_exprs(model_data[dbt_model]["sql"])
        except Exception as e:
            errors.append(f'{table_name}: failed to parse compiled SQL for model "{dbt_model}": {e}')
            continue

        if set(exprs) == {"*"}:
            errors.append(f'{table_name}: model "{dbt_model}" appears to end in a bare '
                          f'SELECT * -- cannot verify its columns')
            continue

        exprs_lower = {k.lower() for k in exprs}
        for col in spec["columns"]:
            checked += 1
            source_col = col["source"]
            if source_col.lower() not in exprs_lower:
                errors.append(f'{table_name}.{col["display"]}: schema YAML source column '
                              f'"{source_col}" not found in "{dbt_model}"\'s compiled SELECT list')

    if errors:
        print(f"ERROR: {len(errors)} schema YAML column(s) not found in their model's compiled SQL:")
        for e in errors:
            print(f"  {e}")
        return 1

    print(f"OK: all schema YAML columns exist in their model's compiled SQL ({checked} columns checked)")
    return 0
