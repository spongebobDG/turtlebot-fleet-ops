import json
import os
import stat
import threading
import time

import pytest

from fleet_gateway.log_ai import (
    LocalAIBusy,
    LocalAIInvalidResponse,
    LocalAINotReady,
    LocalAITimeout,
    LocalLogAIAnalyzer,
    sanitize_log_message,
)
from fleet_gateway.log_mlops import (
    LogRecord,
    incidents_from_path,
    write_json,
    write_jsonl,
)


def make_runtime(tmp_path, message="Navigation lease expired token=secret-value"):
    root = tmp_path / "ros2-logs"
    status_path = root / "status" / "latest.json"
    now = time.time()
    write_json(
        status_path,
        {
            "state": "ANOMALY",
            "observed_at": "2999-01-01T00:00:00+00:00",
            "model_id": "model-1",
            "score": 8.0,
            "threshold": 4.0,
        },
    )
    write_jsonl(
        root / "raw" / "live.jsonl",
        [
            LogRecord(
                timestamp=now,
                severity="ERROR",
                logger="navigation_agent",
                message=message,
                unit="tb1-navigation.service",
            )
        ],
    )
    incident = incidents_from_path(status_path)["diagnoses"][0]
    return root, status_path, incident


class SuccessfulOllama:

    def __init__(self):
        self.posts = 0
        self.last_payload = None
        self.last_context = None

    def __call__(self, method, url, payload, _timeout):
        if method == "GET":
            return {"models": [{"name": "qwen3:8b"}]}
        self.posts += 1
        self.last_payload = payload
        self.last_context = json.loads(payload["messages"][1]["content"])
        evidence_id = next(iter(self.last_context["allowed_evidence"]))
        check_id = next(iter(self.last_context["allowed_checks"]))
        fix_id = next(iter(self.last_context["allowed_fixes"]))
        report = {
            "summary_ko": "Navigation lease 만료 근거가 확인됐습니다.",
            "assessment": "LIKELY",
            "primary_cause": {
                "label": "통신 lease 전달 중단",
                "confidence": 0.82,
                "rationale": "선택 사건의 오류 로그와 규칙 진단이 일치합니다.",
                "evidence_ids": [evidence_id],
            },
            "alternative_causes": [],
            "recommended_check_ids": [check_id],
            "recommended_fix_ids": [fix_id],
            "missing_evidence": ["Gateway TX와 TB1 RX sequence 비교가 필요합니다."],
            "operator_cautions": ["2초 deadman timeout을 임의로 늘리지 마세요."],
        }
        return {
            "message": {"content": json.dumps(report, ensure_ascii=False)},
            "prompt_eval_count": 350,
            "eval_count": 120,
        }


def test_sanitizes_credentials_and_bounds_untrusted_messages():
    value = sanitize_log_message(
        "Authorization: Bearer Bearer-secret token=abc password='wifi-pass' "
        + "x" * 400
    )

    assert "Bearer-secret" not in value
    assert "abc" not in value
    assert "wifi-pass" not in value
    assert value.count("<redacted>") == 3
    assert len(value) == 240


def test_local_analyzer_generates_validated_report_and_reuses_cache(tmp_path):
    root, status_path, incident = make_runtime(tmp_path)
    ollama = SuccessfulOllama()
    analyzer = LocalLogAIAnalyzer(
        status_path=status_path,
        root=root,
        robot_snapshot=lambda: [
            {
                "robot_id": "tb1",
                "online": True,
                "authorization_token": "must-not-leak",
                "navigation": {"state": "FAILED"},
            }
        ],
        enabled=True,
        http_json=ollama,
    )

    first = analyzer.analyze(incident["incident_id"])
    second = analyzer.analyze(incident["incident_id"])

    assert first["state"] == "READY"
    assert first["model"] == "qwen3:8b"
    assert first["cached"] is False
    assert second["cached"] is True
    assert first["analysis_id"] == second["analysis_id"]
    assert ollama.posts == 1
    assert ollama.last_payload["think"] is False
    assert ollama.last_payload["stream"] is False
    assert ollama.last_payload["options"]["num_ctx"] == 8192
    assert len(ollama.last_payload["messages"][1]["content"]) <= 24000
    assert "secret-value" not in ollama.last_payload["messages"][1]["content"]
    assert "must-not-leak" not in ollama.last_payload["messages"][1]["content"]
    assert first["report"]["recommended_checks"][0]["text"]
    assert first["report"]["recommended_fixes"][0]["text"]
    cache_path = analyzer.analyses_dir / f"{first['analysis_id']}.json"
    assert cache_path.is_file()
    assert stat.S_IMODE(os.stat(cache_path).st_mode) == 0o600
    assert "thinking" not in cache_path.read_text(encoding="utf-8")


