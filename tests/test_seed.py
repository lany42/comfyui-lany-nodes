# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Seed contracts tested with the shared ComfyUI API double."""

import pytest

from comfyui_lany_nodes.nodes.seed import Seed


# The maximum matches JavaScript's Number.MAX_SAFE_INTEGER in seed.js.
@pytest.mark.parametrize("seed", [0, 2**53 - 1])
def test_fixed_seeds_are_returned_unchanged(seed):
    result = Seed.execute(seed).result
    assert result == (seed,)
    assert type(result[0]) is int


@pytest.mark.parametrize("mode", [-1, -2, -3])
def test_unresolved_modes_require_the_browser(mode):
    with pytest.raises(
        NotImplementedError, match="require the ComfyUI browser controls"
    ):
        Seed.execute(mode)


def test_seed_rejects_booleans():
    with pytest.raises(TypeError, match="seed must be an integer"):
        Seed.execute(True)


@pytest.mark.parametrize("seed", [-4, 2**53])
def test_seed_rejects_out_of_range_values(seed):
    with pytest.raises(ValueError, match="seed must be between 0 and 9007199254740991"):
        Seed.execute(seed)
