"""Tests for shared utility functions."""

from __future__ import annotations

from bsgateway.core.utils import parse_jsonb_value, safe_json_loads


class TestSafeJsonLoads:
    def test_safe_json_loads_none_returns_empty_dict(self):
        assert safe_json_loads(None) == {}

    def test_safe_json_loads_dict_passthrough(self):
        d = {"key": "value"}
        assert safe_json_loads(d) is d

    def test_safe_json_loads_valid_json_string(self):
        result = safe_json_loads('{"a": 1, "b": 2}')
        assert result == {"a": 1, "b": 2}

    def test_safe_json_loads_invalid_json_returns_fallback(self):
        result = safe_json_loads("not-json")
        assert result == {}

    def test_safe_json_loads_custom_fallback(self):
        fallback = {"default": True}
        result = safe_json_loads("bad-json", fallback=fallback)
        assert result == {"default": True}


class TestParseJsonbValue:
    def test_parse_jsonb_value_json_string(self):
        result = parse_jsonb_value('{"key": "val"}')
        assert result == {"key": "val"}

    def test_parse_jsonb_value_invalid_json_returns_raw(self):
        result = parse_jsonb_value("not-json")
        assert result == "not-json"

    def test_parse_jsonb_value_non_string_passthrough(self):
        assert parse_jsonb_value(42) == 42
        assert parse_jsonb_value({"a": 1}) == {"a": 1}

    def test_parse_jsonb_value_list(self):
        result = parse_jsonb_value("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_parse_jsonb_value_none(self):
        assert parse_jsonb_value(None) is None
