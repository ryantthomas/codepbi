from __future__ import annotations

from dataclasses import dataclass, field

from .ids import hex_id

# Single-role visuals: visualType -> the one query role every projected field goes under.
SINGLE_ROLE_KEY = {
    "slicer": "Field",
    "tableEx": "Values",
    "card": "Values",
    "multiRowCard": "Values",
}


@dataclass
class Field:
    """A column or measure reference projected onto a visual, e.g.
    Field("Projects", "Project Title") for a column, or
    Field("Orders", "Total Sales", is_measure=True) for a measure."""

    entity: str
    property: str
    native_name: str | None = None
    is_measure: bool = False

    @property
    def query_ref(self) -> str:
        return f"{self.entity}.{self.property}"

    @property
    def native_query_ref(self) -> str:
        return self.native_name or self.property


@dataclass
class Position:
    x: float
    y: float
    width: float
    height: float
    z: float = 0
    tab_order: float | None = None

    def __post_init__(self) -> None:
        if self.tab_order is None:
            self.tab_order = self.z


@dataclass
class Filter:
    """A filter pane entry on a visual. Use `categorical` to just expose a field as filterable,
    or `equals` to pre-apply a fixed condition (matches what PBI Desktop itself emits)."""

    entity: str
    property: str
    kind: str  # "Categorical" or "Advanced"
    value: str | None = None
    name: str = field(default_factory=hex_id)

    @staticmethod
    def categorical(entity: str, property: str) -> Filter:
        return Filter(entity, property, kind="Categorical")

    @staticmethod
    def equals(entity: str, property: str, value: str) -> Filter:
        return Filter(entity, property, kind="Advanced", value=value)


@dataclass
class Visual:
    """roles maps a visual-type-specific query role name (e.g. "Category", "Y", "Series" for a
    chart; "Values" for a table/card; "Field" for a slicer) to the fields projected onto it.
    Role names are NOT uniform across visual types.

    objects / visual_container_objects are passed straight through to the visual's own JSON
    (per-visual-type formatting and title/background/border respectively)."""

    visual_type: str
    roles: dict[str, list[Field]]
    position: Position
    filters: list[Filter] = field(default_factory=list)
    name: str = field(default_factory=hex_id)
    drill_filter_other_visuals: bool = True
    objects: dict = field(default_factory=dict)
    visual_container_objects: dict = field(default_factory=dict)


@dataclass
class Page:
    display_name: str
    name: str = field(default_factory=hex_id)
    height: float = 720
    width: float = 1280
    display_option: str = "FitToPage"
    visuals: list[Visual] = field(default_factory=list)

    def add_visual(
        self,
        visual_type: str,
        roles: dict[str, list[Field]],
        position: Position,
        filters: list[Filter] | None = None,
        objects: dict | None = None,
        visual_container_objects: dict | None = None,
    ) -> Visual:
        visual = Visual(
            visual_type, roles, position, filters or [],
            objects=objects or {}, visual_container_objects=visual_container_objects or {},
        )
        self.visuals.append(visual)
        return visual

    def _add_single_role(self, visual_type: str, fields: list[Field], position: Position,
                          filters: list[Filter] | None = None) -> Visual:
        return self.add_visual(visual_type, {SINGLE_ROLE_KEY[visual_type]: fields}, position, filters)

    def add_table(self, fields: list[Field], position: Position, filters: list[Filter] | None = None) -> Visual:
        return self._add_single_role("tableEx", fields, position, filters)

    def add_slicer(self, field_: Field, position: Position) -> Visual:
        return self._add_single_role("slicer", [field_], position)

    def add_card(self, field_: Field, position: Position) -> Visual:
        return self._add_single_role("card", [field_], position)

    def add_multi_row_card(self, fields: list[Field], position: Position) -> Visual:
        return self._add_single_role("multiRowCard", fields, position)

    def add_matrix(
        self, rows: list[Field], values: list[Field], position: Position,
        columns: list[Field] | None = None,
    ) -> Visual:
        roles = {"Rows": rows, "Values": values}
        if columns:
            roles["Columns"] = columns
        return self.add_visual("pivotTable", roles, position)

    def add_bar_chart(
        self, category: Field, values: list[Field], position: Position,
        series: Field | None = None, clustered: bool = True,
    ) -> Visual:
        roles = {"Category": [category], "Y": values}
        if series:
            roles["Series"] = [series]
        visual_type = "clusteredBarChart" if clustered else "barChart"
        return self.add_visual(visual_type, roles, position)

    def add_column_chart(
        self, category: Field, values: list[Field], position: Position,
        series: Field | None = None, clustered: bool = True,
    ) -> Visual:
        roles = {"Category": [category], "Y": values}
        if series:
            roles["Series"] = [series]
        visual_type = "clusteredColumnChart" if clustered else "columnChart"
        return self.add_visual(visual_type, roles, position)

    def add_line_chart(
        self, category: Field, values: list[Field], position: Position,
        series: Field | None = None,
    ) -> Visual:
        roles = {"Category": [category], "Y": values}
        if series:
            roles["Series"] = [series]
        return self.add_visual("lineChart", roles, position)

    def add_combo_chart(
        self, category: Field, column_values: list[Field], line_values: list[Field],
        position: Position,
    ) -> Visual:
        roles = {"Category": [category], "Y": column_values, "Y2": line_values}
        return self.add_visual("lineClusteredColumnComboChart", roles, position)

    def add_pie_chart(
        self, category: Field, values: list[Field], position: Position, donut: bool = False,
    ) -> Visual:
        roles = {"Category": [category], "Y": values}
        return self.add_visual("donutChart" if donut else "pieChart", roles, position)

    def add_scatter_chart(
        self, x: Field, y: Field, position: Position,
        category: Field | None = None, size: Field | None = None,
    ) -> Visual:
        # Desktop's UI labels this well "Details", but (like every other chart here) the
        # underlying role key is "Category" -- see docs/codepbi-lessons-learned.md.
        roles = {"X": [x], "Y": [y]}
        if category:
            roles["Category"] = [category]
        if size:
            roles["Size"] = [size]
        return self.add_visual("scatterChart", roles, position)

    def add_gauge(
        self, value: Field, position: Position,
        min_value: Field | None = None, max_value: Field | None = None, target_value: Field | None = None,
    ) -> Visual:
        roles = {"Y": [value]}
        if min_value:
            roles["MinValue"] = [min_value]
        if max_value:
            roles["MaxValue"] = [max_value]
        if target_value:
            roles["TargetValue"] = [target_value]
        return self.add_visual("gauge", roles, position)

    def add_treemap(
        self, group: Field, values: list[Field], position: Position, details: Field | None = None,
    ) -> Visual:
        roles = {"Group": [group], "Values": values}
        if details:
            roles["Details"] = [details]
        return self.add_visual("treemap", roles, position)

    def add_filled_map(
        self, location: Field, position: Position,
        values: list[Field] | None = None, legend: Field | None = None,
    ) -> Visual:
        roles = {"Category": [location]}
        if values:
            roles["Values"] = values
        if legend:
            roles["Legend"] = [legend]
        return self.add_visual("filledMap", roles, position)


@dataclass
class Report:
    name: str
    semantic_model_path: str
    pages: list[Page] = field(default_factory=list)
    active_page_name: str | None = None

    def add_page(self, display_name: str, **kwargs) -> Page:
        page = Page(display_name=display_name, **kwargs)
        self.pages.append(page)
        if self.active_page_name is None:
            self.active_page_name = page.name
        return page

    def save(self, parent_dir: str) -> str:
        from .writer import write_report

        return write_report(self, parent_dir)
