"""Unit tests for Linux wireless status parsing."""

import pytest

from robot_agent.model import UNKNOWN_VALUE
from robot_agent.system_metrics import parse_wireless_status


def test_wireless_status_parses_interface_signal_and_full_quality() -> None:
    content = """
Inter-| sta-|   Quality        |   Discarded packets               | Missed
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon
 wlan0: 0000   70.  -40.  -256        0      0      0      0      0        0
"""
    result = parse_wireless_status(content)
    assert result.valid
    assert result.interface == "wlan0"
    assert result.signal_dbm == pytest.approx(-40.0)
    assert result.quality_percent == pytest.approx(100.0)


def test_wireless_quality_is_normalized_from_kernel_scale() -> None:
    content = "wlan0: 0000 35. -67. -256 0 0 0 0 0 0"
    result = parse_wireless_status(content)
    assert result.valid
    assert result.quality_percent == pytest.approx(50.0)


def test_missing_wireless_interface_is_unknown() -> None:
    result = parse_wireless_status("Inter-| sta-| Quality\n")
    assert not result.valid
    assert result.interface == ""
    assert result.signal_dbm == UNKNOWN_VALUE
    assert result.quality_percent == UNKNOWN_VALUE


def test_malformed_wireless_values_are_ignored() -> None:
    result = parse_wireless_status("wlan0: 0000 bad bad -256 0 0")
    assert not result.valid
