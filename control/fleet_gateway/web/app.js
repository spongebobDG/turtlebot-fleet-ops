const grid = document.querySelector("#robot-grid");
const connection = document.querySelector("#connection");
const connectionLabel = document.querySelector("#connection-label");
const updatedAt = document.querySelector("#updated-at");
const toast = document.querySelector("#toast");
const robotSelect = document.querySelector("#navigation-robot");
const mapFrame = document.querySelector("#map-frame");
const mapCanvas = document.querySelector("#map-canvas");
const mapPlaceholder = document.querySelector("#map-placeholder");
const mapReadout = document.querySelector("#map-readout");
const mapMeta = document.querySelector("#map-meta");
const mapLiveState = document.querySelector("#map-live-state");
const scanMeta = document.querySelector("#scan-meta");
const poseMeta = document.querySelector("#pose-meta");
const mapZoomOut = document.querySelector("#map-zoom-out");
const mapZoomIn = document.querySelector("#map-zoom-in");
const mapZoomLabel = document.querySelector("#map-zoom-label");
const mapFit = document.querySelector("#map-fit");
const refreshMapButton = document.querySelector("#refresh-map");
const applyMapCommand = document.querySelector("#apply-map-command");
const cancelNavigation = document.querySelector("#cancel-navigation");
const poseX = document.querySelector("#pose-x");
const poseY = document.querySelector("#pose-y");
const poseYaw = document.querySelector("#pose-yaw");
const poseHeading = document.querySelector("#pose-heading");
const alignmentTools = document.querySelector("#alignment-tools");
const alignInitialPose = document.querySelector("#align-initial-pose");
const alignmentMeta = document.querySelector("#alignment-meta");
const navigationState = document.querySelector("#navigation-state");
const navigationMessage = document.querySelector("#navigation-message");
const workflowHint = document.querySelector("#workflow-hint");
const distanceRemaining = document.querySelector("#distance-remaining");
const navigationTime = document.querySelector("#navigation-time");
const leaseAge = document.querySelector("#lease-age");
const recoveryCount = document.querySelector("#recovery-count");
const createTaskButton = document.querySelector("#create-task");
const refreshOperationsButton = document.querySelector("#refresh-operations");
const taskList = document.querySelector("#task-list");
const patrolList = document.querySelector("#patrol-list");
const patrolDraft = document.querySelector("#patrol-draft");
const patrolDraftList = document.querySelector("#patrol-draft-list");
const patrolLoops = document.querySelector("#patrol-loops");
const patrolDwell = document.querySelector("#patrol-dwell");
const createPatrolButton = document.querySelector("#create-patrol");
const clearWaypointsButton = document.querySelector("#clear-waypoints");
const profileState = document.querySelector("#profile-state");
const saveMapButton = document.querySelector("#save-map");
const manualState = document.querySelector("#manual-state");
const faultList = document.querySelector("#fault-list");
const eventList = document.querySelector("#event-list");
const mlopsState = document.querySelector("#mlops-state");
const mlopsModel = document.querySelector("#mlops-model");
const mlopsScore = document.querySelector("#mlops-score");
const mlopsReasons = document.querySelector("#mlops-reasons");
const mlopsModelExplanation = document.querySelector("#mlops-model-explanation");
const incidentCause = document.querySelector("#incident-cause");
const incidentAction = document.querySelector("#incident-action");
const incidentDetails = document.querySelector("#incident-details");
const mapMath = window.FleetMapMath;
const viewportMath = window.FleetMapViewport;
const robotDisplay = window.FleetRobotDisplay;
const manualKeys = window.FleetManualKeys;
const diagnosticsView = window.FleetDiagnosticsView;

let reconnectTimer;
let robots = [];
let currentMap = null;
let currentScan = null;
let currentMapRobot = "";
let mapMode = "goal";
let selectedPose = null;
let poseAlignment = null;
let dragStart = null;
let dragStartScreen = null;
let panDrag = null;
let mapBitmap = null;
let mapViewport = null;
let tasks = [];
let patrols = [];
let draftWaypoints = [];
let faults = [];
let events = [];
let logMlops = null;
let logIncidents = null;
let headingSpecified = false;
let manualSession = null;
let manualTimer = null;
let manualPointer = null;
let manualKeyboardOwner = null;
let manualOwner = null;
let manualPendingOwner = null;
let manualStartInFlight = false;
let liveMapRefreshInFlight = false;
let liveMapStatus = { robotId: "", updatedAt: null, error: false };

const escapeHtml = (value) => String(value ?? "").replace(
  /[&<>"']/g,
  (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[character],
);

const number = (value, digits = 1, suffix = "") => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }
  return `${Number(value).toFixed(digits)}${suffix}`;
};

const health = (robot) => {
  if (!robot.online) return { label: "OFFLINE", className: "offline" };
  if (robot.level === 2) return { label: "ERROR", className: "error" };
  if (robot.level === 1) return { label: "WARN", className: "warn" };
  return { label: "OK", className: "" };
};

const robotCard = (robot) => {
  const state = health(robot);
  const safeRobotId = escapeHtml(robot.robot_id);
  const safeHostname = escapeHtml(robot.hostname);
  const faults = robot.fault_codes?.length
    ? escapeHtml(robot.fault_codes.join(" · "))
    : "활성 고장 없음";
  const navigation = robot.navigation || {};
  const displayPose = robotDisplay.selectDisplayPose(robot);
  const activeGoal = Boolean(navigation.active_command_id);
  return `
    <article class="robot-card">
      <div class="robot-header">
        <div>
          <h3 class="robot-id">${safeRobotId}</h3>
          <p class="hostname">${safeHostname} · heartbeat ${number(robot.heartbeat_age_sec, 2, "s")}</p>
        </div>
        <span class="badge ${state.className}">${state.label}</span>
      </div>
      <div class="metrics">
        <div class="metric"><span>배터리</span><strong>${number(robot.battery?.percent, 1, "%")}</strong></div>
        <div class="metric"><span>전압</span><strong>${number(robot.battery?.voltage, 2, "V")}</strong></div>
        <div class="metric"><span>위치 X / Y (${escapeHtml(displayPose.frame_id)})</span><strong>${number(displayPose.x, 2)} / ${number(displayPose.y, 2)}m</strong></div>
        <div class="metric"><span>방향 Yaw (${escapeHtml(displayPose.frame_id)})</span><strong>${number(displayPose.yaw, 2, "rad")}</strong></div>
        <div class="metric"><span>Nav2</span><strong>${escapeHtml(navigation.state || "UNAVAILABLE")}</strong></div>
        <div class="metric"><span>Safety</span><strong>${escapeHtml(robot.safety?.mode || "UNKNOWN")}</strong></div>
        <div class="metric"><span>최근 장애물</span><strong>${number(robot.scan?.min_range, 2, "m")}</strong></div>
        <div class="metric"><span>CPU / 메모리</span><strong>${number(robot.system?.cpu_percent, 0)} / ${number(robot.system?.memory_percent, 0)}%</strong></div>
        <div class="metric"><span>Wi-Fi</span><strong>${number(robot.wifi?.signal_dbm, 0, "dBm")}</strong></div>
        <div class="metric"><span>Scan points</span><strong>${robot.scan?.valid_points ?? "—"}</strong></div>
      </div>
      <p class="faults ${robot.fault_codes?.length ? "" : "none"}">${faults}</p>
      <div class="actions">
        <button class="estop" data-robot="${safeRobotId}" data-engaged="true">비상 정지</button>
        <button class="release" data-robot="${safeRobotId}" data-engaged="false" ${robot.online && !activeGoal ? "" : "disabled"}>정지 해제</button>
      </div>
    </article>`;
};

const render = (nextRobots) => {
  robots = nextRobots;
  document.querySelector("#known-count").textContent = robots.length;
  document.querySelector("#online-count").textContent = robots.filter((robot) => robot.online).length;
  document.querySelector("#fault-count").textContent = robots.filter((robot) => !robot.online || robot.level > 0).length;
  grid.innerHTML = robots.length
    ? robots.map(robotCard).join("")
    : `<article class="empty-state"><h3>RobotStatus를 기다리는 중입니다.</h3><p>Gateway가 ROS 2 heartbeat를 받으면 여기에 표시됩니다.</p></article>`;
  updatedAt.textContent = `최근 갱신 ${new Date().toLocaleTimeString("ko-KR")}`;
  updateRobotOptions();
  renderNavigation();
};

