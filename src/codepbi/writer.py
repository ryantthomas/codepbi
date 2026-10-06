from __future__ import annotations

import json
from pathlib import Path

from .ids import guid
from .model import Filter, Page, Report, Visual, field_ref

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


def _projection(f) -> dict:
    return {
        "field": field_ref(f.entity, f.property, f.is_measure),
        "queryRef": f.query_ref,
        "nativeQueryRef": f.native_query_ref,
    }


def _filter_json(filt: Filter) -> dict:
    base = {
        "name": filt.name,
        "field": field_ref(filt.entity, filt.property),
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
    query_state = {
        role: {"projections": [_projection(f) for f in fields]}
        for role, fields in visual.roles.items()
    }
    visual_body = {
        "visualType": visual.visual_type,
        "query": {"queryState": query_state},
        "drillFilterOtherVisuals": visual.drill_filter_other_visuals,
    }
    if visual.objects:
        visual_body["objects"] = visual.objects
    if visual.visual_container_objects:
        visual_body["visualContainerObjects"] = visual.visual_container_objects
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
        "visual": visual_body,
    }
    if visual.filters:
        data["filterConfig"] = {"filters": [_filter_json(f) for f in visual.filters]}
    return data


def _page_json(page: Page) -> dict:
    data = {
        "$schema": PAGE_SCHEMA,
        "name": page.name,
        "displayName": page.display_name,
        "displayOption": page.display_option,
        "height": page.height,
        "width": page.width,
    }
    if page.page_type:
        data["type"] = page.page_type
    if page.page_binding:
        data["pageBinding"] = page.page_binding
    if page.visual_interactions:
        data["visualInteractions"] = page.visual_interactions
    if page.objects:
        data["objects"] = page.objects
    if page.filters:
        data["filterConfig"] = {"filters": [_filter_json(f) for f in page.filters]}
    return data


def _report_json(report: Report) -> dict:
    theme_collection = {}
    resource_packages = []
    if report.theme:
        theme_name = report.theme["name"]
        theme_collection["customTheme"] = {
            "name": theme_name,
            "reportVersionAtImport": {"visual": "1.0.0", "page": "1.0.0", "report": "1.0.0"},
            "type": "RegisteredResources",
        }
        resource_packages.append({
            "name": "RegisteredResources",
            "type": "RegisteredResources",
            "items": [{"name": theme_name, "path": f"RegisteredResources/{theme_name}.json", "type": "CustomTheme"}],
        })
    data = {
        "$schema": REPORT_SCHEMA,
        # Required by the schema -- an empty object is valid (baseTheme/customTheme
        # are both optional sub-fields), and Desktop applies its own default theme.
        "themeCollection": theme_collection,
        "settings": {
            "useStylableVisualContainerHeader": True,
            "exportDataMode": "AllowSummarized",
            "defaultDrillFilterOtherVisuals": True,
            "allowChangeFilterTypes": True,
            "useEnhancedTooltips": True,
            "useDefaultAggregateDisplayName": True,
        },
    }
    if resource_packages:
        data["resourcePackages"] = resource_packages
    if report.filters:
        data["filterConfig"] = {"filters": [_filter_json(f) for f in report.filters]}
    return data


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

    _write_json(report_dir / "definition" / "report.json", _report_json(report))

    if report.theme:
        _write_json(
            report_dir / "StaticResources" / "RegisteredResources" / f"{report.theme['name']}.json",
            report.theme,
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
