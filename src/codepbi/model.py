from __future__ import annotations

from dataclasses import dataclass, field

from .ids import hex_id

ROLE_KEY_OVERRIDES = {"slicer": "Field"}
DEFAULT_ROLE_KEY = "Values"


@dataclass
class Field:
    """A column reference projected onto a visual, e.g. Field("Projects", "Project Title")."""

    entity: str
    property: str
    native_name: str | None = None

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
    visual_type: str  # "tableEx", "slicer", "card", "pivotTable"
    fields: list[Field]
    position: Position
    filters: list[Filter] = field(default_factory=list)
    name: str = field(default_factory=hex_id)
    drill_filter_other_visuals: bool = True

    @property
    def role_key(self) -> str:
        return ROLE_KEY_OVERRIDES.get(self.visual_type, DEFAULT_ROLE_KEY)


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
        fields: list[Field],
        position: Position,
        filters: list[Filter] | None = None,
    ) -> Visual:
        visual = Visual(visual_type, fields, position, filters or [])
        self.visuals.append(visual)
        return visual

    def add_table(self, fields: list[Field], position: Position, filters: list[Filter] | None = None) -> Visual:
        return self.add_visual("tableEx", fields, position, filters)

    def add_slicer(self, field_: Field, position: Position) -> Visual:
        return self.add_visual("slicer", [field_], position)

    def add_card(self, field_: Field, position: Position) -> Visual:
        return self.add_visual("card", [field_], position)


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
