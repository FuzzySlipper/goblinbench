# DenCore v1 — API Contract

## Base URL

```
http://localhost:5000
```

## Authentication

All endpoints require a valid API key in the `X-Api-Key` header. *(Not yet implemented in v1.)*

## Endpoints

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health check |

### Tasks

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tasks?projectId={id}` | List tasks in a project |
| GET | `/api/tasks/{id}` | Get task by ID |
| POST | `/api/tasks` | Create a new task |
| GET | `/api/tasks/{id}/messages` | Get messages for a task (offset pagination) |

### Messages

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/messages?projectId={id}&cursor={c}&limit={n}` | List messages (cursor pagination) |
| GET | `/api/messages/{id}` | Get message by ID |
| POST | `/api/messages` | Send a message |

### Documents

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/documents/{id}` | Get document by ID |
| GET | `/api/documents/by-slug/{projectId}/{slug}` | Get document by project + slug |
| POST | `/api/documents` | Create document |
| PUT | `/api/documents/{id}` | Update document |
| DELETE | `/api/documents/{id}` | Delete document |
| GET | `/api/documents?projectId={id}` | List documents |

### Workers

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/workers?role={role}` | List workers (optional role filter) |
| POST | `/api/workers/register` | Register a pool member |
| POST | `/api/workers/assign` | Assign worker to task |
| POST | `/api/workers/release` | Release worker from assignment |
| GET | `/api/workers/assignments?projectId={id}` | List active assignments |

### MCP Tools

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/tools/send-message` | Send a message (MCP) |
| POST | `/api/tools/get-messages` | Get messages (MCP) |
| POST | `/api/tools/list-tasks` | List tasks (MCP) |
| POST | `/api/tools/get-task` | Get task (MCP) |
| POST | `/api/tools/create-task` | Create task (MCP) |
| POST | `/api/tools/worker-complete` | Report worker completion |
| POST | `/api/tools/heartbeat` | Worker heartbeat |
| POST | `/api/tools/triage-complete` | Triage completion signal |
| POST | `/api/tools/generate-summary` | Generate context summary |

## Pagination

- **Messages (REST)**: Cursor-based. Response includes `nextCursor` field.
- **Task Messages (sub-resource)**: Offset-based. Uses `pageNumber` and `pageSize`.
- **Documents**: No pagination in v1.

## Error Responses

```json
{
  "error": "description of the problem"
}
```

Standard HTTP codes: 200, 201, 204, 400, 404, 409, 500.
