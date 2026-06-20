# DenCore v1 — Architecture Brief

## Overview

DenCore is the central service for the Den intelligent agent platform. It provides task management, messaging, document storage, worker pool orchestration, MCP tool routing, and LLM integration for agent-to-agent and agent-to-human collaboration.

## High-Level Architecture

```
┌──────────────────────────────────────────────────────┐
│                   DenCore.Service                     │
│  (ASP.NET Minimal API — Kestrel host, SQLite store)  │
│                                                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │  Routes   │ │  Tools   │ │  MCP     │ │  LLM     │ │
│  │ (REST)    │ │ (MCP)    │ │ Registry │ │ Client   │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│       │             │            │             │        │
│  ┌────┴─────────────┴────────────┴─────────────┴─────┐ │
│  │                  Services                          │ │
│  │  ReviewWorkflow  │  StaleAttention │  WorkerLife   │ │
│  └────────────────────────┬──────────────────────────┘ │
│                           │                             │
│  ┌────────────────────────┴──────────────────────────┐ │
│  │               Data Layer (Repositories)            │ │
│  │  Dapper + SQLite — tasks, messages, documents,     │ │
│  │  pool_members, worker_assignments, dispatch_queue  │ │
│  └───────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

## Key Components

### Models (`DenCore/Models/`)
Core domain types: `ProjectTask`, `Message`, `Document`, `PoolMember`, `WorkerAssignment`, `DispatchEntry`, `TaskHistory`, gateway contracts, and enumerations. Uses C# records with nullable reference types.

### Data Layer (`DenCore/Data/`)
Dapper-based SQLite repositories. Each repository owns its connection management. `DatabaseInitializer` creates schema and pre-loads config cache on startup.

### Services (`DenCore/Services/`)
- **ReviewWorkflowService**: Manages review lifecycle with a per-session verdict cache.
- **StaleAttentionRoutingService**: Background monitor for idle tasks.
- **WorkerLifecycleService**: Assignment/release orchestration for pool members.

### MCP (`DenCore/Mcp/`)
Tool profile registry mapping MCP tool names to schemas and handler routes. Used by the tool routing layer.

### LLM (`DenCore/Llm/`)
OpenAI-compatible client for completions and structured output. Used by the Librarian for context summarization.

### Service Layer (`DenCore.Service/`)
Minimal API endpoints for REST (routes) and MCP tool handlers (tools). Startup in `Program.cs` wires everything together.

## Data Flow

1. **Agent sends message** → `MessageRoutes` → `MessageRepository` → SQLite
2. **Worker assigned to task** → `WorkerRoutes` → `WorkerLifecycleService` → `WorkerPoolRepository`
3. **Review requested** → `ReviewWorkflowService` caches verdict
4. **Background dispatch** → `DispatchRepository.RunBackgroundLoopAsync()` polls queue
5. **LLM summarization** → `LibrarianService` → `OpenAiCompatibleLlmClient`

## Database

SQLite with 10 core tables. Connection string configurable via `ConnectionStrings:DefaultConnection`. Schema auto-created on startup.

## Decision Records

- **SQLite**: Simple single-file storage suitable for single-node deployment.
- **Dapper**: Lightweight ORM — full control over SQL, no EF Core overhead.
- **In-memory caching**: TaskRepository and ReviewWorkflowService use dictionaries for fast reads. Database remains authoritative source of truth.
- **Minimal API**: Modern ASP.NET pattern with less boilerplate than controllers.
- **MCP over HTTP**: Tool endpoints are HTTP POST handlers; no WebSocket transport in v1.
