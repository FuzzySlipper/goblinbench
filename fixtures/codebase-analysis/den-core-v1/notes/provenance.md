# Fixture Provenance: den-core-v1

## Purpose

This fixture is a synthetic C# .NET service that mimics den-core's architecture — task management, messages, documents, worker pool, MCP tool profiles, background dispatch, LLM librarian. It is the frozen test target for the codebase analysis benchmark.

## Generation

- **Date**: 2026-06-15
- **Method**: Generated programmatically by Hermes Agent from a detailed spec
- **Model**: deepseek-v4-flash

## File Inventory

```
repo/
  DenCore.sln
  src/
    DenCore/
      DenCore.csproj
      Models/   — 9 files (Enums.cs, Message.cs, ProjectTask.cs, Document.cs,
                   WorkerPoolModels.cs, DispatchEntry.cs, TaskHistory.cs,
                   GatewayContract.cs, DirectDeliveryContract.cs)
      Data/     — 6 files (MessageRepository.cs, TaskRepository.cs,
                   DocumentRepository.cs, WorkerPoolRepository.cs,
                   DatabaseInitializer.cs, DispatchRepository.cs)
      Services/ — 3 files (ReviewWorkflowService.cs,
                   StaleAttentionRoutingService.cs, WorkerLifecycleService.cs)
      Mcp/      — 2 files (McpToolProfileRegistry.cs, McpToolProfiles.cs)
      Llm/      — 3 files (ILlmClient.cs, OpenAiCompatibleLlmClient.cs,
                   LibrarianService.cs)
    DenCore.Service/
      DenCore.Service.csproj
      Program.cs
      Routes/   — 4 files (MessageRoutes.cs, TaskRoutes.cs, WorkerRoutes.cs,
                   DocumentRoutes.cs)
      Tools/    — 4 files (MessageTools.cs, TaskTools.cs, WorkerTools.cs,
                   CompletionTools.cs)
docs/
  architecture-brief.md
  api-contract.md
  deployment.md
gold-ledger.json     — 12 planted issues
decoys.json           — 4 decoy entries
notes/
  provenance.md       — this file
repo-packet.md        — analysis entry-point packet
```

## Planted Issues

The gold-ledger.json contains 12 issues across 3 severity levels:

- **Critical (1):** exception-in-background-loop
- **High (2):** contract-paging-mismatch, worker-release-before-completion
- **Medium (6):** stale-review-verdict, hardcoded-lan-ip, core-mcp-boundary-leak,
  health-check-ignores-db, tool-schema-description-mismatch, assignment-release-null-state
- **Low (3):** singleton-cache-no-lock, documentation-contradiction, missing-404-test

## Decoys

The decoys.json contains 4 entries that might appear suspicious on first glance
but are architecturally valid decisions.

## Verifying the Fixture

A complete codebase analysis should:
1. Identify all 12 issues with correct severity and scope
2. Produce acceptable diagnoses matching those in gold-ledger.json
3. Not flag the 4 decoys as issues
4. Provide concrete fix proposals matching good_fix_properties

## Note on Compilation

Some files contain intentional logical errors but are structurally valid C#.
The fixture may not compile due to:
- Missing using directives in some route files (WebApplication, Results)
- Program.cs has a DI circular dependency (MessageRepository instantiated before DI is built)
- These are NOT planted issues; they are artifacts of the fixture being a synthetic target

The benchmark should evaluate the codebase as-is for architectural analysis,
not attempt to compile and run it.
