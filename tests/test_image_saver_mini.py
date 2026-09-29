# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Real CPU tensor/file tests with small doubles for the V3 host boundary."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest
import torch
from PIL import Image

from comfyui_lany_nodes import image_saver as saver
from comfyui_lany_nodes.nodes import image_saver_mini
from comfyui_lany_nodes.nodes.image_saver_mini import ImageSaverMini
from comfyui_lany_nodes.nodes.model_names import ModelNames

PICKER_CATEGORIES = ("checkpoints", "diffusion_models", "loras")
NOW = datetime(2026, 9, 26, 12, 34, 56).astimezone()


@pytest.fixture
def host(tmp_path, monkeypatch):
    root = tmp_path / "output"
    folders = ModuleType("folder_paths")
    folders.models_dir = str(tmp_path / "models")
    folders.supported_pt_extensions = {".safetensors", ".ckpt", ".pt", ".custom"}
    folders.get_output_directory = lambda: str(root)
    paths = {category: {} for category in PICKER_CATEGORIES}
    folders.get_filename_list = lambda category: list(paths[category])
    folders.get_full_path = lambda category, name: paths[category].get(
        str(Path(name.replace("\\", "/")))
    )

    def add_model(category, name, content=b"model file"):
        relative = Path(name.replace("\\", "/"))
        path = Path(folders.models_dir) / category / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        paths[category][str(relative)] = str(path)
        return path

    hidden = SimpleNamespace(
        prompt={"1": {"class_type": "Test", "inputs": {"text": "海"}}},
        extra_pnginfo={"workflow": {"nodes": [{"id": 1}]}, "extra": {"a": 1}},
    )
    monkeypatch.setitem(sys.modules, "folder_paths", folders)
    monkeypatch.setattr(ImageSaverMini, "hidden", hidden, raising=False)

    def run(**kwargs):
        inputs = {
            "images": torch.zeros((1, 3, 5, 3)),
            "filename": "image",
            "positive": "positive",
            "negative": "negative",
        }
        return ImageSaverMini.execute(**(inputs | kwargs))

    saver._cached_hash.cache_clear()
    yield SimpleNamespace(
        run=run, root=root, folders=folders, hidden=hidden, add_model=add_model
    )
    saver._cached_hash.cache_clear()


@pytest.fixture
def hash_models(monkeypatch):
    """Fail if a test reaches model hashing, which reads multi-gigabyte files."""
    hash_models = Mock()
    monkeypatch.setattr(saver, "model_hashes", hash_models)
    yield
    hash_models.assert_not_called()


def freeze_time(monkeypatch, *moments):
    """Return NOW from the node's clock, or each given moment once."""
    now = Mock(side_effect=moments) if moments else Mock(return_value=NOW)
    monkeypatch.setattr(image_saver_mini, "datetime", Mock(now=now))


def sha(content):
    return hashlib.sha256(content).hexdigest()[:10]


def hashes_in(text):
    return json.loads(text.split("Hashes: ")[1].split(", Version:")[0])


