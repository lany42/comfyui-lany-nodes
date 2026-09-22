# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Seed contracts tested with an isolated ComfyUI API double."""

import sys
from importlib import import_module
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

import comfyui_lany_nodes


@pytest.fixture
def seed_node():
    def socket(id, **options):
        return SimpleNamespace(id=id, io_type="INT", **options)

    api = ModuleType("comfy_api")
    latest = ModuleType("comfy_api.latest")
    latest.io = SimpleNamespace(
        ComfyNode=type("ComfyNode", (), {}),
        Schema=SimpleNamespace,
        Int=SimpleNamespace(Input=socket, Output=socket),
        NodeOutput=lambda *values: SimpleNamespace(result=values),
    )
    api.latest = latest
    with (
        patch.dict(sys.modules, {"comfy_api": api, "comfy_api.latest": latest}),
        patch.dict(vars(comfyui_lany_nodes)),
    ):
        sys.modules.pop("comfyui_lany_nodes.seed", None)
        yield import_module("comfyui_lany_nodes.seed").Seed


def test_seed_schema(seed_node):
    schema = seed_node.define_schema()
    assert schema.node_id == "LanyNodes_Seed"
    assert schema.display_name == "Seed"
    assert schema.category == "Lany Nodes"
    assert len(schema.inputs) == len(schema.outputs) == 1
    seed = schema.inputs[0]
    assert (seed.id, seed.io_type) == ("seed", "INT")
    assert seed.default == -1
    assert seed.min == -3
    assert seed.max == 2**53 - 1
    assert seed.step == 1
    assert seed.socketless is True
    assert seed.control_after_generate is False
    assert (schema.outputs[0].id, schema.outputs[0].io_type) == ("SEED", "INT")
    assert not getattr(schema, "hidden", [])
    assert not getattr(schema, "not_idempotent", False)
    assert not getattr(schema, "is_output_node", False)
    assert not getattr(schema, "has_intermediate_output", False)


@pytest.mark.parametrize("seed", [0, 1, 42, 2**32, 2**53 - 1])
def test_fixed_seeds_are_returned_unchanged(seed_node, seed):
    for _ in range(2):
        result = seed_node.execute(seed).result
        assert result == (seed,)
        assert type(result[0]) is int


@pytest.mark.parametrize("mode", [-1, -2, -3])
def test_unresolved_modes_require_the_browser(seed_node, mode):
    with pytest.raises(
        NotImplementedError, match="require the ComfyUI browser controls"
    ):
        seed_node.execute(mode)


@pytest.mark.parametrize("seed", [True, False, None, "42", 1.0, -1.0, float("nan")])
def test_seed_rejects_non_integer_values(seed_node, seed):
    with pytest.raises(TypeError, match="seed must be an integer"):
        seed_node.execute(seed)


@pytest.mark.parametrize("seed", [-4, -100, 2**53, 2**64 - 1])
def test_seed_rejects_out_of_range_values(seed_node, seed):
    with pytest.raises(ValueError, match="seed must be between 0 and 9007199254740991"):
        seed_node.execute(seed)
