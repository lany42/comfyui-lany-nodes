# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Image encoding, filenames, and generation metadata without host imports."""

import hashlib
import json
import logging
import os
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from itertools import count
from pathlib import Path, PureWindowsPath
from typing import BinaryIO

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

LOGGER = logging.getLogger(__name__)
TIME_FORMAT = "%Y-%m-%d-%H%M%S"
FILENAME = "%time_%model_%seed"
FILENAME_CHARACTERS = re.compile(r"[a-zA-Z0-9_.-]+")


def model_filename(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def validate_model_reference(name: str, input_name: str = "models") -> None:
    """Validate a relative model path while keeping filename rules separate."""
    filename = model_filename(name)
    if name != name.strip() or any(char.isspace() for char in filename):
        raise ValueError(
            f"{input_name} must be comma-separated values without internal whitespace."
        )
    if any(char in name for char in ',:"\n\r'):
        raise ValueError(
            f"{input_name} must not contain commas, colons, quotes, or newlines."
        )
    if "\0" in name:
        raise ValueError(f"{input_name} must not contain null characters.")

    parts = name.replace("\\", "/").split("/")
    if (
        any(part in {"", ".", ".."} for part in parts)
        or PureWindowsPath(name).anchor
        or Path(filename).suffix in {"", "."}
    ):
        raise ValueError(
            f"{input_name} must contain relative model paths with filename suffixes, "
            "without empty components, relative markers, or anchors."
        )
    if not FILENAME_CHARACTERS.fullmatch(filename):
        raise ValueError(
            f"{input_name} filenames must contain only ASCII letters, digits, "
            "underscores, hyphens, or periods."
        )


def model_basename(name: str) -> str:
    return Path(model_filename(name)).stem


def unique_model_references(names: Iterable[str]) -> dict[str, str]:
    references = {}
    for name in names:
        filename = model_filename(name)
        previous = references.setdefault(filename, name)
        if previous.replace("\\", "/") != name.replace("\\", "/"):
            raise ValueError(
                f"models must use unique filenames across distinct paths: "
                f"{previous!r} and {name!r} both use {filename!r}."
            )
    return references


def _fingerprint(stat: os.stat_result) -> tuple[int, ...]:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@lru_cache(maxsize=128)
def _cached_hash(path: Path, fingerprint: tuple[int, ...]) -> str:
    LOGGER.info("ImageSaverMini: hashing %s", path.name)
    with path.open("rb") as source:
        if _fingerprint(os.fstat(source.fileno())) != fingerprint:
            raise OSError("model changed before hashing")
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        if _fingerprint(os.fstat(source.fileno())) != fingerprint:
            raise OSError("model changed while hashing")
    return digest


def file_hash(path: Path) -> str:
    path = path.resolve()
    return _cached_hash(path, _fingerprint(path.stat()))[:10]


def _resolve_model(name: str, folders) -> Path:
    path = (Path(folders.models_dir) / name.replace("\\", "/")).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"no matching model file at {path}")
    return path


def model_hashes(
    models: set[str], additional_hashes: set[str], folders
) -> dict[str, str]:
    hashes = {}
    for filename, name in unique_model_references(models).items():
        try:
            hashes[filename] = file_hash(_resolve_model(name, folders))
        except (OSError, ValueError) as error:
            LOGGER.warning("ImageSaverMini: skipping model %r: %s", name, error)

    hashes.update(
        (f"hash:{digest}", digest)
        for digest in additional_hashes.difference(hashes.values())
    )
    return hashes


@dataclass(frozen=True, kw_only=True)
class GenerationParameters:
    positive: str
    negative: str
    seed: int
    steps: int
    width: int
    height: int
    model: str
    hashes: frozenset[str]
    model_hash: str | None = None

    def to_string(self) -> str:
        fields = [
            f"Steps: {self.steps}",
            f"Seed: {self.seed}",
            f"Size: {self.width}x{self.height}",
        ]
        if self.model:
            fields.append(f"Model: {self.model}")
        if self.model_hash:
            fields.append(f"Model hash: {self.model_hash}")
        if self.hashes:
            # Civitai extracts a JSON object, then resolves every value by hash.
            hashes = {
                f"hash:{digest}": digest
                for digest in sorted(self.hashes)
                if digest != self.model_hash
            }
            if self.model_hash:
                hashes["model"] = self.model_hash
            fields.append(f"Hashes: {json.dumps(hashes, separators=(',', ':'))}")
        fields.append("Version: ComfyUI")
        return f"{self.positive}\nNegative prompt: {self.negative}\n{', '.join(fields)}"


