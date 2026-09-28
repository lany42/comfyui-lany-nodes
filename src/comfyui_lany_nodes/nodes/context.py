# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""A context pipe that forwards payloads by reference."""

from comfy_api.latest import io

_CONTEXT_TYPE = io.Custom("LANY_CONTEXT")
_FIELDS = (
    ("model", "MODEL", io.Model),
    ("clip", "CLIP", io.Clip),
    ("vae", "VAE", io.Vae),
    ("positive", "POSITIVE", io.Conditioning),
    ("negative", "NEGATIVE", io.Conditioning),
    ("latent", "LATENT", io.Latent),
    ("images", "IMAGES", io.Image),
    ("seed", "SEED", io.Int),
    ("width", "WIDTH", io.Int),
    ("height", "HEIGHT", io.Int),
    ("scale", "SCALE", io.Float),
    ("prompt_pos", "PROMPT_POS", io.String),
    ("prompt_neg", "PROMPT_NEG", io.String),
    ("model_names", "MODEL_NAMES", io.String),
    ("controlnet", "CONTROLNET", io.ControlNet),
    ("upscale_model", "UPSCALE_MODEL", io.UpscaleModel),
    ("tile_plan", "TILE_PLAN", io.AnyType),
    ("api_client", "API_CLIENT", io.AnyType),
    *((f"any_{index}", f"ANY_{index}", io.AnyType) for index in range(1, 5)),
)


class _ExecutionList(list[object]):
    """Mark execution lists in a context without flattening list-valued payloads."""


class Context(io.ComfyNode):
    """Bundle connected values and inherit omitted fields from a base context."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        inputs = [_CONTEXT_TYPE.Input("base_ctx", optional=True)]
        outputs = [_CONTEXT_TYPE.Output("CONTEXT")]
        for name, output_name, socket_type in _FIELDS:
            options = {"optional": True}
            if socket_type in (io.Int, io.Float, io.String):
                options["force_input"] = True
            inputs.append(socket_type.Input(name, **options))
            outputs.append(socket_type.Output(output_name, is_output_list=True))

        return io.Schema(
            node_id="LanyNodes_Context",
            display_name="Context",
            category="Lany Nodes",
            description=(
                "Bundle connected values into a context, inheriting omitted inputs "
                "from base_ctx. Connected values override inherited entries and "
                "must not be None. Execution lists retain their own lengths without "
                "repeating other fields. base_ctx accepts one context. "
                "Unset outputs return None."
            ),
            is_input_list=True,
            inputs=inputs,
            outputs=outputs,
        )

    @classmethod
    def execute(cls, **inputs: list[object]) -> io.NodeOutput:
        # ComfyUI wraps every connected input in an execution list, including
        # scalar values and payloads that are themselves lists (e.g. conditioning).
        for name, values in inputs.items():
            if values is None or any(value is None for value in values):
                raise ValueError(f"Connected input '{name}' must not be None.")

        bases = inputs.pop("base_ctx", [{}])
        if len(bases) != 1:
            raise ValueError("base_ctx must contain exactly one context.")
        base_ctx = bases[0]
        if not isinstance(base_ctx, dict):
            raise TypeError("base_ctx must be a dictionary.")

        # Copy only the outer dictionary so overrides cannot alter the base.
        context = dict(base_ctx)
        for name, values in inputs.items():
            context[name] = values[0] if len(values) == 1 else _ExecutionList(values)

        outputs = []
        for name, _, _ in _FIELDS:
            value = context.get(name)
            outputs.append(value if isinstance(value, _ExecutionList) else [value])
        return io.NodeOutput(context, *outputs)
