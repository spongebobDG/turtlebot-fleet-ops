const grid = document.querySelector("#robot-grid");
const connection = document.querySelector("#connection");
const connectionLabel = document.querySelector("#connection-label");
const updatedAt = document.querySelector("#updated-at");
const toast = document.querySelector("#toast");
let reconnectTimer;
const goalDrafts = new Map();
let navigationByRobot = new Map();

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

const navigationPanel = (robot, navigation) => {
  const robotId = robot.robot_id;
  const safeRobotId = escapeHtml(robotId);
  if (!goalDrafts.has(robotId)) {
    goalDrafts.set(robotId, {
      x: "",
      y: "",
      yaw: "0",
      timeout: "300",
    });
  }
  const draft = goalDrafts.get(robotId);
  const status = navigation?.status || "IDLE";
  const active = ["PENDING", "RUNNING", "CANCELING"].includes(status);
  const feedback = navigation?.feedback || {};
  return `
    <section class="navigation-panel" data-navigation-robot="${safeRobotId}">
      <div class="navigation-heading">
        <strong>Nav2 목적지</strong>
        <span class="navigation-status" data-status="${escapeHtml(status)}">${escapeHtml(status)}</span>
      </div>
      <div class="goal-inputs">
        <label>X (m)<input inputmode="decimal" data-field="x" value="${escapeHtml(draft.x)}" placeholder="1.20"></label>
        <label>Y (m)<input inputmode="decimal" data-field="y" value="${escapeHtml(draft.y)}" placeholder="-0.40"></label>
        <label>Yaw (rad)<input inputmode="decimal" data-field="yaw" value="${escapeHtml(draft.yaw)}"></label>
        <label>Timeout (s)<input inputmode="numeric" data-field="timeout" value="${escapeHtml(draft.timeout)}"></label>
      </div>
      <div class="navigation-feedback">
        <span>남은 거리 ${number(feedback.distance_remaining, 2, "m")}</span>
        <span>예상 시간 ${number(feedback.estimated_time_remaining_sec, 1, "s")}</span>
      </div>
      <div class="navigation-actions">
        <button class="goal" data-action="goal" data-robot="${safeRobotId}" ${robot.online && !active ? "" : "disabled"}>목적지 전송</button>
        <button class="cancel" data-action="cancel" data-robot="${safeRobotId}" ${active ? "" : "disabled"}>주행 취소</button>
      </div>
    </section>`;
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
      ${navigationPanel(robot, navigationByRobot.get(robot.robot_id))}
      <div class="actions">
        <button class="estop" data-action="estop" data-robot="${safeRobotId}" data-engaged="true">비상 정지</button>
        <button class="release" data-action="estop" data-robot="${safeRobotId}" data-engaged="false" ${robot.online ? "" : "disabled"}>정지 해제</button>
      </div>
    </article>`;
};

const render = (robots, navigationStates = []) => {
  const focused = document.activeElement?.matches("input[data-field]")
    ? {
      robotId: document.activeElement.closest("[data-navigation-robot]")?.dataset.navigationRobot,
      field: document.activeElement.dataset.field,
      start: document.activeElement.selectionStart,
      end: document.activeElement.selectionEnd,
    }
    : null;
  navigationByRobot = new Map(
    navigationStates.map((item) => [item.robot_id, item]),
  );
  document.querySelector("#known-count").textContent = robots.length;
  document.querySelector("#online-count").textContent = robots.filter((robot) => robot.online).length;
  document.querySelector("#fault-count").textContent = robots.filter((robot) => !robot.online || robot.level > 0).length;
  grid.innerHTML = robots.length
    ? robots.map(robotCard).join("")
    : `<article class="empty-state"><h3>RobotStatus를 기다리는 중입니다.</h3><p>Gateway가 ROS 2 heartbeat를 받으면 여기에 표시됩니다.</p></article>`;
  if (focused?.robotId && focused?.field) {
    const panel = [...grid.querySelectorAll("[data-navigation-robot]")]
      .find((item) => item.dataset.navigationRobot === focused.robotId);
    const input = panel?.querySelector(`[data-field="${focused.field}"]`);
    input?.focus();
    input?.setSelectionRange(focused.start, focused.end);
  }
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
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    render(message.robots || [], message.navigation || []);
  });
  socket.addEventListener("close", () => {
    setConnection("offline", "재연결 중");
    reconnectTimer = window.setTimeout(connect, 1500);
  });
  socket.addEventListener("error", () => socket.close());
};

const requestEStop = async (button) => {
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
};

const requestGoal = async (button) => {
  const robotId = button.dataset.robot;
  const panel = button.closest("[data-navigation-robot]");
  const field = (name) => panel.querySelector(`[data-field="${name}"]`).value;
  if (!field("x").trim() || !field("y").trim()) {
    showToast("목적지 X와 Y를 모두 입력하세요.", true);
    return;
  }
  const payload = {
    x: Number(field("x")),
    y: Number(field("y")),
    yaw: Number(field("yaw")),
    timeout_sec: Number(field("timeout")),
  };
  if (!Object.values(payload).every(Number.isFinite)) {
    showToast("목적지와 timeout에 유한한 숫자를 입력하세요.", true);
    return;
  }
  if (!window.confirm(
    `${robotId}를 map 좌표 (${payload.x}, ${payload.y}, yaw ${payload.yaw})로 이동할까요?`,
  )) return;
  button.disabled = true;
  try {
    const response = await fetch(
      `/api/robots/${encodeURIComponent(robotId)}/navigation/goals`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "Goal 요청 실패");
    showToast(`Goal ${body.goal_id}이 수락됐습니다.`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
};

const requestCancel = async (button) => {
  const robotId = button.dataset.robot;
  if (!window.confirm(`${robotId}의 현재 Nav2 Goal을 취소할까요?`)) return;
  button.disabled = true;
  try {
    const response = await fetch(
      `/api/robots/${encodeURIComponent(robotId)}/navigation/cancel`,
      { method: "POST" },
    );
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "취소 요청 실패");
    showToast(body.message || "주행 취소를 요청했습니다.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
};

grid.addEventListener("input", (event) => {
  const input = event.target.closest("input[data-field]");
  if (!input) return;
  const panel = input.closest("[data-navigation-robot]");
  const robotId = panel.dataset.navigationRobot;
  const draft = goalDrafts.get(robotId) || {};
  draft[input.dataset.field] = input.value;
  goalDrafts.set(robotId, draft);
});

grid.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action][data-robot]");
  if (!button) return;
  if (button.dataset.action === "estop") await requestEStop(button);
  if (button.dataset.action === "goal") await requestGoal(button);
  if (button.dataset.action === "cancel") await requestCancel(button);
});

connect();
