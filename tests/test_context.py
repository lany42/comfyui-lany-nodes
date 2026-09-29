# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Context contracts tested with the shared ComfyUI API double."""

import pytest

from comfyui_lany_nodes.nodes.context import Context

# test_extension.py pins the socket order; these tests follow it.
FIELDS = [port.id for port in Context.define_schema().inputs[1:]]


class ReferenceOnly:
    """Stand in for opaque host payloads without copying or truth testing."""

    def __bool__(self):
        raise AssertionError("Context must not test payload truthiness")

    def __copy__(self):
        raise AssertionError("Context must not copy payloads")

    def __deepcopy__(self, memo):
        raise AssertionError("Context must not deep-copy payloads")


def test_all_connected_values_are_forwarded_by_identity():
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
    result = Context.execute(
        **{name: [value] for name, value in reversed(values.items())}
    ).result
    ctx = result[0]
    assert ctx is not values
    assert ctx.keys() == values.keys()
    for name, output in zip(FIELDS, result[1:], strict=True):
        assert ctx[name] is values[name]
        assert len(output) == 1
        assert output[0] is values[name]


def test_inherits_sparse_base_and_preserves_extra_entries():
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
    result = Context.execute(base_ctx=[base]).result
    ctx = result[0]
    assert ctx is not base
    assert ctx.keys() == base.keys()
    for name, value in base.items():
        assert ctx[name] is value
    for name, output in zip(FIELDS, result[1:], strict=True):
        assert len(output) == 1
        assert output[0] is base.get(name)


@pytest.mark.parametrize(
    ("name", "value"), [("seed", 0), ("prompt_pos", ""), ("any_2", [])]
)
def test_falsey_values_override_inherited_values(name, value):
    inherited = ReferenceOnly()
    base = {name: inherited}
    result = Context.execute(base_ctx=[base], **{name: [value]}).result
    assert result[0][name] is value
    output = result[FIELDS.index(name) + 1]
    assert len(output) == 1
    assert output[0] is value
    assert base[name] is inherited


@pytest.mark.parametrize("values", [None, [None], [ReferenceOnly(), None]])
def test_connected_none_raises_even_with_inherited_values(values):
    inputs = {
        "base_ctx": [{key: ReferenceOnly() for key in FIELDS}],
        "images": values,
    }
    with pytest.raises(
        ValueError, match=r"^Connected input 'images' must not be None\.$"
    ):
        Context.execute(**inputs)


def test_base_context_must_be_a_dictionary():
    # dict() would silently accept key/value pairs from an Any socket.
    with pytest.raises(TypeError, match=r"^base_ctx must be a dictionary\.$"):
        Context.execute(base_ctx=[[("seed", 1)]])


@pytest.mark.parametrize("bases", [[], [{}, {}]])
def test_base_context_requires_exactly_one_dictionary(bases):
    with pytest.raises(
        ValueError, match=r"^base_ctx must contain exactly one context\.$"
    ):
        Context.execute(base_ctx=bases)


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
            for value in (
                result[index]
                if getattr(port, "is_output_list", False)
                else [result[index]]
            )
        ]
        for index, port in enumerate(schema.outputs)
    }


def test_unequal_execution_lists_preserve_lengths_order_and_payloads():
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
    outputs = execute_with_lists(Context, **streams)

    assert len(outputs["CONTEXT"]) == 1
    for name, output_name in zip(FIELDS, list(outputs)[1:], strict=True):
        expected = streams.get(name, [None])
        actual = outputs[output_name]
        assert len(actual) == len(expected)
        assert all(left is right for left, right in zip(actual, expected, strict=True))


@pytest.mark.parametrize(
    "replacement", [[], ["single"], ["new", "responses"], [[1, 2]]]
)
def test_execution_lists_survive_context_chains_and_branch_overrides(replacement):
    model = ReferenceOnly()
    images = ReferenceOnly()
    conditioning = [[ReferenceOnly(), {}]]
    list_payload = [ReferenceOnly(), ReferenceOnly()]
    scale = 2.0 / 1.5
    tile_plan = ReferenceOnly()
    api_client = ReferenceOnly()
    first = execute_with_lists(
        Context,
        model=[model],
        positive=[conditioning],
        any_1=["one", "two", "three"],
        any_2=[list_payload],
        any_3=[],
        scale=[scale],
        tile_plan=[tile_plan],
        api_client=[api_client],
    )
    second = execute_with_lists(
        Context, base_ctx=first["CONTEXT"], seed=[17], images=[images]
    )
    third = execute_with_lists(Context, base_ctx=second["CONTEXT"], seed=[0])
    sibling = execute_with_lists(Context, base_ctx=first["CONTEXT"], any_1=replacement)

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
    # Overrides reach descendants without leaking into bases or siblings.
    assert first["SEED"] == sibling["SEED"] == [None]
    assert second["SEED"] == [17]
    assert third["SEED"] == [0]
    assert first["IMAGES"] == sibling["IMAGES"] == [None]
    assert second["IMAGES"] == third["IMAGES"] == [images]