const setConnection = (state, label) => {
  connection.dataset.state = state;
  connectionLabel.textContent = label;
};

const showToast = (message, isError = false) => {
  toast.textContent = message;
  toast.className = `toast visible${isError ? " error" : ""}`;
  window.setTimeout(() => { toast.className = "toast"; }, 3200);
};

const selectedRobot = () => robots.find(
  (robot) => robot.robot_id === robotSelect.value,
);

const updateRobotOptions = () => {
  const previous = robotSelect.value;
  robotSelect.innerHTML = robots.map(
    (robot) => `<option value="${escapeHtml(robot.robot_id)}">${escapeHtml(robot.robot_id)}</option>`,
  ).join("");
  if (robots.some((robot) => robot.robot_id === previous)) {
    robotSelect.value = previous;
  }
  if (!robotSelect.value && robots.length) robotSelect.value = robots[0].robot_id;
  if (robotSelect.value && currentMapRobot !== robotSelect.value) loadMap();
};

const renderNavigation = () => {
  document.body.dataset.mapMode = mapMode;
  const robot = selectedRobot();
  const navigation = robot?.navigation || {};
  navigationState.textContent = navigation.state || "UNAVAILABLE";
  navigationMessage.textContent = navigation.message || "NavigationStatus를 기다리는 중입니다.";
  distanceRemaining.textContent = number(navigation.distance_remaining, 2, "m");
  navigationTime.textContent = number(navigation.navigation_time_sec, 1, "s");
  leaseAge.textContent = number(navigation.lease_age_sec, 2, "s");
  recoveryCount.textContent = navigation.number_of_recoveries ?? "—";
  const profile = robot?.mapping || {};
  profileState.textContent = `PROFILE ${profile.profile || "—"}`;
  profileState.title = profile.message || "";
  const liveMapping = Boolean(
    robot?.online
    && profile.profile === "MAPPING"
    && !profile.transitioning,
  );
  mapFrame.classList.toggle("live-mapping", liveMapping);
  mapLiveState.classList.toggle("active", liveMapping);
  mapLiveState.classList.toggle(
    "error",
    liveMapping && liveMapStatus.robotId === robot?.robot_id && liveMapStatus.error,
  );
  if (!liveMapping) {
    mapLiveState.textContent = "SAVED MAP";
    if (liveMapStatus.robotId === robot?.robot_id) {
      liveMapStatus = { robotId: "", updatedAt: null, error: false };
    }
  } else if (liveMapStatus.robotId !== robot.robot_id || !liveMapStatus.updatedAt) {
    mapLiveState.textContent = "LIVE MAP 대기";
  } else if (liveMapStatus.error) {
    mapLiveState.textContent = "LIVE MAP 재연결 중";
  } else {
    mapLiveState.textContent = `LIVE ${liveMapStatus.updatedAt.toLocaleTimeString("ko-KR", { hour12: false })}`;
  }
  const displayPose = robotDisplay.selectDisplayPose(robot);
  poseMeta.textContent = displayPose.frame_id === "map"
    ? `TB1 현재 위치 · map x ${number(displayPose.x, 2)} · y ${number(displayPose.y, 2)} · yaw ${number(displayPose.yaw, 2)}`
    : profile.profile === "MAPPING"
      ? "TB1 현재 위치 · SLAM TF 대기 중"
      : "TB1 현재 위치 · 초기 위치 설정 대기";
  if (profile.profile === "MAPPING") {
    workflowHint.textContent = "매핑: 파란 TB1 화살표를 확인하며 WASD 이동 → 지도 저장 → 주행 모드";
  } else if (profile.profile === "NAVIGATION" && !navigation.localization_ready) {
    workflowHint.textContent = "1 초기 위치 → LiDAR로 현재 위치 찾기 → 초기 위치 적용";
  } else if (profile.profile === "NAVIGATION" && (
    robot?.safety?.estop_active || !robot?.safety?.motion_armed
  )) {
    workflowHint.textContent = "2 초기 위치 확인 완료 → 로봇 카드에서 정지 해제";
  } else if (profile.profile === "NAVIGATION") {
    workflowHint.textContent = "3 목적지 → 지도에서 위치부터 앞방향으로 드래그 → 목적지 전송";
  } else {
    workflowHint.textContent = "새 지도는 MAPPING, 저장된 지도 주행은 NAVIGATION 프로필을 선택하세요.";
  }

  const activeGoal = Boolean(navigation.active_command_id);
  const validCandidate = Boolean(
    selectedPose
    && currentMap
    && headingSpecified
    && mapMath.isFreePose(currentMap, selectedPose.x, selectedPose.y),
  );
  const commonReady = Boolean(
    robot?.online && robot.level < 2 && currentMap && !activeGoal,
  );
  const goalReady = commonReady
    && profile.fresh
    && profile.profile === "NAVIGATION"
    && navigation.fresh
    && navigation.nav2_ready
    && navigation.localization_ready
    && navigation.safety_ready
    && robot?.safety?.fresh
    && !robot?.safety?.estop_active
    && robot?.safety?.motion_armed;
  applyMapCommand.textContent = mapMode === "initial"
    ? "초기 위치 적용"
    : mapMode === "waypoint" ? "순찰점 추가" : "목적지 전송";
  alignmentTools.hidden = mapMode !== "initial";
  patrolDraft.hidden = mapMode !== "waypoint";
  alignInitialPose.disabled = mapMode !== "initial"
    || !currentMap
    || !currentScan?.fresh;
  alignInitialPose.title = !currentMap
    ? "지도를 먼저 불러오세요."
    : !currentScan?.fresh
      ? "최신 LiDAR를 기다리는 중입니다."
      : "현재 LiDAR를 지도 전체와 비교해 TB1 위치를 찾습니다.";
  applyMapCommand.disabled = !validCandidate
    || (mapMode === "initial"
      ? !commonReady || !poseAlignment?.acceptable
      : mapMode === "goal" ? !goalReady : false);
  cancelNavigation.disabled = !activeGoal;
  createTaskButton.disabled = mapMode !== "goal" || !commonReady || !validCandidate;
  createPatrolButton.disabled = draftWaypoints.length < 2 || !commonReady;
  patrolDraftList.textContent = draftWaypoints.length
    ? `순찰점 ${draftWaypoints.length}개 · ${draftWaypoints.map((point, index) => `${index + 1}:${number(point.x, 2)},${number(point.y, 2)} @${number(point.yaw * 180 / Math.PI, 0, "°")}`).join(" · ")}`
    : "순찰점 0개 · 지도에서 위치→앞방향으로 드래그";
  poseHeading.textContent = headingSpecified && selectedPose
    ? `앞방향 ${number(selectedPose.yaw, 3, " rad")} · ${number(selectedPose.yaw * 180 / Math.PI, 1, "°")}`
    : mapMode === "initial"
      ? "LiDAR 찾기가 위치와 앞방향을 자동으로 채웁니다."
      : "앞방향 미지정 · 원에서 화살표 끝까지 드래그";
  poseHeading.classList.toggle("ready", headingSpecified);
  const manualReady = Boolean(
    robot?.online
    && robot.level < 2
    && !activeGoal
    && robot?.safety?.fresh
    && !robot?.safety?.estop_active
    && robot?.safety?.motion_armed
    && profile.fresh
    && ["MAPPING", "NAVIGATION"].includes(profile.profile)
    && !profile.transitioning,
  );
  document.querySelectorAll("[data-manual-linear]").forEach((button) => {
    button.disabled = !manualReady;
  });
  manualState.textContent = manualSession
    ? "조종 중"
    : manualPendingOwner ? "연결 중" : manualReady ? "WASD 준비" : "잠김";
  saveMapButton.disabled = profile.profile !== "MAPPING" || profile.transitioning;
  drawMap();
};

