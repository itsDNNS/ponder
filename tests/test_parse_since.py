"""Tests for _parse_since duration/ID parser."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from daemon import _parse_since


class TestParseSinceDurations:
    """Duration strings like '24h', '7d', '1w', '2m'."""

    @patch("daemon.datetime")
    def test_hours(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 3, 31, 12, 0, 0)
        since_id, cutoff = _parse_since("24h")
        assert since_id == 0
        assert cutoff == "2026-03-30 12:00:00"

    @patch("daemon.datetime")
    def test_days(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 3, 31, 12, 0, 0)
        since_id, cutoff = _parse_since("7d")
        assert since_id == 0
        assert cutoff == "2026-03-24 12:00:00"

    @patch("daemon.datetime")
    def test_weeks(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 3, 31, 12, 0, 0)
        since_id, cutoff = _parse_since("1w")
        assert since_id == 0
        assert cutoff == "2026-03-24 12:00:00"

    @patch("daemon.datetime")
    def test_months(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 3, 31, 12, 0, 0)
        since_id, cutoff = _parse_since("2m")
        assert since_id == 0
        assert cutoff == "2026-01-30 12:00:00"

    @patch("daemon.datetime")
    def test_whitespace_between_number_and_unit(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 3, 31, 12, 0, 0)
        since_id, cutoff = _parse_since("24 h")
        assert since_id == 0
        assert cutoff == "2026-03-30 12:00:00"

    @patch("daemon.datetime")
    def test_leading_trailing_whitespace(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 3, 31, 12, 0, 0)
        since_id, cutoff = _parse_since("  7d  ")
        assert since_id == 0
        assert cutoff == "2026-03-24 12:00:00"


class TestParseSinceIntegerIDs:
    """Plain integer event IDs."""

    def test_positive_integer(self):
        assert _parse_since("42") == (42, None)

    def test_zero(self):
        assert _parse_since("0") == (0, None)

    def test_large_integer(self):
        assert _parse_since("999999") == (999999, None)

    def test_integer_with_whitespace(self):
        assert _parse_since("  100  ") == (100, None)


class TestParseSinceInvalid:
    """Invalid or empty inputs return the safe default."""

    def test_none(self):
        assert _parse_since(None) == (0, None)

    def test_empty_string(self):
        assert _parse_since("") == (0, None)

    def test_whitespace_only(self):
        assert _parse_since("   ") == (0, None)

    def test_garbage(self):
        assert _parse_since("abc") == (0, None)

    def test_unit_without_number(self):
        assert _parse_since("h") == (0, None)

    def test_negative_number_with_unit(self):
        assert _parse_since("-5h") == (0, None)

    def test_float_with_unit(self):
        assert _parse_since("1.5d") == (0, None)

    def test_unknown_unit(self):
        assert _parse_since("10x") == (0, None)

    def test_redos_payload(self):
        """The input that triggered CodeQL alert #2 must not hang."""
        assert _parse_since("9" * 100_000) == (0, None)

    def test_large_duration_number_with_unit_falls_back_safely(self):
        assert _parse_since(("9" * 100_000) + "h") == (0, None)
