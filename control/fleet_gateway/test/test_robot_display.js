"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { selectDisplayPose } = require("../web/robot_display.js");

test("dashboard position prefers the map-frame navigation pose", () => {
  const pose = selectDisplayPose({
    navigation: {
      current: { frame_id: "map", x: -0.13, y: -0.42, yaw: -0.18 },
    },
    odom: { x: -0.77, y: 0.74, yaw: -0.13 },
  });

  assert.deepEqual(pose, {
    frame_id: "map",
    x: -0.13,
    y: -0.42,
    yaw: -0.18,
  });
});

test("dashboard position falls back to odom before localization", () => {
  const pose = selectDisplayPose({
    navigation: {
      current: { frame_id: "", x: 0, y: 0, yaw: 0 },
    },
    odom: { x: 1, y: 2, yaw: 0.5 },
  });

  assert.deepEqual(pose, {
    frame_id: "odom",
    x: 1,
    y: 2,
    yaw: 0.5,
  });
});

test("dashboard position fails closed for invalid pose values", () => {
  assert.deepEqual(selectDisplayPose({ odom: { x: NaN, y: 0, yaw: 0 } }), {
    frame_id: "—",
    x: null,
    y: null,
    yaw: null,
  });
});
