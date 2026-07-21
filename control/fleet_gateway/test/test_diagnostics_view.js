"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  adminAlertPresentation,
  aiAssessmentPresentation,
  diagnosisMeta,
  diagnosisRows,
  escapeHtml,
  incidentSummary,
  localAIActionPresentation,
  localAIResultPresentation,
  localAIStatusPresentation,
  modelPresentation,
  statusPresentation,
} = require("../web/diagnostics_view.js");

test("admin alert stays hidden while robot and log health are normal", () => {
  const presentation = adminAlertPresentation({
    robots: [{ robot_id: "tb1", online: true, level: 0 }],
    faults: [],
    diagnoses: [{ status: "HISTORICAL" }],
    mlops: { state: "NORMAL" },
    dataHealth: { state: "FRESH" },
  });

  assert.equal(presentation.visible, false);
  assert.equal(presentation.count, 0);
});

test("admin alert highlights critical robot faults and actionable log incidents", () => {
  const presentation = adminAlertPresentation({
    robots: [{ robot_id: "tb1", online: false, level: 2 }],
    faults: [{ severity: "ERROR", fault_code: "SCAN_STALE" }],
    diagnoses: [{
      status: "ACTION_REQUIRED",
      label: "LiDAR 입력 중단",
      confirmed_symptom: "최근 LaserScan이 갱신되지 않았습니다.",
    }],
    mlops: { state: "ANOMALY" },
  });

  assert.equal(presentation.visible, true);
  assert.equal(presentation.tone, "critical");
  assert.equal(presentation.label, "관리자 긴급 확인");
  assert.match(presentation.summary, /오프라인 로봇 1/);
  assert.match(presentation.summary, /로그 조치 1/);
  assert.equal(presentation.detail, "최근 LaserScan이 갱신되지 않았습니다.");
});

test("admin alert treats an actionable diagnosis as a visible warning", () => {
  const presentation = adminAlertPresentation({
    robots: [{ robot_id: "tb1", online: true, level: 0 }],
    diagnoses: [{ status: "ACTION_REQUIRED", label: "주행 진행 정체" }],
    mlops: { state: "NORMAL" },
  });

  assert.equal(presentation.visible, true);
  assert.equal(presentation.tone, "warning");
  assert.equal(presentation.detail, "주행 진행 정체");
});

test("admin alert names stale evidence instead of reporting a normal model state", () => {
  const presentation = adminAlertPresentation({
    mlops: { state: "NORMAL" },
    dataHealth: { state: "STALE_EVIDENCE" },
  });

  assert.equal(presentation.visible, true);
  assert.equal(presentation.tone, "warning");
  assert.equal(presentation.summary, "로그 분석 STALE_EVIDENCE");
});

test("diagnosis refresh preserves the user-selected open item", () => {
  const diagnoses = [
    { cause: "clock_sync", label: "Clock" },
    { cause: "transport_reply", label: "Transport" },
  ];

  const firstRender = diagnosisRows(diagnoses, { hasRendered: false });
  assert.deepEqual(firstRender.map((row) => row.open), [true, false]);

  const refreshed = diagnosisRows(diagnoses, {
    hasRendered: true,
    openKeys: ["transport_reply"],
  });
  assert.deepEqual(refreshed.map((row) => row.open), [false, true]);
});

test("rule-only mode explains that no ML model is promoted", () => {
  const presentation = modelPresentation(
    { model_id: null },
    "RULE_ONLY",
  );

  assert.equal(presentation.label, "규칙 분석 · ML 미승격");
  assert.match(presentation.explanation, /LLM이 아니라/);
  assert.match(presentation.explanation, /Production/);
});

test("promoted model explains scenario validation coverage", () => {
  const presentation = modelPresentation({
    model_id: "scenario-model-1",
    model_validation: {
      covered_fault_scenarios: ["safety_stop", "sensor_qos", "navigation_failure"],
      overall_detection_rate: 0.875,
      baseline_false_positive_rate: 0,
    },
  }, "MODEL_AND_RULES");

  assert.equal(presentation.label, "scenario-model-1");
  assert.match(presentation.explanation, /고장 상황 3종/);
  assert.match(presentation.explanation, /자동 규칙 라벨/);
  assert.match(presentation.explanation, /탐지율 88%/);
  assert.match(presentation.explanation, /정상 오탐률 0%/);
});

