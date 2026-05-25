from litkit.oa_resolver import ALLOWED_OA_TIERS


def test_allowed_oa_tiers():
    assert "gold" in ALLOWED_OA_TIERS
    assert "green" in ALLOWED_OA_TIERS
    assert "bronze" in ALLOWED_OA_TIERS
    assert "hybrid" not in ALLOWED_OA_TIERS
    assert "closed" not in ALLOWED_OA_TIERS