def test_health_reports_missing_model_without_breaking_other_analysis(tmp_path):
    root, status_path, _incident = make_runtime(tmp_path)
    analyzer = LocalLogAIAnalyzer(
        status_path=status_path,
        root=root,
        robot_snapshot=list,
        enabled=True,
        http_json=lambda *_args: {"models": [{"name": "other:latest"}]},
    )

    assert analyzer.health()["state"] == "MODEL_NOT_READY"
    with pytest.raises(LocalAINotReady):
        analyzer.analyze("incident-missing")


def test_invalid_structured_response_is_rejected(tmp_path):
    root, status_path, incident = make_runtime(tmp_path)

    def invalid_ollama(method, _url, _payload, _timeout):
        if method == "GET":
            return {"models": [{"name": "qwen3:8b"}]}
        return {"message": {"content": "not-json"}}

    analyzer = LocalLogAIAnalyzer(
        status_path=status_path,
        root=root,
        robot_snapshot=list,
        enabled=True,
        http_json=invalid_ollama,
    )

    with pytest.raises(LocalAIInvalidResponse):
        analyzer.analyze(incident["incident_id"])


def test_timeout_remains_fail_visible(tmp_path):
    root, status_path, incident = make_runtime(tmp_path)

    def timeout_ollama(method, _url, _payload, _timeout):
        if method == "GET":
            return {"models": [{"name": "qwen3:8b"}]}
        raise LocalAITimeout("timeout")

    analyzer = LocalLogAIAnalyzer(
        status_path=status_path,
        root=root,
        robot_snapshot=list,
        enabled=True,
        http_json=timeout_ollama,
    )

    with pytest.raises(LocalAITimeout):
        analyzer.analyze(incident["incident_id"])


def test_rejects_nonlocal_ollama_endpoint(tmp_path):
    with pytest.raises(ValueError, match="localhost"):
        LocalLogAIAnalyzer(
            status_path=tmp_path / "latest.json",
            root=tmp_path,
            robot_snapshot=list,
            enabled=True,
            base_url="https://example.com",
        )


def test_single_inference_slot_fails_fast_when_busy(tmp_path):
    root, status_path, incident = make_runtime(tmp_path)
    ollama = SuccessfulOllama()
    entered = threading.Event()
    release = threading.Event()

    def blocking_ollama(method, url, payload, timeout):
        if method == "GET":
            return ollama(method, url, payload, timeout)
        entered.set()
        assert release.wait(timeout=2.0)
        return ollama(method, url, payload, timeout)

    analyzer = LocalLogAIAnalyzer(
        status_path=status_path,
        root=root,
        robot_snapshot=list,
        enabled=True,
        http_json=blocking_ollama,
    )
    outcome = []
    worker = threading.Thread(
        target=lambda: outcome.append(analyzer.analyze(incident["incident_id"])),
    )
    worker.start()
    assert entered.wait(timeout=2.0)
    try:
        with pytest.raises(LocalAIBusy):
            analyzer.analyze(incident["incident_id"])
    finally:
        release.set()
        worker.join(timeout=3.0)

    assert not worker.is_alive()
    assert outcome[0]["state"] == "READY"
