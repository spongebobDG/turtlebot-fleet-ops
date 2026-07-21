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

  const worldToCell = (map, x, y) => {
    const canvas = worldToCanvas(map, x, y);
    const cellX = Math.floor(canvas.x);
    const cellY = Math.floor(map.height - canvas.y);
    if (
      cellX < 0
      || cellY < 0
      || cellX >= map.width
      || cellY >= map.height
    ) {
      return null;
    }
    return {
      x: cellX,
      y: cellY,
      index: cellY * map.width + cellX,
    };
  };

  const isFreePose = (map, x, y) => {
    const cell = worldToCell(map, x, y);
    return Boolean(
      cell
      && Array.isArray(map.data)
      && map.data[cell.index] === 0
    );
  };

  const yawFromCanvasDrag = (map, startX, startY, endX, endY) => {
    const start = canvasToWorld(map, startX, startY);
    const end = canvasToWorld(map, endX, endY);
    const deltaX = end.x - start.x;
    const deltaY = end.y - start.y;
    if (Math.hypot(deltaX, deltaY) <= 1e-9) return null;
    return Math.atan2(deltaY, deltaX);
  };

  const hasSameGeometry = (first, second) => Boolean(
    first
    && second
    && first.width === second.width
    && first.height === second.height
    && first.resolution === second.resolution
    && first.origin
    && second.origin
    && first.origin.x === second.origin.x
    && first.origin.y === second.origin.y
    && first.origin.yaw === second.origin.yaw
  );

  const centerFreePose = (map) => {
    validate(map, map.origin.x, map.origin.y);
    if (!Array.isArray(map.data) || map.data.length !== map.width * map.height) {
      return null;
    }
    const centerX = (map.width - 1) / 2;
    const centerY = (map.height - 1) / 2;
    let nearest = null;
    for (let cellY = 0; cellY < map.height; cellY += 1) {
      for (let cellX = 0; cellX < map.width; cellX += 1) {
        if (map.data[cellY * map.width + cellX] !== 0) continue;
        const distanceSquared = (cellX - centerX) ** 2 + (cellY - centerY) ** 2;
        if (!nearest || distanceSquared < nearest.distanceSquared) {
          nearest = { cellX, cellY, distanceSquared };
        }
      }
    }
    if (!nearest) return null;
    const world = canvasToWorld(
      map,
      nearest.cellX + 0.5,
      map.height - nearest.cellY - 0.5,
    );
    return { ...world, yaw: 0 };
  };

  return {
    canvasToWorld,
    centerFreePose,
    hasSameGeometry,
    isFreePose,
    worldToCanvas,
    worldToCell,
    yawFromCanvasDrag,
  };
}));
