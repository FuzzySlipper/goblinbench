#!/usr/bin/env python3
"""
Generate a Mode A repo-packet.md that includes full source file contents inline.

Usage:
    python3 scripts/generate-packet.py [--fixture fixtures/codebase-analysis/den-core-v1]

Produces: <fixture>/repo-packet.md
"""
import argparse, json, pathlib

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', default='fixtures/codebase-analysis/den-core-v1',
                        help='Path to fixture directory containing repo/ and docs/')
    args = parser.parse_args()

    fixdir = pathlib.Path(args.fixture).resolve()
    repo = fixdir / 'repo'
    docs = fixdir / 'docs'

    lines = []
    lines.append('# Codebase Analysis Fixture')
    lines.append('')
    lines.append('## Project Brief')
    lines.append('')
    lines.append('A synthetic C# .NET minimal-API service for architectural codebase analysis evaluation.')
    lines.append('')

    # Directory tree
    lines.append('## Directory Structure')
    lines.append('')
    lines.append('```')
    for p in sorted(repo.rglob('*')):
        if not p.is_dir():
            lines.append(f'  {p.relative_to(fixdir)}')
    for p in sorted(docs.rglob('*')):
        if p.is_file():
            lines.append(f'  {p.relative_to(fixdir)}')
    lines.append('```')
    lines.append('')

    # Doc files (architecture, API, deployment)
    for md_file in sorted(docs.rglob('*.md')):
        lines.append(f'## {md_file.relative_to(fixdir)}')
        lines.append('')
        for line in md_file.read_text().splitlines():
            lines.append(line)
        lines.append('')

    # Gold ledger summary (id + severity only — no hint leakage)
    gl = fixdir / 'gold-ledger.json'
    if gl.exists():
        data = json.load(open(gl))
        issues = data.get('issues', data) if isinstance(data, dict) else data
        lines.append('## Known Issues')
        lines.append('')
        for g in issues:
            lines.append(f'- [{g.get("severity", "?")}] {g["id"]} ({g.get("category", "?")})')
        lines.append('')

    # Source files — embed full content inline
    import os
    for suffix in ('.cs', '.csproj', '.md'):
        for p in sorted(repo.rglob(f'*{suffix}')):
            if not p.is_file() or 'obj' in p.parts or 'bin' in p.parts:
                continue
            rel = p.relative_to(fixdir)
            lang = {'cs': 'csharp', 'csproj': 'xml', 'md': 'markdown'}.get(suffix.lstrip('.'), '')
            lines.append(f'## {rel}')
            lines.append('')
            lines.append(f'```{lang}')
            lines.append(p.read_text().rstrip('\n'))
            lines.append('```')
            lines.append('')

    output = '\n'.join(lines)
    outpath = fixdir / 'repo-packet.md'
    outpath.write_text(output)
    print(f'Packet: {outpath} ({len(output)} chars, {len(output.splitlines())} lines)')


if __name__ == '__main__':
    main()
