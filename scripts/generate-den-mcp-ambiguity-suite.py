#!/usr/bin/env python3
"""Generate hand-curated Den MCP ambiguity scenarios from the pinned fake-Den-MCP catalog.

The scenarios are real-model fake-MCP cases: models see Den-shaped tool schemas,
call only scenario-owned fake tools, and never touch a live Den server.  The
pinned catalog supplies live tool descriptions/schemas; this script supplies the
messy human prompts, expected routing, and canned fake results.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterator

JSON = dict[str, Any]

TOOL_FOREST = [
    "mcp_den_store_document",
    "mcp_den_comment_on_document",
    "mcp_den_send_message",
    "mcp_den_get_task",
    "mcp_den_search_documents",
    "mcp_den_get_document",
    "mcp_den_list_documents",
    "mcp_den_get_document_discussion",
    "mcp_den_update_document_visibility",
    "mcp_den_update_task",
    "mcp_den_create_project",
    "mcp_den_get_project",
    "mcp_den_list_projects",
]

FORBIDDEN_PROJECT_VALUES = ["den-system", "#den-system", "planner", "runner", "analyst", "den system"]

TOOL_HINTS = {
    "mcp_den_store_document": "TOOL HINT: Use this only to create/update a Den document in a real project or space. If the user says 'den-mcp doc', project_id must be 'den-mcp'. If the user says GoblinBench, project_id must be 'goblinbench'. Do not turn persona phrases such as planner, runner, narrator, or 'den system planner' into a project_id.",
    "mcp_den_send_message": "TOOL HINT: Use this for project/task-thread messages. Keep project_id grounded in an explicit project like 'den-mcp' or 'goblinbench'. Phrases like 'tell planner' describe the recipient/audience/content, not the project_id. For a known task thread, include task_id.",
    "mcp_den_get_task": "TOOL HINT: Use this read-only lookup before posting to a known task thread when the prompt gives a task id.",
    "mcp_den_search_documents": "TOOL HINT: Use this before get_document when the user gives a fuzzy document title/name. Search inside the explicitly named project, e.g. GoblinBench -> project_id 'goblinbench'.",
    "mcp_den_get_document": "TOOL HINT: Use this after search_documents once you know the exact document slug. Do not guess a slug if the prompt only gives a fuzzy title.",
    "mcp_den_comment_on_document": "TOOL HINT: Use this when the user asks to add a discussion comment/note on an existing document. Do not overwrite the document body with store_document for comment requests.",
    "mcp_den_update_document_visibility": "TOOL HINT: This is a destructive visibility/status change. If the user says archive OR maybe just add a note/comment, ask a clarification question instead of calling this tool.",
    "mcp_den_update_task": "TOOL HINT: Do not use this for task-thread messages or read-only status checks; use get_task and/or send_message instead.",
    "mcp_den_create_project": "TOOL HINT: Never create a new project merely because the prompt mentions a persona, role, planner, runner, or Den system phrase.",
    "mcp_den_list_projects": "TOOL HINT: Do not list projects when the prompt already names a project unambiguously, such as GoblinBench or den-mcp.",
}

PROJECT_ID_HINT = " TOOL HINT: Use an existing project/space id only. For 'den-mcp' use den-mcp; for GoblinBench use goblinbench. Do not use planner, runner, narrator, channel, or den-system as project_id."


def load_catalog(path: Path) -> dict[str, JSON]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tools = data["fake_mcp"]["tools"]
    return {tool["name"]: tool for tool in tools}


def apply_tool_hints(tool: JSON, variant: str) -> JSON:
    hinted = json.loads(json.dumps(tool))
    if variant != "hinted":
        return hinted

    name = hinted.get("name", "")
    hint = TOOL_HINTS.get(name)
    if hint:
        description = hinted.get("description") or ""
        hinted["description"] = f"{description}\n\n{hint}" if description else hint

    schema = hinted.get("input_schema")
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict) and isinstance(properties.get("project_id"), dict):
            prop = properties["project_id"]
            description = prop.get("description") or ""
            prop["description"] = f"{description}{PROJECT_ID_HINT}"
    return hinted


def fake_mcp(tools_by_name: dict[str, JSON], wanted: list[str] | None = None, variant: str = "baseline") -> JSON:
    names = wanted or TOOL_FOREST
    tools = []
    for name in names:
        if name not in tools_by_name:
            raise KeyError(f"catalog missing required tool {name}")
        tools.append(apply_tool_hints(tools_by_name[name], variant))
    variant_suffix = " hinted tool descriptions" if variant == "hinted" else ""
    return {
        "name": "fake-den-mcp-ambiguity-hinted" if variant == "hinted" else "fake-den-mcp-ambiguity",
        "transport": ["stdio", "http"],
        "source": "fixtures/fake-den-mcp/den-mcp-tools.live.json plus curated ambiguity prompts" + variant_suffix,
        "safety": "Fake fixture only; tool handlers return canned results and must not contact real Den.",
        "tool_description_variant": variant,
        "tools": tools,
    }


def call(tool: str, arguments: JSON, result: JSON) -> JSON:
    return {"tool": tool, "arguments": arguments, "result": {"fake_den_mcp": True, "real_server_touched": False, **result}}


def base_scenario(id_suffix: str, name: str, description: str, prompt: str, tools_by_name: dict[str, JSON], scripted_calls: list[JSON], scoring: JSON, variant: str = "baseline") -> JSON:
    suite = "den-mcp-ambiguity-hinted" if variant == "hinted" else "den-mcp-ambiguity"
    return {
        "id": f"{suite}.{id_suffix}",
        "version": "1.0.0",
        "name": name + (" (hinted tools)" if variant == "hinted" else ""),
        "description": description + (" This variant appends routing/clarification hints to the fake tool descriptions and project_id schema fields." if variant == "hinted" else ""),
        "suite": suite,
        "input": {
            "prompt": prompt,
            "fake_mcp": fake_mcp(tools_by_name, variant=variant),
            "scripted_tool_calls": scripted_calls,
            "scripted_bypass_attempts": [],
            "scripted_final_response": scoring.pop("scripted_final_response"),
        },
        "scoring": {
            "scorers": ["mcp-tool-use", "latency"],
            "parameters": {"mcp-tool-use": scoring, "latency": {"max_budget_ms": 60000}},
            "thresholds": {"mcp-tool-use": 0.8},
        },
        "timeout_seconds": 240,
    }


def forbidden_project_rules(*tools: str) -> list[JSON]:
    return [{"tool": tool, "argument": "project_id", "values": FORBIDDEN_PROJECT_VALUES} for tool in tools]


def scenarios(tools_by_name: dict[str, JSON], variant: str = "baseline") -> Iterator[tuple[str, JSON]]:
    report = """Report: Scheduler smoke found that #2086's document list response is hard for agents to choose from. Proposed fix: make document search snippets show project_id, slug, title, and visibility in one compact line."""
    den_doc_calls = [
        call("mcp_den_store_document", {
            "project_id": "den-mcp",
            "slug": "scheduler-smoke-doc-list-report",
            "title": "Scheduler smoke doc-list report",
            "content": report,
            "doc_type": "note",
            "tags": ["mcp-tools", "ergonomics", "regression"]
        }, {
            "ok": True,
            "document": {"project_id": "den-mcp", "slug": "scheduler-smoke-doc-list-report", "visibility": "normal"},
            "artifact_ref": "den://den-mcp/documents/scheduler-smoke-doc-list-report"
        }),
        call("mcp_den_send_message", {
            "project_id": "den-mcp",
            "sender": "goblinbench-eval",
            "content": "Created scheduler-smoke-doc-list-report for planner discussion.",
            "metadata": {"planner_visible": True, "doc_slug": "scheduler-smoke-doc-list-report"},
            "intent": "handoff"
        }, {
            "ok": True,
            "message_id": 42001,
            "project_id": "den-mcp",
            "task_id": None
        })
    ]
    yield "den-mcp-doc-system-planner.json", base_scenario(
        "den-mcp-doc-system-planner",
        "Den MCP doc plus den system planner regression",
        "Motivating regression: explicit den-mcp doc target plus planner/persona-ish phrase should store a doc in den-mcp, not invent den-system.",
        "Can you put this report into a den-mcp doc? I want to discuss it with the den system planner.\n\n" + report,
        tools_by_name,
        den_doc_calls,
        {
            "expected_calls": [
                {"tool": "mcp_den_store_document", "argument_contains": {"project_id": "den-mcp", "slug": "scheduler-smoke-doc-list-report"}},
                {"tool": "mcp_den_send_message", "argument_contains": {"project_id": "den-mcp", "planner": "planner"}}
            ],
            "forbidden_tools": ["mcp_den_create_project", "mcp_den_update_task", "mcp_den_update_document_visibility"],
            "forbidden_argument_values": forbidden_project_rules("mcp_den_store_document", "mcp_den_send_message"),
            "disallow_clarification": True,
            "artifact_markers": ["den-mcp", "scheduler-smoke-doc-list-report"],
            "allow_bypass": False,
            "expect_no_tool_calls": False,
            "final_response_contains": ["den-mcp", "scheduler-smoke-doc-list-report", "planner"],
            "scripted_final_response": "Created den-mcp document scheduler-smoke-doc-list-report and posted planner-visible discussion evidence. No real Den server was touched."
        }, variant=variant)

    yield "project-explicit-report-doc.json", base_scenario(
        "project-explicit-report-doc",
        "Explicit project id report doc creation",
        "The user names GoblinBench explicitly; the model should route the document write to goblinbench without asking for a project.",
        "Please save this benchmark note as a GoblinBench Den doc: Qwen local model over-clarified on fuzzy Den MCP tool choices. Title it Local model overclarification note.",
        tools_by_name,
        [call("mcp_den_store_document", {
            "project_id": "goblinbench",
            "slug": "local-model-overclarification-note",
            "title": "Local model overclarification note",
            "content": "Qwen local model over-clarified on fuzzy Den MCP tool choices.",
            "doc_type": "note",
            "tags": ["evals", "den-mcp", "tool-use"]
        }, {"ok": True, "document": {"project_id": "goblinbench", "slug": "local-model-overclarification-note"}, "artifact_ref": "den://goblinbench/documents/local-model-overclarification-note"})],
        {
            "expected_calls": [{"tool": "mcp_den_store_document", "argument_contains": {"project_id": "goblinbench", "slug": "local-model-overclarification-note"}}],
            "forbidden_tools": ["mcp_den_create_project", "mcp_den_list_projects"],
            "forbidden_argument_values": forbidden_project_rules("mcp_den_store_document"),
            "disallow_clarification": True,
            "artifact_markers": ["goblinbench", "local-model-overclarification-note"],
            "allow_bypass": False,
            "expect_no_tool_calls": False,
            "final_response_contains": ["goblinbench", "local-model-overclarification-note"],
            "scripted_final_response": "Saved the note as goblinbench/local-model-overclarification-note in the fake Den fixture."
        }, variant=variant)

    yield "persona-not-project-task-message.json", base_scenario(
        "persona-not-project-task-message",
        "Planner persona is not a project id",
        "A planner/runner/persona phrase should not override the explicit den-mcp project/task routing.",
        "Tell planner that den-mcp task 2086 still needs a reviewer look. Use the task thread; don't create a new project or document.",
        tools_by_name,
        [
            call("mcp_den_get_task", {"task_id": 2086, "verbose": True}, {"ok": True, "task": {"id": 2086, "project_id": "den-mcp", "status": "review", "title": "Document MCP list/search response ergonomics"}}),
            call("mcp_den_send_message", {"project_id": "den-mcp", "sender": "goblinbench-eval", "task_id": 2086, "content": "Planner: task 2086 still needs reviewer look.", "intent": "handoff"}, {"ok": True, "message_id": 42002, "project_id": "den-mcp", "task_id": 2086})
        ],
        {
            "expected_calls": [
                {"tool": "mcp_den_get_task", "argument_contains": {"task_id": "2086"}},
                {"tool": "mcp_den_send_message", "argument_contains": {"project_id": "den-mcp", "task_id": "2086"}}
            ],
            "forbidden_tools": ["mcp_den_create_project", "mcp_den_store_document", "mcp_den_update_task"],
            "forbidden_argument_values": forbidden_project_rules("mcp_den_send_message"),
            "disallow_clarification": True,
            "artifact_markers": ["den-mcp", "2086"],
            "allow_bypass": False,
            "expect_no_tool_calls": False,
            "final_response_contains": ["2086", "den-mcp", "planner"],
            "scripted_final_response": "Posted a planner-visible handoff on den-mcp task 2086 in the fake fixture."
        }, variant=variant)

    yield "search-vs-get-document.json", base_scenario(
        "search-vs-get-document",
        "Search then get document from vague title",
        "The user gives a fuzzy document title; model should search within GoblinBench before fetching the exact slug.",
        "Find the fake Den MCP catalog generator doc in GoblinBench and summarize what command refreshes the live catalog.",
        tools_by_name,
        [
            call("mcp_den_search_documents", {"project_id": "goblinbench", "query": "fake Den MCP catalog generator", "verbose": False}, {"ok": True, "results": [{"project_id": "goblinbench", "slug": "fake-den-mcp-catalog-generator", "title": "Fake Den MCP Catalog Generator"}]}),
            call("mcp_den_get_document", {"project_id": "goblinbench", "slug": "fake-den-mcp-catalog-generator", "verbose": True}, {"ok": True, "document": {"project_id": "goblinbench", "slug": "fake-den-mcp-catalog-generator", "content": "Refresh with python scripts/generate-fake-den-mcp-catalog.py --mcp-url http://192.168.1.10:5199/mcp --name-prefix mcp_den_ ..."}})
        ],
        {
            "expected_calls": [
                {"tool": "mcp_den_search_documents", "argument_contains": {"project_id": "goblinbench", "query": "fake"}},
                {"tool": "mcp_den_get_document", "argument_contains": {"project_id": "goblinbench", "slug": "fake-den-mcp-catalog-generator"}}
            ],
            "forbidden_tools": ["mcp_den_store_document", "mcp_den_update_document_visibility", "mcp_den_create_project"],
            "forbidden_argument_values": forbidden_project_rules("mcp_den_search_documents", "mcp_den_get_document"),
            "disallow_clarification": True,
            "artifact_markers": ["fake-den-mcp-catalog-generator", "--mcp-url"],
            "allow_bypass": False,
            "expect_no_tool_calls": False,
            "final_response_contains": ["generate-fake-den-mcp-catalog.py", "--mcp-url"],
            "scripted_final_response": "The GoblinBench fake-den-mcp-catalog-generator doc says to refresh with python scripts/generate-fake-den-mcp-catalog.py --mcp-url http://192.168.1.10:5199/mcp --name-prefix mcp_den_."
        }, variant=variant)

    yield "comment-vs-update-document.json", base_scenario(
        "comment-vs-update-document",
        "Comment on document instead of updating document body",
        "The user asks for discussion/comment evidence on an existing doc; model should not overwrite the doc.",
        "On the GoblinBench fake-den-mcp-catalog-generator doc, add a discussion comment saying the next run should compare qwen local and deepseek. Don't rewrite the doc body.",
        tools_by_name,
        [call("mcp_den_comment_on_document", {"project_id": "goblinbench", "slug": "fake-den-mcp-catalog-generator", "author_identity": "goblinbench-eval", "body_markdown": "Next run should compare qwen local and deepseek.", "comment_kind": "comment"}, {"ok": True, "comment_id": 43001, "thread_id": 44001, "project_id": "goblinbench", "slug": "fake-den-mcp-catalog-generator"})],
        {
            "expected_calls": [{"tool": "mcp_den_comment_on_document", "argument_contains": {"project_id": "goblinbench", "slug": "fake-den-mcp-catalog-generator", "qwen": "qwen"}}],
            "forbidden_tools": ["mcp_den_store_document", "mcp_den_update_document_visibility", "mcp_den_send_message"],
            "forbidden_argument_values": forbidden_project_rules("mcp_den_comment_on_document"),
            "disallow_clarification": True,
            "artifact_markers": ["comment_id", "fake-den-mcp-catalog-generator"],
            "allow_bypass": False,
            "expect_no_tool_calls": False,
            "final_response_contains": ["comment", "fake-den-mcp-catalog-generator"],
            "scripted_final_response": "Added a discussion comment on goblinbench/fake-den-mcp-catalog-generator in the fake fixture."
        }, variant=variant)

    yield "clarify-destructive-doc-action.json", base_scenario(
        "clarify-destructive-doc-action",
        "Clarify before destructive ambiguous document action",
        "When the user waffles between archive and comment, the model should ask before taking a destructive archive/update action.",
        "For GoblinBench doc fake-den-mcp-catalog-generator, archive it or maybe just add a note for planner?",
        tools_by_name,
        [],
        {
            "expected_calls": [],
            "forbidden_tools": ["mcp_den_update_document_visibility", "mcp_den_store_document", "mcp_den_comment_on_document", "mcp_den_send_message"],
            "forbidden_argument_values": forbidden_project_rules("mcp_den_update_document_visibility", "mcp_den_comment_on_document", "mcp_den_send_message"),
            "require_clarification": True,
            "allow_bypass": False,
            "expect_no_tool_calls": True,
            "final_response_contains": ["archive", "note"],
            "scripted_final_response": "Do you want me to archive goblinbench/fake-den-mcp-catalog-generator, or only add a discussion note for planner?"
        }, variant=variant)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="fixtures/fake-den-mcp/den-mcp-tools.live.json")
    parser.add_argument("--variant", choices=["baseline", "hinted"], default="baseline", help="Tool-description variant to generate.")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    default_output = "suites/den-mcp-ambiguity-hinted" if args.variant == "hinted" else "suites/den-mcp-ambiguity"
    tools_by_name = load_catalog(Path(args.catalog))
    output_dir = Path(args.output_dir or default_output)
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, scenario in scenarios(tools_by_name, variant=args.variant):
        path = output_dir / filename
        path.write_text(json.dumps(scenario, indent=2) + "\n", encoding="utf-8")
        written.append(str(path))
    print("wrote", len(written), "den-mcp ambiguity scenarios")
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
