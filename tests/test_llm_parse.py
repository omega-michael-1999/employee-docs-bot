"""Tests for LLM response JSON parsing."""
from bot import parse_json_from_llm


class TestParseJsonFromLlm:
    """parse_json_from_llm handles various LLM response formats."""

    def test_bare_json(self):
        """Bare JSON object is parsed directly."""
        result = parse_json_from_llm('{"employee": "Fatou Manneh", "category": "04 - CPR & First Aid"}')
        assert result is not None
        assert result["employee"] == "Fatou Manneh"

    def test_json_in_fences(self):
        """JSON inside ```json fences is extracted."""
        content = """Here's my analysis:
```json
{"employee": "Fatou Manneh", "category": "04 - CPR & First Aid"}
```
Hope that helps!"""
        result = parse_json_from_llm(content)
        assert result is not None
        assert result["employee"] == "Fatou Manneh"

    def test_json_in_plain_fences(self):
        """JSON inside plain ``` fences is extracted."""
        content = """Result:
```
{"employee": "Sandra Namwase", "category": "08 - Administrator Training"}
```"""
        result = parse_json_from_llm(content)
        assert result is not None
        assert result["employee"] == "Sandra Namwase"

    def test_nested_json_object(self):
        """JSON with nested objects can be parsed."""
        content = '{"employee": "Fatou Manneh", "category": "03 - Health Screening", "meta": {"test": "tb"}}'
        result = parse_json_from_llm(content)
        assert result is not None
        assert result["employee"] == "Fatou Manneh"
        assert result["meta"]["test"] == "tb"

    def test_invalid_json_returns_none(self):
        """Malformed JSON returns None."""
        result = parse_json_from_llm("I think this is a CPR card for Fatou Manneh")
        assert result is None

    def test_empty_string_returns_none(self):
        """Empty input returns None."""
        assert parse_json_from_llm("") is None
        assert parse_json_from_llm("   ") is None
