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


if __name__ == "__main__":
    unittest.main()
