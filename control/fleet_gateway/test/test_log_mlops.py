import json
from pathlib import Path

import pytest

from fleet_gateway.log_mlops import (
    LogRecord,
    analyze_records,
    build_dataset,
    build_parser,
    diagnose_records,
    extract_operational_signals,
    incidents_from_path,
    parse_log_line,
    pipeline_paths,
    promote_model,
    read_recent_jsonl,
    replay_jsonl_range,
    run_command,
    score_features,
    status_from_path,
    train_model,
    write_json,
    write_jsonl,
)


def record(timestamp, severity="INFO", message="heartbeat ok"):
    return LogRecord(
        timestamp=float(timestamp),
        severity=severity,
        logger="fleet_gateway",
        message=message,
        unit="fleet-gateway.service",
    )


def healthy_training_records():
    records = []
    epoch = 1_700_000_000
    for minute in range(6):
        start = epoch + minute * 60
        records.extend(record(start + offset) for offset in range(10))
    return records


def test_parses_journal_json_and_ros2_console_lines():
    journal = parse_log_line(
        json.dumps(
            {
                "__REALTIME_TIMESTAMP": "2000000",
                "PRIORITY": "3",
                "SYSLOG_IDENTIFIER": "nav2_controller",
                "_SYSTEMD_UNIT": "tb1-navigation.service",
                "MESSAGE": "goal aborted after timeout",
            }
        )
    )
    ros = parse_log_line(
        "[WARN] [42.500] [amcl]: laser update timeout"
    )

    assert journal.timestamp == 2.0
    assert journal.severity == "ERROR"
    assert journal.unit == "tb1-navigation.service"
    assert ros.timestamp == 42.5
    assert ros.severity == "WARNING"
    assert ros.logger == "amcl"


def test_dataset_is_windowed_and_content_addressed():
    dataset = build_dataset(
        healthy_training_records(),
        window_sec=60.0,
        created_at="2026-07-19T00:00:00+00:00",
    )

    assert dataset["record_count"] == 60
    assert dataset["discarded_record_count"] == 0
    assert len(dataset["rows"]) == 6
    assert dataset["rows"][0]["features"]["line_count"] == 10.0
    assert len(dataset["dataset_hash"]) == 64


def test_dataset_discards_nonpositive_and_nonfinite_timestamps():
    dataset = build_dataset(
        [record(0), record(float("nan")), record(1_700_000_000)]
    )

    assert dataset["record_count"] == 1
    assert dataset["discarded_record_count"] == 2
    assert len(dataset["rows"]) == 1


def test_dataset_time_range_excludes_historical_incidents():
    dataset = build_dataset(
        [record(100), record(200), record(300), record(400)],
        since_timestamp=200,
        until_timestamp=400,
    )

    assert dataset["record_count"] == 2
    assert dataset["discarded_record_count"] == 0
    assert dataset["excluded_outside_range_count"] == 2
    assert dataset["since_timestamp"] == 200
    assert dataset["until_timestamp"] == 400

    model = train_model(dataset)
    assert model["quality"]["excluded_outside_range_count"] == 2


def test_dataset_time_range_must_be_valid():
    with pytest.raises(ValueError, match="positive and finite"):
        build_dataset([record(1)], since_timestamp=0)
    with pytest.raises(ValueError, match="earlier"):
        build_dataset([record(1)], since_timestamp=20, until_timestamp=10)


def test_training_gate_and_explainable_anomaly_score():
    dataset = build_dataset(
        healthy_training_records(),
        created_at="2026-07-19T00:00:00+00:00",
    )
    model = train_model(
        dataset,
        trained_at="2026-07-19T00:01:00+00:00",
    )
    anomalous = [
        record(index, "ERROR", "navigation goal aborted after timeout")
        for index in range(10)
    ]
    status = analyze_records(
        anomalous,
        {**model, "stage": "production"},
        observed_at="2026-07-19T00:02:00+00:00",
    )

    assert model["quality"]["gate_passed"] is True
    assert model["quality"]["discarded_record_count"] == 0
    assert model["quality"]["warnings"] == []
    assert status["state"] == "ANOMALY"
    assert status["score"] > status["threshold"]
    top_names = {item["feature"] for item in status["top_features"]}
    assert "error_rate" in top_names or "timeout_rate" in top_names


