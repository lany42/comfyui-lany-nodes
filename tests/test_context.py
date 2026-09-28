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
    ("scale", "SCALE", "FLOAT"),
    ("prompt_pos", "PROMPT_POS", "STRING"),
    ("prompt_neg", "PROMPT_NEG", "STRING"),
    ("model_names", "MODEL_NAMES", "STRING"),
    ("controlnet", "CONTROLNET", "CONTROL_NET"),
    ("upscale_model", "UPSCALE_MODEL", "UPSCALE_MODEL"),
    ("tile_plan", "TILE_PLAN", "*"),
    ("api_client", "API_CLIENT", "*"),
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
                ("Float", "FLOAT"),
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
    assert schema.is_input_list
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
            port.io_type in ("INT", "FLOAT", "STRING")
        )
    assert not schema.outputs[0].is_output_list
    assert all(port.is_output_list for port in schema.outputs[1:])


def test_empty_context_is_sparse(context):
    result = context.execute().result
    assert result == ({},) + ([None],) * (len(SOCKETS) - 1)


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
        "scale": 2.0 / 1.5,
        "tile_plan": ReferenceOnly(),
        "api_client": ReferenceOnly(),
    }
    # Prompt argument order must not change the output socket order.
    result = context.execute(
        **{name: [value] for name, value in reversed(values.items())}
    ).result
    ctx = result[0]
    assert ctx is not values
    assert ctx.keys() == values.keys()
    for (name, _, _), output in zip(SOCKETS[1:], result[1:], strict=True):
        assert ctx[name] is values[name]
        assert len(output) == 1
        assert output[0] is values[name]


def test_inherits_sparse_base_and_preserves_extra_entries(context):
    base = {
        "model": ReferenceOnly(),
        "positive": [[ReferenceOnly(), {}]],
        "seed": 23,
        "any_1": ["a list-valued payload", "not an execution list"],
        "any_4": {"nested": [ReferenceOnly()]},
        "scale": 2.0 / 1.5,
        "tile_plan": ReferenceOnly(),
        "api_client": ReferenceOnly(),
        "future_field": ReferenceOnly(),
    }
    result = context.execute(base_ctx=[base]).result
    ctx = result[0]
    assert ctx is not base
    assert ctx.keys() == base.keys()
    for name, value in base.items():
        assert ctx[name] is value
    for (name, _, _), output in zip(SOCKETS[1:], result[1:], strict=True):
        assert len(output) == 1
        assert output[0] is base.get(name)
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
        ("scale", 0.0),
        ("tile_plan", {}),
        ("api_client", False),
    ],
)
def test_falsey_values_override_inherited_values(context, name, value):
    inherited = ReferenceOnly()
    base = {name: inherited}
    result = context.execute(base_ctx=[base], **{name: [value]}).result
    assert result[0][name] is value
    output_index = next(i for i, (key, _, _) in enumerate(SOCKETS) if key == name)
    assert len(result[output_index]) == 1
    assert result[output_index][0] is value
    assert base[name] is inherited


