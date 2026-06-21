"""GoblinBench runner package.

The Python package is the canonical in-repo execution layer. It discovers
scenarios under ``suites/``, dispatches candidates through registered runners,
produces ``runs/<run-id>/`` artifacts, and feeds the canonical SQLite store.
"""
