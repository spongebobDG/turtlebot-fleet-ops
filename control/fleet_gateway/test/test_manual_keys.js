"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { commandForKey, isEditableTarget } = require("../web/manual_keys.js");

test("WASD maps to the existing bounded manual velocities", () => {
  assert.deepEqual(commandForKey("w"), {
    key: "w", linearX: 0.05, angularZ: 0.0, label: "W · 전진",
  });
  assert.equal(commandForKey("A").angularZ, 0.3);
  assert.equal(commandForKey("s").linearX, -0.05);
  assert.equal(commandForKey("D").angularZ, -0.3);
  assert.equal(commandForKey("ArrowUp"), null);
});

test("keyboard driving ignores text-entry controls", () => {
  assert.equal(isEditableTarget({ tagName: "INPUT" }), true);
  assert.equal(isEditableTarget({ tagName: "textarea" }), true);
  assert.equal(isEditableTarget({ tagName: "SELECT" }), true);
  assert.equal(isEditableTarget({ tagName: "DIV", isContentEditable: true }), true);
  assert.equal(isEditableTarget({ tagName: "CANVAS" }), false);
  assert.equal(isEditableTarget(null), false);
});