const resetPoseSelection = () => {
  selectedPose = null;
  poseAlignment = null;
  dragStart = null;
  dragStartScreen = null;
  headingSpecified = false;
  poseX.value = "";
  poseY.value = "";
  poseYaw.value = "";
  alignmentMeta.textContent = mapMode === "initial"
    ? "지도 선택 없이 LiDAR로 현재 위치를 찾을 수 있습니다."
    : "대략 위치를 선택해 자동 정렬하세요.";
  alignmentMeta.classList.remove("accepted");
};

const syncPoseSelectionFromFields = () => {
  poseAlignment = null;
  alignmentMeta.textContent = "LiDAR 자동 정렬이 필요합니다.";
  alignmentMeta.classList.remove("accepted");
  const raw = [poseX.value, poseY.value, poseYaw.value];
  if (raw.some((value) => value.trim() === "")) {
    selectedPose = null;
    headingSpecified = false;
  } else {
    const pose = {
      x: Number(raw[0]),
      y: Number(raw[1]),
      yaw: Number(raw[2]),
    };
    selectedPose = Object.values(pose).every(Number.isFinite)
      && currentMap
      && mapMath.isFreePose(currentMap, pose.x, pose.y)
      ? pose
      : null;
    headingSpecified = Boolean(selectedPose);
  }
  renderNavigation();
};

const applyMapSnapshot = (snapshot, { preserveViewport = false } = {}) => {
  if (!Array.isArray(snapshot.data) || snapshot.data.length !== snapshot.width * snapshot.height) {
    throw new Error("지도 크기와 데이터가 일치하지 않습니다.");
  }
  const geometryChanged = !mapMath.hasSameGeometry(currentMap, snapshot);
  currentMap = snapshot;
  mapBitmap = buildMapBitmap(snapshot);
  if (!preserveViewport || geometryChanged) mapViewport = null;
  mapMeta.textContent = `${snapshot.width}×${snapshot.height} cells · ${number(snapshot.resolution * 100, 1, "cm/cell")}`;
  mapFrame.classList.add("loaded");
  renderNavigation();
};

const loadMap = async () => {
  const robotId = robotSelect.value;
  currentMap = null;
  currentScan = null;
  mapBitmap = null;
  mapViewport = null;
  resetPoseSelection();
  mapMeta.textContent = "지도 정보 없음";
  currentMapRobot = robotId;
  mapFrame.classList.remove("loaded");
  mapPlaceholder.textContent = robotId ? "지도를 불러오는 중입니다." : "로봇 지도를 기다리는 중입니다.";
  renderNavigation();
  loadOperations();
  if (!robotId) return;
  try {
    const response = await fetch(`/api/robots/${encodeURIComponent(robotId)}/map`);
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "지도를 불러오지 못했습니다.");
    if (robotSelect.value !== robotId) return;
    applyMapSnapshot(body);
    loadScan();
  } catch (error) {
    mapPlaceholder.textContent = error.message;
  }
};

const loadScan = async () => {
  const robotId = robotSelect.value;
  if (!robotId || currentMapRobot !== robotId) return;
  try {
    const response = await fetch(`/api/robots/${encodeURIComponent(robotId)}/scan`);
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "LiDAR scan unavailable");
    currentScan = body;
    const coverage = Number(body.coverage_ratio) * 100;
    scanMeta.textContent = `LiDAR ${body.valid_points} pts · ${coverage.toFixed(0)}% span · ${number(body.age_sec, 2, "s")}`;
  } catch (error) {
    currentScan = null;
    scanMeta.textContent = `LiDAR: ${error.message}`;
  }
  drawMap();
};

const buildMapBitmap = (map) => {
  const bitmap = document.createElement("canvas");
  bitmap.width = map.width;
  bitmap.height = map.height;
  const context = bitmap.getContext("2d");
  const image = context.createImageData(map.width, map.height);
  for (let y = 0; y < map.height; y += 1) {
    for (let x = 0; x < map.width; x += 1) {
      const value = map.data[y * map.width + x];
      const displayY = map.height - 1 - y;
      const offset = (displayY * map.width + x) * 4;
      const shade = value < 0
        ? 61
        : Math.round(242 - (Math.min(value, 100) / 100) * 228);
      image.data[offset] = shade;
      image.data[offset + 1] = shade;
      image.data[offset + 2] = value < 0 ? shade + 7 : shade;
      image.data[offset + 3] = 255;
    }
  }
  context.putImageData(image, 0, 0);
  return bitmap;
};

const ensureMapViewport = () => {
  const bounds = mapCanvas.getBoundingClientRect();
  const width = Math.max(1, bounds.width);
  const height = Math.max(1, bounds.height);
  const pixelRatio = Math.max(1, window.devicePixelRatio || 1);
  const pixelWidth = Math.round(width * pixelRatio);
  const pixelHeight = Math.round(height * pixelRatio);
  if (mapCanvas.width !== pixelWidth || mapCanvas.height !== pixelHeight) {
    mapCanvas.width = pixelWidth;
    mapCanvas.height = pixelHeight;
  }
  if (!mapViewport) {
    mapViewport = viewportMath.fit(currentMap.width, currentMap.height, width, height);
  } else if (mapViewport.viewWidth !== width || mapViewport.viewHeight !== height) {
    const center = viewportMath.screenToMap(
      mapViewport,
      mapViewport.viewWidth / 2,
      mapViewport.viewHeight / 2,
      true,
    );
    const previousZoom = mapViewport.zoom;
    mapViewport = viewportMath.fit(currentMap.width, currentMap.height, width, height);
    mapViewport.zoom = previousZoom;
    mapViewport.scale = mapViewport.fitScale * previousZoom;
    mapViewport.offsetX = width / 2 - center.x * mapViewport.scale;
    mapViewport.offsetY = height / 2 - center.y * mapViewport.scale;
    viewportMath.pan(mapViewport, 0, 0);
  }
  mapZoomLabel.textContent = `${Math.round(mapViewport.zoom * 100)}%`;
  return { width, height, pixelRatio };
};

const drawMap = () => {
  if (!currentMap || !mapBitmap) return;
  const { width, height, pixelRatio } = ensureMapViewport();
  const context = mapCanvas.getContext("2d");
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#060b0a";
  context.fillRect(0, 0, width, height);
  context.imageSmoothingEnabled = false;
  context.drawImage(
    mapBitmap,
    mapViewport.offsetX,
    mapViewport.offsetY,
    currentMap.width * mapViewport.scale,
    currentMap.height * mapViewport.scale,
  );
  drawCellGrid(context);
  const robot = selectedRobot();
  drawScanOverlay(context, robot, width, height);
  const displayPose = robotDisplay.selectDisplayPose(robot);
  if (displayPose.frame_id === "map") {
    drawArrow(context, displayPose, "#44b9ff", "TB1 현재 위치");
  }
  if (draftWaypoints.length) {
    context.save();
    context.strokeStyle = "rgba(88, 224, 174, 0.7)";
    context.setLineDash([5, 4]);
    context.beginPath();
    draftWaypoints.forEach((point, index) => {
      const screen = worldToScreen(point.x, point.y);
      if (index === 0) context.moveTo(screen.x, screen.y);
      else context.lineTo(screen.x, screen.y);
    });
    context.stroke();
    context.restore();
    draftWaypoints.forEach((point, index) => {
      drawArrow(context, point, "#58e0ae", `P${index + 1}`);
    });
  }
  if (
    robot?.navigation?.active_command_id
    && robot.navigation.target?.frame_id === "map"
  ) {
    drawArrow(context, robot.navigation.target, "#ffd166", "활성 목표");
  }
  if (selectedPose) {
    drawArrow(
      context,
      selectedPose,
      "#58e0ae",
      mapMode === "initial" ? "초기 위치 후보" : "목적지 후보",
    );
  }
};

