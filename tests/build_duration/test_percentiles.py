"""Unit tests for percentile calculations used in duration metrics."""
import pytest
from app.repositories.pipeline_repository import percentile


def test_percentile_empty():
    assert percentile([], 0.9) is None


def test_percentile_single_value():
    assert percentile([7], 0.9) == 7


def test_percentile_interpolates():
    assert percentile([10, 20, 30, 40], 0.9) == 37.0


def test_percentile_min_and_max():
    assert percentile([1, 2, 3, 4], 0) == 1
    assert percentile([1, 2, 3, 4], 1) == 4


def test_percentile_median():
    assert percentile([4, 1, 3, 2], 0.5) == 2.5
