"""Read-only Unity Catalog operations over a user-scoped WorkspaceClient."""

from collections.abc import Iterable
from itertools import islice
from typing import Any

from databricks.sdk import WorkspaceClient

MAX_LIMIT = 500


def _take(items: Iterable[Any], limit: int) -> tuple[list[Any], bool]:
    limit = max(1, min(limit, MAX_LIMIT))
    got = list(islice(items, limit + 1))
    return got[:limit], len(got) > limit


def _enum(value: Any) -> str | None:
    return value.value if value is not None else None


def _named(items: Iterable[Any], limit: int) -> dict[str, Any]:
    got, truncated = _take(items, limit)
    return {
        "items": [{"name": i.name, "comment": i.comment, "owner": i.owner} for i in got],
        "truncated": truncated,
    }


def list_catalogs(w: WorkspaceClient, limit: int = 100) -> dict[str, Any]:
    return _named(w.catalogs.list(), limit)


def list_schemas(w: WorkspaceClient, catalog: str, limit: int = 100) -> dict[str, Any]:
    return _named(w.schemas.list(catalog_name=catalog), limit)


def list_tables(w: WorkspaceClient, catalog: str, schema: str, limit: int = 100) -> dict[str, Any]:
    got, truncated = _take(w.tables.list(catalog_name=catalog, schema_name=schema, omit_columns=True, omit_properties=True), limit)
    return {
        "items": [
            {"name": t.name, "full_name": t.full_name, "table_type": _enum(t.table_type), "comment": t.comment}
            for t in got
        ],
        "truncated": truncated,
    }


def describe_table(w: WorkspaceClient, full_name: str) -> dict[str, Any]:
    t = w.tables.get(full_name=full_name)
    return {
        "full_name": t.full_name,
        "table_type": _enum(t.table_type),
        "data_source_format": _enum(t.data_source_format),
        "owner": t.owner,
        "comment": t.comment,
        "columns": [
            {"name": c.name, "type_text": c.type_text, "nullable": c.nullable, "comment": c.comment}
            for c in (t.columns or [])
        ],
    }
