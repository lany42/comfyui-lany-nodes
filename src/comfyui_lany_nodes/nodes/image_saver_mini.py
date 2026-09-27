# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Save PNG/JPG images with explicit generation metadata."""

import re
from datetime import datetime
from pathlib import Path, PureWindowsPath

from comfy_api.latest import io

from .. import image_saver as saver

FILENAME_TOKENS = re.compile(
    r"%time_format<([^>]*)>|%(model|date|time(?!_format)|seed|steps|width|height)"
)


def _validate_format(format: str) -> None:
    if format not in {"png", "jpg"}:
        raise ValueError("format must be png or jpg.")


def _validate_string(value: str, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string.")


def _parse_comma_separated(value: str, name: str) -> list[str]:
    _validate_string(value, name)

    return [entry.strip() for entry in value.strip().split(",") if entry.strip()]


def _validate_models(models: str) -> tuple[str, set[str]]:
    names = _parse_comma_separated(models, "models")
    for name in names:
        saver.validate_model_reference(name)
    references = saver.unique_model_references(names)

    return next(iter(references), ""), set(references.values())


def _validate_additional_hashes(additional_hashes: str) -> set[str]:
    hashes = set(_parse_comma_separated(additional_hashes, "additional_hashes"))
    if any(char.isspace() for digest in hashes for char in digest):
        raise ValueError(
            "additional_hashes must be comma-separated values without internal whitespace."
        )
    return hashes


def _validate_integer(value: int, name: str, maximum: int, minimum: int = 0) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.")


def _validate_jpg_quality(jpg_quality: int, format: str) -> None:
    if format == "jpg":
        _validate_integer(jpg_quality, "jpg_quality", maximum=100, minimum=1)


def _validate_images(images: io.Image.Type) -> io.Image.Type:
    if images.ndim == 3:
        images = images.unsqueeze(0)
    if (
        images.ndim != 4
        or any(size == 0 for size in images.shape)
        or images.shape[-1] not in (1, 3, 4)
    ):
        raise ValueError(
            "images must be nonempty HWC images or BHWC batches with 1, 3, or 4 channels."
        )

    return images


def _validate_filename(
    filename: str,
    time_format: str,
    *,
    model: str,
    seed: int,
    steps: int,
    width: int,
    height: int,
    now: datetime,
) -> str:
    _validate_string(filename, "filename")
    _validate_string(time_format, "time_format")

    literals = FILENAME_TOKENS.sub("", filename)
    if not filename or (literals and not saver.FILENAME_CHARACTERS.fullmatch(literals)):
        raise ValueError(
            "filename must contain only ASCII letters, digits, underscores, hyphens, "
            "periods, or supported replacement tokens, without a path."
        )

    values = {
        "date": now.strftime("%Y-%m-%d"),
        "model": model,
        "seed": str(seed),
        "steps": str(steps),
        "width": str(width),
        "height": str(height),
    }

    def replace(match):
        if match.group(1) is not None:
            return now.strftime(match.group(1))
        token = match.group(2)
        return now.strftime(time_format) if token == "time" else values[token]

    try:
        expanded = FILENAME_TOKENS.sub(replace, filename)
    except (ValueError, OverflowError) as error:
        raise ValueError("filename contains an invalid time format.") from error

    if expanded in {".", ".."} or not saver.FILENAME_CHARACTERS.fullmatch(expanded):
        raise ValueError(
            "expanded filename must be nonempty and contain only ASCII letters, "
            "digits, underscores, hyphens, or periods; . and .. are not allowed."
        )

    return expanded


def _validate_path(path: str, root: Path, filename: str) -> Path:
    _validate_string(path, "path")

    components = path.replace("\\", "/").split("/")
    if (
        Path(path).anchor
        or PureWindowsPath(path).anchor
        or any(
            part in {".", ".."} or PureWindowsPath(part).anchor for part in components
        )
    ):
        raise ValueError("path must not contain relative markers or anchors.")

    directory = Path(*(part for part in components if part))
    stem = saver.output_stem(root, directory, filename)
    if not stem.is_relative_to(root):
        raise ValueError("path resolves outside ComfyUI's output directory.")

    return stem


def _validate_inputs(
    *,
    images: io.Image.Type,
    positive: str,
    negative: str,
    models: str,
    seed: int,
    steps: int,
    width: int,
    height: int,
    jpg_quality: int,
    additional_hashes: str,
    format: str,
) -> tuple[io.Image.Type, str, set[str], set[str]]:
    """Return images, primary filename, model references, and extra hashes."""
    _validate_format(format)

    _validate_string(positive, "positive")
    _validate_string(negative, "negative")

    primary, model_names = _validate_models(models)
    extra_hashes = _validate_additional_hashes(additional_hashes)

    _validate_integer(seed, "seed", maximum=2**64 - 1)
    _validate_integer(steps, "steps", maximum=10000)
    _validate_integer(width, "width", maximum=2**53 - 1)
    _validate_integer(height, "height", maximum=2**53 - 1)

    _validate_jpg_quality(jpg_quality, format)
    images = _validate_images(images)

    return images, primary, model_names, extra_hashes


class ImageSaverMini(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="LanyNodes_ImageSaverMini",
            display_name="ImageSaverMini",
            category="Lany Nodes",
            description=(
                "Save PNG or JPG images with generation metadata. "
                "Missing model files trigger warnings and have no hashes."
            ),
            inputs=[
                io.Combo.Input(
                    "format", options=["png", "jpg"], default="png", socketless=True
                ),
                io.Image.Input("images"),
                io.String.Input(
                    "path",
                    default="",
                    tooltip=(
                        "Folder inside ComfyUI's output directory. "
                        "Leave empty to use the output directory. "
                        "No absolute paths or . or .. path components."
                    ),
                ),
                io.String.Input(
                    "filename",
                    default=saver.FILENAME,
                    tooltip=(
                        "Filename only; the extension is added automatically. "
                        "Supports %date, %time, %time_format<format>, %model, "
                        "%seed, %steps, %width, and %height. "
                        "%model is the model filename without its extension. "
                        "The result must use only ASCII letters, digits, "
                        "underscores, hyphens, or periods, and cannot be '.' or '..'."
                    ),
                ),
                io.String.Input(
                    "models",
                    default="",
                    tooltip=(
                        "Comma-separated file paths under ComfyUI's models directory. "
                        "Include extensions; the first file is the primary model. "
                        "Filenames may use ASCII letters, digits, underscores, "
                        "hyphens, or periods. "
                        "No absolute paths or . or .. path components. "
                        "Repeated paths are ignored; different files must have "
                        "different filenames."
                    ),
                ),
                io.String.Input("positive", force_input=True),
                io.String.Input("negative", force_input=True),
                io.Int.Input(
                    "seed",
                    default=0,
                    min=0,
                    max=2**64 - 1,
                    step=1,
                    control_after_generate=False,
                ),
                io.Int.Input(
                    "steps",
                    default=20,
                    min=0,
                    max=10000,
                    step=1,
                    control_after_generate=False,
                ),
                io.Int.Input(
                    "width",
                    default=0,
                    min=0,
                    max=2**53 - 1,
                    step=1,
                    tooltip=(
                        "Width stored in metadata. Set to 0 to use the image width."
                    ),
                ),
                io.Int.Input(
                    "height",
                    default=0,
                    min=0,
                    max=2**53 - 1,
                    step=1,
                    tooltip=(
                        "Height stored in metadata. Set to 0 to use the image height."
                    ),
                ),
                io.String.Input("time_format", default=saver.TIME_FORMAT),
                io.Int.Input("jpg_quality", default=80, min=1, max=100, step=1),
                io.Boolean.Input(
                    "optimize_png",
                    default=False,
                    tooltip=(
                        "Make PNG files smaller without losing quality. "
                        "May take longer to save."
                    ),
                ),
                io.Boolean.Input(
                    "png_embed_workflow",
                    default=True,
                    tooltip=(
                        "Save the ComfyUI workflow and API prompt in PNGs. "
                        "Generation metadata is always saved in PNG and JPG."
                    ),
                ),
                io.String.Input(
                    "additional_hashes",
                    default="",
                    tooltip=(
                        "Extra metadata hashes, separated by commas. "
                        "Surrounding whitespace and duplicates are ignored. "
                        "No whitespace inside a hash."
                    ),
                ),
            ],
            outputs=[],
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
            is_output_node=True,
        )

    @classmethod
    def execute(
        cls,
        images: io.Image.Type,
        positive: str,
        negative: str,
        filename: str = saver.FILENAME,
        models: str = "",
        seed: int = 0,
        steps: int = 20,
        width: int = 0,
        height: int = 0,
        time_format: str = saver.TIME_FORMAT,
        jpg_quality: int = 80,
        optimize_png: bool = False,
        png_embed_workflow: bool = True,
        additional_hashes: str = "",
        format: str = "png",
        path: str = "",
    ) -> io.NodeOutput:
        import folder_paths

        images, primary, model_names, extra_hashes = _validate_inputs(
            images=images,
            positive=positive,
            negative=negative,
            models=models,
            seed=seed,
            steps=steps,
            width=width,
            height=height,
            jpg_quality=jpg_quality,
            additional_hashes=additional_hashes,
            format=format,
        )

        width, height = width or images.shape[2], height or images.shape[1]
        model = saver.model_basename(primary)
        expanded_filename = _validate_filename(
            filename,
            time_format,
            model=model,
            seed=seed,
            steps=steps,
            width=width,
            height=height,
            now=datetime.now().astimezone(),
        )
        root = Path(folder_paths.get_output_directory()).resolve()
        file_path = _validate_path(path, root, expanded_filename)

        hashes = saver.model_hashes(model_names, extra_hashes, folder_paths)
        parameters = saver.GenerationParameters(
            positive=positive,
            negative=negative,
            seed=seed,
            steps=steps,
            width=width,
            height=height,
            model=model,
            hashes=frozenset(hashes.values()),
            model_hash=hashes.get(primary),
        )
        metadata = saver.image_metadata(
            format,
            parameters.to_string(),
            png_embed_workflow,
            cls.hidden.prompt,
            cls.hidden.extra_pnginfo,
        )

        options = saver.SaveOptions(
            root=root,
            file_path=file_path,
            format=format,
            jpg_quality=jpg_quality,
            optimize_png=optimize_png,
            metadata=metadata,
        )
        saver.save_batch(images, options)

        return io.NodeOutput()
