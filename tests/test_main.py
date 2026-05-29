"""Unit tests for main.py helpers."""
import pytest
from athenax.main import _extract_json


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
