from __future__ import annotations

import json
from datetime import date, datetime
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


def _literal(value) -> dict:
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, int):
        text = f"{value}L"
    elif isinstance(value, float):
        text = f"{value}D"
    elif isinstance(value, datetime):
        text = f"datetime'{value:%Y-%m-%dT%H:%M:%S}'"
    elif isinstance(value, date):
        text = f"datetime'{value:%Y-%m-%d}T00:00:00'"
    else:
        text = "'" + str(value).replace("'", "''") + "'"
    return {"Literal": {"Value": text}}


def _filter_json(filt: Filter) -> dict:
    base = {
        "name": filt.name,
        "field": field_ref(filt.entity, filt.property),
        "type": filt.kind,
    }
    column = {
        "Column": {"Expression": {"SourceRef": {"Source": "c"}}, "Property": filt.property}
    }
    if filt.values:
        values = [[_literal(v)] for v in filt.values]
        condition = {"In": {"Expressions": [column], "Values": values}}
    elif filt.kind == "Advanced" and filt.value is not None:
        condition = {
            "Comparison": {"ComparisonKind": 0, "Left": column, "Right": _literal(filt.value)}
        }
    else:
        return base
    base["filter"] = {
        "Version": 2,
        "From": [{"Name": "c", "Entity": filt.entity, "Type": 0}],
        "Where": [{"Condition": condition}],
    }
    base["howCreated"] = "User"
    return base


def _visual_json(visual: Visual, index: int) -> dict:
    pos = visual.position
    # Desktop spaces z and tabOrder 1000 apart in insertion order.
    z = index * 1000 if pos.z is None else pos.z
    data = {
        "$schema": VISUAL_SCHEMA,
        "name": visual.name,
        "position": {
            "x": pos.x,
            "y": pos.y,
            "z": z,
            "height": pos.height,
            "width": pos.width,
            "tabOrder": z if pos.tab_order is None else pos.tab_order,
        },
    }
    if visual.visual_group is not None:
        group_body = dict(visual.visual_group)
        if visual.objects:
            group_body["objects"] = visual.objects
        data["visualGroup"] = group_body
    else:
        visual_body = {
            "visualType": visual.visual_type,
            "drillFilterOtherVisuals": visual.drill_filter_other_visuals,
        }
        if visual.roles:
            # Static visuals (textbox, image) have no query roles at all -- confirmed from
            # real Desktop-saved examples, not just an empty queryState.
            query_state = {
                role: {"projections": [_projection(f) for f in fields]}
                for role, fields in visual.roles.items()
            }
            visual_body["query"] = {"queryState": query_state}
        if visual.objects:
            visual_body["objects"] = visual.objects
        if visual.visual_container_objects:
            visual_body["visualContainerObjects"] = visual.visual_container_objects
        data["visual"] = visual_body
    if visual.parent_group_name:
        data["parentGroupName"] = visual.parent_group_name
    if visual.filters:
        data["filterConfig"] = {"filters": [_filter_json(f) for f in visual.filters]}
    if visual.is_hidden:
        data["isHidden"] = True
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
    if page.hidden:
        data["visibility"] = "HiddenInViewMode"
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
    # Theme + images share ONE "RegisteredResources" package -- confirmed from a real
    # Desktop-saved report with both a custom theme and a logo image.
    registered_items = []
    if report.theme:
        theme_name = report.theme["name"]
        theme_collection["customTheme"] = {
            "name": theme_name,
            "reportVersionAtImport": {"visual": "1.0.0", "page": "1.0.0", "report": "1.0.0"},
            "type": "RegisteredResources",
        }
        # path is just the bare theme name -- no folder prefix, no extension. Confirmed:
        # Desktop normalized our original "RegisteredResources/<name>.json" guess down to this.
        registered_items.append({"name": theme_name, "path": theme_name, "type": "CustomTheme"})
    for resource_name, _local_path in report.images:
        registered_items.append({"name": resource_name, "path": resource_name, "type": "Image"})
    resource_packages = (
        [{"name": "RegisteredResources", "type": "RegisteredResources", "items": registered_items}]
        if registered_items else []
    )
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

    for resource_name, local_path in report.images:
        dest = report_dir / "StaticResources" / "RegisteredResources" / resource_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(Path(local_path).read_bytes())

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
        for i, visual in enumerate(page.visuals):
            _write_json(page_dir / "visuals" / visual.name / "visual.json", _visual_json(visual, i))

    return str(report_dir)
