import json

import pytest

from fleet_gateway.log_mlops import (
    LogRecord,
    analyze_records,
    build_dataset,
    build_parser,
    parse_log_line,
    pipeline_paths,
    promote_model,
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
