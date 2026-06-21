"""Report views — each view is a self-contained module exporting a render function.

Adding a view:
  1. Create a module here (e.g. ``model_profile.py``) with a ``render(ctx)``
     function returning a ``ViewResult`` (title, html, optional footnotes).
  2. Register it in ``VIEW_REGISTRY`` below with a stable id and CLI metadata.
  3. Add any new filter parameters it needs to ``ViewContext``.

Views never touch the filesystem or query the DB directly — they read from the
``ViewContext`` (which holds pre-fetched rows + a store connection for lazy
artifact fetches). This keeps view code pure-Python over data and makes the
views trivially testable + recombinable. The report entrypoint (gb-report.py)
owns the DB query, the view dispatch, the HTML envelope, and file writing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ...store import open_db


@dataclass
class ViewContext:
    """Everything a view needs: pre-fetched cells + lazy store access.

    ``cells`` is the already-filtered set of candidate_results (as dicts) the
    view should render. ``filters`` echoes the applied filters (for the
    report's "scope" header). ``conn`` is open for the lifetime of the render
    so views can lazily fetch artifacts/samples without each opening the DB.
    """
    conn: Any  # sqlite3.Connection
    cells: list[dict[str, Any]]
    filters: dict[str, Any] = field(default_factory=dict)
    repo_root: str = ""
    embed: str = "patch"  # what artifacts to inline (patch|stdout|output|none)


@dataclass
class ViewResult:
    """What a view returns: an HTML fragment + metadata for the page."""
    title: str
    html: str  # fragment (no <html>/<body> — the envelope owns those)
    footnotes: list[str] = field(default_factory=list)


def fetch_artifact_bytes(ctx: ViewContext, cr_id: int, name: str) -> bytes | None:
    """Lazy fetch of an inline artifact's bytes. Returns None if missing/external."""
    row = ctx.conn.execute(
        "SELECT content_bytes, external_path FROM artifacts WHERE candidate_result_id=? AND name=?",
        (cr_id, name),
    ).fetchone()
    if row is None:
        return None
    if row["content_bytes"] is not None:
        return row["content_bytes"]
    # External (size-tiered): read from disk if still present.
    if row["external_path"]:
        import os
        p = os.path.join(ctx.repo_root, row["external_path"])
        try:
            with open(p, "rb") as f:
                return f.read()
        except OSError:
            return None
    return None


def fetch_samples(ctx: ViewContext, cr_id: int, kind: str | None = None) -> list[dict[str, Any]]:
    """Lazy fetch of representative samples for a cell."""
    if kind is not None:
        return [dict(r) for r in ctx.conn.execute(
            "SELECT kind, label, language, content, source_path FROM representative_samples "
            "WHERE candidate_result_id=? AND kind=? ORDER BY label",
            (cr_id, kind),
        )]
    return [dict(r) for r in ctx.conn.execute(
        "SELECT kind, label, language, content, source_path FROM representative_samples "
        "WHERE candidate_result_id=? ORDER BY kind, label",
        (cr_id,),
    )]


# Registry populated in __init__ after view modules are imported.
VIEW_REGISTRY: dict[str, dict[str, Any]] = {}


def register(view_id: str, name: str, description: str, render: Callable[[ViewContext], ViewResult]) -> None:
    VIEW_REGISTRY[view_id] = {"id": view_id, "name": name, "description": description, "render": render}


# Import view modules for their side-effects (they call register() at import).
from . import grid_view, failures_view, cell_view  # noqa: E402,F401  (registration side-effect)

__all__ = [
    "ViewContext", "ViewResult", "VIEW_REGISTRY", "register",
    "fetch_artifact_bytes", "fetch_samples", "open_db",
]