def test_model_promotion_rejects_failed_gate_and_publishes_atomically(
    tmp_path,
):
    dataset = build_dataset([record(1), record(2)])
    rejected_model = train_model(dataset)
    rejected_path = tmp_path / "rejected.json"
    write_json(rejected_path, rejected_model)

    with pytest.raises(ValueError, match="quality gate"):
        promote_model(tmp_path, rejected_path)

    accepted = train_model(build_dataset(healthy_training_records()))
    accepted_path = tmp_path / "accepted.json"
    write_json(accepted_path, accepted)
    production = promote_model(tmp_path, accepted_path)

    published = pipeline_paths(tmp_path)["production"]
    assert published.is_file()
    assert production["stage"] == "production"
    assert status_from_path(published)["model_id"] == accepted["model_id"]


def test_scoring_is_deterministic_and_missing_status_is_visible(tmp_path):
    model = train_model(build_dataset(healthy_training_records()))
    features = model["centers"]

    first = score_features(features, model)
    second = score_features(features, model)

    assert first == second
    assert first["score"] == 0.0
    assert status_from_path(tmp_path / "missing.json")["state"] == (
        "MODEL_NOT_READY"
    )


def test_status_becomes_stale_when_inference_monitor_stops(tmp_path):
    status_path = tmp_path / "latest.json"
    write_json(
        status_path,
        {
            "state": "NORMAL",
            "observed_at": "1970-01-01T00:00:10+00:00",
            "message": "normal",
        },
    )

    status = status_from_path(status_path, stale_after_sec=60, now=80)

    assert status["state"] == "STALE"
    assert status["source_state"] == "NORMAL"


def test_model_not_ready_still_reports_collection_health():
    records = [record(1), record(2, "WARNING", "timeout")]

    status = analyze_records(records, None)

    assert status["state"] == "MODEL_NOT_READY"
    assert status["log_count"] == 2
    assert status["feature_values"]["warning_rate"] == 0.5


def test_nav2_operational_signals_are_explainable_before_promotion():
    records = [
        record(1, "WARNING", "Control loop missed its desired rate"),
        record(2, "WARNING", "Behavior Tree tick rate 100.00 was exceeded"),
        record(3, "WARNING", "Planning algorithm failed to generate a valid path"),
        record(4, "WARNING", "Collision Ahead - Exiting Spin"),
        record(5, "ERROR", "Failed to make progress"),
    ]

    signals = extract_operational_signals(records)
    status = analyze_records(records, None)

    assert signals[0] == {
        "signal": "control_deadline_miss",
        "label": "제어 주기 지연",
        "count": 2,
    }
    assert {item["signal"] for item in signals} == {
        "control_deadline_miss",
        "planning_failure",
        "collision_guard",
        "progress_failure",
    }
    assert status["operational_signals"] == signals
    assert "현재 운영 신호" in status["message"]


def test_initial_pose_wait_is_distinct_from_navigation_failure():
    records = [
        record(
            1,
            "WARNING",
            "Timed out waiting for transform from base_link to map to become available",
        ),
        record(
            2,
            "WARNING",
            "AMCL cannot publish a pose. Please set the initial pose...",
        ),
    ]

    signals = extract_operational_signals(records)

    assert signals == [
        {"signal": "initial_pose_wait", "label": "초기 위치 대기", "count": 2}
    ]


def test_dataset_cli_does_not_require_journal_only_arguments(
    tmp_path,
    capsys,
):
    raw_path = tmp_path / "raw.jsonl"
    write_jsonl(raw_path, healthy_training_records())
    arguments = build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "build-dataset",
            "--input",
            str(raw_path),
        ]
    )

    assert run_command(arguments) == 0
    artifact = capsys.readouterr().out.strip()
    assert artifact.endswith(".json")


def test_dataset_cli_applies_baseline_epoch(tmp_path, capsys):
    raw_path = tmp_path / "raw.jsonl"
    write_jsonl(raw_path, [record(100), record(200), record(300)])
    arguments = build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "build-dataset",
            "--input",
            str(raw_path),
            "--since-epoch",
            "200",
        ]
    )

    assert run_command(arguments) == 0
    artifact = Path(capsys.readouterr().out.strip())
    dataset = json.loads(artifact.read_text(encoding="utf-8"))
    assert dataset["record_count"] == 2
    assert dataset["excluded_outside_range_count"] == 1


