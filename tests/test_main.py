"""Unit tests for main.py helpers."""
import pytest
from unittest.mock import MagicMock

from athenax.main import (
    _extract_json,
    _register_schedule_job,
    _validate_schedule_time,
)


class TestExtractJson:
    def test_plain_array(self):
        assert _extract_json('[{"a":1}]') == [{"a": 1}]

    def test_markdown_fenced(self):
        assert _extract_json('```json\n[{"name":"foo"}]\n```') == [{"name": "foo"}]

    def test_markdown_no_lang(self):
        assert _extract_json('```\n[{"x":1}]\n```') == [{"x": 1}]

    def test_prose_prefix(self):
        assert _extract_json('Here are the results:\n[{"x": 2}]') == [{"x": 2}]

    def test_empty_input_returns_list(self):
        assert _extract_json("") == []

    def test_no_array_returns_empty(self):
        assert _extract_json("No JSON here.") == []

    def test_nested_objects(self):
        result = _extract_json('[{"a": [1,2,3], "b": {"c": true}}]')
        assert result[0]["a"] == [1, 2, 3]
        assert result[0]["b"]["c"] is True

    def test_malformed_json_returns_empty(self):
        assert _extract_json("[{broken json}]") == []

    def test_multiple_arrays_takes_first(self):
        result = _extract_json('[{"first": true}] and [{"second": true}]')
        assert result[0]["first"] is True

    def test_unicode_content(self):
        result = _extract_json('[{"name": "Nouns DAO 🟡"}]')
        assert "🟡" in result[0]["name"]

    def test_deeply_nested_brackets(self):
        raw = '[{"tags": ["CC0", "DAO"], "meta": {"score": 90}}]'
        result = _extract_json(raw)
        assert result[0]["tags"] == ["CC0", "DAO"]
        assert result[0]["meta"]["score"] == 90

    def test_trailing_text_after_array(self):
        result = _extract_json('[{"a": 1}] some trailing text')
        assert result == [{"a": 1}]


class TestValidateScheduleTime:
    def test_valid_midnight(self):
        assert _validate_schedule_time("00:00") == "00:00"

    def test_valid_afternoon(self):
        assert _validate_schedule_time("09:00") == "09:00"

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="HH:MM"):
            _validate_schedule_time("9:00")

    def test_invalid_hour(self):
        with pytest.raises(ValueError, match="hour"):
            _validate_schedule_time("24:00")


class TestRegisterScheduleJob:
    def test_weekly_summary(self):
        sched = MagicMock()
        monday = MagicMock()
        sched.every.return_value.monday = monday
        summary = _register_schedule_job(
            sched, day="monday", time_utc="09:00", hours=None,
        )
        assert summary == "every Monday at 09:00 UTC"
        monday.at.assert_called_once_with("09:00")
        monday.at.return_value.do.assert_called_once()

    def test_interval_summary(self):
        sched = MagicMock()
        every = sched.every.return_value
        summary = _register_schedule_job(
            sched, day=None, time_utc="09:00", hours=8,
        )
        assert summary == "every 8 hours"
        sched.every.assert_called_once_with(8)
        every.hours.do.assert_called_once()

    def test_invalid_day(self):
        sched = MagicMock()
        with pytest.raises(ValueError, match="Invalid day"):
            _register_schedule_job(
                sched, day="notaday", time_utc="09:00", hours=None,
            )
