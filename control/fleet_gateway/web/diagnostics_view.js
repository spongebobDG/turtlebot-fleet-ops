"use strict";

(function expose(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.FleetDiagnosticsView = api;
})(typeof globalThis !== "undefined" ? globalThis : this, () => {
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

  const diagnosisKey = (item, index) => String(
    item?.cause || item?.label || `diagnosis-${index}`,
  );

  const diagnosisRows = (diagnoses, options = {}) => {
    const openKeys = new Set(options.openKeys || []);
    const hasRendered = Boolean(options.hasRendered);
    return (diagnoses || []).map((item, index) => ({
      item,
      key: diagnosisKey(item, index),
      open: hasRendered
        ? openKeys.has(diagnosisKey(item, index))
        : index === 0,
    }));
  };

  const modelPresentation = (status, analysisMode) => {
    const modelId = String(status?.model_id || "").trim();
    if (modelId) {
      const validation = status?.model_validation || {};
      const detectionRate = Number(validation.overall_detection_rate);
      const falsePositiveRate = Number(validation.baseline_false_positive_rate);
      const validationLabel = validation.validation_strength === "operator_confirmed"
        ? "사람 확인 라벨"
        : "자동 규칙 라벨(현장 확인 진행 중)";
      const scenarioCount = Array.isArray(validation.covered_fault_scenarios)
        ? validation.covered_fault_scenarios.length
        : 0;
      let metrics = scenarioCount
        && Number.isFinite(detectionRate)
        && Number.isFinite(falsePositiveRate)
        ? ` ${validationLabel} 기반으로 고장 상황 ${scenarioCount}종, 탐지율 ${Math.round(detectionRate * 100)}%, 정상 오탐률 ${Math.round(falsePositiveRate * 100)}%를 검증했습니다.`
        : "";
      const confirmedFaultCount = Array.isArray(
        validation.operator_confirmed_fault_scenarios,
      ) ? validation.operator_confirmed_fault_scenarios.length : 0;
      const confirmedNormalCount = Number(
        validation.operator_confirmed_normal_window_count || 0,
      );
      metrics += ` 현장 확인: 장애 ${confirmedFaultCount}종·정상 ${confirmedNormalCount}창 (독립 검증 기준 장애 3종·정상 2창).`;
      return {
        label: modelId,
        explanation: `검토·승격된 정상 로그 기준 ML 모델과 규칙 기반 원인 분석을 함께 사용합니다.${metrics}`,
      };
    }
    if (analysisMode === "RULE_ONLY") {
      return {
        label: "규칙 분석 · ML 미승격",
        explanation: "현재는 LLM이 아니라 코드에 정의된 증거 규칙이 원인을 분류합니다. 정상 주행 로그로 후보 모델을 학습·검토한 뒤 Production으로 승격하면 ML 이상 점수가 추가됩니다.",
      };
    }
    return {
      label: "분석 준비 중",
      explanation: "로그 수집 상태와 Production 모델 레지스트리를 확인하고 있습니다.",
    };
  };

  const statusPresentation = (status) => {
    const presentations = {
      ACTION_REQUIRED: { label: "현재 확인 필요", tone: "active" },
      HISTORICAL: { label: "과거 이력", tone: "historical" },
      EXPECTED_STARTUP: { label: "초기화 대기", tone: "expected" },
      EXPECTED_SAFETY_STATE: { label: "정상 안전 상태", tone: "expected" },
    };
    return presentations[String(status || "").toUpperCase()]
      || { label: String(status || "검토"), tone: "review" };
  };

  const localAIStatusPresentation = (status) => {
    const state = String(status?.state || "UNAVAILABLE").toUpperCase();
    const model = String(status?.model || "qwen3:8b");
    const labels = {
      READY: "READY",
      MODEL_NOT_READY: "MODEL NOT READY",
      DISABLED: "DISABLED",
      UNAVAILABLE: "UNAVAILABLE",
    };
    return {
      label: `Local AI · ${model} · ${labels[state] || state}`,
      tone: state.toLowerCase().replaceAll("_", "-"),
      canAnalyze: state === "READY",
      explanation: String(status?.message || "로컬 AI 상태를 확인할 수 없습니다."),
    };
  };

  const aiAssessmentPresentation = (assessment) => {
    const values = {
      LIKELY: "가능성 높음",
      POSSIBLE: "가능성 있음",
      INSUFFICIENT_EVIDENCE: "근거 부족",
    };
    return values[String(assessment || "").toUpperCase()] || "AI 자문";
  };

  const localAIActionPresentation = ({ canAnalyze, inFlight, hasResult }) => ({
    disabled: !canAnalyze || inFlight,
    label: inFlight
      ? "로컬 AI 분석 중…"
      : (hasResult ? "로컬 AI 분석 다시 확인" : "로컬 AI 분석"),
  });

  const localAIResultPresentation = (result) => {
    if (result?.state === "ERROR") {
      return {
        isError: true,
        message: String(result.message || "분석 결과를 가져오지 못했습니다."),
        source: "",
      };
    }
    const latency = Number(result?.latency_ms || 0) / 1000;
    return {
      isError: false,
      message: "",
      source: result?.cached ? "캐시 재사용" : `${latency}초`,
    };
  };

  const formatAge = (ageSec) => {
    const value = Number(ageSec);
    if (!Number.isFinite(value)) return "시각 미상";
    if (value < 60) return `${Math.round(value)}초 전`;
    if (value < 3600) return `${Math.round(value / 60)}분 전`;
    return `${Math.round(value / 3600)}시간 전`;
  };

  const diagnosisMeta = (item) => {
    const occurrences = Number(item?.occurrence_count ?? item?.count ?? 0);
    const rawCount = Number(item?.raw_count ?? item?.count ?? occurrences);
    const countText = rawCount === occurrences
      ? `${occurrences}회`
      : `${occurrences}회 · 원문 ${rawCount}건`;
    const sourceCount = Number(item?.source_count ?? item?.sources?.length ?? 0);
    const sourceText = sourceCount ? ` · 출처 ${sourceCount}개` : "";
    return `마지막 ${formatAge(item?.age_sec)} · ${countText}${sourceText}`;
  };

  const incidentSummary = (payload) => {
    const summary = payload?.summary || {};
    const health = payload?.data_health || {};
    const healthLabels = {
      FRESH: "최근 근거 있음",
      STALE_EVIDENCE: "최근 근거 없음",
      NO_DATA: "수집 로그 없음",
    };
    const age = health.latest_record_age_sec;
    const evidenceAge = age !== null
      && age !== undefined
      && Number.isFinite(Number(age))
      ? ` · 마지막 로그 ${formatAge(age)}`
      : "";
    return `현재 조치 ${Number(summary.active || 0)} · 과거 ${Number(summary.historical || 0)} · 정상·예상 ${Number(summary.expected || 0)} · ${healthLabels[health.state] || "수집 상태 확인 중"}${evidenceAge}`;
  };

  return {
    aiAssessmentPresentation,
    diagnosisMeta,
    diagnosisRows,
    escapeHtml,
    formatAge,
    incidentSummary,
    localAIActionPresentation,
    localAIResultPresentation,
    localAIStatusPresentation,
    modelPresentation,
    statusPresentation,
  };
});
