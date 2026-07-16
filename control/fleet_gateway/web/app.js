const grid = document.querySelector("#robot-grid");
const connection = document.querySelector("#connection");
const connectionLabel = document.querySelector("#connection-label");
const updatedAt = document.querySelector("#updated-at");
const toast = document.querySelector("#toast");
let reconnectTimer;

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
        <div class="metric"><span>최근 장애물</span><strong>${number(robot.scan?.min_range, 2, "m")}</strong></div>
        <div class="metric"><span>CPU / 메모리</span><strong>${number(robot.system?.cpu_percent, 0)} / ${number(robot.system?.memory_percent, 0)}%</strong></div>
        <div class="metric"><span>Wi-Fi</span><strong>${number(robot.wifi?.signal_dbm, 0, "dBm")}</strong></div>
        <div class="metric"><span>Scan points</span><strong>${robot.scan?.valid_points ?? "—"}</strong></div>
      </div>
      <p class="faults ${robot.fault_codes?.length ? "" : "none"}">${faults}</p>
      <div class="actions">
        <button class="estop" data-robot="${safeRobotId}" data-engaged="true">비상 정지</button>
        <button class="release" data-robot="${safeRobotId}" data-engaged="false" ${robot.online ? "" : "disabled"}>정지 해제</button>
      </div>
    </article>`;
};

const render = (robots) => {
  document.querySelector("#known-count").textContent = robots.length;
  document.querySelector("#online-count").textContent = robots.filter((robot) => robot.online).length;
  document.querySelector("#fault-count").textContent = robots.filter((robot) => !robot.online || robot.level > 0).length;
  grid.innerHTML = robots.length
    ? robots.map(robotCard).join("")
    : `<article class="empty-state"><h3>RobotStatus를 기다리는 중입니다.</h3><p>Gateway가 ROS 2 heartbeat를 받으면 여기에 표시됩니다.</p></article>`;
  updatedAt.textContent = `최근 갱신 ${new Date().toLocaleTimeString("ko-KR")}`;
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

grid.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-robot]");
  if (!button) return;
  const robotId = button.dataset.robot;
  const engaged = button.dataset.engaged === "true";
  const prompt = engaged
    ? `${robotId}에 비상 정지를 적용할까요?`
    : `${robotId}의 비상 정지를 해제할까요? 해제 후에도 중립 명령 전까지 재가동되지 않습니다.`;
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

connect();
