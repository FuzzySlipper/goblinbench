#!/usr/bin/env python3
"""
Codebase analysis Mode A benchmark runner + scorer + report generator.

Usage:
  # List available fixtures and models
  scripts/codebase-analysis-runner.py --list

  # Run a single candidate
  scripts/codebase-analysis-runner.py run --fixture den-core-v1 --model deepseek-flash --output runs/ca-dsv1-deepseek-flash/

  # Run multiple candidates (parallel)
  scripts/codebase-analysis-runner.py run --fixture den-core-v1 --model deepseek-flash,glm52 --output-dir runs/ca-dsv1-run1/

  # Judge a candidate's findings against the gold ledger
  scripts/codebase-analysis-runner.py judge --fixture den-core-v1 --candidate-dir runs/ca-dsv1-glm52/ --output runs/ca-dsv1-glm52/judge-result.json

  # Generate comparative report
  scripts/codebase-analysis-runner.py report --fixture den-core-v1 --run-dirs runs/ca-dsv1-deepseek-flash/ runs/ca-dsv1-glm52/ --output report.md

  # Full pipeline: run + judge + report
  scripts/codebase-analysis-runner.py all --fixture den-core-v1 --model deepseek-flash,glm52,stepfun --output-dir runs/ca-dsv1-all/
"""

import argparse, json, os, sys, pathlib, subprocess, textwrap, time, re
from datetime import datetime

ROOT = pathlib.Path('/home/dev/goblinbench')
FIXTURES = ROOT / 'fixtures' / 'codebase-analysis'
DEN_ROUTER = 'http://127.0.0.1:18082/v1/chat/completions'

FINDS_JSON_SCHEMA = textwrap.dedent("""
Each finding should have this exact JSON structure:
```json
{
  "findings": [
    {
      "title": "Short descriptive title",
      "category": "one of: service_boundary_leak, source_of_truth_confusion, missing_error_handling, contract_mismatch, config_drift, concurrency_smell, documentation_contradiction, operational_gap, testing_gap, architectural_smell, security_concern, performance_issue, other",
      "severity": "critical|high|medium|low|info",
      "confidence": 0.0-1.0,
      "evidence": [
        {
          "path": "relative/file/path.cs",
          "lines": "12-34",
          "quote": "relevant code snippet"
        }
      ],
      "diagnosis": "Description of what is wrong",
      "impact": "What could go wrong if not fixed",
      "fix": "Description of proposed fix",
      "fix_scope": "one of: localized_change, cross_file_refactor, architecture_change, config_change, doc_only"
    }
  ]
}
```
""".strip())

CANDIDATE_PROMPT_TPL = """You are a senior software architect reviewing a codebase. Your task is to analyze the service described below for architectural, safety, operational, correctness, and maintainability issues.

## Context

{packet}

## Instructions

1. **Read the project brief, architecture doc, API contract, deployment docs, and source code above.**
2. **Identify issues** across categories including: service boundary leaks, source-of-truth confusion, missing error handling, contract mismatches, config drift, concurrency smells, documentation contradictions, operational gaps, testing gaps, and architectural smells.
3. **Prioritize** — lead with the most impactful issues.
4. **Be specific** — cite exact file paths, line ranges, and code quotes. Generic advice ("use best practices") scores poorly.
5. **Consider tradeoffs** — some patterns that look wrong may be intentional. Call out uncertainty when you see it.
6. **Propose concrete fixes** — explain what should change and why.

## Output format

First, write your **analysis** as free-form markdown. Cover the most important findings, their relationships, and your overall assessment.

Then, end with a JSON code block containing ALL findings in this exact format:

```json
{{
  "findings": [
    {{
      "title": "...",
      "category": "contract_mismatch",
      "severity": "high",
      "confidence": 0.9,
      "evidence": [{{"path": "src/...", "lines": "12-34", "quote": "..."}}],
      "diagnosis": "...",
      "impact": "...",
      "fix": "...",
      "fix_scope": "cross_file_refactor"
    }}
  ]
}}
```

Do NOT wrap the findings in a nested 'analysis' object. The top-level JSON key must be 'findings'.
"""


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


