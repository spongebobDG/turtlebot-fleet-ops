const test = require("node:test");
const assert = require("node:assert/strict");

const annotations = require("../web/map_annotations.js");

test("virtual wall includes its configured robot safety margin", () => {
  const wall = {
    enabled: true,
    type: "virtual_wall",
    name: "복도 벽",
    width_m: 0.08,
    safety_margin_m: 0.16,
    points: [{ x: 0, y: -1 }, { x: 0, y: 1 }],
  };

  assert.equal(annotations.blocksPoint(wall, 0.19, 0), true);
  assert.equal(annotations.blocksPoint(wall, 0.21, 0), false);
  assert.match(annotations.blockedReason([wall], 0, 0), /복도 벽/);
});

test("privacy and keepout polygons block their interior and margin", () => {
  const privacy = {
    enabled: true,
    type: "privacy",
    name: "상담실",
    safety_margin_m: 0.1,
    points: [
      { x: 0, y: 0 },
      { x: 1, y: 0 },
      { x: 1, y: 1 },
      { x: 0, y: 1 },
    ],
  };

  assert.equal(annotations.blocksPoint(privacy, 0.5, 0.5), true);
  assert.equal(annotations.blocksPoint(privacy, 1.05, 0.5), true);
  assert.equal(annotations.blocksPoint(privacy, 1.2, 0.5), false);
});

test("charging positions are visible destinations, not barriers", () => {
  const charging = {
    enabled: true,
    type: "charging",
    name: "충전기",
    pose: { x: 0.5, y: 0.5, yaw: 0 },
  };

  assert.equal(annotations.blocksPoint(charging, 0.5, 0.5), false);
  assert.equal(annotations.blockedReason([charging], 0.5, 0.5), "");
});
