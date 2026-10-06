# Validates the TMDL semantic model: file hygiene, duplicate lineageTags,
# ambiguous display names, duplicate/ambiguous relationships, DAX references
# that don't resolve, and measures missing from semantic-model YAML.
# Raises SystemExit on any failure. Called both standalone and from
# sync_descriptions.sync() at the end of a column sync.

import re
from collections import Counter, defaultdict

from . import tom_utils
from .config import TmdlProjectConfig

_BAD_LINE_LITERALS = {r"\r", r"\n", r"\t", r"\\r", r"\\n", r"\\t"}

# A DAX column reference: 'Table Name'[Column Name]
_DAX_REF_RE = re.compile(r"'([^']+)'\[([^\]]+)\]")


def _check_file_hygiene(config: TmdlProjectConfig) -> list[str]:
    """Byte-level tripwires for hand edits: BOMs, trailing whitespace, stray escapes."""
    errors = []
    for path in sorted(config.tables_dir.glob("*.tmdl")):
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            errors.append(f"{path.name}: BOM at file start")
        sep = b"\r\n" if b"\r\n" in raw else b"\n"
        for i, line in enumerate(raw.split(sep), 1):
            try:
                text = line.decode("utf-8")
            except UnicodeDecodeError:
                errors.append(f"{path.name}:{i}: non-UTF-8 bytes")
                continue
            if text.strip() in _BAD_LINE_LITERALS:
                errors.append(
                    f"{path.name}:{i}: literal escape sequence as line content ({text.strip()!r})"
                )
            if text != text.rstrip() and text.strip():
                errors.append(f"{path.name}:{i}: trailing whitespace")
    return errors


def _ambiguous_paths(model):
    """Table pairs reachable by more than one filter path.

    Filters propagate from the 'one' side to the 'many' side -- in TMDL that is
    toColumn -> fromColumn -- and both ways on a bidirectional relationship. Power
    BI permits exactly one path between any two tables; more than one and it
    refuses to load the model.

    Returns [(from_table, to_table, [path, ...]), ...] with each pair reported once.
    """
    edges = defaultdict(set)
    for rel in model.Relationships:
        if not rel.IsActive:
            continue
        one, many = rel.ToTable.Name, rel.FromTable.Name
        edges[one].add(many)
        if str(rel.CrossFilteringBehavior) != "OneDirection":
            edges[many].add(one)

    def walk(src, dst, seen):
        if src == dst:
            return [[src]]
        found = []
        for nxt in edges.get(src, ()):
            if nxt not in seen:
                found += [[src] + p for p in walk(nxt, dst, seen | {nxt})]
        return found

    names = [t.Name for t in model.Tables]
    out = []
    for a in names:
        for b in names:
            if a == b:
                continue
            routes = walk(a, b, {a})
            if len(routes) > 1:
                out.append((a, b, routes))
    return out