const drawScanOverlay = (context, robot, width, height) => {
  if (!currentScan?.fresh || !Array.isArray(currentScan.points)) return;
  const currentPose = robotDisplay.selectDisplayPose(robot);
  const pose = mapMode === "initial" && selectedPose
    ? selectedPose
    : currentPose?.frame_id === "map" ? currentPose : null;
  if (!pose) {
    drawLocalScanInset(context, width, height);
    return;
  }
  const cosine = Math.cos(pose.yaw);
  const sine = Math.sin(pose.yaw);
  context.save();
  context.fillStyle = "rgba(255, 82, 119, 0.92)";
  for (const point of currentScan.points) {
    if (!Array.isArray(point) || point.length !== 2) continue;
    const localX = Number(point[0]);
    const localY = Number(point[1]);
    if (!Number.isFinite(localX) || !Number.isFinite(localY)) continue;
    const worldX = pose.x + cosine * localX - sine * localY;
    const worldY = pose.y + sine * localX + cosine * localY;
    const screen = worldToScreen(worldX, worldY);
    context.beginPath();
    context.arc(screen.x, screen.y, 1.8, 0, Math.PI * 2);
    context.fill();
  }
  context.restore();
};

const drawLocalScanInset = (context, width, height) => {
  const size = Math.max(120, Math.min(170, width * 0.3, height * 0.38));
  const margin = 12;
  const left = width - size - margin;
  const top = height - size - margin;
  const centerX = left + size / 2;
  const centerY = top + size / 2 + 5;
  const displayRange = 2.5;
  const scale = (size * 0.42) / displayRange;
  context.save();
  context.fillStyle = "rgba(3, 11, 9, 0.88)";
  context.strokeStyle = "rgba(88, 224, 174, 0.62)";
  context.lineWidth = 1;
  context.fillRect(left, top, size, size);
  context.strokeRect(left, top, size, size);
  context.strokeStyle = "rgba(145, 170, 163, 0.22)";
  for (const range of [1.0, 2.0]) {
    context.beginPath();
    context.arc(centerX, centerY, range * scale, 0, Math.PI * 2);
    context.stroke();
  }
  context.strokeStyle = "rgba(88, 224, 174, 0.7)";
  context.beginPath();
  context.moveTo(centerX, centerY + 8);
  context.lineTo(centerX, centerY - 14);
  context.stroke();
  context.fillStyle = "#58e0ae";
  context.beginPath();
  context.moveTo(centerX, centerY - 18);
  context.lineTo(centerX - 4, centerY - 10);
  context.lineTo(centerX + 4, centerY - 10);
  context.closePath();
  context.fill();
  context.fillStyle = "rgba(255, 82, 119, 0.95)";
  for (const point of currentScan.points) {
    if (!Array.isArray(point) || point.length !== 2) continue;
    const localX = Number(point[0]);
    const localY = Number(point[1]);
    const range = Math.hypot(localX, localY);
    if (
      !Number.isFinite(localX)
      || !Number.isFinite(localY)
      || range > displayRange
    ) continue;
    context.beginPath();
    context.arc(
      centerX - localY * scale,
      centerY - localX * scale,
      1.7,
      0,
      Math.PI * 2,
    );
    context.fill();
  }
  context.fillStyle = "#bed1cb";
  context.font = "10px ui-monospace, monospace";
  context.fillText("LIVE LiDAR · ROBOT FRAME", left + 7, top + 13);
  context.restore();
};

const drawCellGrid = (context) => {
  if (mapViewport.scale < 12) return;
  context.save();
  context.strokeStyle = "rgba(145, 170, 163, 0.16)";
  context.lineWidth = 0.5;
  context.beginPath();
  for (let x = 0; x <= currentMap.width; x += 1) {
    const point = viewportMath.mapToScreen(mapViewport, x, 0);
    context.moveTo(point.x, mapViewport.offsetY);
    context.lineTo(point.x, mapViewport.offsetY + currentMap.height * mapViewport.scale);
  }
  for (let y = 0; y <= currentMap.height; y += 1) {
    const point = viewportMath.mapToScreen(mapViewport, 0, y);
    context.moveTo(mapViewport.offsetX, point.y);
    context.lineTo(mapViewport.offsetX + currentMap.width * mapViewport.scale, point.y);
  }
  context.stroke();
  context.restore();
};

const drawArrow = (context, pose, color, label = "") => {
  const start = worldToScreen(pose.x, pose.y);
  const length = Math.max(currentMap.resolution * 5, 0.25);
  const end = worldToScreen(
    pose.x + Math.cos(pose.yaw) * length,
    pose.y + Math.sin(pose.yaw) * length,
  );
  context.save();
  context.strokeStyle = color;
  context.fillStyle = color;
  context.lineWidth = 2;
  context.beginPath();
  context.arc(start.x, start.y, 4.5, 0, Math.PI * 2);
  context.fill();
  context.beginPath();
  context.moveTo(start.x, start.y);
  context.lineTo(end.x, end.y);
  context.stroke();
  const screenYaw = Math.atan2(end.y - start.y, end.x - start.x);
  const headLength = 9;
  const headWidth = 5;
  context.beginPath();
  context.moveTo(end.x, end.y);
  context.lineTo(
    end.x - Math.cos(screenYaw) * headLength + Math.sin(screenYaw) * headWidth,
    end.y - Math.sin(screenYaw) * headLength - Math.cos(screenYaw) * headWidth,
  );
  context.lineTo(
    end.x - Math.cos(screenYaw) * headLength - Math.sin(screenYaw) * headWidth,
    end.y - Math.sin(screenYaw) * headLength + Math.cos(screenYaw) * headWidth,
  );
  context.closePath();
  context.fill();
  if (label) {
    context.font = "700 10px system-ui, sans-serif";
    context.textBaseline = "bottom";
    context.fillText(label, start.x + 8, start.y - 5);
  }
  context.restore();
};

const worldToScreen = (x, y) => {
  const mapPoint = mapMath.worldToCanvas(currentMap, x, y);
  return viewportMath.mapToScreen(mapViewport, mapPoint.x, mapPoint.y);
};

const screenCoordinates = (event) => {
  const bounds = mapCanvas.getBoundingClientRect();
  return {
    x: event.clientX - bounds.left,
    y: event.clientY - bounds.top,
  };
};

const cellAtScreenPoint = (point) => {
  const mapPoint = viewportMath.screenToMap(mapViewport, point.x, point.y, false);
  if (!mapPoint) return null;
  const cellX = Math.floor(mapPoint.x);
  const cellY = currentMap.height - 1 - Math.floor(mapPoint.y);
  if (cellX < 0 || cellY < 0 || cellX >= currentMap.width || cellY >= currentMap.height) return null;
  const value = currentMap.data[cellY * currentMap.width + cellX];
  const center = mapMath.canvasToWorld(
    currentMap,
    cellX + 0.5,
    currentMap.height - cellY - 0.5,
  );
  return { cellX, cellY, value, center, mapPoint };
};

const updateMapReadout = (point) => {
  const cell = cellAtScreenPoint(point);
  if (!cell) {
    mapReadout.textContent = "지도 밖";
    return;
  }
  const world = mapMath.canvasToWorld(currentMap, cell.mapPoint.x, cell.mapPoint.y);
  const state = cell.value < 0 ? "UNKNOWN" : cell.value === 0 ? "FREE" : `OCCUPIED ${cell.value}`;
  mapReadout.textContent = `map x ${world.x.toFixed(3)} · y ${world.y.toFixed(3)} m · cell ${cell.cellX},${cell.cellY} · ${state}`;
};

mapCanvas.addEventListener("pointerdown", (event) => {
  if (!currentMap) return;
  mapCanvas.setPointerCapture(event.pointerId);
  const point = screenCoordinates(event);
  if (event.shiftKey || event.button === 1) {
    panDrag = point;
    mapCanvas.classList.add("panning");
    return;
  }
  const cell = cellAtScreenPoint(point);
  if (!cell) {
    mapCanvas.releasePointerCapture(event.pointerId);
    showToast("지도 안의 자유 공간을 선택하세요.", true);
    return;
  }
  if (cell.value !== 0) {
    mapCanvas.releasePointerCapture(event.pointerId);
    showToast(cell.value < 0 ? "알 수 없는 셀은 선택할 수 없습니다." : "장애물 셀은 선택할 수 없습니다.", true);
    return;
  }
  dragStart = cell.center;
  dragStartScreen = point;
  headingSpecified = false;
  poseAlignment = null;
  alignmentMeta.textContent = "LiDAR 자동 정렬이 필요합니다.";
  alignmentMeta.classList.remove("accepted");
  selectedPose = { ...dragStart, yaw: 0 };
  poseX.value = selectedPose.x.toFixed(3);
  poseY.value = selectedPose.y.toFixed(3);
  drawMap();
});

