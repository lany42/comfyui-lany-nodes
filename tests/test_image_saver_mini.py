# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Real CPU tensor/file tests with small doubles for the V3 host boundary."""

import hashlib
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from importlib import import_module
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest
import torch
from PIL import Image

import comfyui_lany_nodes.nodes
from comfyui_lany_nodes import image_saver as saver

PICKER_CATEGORIES = ("checkpoints", "diffusion_models", "loras")


@pytest.fixture
def host(tmp_path):
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

    def socket_type(io_type):
        def socket(id, **options):
            return SimpleNamespace(id=id, io_type=io_type, **options)

        return SimpleNamespace(
            Input=socket,
            Output=socket,
            Type=object,
        )

    api = ModuleType("comfy_api")
    latest = ModuleType("comfy_api.latest")
    latest.io = SimpleNamespace(
        ComfyNode=type("ComfyNode", (), {}),
        Schema=SimpleNamespace,
        Hidden=SimpleNamespace(prompt="PROMPT", extra_pnginfo="EXTRA_PNGINFO"),
        NodeOutput=lambda *values, ui=None: SimpleNamespace(result=values, ui=ui),
        **{
            name: socket_type(kind)
            for name, kind in [
                ("Image", "IMAGE"),
                ("String", "STRING"),
                ("Int", "INT"),
                ("Boolean", "BOOLEAN"),
                ("Combo", "COMBO"),
                ("MultiCombo", "COMBO"),
            ]
        },
    )
    api.latest = latest
    with (
        patch.dict(
            sys.modules,
            {"comfy_api": api, "comfy_api.latest": latest, "folder_paths": folders},
        ),
        patch.dict(vars(comfyui_lany_nodes.nodes)),
    ):
        module_name = "comfyui_lany_nodes.nodes.image_saver_mini"
        model_names_module = "comfyui_lany_nodes.nodes.model_names"
        sys.modules.pop(module_name, None)
        sys.modules.pop(model_names_module, None)
        node = import_module(module_name).ImageSaverMini
        model_names = import_module(model_names_module).ModelNames
        node.hidden = SimpleNamespace(
            prompt={"1": {"class_type": "Test", "inputs": {"text": "海"}}},
            extra_pnginfo={"workflow": {"nodes": [{"id": 1}]}, "extra": {"a": 1}},
        )

        def run(**kwargs):
            inputs = {
                "images": torch.zeros((1, 3, 5, 3)),
                "filename": "image",
                "positive": "positive",
                "negative": "negative",
            }
            return node.execute(**(inputs | kwargs))

        saver._cached_hash.cache_clear()
        yield SimpleNamespace(
            node=node,
            model_names=model_names,
            run=run,
            root=root,
            folders=folders,
            paths=paths,
            add_model=add_model,
        )
        sys.modules.pop(module_name, None)
        sys.modules.pop(model_names_module, None)
        saver._cached_hash.cache_clear()


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


