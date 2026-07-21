#!/usr/bin/env python3
"""Run offline acceptance scenarios against the configured local Ollama model."""

import argparse
import json
from pathlib import Path
import re
import tempfile
import time

from fleet_gateway.log_ai import LocalLogAIAnalyzer
from fleet_gateway.log_mlops import (
    LogRecord,
    incidents_from_path,
    write_json,
    write_jsonl,
)


SCENARIOS = (
    (
        "network_lease",
        "Navigation lease expired after 2.4 seconds; canceling Nav2 goal",
    ),
    (
        "collision_clearance",
        "OBSTACLE_CLEARANCE_BLOCKED collision ahead at 0.18 m",
    ),
    (
        "navigation_progress",
        "Controller failed to make progress; progress checker timeout",
    ),
    (
        "sensor_data",
        "Laser scan stale; dropping message because sensor data timed out",
    ),
)
HANGUL = re.compile(r"[가-힣]")


def _scenario_runtime(base: Path, cause: str, message: str):
    root = base / cause
    status_path = root / "status" / "latest.json"
    write_json(
        status_path,
        {
            "state": "ANOMALY",
            "observed_at": "2999-01-01T00:00:00+00:00",
            "model_id": "acceptance-production-statistical-model",
            "score": 8.0,
            "threshold": 4.0,
        },
    )
    write_jsonl(
        root / "raw" / "acceptance.jsonl",
        [
            LogRecord(
                timestamp=time.time(),
                severity="ERROR",
                logger="acceptance_fixture",
                message=message,
                unit="tb1-navigation.service",
            )
        ],
    )
    diagnoses = incidents_from_path(status_path)["diagnoses"]
    incident = next(
        (item for item in diagnoses if item["cause"] == cause),
        None,
    )
    if incident is None:
        raise RuntimeError(f"fixture did not produce {cause}")
    return root, status_path, incident


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--timeout-sec", type=float, default=90.0)
    args = parser.parse_args()

    results = []
    with tempfile.TemporaryDirectory(prefix="fleet-log-ai-acceptance-") as value:
        base = Path(value)
        for cause, message in SCENARIOS:
            root, status_path, incident = _scenario_runtime(
                base,
                cause,
                message,
            )
            analyzer = LocalLogAIAnalyzer(
                status_path=status_path,
                root=root,
                robot_snapshot=lambda: [
                    {
                        "robot_id": "tb1",
                        "online": True,
                        "navigation": {"state": "FAILED"},
                        "safety": {"motion_armed": False},
                    }
                ],
                enabled=True,
                base_url=args.base_url,
                model=args.model,
                timeout_sec=args.timeout_sec,
            )
            response = analyzer.analyze(incident["incident_id"])
            report = response["report"]
            if response["latency_ms"] > args.timeout_sec * 1000:
                raise RuntimeError(f"{cause} exceeded timeout acceptance")
            if not HANGUL.search(report["summary_ko"]):
                raise RuntimeError(f"{cause} did not return a Korean summary")
            if not report["primary_cause"]["evidence_ids"]:
                raise RuntimeError(f"{cause} did not cite evidence")
            cached = analyzer.analyze(incident["incident_id"])
            if not cached["cached"]:
                raise RuntimeError(f"{cause} cache was not reused")
            results.append(
                {
                    "cause": cause,
                    "incident_id": incident["incident_id"],
                    "assessment": report["assessment"],
                    "evidence_ids": report["primary_cause"]["evidence_ids"],
                    "latency_ms": response["latency_ms"],
                    "cached": cached["cached"],
                    "summary_ko": report["summary_ko"],
                }
            )

    print(
        json.dumps(
            {
                "state": "PASS",
                "provider": "ollama",
                "model": args.model,
                "read_only": True,
                "scenarios": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
