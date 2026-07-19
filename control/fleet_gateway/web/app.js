const grid = document.querySelector("#robot-grid");
const connection = document.querySelector("#connection");
const connectionLabel = document.querySelector("#connection-label");
const updatedAt = document.querySelector("#updated-at");
const toast = document.querySelector("#toast");
const robotSelect = document.querySelector("#navigation-robot");
const mapFrame = document.querySelector("#map-frame");
const mapCanvas = document.querySelector("#map-canvas");
const mapPlaceholder = document.querySelector("#map-placeholder");
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
const mapMath = window.FleetMapMath;

let reconnectTimer;
let robots = [];
let currentMap = null;
let currentMapRobot = "";
let mapMode = "goal";
let selectedPose = null;
let dragStart = null;
let tasks = [];
let faults = [];
let events = [];

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
    mapCanvas.width = body.width;
    mapCanvas.height = body.height;
    mapFrame.classList.add("loaded");
    drawMap();
    renderNavigation();
  } catch (error) {
    mapPlaceholder.textContent = error.message;
  }
};

const drawMap = () => {
  if (!currentMap) return;
  const context = mapCanvas.getContext("2d");
  const image = context.createImageData(currentMap.width, currentMap.height);
  for (let y = 0; y < currentMap.height; y += 1) {
    for (let x = 0; x < currentMap.width; x += 1) {
      const value = currentMap.data[y * currentMap.width + x];
      const displayY = currentMap.height - 1 - y;
      const offset = (displayY * currentMap.width + x) * 4;
      const shade = value < 0 ? 70 : Math.round(238 - (Math.min(value, 100) / 100) * 225);
      image.data[offset] = shade;
      image.data[offset + 1] = shade;
      image.data[offset + 2] = value < 0 ? shade + 4 : shade;
      image.data[offset + 3] = 255;
    }
  }
  context.putImageData(image, 0, 0);
  const robot = selectedRobot();
  if (robot?.navigation?.current?.frame_id === "map") {
    drawArrow(context, robot.navigation.current, "#44b9ff");
  }
  if (robot?.navigation?.target?.frame_id === "map") {
    drawArrow(context, robot.navigation.target, "#ffd166");
  }
  if (selectedPose) drawArrow(context, selectedPose, "#58e0ae");
};

const drawArrow = (context, pose, color) => {
  const start = worldToCanvas(pose.x, pose.y);
  const length = Math.max(currentMap.resolution * 5, 0.25);
  const end = worldToCanvas(
    pose.x + Math.cos(pose.yaw) * length,
    pose.y + Math.sin(pose.yaw) * length,
  );
  context.save();
  context.strokeStyle = color;
  context.fillStyle = color;
  context.lineWidth = Math.max(1.5, currentMap.width / 260);
  context.beginPath();
  context.arc(start.x, start.y, Math.max(3, currentMap.width / 100), 0, Math.PI * 2);
  context.fill();
  context.beginPath();
  context.moveTo(start.x, start.y);
  context.lineTo(end.x, end.y);
  context.stroke();
  context.restore();
};

const worldToCanvas = (x, y) => {
  return mapMath.worldToCanvas(currentMap, x, y);
};

const canvasToWorld = (x, y) => {
  return mapMath.canvasToWorld(currentMap, x, y);
};

const canvasCoordinates = (event) => {
  const bounds = mapCanvas.getBoundingClientRect();
  return {
    x: (event.clientX - bounds.left) * (mapCanvas.width / bounds.width),
    y: (event.clientY - bounds.top) * (mapCanvas.height / bounds.height),
  };
};

mapCanvas.addEventListener("pointerdown", (event) => {
  if (!currentMap) return;
  mapCanvas.setPointerCapture(event.pointerId);
  const point = canvasCoordinates(event);
  dragStart = canvasToWorld(point.x, point.y);
  selectedPose = { ...dragStart, yaw: Number(poseYaw.value) || 0 };
  drawMap();
});

mapCanvas.addEventListener("pointermove", (event) => {
  if (!currentMap || !dragStart || !mapCanvas.hasPointerCapture(event.pointerId)) return;
  const point = canvasCoordinates(event);
  const end = canvasToWorld(point.x, point.y);
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
  if (!dragStart) return;
  if (!selectedPose) selectedPose = { ...dragStart, yaw: 0 };
  poseX.value = selectedPose.x.toFixed(3);
  poseY.value = selectedPose.y.toFixed(3);
  poseYaw.value = selectedPose.yaw.toFixed(3);
  dragStart = null;
  mapCanvas.releasePointerCapture(event.pointerId);
  drawMap();
});

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

const loadOperations = async () => {
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