def test_schema_and_forced_prompts(host):
    schema = host.node.define_schema()
    assert schema.node_id == "LanyNodes_ImageSaverMini"
    assert schema.display_name == "ImageSaverMini"
    assert schema.category == "Lany Nodes"
    assert schema.outputs == []
    assert schema.is_output_node is True
    assert not getattr(schema, "is_input_list", False)
    assert schema.hidden == ["PROMPT", "EXTRA_PNGINFO"]
    assert [(input.id, input.io_type) for input in schema.inputs] == [
        ("format", "COMBO"),
        ("images", "IMAGE"),
        ("path", "STRING"),
        ("filename", "STRING"),
        ("models", "STRING"),
        ("positive", "STRING"),
        ("negative", "STRING"),
        ("seed", "INT"),
        ("steps", "INT"),
        ("width", "INT"),
        ("height", "INT"),
        ("time_format", "STRING"),
        ("jpg_quality", "INT"),
        ("optimize_png", "BOOLEAN"),
        ("png_embed_workflow", "BOOLEAN"),
        ("additional_hashes", "STRING"),
    ]
    fields = {input.id: input for input in schema.inputs}
    for name in ("positive", "negative"):
        assert fields[name].force_input is True
        assert not getattr(fields[name], "optional", False)
        assert not getattr(fields[name], "multiline", False)
        assert not hasattr(fields[name], "default")
    assert fields["format"].options == ["png", "jpg"]
    assert fields["format"].socketless is True
    assert fields["format"].default == "png"
    assert fields["filename"].default == "%time_%model_%seed"
    assert fields["path"].default == ""
    assert fields["time_format"].default == "%Y-%m-%d-%H%M%S"
    for name, default, minimum, maximum in [
        ("seed", 0, 0, 2**64 - 1),
        ("steps", 20, 0, 10000),
        ("width", 0, 0, 2**53 - 1),
        ("height", 0, 0, 2**53 - 1),
        ("jpg_quality", 80, 1, 100),
    ]:
        field = fields[name]
        assert (field.default, field.min, field.max, field.step) == (
            default,
            minimum,
            maximum,
            1,
        ), name
    for name in ("seed", "steps"):
        assert fields[name].control_after_generate is False
    assert fields["optimize_png"].default is False
    assert fields["png_embed_workflow"].default is True
    with pytest.raises(TypeError, match="positive.*negative"):
        host.node.execute(torch.zeros((1, 3, 5, 3)))


@pytest.mark.parametrize("format", ["png", "jpg"])
@pytest.mark.parametrize(
    "prompts",
    [
        ("", ""),
        ("café déjà vu", "jalapeño"),
        ("海 🌊", "🌧️"),
        ("  晴れ\n<lora:keep:1> STYLE(x)  ", "\nembedding:keep\n"),
    ],
)
def test_generation_metadata_pins_comfyui_parameter_minimums(host, format, prompts):
    positive, negative = prompts
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
    assert text == (
        f"{positive}\nNegative prompt: {negative}\n"
        "Steps: 32, Seed: 18446744073709551615, Size: 5x3, Version: ComfyUI"
    )


@pytest.mark.parametrize("embed", [True, False])
def test_png_workflow_and_reserved_metadata(host, embed):
    host.node.hidden.extra_pnginfo.update(parameters="must not replace", prompt="wrong")
    host.run(png_embed_workflow=embed)
    metadata = read_png_metadata(host.root / "image.png")
    assert metadata["parameters"].startswith("positive\nNegative prompt:")
    if embed:
        assert {"parameters", "prompt", "workflow"} <= metadata.keys()
        assert json.loads(metadata["prompt"]) == host.node.hidden.prompt
        assert (
            json.loads(metadata["workflow"])
            == host.node.hidden.extra_pnginfo["workflow"]
        )
        assert json.loads(metadata["extra"]) == {"a": 1}
    else:
        assert set(metadata) == {"parameters"}


def test_png_without_browser_workflow(host):
    host.node.hidden.prompt = host.node.hidden.extra_pnginfo = None
    host.run()
    assert set(read_png_metadata(host.root / "image.png")) == {"parameters"}


def test_jpg_never_serializes_workflow(host):
    host.node.hidden.prompt = object()
    host.node.hidden.extra_pnginfo = {"workflow": object()}
    host.run(format="jpg", png_embed_workflow=True)
    with Image.open(host.root / "image.jpg") as image:
        exif = image.getexif()
        assert set(exif) == {0x8769}
        assert set(exif.get_ifd(0x8769)) == {0x9286}
        assert image.size == (5, 3)