def list_fixtures():
    for d in sorted(FIXTURES.iterdir()):
        if d.is_dir():
            led = d / 'gold-ledger.json'
            pkt = d / 'repo-packet.md'
            info = []
            if led.exists():
                with open(led) as f:
                    l = json.load(f)
                    issues = l.get('issues', [])
                    info.append(f"{len(issues)} planted issues")
            if pkt.exists():
                sz = pkt.stat().st_size
                info.append(f"packet {sz//1024}KB")
            print(f"  {d.name}  ({', '.join(info)})")


def load_fixture(fixture_name):
    """Load fixture metadata and packet."""
    fdir = FIXTURES / fixture_name
    if not fdir.is_dir():
        log(f"FIXTURE NOT FOUND: {fdir}")
        sys.exit(1)
    gold_path = fdir / 'gold-ledger.json'
    decoy_path = fdir / 'decoys.json'
    packet_path = fdir / 'repo-packet.md'
    raw_gold = json.load(open(gold_path)) if gold_path.exists() else {}
    gold = raw_gold.get('issues', []) if isinstance(raw_gold, dict) else raw_gold
    decoys = json.load(open(decoy_path)) if decoy_path.exists() else []
    if isinstance(decoys, dict) and 'decoys' in decoys:
        decoys = decoys['decoys']
    packet = packet_path.read_text() if packet_path.exists() else "No packet found."
    return {
        'dir': fdir,
        'gold': gold,
        'decoys': decoys,
        'packet': packet
    }


MODEL_TEMPS = {
    'kimi-code': 1.0,
    'kimi': 1.0,
}

MODEL_EXTRAS = {
    # Models that need extra API parameters
    'glm-5.2': {'reasoning_effort': 'low'},
    'glm52': {'reasoning_effort': 'low'},
    'glm': {'reasoning_effort': 'low'},
}


def parse_model_spec(spec):
    """Return (api_model, display_name, extra_params) for model specs.

    The normal spec is just a den-router model id. For reasoning-effort A/B
    runs, append @medium or @high, e.g. gpt-5.6-sol-test-only@high. The API
    model remains gpt-5.6-sol-test-only, while reports use the suffixed display
    name so effort variants stay separate rows.
    """
    spec = spec.strip()
    if '@' in spec:
        api_model, effort = spec.rsplit('@', 1)
        if effort in {'low', 'medium', 'high'}:
            return api_model, f"{api_model}-reasoning-{effort}", {'reasoning_effort': effort}
    return spec, spec, dict(MODEL_EXTRAS.get(spec, {}))


