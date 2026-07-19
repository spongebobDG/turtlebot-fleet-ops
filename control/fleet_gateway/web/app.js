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
const navigationState = document.querySelector("#navigation-state");
const navigationMessage = document.querySelector("#navigation-message");
const distanceRemaining = document.querySelector("#distance-remaining");
const navigationTime = document.querySelector("#navigation-time");
const leaseAge = document.querySelector("#lease-age");
const recoveryCount = document.querySelector("#recovery-count");
const createTaskButton = document.querySelector("#create-task");
const refreshOperationsButton = document.querySelector("#refresh-operations");
const taskList = document.querySelector("#task-list");
const faultList = document.querySelector("#fault-list");
const eventList = document.querySelector("#event-list");
const mlopsState = document.querySelector("#mlops-state");
const mlopsModel = document.querySelector("#mlops-model");
const mlopsScore = document.querySelector("#mlops-score");
const mlopsReasons = document.querySelector("#mlops-reasons");
const mapMath = window.FleetMapMath;
const viewportMath = window.FleetMapViewport;

let reconnectTimer;
let robots = [];
let currentMap = null;
let currentMapRobot = "";
let mapMode = "goal";
let selectedPose = null;
let dragStart = null;
let panDrag = null;
let mapBitmap = null;
let mapViewport = null;
let tasks = [];
let faults = [];
let events = [];
let logMlops = null;

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
        <div class="metric"><span>위치 X / Y</span><strong>${number(robot.odom?.x, 2)} / ${number(robot.odom?.y, 2)}m</strong></div>
        <div class="metric"><span>방향 Yaw</span><strong>${number(robot.odom?.yaw, 2, "rad")}</strong></div>
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
  const robot = selectedRobot();
  const navigation = robot?.navigation || {};
  navigationState.textContent = navigation.state || "UNAVAILABLE";
  navigationMessage.textContent = navigation.message || "NavigationStatus를 기다리는 중입니다.";
  distanceRemaining.textContent = number(navigation.distance_remaining, 2, "m");
  navigationTime.textContent = number(navigation.navigation_time_sec, 1, "s");
  leaseAge.textContent = number(navigation.lease_age_sec, 2, "s");
  recoveryCount.textContent = navigation.number_of_recoveries ?? "—";

  const activeGoal = Boolean(navigation.active_command_id);
  const commonReady = Boolean(
    robot?.online && robot.level < 2 && currentMap && !activeGoal,
  );
  const goalReady = commonReady
    && navigation.fresh
    && navigation.nav2_ready
    && navigation.localization_ready
    && navigation.safety_ready
    && robot?.safety?.fresh
    && !robot?.safety?.estop_active
    && robot?.safety?.motion_armed;
  applyMapCommand.textContent = mapMode === "initial" ? "초기 위치 적용" : "목적지 전송";
  applyMapCommand.disabled = mapMode === "initial" ? !commonReady : !goalReady;
  cancelNavigation.disabled = !activeGoal;
  createTaskButton.disabled = mapMode !== "goal" || !commonReady;
  drawMap();
};

const loadMap = async () => {
  const robotId = robotSelect.value;
  currentMap = null;
  mapBitmap = null;
  mapViewport = null;
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
    if (body.data.length !== body.width * body.height) throw new Error("지도 크기와 데이터가 일치하지 않습니다.");
    currentMap = body;
    mapBitmap = buildMapBitmap(body);
    mapFrame.classList.add("loaded");
    drawMap();
    renderNavigation();
  } catch (error) {
    mapPlaceholder.textContent = error.message;
  }
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
  if (robot?.navigation?.current?.frame_id === "map") {
    drawArrow(context, robot.navigation.current, "#44b9ff");
  }
  if (robot?.navigation?.target?.frame_id === "map") {
    drawArrow(context, robot.navigation.target, "#ffd166");
  }
  if (selectedPose) drawArrow(context, selectedPose, "#58e0ae");
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

const drawArrow = (context, pose, color) => {
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
  context.restore();
};

const worldToScreen = (x, y) => {
  const mapPoint = mapMath.worldToCanvas(currentMap, x, y);
  return viewportMath.mapToScreen(mapViewport, mapPoint.x, mapPoint.y);
};

