import os
import sys

import pytest

# Ensure project root is on sys.path for direct test execution
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from scripts.marketplace.context import _build_fortune_lookup
from scripts.marketplace.purchase import _compute_purchase_threshold


def test_compute_purchase_threshold_percent_margin():
    fortune_line = {
        "margin_type": "percent",
        "margin_value": 20,
        "median_price_7d": 1000,
    }
    assert _compute_purchase_threshold(fortune_line) == 800


def test_compute_purchase_threshold_absolute_margin():
    fortune_line = {"margin_type": "absolute", "margin_value": 1500}
    assert _compute_purchase_threshold(fortune_line) == 1500


def test_compute_purchase_threshold_negative_clamped():
    fortune_line = {"margin_type": "absolute", "margin_value": -50}
    assert _compute_purchase_threshold(fortune_line) == 0


def test_compute_purchase_threshold_invalid_configuration():
    fortune_line = {"margin_type": "unknown", "margin_value": 10}
    assert _compute_purchase_threshold(fortune_line) is None


@pytest.mark.parametrize(
    "entries, expected_keys",
    [
        (
            [
                {"slug": "Bois", "qty": "x10", "value": 100},
                {"slug": "bois", "qty": "x1", "value": 25},
                {"slug": "Pierre", "qty": "x100", "value": 250},
            ],
            {"bois": {"x10", "x1"}, "pierre": {"x100"}},
        ),
        (
            [
                {"slug": "  Herbe  ", "qty": "x1", "value": 5},
                {"slug": "", "qty": "x10", "value": 50},
                {"slug": "Champ", "qty": "", "value": 0},
            ],
            {"herbe": {"x1"}},
        ),
    ],
)
def test_build_fortune_lookup(entries, expected_keys):
    lookup = _build_fortune_lookup(entries)
    assert set(lookup.keys()) == set(expected_keys.keys())
    for slug, expected_qtys in expected_keys.items():
        assert set(lookup[slug].keys()) == expected_qtys