def test_jpg_exif_limit_fails_without_saving(host):
    with pytest.raises(ValueError, match="too large.*PNG"):
        host.run(format="jpg", positive="a" * 33000)
    assert not host.root.exists()
    # PNG has no JPEG APP1 limit and keeps the whole prompt.
    host.run(positive="a" * 33000)
    assert read_parameters(host.root / "image.png").startswith("a" * 33000)


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
    base, refiner, ink = [
        hashlib.sha256(data).hexdigest()[:10] for _, _, data in resources
    ]
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
    host.node.hidden.prompt = prompt
    host.node.hidden.extra_pnginfo = {"workflow": workflow}
    samples = []
    for (
        name,
        models,
        additional,
        positive,
        embed,
        expected_model,
        expected_hash,
        expected_hashes,
    ) in [
        (
            "complete",
            "checkpoints/base.safetensors,diffusion_models/refiner.gguf,loras/ink.safetensors",
            f"{base},{manual},{manual}",
            "café 海 🌊",
            True,
            "base",
            base,
            all_hashes,
        ),
        (
            "without_workflow",
            "checkpoints/base.safetensors,diffusion_models/refiner.gguf,loras/ink.safetensors",
            manual,
            "café 海 🌊",
            False,
            "base",
            base,
            all_hashes,
        ),
        (
            "manual_only",
            "",
            f"{manual},custom-digest",
            "manual",
            True,
            None,
            None,
            {f"hash:{manual}": manual, "hash:custom-digest": "custom-digest"},
        ),
        (
            "missing_primary",
            "checkpoints/missing.safetensors,diffusion_models/refiner.gguf",
            "",
            "missing",
            True,
            "missing",
            None,
            {f"hash:{refiner}": refiner},
        ),
        ("long_unicode", "", "", "一" * 600 + " 海 🌊", True, None, None, None),
    ]:
        host.run(
            format=format,
            filename=name,
            models=models,
            additional_hashes=additional,
            positive=positive,
            negative="negative",
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
                "metadata": {
                    "prompt": positive,
                    "negativePrompt": "negative",
                    "seed": 42,
                    "steps": 27,
                    "width": 512,
                    "height": 768,
                    "Model": expected_model,
                    "Model hash": expected_hash,
                    "hashes": expected_hashes,
                },
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


@pytest.mark.parametrize("shape", [(3, 5, 3), (1, 3, 5, 3), (2, 3, 5, 4), (2, 3, 5, 1)])
def test_image_shapes_pixels_and_batch_names(host, shape):
    images = (
        torch.linspace(-0.5, 1.5, int(np.prod(shape))).reshape(shape).requires_grad_()
    )
    result = host.run(images=images)
    assert result.result == ()
    batch = images.unsqueeze(0) if images.ndim == 3 else images
    names = ["image.png", *(f"image_{i}.png" for i in range(1, len(batch)))]
    assert sorted(path.name for path in host.root.iterdir()) == names
    for filename, tensor in zip(names, batch, strict=True):
        expected = np.clip(tensor.detach().numpy() * 255, 0, 255).astype(np.uint8)
        if shape[-1] == 1:
            expected = expected[..., 0]
        with Image.open(host.root / filename) as image:
            np.testing.assert_array_equal(np.asarray(image), expected)
            assert image.size == (5, 3)


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
        ("jpg", "jpg_quality", 37, "quality"),
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


@pytest.mark.parametrize(
    "shape", [(0, 2, 3, 3), (1, 0, 3, 3), (2, 3), (1, 2, 3, 2), (1, 1, 2, 3, 3)]
)
def test_invalid_shapes(host, shape):
    with pytest.raises(ValueError, match="nonempty HWC"):
        host.run(images=torch.zeros(shape))
    assert not host.root.exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"seed": -1},
        {"seed": True},
        {"steps": 10001},
        {"width": -1},
        {"height": 1.5},
        {"format": "webp"},
        {"format": "jpg", "jpg_quality": 101},
        {"positive": None},
        {"models": None},
        {"additional_hashes": None},
        {"filename": None},
        {"path": None},
        {"time_format": None},
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


