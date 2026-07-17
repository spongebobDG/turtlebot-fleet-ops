(function exposeMapMath(root, factory) {
  const mapMath = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = mapMath;
  }
  root.FleetMapMath = mapMath;
}(typeof globalThis === "undefined" ? this : globalThis, () => {
  const validate = (map, x, y) => {
    if (
      !map
      || !Number.isFinite(map.width)
      || !Number.isFinite(map.height)
      || map.width <= 0
      || map.height <= 0
    ) {
      throw new TypeError("Map dimensions must be positive and finite");
    }
    if (!Number.isFinite(map.resolution) || map.resolution <= 0) {
      throw new TypeError("Map resolution must be positive and finite");
    }
    if (!map.origin || ![map.origin.x, map.origin.y, map.origin.yaw].every(Number.isFinite)) {
      throw new TypeError("Map origin must be finite");
    }
    if (![x, y].every(Number.isFinite)) {
      throw new TypeError("Coordinates must be finite");
    }
  };

  const worldToCanvas = (map, x, y) => {
    validate(map, x, y);
    const deltaX = x - map.origin.x;
    const deltaY = y - map.origin.y;
    const cosine = Math.cos(map.origin.yaw);
    const sine = Math.sin(map.origin.yaw);
    const localX = cosine * deltaX + sine * deltaY;
    const localY = -sine * deltaX + cosine * deltaY;
    return {
      x: localX / map.resolution,
      y: map.height - localY / map.resolution,
    };
  };

  const canvasToWorld = (map, x, y) => {
    validate(map, x, y);
    const localX = x * map.resolution;
    const localY = (map.height - y) * map.resolution;
    const cosine = Math.cos(map.origin.yaw);
    const sine = Math.sin(map.origin.yaw);
    return {
      x: map.origin.x + cosine * localX - sine * localY,
      y: map.origin.y + sine * localX + cosine * localY,
    };
  };

  return { canvasToWorld, worldToCanvas };
}));
