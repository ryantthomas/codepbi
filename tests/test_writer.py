import json
import tempfile
import unittest
from pathlib import Path

from codepbi import Field, Filter, Position, Report


class TestWriteReport(unittest.TestCase):
    def build_sample_report(self) -> Report:
        report = Report(name="Sample Report", semantic_model_path="../Sample.SemanticModel")
        page = report.add_page("Overview")
        page.add_slicer(Field("Projects", "Project Title"), Position(x=0, y=0, width=200, height=400))
        page.add_table(
            fields=[Field("Projects", "Project Title"), Field("Projects", "Program Name")],
            position=Position(x=220, y=0, width=800, height=400),
            filters=[Filter.equals("Projects", "Project Status", "Active")],
        )
        return report

    def test_writes_expected_file_tree(self):
        report = self.build_sample_report()
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(report.save(tmp))
            self.assertTrue((Path(tmp) / "Sample Report.pbip").exists())
            self.assertTrue((report_dir / ".platform").exists())
            self.assertTrue((report_dir / "definition.pbir").exists())
            self.assertTrue((report_dir / "definition" / "report.json").exists())
            self.assertTrue((report_dir / "definition" / "version.json").exists())
            self.assertTrue((report_dir / "definition" / "pages" / "pages.json").exists())

            page = report.pages[0]
            page_dir = report_dir / "definition" / "pages" / page.name
            self.assertTrue((page_dir / "page.json").exists())
            for visual in page.visuals:
                self.assertTrue((page_dir / "visuals" / visual.name / "visual.json").exists())

    def test_pbir_points_at_semantic_model(self):
        report = self.build_sample_report()
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(report.save(tmp))
            pbir = json.loads((report_dir / "definition.pbir").read_text())
            self.assertEqual(pbir["datasetReference"]["byPath"]["path"], "../Sample.SemanticModel")

    def test_report_json_has_required_theme_collection(self):
        # See LESSONS_LEARNED.md -- the schema requires themeCollection, even empty;
        # Desktop fails to open a report that omits it.
        report = self.build_sample_report()
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(report.save(tmp))
            report_json = json.loads((report_dir / "definition" / "report.json").read_text())
            self.assertIn("themeCollection", report_json)

    def test_table_visual_projects_all_fields(self):
        report = self.build_sample_report()
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(report.save(tmp))
            page = report.pages[0]
            table_visual = page.visuals[1]
            visual_json = json.loads(
                (report_dir / "definition" / "pages" / page.name / "visuals" / table_visual.name / "visual.json").read_text()
            )
            projections = visual_json["visual"]["query"]["queryState"]["Values"]["projections"]
            self.assertEqual(len(projections), 2)
            self.assertEqual(projections[0]["queryRef"], "Projects.Project Title")
            self.assertEqual(visual_json["filterConfig"]["filters"][0]["filter"]["Where"][0]["Condition"]["Comparison"]["Right"]["Literal"]["Value"], "'Active'")

    def test_slicer_uses_field_role_key(self):
        report = self.build_sample_report()
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(report.save(tmp))
            page = report.pages[0]
            slicer_visual = page.visuals[0]
            visual_json = json.loads(
                (report_dir / "definition" / "pages" / page.name / "visuals" / slicer_visual.name / "visual.json").read_text()
            )
            self.assertIn("Field", visual_json["visual"]["query"]["queryState"])

    def _visual_json(self, report, report_dir, page, visual):
        path = report_dir / "definition" / "pages" / page.name / "visuals" / visual.name / "visual.json"
        return json.loads(path.read_text())

    def test_measure_field_uses_measure_wrapper(self):
        report = Report(name="Measures Report", semantic_model_path="../Sample.SemanticModel")
        page = report.add_page("Overview")
        card = page.add_card(Field("Orders", "Total Sales", is_measure=True), Position(x=0, y=0, width=200, height=100))
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(report.save(tmp))
            visual_json = self._visual_json(report, report_dir, page, card)
            field_ref = visual_json["visual"]["query"]["queryState"]["Values"]["projections"][0]["field"]
            self.assertIn("Measure", field_ref)
            self.assertNotIn("Column", field_ref)

    def test_bar_chart_has_category_and_y_roles(self):
        report = Report(name="Charts Report", semantic_model_path="../Sample.SemanticModel")
        page = report.add_page("Overview")
        chart = page.add_bar_chart(
            category=Field("Projects", "Program Name"),
            values=[Field("Orders", "Total Sales", is_measure=True)],
            position=Position(x=0, y=0, width=400, height=300),
        )
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(report.save(tmp))
            visual_json = self._visual_json(report, report_dir, page, chart)
            self.assertEqual(visual_json["visual"]["visualType"], "clusteredBarChart")
            query_state = visual_json["visual"]["query"]["queryState"]
            self.assertIn("Category", query_state)
            self.assertIn("Y", query_state)

    def test_matrix_has_rows_and_values_roles(self):
        report = Report(name="Matrix Report", semantic_model_path="../Sample.SemanticModel")
        page = report.add_page("Overview")
        matrix = page.add_matrix(
            rows=[Field("Projects", "Program Name")],
            values=[Field("Orders", "Total Sales", is_measure=True)],
            position=Position(x=0, y=0, width=400, height=300),
        )
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(report.save(tmp))
            visual_json = self._visual_json(report, report_dir, page, matrix)
            self.assertEqual(visual_json["visual"]["visualType"], "pivotTable")
            query_state = visual_json["visual"]["query"]["queryState"]
            self.assertIn("Rows", query_state)
            self.assertIn("Values", query_state)
            self.assertNotIn("Columns", query_state)

    def test_visual_objects_and_container_objects_passthrough(self):
        report = Report(name="Styled Report", semantic_model_path="../Sample.SemanticModel")
        page = report.add_page("Overview")
        card = page.add_visual(
            "card",
            {"Values": [Field("Orders", "Total Sales", is_measure=True)]},
            Position(x=0, y=0, width=200, height=100),
            objects={"border": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}]},
            visual_container_objects={"title": [{"properties": {"text": {"expr": {"Literal": {"Value": "'Total'"}}}}}]},
        )
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(report.save(tmp))
            visual_json = self._visual_json(report, report_dir, page, card)
            self.assertIn("objects", visual_json["visual"])
            self.assertIn("visualContainerObjects", visual_json["visual"])


if __name__ == "__main__":
    unittest.main()
