(function attachRobotDisplay(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.FleetRobotDisplay = api;
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
  "use strict";

  const finitePose = (pose) => {
    if (!pose) return false;
    const values = [pose.x, pose.y, pose.yaw];
    return values.every((value) => value !== null
      && value !== undefined
      && Number.isFinite(Number(value)));
  };

  const selectDisplayPose = (robot) => {
    const mapPose = robot?.navigation?.current;
    if (mapPose?.frame_id === "map" && finitePose(mapPose)) {
      return {
        frame_id: "map",
        x: Number(mapPose.x),
        y: Number(mapPose.y),
        yaw: Number(mapPose.yaw),
      };
    }
    const odomPose = robot?.odom;
    if (finitePose(odomPose)) {
      return {
        frame_id: "odom",
        x: Number(odomPose.x),
        y: Number(odomPose.y),
        yaw: Number(odomPose.yaw),
      };
    }
    return {
      frame_id: "—",
      x: null,
      y: null,
      yaw: null,
    };
  };

  return { selectDisplayPose };
}));