def test_native_list_mapping_invocations_and_collisions(host):
    # ComfyUI maps each list entry to a separate call; no whole-schema list mode.
    for index, image in enumerate([torch.zeros((2, 3, 3)), torch.ones((1, 4, 6, 3))]):
        host.run(images=image, seed=index)
    assert "Seed: 0, Size: 3x2" in read_parameters(host.root / "image.png")
    assert "Seed: 1, Size: 6x4" in read_parameters(host.root / "image_1.png")
    original = (host.root / "image.png").read_bytes()
    host.run(images=torch.zeros((2, 2, 3, 3)))
    assert (host.root / "image.png").read_bytes() == original
    assert (host.root / "image_2.png").exists()
    assert (host.root / "image_3.png").exists()


@pytest.mark.parametrize("format", ["png", "jpg"])
@pytest.mark.parametrize(
    ("existing", "expected"),
    [
        (["image", "image_1", "image_2"], "image_3"),
        (["image", "image_9", "image_10"], "image_11"),
        (["image_2", "image_8"], "image_9"),
        (["image_01", "image_02"], "image_3"),
        (["image_9", "image_100"], "image_101"),
    ],
)
def test_filenames_continue_after_highest_numeric_suffix(
    host, format, existing, expected
):
    host.root.mkdir()
    for name in existing:
        (host.root / f"{name}.{format}").write_bytes(b"existing file")

    host.run(format=format)

    assert {path.stem for path in host.root.iterdir()} == {*existing, expected}
    assert "Steps: 20" in read_parameters(host.root / f"{expected}.{format}")
    for name in existing:
        assert (host.root / f"{name}.{format}").read_bytes() == b"existing file"


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


def test_concurrent_saves_do_not_overwrite(host):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: host.run(), range(8)))
    files = list(host.root.iterdir())
    assert len(files) == 8
    for path in files:
        with Image.open(path) as image:
            image.verify()


def test_filename_interpolation_and_directories(host, monkeypatch):
    now = datetime(2026, 9, 26, 12, 34, 56).astimezone()
    monkeypatch.setattr(
        sys.modules[host.node.__module__], "datetime", Mock(now=Mock(return_value=now))
    )
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
    ("path", "directory"),
    [
        ("", ""),
        ("my_dir", "my_dir"),
        ("my_dir///", "my_dir"),
        ("my.dir/海 images/", "my.dir/海 images"),
        ("portraits\\day\\", "portraits/day"),
    ],
)
def test_output_path_is_separate_from_filename(host, path, directory):
    host.run(path=path, filename="Image_01-test")
    assert (host.root / directory / "Image_01-test.png").exists()


@pytest.mark.parametrize("format", ["png", "jpg"])
@pytest.mark.parametrize(
    "filename", ["Image.v2-test_01", ".image", "image.", "image.png", "%model"]
)
def test_periods_in_filenames_and_model_tokens(host, format, filename):
    host.add_model("checkpoints", "base.v2.safetensors")
    host.run(
        images=torch.zeros((2, 3, 5, 3)),
        filename=filename,
        models="checkpoints/base.v2.safetensors",
        format=format,
    )
    stem = "base.v2" if filename == "%model" else filename
    for suffix in ("", "_1"):
        saved = host.root / f"{stem}{suffix}.{format}"
        assert "Model: base.v2" in read_parameters(saved)


@pytest.mark.parametrize(
    "filename",
    [
        "",
        " ",
        " image",
        "image ",
        ".",
        "..",
        "my image",
        "my?:image",
        "image\n",
        "海",
        "../escape",
        "nested/../../escape",
        "/tmp/escape",
        "C:/escape",
        "C:escape",
        r"..\escape",
        "%basemodelname",
        "%unknown",
        "%time_format",
        "%time_format<%H",
        "%counter<03>_%cfg_%Other.seed%",
    ],
)
def test_invalid_filename_fails_before_hashing(host, monkeypatch, filename):
    hash_models = Mock()
    monkeypatch.setattr(saver, "model_hashes", hash_models)
    with pytest.raises(ValueError, match="filename"):
        host.run(filename=filename)
    hash_models.assert_not_called()
    assert not host.root.exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"filename": "%model"},
        {"filename": "%time", "time_format": "."},
        {"filename": "%time_format<..>"},
        {"filename": "%time", "time_format": "%H:%M"},
        {"filename": "%time", "time_format": "%Y/%m/%d"},
        {"filename": "%time_format<%H %M>"},
        {"filename": "%time_format<%n>"},
        {"filename": "%time_format<>"},
    ],
)
def test_invalid_expanded_filename_fails_before_hashing(host, monkeypatch, kwargs):
    hash_models = Mock()
    monkeypatch.setattr(saver, "model_hashes", hash_models)
    with pytest.raises(ValueError, match="expanded filename"):
        host.run(**kwargs)
    hash_models.assert_not_called()
    assert not host.root.exists()


