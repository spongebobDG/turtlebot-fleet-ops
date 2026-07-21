(function exposeMapAnnotations(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.FleetMapAnnotations = api;
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
  "use strict";

  const types = {
    virtual_wall: {
      label: "가상 벽",
      color: "#ff5f67",
      fill: "rgba(255, 95, 103, 0.16)",
    },
    keepout: {
      label: "금지구역",
      color: "#ff9f43",
      fill: "rgba(255, 159, 67, 0.22)",
    },
    privacy: {
      label: "개인정보 보호구역",
      color: "#c084fc",
      fill: "rgba(192, 132, 252, 0.23)",
    },
    charging: {
      label: "충전 위치",
      color: "#38d996",
      fill: "rgba(56, 217, 150, 0.2)",
    },
  };

  const distanceToSegment = (x, y, first, second) => {
    const deltaX = second.x - first.x;
    const deltaY = second.y - first.y;
    const lengthSquared = deltaX ** 2 + deltaY ** 2;
    if (lengthSquared <= 1e-12) return Math.hypot(x - first.x, y - first.y);
    const ratio = Math.max(0, Math.min(
      1,
      ((x - first.x) * deltaX + (y - first.y) * deltaY) / lengthSquared,
    ));
    return Math.hypot(
      x - (first.x + ratio * deltaX),
      y - (first.y + ratio * deltaY),
    );
  };

  const polygonEdges = (points) => points.map(
    (point, index) => [point, points[(index + 1) % points.length]],
  );

  const pointInPolygon = (x, y, points) => {
    let inside = false;
    let previous = points[points.length - 1];
    for (const current of points) {
      if ((current.y > y) !== (previous.y > y)) {
        const boundaryX = ((previous.x - current.x) * (y - current.y))
          / (previous.y - current.y) + current.x;
        if (x < boundaryX) inside = !inside;
      }
      previous = current;
    }
    return inside;
  };

  const blocksPoint = (annotation, x, y) => {
    if (!annotation?.enabled || !["virtual_wall", "keepout", "privacy"].includes(annotation.type)) {
      return false;
    }
    const points = annotation.points || [];
    const margin = Math.max(0, Number(annotation.safety_margin_m) || 0);
    if (annotation.type === "virtual_wall") {
      const radius = margin + Math.max(0, Number(annotation.width_m) || 0) / 2;
      return points.slice(1).some(
        (point, index) => distanceToSegment(x, y, points[index], point) <= radius,
      );
    }
    if (points.length < 3) return false;
    return pointInPolygon(x, y, points) || polygonEdges(points).some(
      ([first, second]) => distanceToSegment(x, y, first, second) <= margin,
    );
  };

  const blockedReason = (annotations, x, y) => {
    const annotation = (annotations || []).find((item) => blocksPoint(item, x, y));
    if (!annotation) return "";
    const label = types[annotation.type]?.label || annotation.type;
    return `${label} '${annotation.name || label}'이(가) 이동을 차단합니다.`;
  };

  return {
    blockedReason,
    blocksPoint,
    distanceToSegment,
    pointInPolygon,
    types,
  };
}));
