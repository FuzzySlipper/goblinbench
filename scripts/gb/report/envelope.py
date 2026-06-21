"""HTML envelope + escaping helpers shared by all views.

Views return HTML fragments; this module wraps them in a stable page shell
(CSS + a scope header + the narrative slot + the view fragment). Keeping the
chrome here means a view only ever produces its own content — no view re-
implements the <head>/CSS.
"""

from __future__ import annotations

import html as _html
from datetime import datetime, timezone


PAGE_CSS = """
:root { color-scheme: light dark; }
body { font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
       max-width: 1200px; margin: 0 auto; padding: 24px; color: #1a1a1a; background: #fff; }
@media (prefers-color-scheme: dark) { body { color: #e0e0e0; background: #1a1a1a; } }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 24px 0 8px; border-bottom: 1px solid #888; padding-bottom: 4px; }
.scope { color: #666; font-size: 12px; margin-bottom: 16px; }
@media (prefers-color-scheme: dark) { .scope { color: #999; } }
.narrative { background: #f5f5f5; padding: 12px 16px; border-radius: 6px; margin: 12px 0 20px;
             border-left: 3px solid #4a90d9; }
@media (prefers-color-scheme: dark) { .narrative { background: #2a2a2a; } }
.narrative p { margin: 0.5em 0; }
.narrative p:first-child { margin-top: 0; }
.narrative p:last-child { margin-bottom: 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; }
th, td { padding: 4px 8px; text-align: left; border-bottom: 1px solid #ddd; font-size: 13px; }
@media (prefers-color-scheme: dark) { th, td { border-color: #444; } }
th { background: #f0f0f0; font-weight: 600; cursor: pointer; user-select: none; }
@media (prefers-color-scheme: dark) { th { background: #2a2a2a; } }
th.sorted-asc::after { content: " ▲"; }
th.sorted-desc::after { content: " ▼"; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
td.pass { color: #1a7a1a; font-weight: 600; }
td.fail { color: #c62828; font-weight: 600; }
@media (prefers-color-scheme: dark) { td.pass { color: #6bcb6b; } td.fail { color: #ff6b6b; } }
.cats { font-size: 11px; color: #888; }
.sample { margin: 8px 0; }
.sample-label { font-size: 12px; color: #666; font-family: ui-monospace, monospace; }
pre, code { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 12px; }
pre { background: #f5f5f5; padding: 8px 12px; border-radius: 4px; overflow-x: auto; }
@media (prefers-color-scheme: dark) { pre { background: #2a2a2a; } }
details { margin: 4px 0; }
summary { cursor: pointer; font-size: 12px; color: #4a90d9; }
.cell-detail { padding: 8px 0; }
.muted { color: #888; font-size: 11px; }
.footer { margin-top: 40px; padding-top: 12px; border-top: 1px solid #ddd; font-size: 11px; color: #999; }
"""


def esc(text: str | None) -> str:
    """HTML-escape."""
    return _html.escape(text or "", quote=True)


def render_page(
    *, title: str, scope: dict[str, str], narrative: str, view_html: str,
    footnotes: list[str], generated_by: str,
) -> str:
    """Wrap a view fragment in the page shell with the narrative as the lede."""
    scope_bits = [f"{k}: <code>{esc(v)}</code>" for k, v in scope.items() if v]
    scope_html = (" · " if scope_bits else "") .join(scope_bits)
    # Narrative comes in as markdown-ish text; render paragraphs.
    narrative_html = "".join(
        f"<p>{esc(p)}</p>" for p in (narrative or "").split("\n\n") if p.strip()
    )
    footnotes_html = (
        "<ul>" + "".join(f"<li>{esc(f)}</li>" for f in footnotes) + "</ul>"
        if footnotes else ""
    )
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{esc(title)}</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<h1>{esc(title)}</h1>
<div class="scope">{scope_html}</div>
{('<div class="narrative">' + narrative_html + '</div>') if narrative_html else ''}
{view_html}
{('<h2>Notes</h2>' + footnotes_html) if footnotes_html else ''}
<div class="footer">Generated {generated_at} by {esc(generated_by)} · data from the GoblinBench store</div>
</body>
</html>
"""