@pytest.mark.parametrize(
    "path",
    [
        ".",
        "./",
        "./nested",
        "../escape",
        "nested/../escape",
        "nested/./escape",
        "nested/..",
        "/",
        "/tmp/escape",
        "C:/escape",
        "C:escape",
        "nested/C:escape",
        r"..\escape",
        r"nested\..\escape",
        r"\\server\share",
    ],
)
def test_invalid_path_fails_before_hashing(host, monkeypatch, path):
    hash_models = Mock()
    monkeypatch.setattr(saver, "model_hashes", hash_models)
    with pytest.raises(ValueError, match="path.*relative markers or anchors"):
        host.run(path=path)
    hash_models.assert_not_called()
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


def test_output_path_allows_symlinks_within_output(host):
    directory = host.root / "nested"
    directory.mkdir(parents=True)
    (host.root / "link").symlink_to(directory, target_is_directory=True)
    host.run(path="link/")
    assert (directory / "image.png").exists()


@pytest.mark.parametrize("format", ["png", "jpg"])
def test_model_hashes_and_metadata(host, format):
    host.add_model("checkpoints", "base.v2.safetensors", b"base")
    host.add_model("diffusion_models", "refiner.gguf", b"refiner")
    host.add_model("loras", "ink.safetensors", b"ink")
    host.run(
        models=(
            " checkpoints/base.v2.safetensors, diffusion_models/refiner.gguf, "
            "loras/ink.safetensors, "
        ),
        additional_hashes=f"ABCDEF0123, {hashlib.sha256(b'base').hexdigest()[:10]}",
        format=format,
    )
    text = read_parameters(host.root / f"image.{format}")
    assert "Model: base.v2" in text
    assert f"Model hash: {hashlib.sha256(b'base').hexdigest()[:10]}" in text
    hashes = json.loads(text.split("Hashes: ")[1].split(", Version:")[0])
    expected = [
        hashlib.sha256(content).hexdigest()[:10] for content in (b"refiner", b"ink")
    ]
    assert hashes == {
        "model": hashlib.sha256(b"base").hexdigest()[:10],
        **{f"hash:{digest}": digest for digest in [*expected, "ABCDEF0123"]},
    }


