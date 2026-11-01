import pytest

from cam3d.engine.profiles import FAST, HIGH, ULTRA, PROFILES, get_profile


def test_three_distinct_profiles():
    assert set(PROFILES) == {"fast", "high", "ultra"}
    # the profiles must map to genuinely different parameters
    assert FAST.densify_resolution_level > HIGH.densify_resolution_level > ULTRA.densify_resolution_level
    assert FAST.max_image_size < HIGH.max_image_size
    assert ULTRA.max_image_size == 0  # original resolution
    assert not FAST.refine_enabled and ULTRA.refine_enabled
    assert FAST.texture_max_size < HIGH.texture_max_size


def test_get_profile_errors():
    assert get_profile("FAST") is FAST
    with pytest.raises(ValueError):
        get_profile("insane")
