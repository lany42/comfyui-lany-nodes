# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Context contracts tested with an isolated ComfyUI API double."""

import gc
import sys
import weakref
from importlib import import_module
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

import comfyui_lany_nodes.nodes

SOCKETS = (
    ("base_ctx", "CONTEXT", "LANY_CONTEXT"),
    ("model", "MODEL", "MODEL"),
    ("clip", "CLIP", "CLIP"),
    ("vae", "VAE", "VAE"),
    ("positive", "POSITIVE", "CONDITIONING"),
    ("negative", "NEGATIVE", "CONDITIONING"),
    ("latent", "LATENT", "LATENT"),
    ("images", "IMAGES", "IMAGE"),
    ("seed", "SEED", "INT"),
    ("width", "WIDTH", "INT"),
    ("height", "HEIGHT", "INT"),
    ("prompt_pos", "PROMPT_POS", "STRING"),
    ("prompt_neg", "PROMPT_NEG", "STRING"),
    ("model_names", "MODEL_NAMES", "STRING"),
    ("controlnet", "CONTROLNET", "CONTROL_NET"),
    ("upscale_model", "UPSCALE_MODEL", "UPSCALE_MODEL"),
    ("any_1", "ANY_1", "*"),
    ("any_2", "ANY_2", "*"),
    ("any_3", "ANY_3", "*"),
    ("any_4", "ANY_4", "*"),
)


@pytest.fixture
def context():
    def socket_type(io_type):
        def input_socket(id, *, optional=False, **options):
            return SimpleNamespace(id=id, io_type=io_type, optional=optional, **options)

        def output_socket(id, *, display_name=None, is_output_list=False):
            return SimpleNamespace(
                id=id,
                io_type=io_type,
                display_name=display_name or id,
                is_output_list=is_output_list,
            )

        return SimpleNamespace(
            io_type=io_type, Input=input_socket, Output=output_socket
        )

    api = ModuleType("comfy_api")
    latest = ModuleType("comfy_api.latest")
    latest.io = SimpleNamespace(
        ComfyNode=type("ComfyNode", (), {}),
        Schema=SimpleNamespace,
        Custom=socket_type,
        NodeOutput=lambda *values: SimpleNamespace(result=values),
        **{
            name: socket_type(io_type)
            for name, io_type in (
                ("Model", "MODEL"),
                ("Clip", "CLIP"),
                ("Vae", "VAE"),
                ("Conditioning", "CONDITIONING"),
                ("Latent", "LATENT"),
                ("Image", "IMAGE"),
                ("Int", "INT"),
                ("String", "STRING"),
                ("ControlNet", "CONTROL_NET"),
                ("UpscaleModel", "UPSCALE_MODEL"),
                ("AnyType", "*"),
            )
        },
    )
    api.latest = latest
    with (
        patch.dict(sys.modules, {"comfy_api": api, "comfy_api.latest": latest}),
        patch.dict(vars(comfyui_lany_nodes.nodes)),
    ):
        sys.modules.pop("comfyui_lany_nodes.nodes.context", None)
        yield import_module("comfyui_lany_nodes.nodes.context").Context


class ReferenceOnly:
    """Stand in for opaque host payloads without copying or truth testing."""

    def __bool__(self):
        raise AssertionError("Context must not test payload truthiness")

    def __copy__(self):
        raise AssertionError("Context must not copy payloads")

    def __deepcopy__(self, memo):
        raise AssertionError("Context must not deep-copy payloads")


def test_context_schema(context):
    schema = context.define_schema()
    assert schema.node_id == "LanyNodes_Context"
    assert schema.display_name == "Context"
    assert schema.category == "Lany Nodes"
    assert not getattr(schema, "is_input_list", False)
    assert not getattr(schema, "accept_all_inputs", False)
    assert not getattr(schema, "is_output_node", False)
    assert not getattr(schema, "has_intermediate_output", False)
    assert [(port.id, port.io_type) for port in schema.inputs] == [
        (name, io_type) for name, _, io_type in SOCKETS
    ]
    assert [(port.id, port.display_name, port.io_type) for port in schema.outputs] == [
        (name, name, io_type) for _, name, io_type in SOCKETS
    ]
    assert all(port.optional for port in schema.inputs)
    assert all(getattr(port, "default", None) is None for port in schema.inputs)
    for port in schema.inputs:
        assert bool(getattr(port, "force_input", False)) == (
            port.io_type in ("INT", "STRING")
        )
    assert all(not port.is_output_list for port in schema.outputs)


def test_empty_context_is_sparse(context):
    result = context.execute().result
    assert result == ({},) + (None,) * 19