@pytest.mark.parametrize("format", ["png", "jpg"])
@pytest.mark.parametrize(
    "prefix", ["", "family/", "family\\", "family/nested/", "版本/art styles/"]
)
def test_model_names_output_saves_images(host, monkeypatch, caplog, format, prefix):
    resources = [
        ("checkpoints", f"{prefix}base.v2.safetensors", b"base"),
        ("diffusion_models", f"{prefix}refiner.gguf", b"refiner"),
        ("loras", f"{prefix}ink.safetensors", b"ink"),
        ("loras", "detail.safetensors", b"detail"),
    ]
    for category, name, content in resources:
        host.add_model(category, name, content)
        if prefix and name.startswith(prefix):
            host.add_model(
                category, name.replace("\\", "/").rsplit("/", 1)[-1], b"wrong file"
            )
    monkeypatch.setattr(
        host.folders,
        "get_filename_list",
        lambda category: [name for folder, name, _ in resources if folder == category],
    )
    schema = host.model_names.define_schema()
    references = [
        category + "/" + name.replace("\\", "/") for category, name, _ in resources
    ]
    assert references[0] in schema.inputs[0].options
    assert references[1] in schema.inputs[0].options
    assert references[2] in schema.inputs[1].options
    (models,) = host.model_names.execute(
        references[:2],
        references[2:],
    ).result
    assert models == ",".join(references)
    now = datetime(2026, 9, 26, 12, 34, 56).astimezone()
    monkeypatch.setattr(
        sys.modules[host.node.__module__], "datetime", Mock(now=Mock(return_value=now))
    )

    result = host.node.execute(
        torch.zeros((1, 3, 5, 3)), "positive", "negative", models=models, format=format
    )

    assert result.result == () and result.ui is None
    text = read_parameters(host.root / f"2026-09-26-123456_base.v2_0.{format}")
    assert "Model: base.v2" in text
    if prefix:
        assert prefix not in text
    hashes = json.loads(text.split("Hashes: ")[1].split(", Version:")[0])
    primary, *others = [
        hashlib.sha256(content).hexdigest()[:10] for _, _, content in resources
    ]
    assert hashes == {
        "model": primary,
        **{f"hash:{digest}": digest for digest in others},
    }
    assert f"Model hash: {primary}" in text
    assert not caplog.records


@pytest.mark.parametrize("prefix", ["", "family/", "family\\"])
def test_missing_primary_preserves_name_and_other_hashes(host, caplog, prefix):
    host.add_model("checkpoints", "base.safetensors", b"one")
    host.add_model("loras", "ink.custom", b"ink")
    host.run(
        models=(
            f"checkpoints/{prefix}missing.safetensors, "
            "checkpoints/base.safetensors, loras/ink.custom"
        ),
        additional_hashes="ABCDEF",
    )
    text = read_parameters(host.root / "image.png")
    assert "Model: missing" in text
    hashes = json.loads(text.split("Hashes: ")[1].split(", Version:")[0])
    expected = [
        hashlib.sha256(content).hexdigest()[:10] for content in (b"one", b"ink")
    ]
    assert hashes == {f"hash:{digest}": digest for digest in [*expected, "ABCDEF"]}
    assert "Model hash:" not in text
    assert "no matching model file" in caplog.text


@pytest.mark.parametrize(
    "reference",
    [
        "./base.safetensors",
        "../base.safetensors",
        "old/../base.safetensors",
        "/base.safetensors",
        "base.safetensors/",
        "old//base.safetensors",
        "old/./base.safetensors",
        "old\0/base.safetensors",
        "old\n/base.safetensors",
        r".\base.safetensors",
        r"..\base.safetensors",
        r"C:\base.safetensors",
        "C:/base.safetensors",
        "C:base.safetensors",
        r"\\server\share\base.safetensors",
        ".",
        "..",
        "base",
        "base.",
        ".safetensors",
    ],
)
def test_invalid_model_paths_and_missing_suffixes_fail_at_node_input(
    host, monkeypatch, reference
):
    hash_models = Mock()
    monkeypatch.setattr(saver, "model_hashes", hash_models)
    with pytest.raises(ValueError, match="models"):
        host.run(models=f"valid.safetensors, {reference}")
    hash_models.assert_not_called()
    assert not host.root.exists()


def test_model_lookup_does_not_search_subfolders(host, caplog):
    host.add_model("checkpoints", "other/base.safetensors", b"base")
    assert saver.model_hashes({"base.safetensors"}, set(), host.folders) == {}
    assert "no matching model file" in caplog.text


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
    assert f"Model hash: {hashlib.sha256(b'base').hexdigest()[:10]}" in text


