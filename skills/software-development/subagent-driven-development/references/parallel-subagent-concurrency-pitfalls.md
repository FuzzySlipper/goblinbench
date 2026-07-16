# Parallel Subagent Concurrency Pitfalls

When dispatching multiple subagents in parallel (via `delegate_task(tasks=[...])`), overlapping file writes can cause silent corruption. This reference covers detection, recovery, and prevention.

## The problem

Each subagent gets a clean context and terminal session. They can read from and write to the same project files independently. If two subagents read the same file at nearly the same time, modify different sections, and write back, **one subagent's changes overwrite the other's** — the second write replaces the entire file.

The parent process has no automatic merge capability. The standard `patch` tool only detects drift on its own writes; it cannot detect two subagents overwriting each other's changes.

## Symptom patterns

| Symptom | Likely Cause |
|---------|-------------|
| Build succeeds but tests fail with missing assertions | Test file was overwritten by second subagent |
| Code compiles but logical paths are missing | Route/controller file was overwritten |
| "File was modified since you last read it" warnings | Another subagent wrote the file between your reads |
| Syntax errors in a file one subagent "definitely didn't touch" | Subagent wrote the file, resetting content that another subagent had added |
| Pre-existing feature code is suddenly gone | The later-writer subagent's write replaced the earlier one's |

## Prevention

### 1. Assign clear file ownership per subagent

Before dispatching, enumerate which files each subagent will touch. If two subagents touch the same file, they CANNOT run in parallel — serialize them.

**GOOD — files are disjoint:**
```python
tasks = [
    {"goal": "Remove GatewayStateClient, update GatewayRoutes.cs", ...},  # touches Gateway/*
    {"goal": "Remove Gateway dependency from AgentsOverviewService", ...},  # touches AgentsOverview/*
    {"goal": "Update Program.cs DI, config, den-host", ...},               # touches Program.cs, config, den-host/*
]
```

**BAD — overlapping files:**
```python
tasks = [
    {"goal": "Add new route", ...},      # touches Routes.cs
    {"goal": "Remove old route", ...},   # also touches Routes.cs — CONFLICT!
]
```

### 2. Isolate by directory, not by function

If two subagents need to touch the same directory, they probably conflict. Split by directory boundary when possible.

### 3. When serial is required, dispatch one at a time

```python
# Dispatch sequentially for overlapping files
result1 = await delegate_task(goal="Step 1: Add route", ...)
result2 = await delegate_task(goal="Step 2: Update DI", ...)
```

## Recovery after parallel dispatch

After ALL parallel subagents complete:

### 1. Read the subagent notes for "modified files" warnings

Both the subagent result and the parent conversation will show warnings like:
> `[NOTE: subagent modified files the parent previously read — re-read before editing: file1.cs, file2.cs]`

This is a red flag that the parent's cached file state is stale.

### 2. Re-read ALL touched files before continuing

```python
# Read every file that was modified by any subagent
files = ["File1.cs", "File2.cs", ...]
for f in files:
    content = read_file(f)  # get fresh state from disk
```

### 3. Build immediately

```bash
dotnet build
```

If the build fails with unexpected errors, one or more subagent writes were corrupted. Check `git diff` to see if expected changes are present.

### 4. Fix missing changes manually

If a subagent's changes were lost:
1. Re-read the subagent's original goal/context
2. Re-apply the change with `patch`
3. Rebuild and test

### 5. Run tests immediately after build

```bash
dotnet test
```

Expect some failures from expected behavioral changes (removing a feature causes its tests to need updating). Watch for UNEXPECTED failures — tests that should still pass but don't, indicating a corrupted file.

## Edge cases

### File was NOT directly edited but still affected

If subagent A modifies `FileA.cs` and subagent B modifies `FileB.cs` that includes/imports `FileA.cs`, there's no direct file conflict. However, if `FileB.cs` had a stale import or reference to an API that A removed, B's work may silently compile against the wrong state. This is less likely to cause corruption but can cause compilation errors.

### The "both touched Program.cs" case

When one subagent needs to update DI registration and another needs to remove a config section from the same Program.cs, **serialize them**. The safe pattern:

```python
# Step 1: Config changes only
result1 = await delegate_task(goal="Remove GatewayOptions from DenChannelsOptions.cs", ...)
# Step 2: DI changes (reads updated config)
result2 = await delegate_task(goal="Remove GatewayStateClient DI from Program.cs", ...)
```

### C# `$""` strings and `patch` escape-drift

When subagents use the `patch` tool on C# files containing interpolated strings (`$"..."`), the tool may report "Escape-drift detected" even when the literal text is unchanged. Workaround: use `sed` via the terminal tool for single-line replacements, or re-read the file and craft the patch more precisely.

```bash
# Example: replace /api/gateway/events with /api/direct-agent-events in all .cs files
sed -i 's|/api/gateway/events|/api/direct-agent-events|g' src/**/*.cs
```

## Summary checklist

After parallel subagent dispatch:

- [ ] Read all subagent summary notes for "modified files" warnings
- [ ] Re-read all touched files from disk
- [ ] Build immediately
- [ ] Fix any missing changes
- [ ] Run targeted tests
- [ ] Run full test suite
- [ ] Verify git diff shows ALL expected changes
