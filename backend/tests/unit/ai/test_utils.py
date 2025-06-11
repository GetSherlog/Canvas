from backend.ai.utils import _truncate_output

DEFAULT_LIMIT = 100 # Use a smaller default limit for easier testing
TRUNCATION_INDICATOR_PREFIX = "\n\n...[output truncated"

# Test cases for _truncate_output
def test_truncate_short_content():
    content = "This is short content."
    assert _truncate_output(content, limit=DEFAULT_LIMIT) == content

def test_truncate_long_content():
    content = "This is very long content that definitely exceeds the limit of one hundred characters set for this specific test case."
    expected_truncated = content[:DEFAULT_LIMIT]
    expected_suffix_start = TRUNCATION_INDICATOR_PREFIX
    truncated_result = _truncate_output(content, limit=DEFAULT_LIMIT)
    assert truncated_result.startswith(expected_truncated)
    assert expected_suffix_start in truncated_result
    assert f"original length {len(content)}" in truncated_result
    assert len(truncated_result) > DEFAULT_LIMIT # Indicator adds length

def test_truncate_exact_limit_content():
    content = "a" * DEFAULT_LIMIT
    assert _truncate_output(content, limit=DEFAULT_LIMIT) == content

def test_truncate_empty_string():
    content = ""
    assert _truncate_output(content, limit=DEFAULT_LIMIT) == content

def test_truncate_non_string_input():
    content_list = [1, 2, 3]
    content_int = 12345
    content_none = None
    assert _truncate_output(content_list, limit=DEFAULT_LIMIT) == content_list
    assert _truncate_output(content_int, limit=DEFAULT_LIMIT) == content_int
    assert _truncate_output(content_none, limit=DEFAULT_LIMIT) is None

def test_truncate_custom_limit():
    content = "This content should be truncated at 10 chars."
    custom_limit = 10
    expected_truncated = content[:custom_limit]
    expected_suffix_start = TRUNCATION_INDICATOR_PREFIX
    truncated_result = _truncate_output(content, limit=custom_limit)
    assert truncated_result.startswith(expected_truncated)
    assert expected_suffix_start in truncated_result
    assert f"original length {len(content)}" in truncated_result
    assert len(truncated_result) > custom_limit 