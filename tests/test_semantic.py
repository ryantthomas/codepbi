"""Tests for codepbi.semantic's pure-Python logic (schema/YAML parsing, no TOM).

Functions that call into TOM (tom_utils.load_model/save_model, and anything that
calls them -- sync_descriptions.sync, sync_measures.sync, sync_relationships.sync,
validate_tmdl.validate_tmdl, check_drift.check) need the Microsoft.AnalysisServices
.NET DLLs and are not covered here.
"""

import unittest
from pathlib import Path

from codepbi.semantic import schema_loader, sync_relationships
from codepbi.semantic.config import TmdlProjectConfig
from codepbi.semantic.dbt_sql import sql_exprs
from codepbi.semantic.tom_utils import pbi_table_of

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dbt_project"


def make_config(tmp_tables_dir: Path) -> TmdlProjectConfig:
    return TmdlProjectConfig(
        dbt_project_dir=FIXTURE_DIR,
        semantic_model_definition_dir=tmp_tables_dir,
        tom_lib_dir=Path("unused-for-these-tests"),
    )


class TestSchemaLoader(unittest.TestCase):
    def test_load_schema_reads_entity_and_columns(self):
        config = make_config(Path("."))
        schema = schema_loader.load_schema(config)

        self.assertIn("Orders", schema)
        self.assertIn("Customers", schema)

        orders = schema["Orders"]
        self.assertEqual(orders["model"], "fact_orders")
        display_names = {c["display"] for c in orders["columns"]}
        self.assertEqual(display_names, {"Order ID", "Customer ID", "Order Amount"})

        amount_col = next(c for c in orders["columns"] if c["source"] == "order_amount")
        self.assertEqual(amount_col["format_string"], "$#,0.00")
        self.assertEqual(amount_col["summarize_by"], "sum")

    def test_pbi_table_of_combines_entity_and_grain(self):
        self.assertEqual(pbi_table_of({"entity": "Orders", "grain": "Monthly"}), "Orders - Monthly")
        self.assertEqual(pbi_table_of({"entity": "Orders"}), "Orders")
        self.assertIsNone(pbi_table_of({}))

    def test_extra_meta_passthrough_uses_default_when_undeclared(self):
        config = TmdlProjectConfig(
            dbt_project_dir=FIXTURE_DIR,
            semantic_model_definition_dir=Path("."),
            tom_lib_dir=Path("unused-for-these-tests"),
            extra_column_meta={"owner": "unassigned"},
            extra_table_meta={"layer": "core"},
        )
        schema = schema_loader.load_schema(config)
        self.assertEqual(schema["Orders"]["layer"], "core")
        self.assertTrue(all(c["owner"] == "unassigned" for c in schema["Orders"]["columns"]))

    def test_iter_semantic_models_resolves_table_names(self):
        config = make_config(Path("."))
        found = {table_name: sm for _p, _d, sm, table_name in schema_loader.iter_semantic_models(config)}
        self.assertIn("Orders", found)
        self.assertIn("Customers", found)
        self.assertEqual(found["Orders"]["entities"][0]["name"], "customer")


class TestSyncRelationshipsValidation(unittest.TestCase):
    def test_validate_passes_on_matched_primary_foreign(self):
        config = make_config(Path("."))
        errors = sync_relationships.validate(config)
        self.assertEqual(errors, [])

    def test_load_builds_relationship_rows(self):
        config = make_config(Path("."))
        rels = sync_relationships.load(config)
        self.assertEqual(len(rels), 1)
        rel = rels[0]
        self.assertEqual(rel["from"], "Orders")
        self.assertEqual(rel["to"], "Customers")
        self.assertEqual(rel["to_column"], "Customer ID")


class TestDbtSql(unittest.TestCase):
    def test_sql_exprs_reads_select_list(self):
        sql = "SELECT a.order_id AS OrderID, a.amount AS Amount FROM orders a"
        exprs = sql_exprs(sql)
        self.assertEqual(set(exprs), {"OrderID", "Amount"})


if __name__ == "__main__":
    unittest.main()
