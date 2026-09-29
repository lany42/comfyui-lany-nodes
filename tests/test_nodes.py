# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""ScaleTo and ScaleOf contracts tested with the shared ComfyUI API double."""

import sys

import pytest

from comfyui_lany_nodes.nodes.scaleof import ScaleOf
from comfyui_lany_nodes.nodes.scaleto import ScaleTo


@pytest.mark.parametrize(
    ("width", "height", "scale", "expected"),
    [
        # Exact halfway values round to even: 50.5 -> 50 and 51.5 -> 52.
        (101, 103, 0.5, (50, 52)),
        # A linked ScaleOf ratio passes through unrounded.
        (3, 6, 1.3333333333333333, (4, 8)),
        # Decimal scales round as written: binary 25 * 2.18 would give 55.
        (25, 75, 2.18, (54, 164)),
        # Integer arithmetic avoids float overflow at extreme scales.
        (2, 3, 1e308, (2 * 10**308, 3 * 10**308)),
    ],
)
def test_scale_to_dimensions(width, height, scale, expected):
    output = ScaleTo.execute(width, height, scale)
    assert output.result == (*expected, scale)
    assert all(type(value) is int for value in output.result[:2])
    assert output.ui == {"dimensions": [f"({expected[0]}x{expected[1]})"]}


@pytest.mark.parametrize("scale", [-0.01, float("nan")])
def test_scale_to_rejects_invalid_scale(scale):
    with pytest.raises(ValueError, match="finite, nonnegative"):
        ScaleTo.execute(1024, 768, scale)


def test_scale_of_returns_the_unrounded_ratio():
    output = ScaleOf.execute(-2.0, 1.5)
    assert output.result == (-1.3333333333333333,)
    assert type(output.result[0]) is float


def test_scale_of_rejects_zero_source():
    with pytest.raises(ValueError, match="source must be nonzero"):
        ScaleOf.execute(2.0, 0.0)


@pytest.mark.parametrize(
    ("name", "value"), [("target", float("nan")), ("source", float("inf"))]
)
def test_scale_of_rejects_nonfinite_inputs(name, value):
    with pytest.raises(ValueError, match="target and source must be finite"):
        ScaleOf.execute(**{name: value})


def test_scale_of_rejects_nonfinite_result():
    with pytest.raises(ValueError, match="scale must be a finite"):
        ScaleOf.execute(sys.float_info.max, 0.5)
