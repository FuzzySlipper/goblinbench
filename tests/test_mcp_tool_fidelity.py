from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gb.models import CandidateConfig, CandidateResult, Scenario  # type: ignore[import-not-found]  # noqa: E402
from gb.runners import _openai  # type: ignore[import-not-found]  # noqa: E402
from gb.scorers.mcp_tool_use import McpToolUseScorer  # type: ignore[import-not-found]  # noqa: E402


def _load_fake_server():  # type: ignore[no-untyped-def]
    path = SCRIPTS / "fake-mcp-server.py"
    spec = importlib.util.spec_from_file_location("goblinbench_fake_mcp_server", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _invoice_scenario() -> dict:
    return json.loads((REPO / "suites" / "mcp-tools-hard" / "invoice-payment-forest.json").read_text())


def test_scripted_tool_result_requires_arguments_and_preserves_recovery_step() -> None:
    calls = [{"tool": "invoice_read", "arguments": {"vendor_id": "ven-202", "invoice": "GOB-202"}, "result": {"invoice_id": "inv-202"}}]
    used: set[int] = set()

    invalid = _openai.execute_fake_tool("invoice_read", {"vendor_id": "WRONG", "invoice": "NOPE"}, calls, used)

    assert invalid == {"ok": False, "error": "validation failed for fake tool: invoice_read", "retryable": True}
    assert used == set()

    valid = _openai.execute_fake_tool("invoice_read", {"vendor_id": "ven-202", "invoice": "GOB-202"}, calls, used)

    assert valid == {"invoice_id": "inv-202"}
    assert used == {0}


def test_fake_server_matches_shared_validation_and_consumes_only_successful_call() -> None:
    fake_server = _load_fake_server()
    scenario = _invoice_scenario()
    used: set[int] = set()

    invalid = fake_server.call_tool(scenario, "invoice_read", {"vendor_id": "WRONG", "invoice": "NOPE"}, None, used)
    valid = fake_server.call_tool(scenario, "invoice_read", {"vendor_id": "ven-202", "invoice": "GOB-202"}, None, used)

    assert invalid["ok"] is False
    assert "invoice_id" not in invalid
    assert valid["invoice_id"] == "inv-202"
    assert len(used) == 1


def test_safe_draft_fixture_accepts_nonempty_agent_authored_note() -> None:
    scenario = _invoice_scenario()
    fake_server = _load_fake_server()
    used: set[int] = set()

    result = fake_server.call_tool(
        scenario,
        "draft_note_create",
        {"invoice_id": "inv-202", "note": "Reviewer-facing draft with the gathered evidence."},
        None,
        used,
    )

    assert result == {"draft_id": "draft-202"}
    assert len(used) == 1


def test_direct_fake_executor_rejects_advertised_but_unscripted_decoy() -> None:
    scenario = _invoice_scenario()
    used: set[int] = set()

    result = _openai.execute_fake_tool(
        "approval_request_send",
        {"invoice_id": "inv-202"},
        scenario["input"]["scripted_tool_calls"],
        used,
        scenario["input"]["fake_mcp"]["tools"],
    )

    assert result == {
        "ok": False,
        "error": "unavailable fake tool: approval_request_send",
        "retryable": False,
    }
    assert used == set()

    fake_server = _load_fake_server()
    server_result = fake_server.call_tool(
        scenario,
        "approval_request_send",
        {"invoice_id": "inv-202"},
        None,
        set(),
    )
    assert server_result == result


def test_hard_invoice_schema_exposes_scripted_required_fields() -> None:
    scenario = _invoice_scenario()
    tools = {tool["name"]: tool["input_schema"] for tool in scenario["input"]["fake_mcp"]["tools"]}

    assert tools["vendor_lookup"]["required"] == ["name"]
    assert tools["invoice_read"]["required"] == ["vendor_id", "invoice"]
    assert tools["duplicate_invoice_search"]["required"] == ["vendor_id", "invoice"]
    assert tools["draft_note_create"]["required"] == ["invoice_id", "note"]
    assert tools["policy_check"]["required"] == ["invoice_id"]


def test_scorer_summary_explains_argument_cap() -> None:
    scenario = Scenario.from_dict(_invoice_scenario())
    result = CandidateResult(
        success=True,
        output={
            "tool_calls": [
                {"tool": "vendor_lookup", "arguments": {}},
                {"tool": "invoice_read", "arguments": {}},
                {"tool": "duplicate_invoice_search", "arguments": {}},
                {"tool": "draft_note_create", "arguments": {}},
            ],
            "bypass_attempts": [],
            "final_response": "draft-202; did not pay; no duplicate",
        },
    )

    score = McpToolUseScorer().score(scenario, CandidateConfig(), result, None)

    assert score.score == 0.75
    assert score.passed is False
    assert "FAIL [near-pass]: mcp-tool-use: calls 4/4; arguments 0/4; final 3/3" in score.human_summary
    assert "expected argument mismatch" in score.human_summary
    assert score.detail["raw_score"] == 0.85
    assert score.detail["score_cap"] == 0.75
    assert score.detail["score_cap_reasons"] == ["expected argument mismatch"]
    assert score.detail["outcome_class"] == "near-pass"