mapCanvas.addEventListener("pointermove", (event) => {
  if (!currentMap) return;
  const point = screenCoordinates(event);
  updateMapReadout(point);
  if (panDrag && mapCanvas.hasPointerCapture(event.pointerId)) {
    viewportMath.pan(mapViewport, point.x - panDrag.x, point.y - panDrag.y);
    panDrag = point;
    drawMap();
    return;
  }
  if (!dragStart || !mapCanvas.hasPointerCapture(event.pointerId)) return;
  const startMapPoint = mapMath.worldToCanvas(
    currentMap,
    dragStart.x,
    dragStart.y,
  );
  const endMapPoint = viewportMath.screenToMap(
    mapViewport,
    point.x,
    point.y,
    true,
  );
  const dragYaw = mapMath.yawFromCanvasDrag(
    currentMap,
    startMapPoint.x,
    startMapPoint.y,
    endMapPoint.x,
    endMapPoint.y,
  );
  const dragPixels = dragStartScreen
    ? Math.hypot(point.x - dragStartScreen.x, point.y - dragStartScreen.y)
    : 0;
  if (dragPixels < 12 || dragYaw === null) {
    headingSpecified = false;
    poseYaw.value = "";
    drawMap();
    return;
  }
  headingSpecified = true;
  selectedPose = {
    ...dragStart,
    yaw: dragYaw,
  };
  poseX.value = selectedPose.x.toFixed(3);
  poseY.value = selectedPose.y.toFixed(3);
  poseYaw.value = selectedPose.yaw.toFixed(3);
  drawMap();
});

mapCanvas.addEventListener("pointerup", (event) => {
  if (panDrag) {
    panDrag = null;
    mapCanvas.classList.remove("panning");
    if (mapCanvas.hasPointerCapture(event.pointerId)) mapCanvas.releasePointerCapture(event.pointerId);
    return;
  }
  if (!dragStart) {
    if (mapCanvas.hasPointerCapture(event.pointerId)) mapCanvas.releasePointerCapture(event.pointerId);
    return;
  }
  if (!selectedPose) selectedPose = { ...dragStart, yaw: 0 };
  poseX.value = selectedPose.x.toFixed(3);
  poseY.value = selectedPose.y.toFixed(3);
  poseYaw.value = headingSpecified ? selectedPose.yaw.toFixed(3) : "";
  dragStart = null;
  dragStartScreen = null;
  mapCanvas.releasePointerCapture(event.pointerId);
  if (!headingSpecified) {
    showToast("위치에서 로봇 앞방향으로 12px 이상 드래그하세요.", true);
  }
  renderNavigation();
});

mapCanvas.addEventListener("pointercancel", (event) => {
  dragStart = null;
  dragStartScreen = null;
  headingSpecified = false;
  panDrag = null;
  mapCanvas.classList.remove("panning");
  if (mapCanvas.hasPointerCapture(event.pointerId)) mapCanvas.releasePointerCapture(event.pointerId);
});

mapCanvas.addEventListener("pointerleave", () => {
  if (!dragStart && !panDrag) mapReadout.textContent = "커서를 지도 위에 올리세요.";
});

mapCanvas.addEventListener("wheel", (event) => {
  if (!currentMap) return;
  event.preventDefault();
  const point = screenCoordinates(event);
  const factor = event.deltaY < 0 ? 1.25 : 0.8;
  viewportMath.zoomAt(mapViewport, mapViewport.zoom * factor, point.x, point.y);
  drawMap();
}, { passive: false });

const changeMapZoom = (factor) => {
  if (!mapViewport) return;
  viewportMath.zoomAt(
    mapViewport,
    mapViewport.zoom * factor,
    mapViewport.viewWidth / 2,
    mapViewport.viewHeight / 2,
  );
  drawMap();
};

mapZoomOut.addEventListener("click", () => changeMapZoom(0.8));
mapZoomIn.addEventListener("click", () => changeMapZoom(1.25));
mapFit.addEventListener("click", () => {
  if (!currentMap) return;
  const bounds = mapCanvas.getBoundingClientRect();
  mapViewport = viewportMath.fit(currentMap.width, currentMap.height, bounds.width, bounds.height);
  drawMap();
});

new ResizeObserver(() => drawMap()).observe(mapFrame);

document.querySelectorAll("button[data-map-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    mapMode = button.dataset.mapMode;
    resetPoseSelection();
    document.querySelectorAll("button[data-map-mode]").forEach(
      (candidate) => candidate.classList.toggle("active", candidate === button),
    );
    renderNavigation();
  });
});

[poseX, poseY, poseYaw].forEach((input) => {
  input.addEventListener("input", syncPoseSelectionFromFields);
});

alignInitialPose.addEventListener("click", async () => {
  const robot = selectedRobot();
  const selectedSeed = selectedPose
    && currentMap
    && mapMath.isFreePose(currentMap, selectedPose.x, selectedPose.y)
    ? { ...selectedPose, yaw: headingSpecified ? selectedPose.yaw : 0 }
    : null;
  const seed = selectedSeed || (currentMap ? mapMath.centerFreePose(currentMap) : null);
  if (!robot || !seed || !currentScan?.fresh) {
    showToast(
      !currentScan?.fresh
        ? "최신 LiDAR를 기다리는 중입니다."
        : "자동 정렬에 사용할 자유 공간이 지도에 없습니다.",
      true,
    );
    return;
  }
  alignInitialPose.disabled = true;
  alignmentMeta.textContent = "LiDAR와 지도 전체를 비교하는 중입니다.";
  alignmentMeta.classList.remove("accepted");
  try {
    const response = await fetch(
      `/api/robots/${encodeURIComponent(robot.robot_id)}/localization/align-pose`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(seed),
      },
    );
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "LiDAR 자동 정렬 실패");
    selectedPose = { ...body.pose };
    headingSpecified = true;
    poseAlignment = body;
    poseX.value = selectedPose.x.toFixed(3);
    poseY.value = selectedPose.y.toFixed(3);
    poseYaw.value = selectedPose.yaw.toFixed(3);
    alignmentMeta.textContent = `정렬 일치 ${(body.matched_ratio * 100).toFixed(0)}% · 지도 내부 ${(body.inside_ratio * 100).toFixed(0)}%`;
    alignmentMeta.classList.add("accepted");
    showToast("LiDAR-지도 보정 후보를 확보했습니다. 붉은 점을 확인한 뒤 적용하세요.");
  } catch (error) {
    poseAlignment = null;
    alignmentMeta.textContent = error.message;
    showToast(error.message, true);
  } finally {
    renderNavigation();
  }
});

applyMapCommand.addEventListener("click", async () => {
  const robot = selectedRobot();
  if (!robot) return;
  const pose = selectedPose ? { ...selectedPose } : null;
  if (!pose || !headingSpecified || !currentMap || !mapMath.isFreePose(currentMap, pose.x, pose.y)) {
    showToast("지도에서 자유 공간의 위치와 방향을 새로 선택하세요.", true);
    return;
  }
  if (mapMode === "waypoint") {
    if (draftWaypoints.length >= 20) {
      showToast("순찰점은 최대 20개입니다.", true);
      return;
    }
    draftWaypoints.push(pose);
    showToast(`순찰점 ${draftWaypoints.length}을 추가했습니다.`);
    resetPoseSelection();
    renderNavigation();
    return;
  }
  const isInitial = mapMode === "initial";
  const warningConfirmed = !isInitial && robot.level === 1
    ? window.confirm(`${robot.robot_id} 경고(${(robot.fault_codes || []).join(", ")})가 있습니다. 그래도 목표를 전송할까요?`)
    : false;
  if (!isInitial && robot.level === 1 && !warningConfirmed) return;
  const path = isInitial
    ? `/api/robots/${encodeURIComponent(robot.robot_id)}/localization/initial-pose`
    : `/api/robots/${encodeURIComponent(robot.robot_id)}/navigation/goals`;
  const method = isInitial ? "PUT" : "POST";
  applyMapCommand.disabled = true;
  try {
    const response = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...pose, confirm_warnings: warningConfirmed }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "지도 명령 실패");
    showToast(body.message || "지도 명령을 전송했습니다.");
    resetPoseSelection();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    renderNavigation();
  }
});