def validate_tmdl(config: TmdlProjectConfig) -> None:
    """Validate the semantic model. Raises SystemExit on any failure.

    A dangling relationship endpoint makes TOM deserialization fail outright,
    so that class of error is caught by simply loading the model.
    """
    from .sync_measures import load_by_table as _load_measures_by_table
    from .sync_relationships import validate as validate_relationships

    errors = _check_file_hygiene(config)

    try:
        _, model = tom_utils.load_model(config)
    except Exception as exc:
        for e in errors:
            print(f"TMDL VALIDATE: {e}")
        raise SystemExit(
            f"TMDL failed to load -- a reference does not resolve (often a relationship "
            f"pointing at a deleted table or renamed column):\n  {exc}"
        )

    tables = tom_utils.read_tables(config)

    # Duplicate lineageTags across the model
    tags = defaultdict(list)
    for table in model.Tables:
        for col in table.Columns:
            if col.LineageTag:
                tags[col.LineageTag].append(f"{table.Name}[{col.Name}]")
    for tag, locs in tags.items():
        if len(locs) > 1:
            errors.append(f"duplicate lineageTag {tag!r} at {', '.join(locs)}")

    # No display name may be visible on two tables at once. Two variants:
    #   A: same name, different sourceColumn  -> genuinely different things
    #   B: same name, same sourceColumn       -> the same thing in two places
    # Both confuse the field list, so both are errors. Measures share the same
    # namespace as columns (a table object model requires every column AND
    # measure name to be unique within that table), so they go in the same map --
    # a column/measure pair with the same name on the same table is a Desktop
    # "Issues were found" failure on open, not just a field-list ambiguity.
    name_map = defaultdict(list)
    for tname, t in tables.items():
        for cname, c in t["columns"].items():
            name_map[cname].append((tname, c["source"] or "", c["hidden"], "column"))
    for table in model.Tables:
        for measure in table.Measures:
            name_map[measure.Name].append((table.Name, "", False, "measure"))

    for name, entries in name_map.items():
        by_table = defaultdict(list)
        for t, s, h, kind in entries:
            by_table[t].append((s, h, kind))
        for tname, items in by_table.items():
            if len(items) > 1:
                kinds = ", ".join(f'{kind} ({"hidden" if h else "visible"})' for _, h, kind in items)
                errors.append(
                    f"{name!r} defined more than once on table {tname!r}: {kinds}. "
                    f"A column and a measure (or two measures) cannot share a name "
                    f"on the same table -- rename or remove one."
                )

        visible = [(t, s) for t, s, h, kind in entries if not h]
        if len(visible) < 2:
            continue
        if len({s for _, s in visible}) > 1:
            details = ", ".join(f'{t}[{s or "-"}]' for t, s in visible)
            errors.append(
                f"ambiguous display name {name!r} on visible tables with "
                f"different sourceColumns: {details}. Rename to disambiguate grain."
            )
        else:
            errors.append(
                f"column {name!r} visible on multiple tables (same source): "
                f"{sorted(t for t, _ in visible)}. Either hide it where a "
                f"relationship already supplies it, or rename to make the grain "
                f"explicit. Do not hide it if nothing else supplies it."
            )

    # semantic-model YAML owns measures. A measure only in TMDL -- hand-written, or
    # built in Power BI Desktop -- is outside source control, so flag it rather than
    # delete it: destroying someone's Desktop work on a sync would be worse.
    in_yaml = {
        (table, m["name"])
        for table, entries in _load_measures_by_table(config).items()
        for m in entries
    }
    for table in model.Tables:
        for measure in table.Measures:
            if (table.Name, measure.Name) not in in_yaml:
                errors.append(
                    f"measure {table.Name}[{measure.Name}] is not in semantic-model YAML. "
                    f"Add it there (semantic-model YAML is the source of truth for "
                    f"measures) or delete it from TMDL."
                )

    # Every 'Table'[Column] reference in measure DAX must resolve. Renaming a
    # column only rewrites the column header, so measures silently rot otherwise.
    known = {
        t.Name: {c.Name for c in t.Columns} | {x.Name for x in t.Measures}
        for t in model.Tables
    }
    for table in model.Tables:
        for measure in table.Measures:
            for ref_tbl, ref_col in _DAX_REF_RE.findall(str(measure.Expression)):
                if ref_tbl not in known:
                    errors.append(
                        f"measure {table.Name}[{measure.Name}] references table "
                        f"{ref_tbl!r}, which does not exist."
                    )
                elif ref_col not in known[ref_tbl]:
                    errors.append(
                        f"measure {table.Name}[{measure.Name}] references "
                        f"{ref_tbl!r}[{ref_col!r}], which does not exist. "
                        f"A rename only rewrites the column header -- update the DAX too."
                    )

    # 2+ active relationships between the same table pair (PBI ambiguity)
    pair_counts = Counter(
        frozenset((r.FromTable.Name, r.ToTable.Name))
        for r in model.Relationships if r.IsActive
    )
    for pair, n in pair_counts.items():
        if n >= 2:
            errors.append(
                f"{n} active relationships between {sorted(pair)}. "
                f"PBI will throw 'ambiguous paths'. Mark at most one active per pair."
            )

    # More than one filter path between any two tables, however many hops -- the
    # pair-count check above only sees duplicate relationships on a single pair,
    # so it misses longer cycles.
    for a, b, routes in _ambiguous_paths(model):
        shown = "; ".join(" -> ".join(p) for p in routes[:3])
        errors.append(
            f"{len(routes)} filter paths from {a!r} to {b!r}: {shown}. "
            f"PBI allows only one. Drop a relationship or mark one inactive."
        )

    # semantic-model YAML entities are the join authority; every entity's expr
    # must name a real column, and every foreign entity needs a matching primary
    # elsewhere, or a typo silently drops a join instead of failing loudly.
    for e in validate_relationships(config):
        errors.append(f"semantic model: {e}")

    if errors:
        for e in errors:
            print(f"TMDL VALIDATE: {e}")
        raise SystemExit(f"TMDL validation failed: {len(errors)} issue(s)")
    print("TMDL: validation passed.")