@pytest.mark.parametrize(
    "other", ["checkpoints/other/base.safetensors", "loras/base.safetensors"]
)
def test_conflicting_model_filenames_fail_before_hashing(host, monkeypatch, other):
    hash_models = Mock()
    monkeypatch.setattr(saver, "model_hashes", hash_models)

    with pytest.raises(ValueError, match="unique filenames across distinct paths"):
        host.run(models=f"checkpoints/base.safetensors,{other}")

    hash_models.assert_not_called()
    assert not host.root.exists()


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_model_hashes_use_paths_for_lookup_and_filenames_for_keys(host, separator):
    reference = f"checkpoints{separator}family{separator}base.v2.safetensors"
    host.add_model("checkpoints", "family/base.v2.safetensors", b"selected file")
    host.add_model("checkpoints", "base.v2.safetensors", b"wrong file")

    assert saver.model_hashes({reference}, set(), host.folders) == {
        "base.v2.safetensors": hashlib.sha256(b"selected file").hexdigest()[:10]
    }


@pytest.mark.parametrize("category", PICKER_CATEGORIES)
def test_model_lookup_uses_only_the_exact_path(host, monkeypatch, caplog, category):
    for folder in PICKER_CATEGORIES:
        host.add_model(folder, "base.safetensors", folder.encode())
    monkeypatch.setattr(
        host.folders,
        "get_full_path",
        Mock(side_effect=AssertionError("category lookup")),
    )
    assert saver.model_hashes(
        {f"{category}/base.safetensors"}, set(), host.folders
    ) == {"base.safetensors": hashlib.sha256(category.encode()).hexdigest()[:10]}
    host.run(models=f"{category}/base.safetensors", filename="%model")
    text = read_parameters(host.root / "base.png")
    assert f"Model hash: {hashlib.sha256(category.encode()).hexdigest()[:10]}" in text
    assert "Model: base" in text
    assert f"{category}/" not in text
    assert not caplog.records


@pytest.mark.parametrize("format", ["png", "jpg"])
@pytest.mark.parametrize(
    "reference", ["vae/decoder.bin", "other/assets/reference.data", "payload.txt"]
)
def test_saver_hashes_files_without_category_or_extension_registration(
    host, monkeypatch, caplog, format, reference
):
    content = b"\x00arbitrary file contents\xff"
    path = Path(host.folders.models_dir) / reference
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    for attribute in ("get_filename_list", "get_full_path", "supported_pt_extensions"):
        monkeypatch.delattr(host.folders, attribute)

    host.run(models=reference, filename="%model", format=format)

    text = read_parameters(host.root / f"{path.stem}.{format}")
    digest = hashlib.sha256(content).hexdigest()[:10]
    assert f"Model: {path.stem}" in text
    assert f"Model hash: {digest}" in text
    hashes = json.loads(text.split("Hashes: ")[1].split(", Version:")[0])
    assert hashes == {"model": digest}
    assert reference not in text
    assert not caplog.records


def test_missing_exact_model_does_not_fall_back_to_other_categories(host, caplog):
    host.add_model("checkpoints", "base.safetensors", b"wrong file")
    host.add_model("loras", "base.safetensors", b"also wrong")

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
    assert f"Model hash: {hashlib.sha256(b'exact file').hexdigest()[:10]}" in text


def test_model_lookup_resolves_from_models_directory(host, tmp_path, monkeypatch):
    path = host.add_model("checkpoints", "base.safetensors")
    monkeypatch.chdir(tmp_path)
    resolved = saver._resolve_model("checkpoints/base.safetensors", host.folders)
    assert resolved.is_absolute()
    assert resolved == path


def test_missing_and_unreadable_model_files_warn(host, caplog, monkeypatch):
    host.add_model("checkpoints", "base.safetensors")
    monkeypatch.setattr(saver, "file_hash", Mock(side_effect=PermissionError("denied")))
    host.run(models="checkpoints/base.safetensors, checkpoints/missing.safetensors")
    assert (host.root / "image.png").exists()
    assert "denied" in caplog.text
    assert "no matching model file" in caplog.text


