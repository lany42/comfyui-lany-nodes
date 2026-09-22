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
    ("prompt_pos", "PROMPT_POS", io.String),
    ("prompt_neg", "PROMPT_NEG", io.String),
    ("model_names", "MODEL_NAMES", io.String),
    ("controlnet", "CONTROLNET", io.ControlNet),
    ("upscale_model", "UPSCALE_MODEL", io.UpscaleModel),
    *((f"any_{index}", f"ANY_{index}", io.AnyType) for index in range(1, 5)),
)


class Context(io.ComfyNode):
    """Bundle connected values and inherit omitted fields from a base context."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        inputs = [_CONTEXT_TYPE.Input("base_ctx", optional=True)]
        outputs = [_CONTEXT_TYPE.Output("CONTEXT")]
        for name, output_name, socket_type in _FIELDS:
            options = {"optional": True}
            if socket_type in (io.Int, io.String):
                options["force_input"] = True
            inputs.append(socket_type.Input(name, **options))
            outputs.append(socket_type.Output(output_name))

        return io.Schema(
            node_id="LanyNodes_Context",
            display_name="Context",
            category="Lany Nodes",
            description=(
                "Bundle connected values into a context, inheriting omitted inputs "
                "from base_ctx. Connected values override inherited entries and "
                "must not be None. Unset outputs return None."
            ),
            inputs=inputs,
            outputs=outputs,
        )

    @classmethod
    def execute(cls, **inputs: object) -> io.NodeOutput:
        # Optional sockets are omitted from kwargs; a supplied None is an error.
        for name, value in inputs.items():
            if value is None:
                raise ValueError(f"Connected input '{name}' must not be None.")

        base_ctx = inputs.pop("base_ctx", {})
        if not isinstance(base_ctx, dict):
            raise TypeError("base_ctx must be a dictionary.")

        # Copy only the outer dictionary so overrides cannot alter the base.
        context = dict(base_ctx)
        context.update(inputs)
        return io.NodeOutput(context, *(context.get(name) for name, _, _ in _FIELDS))
