const test = require("node:test");
const assert = require("node:assert/strict");

const viewportMath = require("../web/map_viewport.js");

test("fit preserves map aspect ratio and centers it", () => {
  const viewport = viewportMath.fit(58, 96, 380, 440, 10);
  assert.equal(viewport.zoom, 1);
  assert.ok(Math.abs(viewport.scale - 4.375) < 1e-9);
  assert.ok(Math.abs(viewport.offsetX - 63.125) < 1e-9);
  assert.equal(viewport.offsetY, 10);
});

test("screen and map coordinates round-trip after zoom and pan", () => {
  const viewport = viewportMath.fit(80, 60, 500, 400, 10);
  viewportMath.zoomAt(viewport, 2.5, 250, 200);
  viewportMath.pan(viewport, -35, 20);
  const screen = viewportMath.mapToScreen(viewport, 31.25, 18.75);
  const map = viewportMath.screenToMap(viewport, screen.x, screen.y);
  assert.ok(Math.abs(map.x - 31.25) < 1e-9);
  assert.ok(Math.abs(map.y - 18.75) < 1e-9);
});

test("outside clicks fail closed while clamped anchors remain usable", () => {
  const viewport = viewportMath.fit(20, 20, 200, 200, 0);
  assert.equal(viewportMath.screenToMap(viewport, -1, 100), null);
  const clamped = viewportMath.screenToMap(viewport, -1, 100, true);
  assert.equal(clamped.inside, false);
  assert.equal(clamped.x, 0);
});

test("zoom remains bounded for usable navigation", () => {
  const viewport = viewportMath.fit(100, 100, 500, 500, 0);
  viewportMath.zoomAt(viewport, 100, 250, 250);
  assert.equal(viewport.zoom, 8);
  viewportMath.zoomAt(viewport, 0.1, 250, 250);
  assert.equal(viewport.zoom, 1);
});

test("zoomed maps pan within the viewport instead of staying centered", () => {
  const viewport = viewportMath.fit(100, 100, 300, 200, 10);
  viewportMath.zoomAt(viewport, 4, 150, 100);
  const centeredOffset = viewport.offsetX;

  viewportMath.pan(viewport, 50, 0);

  assert.ok(viewport.offsetX > centeredOffset);
  viewportMath.pan(viewport, 10000, 0);
  assert.equal(viewport.offsetX, 12);
});
