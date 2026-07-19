from types import SimpleNamespace

from fleet_gateway.log_mlops_node import rosout_message_to_record


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
