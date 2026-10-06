# CI drift detection: compares dbt columns (schema YAML) against TMDL sourceColumns.
# Returns 1 if TMDL references columns that don't exist in dbt.

from . import tom_utils
from .config import TmdlProjectConfig
from .schema_loader import load_schema


def check(config: TmdlProjectConfig) -> int:
    dbt_models = {
        pbi_table: {col["source"] for col in spec["columns"]}
        for pbi_table, spec in load_schema(config).items()
    }

    errors = []
    warnings = []

    for table_name, table in sorted(tom_utils.read_tables(config).items()):
        if table_name not in dbt_models:
            continue

        dbt_cols = dbt_models[table_name]
        tmdl_sources = {col["source"] for col in table["columns"].values() if col["source"]}

        # TMDL references columns not in dbt (breaking -- column was removed/renamed)
        orphaned = tmdl_sources - dbt_cols
        for col in sorted(orphaned):
            errors.append(f'  {table_name}: TMDL sourceColumn "{col}" not found in schema YAML')

        # dbt has columns not in TMDL (informational -- new column not yet exposed in PBI)
        missing = dbt_cols - tmdl_sources
        for col in sorted(missing):
            warnings.append(f'  {table_name}: dbt column "{col}" not in TMDL')

    if warnings:
        print(f"INFO: {len(warnings)} dbt columns not yet in TMDL:")
        for w in warnings:
            print(w)
        print()

    if errors:
        print(f"ERROR: {len(errors)} TMDL columns reference missing dbt columns:")
        for e in errors:
            print(e)
        return 1

    print(f"OK: all TMDL sourceColumns exist in schema YAML ({len(dbt_models)} tables checked)")
    return 0
