"""Tests for codepbi.semantic's pure-Python logic (schema/YAML parsing, no TOM).

Functions that call into TOM (tom_utils.load_model/save_model, and anything that
calls them -- sync_descriptions.sync, sync_measures.sync, sync_relationships.sync,
validate_tmdl.validate_tmdl, check_drift.check) need the Microsoft.AnalysisServices
.NET DLLs and are not covered here.
"""

import unittest
from pathlib import Path

from codepbi.semantic import schema_loader, sync_measures, sync_relationships
from codepbi.semantic.config import TmdlProjectConfig
from codepbi.semantic.dbt_sql import sql_exprs
from codepbi.semantic.tom_utils import pbi_table_of
from codepbi.semantic.validate_tmdl import dax_reference_errors

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

    def test_in_model_skips_relationships_to_tables_in_another_model(self):
        rels = sync_relationships.load(make_config(Path(".")))
        self.assertEqual(sync_relationships.in_model(rels, {"Orders", "Customers"}), (rels, 0))
        self.assertEqual(sync_relationships.in_model(rels, {"Orders"}), ([], 1))


class TestExportRelationships(unittest.TestCase):
    def sms(self):
        config = make_config(Path("."))
        return {t: sm for _p, _d, sm, t in schema_loader.iter_semantic_models(config)}

    def test_export_round_trips_source_names_and_keeps_names(self):
        sms = self.sms()
        sms["Customers"]["entities"][0]["description"] = "The customer."
        rels = [("Orders", "customer_id", "Customers", "customer_id", True, False)]
        skipped = sync_relationships.export_entities(sms, rels, {"Orders", "Customers"})
        self.assertEqual(skipped, 0)
        self.assertEqual(sms["Customers"]["entities"], [
            {"name": "customer", "type": "primary", "expr": "customer_id",
             "description": "The customer."},
        ])
        self.assertEqual(sms["Orders"]["entities"], [
            {"name": "customer", "type": "foreign", "expr": "customer_id",
             "config": {"meta": {"both_directions": True}}},
        ])

    def test_export_drops_removed_in_model_join(self):
        sms = self.sms()
        sync_relationships.export_entities(sms, [], {"Orders", "Customers"})
        self.assertNotIn("entities", sms["Orders"])
        self.assertEqual(len(sms["Customers"]["entities"]), 1)

    def test_export_keeps_join_to_table_in_another_model(self):
        sms = self.sms()
        sync_relationships.export_entities(sms, [], {"Orders"})
        self.assertEqual(sms["Orders"]["entities"][0]["name"], "customer")


class TestMeasures(unittest.TestCase):
    def test_load_by_table_splits_prose_from_dax(self):
        entry = sync_measures.load_by_table(make_config(Path(".")))["Orders"][0]
        self.assertEqual(entry["name"], "Total Order Amount")
        self.assertEqual(entry["description"], "Total across selected orders.")
        self.assertEqual(entry["dax"], "SUM('Orders'[Order Amount])")

    def test_export_merges_by_label_and_names_new_measures(self):
        config = make_config(Path("."))
        sm = next(sm for _p, _d, sm, t in schema_loader.iter_semantic_models(config)
                  if t == "Orders")
        measures = [
            {"name": "Total Order Amount", "dax": "SUMX('Orders', [Order Amount])",
             "formatString": "0", "displayFolder": "Totals"},
            {"name": "Order Count", "dax": "COUNTROWS('Orders')",
             "formatString": "", "displayFolder": "Calculations"},
        ]
        merged = sync_measures.export_measures(sm["measures"], measures)
        self.assertEqual(merged[0], {
            "name": "total_order_amount",
            "agg": "sum",
            "label": "Total Order Amount",
            "description": "Total across selected orders. DAX: SUMX('Orders', [Order Amount])",
            "config": {"meta": {"format_string": "0", "displayFolder": "Totals"}},
        })
        self.assertEqual(merged[1]["name"], "order_count")
        self.assertEqual(merged[1]["description"], "DAX: COUNTROWS('Orders')")

    def test_export_drops_measures_gone_from_tmdl(self):
        self.assertEqual(sync_measures.export_measures([{"name": "x", "label": "X"}], []), [])


class TestDaxReferences(unittest.TestCase):
    COLUMNS = {"Orders": {"Order Amount", "Region"}, "Customers": {"Customer ID"}}
    MEASURES = {"Orders": {"Total Sales"}, "Customers": {"Customer Count"}}

    def errors(self, expression, table="Orders"):
        return dax_reference_errors(table, expression, self.COLUMNS, self.MEASURES)

    def test_valid_references_pass(self):
        dax = (
            "SUM('Orders'[Order Amount]) + Orders[Total Sales] + [Customer Count] "
            "+ [Region] + SUMX(ADDCOLUMNS(Orders, \"@x\", 1), [@x])"
        )
        self.assertEqual(self.errors(dax), [])

    def test_bare_reference_to_column_on_another_table_fails(self):
        self.assertEqual(len(self.errors("[Customer ID]")), 1)
        self.assertEqual(self.errors("[Customer ID]", table="Customers"), [])

    def test_unquoted_and_quoted_unknowns_fail(self):
        self.assertEqual(len(self.errors("Orders[Old Name] + 'Nope'[X] + [Gone]")), 3)

    def test_strings_and_comments_are_ignored(self):
        dax = "\"see [Gone]\" // [Gone]\n-- 'Nope'[X]\n/* Orders[Old] */ [Total Sales]"
        self.assertEqual(self.errors(dax), [])


class TestDbtSql(unittest.TestCase):
    def test_sql_exprs_reads_select_list(self):
        sql = "SELECT a.order_id AS OrderID, a.amount AS Amount FROM orders a"
        exprs = sql_exprs(sql)
        self.assertEqual(set(exprs), {"OrderID", "Amount"})


if __name__ == "__main__":
    unittest.main()