# Contract references pinned to ComfyUI_frontend f288d755b488f8bf6609100ee3e8c8b507d88630:
# https://github.com/Comfy-Org/ComfyUI_frontend/blob/f288d755b488f8bf6609100ee3e8c8b507d88630/src/scripts/metadata/png.ts
# https://github.com/Comfy-Org/ComfyUI_frontend/blob/f288d755b488f8bf6609100ee3e8c8b507d88630/src/scripts/pnginfo.ts
# https://github.com/Comfy-Org/ComfyUI_frontend/blob/f288d755b488f8bf6609100ee3e8c8b507d88630/src/scripts/metadata/parser.ts
def read_png_metadata(path):
    """Read our saved text chunks with ComfyUI's UTF-8 decoding contract."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    metadata = {}
    offset = 8
    while offset < len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        if kind in {b"tEXt", b"iTXt"}:
            chunk = data[offset + 8 : offset + 8 + length]
            keyword, content = chunk.split(b"\0", 1)
            # Readers disagree on whether the first or last duplicate wins.
            assert keyword.decode("latin-1") not in metadata, keyword
            if kind == b"iTXt":
                assert content[:2] == b"\0\0"  # Uncompressed, compression method zero.
                _, _, content = content[2:].split(b"\0", 2)
            metadata[keyword.decode("latin-1")] = content.decode("utf-8")
        offset += length + 12
    return metadata


def read_parameters(path):
    if path.suffix == ".png":
        return read_png_metadata(path)["parameters"]
    with Image.open(path) as image:
        # The pinned ComfyUI file dispatcher has no JPEG branch. Pin EXIF's
        # UserComment location and Unicode encoding separately from PNG imports.
        raw = image.getexif().get_ifd(0x8769)[0x9286]
        assert raw[:8] == b"UNICODE\0"
        assert raw[8:10] == b"\xfe\xff"
        return raw[10:].decode("utf-16-be")


# Metadata consumers


@pytest.mark.parametrize("format", ["png", "jpg"])
def test_generation_metadata_pins_comfyui_parameter_minimums(host, format):
    positive, negative = "  晴れ\n<lora:keep:1> STYLE(x)  ", "\nembedding:keep\n"
    result = host.run(
        format=format,
        positive=positive,
        negative=negative,
        png_embed_workflow=False,
        seed=2**64 - 1,
        steps=32,
    )
    assert result.result == () and result.ui is None
    text = read_parameters(host.root / f"image.{format}")
    # importA1111 locates the last Negative prompt and Steps line markers, then
    # reads Steps, Seed, and Size from the final line to populate core nodes.
    # JavaScript numbers cannot hold this seed, so pin the exact text here.
    assert text == (
        f"{positive}\nNegative prompt: {negative}\n"
        "Steps: 32, Seed: 18446744073709551615, Size: 5x3, Version: ComfyUI"
    )


@pytest.mark.parametrize("format", ["png", "jpg"])
def test_civitai_and_comfyui_metadata_contracts(host, tmp_path, format):
    node = shutil.which("node")
    assert node is not None, (
        "Node.js and npm ci are required for metadata contract tests."
    )
    resources = [
        ("checkpoints", "base.safetensors", b"base"),
        ("diffusion_models", "refiner.gguf", b"refiner"),
        ("loras", "ink.safetensors", b"ink"),
    ]
    for category, name, content in resources:
        host.add_model(category, name, content)
    base, refiner, ink = [sha(data) for _, _, data in resources]
    manual = "A" * 64
    all_hashes = {
        "model": base,
        f"hash:{refiner}": refiner,
        f"hash:{ink}": ink,
        f"hash:{manual}": manual,
    }

    # A complete, loadable core-node workflow, not just an arbitrary JSON object.
    workflow = {
        "version": 0.4,
        "last_node_id": 1,
        "last_link_id": 0,
        "nodes": [
            {
                "id": 1,
                "type": "EmptyLatentImage",
                "pos": [100, 100],
                "size": [315, 106],
                "flags": {},
                "order": 0,
                "mode": 0,
                "inputs": [],
                "outputs": [{"name": "LATENT", "type": "LATENT", "links": []}],
                "properties": {"Node name for S&R": "EmptyLatentImage"},
                "widgets_values": [512, 768, 1],
            }
        ],
        "links": [],
        "groups": [],
        "config": {},
        "extra": {"label": "café 海 🌊"},
    }
    prompt = {
        "1": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 768, "batch_size": 1},
        }
    }
    host.hidden.prompt = prompt
    host.hidden.extra_pnginfo = {"workflow": workflow}
    all_models = (
        "checkpoints/base.safetensors,diffusion_models/refiner.gguf,"
        "loras/ink.safetensors"
    )
    cases = [
        {
            "name": "complete",
            "models": all_models,
            "additional": f"{base},{manual},{manual}",
            "positive": "café 海 🌊",
            "model": "base",
            "model_hash": base,
            "hashes": all_hashes,
        },
        {
            "name": "without_workflow",
            "models": all_models,
            "additional": manual,
            "positive": "café 海 🌊",
            "embed": False,
            "model": "base",
            "model_hash": base,
            "hashes": all_hashes,
        },
        {
            "name": "manual_only",
            "additional": f"{manual},custom-digest",
            "positive": "manual",
            "hashes": {f"hash:{manual}": manual, "hash:custom-digest": "custom-digest"},
        },
        {
            "name": "missing_primary",
            "models": "checkpoints/missing.safetensors,diffusion_models/refiner.gguf",
            "positive": "missing",
            "model": "missing",
            "hashes": {f"hash:{refiner}": refiner},
        },
        {"name": "empty_prompts", "positive": "", "negative": ""},
        {
            "name": "multiline_prompts",
            "positive": "  晴れ\n<lora:keep:1> STYLE(x)  ",
            "negative": "\nembedding:keep\n",
            "prompt_resources": [{"type": "lora", "name": "keep", "weight": 1}],
        },
        {"name": "long_unicode", "positive": "一" * 600 + " 海 🌊"},
        # Latin-1-only text must still be UTF-8 for ComfyUI's PNG decoder.
        {"name": "latin1_prompts", "positive": "café crème", "negative": "naïve"},
    ]
    samples = []
    for case in cases:
        name, positive = case["name"], case["positive"]
        negative, embed = case.get("negative", "negative"), case.get("embed", True)
        model, model_hash = case.get("model"), case.get("model_hash")
        host.run(
            format=format,
            filename=name,
            models=case.get("models", ""),
            additional_hashes=case.get("additional", ""),
            positive=positive,
            negative=negative,
            seed=42,
            steps=27,
            width=512,
            height=768,
            png_embed_workflow=embed,
        )
        samples.append(
            {
                "name": name,
                "path": str(host.root / f"{name}.{format}"),
                "format": "jpeg" if format == "jpg" else "png",
                # Civitai trims prompts and omits empty ones; the saved text keeps
                # them exactly, as test_generation_metadata_pins_... checks.
                "metadata": {
                    "prompt": positive.strip() or None,
                    "negativePrompt": negative.strip() or None,
                    "seed": 42,
                    "steps": 27,
                    "width": 512,
                    "height": 768,
                    "Model": model,
                    "Model hash": model_hash,
                    "hashes": case.get("hashes"),
                },
                # Civitai credits hashed models and LoRA tags in the prompt.
                "resources": [
                    *(
                        [{"type": "model", "name": model, "hash": model_hash}]
                        if model_hash
                        else []
                    ),
                    *case.get("prompt_resources", []),
                ],
                "parameters_prefix": f"{positive}\nNegative prompt: {negative}\n",
                "workflow": workflow if embed else None,
                "prompt": prompt if embed else None,
            }
        )

    manifest = tmp_path / "metadata-cases.json"
    manifest.write_text(json.dumps(samples), encoding="utf-8")
    result = subprocess.run(
        [
            node,
            str(Path(__file__).with_name("metadata_contract.test.mjs")),
            str(manifest),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("embed", [True, False])
def test_png_workflow_and_reserved_metadata(host, embed):
    host.hidden.extra_pnginfo.update(parameters="must not replace", prompt="wrong")
    host.run(png_embed_workflow=embed)
    metadata = read_png_metadata(host.root / "image.png")
    assert metadata["parameters"].startswith("positive\nNegative prompt:")
    if embed:
        assert {"parameters", "prompt", "workflow"} <= metadata.keys()
        assert json.loads(metadata["prompt"]) == host.hidden.prompt
        assert json.loads(metadata["workflow"]) == host.hidden.extra_pnginfo["workflow"]
        assert json.loads(metadata["extra"]) == {"a": 1}
    else:
        assert set(metadata) == {"parameters"}


def test_png_without_browser_workflow(host):
    host.hidden.prompt = host.hidden.extra_pnginfo = None
    host.run()
    assert set(read_png_metadata(host.root / "image.png")) == {"parameters"}


def test_jpg_never_serializes_workflow(host):
    host.hidden.prompt = object()
    host.hidden.extra_pnginfo = {"workflow": object()}
    host.run(format="jpg", png_embed_workflow=True)
    with Image.open(host.root / "image.jpg") as image:
        exif = image.getexif()
        assert set(exif) == {0x8769}
        assert set(exif.get_ifd(0x8769)) == {0x9286}


def test_jpg_exif_limit_fails_without_saving(host):
    with pytest.raises(ValueError, match="too large.*PNG"):
        host.run(format="jpg", positive="a" * 33000)
    assert not host.root.exists()
    # PNG has no JPEG APP1 limit and keeps the whole prompt.
    host.run(positive="a" * 33000)
    assert read_parameters(host.root / "image.png").startswith("a" * 33000)


# Pixels and encoding


@pytest.mark.parametrize("shape", [(3, 5, 3), (1, 3, 5, 3), (2, 3, 5, 4), (2, 3, 5, 1)])
def test_image_shapes_pixels_and_batch_names(host, shape):
    images = (
        torch.linspace(-0.5, 1.5, int(np.prod(shape))).reshape(shape).requires_grad_()
    )
    host.run(images=images)
    batch = images.unsqueeze(0) if images.ndim == 3 else images
    names = ["image.png", *(f"image_{i}.png" for i in range(1, len(batch)))]
    assert sorted(path.name for path in host.root.iterdir()) == names
    for filename, tensor in zip(names, batch, strict=True):
        expected = np.clip(tensor.detach().numpy() * 255, 0, 255).astype(np.uint8)
        if shape[-1] == 1:
            expected = expected[..., 0]
        with Image.open(host.root / filename) as image:
            np.testing.assert_array_equal(np.asarray(image), expected)


def test_noncontiguous_bfloat_tensor_and_metadata_dimensions(host):
    images = torch.zeros((1, 3, 7, 3), dtype=torch.bfloat16).transpose(1, 2)
    host.run(images=images, filename="%widthx%height_%width_%height", width=1024)
    path = host.root / "1024x7_1024_7.png"
    with Image.open(path) as image:
        assert image.size == (3, 7)
    assert "Size: 1024x7" in read_parameters(path)


def test_jpg_rgba(host):
    image = torch.zeros((2, 3, 4))
    image[..., 0] = 1
    host.run(images=image, format="jpg", jpg_quality=100)
    with Image.open(host.root / "image.jpg") as saved:
        assert saved.mode == "RGB"
        assert saved.size == (3, 2)
        assert saved.getpixel((0, 0))[0] >= 250


@pytest.mark.parametrize(
    ("format", "input_name", "value", "encoder_option"),
    [
        ("png", "optimize_png", False, "optimize"),
        ("png", "optimize_png", True, "optimize"),
        ("jpg", "jpg_quality", 100, "quality"),
    ],
)
def test_encoding_controls_reach_encoder(
    host, format, input_name, value, encoder_option
):
    with patch.object(
        Image.Image, "save", autospec=True, side_effect=Image.Image.save
    ) as encode:
        host.run(format=format, **{input_name: value})
    encode.assert_called_once()
    assert encode.call_args.kwargs[encoder_option] == value


@pytest.mark.parametrize("shape", [(0, 2, 3, 3), (2, 3), (1, 2, 3, 2)])
def test_invalid_shapes(host, shape):
    with pytest.raises(ValueError, match="nonempty HWC"):
        host.run(images=torch.zeros(shape))
    assert not host.root.exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"seed": True},
        {"steps": 10001},
        # Linked INT inputs bypass the host's min/max checks.
        {"width": -1},
        {"height": 1.5},
        {"format": "webp"},
        {"format": "jpg", "jpg_quality": 101},
        {"positive": None},
    ],
)
def test_invalid_inputs(host, kwargs):
    with pytest.raises((ValueError, TypeError)):
        host.run(**kwargs)
    assert not host.root.exists()


def test_nonfinite_pixels_and_failed_encode_leave_no_file(host, monkeypatch):
    with pytest.raises(ValueError, match="finite"):
        host.run(images=torch.full((1, 2, 3, 3), float("nan")))
    assert list(host.root.iterdir()) == []
    monkeypatch.setattr(Image.Image, "save", Mock(side_effect=OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        host.run()
    assert list(host.root.iterdir()) == []


# Output names and paths


@pytest.mark.parametrize(
    ("existing", "expected"),
    [
        (["image", "image_1", "image_2"], "image_3"),
        # Numeric, not lexical, order. A gap is needed: with image_10 present,
        # the collision retry would hide a lexical sort.
        (["image_9", "image_100"], "image_101"),
        (["image_2", "image_8"], "image_9"),
        (["image_01", "image_02"], "image_3"),
    ],
)
def test_filenames_continue_after_highest_numeric_suffix(host, existing, expected):
    # JPG here; the next test covers the PNG counter.
    host.root.mkdir()
    for name in existing:
        (host.root / f"{name}.jpg").write_bytes(b"existing file")

    host.run(format="jpg")

    assert {path.stem for path in host.root.iterdir()} == {*existing, expected}
    assert "Steps: 20" in read_parameters(host.root / f"{expected}.jpg")
    for name in existing:
        assert (host.root / f"{name}.jpg").read_bytes() == b"existing file"


def test_filename_counter_ignores_other_stems_and_formats(host):
    host.root.mkdir()
    unrelated = {
        "image_edit.png",
        "image2.png",
        "image_1_edit.png",
        "image_extra_99.png",
        "other_99.png",
        "image_100.jpg",
    }
    for name in unrelated:
        (host.root / name).touch()

    host.run(images=torch.zeros((2, 2, 3, 3)))

    assert {path.name for path in host.root.iterdir()} == unrelated | {
        "image.png",
        "image_1.png",
    }


def test_filename_reservation_retries_a_concurrent_collision(host, monkeypatch):
    open_path = Path.open

    def claim_before_open(path, mode="r", *args, **kwargs):
        if mode == "xb" and path.name == "image.png":
            with open_path(path, "wb") as competing:
                competing.write(b"another writer")
        return open_path(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", claim_before_open)
    host.run()

    assert (host.root / "image.png").read_bytes() == b"another writer"
    assert "Steps: 20" in read_parameters(host.root / "image_1.png")


def test_filename_interpolation_and_directories(host, monkeypatch):
    freeze_time(monkeypatch)
    host.add_model("checkpoints", "model.custom")
    host.run(
        path="portraits/day///",
        filename="%date_%time_format<%H%M>_%time_%model_%seed_%steps_%width_%height",
        time_format="%H-%M",
        models="checkpoints/model.custom",
        seed=42,
        steps=20,
        width=1024,
        height=768,
    )
    saved = host.root / "portraits/day/2026-09-26_1234_12-34_model_42_20_1024_768.png"
    assert "Model: model" in read_parameters(saved)


@pytest.mark.parametrize(
    ("path", "time_format", "directory"),
    [
        (r"%date\sdxl\png", "%H-%M", "2026-09-26/sdxl/png"),
        (
            "%date/%time/%time_format<%H%M>/%model/%seed_%steps_%widthx%height",
            "%H-%M",
            "2026-09-26/12-34/1234/base.v2/42_20_5x3",
        ),
        ("%time/sdxl/png", "%Y/%m/%d", "2026/09/26/sdxl/png"),
    ],
)
def test_path_interpolation(host, monkeypatch, path, time_format, directory):
    # A second clock read would move the path to another day.
    freeze_time(monkeypatch, NOW, NOW.replace(day=27))
    host.add_model("checkpoints", "base.v2.safetensors")
    host.run(
        path=path,
        filename="%date_%time_format<%H%M%S>",
        time_format=time_format,
        models="checkpoints/base.v2.safetensors",
        seed=42,
        steps=20,
    )
    saved = host.root / directory / "2026-09-26_123456.png"
    assert "Model: base.v2" in read_parameters(saved)


@pytest.mark.parametrize(
    ("path", "directory"), [("", ""), ("my.dir//海 images///", "my.dir/海 images")]
)
def test_output_path_is_separate_from_filename(host, path, directory):
    host.run(path=path, filename="Image_01-test")
    assert (host.root / directory / "Image_01-test.png").exists()


@pytest.mark.parametrize("filename", [".image", "image.png", "%model"])
def test_periods_in_filenames_and_model_tokens(host, filename):
    host.add_model("checkpoints", "base.v2.safetensors")
    host.run(
        images=torch.zeros((2, 3, 5, 3)),
        filename=filename,
        models="checkpoints/base.v2.safetensors",
    )
    stem = "base.v2" if filename == "%model" else filename
    for suffix in ("", "_1"):
        saved = host.root / f"{stem}{suffix}.png"
        assert "Model: base.v2" in read_parameters(saved)


@pytest.mark.parametrize(
    "filename",
    [
        "",
        ".",
        "..",
        "my image",
        "../escape",
        r"..\escape",
        "%unknown",
        "%time_format<%H",
        "%time_format",
    ],
)
def test_invalid_filename_fails_before_hashing(host, hash_models, filename):
    with pytest.raises(ValueError, match="filename"):
        host.run(filename=filename)
    assert not host.root.exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"filename": "%model"},
        {"filename": "%time_format<..>"},
        {"filename": "%time", "time_format": "%H:%M"},
        {"filename": "%time", "time_format": "%Y/%m/%d"},
    ],
)
def test_invalid_expanded_filename_fails_before_hashing(host, hash_models, kwargs):
    with pytest.raises(ValueError, match="expanded filename"):
        host.run(**kwargs)
    assert not host.root.exists()


@pytest.mark.parametrize(
    "path",
    [
        ".",
        "../escape",
        r"nested\..\escape",
        "/tmp/escape",
        "C:escape",
        "nested/C:escape",
        r"\\server\share",
    ],
)
def test_invalid_path_fails_before_hashing(host, hash_models, path):
    with pytest.raises(ValueError, match="path.*relative markers or anchors"):
        host.run(path=path)
    assert not host.root.exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"path": "%time", "time_format": "../escape"},
        {"path": "nested/%time_format<C:escape>"},
    ],
)
def test_invalid_expanded_path_fails_before_hashing(host, hash_models, kwargs):
    with pytest.raises(ValueError, match="path.*relative markers or anchors"):
        host.run(**kwargs)
    assert not host.root.exists()


def test_output_paths_do_not_follow_symlinks_outside_output(host, tmp_path):
    host.root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (host.root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="outside"):
        host.run(path="link")
    (host.root / "image").symlink_to(outside / "stem")
    with pytest.raises(ValueError, match="outside"):
        host.run()
    (host.root / "image").unlink()
    (host.root / "image.png").symlink_to(outside / "target.png")
    host.run()
    assert (host.root / "image_1.png").is_file()
    assert (host.root / "image.png").is_symlink()
    assert list(outside.iterdir()) == []


def test_symlinked_output_directory_is_the_output_root(host, tmp_path):
    # ComfyUI reports its output directory without resolving symlinks.
    disk = tmp_path / "disk"
    disk.mkdir()
    host.root.symlink_to(disk, target_is_directory=True)
    host.run(path="nested")
    assert (disk / "nested" / "image.png").is_file()


def test_output_path_allows_symlinks_within_output(host):
    directory = host.root / "nested"
    directory.mkdir(parents=True)
    (host.root / "link").symlink_to(directory, target_is_directory=True)
    host.run(path="link/")
    assert (directory / "image.png").exists()


# Models and hashes


@pytest.mark.parametrize("prefix", ["", "版本/art styles/"])
def test_model_names_output_saves_images(host, monkeypatch, caplog, prefix):
    resources = [
        ("checkpoints", f"{prefix}base.v2.safetensors", b"base"),
        ("diffusion_models", f"{prefix}refiner.gguf", b"refiner"),
        ("loras", f"{prefix}ink.safetensors", b"ink"),
        ("loras", "detail.safetensors", b"detail"),
    ]
    for category, name, content in resources:
        host.add_model(category, name, content)
        if prefix and name.startswith(prefix):
            # Same filename at the category root: lookup must use the full path.
            host.add_model(category, name.rsplit("/", 1)[-1], b"wrong file")
    monkeypatch.setattr(
        host.folders,
        "get_filename_list",
        lambda category: [name for folder, name, _ in resources if folder == category],
    )
    schema = ModelNames.define_schema()
    references = [f"{category}/{name}" for category, name, _ in resources]
    assert {*references[:2]} <= {*schema.inputs[0].options}
    assert {*references[2:]} <= {*schema.inputs[1].options}
    (models,) = ModelNames.execute(references[:2], references[2:]).result
    freeze_time(monkeypatch)

    host.run(models=models, filename=saver.FILENAME)

    text = read_parameters(host.root / "2026-09-26-123456_base.v2_0.png")
    assert "Model: base.v2" in text
    if prefix:
        assert prefix not in text
    primary, *others = [sha(content) for _, _, content in resources]
    assert f"Model hash: {primary}" in text
    assert hashes_in(text) == {
        "model": primary,
        **{f"hash:{digest}": digest for digest in others},
    }
    assert not caplog.records


# Each clause of the shared model reference rules. ModelNames covers the
# filename characters that real files on disk can contain.
@pytest.mark.parametrize(
    "reference",
    [
        "../base.safetensors",
        r"..\base.safetensors",
        "old//base.safetensors",
        "old/./base.safetensors",
        "base.safetensors/",
        "/base.safetensors",
        r"C:\base.safetensors",
        r"\\server\share\base.safetensors",
        "old\0/base.safetensors",
        "base",
        ".safetensors",
    ],
)
def test_invalid_model_paths_and_missing_suffixes_fail_at_node_input(
    host, hash_models, reference
):
    with pytest.raises(ValueError, match="models"):
        host.run(models=f"valid.safetensors, {reference}")
    assert not host.root.exists()


@pytest.mark.parametrize("input_name", ["models", "additional_hashes"])
def test_internal_whitespace_fails_at_node_input(host, hash_models, input_name):
    with pytest.raises(ValueError, match=f"{input_name}.*internal whitespace"):
        host.run(**{input_name: "valid.safetensors, ABC\u00a0DEF.safetensors"})
    assert not host.root.exists()


def test_model_metadata_delimiters_fail_at_node_input(host, hash_models):
    # Quotes and colons would corrupt the Model and Hashes metadata fields.
    with pytest.raises(ValueError, match="models.*commas, colons, quotes, or newlines"):
        host.run(models='valid.safetensors, bad"name.safetensors')
    assert not host.root.exists()


def test_model_names_share_filename_character_restrictions(host, hash_models):
    with pytest.raises(ValueError, match="models.*ASCII letters"):
        ModelNames.execute(["nested/bad%name.safetensors"], [])
    with pytest.raises(ValueError, match="models.*ASCII letters"):
        host.run(models="bad%name.safetensors")
    assert not host.root.exists()


def test_conflicting_model_filenames_fail_before_hashing(host, hash_models):
    with pytest.raises(ValueError, match="unique filenames across distinct paths"):
        host.run(models="checkpoints/base.safetensors,loras/base.safetensors")
    assert not host.root.exists()


def test_node_deduplicates_model_names_and_preserves_primary(host, monkeypatch):
    host.add_model("checkpoints", "zbase.safetensors", b"base")
    host.add_model("diffusion_models", "arefiner.gguf", b"refiner")
    hash_file = Mock(wraps=saver.file_hash)
    monkeypatch.setattr(saver, "file_hash", hash_file)
    host.run(
        models=(
            " \t, checkpoints/zbase.safetensors, diffusion_models/arefiner.gguf,"
            "\ncheckpoints/zbase.safetensors, diffusion_models/arefiner.gguf \u00a0"
        ),
        filename="%model",
    )
    assert hash_file.call_count == 2
    text = read_parameters(host.root / "zbase.png")
    assert "Model: zbase" in text
    assert f"Model hash: {sha(b'base')}" in text


def test_backslash_model_references_use_the_full_path(host):
    host.add_model("checkpoints", "family/base.v2.safetensors", b"selected file")
    host.add_model("checkpoints", "base.v2.safetensors", b"wrong file")
    host.run(models=r"checkpoints\family\base.v2.safetensors", filename="%model")
    text = read_parameters(host.root / "base.v2.png")
    assert "Model: base.v2" in text
    assert f"Model hash: {sha(b'selected file')}" in text


def test_saver_hashes_any_file_without_host_model_registries(host, monkeypatch, caplog):
    reference = "other/assets/reference.data"
    content = b"\x00arbitrary file contents\xff"
    path = Path(host.folders.models_dir) / reference
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    for attribute in ("get_filename_list", "get_full_path", "supported_pt_extensions"):
        monkeypatch.delattr(host.folders, attribute)

    host.run(models=reference, filename="%model")

    text = read_parameters(host.root / "reference.png")
    assert "Model: reference" in text
    assert f"Model hash: {sha(content)}" in text
    assert hashes_in(text) == {"model": sha(content)}
    assert reference not in text
    assert not caplog.records


def test_missing_exact_model_does_not_fall_back_to_other_categories(host, caplog):
    host.add_model("checkpoints", "base.safetensors", b"wrong file")
    host.add_model("loras", "base.safetensors", b"also wrong")
    host.add_model("diffusion_models", "nested/base.safetensors", b"nested wrong")

    host.run(models="diffusion_models/base.safetensors", filename="%model")

    text = read_parameters(host.root / "base.png")
    assert "Model: base" in text
    assert "Model hash:" not in text
    assert "Hashes:" not in text
    assert "no matching model file" in caplog.text
    assert "diffusion_models/base.safetensors" in caplog.text


def test_bare_model_filename_means_file_directly_in_models_directory(host):
    root = Path(host.folders.models_dir)
    root.mkdir()
    (root / "base.safetensors").write_bytes(b"exact file")
    host.add_model("checkpoints", "base.safetensors", b"wrong file")

    host.run(models="base.safetensors")

    text = read_parameters(host.root / "image.png")
    assert f"Model hash: {sha(b'exact file')}" in text


def test_missing_and_unreadable_model_files_warn(host, caplog, monkeypatch):
    host.add_model("checkpoints", "base.safetensors")
    monkeypatch.setattr(saver, "file_hash", Mock(side_effect=PermissionError("denied")))
    host.run(models="checkpoints/base.safetensors, checkpoints/missing.safetensors")
    assert (host.root / "image.png").exists()
    assert "denied" in caplog.text
    assert "no matching model file" in caplog.text


def test_model_hashes_are_cached_until_the_file_changes(host, monkeypatch):
    path = host.add_model("checkpoints", "base.safetensors", b"first")
    digest = Mock(wraps=hashlib.file_digest)
    monkeypatch.setattr(hashlib, "file_digest", digest)
    for _ in range(2):
        host.run(models="checkpoints/base.safetensors")
    assert digest.call_count == 1

    path.write_bytes(b"other")
    # Same size; move mtime explicitly because filesystem clocks can be coarse.
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    host.run(models="checkpoints/base.safetensors")

    assert digest.call_count == 2
    assert f"Model hash: {sha(b'other')}" in read_parameters(host.root / "image_2.png")
    assert list(path.parent.iterdir()) == [path]


def test_additional_hashes_without_models(host):
    host.run(
        models=" , \n",
        additional_hashes=" \tsha256:Ab+/=\n, \u2003arbitrary-digest\u00a0",
    )
    text = read_parameters(host.root / "image.png")
    assert "Model:" not in text
    assert hashes_in(text) == {
        "hash:sha256:Ab+/=": "sha256:Ab+/=",
        "hash:arbitrary-digest": "arbitrary-digest",
    }
