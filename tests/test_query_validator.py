from litkit.query_validator import validate_openalex, has_blocking_errors, validate_all


def test_quoted_acronym_counts_as_token():
    q = '("LLM" OR "large language model") AND ("code review" OR "pull request")'
    r = validate_openalex(q)
    assert not r.has_errors, r.errors


def test_empty_and_group_still_errors():
    q = '("LLM") AND () AND (review)'
    r = validate_openalex(q)
    assert r.has_errors
