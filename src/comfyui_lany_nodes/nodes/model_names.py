# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Combine selected model and LoRA filenames for ImageSaverMini."""

from pathlib import Path

from comfy_api.latest import io

from .. import image_saver as saver


def _model_paths(category: str, folders) -> list[str]:
    references = []
    for name in folders.get_filename_list(category):
        path = folders.get_full_path(category, name)
        if path is None:
            continue
        try:
            relative = (
                Path(path).absolute().relative_to(Path(folders.models_dir).absolute())
            )
        except ValueError:
            # Files outside models_dir cannot be represented by this contract.
            continue
        references.append(relative.as_posix())
    return references


def _validate_names(names: list[str], input_name: str) -> None:
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise TypeError(f"{input_name} must be a list of filenames.")
    for name in names:
        if not saver.model_filename(name):
            raise ValueError(f"{input_name} must not contain an empty filename.")
        try:
            saver.validate_model_reference(name, input_name)
        except ValueError as error:
            raise ValueError(
                f"ImageSaverMini cannot represent {input_name} filename {name!r}: {error}"
            ) from error


class ModelNames(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        import folder_paths

        model_names = sorted(
            set(_model_paths("checkpoints", folder_paths))
            | set(_model_paths("diffusion_models", folder_paths))
        )
        return io.Schema(
            node_id="LanyNodes_ModelNames",
            display_name="ModelNames",
            category="Lany Nodes",
            description="Select models and LoRAs for ImageSaverMini.",
            inputs=[
                io.MultiCombo.Input(
                    "models",
                    options=model_names,
                    default=[],
                    placeholder="Select models",
                    chip=True,
                    socketless=True,
                    control_after_generate=False,
                    tooltip=(
                        "Select checkpoints and diffusion models in output order. "
                        "The first selection is the primary model."
                    ),
                ),
                io.MultiCombo.Input(
                    "loras",
                    options=_model_paths("loras", folder_paths),
                    default=[],
                    placeholder="Select LoRAs",
                    chip=True,
                    socketless=True,
                    control_after_generate=False,
                    tooltip="Select LoRAs in output order. They follow the models.",
                ),
            ],
            outputs=[
                io.String.Output(
                    "MODEL_NAMES",
                    tooltip="Comma-separated paths relative to ComfyUI's models directory.",
                ),
            ],
        )

    @classmethod
    def execute(cls, models: list[str], loras: list[str]) -> io.NodeOutput:
        _validate_names(models, "models")
        _validate_names(loras, "loras")
        saver.unique_model_references([*models, *loras])
        return io.NodeOutput(",".join([*models, *loras]))
