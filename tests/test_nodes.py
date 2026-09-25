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
def scale_nodes():
    def socket_type(io_type):
        def socket(id, **options):
            return SimpleNamespace(id=id, io_type=io_type, **options)

        return SimpleNamespace(Input=socket, Output=socket)

    api = ModuleType("comfy_api")
    latest = ModuleType("comfy_api.latest")
    latest.io = SimpleNamespace(
        ComfyNode=type("ComfyNode", (), {}),
        Schema=SimpleNamespace,
        Int=socket_type("INT"),
        Float=socket_type("FLOAT"),
        NodeOutput=lambda *values, ui=None: SimpleNamespace(result=values, ui=ui),
    )
    api.latest = latest
    with (
        patch.dict(sys.modules, {"comfy_api": api, "comfy_api.latest": latest}),
        patch.dict(vars(comfyui_lany_nodes.nodes)),
    ):
        sys.modules.pop("comfyui_lany_nodes.nodes.scaleto", None)
        sys.modules.pop("comfyui_lany_nodes.nodes.scaleof", None)
        yield SimpleNamespace(
            ScaleTo=import_module("comfyui_lany_nodes.nodes.scaleto").ScaleTo,
            ScaleOf=import_module("comfyui_lany_nodes.nodes.scaleof").ScaleOf,
        )


@pytest.fixture
def scale_to(scale_nodes):
    return scale_nodes.ScaleTo


@pytest.fixture
def scale_of(scale_nodes):
    return scale_nodes.ScaleOf


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
    assert [(item.id, item.io_type) for item in schema.outputs] == [
        ("target_width", "INT"),
        ("target_height", "INT"),
        ("scale", "FLOAT"),
    ]


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
        (3, 6, 1.3333333333333333, (4, 8)),
        (2, 3, 4096.0, (8192, 12288)),
        (2, 3, 1e308, (2 * 10**308, 3 * 10**308)),
    ],
)
def test_scale_to_dimensions(scale_to, width, height, scale, expected):
    output = scale_to.execute(width, height, scale)
    assert output.result == (*expected, scale)
    assert all(type(value) is int for value in output.result[:2])
    assert type(output.result[2]) is float
    assert output.ui == {"dimensions": [f"({expected[0]}x{expected[1]})"]}


@pytest.mark.parametrize("scale", [-0.01, float("nan"), float("inf"), -float("inf")])
def test_scale_to_rejects_invalid_scale(scale_to, scale):
    with pytest.raises(ValueError, match="finite, nonnegative"):
        scale_to.execute(1024, 768, scale)


def test_scale_of_schema(scale_of):
    schema = scale_of.define_schema()
    assert schema.node_id == "LanyNodes_ScaleOf"
    assert schema.display_name == "ScaleOf"
    assert schema.category == "Lany Nodes"
    assert [(item.id, item.io_type) for item in schema.inputs] == [
        ("target", "FLOAT"),
        ("source", "FLOAT"),
    ]
    for item in schema.inputs:
        assert item.default == 1.0
        assert item.min == -sys.float_info.max
        assert item.max == sys.float_info.max
        assert item.round is False
        assert not getattr(item, "force_input", False)
        assert not getattr(item, "socketless", False)
    assert [(item.id, item.io_type) for item in schema.outputs] == [("scale", "FLOAT")]


@pytest.mark.parametrize(
    ("target", "source", "expected"),
    [
        (2.0, 1.5, 1.3333333333333333),
        (1.5, 1.5, 1.0),
        (1.5, 2.0, 0.75),
        (4.0, 1.0, 4.0),
        (0.0, 1.5, 0.0),
        (-2.0, 1.5, -1.3333333333333333),
        (2.0, -1.5, -1.3333333333333333),
        (0.1234567890123456, 1.0, 0.1234567890123456),
        (sys.float_info.max, sys.float_info.max, 1.0),
    ],
)
def test_scale_of_ratio(scale_of, target, source, expected):
    output = scale_of.execute(target, source)
    assert output.result == (expected,)
    assert type(output.result[0]) is float


def test_scale_of_defaults(scale_of):
    assert scale_of.execute().result == (1.0,)


@pytest.mark.parametrize("source", [0.0, -0.0])
def test_scale_of_rejects_zero_source(scale_of, source):
    with pytest.raises(ValueError, match="source must be nonzero"):
        scale_of.execute(2.0, source)


@pytest.mark.parametrize("name", ["target", "source"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_scale_of_rejects_nonfinite_inputs(scale_of, name, value):
    with pytest.raises(ValueError, match="target and source must be finite"):
        scale_of.execute(**{name: value})


def test_scale_of_rejects_nonfinite_result(scale_of):
    with pytest.raises(ValueError, match="scale must be a finite"):
        scale_of.execute(sys.float_info.max, 0.5)


def test_scale_of_composes_scale_to_stages(scale_to, scale_of):
    source = scale_to.execute(1024, 768, 1.5)
    target = scale_to.execute(1024, 768, 2.0)
    assert source.result == (1536, 1152, 1.5)
    assert target.result == (2048, 1536, 2.0)
    relative = scale_of.execute(target=target.result[2], source=source.result[2])
    assert relative.result == (1.3333333333333333,)