const screenToWorld = (x, y, clampToMap = false) => {
  const mapPoint = viewportMath.screenToMap(mapViewport, x, y, clampToMap);
  return mapPoint ? mapMath.canvasToWorld(currentMap, mapPoint.x, mapPoint.y) : null;
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
    showToast("지도 안의 자유 공간을 선택하세요.", true);
    return;
  }
  if (cell.value !== 0) {
    showToast(cell.value < 0 ? "알 수 없는 셀은 선택할 수 없습니다." : "장애물 셀은 선택할 수 없습니다.", true);
    return;
  }
  dragStart = cell.center;
  selectedPose = { ...dragStart, yaw: Number(poseYaw.value) || 0 };
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
  const end = screenToWorld(point.x, point.y, true);
  selectedPose = {
    ...dragStart,
    yaw: Math.atan2(end.y - dragStart.y, end.x - dragStart.x),
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
  if (!dragStart) return;
  if (!selectedPose) selectedPose = { ...dragStart, yaw: 0 };
  poseX.value = selectedPose.x.toFixed(3);
  poseY.value = selectedPose.y.toFixed(3);
  poseYaw.value = selectedPose.yaw.toFixed(3);
  dragStart = null;
  mapCanvas.releasePointerCapture(event.pointerId);
  drawMap();
});

mapCanvas.addEventListener("pointercancel", (event) => {
  dragStart = null;
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
    document.querySelectorAll("button[data-map-mode]").forEach(
      (candidate) => candidate.classList.toggle("active", candidate === button),
    );
    renderNavigation();
  });
});

applyMapCommand.addEventListener("click", async () => {
  const robot = selectedRobot();
  if (!robot) return;
  const pose = {
    x: Number(poseX.value),
    y: Number(poseY.value),
    yaw: Number(poseYaw.value),
  };
  if (!Object.values(pose).every(Number.isFinite)) {
    showToast("유효한 X, Y, Yaw를 입력하세요.", true);
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
  } catch (error) {
    showToast(error.message, true);
  } finally {
    renderNavigation();
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

const renderOperations = () => {
  document.querySelector("#task-count").textContent = tasks.length;
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
  mlopsReasons.textContent = reasons || status.message || "분석 결과가 없습니다.";
  mlopsReasons.title = mlopsReasons.textContent;
};

const loadLogMlops = async () => {
  try {
    const response = await fetch("/api/mlops/ros2-logs");
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "MLOps 상태 조회 실패");
    logMlops = body;
  } catch (error) {
    logMlops = {
      state: "ERROR",
      message: error.message,
      model_id: null,
      score: null,
    };
  }
  renderLogMlops();
};

const loadOperations = async () => {
  loadLogMlops();
  const robotId = robotSelect.value;
  if (!robotId) {
    tasks = [];
    faults = [];
    events = [];
    renderOperations();
    return;
  }
  try {
    const encoded = encodeURIComponent(robotId);
    const responses = await Promise.all([
      fetch(`/api/tasks?robot_id=${encoded}&limit=50`),
      fetch(`/api/robots/${encoded}/faults`),
      fetch(`/api/events?robot_id=${encoded}&limit=50`),
    ]);
    const bodies = await Promise.all(responses.map((response) => response.json()));
    const failedIndex = responses.findIndex((response) => !response.ok);
    if (failedIndex >= 0) throw new Error(bodies[failedIndex].detail || "운영 기록 조회 실패");
    tasks = bodies[0].tasks || [];
    faults = bodies[1].faults || [];
    events = bodies[2].events || [];
    renderOperations();
  } catch (error) {
    showToast(error.message, true);
  }
};

createTaskButton.addEventListener("click", async () => {
  const robot = selectedRobot();
  if (!robot) return;
  const pose = {
    x: Number(poseX.value),
    y: Number(poseY.value),
    yaw: Number(poseYaw.value),
  };
  if (!Object.values(pose).every(Number.isFinite)) {
    showToast("유효한 X, Y, Yaw를 입력하세요.", true);
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
