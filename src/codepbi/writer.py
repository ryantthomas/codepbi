from __future__ import annotations

import json
from pathlib import Path

from .ids import guid
from .model import Filter, Page, Report, Visual

PBIP_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json"
PLATFORM_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json"
PBIR_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json"
REPORT_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json"
VERSION_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json"
PAGES_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
VISUAL_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.12.0/schema.json"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _field_ref(entity: str, property_: str) -> dict:
    return {
        "Column": {
            "Expression": {"SourceRef": {"Entity": entity}},
            "Property": property_,
        }
    }


def _projection(f) -> dict:
    return {
        "field": _field_ref(f.entity, f.property),
        "queryRef": f.query_ref,
        "nativeQueryRef": f.native_query_ref,
    }


def _filter_json(filt: Filter) -> dict:
    base = {
        "name": filt.name,
        "field": _field_ref(filt.entity, filt.property),
        "type": filt.kind,
    }
    if filt.kind == "Advanced" and filt.value is not None:
        base["filter"] = {
            "Version": 2,
            "From": [{"Name": "c", "Entity": filt.entity, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "Comparison": {
                            "ComparisonKind": 0,
                            "Left": {
                                "Column": {
                                    "Expression": {"SourceRef": {"Source": "c"}},
                                    "Property": filt.property,
                                }
                            },
                            "Right": {"Literal": {"Value": f"'{filt.value}'"}},
                        }
                    }
                }
            ],
        }
        base["howCreated"] = "User"
    return base


def _visual_json(visual: Visual) -> dict:
    pos = visual.position
    data = {
        "$schema": VISUAL_SCHEMA,
        "name": visual.name,
        "position": {
            "x": pos.x,
            "y": pos.y,
            "z": pos.z,
            "height": pos.height,
            "width": pos.width,
            "tabOrder": pos.tab_order,
        },
        "visual": {
            "visualType": visual.visual_type,
            "query": {
                "queryState": {
                    visual.role_key: {"projections": [_projection(f) for f in visual.fields]}
                }
            },
            "drillFilterOtherVisuals": visual.drill_filter_other_visuals,
        },
    }
    if visual.filters:
        data["filterConfig"] = {"filters": [_filter_json(f) for f in visual.filters]}
    return data


def _page_json(page: Page) -> dict:
    return {
        "$schema": PAGE_SCHEMA,
        "name": page.name,
        "displayName": page.display_name,
        "displayOption": page.display_option,
        "height": page.height,
        "width": page.width,
    }


def write_report(report: Report, parent_dir: str) -> str:
    """Write a full .pbip + .Report folder tree. Does not create the semantic model --
    `report.semantic_model_path` must point at one that already exists (relative to the .Report folder)."""
    parent = Path(parent_dir)
    report_dir = parent / f"{report.name}.Report"

    _write_json(
        parent / f"{report.name}.pbip",
        {
            "$schema": PBIP_SCHEMA,
            "version": "1.0",
            "artifacts": [{"report": {"path": f"{report.name}.Report"}}],
            "settings": {"enableAutoRecovery": True},
        },
    )

    _write_json(
        report_dir / ".platform",
        {
            "$schema": PLATFORM_SCHEMA,
            "metadata": {"type": "Report", "displayName": report.name},
            "config": {"version": "2.0", "logicalId": guid()},
        },
    )

    _write_json(
        report_dir / "definition.pbir",
        {
            "$schema": PBIR_SCHEMA,
            "version": "4.0",
            "datasetReference": {"byPath": {"path": report.semantic_model_path}},
        },
    )

    _write_json(
        report_dir / "definition" / "report.json",
        {
            "$schema": REPORT_SCHEMA,
            "settings": {
                "useStylableVisualContainerHeader": True,
                "exportDataMode": "AllowSummarized",
                "defaultDrillFilterOtherVisuals": True,
                "allowChangeFilterTypes": True,
                "useEnhancedTooltips": True,
                "useDefaultAggregateDisplayName": True,
            },
        },
    )

    _write_json(
        report_dir / "definition" / "version.json",
        {"$schema": VERSION_SCHEMA, "version": "2.0.0"},
    )

    _write_json(
        report_dir / "definition" / "pages" / "pages.json",
        {
            "$schema": PAGES_SCHEMA,
            "pageOrder": [p.name for p in report.pages],
            "activePageName": report.active_page_name,
        },
    )

    for page in report.pages:
        page_dir = report_dir / "definition" / "pages" / page.name
        _write_json(page_dir / "page.json", _page_json(page))
        for visual in page.visuals:
            _write_json(page_dir / "visuals" / visual.name / "visual.json", _visual_json(visual))

    return str(report_dir)
