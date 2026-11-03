# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.14] - 2026-11-03

### Added
- Role-playing joins: a foreign entity with `config.meta.joins: <primary entity>` pairs with that primary entity
  (e.g. a second date key joining the date table), since a model can't repeat an entity name.
- A simple metric whose `agg_time_dimension` rides an inactive relationship renders with `USERELATIONSHIP`.
- `sync-measures` skips, and reports, a measure that references a table the model doesn't hold, and any measure
  built on it.

## [0.1.13] - 2026-11-02

### Added
- Filtered simple metrics render to DAX: equality, `IN` and `NOT IN` conditions on dimensions (through
  their entity, so a filter can sit on a joined table), joined with `AND`, each wrapped in `KEEPFILTERS` so it
  narrows the report's filters as MetricFlow does. `agg: sum` with `expr: 1` renders as `COUNTROWS`.

## [0.1.12] - 2026-11-02

### Added
- With `semantic_manifest_path` set, typed MetricFlow metrics get their DAX rendered: simple (one-column
  aggregation), ratio (`DIVIDE`) and derived (an expression of other measures). Ratio and derived metrics belong
  to their first input's table. A metric with DAX after `DAX:` in its description keeps it as written, and one
  with neither stops the sync.

## [0.1.11] - 2026-11-02

### Added
- `semantic_manifest_path` in `TmdlProjectConfig`: syncs and validation read dbt's compiled
  `semantic_manifest.json`, with simple metrics read as measures, so both dbt's legacy and latest semantic
  YAML specs work. Export still writes the legacy per-table files and is unavailable in this mode.

## [0.1.10] - 2026-11-02

### Added
- `meta.table_name` in schema YAML sets the Power BI table name directly, so `entity` and
  `grain` can stay descriptive metadata when a table follows a different naming pattern.

## [0.1.9] - 2026-10-08

### Added
- `Filter.in_(entity, property, values)`: multi-value categorical filter (`In` condition).
- `Visual.is_hidden` (`isHidden`) and `Page.hidden` (`"visibility": "HiddenInViewMode"`).
- `sync_measures.sync(config, prune=True)` removes TMDL measures not declared in YAML.
- `sync_measures.sync` writes the prose before `DAX:` into `Measure.Description`.
- DAX reference validation resolves bare `[X]` and unquoted `Table[Col]` references and
  ignores string literals and comments.

### Changed
- Filter literals are typed by Python type (int `L`, float `D`, bool, date/datetime) and
  single quotes in strings are escaped.
- Visual `z`/`tabOrder` default to insertion order within the page instead of all `0`.
- Saving over an existing report clears generated pages and `RegisteredResources` and keeps
  the existing `.platform` `logicalId`.
- `sync_measures.sync` reports tables missing from the model in one summary line.

### Fixed
- `sync_relationships.export` writes source column names, keeps entity names, descriptions
  and order, and leaves joins to tables outside the model untouched.
- `sync_measures.export` merges into existing YAML measures (keeps name, agg and prose),
  names new measures in snake_case, and leaves tables outside the model untouched.
