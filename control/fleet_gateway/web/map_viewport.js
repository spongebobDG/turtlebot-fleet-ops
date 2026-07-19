(function attachFleetMapViewport(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.FleetMapViewport = api;
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
  "use strict";

  const finitePositive = (value, name) => {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) {
      throw new Error(`${name} must be a positive finite number`);
    }
    return number;
  };

  const fit = (mapWidth, mapHeight, viewWidth, viewHeight, padding = 12) => {
    const width = finitePositive(mapWidth, "mapWidth");
    const height = finitePositive(mapHeight, "mapHeight");
    const viewportWidth = finitePositive(viewWidth, "viewWidth");
    const viewportHeight = finitePositive(viewHeight, "viewHeight");
    const safePadding = Math.max(0, Number(padding) || 0);
    const availableWidth = Math.max(1, viewportWidth - safePadding * 2);
    const availableHeight = Math.max(1, viewportHeight - safePadding * 2);
    const fitScale = Math.min(
      availableWidth / width,
      availableHeight / height,
    );
    return {
      mapWidth: width,
      mapHeight: height,
      viewWidth: viewportWidth,
      viewHeight: viewportHeight,
      fitScale,
      scale: fitScale,
      zoom: 1,
      offsetX: (viewportWidth - width * fitScale) / 2,
      offsetY: (viewportHeight - height * fitScale) / 2,
    };
  };

  const mapToScreen = (viewport, x, y) => ({
    x: viewport.offsetX + Number(x) * viewport.scale,
    y: viewport.offsetY + Number(y) * viewport.scale,
  });

  const screenToMap = (viewport, x, y, clampToMap = false) => {
    let mapX = (Number(x) - viewport.offsetX) / viewport.scale;
    let mapY = (Number(y) - viewport.offsetY) / viewport.scale;
    const inside = mapX >= 0 && mapY >= 0
      && mapX < viewport.mapWidth && mapY < viewport.mapHeight;
    if (!inside && !clampToMap) return null;
    if (clampToMap) {
      mapX = Math.max(0, Math.min(viewport.mapWidth - 1e-9, mapX));
      mapY = Math.max(0, Math.min(viewport.mapHeight - 1e-9, mapY));
    }
    return { x: mapX, y: mapY, inside };
  };

  const clampOffsets = (viewport) => {
    const mapDisplayWidth = viewport.mapWidth * viewport.scale;
    const mapDisplayHeight = viewport.mapHeight * viewport.scale;
    const margin = 12;
    if (mapDisplayWidth <= viewport.viewWidth - margin * 2) {
      viewport.offsetX = (viewport.viewWidth - mapDisplayWidth) / 2;
    } else {
      const minX = viewport.viewWidth - margin - mapDisplayWidth;
      viewport.offsetX = Math.max(minX, Math.min(margin, viewport.offsetX));
    }
    if (mapDisplayHeight <= viewport.viewHeight - margin * 2) {
      viewport.offsetY = (viewport.viewHeight - mapDisplayHeight) / 2;
    } else {
      const minY = viewport.viewHeight - margin - mapDisplayHeight;
      viewport.offsetY = Math.max(minY, Math.min(margin, viewport.offsetY));
    }
    return viewport;
  };

  const zoomAt = (viewport, zoom, anchorX, anchorY) => {
    const nextZoom = Math.max(1, Math.min(8, Number(zoom)));
    const anchor = screenToMap(viewport, anchorX, anchorY, true);
    viewport.zoom = nextZoom;
    viewport.scale = viewport.fitScale * nextZoom;
    viewport.offsetX = Number(anchorX) - anchor.x * viewport.scale;
    viewport.offsetY = Number(anchorY) - anchor.y * viewport.scale;
    return clampOffsets(viewport);
  };

  const pan = (viewport, deltaX, deltaY) => {
    viewport.offsetX += Number(deltaX) || 0;
    viewport.offsetY += Number(deltaY) || 0;
    return clampOffsets(viewport);
  };

  return { fit, mapToScreen, screenToMap, zoomAt, pan };
}));
