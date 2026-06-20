#!/usr/bin/env python3
"""
Generate a lean Mode A repo-packet.md that includes project context +
only the source files relevant to planted issues.
"""
import json, pathlib

FIXTURE = pathlib.Path('/home/dev/goblinbench/fixtures/codebase-analysis/den-core-v1')
REPO = FIXTURE / 'repo'
DOCS = FIXTURE / 'docs'

# Files that contain planted issues or are needed for structural understanding
KEY_FILES = [
    'src/DenCore/Models/ProjectTask.cs',
    'src/DenCore/Models/Message.cs',
    'src/DenCore/Models/Document.cs',
    'src/DenCore/Models/WorkerPoolModels.cs',
    'src/DenCore/Models/Enums.cs',
    'src/DenCore/Data/MessageRepository.cs',
    'src/DenCore/Data/TaskRepository.cs',
    'src/DenCore/Data/DocumentRepository.cs',
    'src/DenCore/Data/WorkerPoolRepository.cs',
    'src/DenCore/Data/DispatchRepository.cs',
    'src/DenCore/Data/DatabaseInitializer.cs',
    'src/DenCore/Services/ReviewWorkflowService.cs',
    'src/DenCore/Services/WorkerLifecycleService.cs',
    'src/DenCore/Services/StaleAttentionRoutingService.cs',
    'src/DenCore.Service/Program.cs',
    'src/DenCore.Service/Routes/MessageRoutes.cs',
    'src/DenCore.Service/Routes/TaskRoutes.cs',
    'src/DenCore.Service/Routes/DocumentRoutes.cs',
    'src/DenCore.Service/Routes/WorkerRoutes.cs',
    'src/DenCore.Service/Tools/CompletionTools.cs',
]

DOC_FILES = [
    'docs/architecture-brief.md',
    'docs/api-contract.md',
    'docs/deployment.md',
]

lines = []
lines.append('# DenCore v1 — Codebase Analysis Fixture')
lines.append('')
lines.append('## Project Brief')
lines.append('')
lines.append('A synthetic C# .NET minimal-API service mimicking DenCore, ')
lines.append('the central orchestration service for the Den intelligent agent platform.')
lines.append('It exposes REST and MCP tool endpoints for task management, messaging,')
lines.append('document storage, worker pool orchestration, and LLM-powered context retrieval.')
lines.append('')

# Architecture brief
ab = DOCS / 'architecture-brief.md'
if ab.exists():
    lines.append('## Architecture')
    lines.append('')
    for line in ab.read_text().splitlines():
        lines.append(line)
    lines.append('')

# API contract
ac = DOCS / 'api-contract.md'
if ac.exists():
    lines.append('## API Contract')
    lines.append('')
    for line in ac.read_text().splitlines():
        lines.append(line)
    lines.append('')

# Source files
for rel in KEY_FILES:
    fp = REPO / rel
    if not fp.exists():
        print(f'WARNING: {rel} not found')
        continue
    lines.append(f'## {rel}')
    lines.append('')
    lines.append('```csharp')
    content = fp.read_text()
    lines.append(content)
    lines.append('```')
    lines.append('')

# Doc files
for rel in DOC_FILES:
    fp = FIXTURE / rel
    if not fp.exists():
        continue
    lines.append(f'## {rel}')
    lines.append('')
    for line in fp.read_text().splitlines():
        lines.append(line)
    lines.append('')

output = '\n'.join(lines)
outpath = FIXTURE / 'repo-packet.md'
outpath.write_text(output)

print(f'Packet written: {outpath}')
print(f'Size: {len(output)} chars, {len(output.splitlines())} lines')
print(f'~{len(output)//4} estimated tokens')
