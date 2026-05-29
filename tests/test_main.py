"""Unit tests for main.py helpers."""
import pytest
from athenax.main import _extract_json


class TestExtractJson:
    def test_plain_array(self):
        assert _extract_json('[{"a":1}]') == [{"a": 1}]

    def test_markdown_fenced(self):
        text = '```json\n[{"name":"foo"}]\n```'
        assert _extract_json(text) == [{"name": "foo"}]

    def test_prose_prefix(self):
        text = 'Here are the results:\n[{"x": 2}]'
        assert _extract_json(text) == [{"x": 2}]

    def test_empty_returns_list(self):
        assert _extract_json("No JSON here.") == []

    def test_nested_objects(self):
        text = '[{"a": [1,2,3], "b": {"c": true}}]'
        result = _extract_json(text)
        assert result[0]["a"] == [1, 2, 3]

    def test_malformed_returns_empty(self):
        assert _extract_json("[{broken json}]") == []
