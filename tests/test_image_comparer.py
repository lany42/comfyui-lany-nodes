# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""ImageComparer contracts with the shared API double and a preview-helper double."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from comfyui_lany_nodes.nodes import image_comparer
from comfyui_lany_nodes.nodes.image_comparer import ImageComparer


@pytest.fixture
def preview(monkeypatch):
    preview = Mock()
    monkeypatch.setattr(image_comparer.ui, "PreviewImage", preview)
    return preview


def test_preview_batches_and_descriptors(preview):
    # Only batch lengths must match; image_comparer.js fits differing sizes.
    a = SimpleNamespace(shape=(2, 32, 48, 3))
    b = SimpleNamespace(shape=(2, 80, 24, 4))
    descriptors = [
        [
            {"filename": f"{side}_{i}.png", "subfolder": "", "type": "temp"}
            for i in range(2)
        ]
        for side in ("a", "b")
    ]
    preview.side_effect = [
        SimpleNamespace(as_dict=lambda: {"images": descriptors[0]}),
        SimpleNamespace(as_dict=lambda: {"images": descriptors[1]}),
    ]
    output = ImageComparer.execute(a, b)
    assert output.result == ()
    assert output.ui == {"a_images": descriptors[0], "b_images": descriptors[1]}
    assert [call.args for call in preview.call_args_list] == [(a,), (b,)]


@pytest.mark.parametrize(
    ("a_count", "b_count", "message"),
    [
        (0, 1, "nonempty"),
        (1, 0, "nonempty"),
        (1, 2, "equal length"),
        (2, 1, "equal length"),
    ],
)
def test_bad_counts_fail_before_saving(preview, a_count, b_count, message):
    with pytest.raises(ValueError, match=message):
        ImageComparer.execute(
            SimpleNamespace(shape=(a_count, 32, 48, 3)),
            SimpleNamespace(shape=(b_count, 80, 24, 3)),
        )
    preview.assert_not_called()
