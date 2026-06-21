"""GoblinBench report tool — static HTML report generation."""

from .envelope import render_page  # noqa: E402  (no views import → no cycle)


def get_views():
    """ Lazily import the views module so its registration side-effects run.

    Views import from ``gb.report.envelope`` (sibling) and ``gb.store`` (uncle),
    not from this package's top level — so importing them here, after this
    module is fully initialized, avoids the circular import.
    """
    from . import views  # noqa: F401  (registration side-effect)
    return views.VIEW_REGISTRY


__all__ = ["render_page", "get_views"]
