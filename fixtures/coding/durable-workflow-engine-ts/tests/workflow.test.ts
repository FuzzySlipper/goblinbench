import { describe, expect, test } from "vitest";
import {
  EventOutbox,
  InMemoryWorkflowRepository,
  WorkflowEngine,
  WorkflowError,
  type TaskLease,
  type WorkflowDefinition,
} from "../src";

function definition(id = "release"): WorkflowDefinition {
  return {
    id,
    tasks: [
      { id: "compile", dependencies: [], resource: "cpu", maxAttempts: 3, retryDelayMs: 100 },
      { id: "unit", dependencies: ["compile"], resource: "cpu", maxAttempts: 2, retryDelayMs: 50 },
      { id: "package", dependencies: ["unit"], resource: "io", maxAttempts: 2, retryDelayMs: 100 },
    ],
  };
}

function claim(engine: WorkflowEngine, worker: string, resources: string[], nowMs = 0): TaskLease {
  const lease = engine.claim(worker, resources, nowMs, 40);
  expect(lease).toBeDefined();
  return lease!;
}

function expectCode(action: () => unknown, code: string): void {
  try {
    action();
    throw new Error("expected WorkflowError");
  } catch (error) {
    expect(error).toBeInstanceOf(WorkflowError);
    expect((error as WorkflowError).code).toBe(code);
  }
}

