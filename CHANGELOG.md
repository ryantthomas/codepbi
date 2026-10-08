# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