def test_hash_cache_invalidation_and_no_sidecars(host):
    path = host.add_model("checkpoints", "base.safetensors", b"first")
    first = saver.file_hash(path)
    assert saver.file_hash(path) == first
    assert saver._cached_hash.cache_info().hits == 1
    path.write_bytes(b"other")  # Same length; mtime/ctime also participate in the key.
    assert saver.file_hash(path) == hashlib.sha256(b"other").hexdigest()[:10] != first
    assert list(path.parent.iterdir()) == [path]


def test_hashes_deduplicate_and_preserve_additional_digests(host, caplog):
    host.add_model("checkpoints", "base.safetensors", b"base")
    host.add_model("loras", "copy.safetensors", b"base")
    digest = hashlib.sha256(b"base").hexdigest()[:10]
    additional = {digest, "ABCDEF0123", "abcdef0123", "f" * 64}
    hashes = saver.model_hashes(
        {"checkpoints/base.safetensors", "loras/copy.safetensors"},
        additional,
        host.folders,
    )
    assert hashes == {
        "base.safetensors": digest,
        "copy.safetensors": digest,
        "hash:ABCDEF0123": "ABCDEF0123",
        "hash:abcdef0123": "abcdef0123",
        f"hash:{'f' * 64}": "f" * 64,
    }
    assert not caplog.records


@pytest.mark.parametrize(
    ("additional", "expected"),
    [
        (" , \n", set()),
        ("ABCDEF, ABCDEF,\n123456", {"ABCDEF", "123456"}),
        (
            " \tsha256:Ab+/=\n, \u2003arbitrary-digest\u00a0",
            {"sha256:Ab+/=", "arbitrary-digest"},
        ),
    ],
)
def test_additional_hashes_without_models(host, additional, expected):
    host.run(models=" , \n", additional_hashes=additional)
    text = read_parameters(host.root / "image.png")
    assert "Model:" not in text
    if expected:
        hashes = json.loads(text.split("Hashes: ")[1].split(", Version:")[0])
        assert hashes == {f"hash:{digest}": digest for digest in expected}
    else:
        assert "Hashes:" not in text


@pytest.mark.parametrize("input_name", ["models", "additional_hashes"])
@pytest.mark.parametrize(
    "whitespace", [" ", "\t", "\n", "\r", "\v", "\f", "\u00a0", "\u2003"]
)
def test_internal_whitespace_fails_at_node_input(
    host, monkeypatch, caplog, input_name, whitespace
):
    hash_models = Mock()
    monkeypatch.setattr(saver, "model_hashes", hash_models)
    with pytest.raises(ValueError, match=f"{input_name}.*internal whitespace"):
        host.run(
            **{
                input_name: f"valid.safetensors, \tABC{whitespace}DEF.safetensors \n, last.ckpt"
            }
        )
    hash_models.assert_not_called()
    assert not host.root.exists()
    assert not caplog.records


@pytest.mark.parametrize("name", ['bad"name.safetensors', "bad:name.safetensors"])
@pytest.mark.parametrize("primary", [True, False])
def test_model_metadata_delimiters_fail_at_node_input(host, monkeypatch, name, primary):
    hash_models = Mock()
    monkeypatch.setattr(saver, "model_hashes", hash_models)
    models = f"{name}, valid.safetensors" if primary else f"valid.safetensors, {name}"
    with pytest.raises(ValueError, match="models.*commas, colons, quotes, or newlines"):
        host.run(models=models)
    hash_models.assert_not_called()
    assert not host.root.exists()


@pytest.mark.parametrize(
    "name", ["海.safetensors", "bad>name.safetensors", "bad%name.safetensors"]
)
def test_model_names_share_filename_character_restrictions(host, monkeypatch, name):
    hash_models = Mock()
    monkeypatch.setattr(saver, "model_hashes", hash_models)
    with pytest.raises(ValueError, match="models.*ASCII letters"):
        host.model_names.execute([f"nested/{name}"], [])
    with pytest.raises(ValueError, match="models.*ASCII letters"):
        host.run(models=name)
    hash_models.assert_not_called()
    assert not host.root.exists()