def test_all_connected_values_are_forwarded_by_identity(context):
    values = {
        "model": ReferenceOnly(),
        "clip": ReferenceOnly(),
        "vae": ReferenceOnly(),
        "positive": [[ReferenceOnly(), {"pooled_output": ReferenceOnly()}]],
        "negative": [[ReferenceOnly(), {}]],
        "latent": {"samples": ReferenceOnly()},
        "images": ReferenceOnly(),
        "seed": 2**64 - 1,
        "width": 1024,
        "height": 768,
        "prompt_pos": "A mountain lake",
        "prompt_neg": "Haze",
        "model_names": "model.safetensors",
        "controlnet": ReferenceOnly(),
        "upscale_model": ReferenceOnly(),
        "any_1": ReferenceOnly(),
        "any_2": [ReferenceOnly()],
        "any_3": {"nested": [ReferenceOnly()]},
        "any_4": (ReferenceOnly(),),
    }
    # Prompt argument order must not change the output socket order.
    result = context.execute(**dict(reversed(values.items()))).result
    ctx = result[0]
    assert ctx is not values
    assert ctx.keys() == values.keys()
    for (name, _, _), output in zip(SOCKETS[1:], result[1:], strict=True):
        assert ctx[name] is values[name]
        assert output is values[name]


def test_inherits_sparse_base_and_preserves_extra_entries(context):
    base = {
        "model": ReferenceOnly(),
        "seed": 23,
        "any_4": {"nested": [ReferenceOnly()]},
        "future_field": ReferenceOnly(),
    }
    result = context.execute(base_ctx=base).result
    ctx = result[0]
    assert ctx is not base
    assert ctx.keys() == base.keys()
    for name, value in base.items():
        assert ctx[name] is value
    for (name, _, _), output in zip(SOCKETS[1:], result[1:], strict=True):
        assert output is base.get(name)
    assert "base_ctx" not in ctx


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("seed", 0),
        ("width", 0),
        ("height", 0),
        ("prompt_pos", ""),
        ("prompt_neg", ""),
        ("model_names", ""),
        ("any_1", False),
        ("any_2", []),
        ("any_3", {}),
        ("any_4", ()),
    ],
)
def test_falsey_values_override_inherited_values(context, name, value):
    inherited = ReferenceOnly()
    base = {name: inherited}
    result = context.execute(base_ctx=base, **{name: value}).result
    assert result[0][name] is value
    output_index = next(i for i, (key, _, _) in enumerate(SOCKETS) if key == name)
    assert result[output_index] is value
    assert base[name] is inherited


@pytest.mark.parametrize("name", [name for name, _, _ in SOCKETS])
def test_connected_none_raises_even_with_inherited_values(context, name):
    inputs = {
        "base_ctx": {key: ReferenceOnly() for key, _, _ in SOCKETS[1:]},
        name: None,
    }
    with pytest.raises(
        ValueError, match=rf"^Connected input '{name}' must not be None\.$"
    ):
        context.execute(**inputs)


@pytest.mark.parametrize(
    "base_ctx",
    [False, 0, "", [], (), [("seed", 1)]],
    ids=["bool", "int", "string", "list", "tuple", "pairs"],
)
def test_base_context_must_be_a_dictionary(context, base_ctx):
    with pytest.raises(TypeError, match=r"^base_ctx must be a dictionary\.$"):
        context.execute(base_ctx=base_ctx)


def test_chains_and_branches_preserve_references_without_mutating_bases(context):
    model = ReferenceOnly()
    images = ReferenceOnly()
    replacement_images = ReferenceOnly()
    first = context.execute(model=model, images=images, seed=17).result[0]
    second = context.execute(base_ctx=first, images=replacement_images).result[0]
    third = context.execute(base_ctx=second, seed=0).result[0]
    sibling = context.execute(base_ctx=first, prompt_pos="A lake").result[0]

    assert len({id(ctx) for ctx in (first, second, third, sibling)}) == 4
    assert all(ctx["model"] is model for ctx in (first, second, third, sibling))
    assert first["images"] is sibling["images"] is images
    assert second["images"] is third["images"] is replacement_images
    assert first["seed"] == second["seed"] == sibling["seed"] == 17
    assert third["seed"] == 0
    assert sibling["prompt_pos"] == "A lake"
    assert all("prompt_pos" not in ctx for ctx in (first, second, third))
    assert all("base_ctx" not in ctx for ctx in (first, second, third, sibling))


def test_executions_do_not_reuse_or_retain_context_dictionaries(context):
    model = ReferenceOnly()
    model_ref = weakref.ref(model)
    first = context.execute(model=model).result[0]
    second = context.execute(model=model).result[0]
    assert first is not second
    first["seed"] = 5
    assert "seed" not in second
    assert context.execute().result[0] == {}
    del model, first, second
    gc.collect()
    assert model_ref() is None