def output_stem(root: Path, path: Path, filename: str) -> Path:
    return (root / path / filename).resolve()


def _within_output(root: Path, path: Path) -> None:
    if not path.resolve().is_relative_to(root):
        raise ValueError("filename resolves outside ComfyUI's output directory.")


def image_metadata(format, text, png_embed_workflow, prompt, extra_pnginfo):
    if format == "png":
        return _png_metadata(text, png_embed_workflow, prompt, extra_pnginfo)
    return _jpg_metadata(text)


def _png_metadata(text, png_embed_workflow, prompt, extra_pnginfo):
    metadata = PngInfo()
    if png_embed_workflow:
        for key, value in (extra_pnginfo or {}).items():
            if key not in {"parameters", "prompt"}:
                metadata.add_text(key, json.dumps(value, separators=(",", ":")))
        if prompt is not None:
            metadata.add_text("prompt", json.dumps(prompt, separators=(",", ":")))
    # ComfyUI decodes PNG text as UTF-8, including prompts that fit in Latin-1.
    metadata.add_itxt("parameters", text)
    return {"pnginfo": metadata}


def _jpg_metadata(text):
    exif = Image.Exif()
    # A BOM prevents readers from guessing the wrong byte order for CJK prompts.
    exif[0x8769] = {0x9286: b"UNICODE\0\xfe\xff" + text.encode("utf-16-be")}
    encoded = exif.tobytes()
    # A JPEG APP1 marker's 16-bit length includes its own two length bytes.
    if len(encoded) > 65533:
        raise ValueError(
            "ImageSaverMini generation metadata is too large for JPG; use PNG."
        )
    return {"exif": encoded}


@dataclass(frozen=True, kw_only=True)
class SaveOptions:
    root: Path
    file_path: Path
    format: str
    jpg_quality: int
    optimize_png: bool
    metadata: dict[str, PngInfo | bytes]


def _batch_images(images, format: str) -> Iterator[Image.Image]:
    for tensor in images:
        pixels = tensor.detach().cpu().float().numpy()
        if not np.isfinite(pixels).all():
            raise ValueError("images must contain finite pixel values.")
        # Pillow's RGB/RGBA modes require 8-bit channels. Its float mode is
        # grayscale only and cannot be written as PNG or JPEG.
        pixels = np.clip(pixels * 255, 0, 255).astype(np.uint8)
        if pixels.shape[-1] == 1:
            pixels = pixels[..., 0]
        image = Image.fromarray(pixels)
        yield image.convert("RGB") if format == "jpg" else image


def _reserve_output(options: SaveOptions) -> tuple[Path, BinaryIO]:
    file_path = options.file_path
    prefix = f"{file_path.name}_"
    matches = sorted(
        (
            entry
            for entry in file_path.parent.iterdir()
            if entry.suffix == f".{options.format}"
            and (
                entry.stem == file_path.name
                or (
                    entry.stem.startswith(prefix)
                    and entry.stem[len(prefix) :].isdecimal()
                )
            )
        ),
        key=lambda entry: int(entry.stem[len(prefix) :] or 0),
    )
    start = int(matches[-1].stem[len(prefix) :] or 0) + 1 if matches else 0

    for index in count(start):
        suffix = f"_{index}" if index else ""
        path = file_path.with_name(f"{file_path.name}{suffix}.{options.format}")
        _within_output(options.root, path)
        try:
            return path, path.open("xb")
        except FileExistsError:
            # Another writer may have claimed this name since the directory scan.
            continue


def save_batch(images, options: SaveOptions) -> None:
    _within_output(options.root, options.file_path)
    options.file_path.parent.mkdir(parents=True, exist_ok=True)
    encoding = (
        {"optimize": options.optimize_png}
        if options.format == "png"
        else {"quality": options.jpg_quality, "optimize": True}
    )
    for image in _batch_images(images, options.format):
        path, output = _reserve_output(options)
        try:
            with output:
                image.save(
                    output,
                    format="PNG" if options.format == "png" else "JPEG",
                    **options.metadata,
                    **encoding,
                )
        except BaseException:
            path.unlink(missing_ok=True)
            raise