def call_model(model, prompt, max_tokens=16384, temperature=0.2, extra_params=None):
    """Call a model via den-router. Returns response text."""
    import urllib.request, urllib.error

    # Check for model-specific temperature constraints
    effective_temp = MODEL_TEMPS.get(model, temperature)
    extras = dict(MODEL_EXTRAS.get(model, {}))
    if extra_params:
        extras.update(extra_params)

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    # Some reasoning APIs reject temperature when reasoning_effort is present.
    if 'reasoning_effort' in extras:
        payload.update(extras)
    else:
        payload["temperature"] = effective_temp
        payload.update(extras)

    body = json.dumps(payload).encode()

    req = urllib.request.Request(
        DEN_ROUTER,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    for attempt in range(3):
        try:
            resp = urllib.request.urlopen(req, timeout=600)
            data = json.loads(resp.read())
            content = data['choices'][0]['message']['content']
            if content:
                return content
            log(f"Model {model} returned empty content (attempt {attempt+1})")
        except urllib.error.HTTPError as e:
            log(f"HTTP {e.code} for {model}: {e.read().decode()[:200]}")
            if e.code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            raise
        except Exception as e:
            log(f"Error calling {model}: {e}")
            if attempt < 2:
                time.sleep(5)
                continue
            raise
    return None


def extract_findings(text):
    """Extract findings JSON from model response. Tries multiple strategies."""

    def _find_balanced_json_block(text, start_pos):
        """Starting from text[start_pos], find the first { and its matching } using JSON-aware brace counting (skips braces inside strings)."""
        brace_start = text.find('{', start_pos)
        if brace_start == -1:
            return None
        depth = 0
        in_string = False
        escape = False
        for i in range(brace_start, len(text)):
            c = text[i]
            if in_string:
                if escape:
                    escape = False
                elif c == '\\':
                    escape = True
                elif c == '"':
                    in_string = False
            else:
                if c == '"':
                    in_string = True
                elif c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        return brace_start, i + 1
        return None

    def _try_parse_json_block(text, start_pos):
        result = _find_balanced_json_block(text, start_pos)
        if not result:
            return None
        s, e = result
        try:
            data = json.loads(text[s:e])
            if isinstance(data, dict) and 'findings' in data:
                return data['findings']
        except json.JSONDecodeError:
            pass
        return None

    # Strategy 1: ```json ... ``` block — parse the entire fenced block directly
    for m in re.finditer(r'```(?:json)?\s*\n?', text):
        fence_start = m.end()
        close_fence = text.find('```', fence_start)
        if close_fence == -1:
            continue
        # Direct attempt: try parsing the whole fenced block as JSON
        block = text[fence_start:close_fence].strip()
        if block:
            try:
                data = json.loads(block)
                if isinstance(data, dict) and 'findings' in data:
                    return data['findings']
            except json.JSONDecodeError:
                pass
        # Fallback: brace-based extraction within the fence (handles truncated blocks)
        result = _try_parse_json_block(text, fence_start)
        if result is not None:
            return result

    # Strategy 2: any {findings: [...]} in the text
    for m in re.finditer(r'\{[\s\S]*?"findings"\s*:\s*\[', text):
        result = _try_parse_json_block(text, m.start())
        if result is not None:
            return result

    # Strategy 3: truncated JSON — parse partial findings from individual {}-delimited objects
    # Uses JSON-aware brace counting (skips braces inside string values)
    start_idx = text.find('"findings"')
    if start_idx >= 0:
        arr_start = text.find('[', start_idx)
        if arr_start >= 0:
            partial = []
            pos = arr_start + 1
            while True:
                # Look for next { after non-whitespace
                bs = text.find('{', pos)
                if bs == -1 or bs > len(text):
                    break
                # JSON-aware brace counting to find matching }
                depth = 0
                end = -1
                in_string = False
                escape = False
                for i in range(bs, min(bs + 10000, len(text))):
                    c = text[i]
                    if in_string:
                        if escape:
                            escape = False
                        elif c == '\\':
                            escape = True
                        elif c == '"':
                            in_string = False
                    else:
                        if c == '"':
                            in_string = True
                        elif c == '{':
                            depth += 1
                        elif c == '}':
                            depth -= 1
                            if depth == 0:
                                end = i + 1
                                break
                if end == -1 or end - bs > 20000:
                    break  # truncated or too large
                try:
                    obj = json.loads(text[bs:end])
                    if isinstance(obj, dict):
                        partial.append(obj)
                except json.JSONDecodeError:
                    pass
                # Check what comes after: comma or closing bracket
                rest = text[end:end+10]
                if ']' in rest[:3]:
                    break  # end of array
                if ',' not in rest[:3]:
                    break  # truncated — no comma means the model was cut off
                pos = end + 1
            if partial:
                return partial

    return None


def run_candidate(model_spec, fixture, output_dir, judge_model=None):
    """Run one candidate model against the fixture."""
    api_model, display_model, extra_params = parse_model_spec(model_spec)
    outdir = pathlib.Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    log(f"Running {display_model} ({api_model}) against {fixture['dir'].name}...")
    prompt = CANDIDATE_PROMPT_TPL.format(packet=fixture['packet'])

    t0 = time.time()
    response = call_model(api_model, prompt, extra_params=extra_params)
    elapsed = time.time() - t0

    if not response:
        log(f"  {display_model}: NO RESPONSE")
        return None

    # Save full response
    with open(outdir / 'analysis.md', 'w') as f:
        f.write(response)

    # Extract findings
    findings = extract_findings(response)

    # Save meta
    meta = {
        'model': display_model,
        'api_model': api_model,
        'model_spec': model_spec,
        'extra_params': extra_params,
        'fixture': fixture['dir'].name,
        'timestamp': datetime.utcnow().isoformat(),
        'duration_s': round(elapsed, 1),
        'response_length': len(response),
        'findings_count': len(findings) if findings else 0,
        'extraction_status': 'success' if findings else 'parse_failed'
    }
    with open(outdir / 'meta.json', 'w') as f:
        json.dump(meta, f, indent=2)

    if findings:
        with open(outdir / 'findings.json', 'w') as f:
            json.dump(findings, f, indent=2)
        log(f"  {display_model}: {len(findings)} findings extracted ({elapsed:.0f}s)")
    else:
        log(f"  {display_model}: JSON PARSE FAILED ({elapsed:.0f}s)")
        # Save raw text for inspection
        with open(outdir / 'raw-response.txt', 'w') as f:
            f.write(response)

    return meta


SAMPLE_JUDGE_PROMPT = """You are a codebase analysis quality judge. Compare the candidate's findings against the gold issue ledger and score them.

## Gold Issue Ledger

{gold_ledger}

(Categories: {gold_categories})

## Decoys (valid patterns that should NOT be flagged as issues)

{decoys}

## Candidate Findings

{findings}

## Scoring Instructions

For each candidate finding:
1. Does it match a gold issue? If yes, which one?
   - A match means the finding identifies the same root cause, even if the description is different.
   - Exact wording match is NOT required — semantic match counts.
2. Is it a false positive hitting a decoy?
3. Is it a false positive (flagging something that is not actually a problem)?
4. Is it a genuine issue NOT in the gold ledger? Score as bonus_finding.

Return JSON with this structure:
{{
  "findings": [
    {{
      "title": "Copy of the candidate's finding title",
      "match_gold_id": "issue-id-or-null",
      "match_quality": "good_match|partial_match|no_match",
      "match_reasoning": "Why this does/doesn't match the gold issue",
      "is_false_positive": false,
      "is_decoy_hit": false,
      "is_bonus_finding": false,
      "evidence_quality": "good|adequate|poor|missing",
      "severity_agreement": "matches|model_overrates|model_underrates|no_match"
    }}
  ],
  "scoring": {{
    "gold_recall": 0.0,
    "true_positive_count": 0,
    "false_positive_count": 0,
    "decoy_hit_count": 0,
    "bonus_finding_count": 0,
    "evidence_quality_score": 0.0,
    "severity_calibration_score": 0.0,
    "fix_quality_notes": "text",
    "overall_assessment": "Brief qualitative assessment"
  }},
  "excerpts": {{
    "best_finding": {{
      "title": "...",
      "quote": "Excerpt from the finding that demonstrates good analysis",
      "why": "Why this excerpt represents good code review"
    }},
    "key_miss": {{
      "gold_id": "issue-id",
      "description": "What the candidate missed and why it matters"
    }},
    "notable_exchange": null
  }}
}}
"""


def judge_candidate(fixture, candidate_dir, output_path, judge_model='deepseek-pro'):
    """Score a candidate's findings against the gold ledger using a judge model."""
    candir = pathlib.Path(candidate_dir)
    findings_path = candir / 'findings.json'
    meta_path = candir / 'meta.json'

    if not findings_path.exists():
        log(f"No findings.json at {candir}")
        return None

    findings = json.loads(findings_path.read_text())
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    gold_ledger = fixture['gold']
    decoys = fixture['decoys']

    # Build compact gold ledger for the judge
    gold_lines = []
    cats = set()
    for g in gold_ledger:
        cats.add(g.get('category', 'other'))
        gold_lines.append(f"- [{g['severity']}] {g['id']}: {g['description'][:100].strip()}")
        gold_lines.append(f"  Evidence: {'; '.join(g.get('expected_evidence', []))[:120]}")
        gold_lines.append(f"  Dx: {'; '.join(g.get('acceptable_diagnoses', []))[:120]}")

    decoy_lines = []
    for d in decoys:
        decoy_lines.append(f"- {d['id']}: {d.get('description', '')[:80]}")
        decoy_lines.append(f"  Why: {d.get('reason_valid', '')[:80]}")

    findings_text = json.dumps(findings, indent=2)
    judge_prompt = SAMPLE_JUDGE_PROMPT.format(
        gold_ledger='\n'.join(gold_lines),
        gold_categories=', '.join(sorted(cats)),
        decoys='\n'.join(decoy_lines),
        findings=findings_text
    )

    model_name = meta.get('model', candir.name)
    log(f"  Judging {model_name} findings...")
    t0 = time.time()
    response = call_model(judge_model, judge_prompt, max_tokens=8192)
    elapsed = time.time() - t0

    if not response:
        log(f"  JUDGE: No response for {candir}")
        return None

    # Save raw judge response regardless of parse outcome
    raw_path = pathlib.Path(output_path).with_suffix('.judge-raw.md')
    raw_path.write_text(response)

    # Strategy 1: full JSON response with findings + scoring keys
    try:
        parsed = json.loads(response)
        if 'findings' in parsed and 'scoring' in parsed:
            judge_result = {
                'candidate': model_name,
                'candidate_dir': str(candir),
                'judge_model': judge_model,
                'duration_s': round(elapsed, 1),
                'judge_output': parsed
            }
            with open(output_path, 'w') as f:
                json.dump(judge_result, f, indent=2)
            log(f"  Judge complete: {parsed.get('scoring', {}).get('gold_recall', '?')} recall")
            return judge_result
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract full JSON from codeblock
    for m in re.finditer(r'```(?:json)?\s*\n?', response):
        fence_start = m.end()
        close_fence = response.find('```', fence_start)
        if close_fence == -1:
            continue
        bs = response.find('{', fence_start)
        if bs == -1 or bs > close_fence:
            continue
        depth = 0
        for i in range(bs, min(bs + 20000, len(response))):
            if response[i] == '{': depth += 1
            elif response[i] == '}': depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(response[bs:i+1])
                    if 'findings' in parsed and 'scoring' in parsed:
                        judge_result = {
                            'candidate': model_name,
                            'candidate_dir': str(candir),
                            'judge_model': judge_model,
                            'duration_s': round(elapsed, 1),
                            'judge_output': parsed
                        }
                        with open(output_path, 'w') as f:
                            json.dump(judge_result, f, indent=2)
                        log(f"  Judge via codeblock: {parsed.get('scoring', {}).get('gold_recall', '?')} recall")
                        return judge_result
                except (json.JSONDecodeError, Exception):
                    pass
                break

    # Strategy 3: fall back to extract_findings for the list
    result = extract_findings(response)
    if result:
        judge_result = {
            'candidate': model_name,
            'candidate_dir': str(candir),
            'judge_model': judge_model,
            'duration_s': round(elapsed, 1),
            'judge_output': {'findings': result, 'scoring': {}, 'excerpts': {}}
        }
        with open(output_path, 'w') as f:
            json.dump(judge_result, f, indent=2)
        log(f"  Judge via findings-only extraction (no scoring)")
        return judge_result

    log(f"  JUDGE PARSE FAILED for {model_name} ({len(response)} chars saved to {raw_path})")
    return None


def generate_report(fixture, judge_results, output_path):
    """Generate a comparative Markdown report from judge results."""
    from collections import defaultdict

    report = []

    fixture_name = fixture['dir'].name
    gold = fixture['gold']

    title = f"# Codebase Analysis Benchmark — {fixture_name}"
    report.append(title)
    report.append("")
    report.append(f"*Generated: {datetime.utcnow().isoformat()}*")
    report.append(f"*Gold issues: {len(gold)}*")
    report.append("")

    # --- Leaderboard table ---
    report.append(f'| Model            | Recall   | TP   | FP   | Decoy hits   | Bonus   | Evidence   | Severity cal   | Duration   |')
    report.append(f'|------------------|----------|------|------|--------------|---------|------------|----------------|------------|')

    valid_results = [j for j in (judge_results or []) if j is not None]
    for jr in valid_results:
        if jr is None:
            continue
        s = jr.get('judge_output', {}).get('scoring', {})
        jo = jr.get('judge_output', {})
        findings_list = jo.get('findings', [])
        meta = {}
        mpath = jr.get('candidate_dir')
        if mpath:
            mp = pathlib.Path(mpath) / 'meta.json'
            if mp.exists():
                meta = json.loads(mp.read_text())

        # If scoring is empty but findings list exists, compute from findings
        if not s and findings_list:
            tp = sum(1 for f in findings_list if f.get('match_gold_id') and not f.get('is_false_positive') and not f.get('is_decoy_hit'))
            fp = sum(1 for f in findings_list if f.get('is_false_positive'))
            decoy = sum(1 for f in findings_list if f.get('is_decoy_hit'))
            bonus = sum(1 for f in findings_list if f.get('is_bonus_finding'))
            recall = tp / len(gold) if gold else 0
            ev_scores = {'poor': 0, 'adequate': 0.33, 'good': 0.66, 'excellent': 1.0}
            ev = sum(ev_scores.get(f.get('evidence_quality', 'poor'), 0) for f in findings_list) / len(findings_list) if findings_list else 0
            sev = sum(1 for f in findings_list if f.get('severity_agreement') == 'matches') / len(findings_list) if findings_list else 0
            s = {
                'gold_recall': recall,
                'true_positive_count': tp,
                'false_positive_count': fp,
                'decoy_hit_count': decoy,
                'bonus_finding_count': bonus,
                'evidence_quality_score': round(ev, 2),
                'severity_calibration_score': round(sev, 2),
            }

        recall = s.get('gold_recall', 0)
        tp = s.get('true_positive_count', 0)
        fp = s.get('false_positive_count', 0)
        decoy = s.get('decoy_hit_count', 0)
        bonus = s.get('bonus_finding_count', 0)
        ev = s.get('evidence_quality_score', 0)
        sev = s.get('severity_calibration_score', 0)
        dur = meta.get('duration_s', jr.get('duration_s', 0))
        report.append(f'| {jr.get("candidate", "?").ljust(16)} | {recall*100:.0f}%{" " if recall*100 < 10 else ""}    | {str(tp).ljust(3)} | {str(fp).ljust(3)} | {str(decoy).ljust(3)}        | {str(bonus).ljust(3)}     | {ev*100:.0f}%{" ".ljust(5 if ev*100 < 10 else 4)} | {sev*100:.0f}%{" ".ljust(6 if sev*100 < 10 else 5)} | {dur:.0f}s{" " if dur < 100 else ""}    |')

    # --- Issue coverage matrix ---
    report.append("## Issue Coverage Matrix")
    report.append("")
    report.append("| Gold Issue | Severity | " + " | ".join(
        jr.get('candidate', '?') for jr in valid_results) + " |")
    report.append("|" + "---|" * (2 + len(valid_results)) + "")
    report.append("")

    # Map judges by model
    judges_by_model = {}
    for jr in judge_results:
        if jr:
            judges_by_model[jr.get('candidate', '?')] = jr

    from collections import defaultdict

    for g in gold:
        gid = g['id']
        row = [f"**{gid}**", g.get('severity', '?')]
        for jr in valid_results:
            judged = jr.get('judge_output', {}).get('findings', [])
            matched = [f for f in judged if f.get('match_gold_id') == gid]
            if matched:
                best = max(matched, key=lambda x: {'good_match': 3, 'partial_match': 2, 'no_match': 1}.get(x.get('match_quality'), 0))
                quality = best.get('match_quality', '')
                symbols = {'good_match': '✓', 'partial_match': '~', 'no_match': '✗'}
                row.append(symbols.get(quality, '?'))
            else:
                row.append('·')
        report.append("| " + " | ".join(row) + " |")

    report.append("")

    # --- Excerpts & qualitative ---
    report.append("## Qualitative Assessment")
    report.append("")

    for jr in judge_results:
        if jr is None:
            continue
        model = jr.get('candidate', '?')
        judged = jr.get('judge_output', {})
        s = judged.get('scoring', {})
        excerpts = judged.get('excerpts', {})
        assessment = s.get('overall_assessment', '')

        report.append(f"### {model}")
        report.append("")
        if assessment:
            report.append(f"**Overall:** {assessment}")
            report.append("")

        if excerpts.get('best_finding'):
            bf = excerpts['best_finding']
            report.append(f"**Best finding:** {bf.get('title', '')}")
            report.append(f"> {bf.get('quote', '')}")
            report.append(f"> *{bf.get('why', '')}*")
            report.append("")

        if excerpts.get('key_miss'):
            km = excerpts['key_miss']
            report.append(f"**Key miss:** {km.get('gold_id', '')}")
            report.append(f"> {km.get('description', '')}")
            report.append("")

    report.append("")
    report.append("---")
    report.append("")

    # --- Role recommendations ---
    report.append("## Role Routing Recommendation")
    report.append("")

    valid_results = [j for j in (judge_results or []) if j is not None]
    sorted_by_recall = sorted(valid_results, key=lambda j: (
        j.get('judge_output', {}).get('scoring', {}).get('gold_recall', 0)
    ), reverse=True)

    if len(sorted_by_recall) >= 3:
        best_model = sorted_by_recall[0].get('candidate', '?')
        second_model = sorted_by_recall[1].get('candidate', '?') if len(sorted_by_recall) > 1 else '?'
    elif len(sorted_by_recall) >= 1:
        best_model = sorted_by_recall[0].get('candidate', '?')
        second_model = 'n/a'
    else:
        best_model = '?'
        second_model = '?'

    report.append(f"- **Planner/Architect:** {best_model} (highest recall + evidence quality)")
    report.append(f"- **Reviewer:** {best_model} (good recall + bonus/real-finding awareness)")
    report.append(f"- **Operator:** {second_model or best_model} (fewer false positives, tradeoff awareness)")
    report.append(f"- **Cheap triage:** {second_model or '?'} (best value for cost)")
    report.append("")

    report.append("---")
    report.append(f"*Report generated by codebase-analysis-runner.py*")

    report_text = '\n'.join(report)
    with open(output_path, 'w') as f:
        f.write(report_text)
    log(f"Report written to {output_path}")
    return report_text


def cmd_list(args):
    print("Fixtures:")
    list_fixtures()
    print("")
    print("Models (via den-router):")
    import urllib.request, json
    try:
        req = urllib.request.Request("http://127.0.0.1:18082/v1/models")
        resp = json.loads(urllib.request.urlopen(req).read())
        for m in resp.get('data', []):
            print(f"  {m.get('id', '?')}")
    except Exception as e:
        print(f"  Could not fetch: {e}")
        print("  Known: deepseek-flash, deepseek-pro, glm52, kimi-code, stepfun")


def cmd_run(args):
    fixture = load_fixture(args.fixture)
    models = [m.strip() for m in args.model.split(',') if m.strip()]
    output_dir = pathlib.Path(args.output_dir)

    results = []
    for i, model in enumerate(models):
        _, display_model, _ = parse_model_spec(model)
        od = output_dir / display_model.replace('/', '-').replace(':', '-').replace('@', '-')
        result = run_candidate(model, fixture, str(od))
        results.append((model, result))

    if args.judge:
        log(f"\n--- Judging candidates ---")
        judge_results = []
        for model, result in results:
            _, display_model, _ = parse_model_spec(model)
            od = output_dir / display_model.replace('/', '-').replace(':', '-').replace('@', '-')
            judge_path = od / 'judge-result.json'
            jr = judge_candidate(fixture, str(od), str(judge_path), judge_model=args.judge_model)
            judge_results.append(jr)

        if args.report:
            report_path = pathlib.Path(args.report)
            report = generate_report(fixture, judge_results, str(report_path))
            print(report)


def cmd_judge(args):
    fixture = load_fixture(args.fixture)
    jr = judge_candidate(fixture, args.candidate_dir, args.output, args.judge_model)
    if jr:
        print(json.dumps(jr, indent=2))


def cmd_report(args):
    fixture = load_fixture(args.fixture)
    judge_results = []
    for d in args.run_dirs:
        jp = pathlib.Path(d) / 'judge-result.json'
        if jp.exists():
            judge_results.append(json.loads(jp.read_text()))
        else:
            log(f"No judge-result.json in {d}")
    generate_report(fixture, judge_results, args.output)


def cmd_all(args):
    """Full pipeline: run, judge, report."""
    fixture = load_fixture(args.fixture)
    models = [m.strip() for m in args.model.split(',') if m.strip()]
    output_base = pathlib.Path(args.output_dir)
    output_base.mkdir(parents=True, exist_ok=True)

    # Phase 1: Run all candidates
    log(f"=== Phase 1: Running {len(models)} candidates ===")
    run_results = []
    for model in models:
        _, display_model, _ = parse_model_spec(model)
        od = output_base / display_model.replace('/', '-').replace(':', '-').replace('@', '-')
        result = run_candidate(model, fixture, str(od))
        run_results.append((model, result))

    # Phase 2: Judge all
    log(f"\n=== Phase 2: Judging candidates ===")
    judge_results = []
    for model, result in run_results:
        _, display_model, _ = parse_model_spec(model)
        od = output_base / display_model.replace('/', '-').replace(':', '-').replace('@', '-')
        judge_path = od / 'judge-result.json'
        if not args.no_judge:
            jr = judge_candidate(fixture, str(od), str(judge_path), judge_model=args.judge_model)
            judge_results.append(jr)
        else:
            # Load existing if available
            if judge_path.exists():
                judge_results.append(json.loads(judge_path.read_text()))
                log(f"  Loaded existing judge for {model}")

    # Phase 3: Report
    report_path = output_base / 'comparative-report.md'
    if judge_results:
        log(f"\n=== Phase 3: Generating report ===")
        generate_report(fixture, judge_results, str(report_path))
        log(f"\nReport: {report_path}")
    else:
        log(f"\nNo judge results — skipping report. Run again with --no-judge to load existing.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Codebase Analysis Mode A Benchmark')
    sub = parser.add_subparsers(dest='command')

    p_list = sub.add_parser('list', help='List available fixtures and models')

    p_run = sub.add_parser('run', help='Run candidates')
    p_run.add_argument('--fixture', default='den-core-v1')
    p_run.add_argument('--model', required=True, help='Model(s) comma-separated')
    p_run.add_argument('--output-dir', default='runs/ca-run/')
    p_run.add_argument('--judge', action='store_true', help='Also judge after running')
    p_run.add_argument('--judge-model', default='deepseek-pro', help='Judge model')
    p_run.add_argument('--report', help='Report output path (requires --judge)')

    p_judge = sub.add_parser('judge', help='Judge a candidate')
    p_judge.add_argument('--fixture', default='den-core-v1')
    p_judge.add_argument('--candidate-dir', required=True)
    p_judge.add_argument('--output', required=True)
    p_judge.add_argument('--judge-model', default='deepseek-pro')

    p_report = sub.add_parser('report', help='Generate comparative report')
    p_report.add_argument('--fixture', default='den-core-v1')
    p_report.add_argument('--run-dirs', nargs='+', required=True)
    p_report.add_argument('--output', default='report.md')

    p_all = sub.add_parser('all', help='Full pipeline: run + judge + report')
    p_all.add_argument('--fixture', default='den-core-v1')
    p_all.add_argument('--model', required=True, help='Models comma-separated')
    p_all.add_argument('--output-dir', default='runs/ca-full-run/')
    p_all.add_argument('--judge-model', default='deepseek-pro')
    p_all.add_argument('--no-judge', action='store_true', help='Skip judge phase, use existing')

    args = parser.parse_args()
    if args.command == 'list':
        cmd_list(args)
    elif args.command == 'run':
        cmd_run(args)
    elif args.command == 'judge':
        cmd_judge(args)
    elif args.command == 'report':
        cmd_report(args)
    elif args.command == 'all':
        cmd_all(args)
    else:
        parser.print_help()
