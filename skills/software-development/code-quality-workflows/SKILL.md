---
name: code-quality-workflows
description: Use when shaping software changes through spikes, TDD, parallel simplification review, and pre-commit verification before reporting or opening a PR.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [software-development, tdd, spikes, code-review, refactoring, verification]
    related_skills: [systematic-debugging, requesting-code-review]
---

# Code Quality Workflows

## Overview

This umbrella covers process-level engineering workflows that improve confidence before a change is delivered: validating an idea with a spike, implementing behavior with TDD, simplifying recent changes, and running pre-commit verification. Pick the smallest workflow that matches the uncertainty and risk.

## When to Use

- The user asks to validate a risky approach before full implementation.
- A behavior change should be built test-first.
- A recent diff has grown messy and needs simplification.
- A commit/PR is nearly ready and needs verification.

## Workflow Selector

| Situation | Use | Output |
| --- | --- | --- |
| Unsure whether an approach will work | Spike | VALIDATED / PARTIAL / INVALIDATED verdict with evidence |
| Clear behavior needs implementation | TDD | Failing test → passing minimal code → refactor |
| Diff works but is complex | Simplification review | Concrete cleanup changes and preserved tests |
| Ready to commit/open PR | Pre-commit verification | Diff summary, scans, tests, risks |

## Spike Workflow

1. Define the hypothesis and acceptance criteria.
2. Decompose multiple unknowns into separate spikes if needed.
3. Research just enough to choose an approach.
4. Build a throwaway proof, not production architecture.
5. Run it and record evidence.
6. End with `VALIDATED`, `PARTIAL`, or `INVALIDATED`, plus recommendation for the real build.

Do not let spike code silently become production code without review and cleanup.

## TDD Workflow

1. **RED:** write the smallest failing test for the desired behavior.
2. Run the specific test and confirm it fails for the right reason.
3. **GREEN:** implement the minimum code to pass.
4. Run the specific test, then relevant broader tests.
5. **REFACTOR:** simplify while keeping tests green.
6. Repeat for the next behavior.

Useful commands:

```bash
pytest tests/test_feature.py::test_specific_behavior -v
pytest tests/ -q
```

For non-Python projects, adapt to the repo's established test runner.

## Simplification Review Workflow

1. Identify the diff: uncommitted changes first, then staged changes, or an explicit branch/range.
2. Ask three independent reviewers (or three passes) to look for duplication, over-complexity, dead code, and needless abstractions.
3. Aggregate suggestions by risk and payoff.
4. Apply only changes you can verify.
5. Rerun tests and inspect the final diff.

## Pre-Commit Verification Workflow

1. Get the diff (`git diff`, staged diff, or branch comparison).
2. Scan for hardcoded secrets, command injection, unsafe eval/exec, unsafe deserialization, SQL string formatting, and permission broadening.
3. Run project tests/lint/build. Use language-specific quick checks when a full suite is unavailable.
4. Inspect generated files, lockfiles, migrations, and config changes manually.
5. Summarize what was verified and what remains unverified.

## Common Pitfalls

1. **Skipping RED in TDD.** A test that never failed did not prove it catches the bug.
2. **Gold-plating spikes.** Spikes answer a question; they are not the production implementation.
3. **Applying reviewer suggestions blindly.** Simplification must preserve behavior and pass tests.
4. **Treating scans as proof.** Static scans catch classes of risk; they do not replace code review.
5. **Reporting unrun tests as passing.** Only claim commands that actually executed.

## Verification Checklist

- [ ] The chosen workflow matches the uncertainty/risk.
- [ ] Evidence includes real command output or inspected artifacts.
- [ ] Tests fail/pass in the expected order for TDD.
- [ ] Simplification changes are smaller and behavior-preserving.
- [ ] Pre-commit summary distinguishes verified, not run, and blocked checks.
