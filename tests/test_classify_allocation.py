"""Allocation invariant: every cent lands in exactly one category."""

from __future__ import annotations

import pytest

from finance.classify.allocation import (
    Allocation,
    AllocationError,
    even_split,
    to_splits,
    validate_allocations,
)


def test_single_allocation_covers_whole_amount():
    validate_allocations([Allocation("expenses:food", "300.00")], "-300.00")


def test_split_must_sum_exactly():
    allocs = [Allocation("expenses:food", "200.00"), Allocation("expenses:fun", "100.00")]
    validate_allocations(allocs, "-300.00")


def test_split_that_does_not_sum_is_rejected():
    allocs = [Allocation("expenses:food", "200.00"), Allocation("expenses:fun", "99.99")]
    with pytest.raises(AllocationError):
        validate_allocations(allocs, "-300.00")


def test_negative_or_zero_allocation_rejected():
    with pytest.raises(AllocationError):
        validate_allocations([Allocation("expenses:food", "0.00")], "0.00")


def test_works_for_positive_income_amount():
    validate_allocations([Allocation("income:salary", "5000.00")], "5000.00")


def test_even_split_absorbs_rounding_remainder():
    parts = even_split(["a", "b", "c"], "-100.00")
    assert [p.amount for p in parts] == ["33.34", "33.33", "33.33"]
    validate_allocations(parts, "-100.00")  # still sums exactly


def test_to_splits_bridges_to_model():
    splits = to_splits([Allocation("expenses:food", "200.00", notes="lunch")])
    assert splits[0].account == "expenses:food"
    assert splits[0].amount == "200.00"
    assert splits[0].notes == "lunch"
