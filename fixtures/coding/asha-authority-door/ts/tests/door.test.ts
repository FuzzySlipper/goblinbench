import assert from "node:assert/strict";
import test from "node:test";

import type { DoorPolicyView, DoorProjection } from "@mini-asha/contracts";
import { proposeDoorTransition } from "@mini-asha/policy-door";
import { displayDoor } from "@mini-asha/renderer-door";

const view: DoorPolicyView = {
  entityId: 7,
  position: "closed",
  availableEnergy: 1,
  openEnergyCost: 4,
  cooldownUntilTick: 50,
  revision: 3,
  observedTick: 10,
};

test("policy proposes intent without duplicating Rust acceptance", () => {
  assert.deepEqual(proposeDoorTransition(view, "open"), {
    entityId: 7,
    desired: "open",
    expectedRevision: 3,
    observedTick: 10,
  });
});

test("policy avoids a redundant proposal", () => {
  assert.equal(proposeDoorTransition(view, "closed"), undefined);
});

test("renderer consumes the supplied projection", () => {
  const projection: DoorProjection = {
    entityId: 7,
    position: "open",
    opennessMilli: 625,
    revision: 4,
  };
  assert.deepEqual(displayDoor(projection), {
    entityId: 7,
    openness: 0.625,
    stateLabel: "open",
    revision: 4,
  });
});

