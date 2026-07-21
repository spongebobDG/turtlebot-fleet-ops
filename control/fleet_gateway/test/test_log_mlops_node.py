from types import SimpleNamespace

from fleet_gateway.log_mlops_node import (
    journal_payload_to_record,
    rosout_message_to_record,
)


def test_rosout_message_is_normalized_for_feature_pipeline():
    message = SimpleNamespace(
        stamp=SimpleNamespace(sec=10, nanosec=250_000_000),
        level=40,
        name="controller_server",
        msg="navigation goal aborted after timeout",
    )

    record = rosout_message_to_record(message)

    assert record.timestamp == 10.25
    assert record.severity == "ERROR"
    assert record.logger == "controller_server"
    assert record.unit == "rosout"


def test_zero_ros_timestamp_uses_collection_time():
    message = SimpleNamespace(
        stamp=SimpleNamespace(sec=0, nanosec=0),
        level=20,
        name="acceptance",
        msg="probe",
    )

    record = rosout_message_to_record(message, received_at=123.5)

    assert record.timestamp == 123.5


def test_rosout_source_is_preserved_for_cross_host_correlation():
    message = SimpleNamespace(
        stamp=SimpleNamespace(sec=20, nanosec=0),
        level=40,
        name="fleet_gateway",
        msg="Navigation lease timer gap 2.1s",
    )

    record = rosout_message_to_record(message, unit="control_rosout")

    assert record.unit == "control_rosout"


def test_systemd_journal_warning_is_normalized_for_incident_rules():
    record = journal_payload_to_record(
        {
            "__REALTIME_TIMESTAMP": "1784533923281337",
            "PRIORITY": "4",
            "SYSLOG_IDENTIFIER": "zenoh-bridge-ros2dds",
            "_SYSTEMD_USER_UNIT": "fleet-control-zenoh.service",
            "MESSAGE": "received NO reply for request",
        }
    )

    assert record is not None
    assert record.timestamp == 1784533923.281337
    assert record.severity == "WARNING"
    assert record.logger == "zenoh-bridge-ros2dds"
    assert record.unit == "fleet-control-zenoh.service"


def test_zenoh_ansi_byte_message_infers_embedded_warning_level():
    message = (
        "\x1b[2m2026-07-20T08:23:36Z\x1b[0m "
        "\x1b[33m WARN\x1b[0m received NO reply for request"
    )
    record = journal_payload_to_record(
        {
            "__REALTIME_TIMESTAMP": "1784535816128123",
            # Zenoh writes colored tracing output to stdout, so journald marks
            # it INFO even when the embedded application level is WARN.
            "PRIORITY": "6",
            "_COMM": "zenoh-bridge-ro",
            "_SYSTEMD_USER_UNIT": "fleet-control-zenoh.service",
            "MESSAGE": list(message.encode("utf-8")),
        }
    )

    assert record is not None
    assert record.severity == "WARNING"
    assert "\x1b" not in record.message
    assert "received NO reply" in record.message


def test_systemd_journal_record_requires_message_and_timestamp():
    assert journal_payload_to_record({"MESSAGE": "warning"}) is None
    assert journal_payload_to_record({"__REALTIME_TIMESTAMP": "1"}) is None