def test_replay_cli_scores_an_immutable_error_range(tmp_path, capsys):
    paths = pipeline_paths(tmp_path)
    model = train_model(build_dataset(healthy_training_records(), 60.0))
    model["stage"] = "production"
    write_json(paths["production"], model)
    raw_path = tmp_path / "raw.jsonl"
    write_jsonl(
        raw_path,
        [
            record(0),
            record(100),
            record(200, "ERROR", "controller timeout"),
            record(201, "ERROR", "failed to make progress"),
            record(300),
        ],
    )
    arguments = build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "replay",
            "--input",
            str(raw_path),
            "--since-epoch",
            "200",
            "--until-epoch",
            "201",
        ]
    )

    assert run_command(arguments) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["state"] == "ANOMALY"
    assert status["feature_values"]["error_rate"] == 1.0
    assert status["replay"] == {
        "since_timestamp": 200.0,
        "until_timestamp": 201.0,
        "record_count": 2,
        "excluded_outside_range_count": 2,
        "excluded_invalid_timestamp_count": 1,
    }


def test_replay_rejects_a_reversed_time_range(tmp_path):
    raw_path = tmp_path / "raw.jsonl"
    write_jsonl(raw_path, [record(100)])

    with pytest.raises(ValueError, match="finite and ordered"):
        replay_jsonl_range([raw_path], {}, 200, 100)


def test_recent_jsonl_restore_survives_a_torn_last_record(tmp_path):
    raw = tmp_path / "live.jsonl"
    raw.write_text(
        "\n".join(
            [
                json.dumps(record(10).__dict__),
                json.dumps(record(20, "WARNING", "Collision Ahead").__dict__),
                '{"timestamp":',
            ]
        ),
        encoding="utf-8",
    )

    restored = read_recent_jsonl([raw], cutoff_timestamp=15)

    assert len(restored) == 1
    assert restored[0].timestamp == 20
    assert restored[0].message == "Collision Ahead"


def test_root_cause_diagnosis_keeps_evidence_and_recommendation():
    records = [
        record(100, "ERROR", "Failed to make progress in map frame"),
        record(101, "WARNING", "controller progress checker failed"),
        record(102, "ERROR", "Navigation lease expired after timeout"),
    ]

    diagnoses = diagnose_records(records)

    assert diagnoses[0]["cause"] == "network_lease"
    progress = next(
        item for item in diagnoses if item["cause"] == "navigation_progress"
    )
    assert progress["count"] == 2
    assert progress["confidence"] > 0.5
    assert "map-frame" in progress["recommended_action"]
    assert progress["evidence"][-1]["logger"] == "fleet_gateway"


def test_root_cause_diagnosis_ignores_success_path_info_messages():
    records = [
        record(
            100,
            "INFO",
            "Navigation agent ready: robot=tb1, lease timeout=2.0s",
        ),
        record(
            101,
            "INFO",
            "Rotation Shim Controller was unable to find a goal point, "
            "a rotational collision was detected, or TF failed to transform "
            "into base frame! what(): Failed to transform pose to base frame!",
        ),
    ]

    assert diagnose_records(records) == []


def test_root_cause_diagnosis_keeps_warning_level_tf_and_lease_failures():
    records = [
        record(100, "WARNING", "Failed to transform pose to base frame"),
        record(101, "ERROR", "Navigation lease expired after timeout"),
    ]

    causes = {item["cause"] for item in diagnose_records(records)}

    assert causes == {"localization_tf", "network_lease"}


def test_incident_artifact_links_raw_evidence_to_model_status(tmp_path):
    root = tmp_path / "ros2-logs"
    status_path = root / "status" / "latest.json"
    write_json(
        status_path,
        {
            "state": "NORMAL",
            "observed_at": "2026-07-20T00:00:00+00:00",
            "model_id": "model-1",
            "score": 1.0,
            "threshold": 5.0,
        },
    )
    write_jsonl(
        root / "raw" / "live.jsonl",
        [record(1_784_473_917, "ERROR", "Failed to make progress")],
    )

    result = incidents_from_path(status_path)

    assert result["analysis_method"] == "rule_evidence_v1"
    assert result["model"]["model_id"] == "model-1"
    assert result["diagnoses"][0]["cause"] == "navigation_progress"