clearWaypointsButton.addEventListener("click", () => {
  draftWaypoints = [];
  resetPoseSelection();
  renderNavigation();
});

createPatrolButton.addEventListener("click", async () => {
  const robot = selectedRobot();
  if (!robot || draftWaypoints.length < 2) return;
  const warningConfirmed = robot.level === 1
    ? window.confirm(`${robot.robot_id} 경고를 확인하고 순찰에 저장할까요?`)
    : false;
  if (robot.level === 1 && !warningConfirmed) return;
  try {
    const response = await fetch(`/api/robots/${encodeURIComponent(robot.robot_id)}/patrols`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        waypoints: draftWaypoints,
        loops: Number(patrolLoops.value),
        dwell_sec: Number(patrolDwell.value),
        confirm_warnings: warningConfirmed,
      }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "순찰 저장 실패");
    draftWaypoints = [];
    showToast(`순찰 ${body.patrol_id.slice(0, 8)}을 저장했습니다.`);
    await loadOperations();
    renderNavigation();
  } catch (error) {
    showToast(error.message, true);
  }
});

cancelNavigation.addEventListener("click", async () => {
  const robot = selectedRobot();
  const commandId = robot?.navigation?.active_command_id;
  if (!robot || !commandId) return;
  if (!window.confirm(`${robot.robot_id}의 현재 목적지를 취소할까요?`)) return;
  cancelNavigation.disabled = true;
  try {
    const response = await fetch(
      `/api/robots/${encodeURIComponent(robot.robot_id)}/navigation/goals/${encodeURIComponent(commandId)}`,
      { method: "DELETE" },
    );
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "목표 취소 실패");
    showToast(body.message || "목표 취소를 요청했습니다.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    renderNavigation();
  }
});

let manualSending = false;

const setManualButtonActive = (key, active) => {
  if (!key) return;
  const button = document.querySelector(`[data-manual-key="${key}"]`);
  button?.classList.toggle("manual-active", active);
};

const deleteManualSession = async (session) => {
  if (!session) return;
  await fetch(
    `/api/robots/${encodeURIComponent(session.robotId)}/manual/sessions/${encodeURIComponent(session.sessionId)}`,
    { method: "DELETE", keepalive: true },
  );
};

const sendManualVelocity = async (linearX, angularZ) => {
  const session = manualSession;
  if (!session) return false;
  if (manualSending) return true;
  manualSending = true;
  try {
    const response = await fetch(
      `/api/robots/${encodeURIComponent(session.robotId)}/manual/sessions/${encodeURIComponent(session.sessionId)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ linear_x: linearX, angular_z: angularZ }),
      },
    );
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "수동 명령 거부");
    return true;
  } catch (error) {
    await stopManualDrive();
    showToast(error.message, true);
    return false;
  } finally {
    manualSending = false;
  }
};

const stopManualDrive = async (owner = null) => {
  const ownerMatches = !owner
    || manualOwner === owner
    || manualPendingOwner === owner;
  if (!ownerMatches) return;
  window.clearInterval(manualTimer);
  manualTimer = null;
  if (!owner || manualPointer === owner) manualPointer = null;
  if (!owner || manualKeyboardOwner === owner) manualKeyboardOwner = null;
  if (!owner || manualPendingOwner === owner) manualPendingOwner = null;
  if (!owner || manualOwner === owner) manualOwner = null;
  const session = manualSession && (!owner || manualSession.owner === owner)
    ? manualSession
    : null;
  if (session) manualSession = null;
  if (owner) {
    setManualButtonActive(owner.key, false);
  } else {
    document.querySelectorAll("[data-manual-key]").forEach((button) => {
      button.classList.remove("manual-active");
    });
  }
  manualState.textContent = "정지";
  if (!session) return;
  try {
    await deleteManualSession(session);
  } finally {
    renderNavigation();
  }
};

const refreshLiveMap = async () => {
  const robot = selectedRobot();
  const profile = robot?.mapping || {};
  const robotId = robotSelect.value;
  const liveMapping = Boolean(
    robotId
    && robot?.online
    && profile.profile === "MAPPING"
    && !profile.transitioning,
  );
  if (!liveMapping || liveMapRefreshInFlight) return;

  liveMapRefreshInFlight = true;
  try {
    const response = await fetch(
      `/api/robots/${encodeURIComponent(robotId)}/map`,
      { cache: "no-store" },
    );
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "실시간 지도를 불러오지 못했습니다.");
    const latestRobot = selectedRobot();
    if (
      robotSelect.value !== robotId
      || latestRobot?.mapping?.profile !== "MAPPING"
      || latestRobot?.mapping?.transitioning
    ) return;
    liveMapStatus = { robotId, updatedAt: new Date(), error: false };
    applyMapSnapshot(body, { preserveViewport: true });
  } catch (error) {
    if (robotSelect.value === robotId) {
      liveMapStatus = { robotId, updatedAt: liveMapStatus.updatedAt, error: true };
      if (!currentMap) mapPlaceholder.textContent = error.message;
    }
  } finally {
    liveMapRefreshInFlight = false;
    renderNavigation();
  }
};

const startManualVector = async (command, owner) => {
  if (!command || manualSession || manualStartInFlight) return false;
  const robot = selectedRobot();
  if (!robot) return false;
  const confirmed = robot.level === 1
    ? window.confirm(`${robot.robot_id} 경고를 확인하고 수동 조종할까요?`)
    : false;
  if (robot.level === 1 && !confirmed) {
    return false;
  }
  manualStartInFlight = true;
  manualPendingOwner = owner;
  try {
    const response = await fetch(`/api/robots/${encodeURIComponent(robot.robot_id)}/manual/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm_warnings: confirmed }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "수동 세션 시작 실패");
    const session = {
      robotId: robot.robot_id,
      sessionId: body.session_id,
      owner,
    };
    if (manualPendingOwner !== owner) {
      await deleteManualSession(session);
      return false;
    }
    manualPendingOwner = null;
    manualOwner = owner;
    manualSession = session;
    manualState.textContent = command.label;
    const accepted = await sendManualVelocity(command.linearX, command.angularZ);
    if (!accepted || manualSession !== session) return false;
    manualTimer = window.setInterval(
      () => sendManualVelocity(command.linearX, command.angularZ),
      100,
    );
    return true;
  } catch (error) {
    if (manualPendingOwner === owner) manualPendingOwner = null;
    if (manualOwner === owner) await stopManualDrive(owner);
    showToast(error.message, true);
    return false;
  } finally {
    manualStartInFlight = false;
  }
};

document.querySelectorAll("[data-manual-linear]").forEach((button) => {
  button.addEventListener("pointerdown", async (event) => {
    if (button.disabled || manualSession || manualStartInFlight) return;
    event.preventDefault();
    const owner = {
      source: "pointer",
      pointerId: event.pointerId,
      key: button.dataset.manualKey,
    };
    manualPointer = owner;
    button.setPointerCapture(event.pointerId);
    setManualButtonActive(owner.key, true);
    const command = {
      key: owner.key,
      linearX: Number(button.dataset.manualLinear),
      angularZ: Number(button.dataset.manualAngular),
      label: `${String(owner.key || "").toUpperCase()} · 버튼 조종`,
    };
    const started = await startManualVector(command, owner);
    if (!started && manualPointer === owner) {
      manualPointer = null;
      setManualButtonActive(owner.key, false);
    }
  });
  ["pointerup", "pointercancel", "lostpointercapture"].forEach((name) => {
    button.addEventListener(name, (event) => {
      if (!manualPointer || manualPointer.pointerId !== event.pointerId) return;
      const owner = manualPointer;
      manualPointer = null;
      setManualButtonActive(owner.key, false);
      void stopManualDrive(owner);
    });
  });
});

