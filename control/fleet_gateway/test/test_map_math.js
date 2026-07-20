"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  canvasToWorld,
  centerFreePose,
  hasSameGeometry,
  isFreePose,
  worldToCanvas,
  worldToCell,
  yawFromCanvasDrag,
} = require("../web/map_math.js");

const closeTo = (actual, expected, tolerance = 1e-12) => {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} != ${expected}`);
};

test("world and canvas coordinates round-trip with row inversion", () => {
  const map = {
    width: 8,
    height: 10,
    resolution: 0.5,
    origin: { x: -2, y: -3, yaw: 0 },
  };
  const canvas = worldToCanvas(map, -0.75, -0.25);
  closeTo(canvas.x, 2.5);
  closeTo(canvas.y, 4.5);
  const world = canvasToWorld(map, canvas.x, canvas.y);
  closeTo(world.x, -0.75);
  closeTo(world.y, -0.25);
});

test("origin yaw rotates map-local axes before canvas conversion", () => {
  const map = {
    width: 3,
    height: 4,
    resolution: 1,
    origin: { x: 10, y: 20, yaw: Math.PI / 2 },
  };
  const canvas = worldToCanvas(map, 9.5, 21.5);
  closeTo(canvas.x, 1.5);
  closeTo(canvas.y, 3.5);
  const world = canvasToWorld(map, 1.5, 3.5);
  closeTo(world.x, 9.5);
  closeTo(world.y, 21.5);
});

test("invalid map metadata and coordinates fail closed", () => {
  const map = {
    width: 2,
    height: 2,
    resolution: 0,
    origin: { x: 0, y: 0, yaw: 0 },
  };
  assert.throws(() => worldToCanvas(map, 0, 0), /resolution/);
  map.resolution = 1;
  assert.throws(() => canvasToWorld(map, Number.NaN, 0), /Coordinates/);
  map.height = 0;
  assert.throws(() => worldToCanvas(map, 0, 0), /dimensions/);
});

test("world coordinates resolve to the row-major occupancy cell", () => {
  const map = {
    width: 3,
    height: 2,
    resolution: 0.5,
    origin: { x: -1, y: -2, yaw: 0 },
    data: [100, 0, -1, 0, 0, 100],
  };

  assert.deepEqual(worldToCell(map, -0.25, -1.75), {
    x: 1,
    y: 0,
    index: 1,
  });
  assert.equal(isFreePose(map, -0.25, -1.75), true);
  assert.equal(isFreePose(map, -0.75, -1.75), false);
  assert.equal(worldToCell(map, 1, -1.75), null);
});

test("world-to-cell honors a rotated map origin", () => {
  const map = {
    width: 2,
    height: 2,
    resolution: 1,
    origin: { x: 10, y: 20, yaw: Math.PI / 2 },
    data: [0, 100, 100, 100],
  };

  assert.deepEqual(worldToCell(map, 9.5, 20.5), {
    x: 0,
    y: 0,
    index: 0,
  });
  assert.equal(isFreePose(map, 9.5, 20.5), true);
});

test("canvas drag yaw follows the triangle endpoint in map coordinates", () => {
  const map = {
    width: 10,
    height: 10,
    resolution: 0.1,
    origin: { x: 0, y: 0, yaw: 0 },
  };

  closeTo(yawFromCanvasDrag(map, 5, 5, 7, 5), 0);
  closeTo(yawFromCanvasDrag(map, 5, 5, 5, 3), Math.PI / 2);
  assert.equal(yawFromCanvasDrag(map, 5, 5, 5, 5), null);
});

test("canvas drag yaw includes a rotated occupancy-grid origin", () => {
  const map = {
    width: 10,
    height: 10,
    resolution: 0.1,
    origin: { x: 2, y: -1, yaw: Math.PI / 2 },
  };

  closeTo(yawFromCanvasDrag(map, 5, 5, 7, 5), Math.PI / 2);
  closeTo(yawFromCanvasDrag(map, 5, 5, 5, 3), Math.PI);
});

test("map geometry ignores occupancy updates but detects an expanded map", () => {
  const original = {
    width: 10,
    height: 8,
    resolution: 0.05,
    origin: { x: -1, y: -2, yaw: 0 },
    data: [0, 100],
  };
  const occupancyUpdate = {
    ...original,
    data: [100, 0],
  };
  const expanded = {
    ...occupancyUpdate,
    width: 12,
    origin: { ...original.origin, x: -1.1 },
  };

  assert.equal(hasSameGeometry(original, occupancyUpdate), true);
  assert.equal(hasSameGeometry(original, expanded), false);
  assert.equal(hasSameGeometry(original, null), false);
});

test("center free pose provides a safe seed for global LiDAR alignment", () => {
  const map = {
    width: 3,
    height: 3,
    resolution: 0.5,
    origin: { x: -1, y: -2, yaw: 0 },
    data: [100, 0, 100, 0, -1, 0, 100, 0, 100],
  };

  assert.deepEqual(centerFreePose(map), { x: -0.25, y: -1.75, yaw: 0 });
  assert.equal(centerFreePose({ ...map, data: Array(9).fill(100) }), null);
});
