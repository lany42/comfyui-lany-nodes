# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""ImageComparer contracts with isolated API and preview-helper doubles."""

import sys
from importlib import import_module
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import comfyui_lany_nodes.nodes


@pytest.fixture
def comparer():
    def socket(id, **options):
        return SimpleNamespace(id=id, io_type="IMAGE", **options)

    preview = Mock()
    api = ModuleType("comfy_api")
    latest = ModuleType("comfy_api.latest")
    latest.io = SimpleNamespace(
        ComfyNode=type("ComfyNode", (), {}),
        Schema=SimpleNamespace,
        Image=SimpleNamespace(Input=socket, Type=object),
        NodeOutput=lambda *values, ui=None: SimpleNamespace(result=values, ui=ui),
    )
    latest.ui = SimpleNamespace(PreviewImage=preview)
    api.latest = latest
    with (
        patch.dict(sys.modules, {"comfy_api": api, "comfy_api.latest": latest}),
        patch.dict(vars(comfyui_lany_nodes.nodes)),
    ):
        sys.modules.pop("comfyui_lany_nodes.nodes.image_comparer", None)
        node = import_module("comfyui_lany_nodes.nodes.image_comparer").ImageComparer
        yield node, preview


def test_comparer_schema(comparer):
    node, _ = comparer
    schema = node.define_schema()
    assert schema.node_id == "LanyNodes_ImageComparer"
    assert schema.display_name == "ImageComparer"
    assert schema.category == "Lany Nodes"
    assert schema.is_output_node is True
    assert schema.outputs == []
    assert [(item.id, item.io_type) for item in schema.inputs] == [
        ("image_a", "IMAGE"),
        ("image_b", "IMAGE"),
    ]
    assert all(not getattr(item, "optional", False) for item in schema.inputs)


@pytest.mark.parametrize("count", [1, 3])
@pytest.mark.parametrize("b_dimensions", [(32, 48), (80, 24)])
def test_preview_batches_and_descriptors(comparer, count, b_dimensions):
    node, preview = comparer
    a = SimpleNamespace(shape=(count, 32, 48, 3))
    b = SimpleNamespace(shape=(count, *b_dimensions, 4))
    descriptors = [
        [
            {"filename": f"{side}_{i}.png", "subfolder": "", "type": "temp"}
            for i in range(count)
        ]
        for side in ("a", "b")
    ]
    preview.side_effect = [
        SimpleNamespace(as_dict=lambda: {"images": descriptors[0]}),
        SimpleNamespace(as_dict=lambda: {"images": descriptors[1]}),
    ]
    output = node.execute(a, b)
    assert output.result == ()
    assert output.ui == {"a_images": descriptors[0], "b_images": descriptors[1]}
    assert preview.call_count == 2
    assert preview.call_args_list[0].args == (a,)
    assert preview.call_args_list[1].args == (b,)
    assert all(call.kwargs == {} for call in preview.call_args_list)


@pytest.mark.parametrize(
    ("a_count", "b_count", "message"),
    [
        (0, 0, "nonempty"),
        (0, 1, "nonempty"),
        (1, 0, "nonempty"),
        (1, 2, "equal length"),
        (3, 1, "equal length"),
    ],
)
def test_bad_counts_fail_before_saving(comparer, a_count, b_count, message):
    node, preview = comparer
    with pytest.raises(ValueError, match=message):
        node.execute(
            SimpleNamespace(shape=(a_count, 32, 48, 3)),
            SimpleNamespace(shape=(b_count, 80, 24, 3)),
        )
    preview.assert_not_called()