@pytest.mark.parametrize("name", [name for name, _, _ in SOCKETS])
@pytest.mark.parametrize("values", [None, [None], [ReferenceOnly(), None]])
def test_connected_none_raises_even_with_inherited_values(context, name, values):
    inputs = {
        "base_ctx": [{key: ReferenceOnly() for key, _, _ in SOCKETS[1:]}],
        name: values,
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
        context.execute(base_ctx=[base_ctx])


@pytest.mark.parametrize("bases", [[], [{}, {}]])
def test_base_context_requires_exactly_one_dictionary(context, bases):
    with pytest.raises(
        ValueError, match=r"^base_ctx must contain exactly one context\.$"
    ):
        context.execute(base_ctx=bases)


def test_chains_and_branches_preserve_references_without_mutating_bases(context):
    model = ReferenceOnly()
    images = ReferenceOnly()
    replacement_images = ReferenceOnly()
    first = context.execute(model=[model], images=[images], seed=[17]).result[0]
    second = context.execute(base_ctx=[first], images=[replacement_images]).result[0]
    third = context.execute(base_ctx=[second], seed=[0]).result[0]
    sibling = context.execute(base_ctx=[first], prompt_pos=["A lake"]).result[0]

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
    first = context.execute(model=[model]).result[0]
    second = context.execute(model=[model]).result[0]
    assert first is not second
    first["seed"] = 5
    assert "seed" not in second
    assert context.execute().result[0] == {}
    del model, first, second
    gc.collect()
    assert model_ref() is None


def execute_with_lists(node, **inputs):
    """Model host list mapping and output merging; this is not a host integration.

    Inputs and returned outputs are ComfyUI execution lists. Schema flags decide
    whether to call once with whole lists or once per item, and whether each
    returned value is an execution list or a single (possibly list-valued) item.
    """
    schema = node.define_schema()
    if getattr(schema, "is_input_list", False):
        calls = [inputs]
    else:
        count = max((len(values) for values in inputs.values()), default=0)
        calls = (
            [
                {
                    name: values[min(index, len(values) - 1)]
                    for name, values in inputs.items()
                }
                for index in range(count)
            ]
            if count
            else [{}]
        )
    results = [node.execute(**call).result for call in calls]
    return {
        port.id: [
            value
            for result in results
            for value in (result[index] if port.is_output_list else [result[index]])
        ]
        for index, port in enumerate(schema.outputs)
    }


@pytest.mark.parametrize("name", [name for name, _, kind in SOCKETS if kind == "*"])
@pytest.mark.parametrize("responses", [[], ["one"], ["one", "two", "three"]])
def test_string_execution_list_does_not_repeat_other_outputs(context, name, responses):
    # BatchedChatCompletion publishes responses as a STRING execution list.
    shared = {key: ReferenceOnly() for key, _, _ in SOCKETS[1:] if key != name}
    outputs = execute_with_lists(
        context, **{key: [value] for key, value in shared.items()}, **{name: responses}
    )

    assert len(outputs["CONTEXT"]) == 1
    for key, output_name, _ in SOCKETS[1:]:
        if key == name:
            assert outputs[output_name] == responses
        else:
            assert len(outputs[output_name]) == 1
            assert outputs[output_name][0] is shared[key]


def test_unequal_execution_lists_preserve_lengths_order_and_payloads(context):
    conditioning = [[ReferenceOnly(), {}]]
    other_conditioning = [[ReferenceOnly(), {"pooled_output": ReferenceOnly()}]]
    image_batch = ReferenceOnly()
    other_image_batch = ReferenceOnly()
    list_payload = [ReferenceOnly(), ReferenceOnly()]
    streams = {
        "positive": [conditioning, other_conditioning],
        "images": [image_batch, other_image_batch],
        "seed": [17],
        "prompt_pos": ["first", "second", "third"],
        "any_1": ["repeated", "repeated", "last", "last"],
        "any_2": [list_payload],
        "any_3": [],
    }
    outputs = execute_with_lists(context, **streams)

    assert len(outputs["CONTEXT"]) == 1
    for name, output_name, _ in SOCKETS[1:]:
        expected = streams.get(name, [None])
        actual = outputs[output_name]
        assert len(actual) == len(expected)
        assert all(left is right for left, right in zip(actual, expected, strict=True))


@pytest.mark.parametrize(
    "replacement", [[], ["single"], ["new", "responses"], [[1, 2]]]
)
def test_execution_lists_survive_context_chains_and_branch_overrides(
    context, replacement
):
    model = ReferenceOnly()
    conditioning = [[ReferenceOnly(), {}]]
    list_payload = [ReferenceOnly(), ReferenceOnly()]
    scale = 2.0 / 1.5
    tile_plan = ReferenceOnly()
    api_client = ReferenceOnly()
    first = execute_with_lists(
        context,
        model=[model],
        positive=[conditioning],
        any_1=["one", "two", "three"],
        any_2=[list_payload],
        any_3=[],
        scale=[scale],
        tile_plan=[tile_plan],
        api_client=[api_client],
    )
    second = execute_with_lists(context, base_ctx=first["CONTEXT"], seed=[17])
    third = execute_with_lists(context, base_ctx=second["CONTEXT"], seed=[0])
    sibling = execute_with_lists(context, base_ctx=first["CONTEXT"], any_1=replacement)

    for outputs in (first, second, third, sibling):
        assert len(outputs["CONTEXT"]) == 1
        assert outputs["MODEL"] == [model]
        assert len(outputs["POSITIVE"]) == 1
        assert outputs["POSITIVE"][0] is conditioning
        assert len(outputs["ANY_2"]) == 1
        assert outputs["ANY_2"][0] is list_payload
        assert outputs["ANY_3"] == []
        assert outputs["ANY_4"] == [None]
        for name, expected in (
            ("SCALE", scale),
            ("TILE_PLAN", tile_plan),
            ("API_CLIENT", api_client),
        ):
            assert len(outputs[name]) == 1
            assert outputs[name][0] is expected
    for outputs in (first, second, third):
        assert outputs["ANY_1"] == ["one", "two", "three"]
        assert outputs["CONTEXT"][0]["any_1"] is first["CONTEXT"][0]["any_1"]
    assert sibling["ANY_1"] == replacement
    assert (
        len({id(outputs["CONTEXT"][0]) for outputs in (first, second, third, sibling)})
        == 4
    )
    assert first["SEED"] == sibling["SEED"] == [None]
    assert second["SEED"] == [17]
    assert third["SEED"] == [0]