document.addEventListener("keydown", async (event) => {
  if (event.ctrlKey || event.altKey || event.metaKey || manualKeys.isEditableTarget(event.target)) return;
  const command = manualKeys.commandForKey(event.key);
  if (!command) {
    if (["Escape", " "].includes(event.key) && (manualSession || manualPendingOwner)) {
      event.preventDefault();
      await stopManualDrive();
    }
    return;
  }
  const button = document.querySelector(`[data-manual-key="${command.key}"]`);
  if (event.repeat || button?.disabled || manualKeyboardOwner || manualSession || manualStartInFlight) return;
  event.preventDefault();
  const owner = { source: "keyboard", key: command.key };
  manualKeyboardOwner = owner;
  setManualButtonActive(owner.key, true);
  const started = await startManualVector(command, owner);
  if (!started && manualKeyboardOwner === owner) {
    manualKeyboardOwner = null;
    setManualButtonActive(owner.key, false);
  }
});

document.addEventListener("keyup", (event) => {
  const command = manualKeys.commandForKey(event.key);
  if (!command || manualKeyboardOwner?.key !== command.key) return;
  event.preventDefault();
  const owner = manualKeyboardOwner;
  manualKeyboardOwner = null;
  setManualButtonActive(owner.key, false);
  void stopManualDrive(owner);
});

document.querySelector("[data-manual-stop]").addEventListener("click", () => stopManualDrive());
window.addEventListener("blur", () => stopManualDrive());
window.addEventListener("pagehide", () => stopManualDrive());

document.querySelectorAll("[data-profile]").forEach((button) => {
  button.addEventListener("click", async () => {
    const robot = selectedRobot();
    if (!robot) return;
    const profile = button.dataset.profile;
    if (!window.confirm(`${profile} 프로필로 전환할까요? e-stop이 체결되고 이전 동작은 재개되지 않습니다.`)) return;
    button.disabled = true;
    try {
      const response = await fetch(
        `/api/robots/${encodeURIComponent(robot.robot_id)}/profiles/${profile}`,
        { method: "POST" },
      );
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "프로필 전환 실패");
      showToast(body.message || `${profile} 프로필 전환을 요청했습니다.`);
      window.setTimeout(loadMap, 2500);
    } catch (error) {
      showToast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
});

saveMapButton.addEventListener("click", async () => {
  const robot = selectedRobot();
  if (!robot) return;
  if (!window.confirm("현재 지도와 pose graph를 기존 TB1 지도에 덮어쓸까요? e-stop이 체결됩니다.")) return;
  saveMapButton.disabled = true;
  try {
    const response = await fetch(`/api/robots/${encodeURIComponent(robot.robot_id)}/mapping/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ overwrite: true }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "지도 저장 실패");
    showToast(body.message || "지도 저장 완료");
    await loadMap();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    renderNavigation();
  }
});

const recordTime = (value) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("ko-KR");
};

const taskActions = (task) => {
  if (task.state === "CREATED") {
    return `
      <button data-task-action="run" data-task-id="${escapeHtml(task.task_id)}">실행</button>
      <button class="secondary" data-task-action="cancel" data-task-id="${escapeHtml(task.task_id)}">취소</button>`;
  }
  if (task.state === "STARTING" || task.state === "ACTIVE") {
    return `<button class="secondary" data-task-action="cancel" data-task-id="${escapeHtml(task.task_id)}">취소</button>`;
  }
  if (task.state === "FAILED" || task.state === "CANCELED") {
    return `<button class="secondary" data-task-action="retry" data-task-id="${escapeHtml(task.task_id)}">재시도 작업 생성</button>`;
  }
  return "";
};

const patrolActions = (patrol) => {
  if (patrol.state === "CREATED") {
    return `<button data-patrol-action="run" data-patrol-id="${escapeHtml(patrol.patrol_id)}">순찰 시작</button>
      <button class="secondary" data-patrol-action="cancel" data-patrol-id="${escapeHtml(patrol.patrol_id)}">취소</button>`;
  }
  if (patrol.state === "STARTING" || patrol.state === "ACTIVE") {
    return `<button class="secondary" data-patrol-action="cancel" data-patrol-id="${escapeHtml(patrol.patrol_id)}">순찰 취소</button>`;
  }
  return "";
};

const renderOperations = () => {
  document.querySelector("#task-count").textContent = `${tasks.length} / P${patrols.length}`;
  document.querySelector("#active-fault-count").textContent = faults.length;
  document.querySelector("#event-count").textContent = events.length;
  taskList.innerHTML = tasks.length ? tasks.map((task) => `
    <div class="record-item task-item">
      <div>
        <span class="record-badge ${escapeHtml(task.state.toLowerCase())}">${escapeHtml(task.state)}</span>
        <strong>시도 ${task.attempt} · ${number(task.target.x, 2)}, ${number(task.target.y, 2)}</strong>
        <p>${escapeHtml(task.message || "상태 메시지 없음")} · ${recordTime(task.updated_at)}</p>
      </div>
      <div class="record-actions">${taskActions(task)}</div>
    </div>`).join("") : '<p class="record-empty">저장된 작업이 없습니다.</p>';
  patrolList.innerHTML = patrols.length ? patrols.map((patrol) => `
    <div class="record-item task-item">
      <div>
        <span class="record-badge ${escapeHtml(patrol.state.toLowerCase())}">${escapeHtml(patrol.state)}</span>
        <strong>순찰 ${patrol.waypoints.length}점 · ${patrol.current_loop + 1}/${patrol.loops}회 · P${patrol.current_waypoint + 1}</strong>
        <p>${escapeHtml(patrol.message || "상태 메시지 없음")} · ${recordTime(patrol.updated_at)}</p>
      </div>
      <div class="record-actions">${patrolActions(patrol)}</div>
    </div>`).join("") : '<p class="record-empty">저장된 순찰이 없습니다.</p>';
  faultList.innerHTML = faults.length ? faults.map((fault) => `
    <div class="record-item">
      <div>
        <span class="record-badge ${escapeHtml(fault.severity.toLowerCase())}">${escapeHtml(fault.severity)}</span>
        <strong>${escapeHtml(fault.fault_code)}</strong>
        <p>최근 감지 ${recordTime(fault.last_seen)}</p>
      </div>
    </div>`).join("") : '<p class="record-empty">활성 고장이 없습니다.</p>';
  eventList.innerHTML = events.length ? events.map((item) => `
    <div class="record-item">
      <div>
        <span class="record-badge ${escapeHtml(item.severity.toLowerCase())}">${escapeHtml(item.event_type)}</span>
        <strong>${escapeHtml(item.message)}</strong>
        <p>${recordTime(item.occurred_at)} · ${escapeHtml(item.category)}</p>
      </div>
    </div>`).join("") : '<p class="record-empty">기록된 이벤트가 없습니다.</p>';
};

const renderLogMlops = () => {
  const status = logMlops || { state: "UNAVAILABLE" };
  const state = String(status.state || "UNAVAILABLE");
  mlopsState.textContent = state;
  mlopsState.className = `mlops-state ${state.toLowerCase().replaceAll("_", "-")}`;
  mlopsModel.textContent = status.model_id || "승격 모델 없음";
  mlopsModel.title = status.model_id || "";
  mlopsScore.textContent = status.score === null || status.score === undefined
    ? "—"
    : `${number(status.score, 2)} / ${number(status.threshold, 2)}`;
  const reasons = (status.top_features || [])
    .filter((item) => Number(item.deviation) >= 1)
    .map((item) => `${item.feature} ${number(item.deviation, 1)}σ`)
    .join(" · ");
  const operationalSignals = (status.operational_signals || [])
    .slice(0, 3)
    .map((item) => `${item.label} ${item.count}회`)
    .join(" · ");
  mlopsReasons.textContent = operationalSignals
    || reasons
    || status.message
    || "분석 결과가 없습니다.";
  mlopsReasons.title = mlopsReasons.textContent;
  const diagnoses = logIncidents?.diagnoses || [];
  const diagnosis = diagnoses.find((item) => item.status === "ACTION_REQUIRED")
    || diagnoses[0];
  const analysisMode = logIncidents?.analysis_mode || "UNKNOWN";
  const modelPresentation = diagnosticsView.modelPresentation(status, analysisMode);
  mlopsModel.textContent = modelPresentation.label;
  mlopsModel.title = modelPresentation.explanation;
  mlopsModelExplanation.textContent = modelPresentation.explanation;
  incidentCause.textContent = diagnosticsView.incidentSummary(logIncidents);
  incidentAction.textContent = diagnosis?.confirmed_symptom || logIncidents?.message || "";
  incidentCause.title = diagnosis?.evidence?.map((item) => `${item.logger}: ${item.message}`).join("\n") || "";
  const openKeys = Array.from(
    incidentDetails.querySelectorAll("details[open][data-cause]"),
    (element) => element.dataset.cause,
  );
  const diagnosisRows = diagnosticsView.diagnosisRows(
    diagnoses,
    {
      hasRendered: incidentDetails.dataset.rendered === "true",
      openKeys,
    },
  );
  incidentDetails.innerHTML = diagnosisRows.length ? diagnosisRows.map(({ item, key, open }) => {
    const status = diagnosticsView.statusPresentation(item.status);
    const list = (label, values) => values?.length ? `
      <section><strong>${label}</strong><ol>${values.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ol></section>` : "";
    const causeLabels = new Map(diagnoses.map((entry) => [entry.cause, entry.label]));
    const correlated = (item.correlated_causes || [])
      .map((cause) => causeLabels.get(cause) || cause);
    const evidence = (item.evidence || []).map((entry) => `
      <li><time>${recordTime(entry.timestamp)}</time> <b>${escapeHtml(entry.severity)}</b> ${escapeHtml(entry.logger)}: ${escapeHtml(entry.message)}</li>`).join("");
    return `<details class="incident-item ${escapeHtml(status.tone)}" data-cause="${escapeHtml(key)}" ${open ? "open" : ""}>
      <summary><span>${escapeHtml(status.label)}</span>${escapeHtml(item.label)} <small>${escapeHtml(diagnosticsView.diagnosisMeta(item))}</small></summary>
      <p><strong>판정</strong> ${escapeHtml(item.root_cause_status || "HYPOTHESIS")}</p>
      <p><strong>확정 증상</strong> ${escapeHtml(item.confirmed_symptom || item.recommended_action || "-")}</p>
      ${list("같은 시각에 함께 감지", correlated)}
      ${list("가능한 원인", item.hypotheses)}
      ${list("지금 확인", item.checks)}
      ${list("해결·검증", item.fixes)}
      ${list("현재 로그의 한계", item.missing_evidence)}
      ${evidence ? `<section><strong>근거 로그</strong><ul class="incident-evidence">${evidence}</ul></section>` : ""}
    </details>`;
  }).join("") : '<p class="record-empty">해당 시간 범위에 진단 가능한 로그가 없습니다.</p>';
  incidentDetails.dataset.rendered = "true";
};

const loadLogMlops = async () => {
  const fetchJson = async (url, fallbackMessage) => {
    const response = await fetch(url);
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || fallbackMessage);
    return body;
  };
  const [statusResult, incidentResult] = await Promise.allSettled([
    fetchJson("/api/mlops/ros2-logs", "MLOps 상태 조회 실패"),
    fetchJson("/api/mlops/ros2-logs/incidents", "원인 분석 조회 실패"),
  ]);
  if (statusResult.status === "fulfilled") {
    logMlops = statusResult.value;
  } else {
    const error = statusResult.reason;
    logMlops = {
      state: "ERROR",
      message: error.message,
      model_id: null,
      score: null,
    };
  }
  if (incidentResult.status === "fulfilled") {
    logIncidents = incidentResult.value;
  } else {
    const error = incidentResult.reason;
    logIncidents = { diagnoses: [], message: error.message };
  }
  renderLogMlops();
};

const loadOperations = async () => {
  loadLogMlops();
  const robotId = robotSelect.value;
  if (!robotId) {
    tasks = [];
    patrols = [];
    faults = [];
    events = [];
    renderOperations();
    return;
  }
  try {
    const encoded = encodeURIComponent(robotId);
    const responses = await Promise.all([
      fetch(`/api/tasks?robot_id=${encoded}&limit=50`),
      fetch(`/api/patrols?robot_id=${encoded}&limit=50`),
      fetch(`/api/robots/${encoded}/faults`),
      fetch(`/api/events?robot_id=${encoded}&limit=50`),
    ]);
    const bodies = await Promise.all(responses.map((response) => response.json()));
    const failedIndex = responses.findIndex((response) => !response.ok);
    if (failedIndex >= 0) throw new Error(bodies[failedIndex].detail || "운영 기록 조회 실패");
    tasks = bodies[0].tasks || [];
    patrols = bodies[1].patrols || [];
    faults = bodies[2].faults || [];
    events = bodies[3].events || [];
    renderOperations();
  } catch (error) {
    showToast(error.message, true);
  }
};

createTaskButton.addEventListener("click", async () => {
  const robot = selectedRobot();
  if (!robot) return;
  const pose = selectedPose ? { ...selectedPose } : null;
  if (!pose || !currentMap || !mapMath.isFreePose(currentMap, pose.x, pose.y)) {
    showToast("지도에서 자유 공간의 위치와 방향을 새로 선택하세요.", true);
    return;
  }
  const warningConfirmed = robot.level === 1
    ? window.confirm(`${robot.robot_id} 경고를 확인하고 작업에 저장할까요?`)
    : false;
  if (robot.level === 1 && !warningConfirmed) return;
  try {
    const response = await fetch(`/api/robots/${encodeURIComponent(robot.robot_id)}/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...pose, confirm_warnings: warningConfirmed }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "작업 생성 실패");
    showToast(`작업 ${body.task_id.slice(0, 8)}을 저장했습니다.`);
    await loadOperations();
  } catch (error) {
    showToast(error.message, true);
  }
});

taskList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-task-action]");
  if (!button) return;
  const action = button.dataset.taskAction;
  const taskId = button.dataset.taskId;
  const path = action === "retry"
    ? `/api/tasks/${encodeURIComponent(taskId)}/retry`
    : `/api/tasks/${encodeURIComponent(taskId)}${action === "run" ? "/run" : ""}`;
  const method = action === "cancel" ? "DELETE" : "POST";
  button.disabled = true;
  try {
    const response = await fetch(path, { method });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || `작업 ${action} 실패`);
    showToast(body.message || `작업 ${action} 요청을 처리했습니다.`);
    await loadOperations();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

patrolList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-patrol-action]");
  if (!button) return;
  const action = button.dataset.patrolAction;
  const patrolId = button.dataset.patrolId;
  const path = `/api/patrols/${encodeURIComponent(patrolId)}${action === "run" ? "/run" : ""}`;
  button.disabled = true;
  try {
    const response = await fetch(path, { method: action === "cancel" ? "DELETE" : "POST" });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || `순찰 ${action} 실패`);
    showToast(body.message || `순찰 ${action} 요청을 처리했습니다.`);
    await loadOperations();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