describe("durable workflow engine", () => {
  test("validates duplicate task ids, unknown dependencies, and cycles before persistence", () => {
    const engine = new WorkflowEngine();
    const invalid: WorkflowDefinition = {
      id: "broken",
      tasks: [
        { id: "a", dependencies: ["missing", "b"], resource: "cpu", maxAttempts: 0, retryDelayMs: -1 },
        { id: "a", dependencies: [], resource: "", maxAttempts: 1, retryDelayMs: 0 },
        { id: "b", dependencies: ["a"], resource: "cpu", maxAttempts: 1, retryDelayMs: 0 },
      ],
    };

    expectCode(() => engine.submit(invalid, "invalid-key"), "invalid_definition");
    expect(engine.repository.get("broken")).toBeUndefined();
    expect(engine.outbox.after(0)).toEqual([]);
  });

  test("exact submission replay is idempotent while key reuse with another definition conflicts", () => {
    const engine = new WorkflowEngine();
    expect(engine.submit(definition(), "release-key")).toEqual({ workflowId: "release", replayed: false });
    const eventCount = engine.outbox.after(0).length;
    expect(engine.submit(definition(), "release-key")).toEqual({ workflowId: "release", replayed: true });
    expect(engine.outbox.after(0)).toHaveLength(eventCount);

    expectCode(() => engine.submit(definition("other"), "release-key"), "idempotency_conflict");
    expect(engine.repository.get("other")).toBeUndefined();
  });

  test("two engines sharing persistence observe one idempotent workflow and one outbox stream", () => {
    const repository = new InMemoryWorkflowRepository();
    const outbox = new EventOutbox();
    const first = new WorkflowEngine(repository, outbox);
    const second = new WorkflowEngine(repository, outbox);

    expect(first.submit(definition(), "key").replayed).toBe(false);
    expect(second.submit(definition(), "key").replayed).toBe(true);
    expect(repository.list()).toHaveLength(1);
    expect(outbox.after(0).filter((event) => event.type === "workflow.submitted")).toHaveLength(1);
  });

  test("claim honors dependency readiness and resource capability", () => {
    const engine = new WorkflowEngine();
    engine.submit(definition(), "key");
    expect(engine.claim("io-only", ["io"], 0, 50)).toBeUndefined();
    const compile = claim(engine, "cpu-worker", ["cpu"]);
    expect(compile.taskId).toBe("compile");
    engine.complete(compile);
    const unit = claim(engine, "cpu-worker", ["cpu"]);
    expect(unit.taskId).toBe("unit");
  });

  test("claim order is workflow creation order then task declaration order", () => {
    const engine = new WorkflowEngine();
    engine.submit({ id: "first", tasks: [
      { id: "one", dependencies: [], resource: "cpu", maxAttempts: 1, retryDelayMs: 0 },
      { id: "two", dependencies: [], resource: "cpu", maxAttempts: 1, retryDelayMs: 0 },
    ] }, "first-key");
    engine.submit({ id: "second", tasks: [
      { id: "three", dependencies: [], resource: "cpu", maxAttempts: 1, retryDelayMs: 0 },
    ] }, "second-key");

    expect(claim(engine, "w1", ["cpu"]).taskId).toBe("one");
    expect(claim(engine, "w2", ["cpu"]).taskId).toBe("two");
    expect(claim(engine, "w3", ["cpu"]).workflowId).toBe("second");
  });

  test("live leases are exclusive across engine instances sharing a repository", () => {
    const repository = new InMemoryWorkflowRepository();
    const outbox = new EventOutbox();
    const first = new WorkflowEngine(repository, outbox);
    const second = new WorkflowEngine(repository, outbox);
    first.submit(definition(), "key");

    const lease = claim(first, "first", ["cpu"], 100);
    expect(second.claim("second", ["cpu"], 120, 40)).toBeUndefined();
    expect(lease.worker).toBe("first");
  });

  test("expired leases receive a new fencing token and stale owners cannot mutate", () => {
    const engine = new WorkflowEngine();
    engine.submit(definition(), "key");
    const oldLease = claim(engine, "old", ["cpu"], 100);
    expect(engine.claim("early", ["cpu"], 139, 40)).toBeUndefined();
    const newLease = claim(engine, "new", ["cpu"], 140);

    expect(newLease.token).not.toBe(oldLease.token);
    expect(newLease.attempt).toBe(2);
    expectCode(() => engine.complete(oldLease), "stale_lease");
    engine.complete(newLease);
  });

  test("heartbeat extends from observed time and preserves the fencing token", () => {
    const engine = new WorkflowEngine();
    engine.submit(definition(), "key");
    const lease = claim(engine, "worker", ["cpu"], 100);
    const renewed = engine.heartbeat(lease, 130, 80);
    expect(renewed).toEqual({ ...lease, expiresAtMs: 210 });
    expect(engine.claim("other", ["cpu"], 180, 40)).toBeUndefined();
  });

  test("retry uses exponential attempt backoff and is not ready early", () => {
    const engine = new WorkflowEngine();
    engine.submit(definition(), "key");
    const first = claim(engine, "worker", ["cpu"], 1_000);
    engine.fail(first, 1_010, true, "transient");
    expect(engine.snapshot("release").tasks.compile).toMatchObject({ status: "retry_wait", readyAtMs: 1_110 });
    expect(engine.claim("worker", ["cpu"], 1_109, 40)).toBeUndefined();
    const second = claim(engine, "worker", ["cpu"], 1_110);
    engine.fail(second, 1_120, true, "transient");
    expect(engine.snapshot("release").tasks.compile).toMatchObject({ status: "retry_wait", readyAtMs: 1_320 });
  });

  test("non-retryable failure blocks transitive dependants and fails workflow", () => {
    const engine = new WorkflowEngine();
    engine.submit(definition(), "key");
    const compile = claim(engine, "worker", ["cpu"], 0);
    engine.fail(compile, 1, false, "bad source");

    const snapshot = engine.snapshot("release");
    expect(snapshot.status).toBe("failed");
    expect(snapshot.tasks.compile).toMatchObject({ status: "failed", failure: "bad source" });
    expect(snapshot.tasks.unit).toMatchObject({ status: "blocked", blockedBy: "compile" });
    expect(snapshot.tasks.package).toMatchObject({ status: "blocked", blockedBy: "unit" });
  });

  test("attempt exhaustion is terminal even when the failure was retryable", () => {
    const engine = new WorkflowEngine();
    engine.submit({ id: "one-shot", tasks: [
      { id: "task", dependencies: [], resource: "cpu", maxAttempts: 1, retryDelayMs: 10 },
    ] }, "key");
    const lease = claim(engine, "worker", ["cpu"], 0);
    engine.fail(lease, 1, true, "still broken");
    expect(engine.snapshot("one-shot")).toMatchObject({ status: "failed", tasks: { task: { status: "failed" } } });
  });

  test("completing every task succeeds workflow without duplicate terminal events", () => {
    const engine = new WorkflowEngine();
    engine.submit(definition(), "key");
    for (const resource of ["cpu", "cpu", "io"]) {
      engine.complete(claim(engine, "worker", [resource]));
    }
    expect(engine.snapshot("release").status).toBe("succeeded");
    expect(engine.outbox.after(0).filter((event) => event.type === "workflow.succeeded")).toHaveLength(1);
  });

  test("cancellation is idempotent, cancels nonterminal tasks, and preserves completed work", () => {
    const engine = new WorkflowEngine();
    engine.submit(definition(), "key");
    engine.complete(claim(engine, "worker", ["cpu"]));
    engine.cancelWorkflow("release");
    engine.cancelWorkflow("release");

    const snapshot = engine.snapshot("release");
    expect(snapshot.status).toBe("cancelled");
    expect(snapshot.tasks.compile?.status).toBe("succeeded");
    expect(snapshot.tasks.unit?.status).toBe("cancelled");
    expect(snapshot.tasks.package?.status).toBe("cancelled");
    expect(engine.outbox.after(0).filter((event) => event.type === "workflow.cancelled")).toHaveLength(1);
  });

  test("outbox sequence is gapless and transition events are emitted once", () => {
    const engine = new WorkflowEngine();
    engine.submit(definition(), "key");
    const lease = claim(engine, "worker", ["cpu"]);
    engine.heartbeat(lease, 10, 40);
    engine.complete(lease);

    const events = engine.outbox.after(0);
    expect(events.map((event) => event.sequence)).toEqual(events.map((_, index) => index + 1));
    expect(events.map((event) => event.type)).toEqual([
      "workflow.submitted",
      "task.claimed",
      "task.heartbeat",
      "task.succeeded",
    ]);
    expect(engine.outbox.after(2).map((event) => event.sequence)).toEqual([3, 4]);
  });

  test("snapshots are detached copies and cannot mutate repository state", () => {
    const engine = new WorkflowEngine();
    engine.submit(definition(), "key");
    const snapshot = engine.snapshot("release");
    snapshot.tasks.compile!.status = "succeeded";
    expect(engine.snapshot("release").tasks.compile?.status).toBe("pending");
  });
});
