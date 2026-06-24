"""Tests for WAC category definitions and folder creation."""
from bot import WAC_CATEGORIES


def test_wac_categories_has_eight_items():
    """WAC defines exactly 8 document categories."""
    assert len(WAC_CATEGORIES) == 8


def test_wac_categories_follow_naming_convention():
    """Each category starts with a two-digit code and dash."""
    for cat in WAC_CATEGORIES:
        assert cat[0:2].isdigit(), f"Expected leading digits: {cat}"
        assert cat[2:5] == " - ", f"Expected ' - ' separator: {cat}"


def test_wac_categories_are_unique():
    """No duplicate category names."""
    assert len(WAC_CATEGORIES) == len(set(WAC_CATEGORIES))


def test_wac_categories_are_ordered():
    """Categories are ordered 01 through 08."""
    for i, cat in enumerate(WAC_CATEGORIES, start=1):
        expected_prefix = f"{i:02d}"
        assert cat.startswith(expected_prefix), (
            f"Expected category {i:02d}, got {cat}"
        )


def test_wac_categories_include_administrator_training():
    """Category 08 is Administrator Training (provider-only requirement)."""
    cat_08 = WAC_CATEGORIES[7]
    assert "08" in cat_08
    assert "Administrator" in cat_08
