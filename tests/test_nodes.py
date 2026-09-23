# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Node contracts tested with a small, isolated ComfyUI API double."""

import sys
from importlib import import_module
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

import comfyui_lany_nodes.nodes


@pytest.fixture
def scale_to():
    def socket(id, **options):
        return SimpleNamespace(id=id, **options)

    api = ModuleType("comfy_api")
    latest = ModuleType("comfy_api.latest")
    latest.io = SimpleNamespace(
        ComfyNode=type("ComfyNode", (), {}),
        Schema=SimpleNamespace,
        Int=SimpleNamespace(Input=socket, Output=socket),
        Float=SimpleNamespace(Input=socket),
        NodeOutput=lambda *values, ui=None: SimpleNamespace(result=values, ui=ui),
    )
    api.latest = latest
    with (
        patch.dict(sys.modules, {"comfy_api": api, "comfy_api.latest": latest}),
        patch.dict(vars(comfyui_lany_nodes.nodes)),
    ):
        sys.modules.pop("comfyui_lany_nodes.nodes.scaleto", None)
        yield import_module("comfyui_lany_nodes.nodes.scaleto").ScaleTo


def test_scale_to_schema(scale_to):
    schema = scale_to.define_schema()
    assert schema.node_id == "LanyNodes_ScaleTo"
    assert schema.display_name == "ScaleTo"
    assert schema.has_intermediate_output is True
    assert [item.id for item in schema.inputs] == ["width", "height", "scale"]
    scale = schema.inputs[2]
    assert scale.default == 1.0
    assert scale.min == 0.0
    assert scale.max == sys.float_info.max
    assert scale.step == scale.round == 0.01
    assert [item.id for item in schema.outputs] == ["target_width", "target_height"]


@pytest.mark.parametrize(
    ("width", "height", "scale", "expected"),
    [
        (1024, 768, 1.0, (1024, 768)),
        (1024, 768, 0.0, (0, 0)),
        (0, 768, 2.0, (0, 1536)),
        (101, 203, 1.25, (126, 254)),
        (7, 8, 0.2, (1, 2)),
        (101, 103, 0.5, (50, 52)),
        (25, 75, 2.18, (54, 164)),
        (2, 3, 4096.0, (8192, 12288)),
        (2, 3, 1e308, (2 * 10**308, 3 * 10**308)),
    ],
)
def test_scale_to_dimensions(scale_to, width, height, scale, expected):
    output = scale_to.execute(width, height, scale)
    assert output.result == expected
    assert all(type(value) is int for value in output.result)
    assert output.ui == {"dimensions": [f"({expected[0]}x{expected[1]})"]}


@pytest.mark.parametrize("scale", [-0.01, float("nan"), float("inf"), -float("inf")])
def test_scale_to_rejects_invalid_scale(scale_to, scale):
    with pytest.raises(ValueError, match="finite, nonnegative"):
        scale_to.execute(1024, 768, scale)
