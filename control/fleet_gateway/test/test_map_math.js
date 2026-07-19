"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  canvasToWorld,
  isFreePose,
  worldToCanvas,
  worldToCell,
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