refreshMapButton.addEventListener("click", loadMap);
refreshOperationsButton.addEventListener("click", loadOperations);
robotSelect.addEventListener("change", () => {
  selectedPose = null;
  loadMap();
});

grid.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-robot]");
  if (!button) return;
  const robotId = button.dataset.robot;
  const engaged = button.dataset.engaged === "true";
  const prompt = engaged
    ? `${robotId}에 비상 정지를 적용할까요? 활성 목적지도 취소됩니다.`
    : `${robotId}의 비상 정지를 해제할까요? 이전 목적지는 재개되지 않습니다.`;
  if (!window.confirm(prompt)) return;

  button.disabled = true;
  try {
    const response = await fetch(`/api/robots/${encodeURIComponent(robotId)}/estop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ engaged }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "요청 실패");
    showToast(body.message || "안전 명령을 전송했습니다.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

const connect = () => {
  window.clearTimeout(reconnectTimer);
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/robots`);
  setConnection("connecting", "연결 중");

  socket.addEventListener("open", () => setConnection("connected", "실시간 연결"));
  socket.addEventListener("message", (event) => render(JSON.parse(event.data).robots || []));
  socket.addEventListener("close", () => {
    setConnection("offline", "재연결 중");
    reconnectTimer = window.setTimeout(connect, 1500);
  });
  socket.addEventListener("error", () => socket.close());
};

connect();
window.setInterval(loadOperations, 3000);
window.setInterval(loadScan, 400);
window.setInterval(refreshLiveMap, 1000);