test("operator-confirmed model identifies independent validation", () => {
  const presentation = modelPresentation({
    model_id: "confirmed-model",
    model_validation: {
      validation_strength: "operator_confirmed",
      covered_fault_scenarios: ["obstacle_clearance"],
      overall_detection_rate: 1,
      baseline_false_positive_rate: 0,
    },
  }, "MODEL_AND_RULES");

  assert.match(presentation.explanation, /사람 확인 라벨/);
});

test("partially confirmed model reports field validation progress", () => {
  const presentation = modelPresentation({
    model_id: "partially-confirmed-model",
    model_validation: {
      validation_strength: "auto_rule_weak_supervision",
      covered_fault_scenarios: ["obstacle_clearance"],
      overall_detection_rate: 1,
      baseline_false_positive_rate: 0,
      operator_confirmed_fault_scenarios: ["obstacle_clearance"],
      operator_confirmed_normal_window_count: 0,
    },
  }, "MODEL_AND_RULES");

  assert.match(presentation.explanation, /현장 확인: 장애 1종·정상 0창/);
  assert.match(presentation.explanation, /독립 검증 기준 장애 3종·정상 2창/);
});

test("diagnosis presentation distinguishes active, historical, and expected states", () => {
  assert.deepEqual(statusPresentation("ACTION_REQUIRED"), {
    label: "현재 확인 필요",
    tone: "active",
  });
  assert.equal(statusPresentation("HISTORICAL").label, "과거 이력");
  assert.equal(statusPresentation("EXPECTED_SAFETY_STATE").tone, "expected");
});

test("diagnosis metadata reports deduplicated occurrences and raw records", () => {
  assert.equal(
    diagnosisMeta({
      age_sec: 65,
      occurrence_count: 2,
      raw_count: 8,
      source_count: 1,
    }),
    "마지막 1분 전 · 2회 · 원문 8건 · 출처 1개",
  );
});

test("incident summary includes lifecycle counts and evidence freshness", () => {
  assert.equal(
    incidentSummary({
      summary: { active: 1, historical: 2, expected: 1 },
      data_health: { state: "FRESH", latest_record_age_sec: 8 },
    }),
    "현재 조치 1 · 과거 2 · 정상·예상 1 · 최근 근거 있음 · 마지막 로그 8초 전",
  );
});

test("no-data summary does not invent a zero-second log age", () => {
  const summary = incidentSummary({
    summary: {},
    data_health: { state: "NO_DATA", latest_record_age_sec: null },
  });

  assert.equal(summary, "현재 조치 0 · 과거 0 · 정상·예상 0 · 수집 로그 없음");
});

test("local AI readiness controls the incident analysis action", () => {
  const ready = localAIStatusPresentation({
    state: "READY",
    model: "qwen3:8b",
    message: "ready",
  });
  const missing = localAIStatusPresentation({
    state: "MODEL_NOT_READY",
    model: "qwen3:8b",
    message: "pull required",
  });

  assert.equal(ready.label, "Local AI · qwen3:8b · READY");
  assert.equal(ready.canAnalyze, true);
  assert.equal(missing.canAnalyze, false);
  assert.equal(missing.tone, "model-not-ready");
  assert.equal(missing.explanation, "pull required");
});

test("local AI assessment keeps uncertainty visible", () => {
  assert.equal(aiAssessmentPresentation("LIKELY"), "가능성 높음");
  assert.equal(aiAssessmentPresentation("POSSIBLE"), "가능성 있음");
  assert.equal(
    aiAssessmentPresentation("INSUFFICIENT_EVIDENCE"),
    "근거 부족",
  );
});

test("local AI action exposes loading and completed states", () => {
  assert.deepEqual(
    localAIActionPresentation({
      canAnalyze: true,
      inFlight: true,
      hasResult: false,
    }),
    { disabled: true, label: "로컬 AI 분석 중…" },
  );
  assert.deepEqual(
    localAIActionPresentation({
      canAnalyze: true,
      inFlight: false,
      hasResult: true,
    }),
    { disabled: false, label: "로컬 AI 분석 다시 확인" },
  );
});

test("local AI result distinguishes errors and cache reuse", () => {
  assert.deepEqual(
    localAIResultPresentation({ state: "ERROR", message: "timeout" }),
    { isError: true, message: "timeout", source: "" },
  );
  assert.equal(
    localAIResultPresentation({ cached: true, latency_ms: 999 }).source,
    "캐시 재사용",
  );
});

test("AI report fields are HTML escaped before rendering", () => {
  assert.equal(
    escapeHtml('<img src=x onerror="alert(1)">&\''),
    "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;&#039;",
  );
});
