#!/usr/bin/env python3
"""GoblinBench pi-crew worker/profile suitability matrix.

This is intentionally a standalone script, not a GoblinBench .NET runner
scenario: pi-crew worker evaluation needs to drive Den MCP assignment lifecycle
tools directly.

Important model/profile boundary
--------------------------------
A Den worker lease selects a configured pool member/profile. It does *not* pass
an arbitrary model name to pi-crew. Therefore this script treats the configured
profile model as the tested model unless you supply an explicit matrix JSON that
corresponds to separately configured profiles/members. Do not build a fake
cross-product of den-router model names x worker identities unless pi-crew has
actually been reconfigured to expose those combinations.

Modes
-----
  plan       : no Den writes; emits the matrix plan/report skeleton.
  preflight  : raw MCP initialize + tools/list + optional pool discovery; no Den writes.
  automated  : creates one child Den task per cell, leases workers, monitors,
               validates artifacts, and writes results. Requires --execute-live.
  import     : ingests externally collected handles/results and scores/writes them.

Outputs
-------
  <runs-root>/pi-crew-matrix-<timestamp>/plan.json
  <runs-root>/pi-crew-matrix-<timestamp>/matrix.json
  <runs-root>/pi-crew-matrix-<timestamp>/matrix.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import requests

DEFAULT_MCP_URL = "http://192.168.1.10:5199/mcp"
DEFAULT_PROJECT_ID = "pi-crew"
DEFAULT_PARENT_TASK_ID = 2283
DEFAULT_RUNS_ROOT = Path(__file__).resolve().parents[2] / "runs"
DEFAULT_PROFILE_ROOT = Path("/home/agents/pi-crew/profiles")
DEFAULT_ARTIFACT_PROJECT = "pi-crew"
DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 900
TERMINAL_ASSIGNMENT_STATES = {"completed", "failed", "blocked", "cancelled", "expired", "released"}
VALID_COMPLETION_STATES = {"present", "valid"}

FALLBACK_POOL_MEMBERS = [
    {"worker_identity": "pi-crew-coder-1", "role": "coder", "profile_identity": "pi-crew-coder-worker", "profile_id": "coder-worker"},
    {"worker_identity": "pi-crew-coder-2", "role": "coder", "profile_identity": "pi-crew-coder-worker", "profile_id": "coder-worker"},
    {"worker_identity": "pi-crew-coder-3", "role": "coder", "profile_identity": "pi-crew-coder-worker", "profile_id": "coder-worker"},
    {"worker_identity": "pi-crew-coder-4", "role": "coder", "profile_identity": "pi-crew-coder-worker", "profile_id": "coder-worker"},
    {"worker_identity": "pi-crew-reviewer-1", "role": "reviewer", "profile_identity": "pi-crew-reviewer-worker", "profile_id": "reviewer-worker"},
    {"worker_identity": "pi-crew-reviewer-2", "role": "reviewer", "profile_identity": "pi-crew-reviewer-worker", "profile_id": "reviewer-worker"},
]


# ---------------------------------------------------------------------------
# Small data helpers
# ---------------------------------------------------------------------------
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(value: str) -> str:
    value = value.lower().replace("_", "-")
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:90] or "cell"


def make_run_id(prefix: str = "piw-goblinbench") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    digest = hashlib.sha1(f"{stamp}-{time.time_ns()}".encode()).hexdigest()[:8]
    return f"{prefix}-{stamp}-{digest}"


def deep_get(obj: Any, *paths: str, default: Any = None) -> Any:
    """Try dotted paths against nested dicts/lists."""
    for path in paths:
        cur = obj
        ok = True
        for part in path.split("."):
            if isinstance(cur, Mapping) and part in cur:
                cur = cur[part]
            elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
                cur = cur[int(part)]
            else:
                ok = False
                break
        if ok:
            return cur
    return default


def parse_json_maybe(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text and text[0] in "[{\"":
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def normalize_tool_payload(payload: Any) -> Any:
    """Handle Den MCP text blocks that sometimes contain JSON-in-JSON."""
    payload = parse_json_maybe(payload)
    if isinstance(payload, Mapping) and "result" in payload and len(payload) <= 2:
        result = parse_json_maybe(payload["result"])
        return result
    return payload


# ---------------------------------------------------------------------------
# Raw streamable HTTP MCP client
# ---------------------------------------------------------------------------
class McpClient:
    def __init__(self, base_url: str, *, tool_profile: str = "runner", timeout: int = 30) -> None:
        self.base_url = self._with_tool_profile(base_url, tool_profile)
        self.timeout = timeout
        self.session_id: str | None = None
        self._next_id = 1

    @staticmethod
    def _with_tool_profile(base_url: str, tool_profile: str) -> str:
        parsed = urlparse(base_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if tool_profile:
            query["tool_profile"] = tool_profile
        return urlunparse(parsed._replace(query=urlencode(query)))

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream, application/json"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    @staticmethod
    def _parse_response(resp: requests.Response, context: str) -> Any:
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            body = resp.text[:1000].replace("\n", "\\n")
            raise RuntimeError(f"HTTP {resp.status_code} during {context}: {body}") from exc

        text = resp.text.strip()
        if not text:
            return None

        # Streamable HTTP returns SSE lines: event: message / data: {...}
        data_lines = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if data_lines:
            text = "\n".join(data_lines)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Non-JSON response during {context}: {text[:1000]}") from exc

        if isinstance(parsed, Mapping) and parsed.get("error"):
            raise RuntimeError(f"MCP error during {context}: {parsed['error']}")
        return parsed

    def initialize(self) -> None:
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "goblinbench-pi-crew-matrix", "version": "0.2.0"},
            },
        }
        self._next_id += 1
        resp = requests.post(self.base_url, json=body, headers=self._headers(), timeout=self.timeout)
        parsed = self._parse_response(resp, "initialize")
        self.session_id = resp.headers.get("Mcp-Session-Id") or deep_get(parsed, "result.sessionId")
        if not self.session_id:
            raise RuntimeError("initialize succeeded but no Mcp-Session-Id header was returned")

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if method != "initialize" and not self.session_id:
            raise RuntimeError("MCP client is not initialized")
        body = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params or {}}
        self._next_id += 1
        resp = requests.post(self.base_url, json=body, headers=self._headers(), timeout=self.timeout)
        parsed = self._parse_response(resp, method)
        return deep_get(parsed, "result", default=parsed)

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.rpc("tools/list")
        return list(result.get("tools", [])) if isinstance(result, Mapping) else []

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        result = self.rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if isinstance(result, Mapping) and result.get("isError"):
            raise RuntimeError(f"Tool {name} returned isError=true: {result.get('content')}")
        if isinstance(result, Mapping) and isinstance(result.get("content"), list):
            blocks = result["content"]
            if blocks and isinstance(blocks[0], Mapping) and blocks[0].get("type") == "text":
                return normalize_tool_payload(blocks[0].get("text", ""))
        return normalize_tool_payload(result)


# ---------------------------------------------------------------------------
# Profile/pool discovery
# ---------------------------------------------------------------------------
def parse_profile_yaml(path: Path) -> dict[str, str]:
    """Extract only non-secret modelConfig fields from simple profile YAML."""
    fields: dict[str, str] = {}
    if not path.exists():
        return fields
    in_model_config = False
    model_indent: int | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if stripped == "modelConfig:":
            in_model_config = True
            model_indent = indent
            continue
        if in_model_config and model_indent is not None and indent <= model_indent:
            break
        if in_model_config and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip().strip('"\'')
            if key in {"provider", "model", "baseUrl", "maxTokens", "temperature"}:
                fields[key] = value
    return fields


def load_profile_models(profile_root: Path) -> dict[str, dict[str, str]]:
    models: dict[str, dict[str, str]] = {}
    if not profile_root.exists():
        return models
    for path in sorted(profile_root.glob("*/profile.yaml")):
        profile_id = path.parent.name
        fields = parse_profile_yaml(path)
        if fields:
            models[profile_id] = fields
    for path in sorted(profile_root.glob("*.profile.yaml")):
        profile_id = path.name.replace(".profile.yaml", "")
        fields = parse_profile_yaml(path)
        if fields:
            models[profile_id] = fields
    return models


def metadata_profile_id(member: Mapping[str, Any]) -> str | None:
    metadata = parse_json_maybe(member.get("metadata"))
    if isinstance(metadata, Mapping):
        return metadata.get("profile_id") or metadata.get("profileId")
    return member.get("profile_id") or member.get("profileId")


def normalize_pool_members(raw: Any) -> list[dict[str, Any]]:
    raw = normalize_tool_payload(raw)
    members = []
    if isinstance(raw, Mapping):
        members = raw.get("members") or raw.get("pool_members") or []
    elif isinstance(raw, list):
        members = raw
    normalized = []
    for member in members:
        if not isinstance(member, Mapping):
            continue
        worker_identity = member.get("worker_identity") or member.get("identity") or member.get("workerIdentity")
        role = member.get("worker_role") or member.get("role") or member.get("workerRole")
        profile_identity = member.get("profile_identity") or member.get("profileIdentity")
        if worker_identity and role and profile_identity:
            normalized.append({
                "worker_identity": worker_identity,
                "role": role,
                "profile_identity": profile_identity,
                "profile_id": metadata_profile_id(member),
                "status": member.get("status"),
                "capabilities": parse_json_maybe(member.get("capabilities")),
            })
    return normalized


def discover_pool_members(client: McpClient) -> list[dict[str, Any]]:
    raw = client.call_tool("list_pool_members", {"limit": 200, "verbose": True})
    members = normalize_pool_members(raw)
    return [m for m in members if str(m.get("worker_identity", "")).startswith("pi-crew-")]


# ---------------------------------------------------------------------------
# Matrix construction and task prompts
# ---------------------------------------------------------------------------
@dataclass
class MatrixCell:
    idx: int
    worker_identity: str
    role: str
    profile_identity: str
    profile_id: str | None
    provider: str
    model: str
    artifact_kind: str
    campaign_id: str
    artifact_slug: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "idx": self.idx,
            "worker_identity": self.worker_identity,
            "role": self.role,
            "profile_identity": self.profile_identity,
            "profile_id": self.profile_id,
            "provider": self.provider,
            "model": self.model,
            "artifact_kind": self.artifact_kind,
            "campaign_id": self.campaign_id,
            "artifact_slug": self.artifact_slug,
            "model_source": "profile_config",
        }


def configured_model_for(member: Mapping[str, Any], profile_models: Mapping[str, Mapping[str, str]]) -> tuple[str, str]:
    profile_id = member.get("profile_id") or metadata_profile_id(member) or ""
    profile_identity = str(member.get("profile_identity") or "")
    candidates = [str(profile_id), profile_identity.replace("pi-crew-", "").removesuffix("-worker") + "-worker"]
    for candidate in candidates:
        if candidate in profile_models:
            fields = profile_models[candidate]
            return fields.get("provider", "unknown"), fields.get("model", "unknown")
    return "configured", "unknown"


def select_representative_members(members: Sequence[dict[str, Any]], *, all_lanes: bool) -> list[dict[str, Any]]:
    if all_lanes:
        return list(members)
    selected: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    for member in members:
        role = str(member.get("role"))
        if role in {"coder", "reviewer"} and role not in seen_roles:
            selected.append(member)
            seen_roles.add(role)
    return selected


def build_matrix(
    members: Sequence[dict[str, Any]],
    profile_models: Mapping[str, Mapping[str, str]],
    *,
    campaign_id: str,
    all_lanes: bool = False,
    include_code_change: bool = False,
) -> list[MatrixCell]:
    cells: list[MatrixCell] = []
    for member in select_representative_members(members, all_lanes=all_lanes):
        role = str(member["role"])
        provider, model = configured_model_for(member, profile_models)
        artifact_kinds: list[str]
        if role == "coder":
            artifact_kinds = ["den_document"]
            if include_code_change:
                artifact_kinds.append("code_change")
        elif role == "reviewer":
            artifact_kinds = ["review_finding"]
        else:
            artifact_kinds = ["read_only_inventory"]
        for kind in artifact_kinds:
            idx = len(cells) + 1
            slug = None
            if kind == "den_document":
                slug = slugify(f"{campaign_id}-{idx}-{member['worker_identity']}-{model}")
            cells.append(MatrixCell(
                idx=idx,
                worker_identity=str(member["worker_identity"]),
                role=role,
                profile_identity=str(member["profile_identity"]),
                profile_id=member.get("profile_id"),
                provider=provider,
                model=model,
                artifact_kind=kind,
                campaign_id=campaign_id,
                artifact_slug=slug,
            ))
    return cells


def load_matrix_json(path: Path, campaign_id: str) -> list[MatrixCell]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cells = payload.get("cells", payload) if isinstance(payload, Mapping) else payload
    cells: list[MatrixCell] = []
    for idx, raw in enumerate(raw_cells, 1):
        cells.append(MatrixCell(
            idx=int(raw.get("idx", idx)),
            worker_identity=str(raw["worker_identity"]),
            role=str(raw["role"]),
            profile_identity=str(raw["profile_identity"]),
            profile_id=raw.get("profile_id"),
            provider=str(raw.get("provider", "configured")),
            model=str(raw.get("model", "unknown")),
            artifact_kind=str(raw.get("artifact_kind", "den_document")),
            campaign_id=str(raw.get("campaign_id", campaign_id)),
            artifact_slug=raw.get("artifact_slug"),
        ))
    return cells


def task_description(cell: MatrixCell, *, project_id: str, artifact_project_id: str) -> str:
    common = (
        f"GoblinBench task #2283 matrix cell {cell.idx}.\n"
        f"Configured worker: {cell.worker_identity}\n"
        f"Role/profile: {cell.role} / {cell.profile_identity}\n"
        f"Configured provider/model observed by harness: {cell.provider} / {cell.model}\n"
        "Important: complete the requested artifact, then post a structured completion packet with an artifactKind matching the artifact.\n"
    )
    if cell.artifact_kind == "den_document":
        slug = cell.artifact_slug or slugify(f"{cell.campaign_id}-{cell.idx}-{cell.worker_identity}")
        return common + (
            f"\nDeliverable: create or update Den document `{artifact_project_id}/{slug}`.\n"
            "Document content must include: campaign id, worker identity, profile identity, configured provider/model, and one sentence confirming what you did.\n"
            "Completion packet requirements: status completed, artifactKind den_document, artifact ref to the document slug.\n"
            "Do not make repository changes for this cell.\n"
        )
    if cell.artifact_kind == "code_change":
        return common + (
            "\nDeliverable: in `/home/dev/pi-crew`, create or update `MATRIX_SMOKE_LOG.md` by appending one line containing campaign id, worker identity, profile identity, and configured provider/model.\n"
            "Run a lightweight verification (`git diff -- MATRIX_SMOKE_LOG.md` is enough).\n"
            "Completion packet requirements: status completed, artifactKind code_change, branch/head/tests_run fields present.\n"
        )
    if cell.artifact_kind == "review_finding":
        return common + (
            "\nDeliverable: review the current pi-crew README or worker usage docs and produce one concise finding plus one recommendation in the completion summary.\n"
            "Do not make repository changes.\n"
            "Completion packet requirements: status completed, artifactKind read_only_inventory or den_artifact, artifact/finding summary present.\n"
        )
    return common + "\nDeliverable: produce a bounded read-only inventory summary in the completion packet.\n"


# ---------------------------------------------------------------------------
# Den tool wrappers and scoring
# ---------------------------------------------------------------------------
def create_child_task(client: McpClient, cell: MatrixCell, *, project_id: str, parent_task_id: int, artifact_project_id: str) -> dict[str, Any]:
    title = f"Matrix smoke: {cell.model}/{cell.role}/{cell.artifact_kind} #{cell.idx}"
    description = task_description(cell, project_id=project_id, artifact_project_id=artifact_project_id)
    tags = [
        "goblinbench",
        f"model:{slugify(cell.model)}",
        f"provider:{slugify(cell.provider)}",
        f"profile:{cell.profile_identity}",
        f"artifact:{cell.artifact_kind}",
        f"role:{cell.role}",
        cell.campaign_id,
    ]
    return client.call_tool("create_task", {
        "project_id": project_id,
        "title": title,
        "description": description,
        "priority": 3,
        "tags": tags,
        "assigned_to": "goblinbench-matrix",
        "parent_id": parent_task_id,
    })


def lease_worker(client: McpClient, cell: MatrixCell, *, project_id: str, task_id: int, assigned_by: str) -> dict[str, Any]:
    run_id = make_run_id()
    lease = client.call_tool("lease_worker", {
        "project_id": project_id,
        "role": cell.role,
        "assigned_by": assigned_by,
        "run_id": run_id,
        "task_id": task_id,
        "preferred_worker_identity": cell.worker_identity,
        "profile_identity": cell.profile_identity,
        "worker_role": cell.role,
        "verbose": True,
    })
    if not isinstance(lease, Mapping):
        raise RuntimeError(f"lease_worker returned non-object payload: {lease!r}")
    normalized = dict(lease)
    normalized.setdefault("run_id", run_id)
    return normalized


def assignment_state(status_payload: Any) -> str | None:
    return deep_get(
        status_payload,
        "state",
        "assignment.state",
        "worker_run.state",
        "run.state",
        "status.state",
    )


def poll_worker(client: McpClient, *, project_id: str, task_id: int, run_id: str, timeout_seconds: int, poll_interval: int) -> dict[str, Any]:
    started = time.monotonic()
    last: dict[str, Any] = {}
    while time.monotonic() - started < timeout_seconds:
        last = client.call_tool("get_worker_run_status", {
            "project_id": project_id,
            "run_id": run_id,
            "task_id": task_id,
            "verbose": True,
        })
        state = assignment_state(last)
        completion_state = deep_get(last, "completion_state", "latest_completion.completion_state", "completion.completion_state")
        if state in TERMINAL_ASSIGNMENT_STATES or completion_state in {"present", "malformed", "missing_packet"}:
            return last
        time.sleep(poll_interval)
    raise TimeoutError(f"timeout after {timeout_seconds}s waiting for run {run_id}; last={last}")


def latest_completion(client: McpClient, *, project_id: str, task_id: int, run_id: str, role: str) -> dict[str, Any]:
    return client.call_tool("get_latest_worker_completion", {
        "project_id": project_id,
        "task_id": task_id,
        "run_id": run_id,
        "role": role,
        "verbose": True,
    })


def verify_pool_available(client: McpClient, worker_identity: str) -> tuple[str | None, Any]:
    pool = client.call_tool("list_pool_members", {"worker_identity": worker_identity, "limit": 20, "verbose": True})
    members = normalize_pool_members(pool)
    for member in members:
        if member["worker_identity"] == worker_identity:
            return member.get("status"), pool
    return None, pool


def read_den_document(client: McpClient, project_id: str, slug: str) -> tuple[bool, Any]:
    try:
        doc = client.call_tool("get_document", {"project_id": project_id, "slug": slug, "verbose": True})
        return bool(doc), doc
    except Exception as exc:
        return False, {"error": str(exc)}


def completion_text(completion: Any) -> str:
    candidates = [
        deep_get(completion, "completion.content"),
        deep_get(completion, "completion.summary"),
        deep_get(completion, "content"),
        deep_get(completion, "summary"),
        deep_get(completion, "message.content"),
    ]
    return "\n".join(str(c) for c in candidates if c)


def extract_completion_state(completion: Any) -> tuple[str | None, str | None, int | None]:
    state = deep_get(completion, "completion_state", "state")
    status = deep_get(completion, "completion.status", "status")
    message_id = deep_get(completion, "message_id", "id", "message.id")
    try:
        message_id = int(message_id) if message_id is not None else None
    except (TypeError, ValueError):
        message_id = None
    return state, status, message_id


def base_record(cell: MatrixCell) -> dict[str, Any]:
    return {
        **cell.to_dict(),
        "task_id": None,
        "assignment_id": None,
        "run_id": None,
        "completion_state": None,
        "completion_status": None,
        "completion_packet_id": None,
        "substrate_success": False,
        "deliverable_success": False,
        "packet_valid": False,
        "pool_status_after": None,
        "failure_category": None,
        "started_at": utc_now(),
        "finished_at": None,
        "duration_ms": None,
        "turns": None,
        "tokens": None,
        "error": None,
        "evidence": {},
    }


def score_record(record: dict[str, Any], *, completion: Any | None = None, pool_status: str | None = None, document_readback: Any | None = None) -> dict[str, Any]:
    if completion is not None:
        completion_state, completion_status, message_id = extract_completion_state(completion)
        record["completion_state"] = completion_state
        record["completion_status"] = completion_status
        record["completion_packet_id"] = message_id
        record["packet_valid"] = completion_state in VALID_COMPLETION_STATES and completion_status in {None, "completed"}
        record["turns"] = deep_get(completion, "turns", "turn_count", "completion.turns", "metadata.turns")
        record["tokens"] = deep_get(completion, "tokens", "token_count", "completion.tokens", "metadata.tokens")
    if pool_status is not None:
        record["pool_status_after"] = pool_status

    lifecycle_ok = bool(record.get("assignment_id")) and record.get("pool_status_after") in {"available", "released", None}
    packet_ok = bool(record.get("packet_valid"))
    record["substrate_success"] = lifecycle_ok and packet_ok

    text = completion_text(completion or {})
    kind = record["artifact_kind"]
    if kind == "den_document":
        record["deliverable_success"] = bool(document_readback) and not (isinstance(document_readback, Mapping) and document_readback.get("error"))
    elif kind == "code_change":
        log_path = Path("/home/dev/pi-crew/MATRIX_SMOKE_LOG.md")
        record["deliverable_success"] = log_path.exists() and record["campaign_id"] in log_path.read_text(errors="ignore")
    elif kind == "review_finding":
        lowered = text.lower()
        record["deliverable_success"] = any(word in lowered for word in ["finding", "recommend", "suggest", "verdict", "review"])
    else:
        record["deliverable_success"] = bool(text.strip())

    if not record["failure_category"]:
        if record.get("completion_state") == "missing_packet":
            record["failure_category"] = "completion_missing"
        elif record.get("completion_state") == "malformed" or not packet_ok:
            record["failure_category"] = "malformed_packet" if record.get("completion_state") == "malformed" else "completion_failed"
        elif not record["deliverable_success"]:
            record["failure_category"] = "missing_or_unverified_artifact"
        elif record.get("pool_status_after") not in {"available", "released", None}:
            record["failure_category"] = "worker_not_available_after_release"
    return record


def run_automated_cell(
    client: McpClient,
    cell: MatrixCell,
    *,
    project_id: str,
    parent_task_id: int,
    artifact_project_id: str,
    assigned_by: str,
    timeout_seconds: int,
    poll_interval: int,
) -> dict[str, Any]:
    record = base_record(cell)
    started = time.monotonic()
    try:
        task = create_child_task(client, cell, project_id=project_id, parent_task_id=parent_task_id, artifact_project_id=artifact_project_id)
        task_id = deep_get(task, "id", "task.id")
        if not task_id:
            raise RuntimeError(f"create_task returned no task id: {task}")
        record["task_id"] = int(task_id)
        record["evidence"]["task"] = task

        lease = lease_worker(client, cell, project_id=project_id, task_id=int(task_id), assigned_by=assigned_by)
        if isinstance(lease, Mapping) and lease.get("error"):
            record["failure_category"] = "no_capacity" if lease.get("no_capacity") else "lease_failed"
            record["error"] = json.dumps(lease, default=str)[:2000]
            return record
        assignment_id = deep_get(lease, "assignment_id", "id", "assignment.id")
        run_id = deep_get(lease, "run_id", "runId")
        record["assignment_id"] = assignment_id
        record["run_id"] = run_id
        record["evidence"]["lease"] = lease
        if not assignment_id or not run_id:
            raise RuntimeError(f"lease_worker returned missing assignment/run: {lease}")

        status = poll_worker(client, project_id=project_id, task_id=int(task_id), run_id=str(run_id), timeout_seconds=timeout_seconds, poll_interval=poll_interval)
        record["evidence"]["worker_run_status"] = status

        completion = latest_completion(client, project_id=project_id, task_id=int(task_id), run_id=str(run_id), role=cell.role)
        record["evidence"]["completion"] = completion

        if cell.artifact_kind == "den_document" and cell.artifact_slug:
            found, doc = read_den_document(client, artifact_project_id, cell.artifact_slug)
            record["evidence"]["artifact_readback"] = doc
            document_readback = doc if found else None
        else:
            document_readback = None

        try:
            cleanup = client.call_tool("cleanup_worker_run", {
                "project_id": project_id,
                "run_id": str(run_id),
                "requested_by": assigned_by,
                "reason": "goblinbench matrix closeout",
            })
            record["evidence"]["cleanup"] = cleanup
        except Exception as exc:  # workers often self-release; keep as evidence, not automatic failure
            record["evidence"]["cleanup_error"] = str(exc)

        try:
            pool_status, pool = verify_pool_available(client, cell.worker_identity)
            record["evidence"]["pool"] = pool
        except Exception as exc:
            pool_status = None
            record["evidence"]["pool_error"] = str(exc)

        score_record(record, completion=completion, pool_status=pool_status, document_readback=document_readback)
        return record
    except TimeoutError as exc:
        record["failure_category"] = "timeout"
        record["error"] = str(exc)
        return record
    except Exception as exc:
        record["failure_category"] = record.get("failure_category") or "runtime_failure"
        record["error"] = str(exc)
        return record
    finally:
        record["finished_at"] = utc_now()
        record["duration_ms"] = int((time.monotonic() - started) * 1000)


# ---------------------------------------------------------------------------
# Import mode and reports
# ---------------------------------------------------------------------------
def load_import_records(source: str | None) -> list[dict[str, Any]]:
    if source and source != "-":
        text = Path(source).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()
    payload = json.loads(text)
    if isinstance(payload, Mapping):
        records = payload.get("cells") or payload.get("results") or payload.get("records") or [payload]
    else:
        records = payload
    return [dict(r) for r in records]


def run_import(records: list[dict[str, Any]], campaign_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cells: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for idx, raw in enumerate(records, 1):
        raw.setdefault("idx", idx)
        raw.setdefault("campaign_id", campaign_id)
        raw.setdefault("artifact_kind", raw.get("artifactKind", "den_document"))
        raw.setdefault("provider", raw.get("provider", "imported"))
        raw.setdefault("model", raw.get("model", raw.get("configured_model", "unknown")))
        raw.setdefault("role", raw.get("role", raw.get("worker_role", "unknown")))
        raw.setdefault("profile_identity", raw.get("profile_identity", raw.get("profile", "unknown")))
        raw.setdefault("worker_identity", raw.get("worker_identity", raw.get("worker", "unknown")))
        raw.setdefault("packet_valid", raw.get("completion_state") in VALID_COMPLETION_STATES or raw.get("packet_valid", False))
        raw.setdefault("substrate_success", bool(raw.get("assignment_id") and raw.get("packet_valid")))
        raw.setdefault("deliverable_success", bool(raw.get("artifact_handle") or raw.get("deliverable_success")))
        raw.setdefault("failure_category", None if raw["substrate_success"] and raw["deliverable_success"] else raw.get("failure_category", "imported_incomplete"))
        raw.setdefault("evidence", {})
        cells.append({k: raw.get(k) for k in ["idx", "worker_identity", "role", "profile_identity", "provider", "model", "artifact_kind", "campaign_id"]})
        results.append(raw)
    return cells, results


def write_reports(run_dir: Path, *, campaign_id: str, parent_task_id: int | None, mode: str, cells: Sequence[Any], results: Sequence[dict[str, Any]], notes: Sequence[str]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    cell_dicts = [c.to_dict() if hasattr(c, "to_dict") else dict(c) for c in cells]
    plan = {
        "campaign_id": campaign_id,
        "parent_task_id": parent_task_id,
        "mode": mode,
        "generated_at": utc_now(),
        "notes": list(notes),
        "cells": cell_dicts,
    }
    (run_dir / "plan.json").write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")
    payload = {**plan, "count": len(results), "results": list(results)}
    (run_dir / "matrix.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    lines = [
        "# pi-crew worker model/profile suitability matrix",
        "",
        f"- Generated: {plan['generated_at']}",
        f"- Campaign: {campaign_id}",
        f"- Parent task: {parent_task_id}",
        f"- Mode: {mode}",
    ]
    if notes:
        lines.append("- Notes: " + "; ".join(notes))
    lines += [
        "",
        "| idx | provider/model | role | profile | artifact | substrate | deliverable | packet | worker | task | assignment | run_id | failure |",
        "|---:|---|---|---|---|---|---|---|---|---:|---:|---|---|",
    ]
    for idx, result in enumerate(results, 1):
        provider_model = f"{result.get('provider', '-')}/{result.get('model', '-')}"
        lines.append(
            f"| {result.get('idx', idx)} | {provider_model} | {result.get('role', '-')} | {result.get('profile_identity', '-')} "
            f"| {result.get('artifact_kind', '-')} | {str(bool(result.get('substrate_success'))).lower()} "
            f"| {str(bool(result.get('deliverable_success'))).lower()} | {str(bool(result.get('packet_valid'))).lower()} "
            f"| {result.get('worker_identity', '-')} | {result.get('task_id') or '-'} | {result.get('assignment_id') or '-'} "
            f"| {result.get('run_id') or '-'} | {result.get('failure_category') or result.get('error') or '-'} |"
        )
    (run_dir / "matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GoblinBench pi-crew worker suitability matrix")
    parser.add_argument("--mode", choices=["plan", "preflight", "automated", "import"], default="plan")
    parser.add_argument("--execute-live", action="store_true", help="Required for --mode automated; creates Den tasks and leases workers")
    parser.add_argument("--mcp-url", default=DEFAULT_MCP_URL)
    parser.add_argument("--tool-profile", default="runner")
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--artifact-project-id", default=DEFAULT_ARTIFACT_PROJECT)
    parser.add_argument("--parent-task-id", type=int, default=DEFAULT_PARENT_TASK_ID)
    parser.add_argument("--campaign-id", default=f"goblinbench-2283-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--profile-root", default=str(DEFAULT_PROFILE_ROOT))
    parser.add_argument("--matrix-json", help="Explicit matrix cell list; use when testing separately configured model/profile combinations")
    parser.add_argument("--pool-json", help="Pool/member list override")
    parser.add_argument("--discover-pool", action="store_true", help="Use MCP list_pool_members instead of static fallback/--pool-json")
    parser.add_argument("--all-lanes", action="store_true", help="Include all discovered/configured lanes instead of one coder + one reviewer representative")
    parser.add_argument("--include-code-change", action="store_true", help="Include a repo-writing code_change coder cell; default stays Den-doc/review only")
    parser.add_argument("--cell-count", type=int, default=0, help="Limit cells after matrix construction")
    parser.add_argument("--assigned-by", default="goblinbench-matrix")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--poll-interval-seconds", type=int, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--import-json", help="Import records JSON path, or '-' / omitted for stdin in import mode")
    return parser.parse_args(argv)


def build_or_load_cells(args: argparse.Namespace, client: McpClient | None = None) -> tuple[list[MatrixCell], list[str]]:
    notes: list[str] = [
        "lease_worker selects configured pool members/profiles; model is read from profile config, not passed per assignment",
    ]
    profile_models = load_profile_models(Path(args.profile_root))
    if args.matrix_json:
        notes.append("using explicit matrix-json; caller is responsible for matching cells to installed worker config")
        cells = load_matrix_json(Path(args.matrix_json), args.campaign_id)
    else:
        if args.pool_json:
            members = json.loads(Path(args.pool_json).read_text(encoding="utf-8"))
            notes.append("using pool-json override")
        elif args.discover_pool and client is not None:
            members = discover_pool_members(client)
            notes.append("pool discovered from live Den MCP list_pool_members")
        else:
            members = FALLBACK_POOL_MEMBERS
            notes.append("using fallback six-lane pi-crew pool from #2190 docs; use --discover-pool for live readback")
        cells = build_matrix(members, profile_models, campaign_id=args.campaign_id, all_lanes=args.all_lanes, include_code_change=args.include_code_change)
    if args.cell_count > 0:
        cells = cells[: args.cell_count]
        notes.append(f"limited to first {args.cell_count} cell(s)")
    return cells, notes


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = Path(args.runs_root) / f"pi-crew-matrix-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    client: McpClient | None = None
    tools: set[str] = set()

    if args.mode in {"preflight", "automated"} or args.discover_pool:
        client = McpClient(args.mcp_url, tool_profile=args.tool_profile)
        client.initialize()
        tools = {tool.get("name", "") for tool in client.list_tools()}

    if args.mode == "import":
        cells, results = run_import(load_import_records(args.import_json), args.campaign_id)
        write_reports(run_dir, campaign_id=args.campaign_id, parent_task_id=args.parent_task_id, mode=args.mode, cells=cells, results=results, notes=["imported external worker handles/results"])
        print(run_dir)
        return 0

    cells, notes = build_or_load_cells(args, client)
    required_tools = {"create_task", "lease_worker", "get_worker_run_status", "get_latest_worker_completion", "list_pool_members"}
    if args.mode in {"preflight", "automated"}:
        missing = sorted(required_tools - tools)
        notes.append(f"MCP endpoint: {client.base_url if client else args.mcp_url}")
        notes.append(f"required worker tools present: {not missing}")
        if missing:
            notes.append(f"missing tools: {', '.join(missing)}")

    if args.mode in {"plan", "preflight"}:
        results = [{**cell.to_dict(), "substrate_success": False, "deliverable_success": False, "packet_valid": False, "failure_category": "not_executed_plan_only"} for cell in cells]
        write_reports(run_dir, campaign_id=args.campaign_id, parent_task_id=args.parent_task_id, mode=args.mode, cells=cells, results=results, notes=notes)
        print(f"Run directory: {run_dir}")
        print(f"Plan: {run_dir / 'plan.json'}")
        print(f"Summary: {run_dir / 'matrix.md'}")
        return 0

    if args.mode == "automated" and not args.execute_live:
        raise SystemExit("Refusing live Den writes/worker leases without --execute-live")
    if args.mode == "automated" and client is None:
        raise SystemExit("internal error: automated mode requires MCP client")
    assert client is not None

    results: list[dict[str, Any]] = []
    for cell in cells:
        print(f"[{cell.idx}/{len(cells)}] {cell.provider}/{cell.model} {cell.role} {cell.worker_identity} {cell.artifact_kind}", flush=True)
        record = run_automated_cell(
            client,
            cell,
            project_id=args.project_id,
            parent_task_id=args.parent_task_id,
            artifact_project_id=args.artifact_project_id,
            assigned_by=args.assigned_by,
            timeout_seconds=args.timeout_seconds,
            poll_interval=args.poll_interval_seconds,
        )
        results.append(record)
        verdict = "OK" if record.get("substrate_success") and record.get("deliverable_success") else "FAIL"
        print(f"  -> {verdict}: {record.get('failure_category') or '-'} task={record.get('task_id')} run={record.get('run_id')}", flush=True)

    write_reports(run_dir, campaign_id=args.campaign_id, parent_task_id=args.parent_task_id, mode=args.mode, cells=cells, results=results, notes=notes)
    print(f"Run directory: {run_dir}")
    print(f"Summary: {run_dir / 'matrix.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
