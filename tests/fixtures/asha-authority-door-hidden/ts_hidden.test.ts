import assert from "node:assert/strict";
import test from "node:test";

import type { DoorPolicyView } from "@mini-asha/contracts";
import { proposeDoorTransition } from "@mini-asha/policy-door";
import { displayDoor } from "@mini-asha/renderer-door";

test("policy leaves insufficient-energy and cooldown rejection to Rust", () => {
  const view: DoorPolicyView = Object.freeze({
    entityId: 4,
    position: "closed",
    availableEnergy: 0,
    openEnergyCost: 50,
    cooldownUntilTick: 999,
    revision: 12,
    observedTick: 2,
  });
  const before = structuredClone(view);
  assert.deepEqual(proposeDoorTransition(view, "open"), {
    entityId: 4,
    desired: "open",
    expectedRevision: 12,
    observedTick: 2,
  });
  assert.deepEqual(view, before);
});

test("renderer uses projection values without deciding authority", () => {
  assert.deepEqual(
    displayDoor({ entityId: 4, position: "closed", opennessMilli: 400, revision: 12 }),
    { entityId: 4, openness: 0.4, stateLabel: "closed", revision: 12 },
  );
});
