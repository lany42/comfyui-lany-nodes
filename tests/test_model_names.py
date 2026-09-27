# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Formatting contracts tested with isolated ComfyUI API and directory doubles."""

import sys
from importlib import import_module
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

import comfyui_lany_nodes.nodes


@pytest.fixture
def model_names():
    def socket_type(io_type):
        def socket(id, **options):
            return SimpleNamespace(id=id, io_type=io_type, **options)

        return SimpleNamespace(Input=socket, Output=socket)

    api = ModuleType("comfy_api")
    latest = ModuleType("comfy_api.latest")
    latest.io = SimpleNamespace(
        ComfyNode=type("ComfyNode", (), {}),
        Schema=SimpleNamespace,
        MultiCombo=socket_type("COMBO"),
        String=socket_type("STRING"),
        NodeOutput=lambda *values: SimpleNamespace(result=values),
    )
    api.latest = latest
    with (
        patch.dict(sys.modules, {"comfy_api": api, "comfy_api.latest": latest}),
        patch.dict(vars(comfyui_lany_nodes.nodes)),
    ):
        sys.modules.pop("comfyui_lany_nodes.nodes.model_names", None)
        yield import_module("comfyui_lany_nodes.nodes.model_names").ModelNames
        sys.modules.pop("comfyui_lany_nodes.nodes.model_names", None)


def test_schema_discovers_registered_filenames(model_names, monkeypatch):
    filenames = {
        "checkpoints": ["zeta.safetensors", "shared.safetensors"],
        "diffusion_models": ["shared.safetensors", "family/alpha.safetensors"],
        "loras": ["detail.safetensors", "styles/ink.safetensors"],
        "vae": ["decoder.safetensors"],
    }
    folder_paths = ModuleType("folder_paths")
    folder_paths.models_dir = "/models"
    folder_paths.get_filename_list = lambda folder: filenames[folder]
    folder_paths.get_full_path = lambda folder, name: f"/models/{folder}/{name}"
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)

    schema = model_names.define_schema()
    assert schema.node_id == "LanyNodes_ModelNames"
    assert schema.display_name == "ModelNames"
    assert schema.category == "Lany Nodes"
    assert [(item.id, item.io_type) for item in schema.inputs] == [
        ("models", "COMBO"),
        ("loras", "COMBO"),
    ]
    assert schema.inputs[0].options == [
        "checkpoints/shared.safetensors",
        "checkpoints/zeta.safetensors",
        "diffusion_models/family/alpha.safetensors",
        "diffusion_models/shared.safetensors",
    ]
    assert schema.inputs[1].options == [
        "loras/detail.safetensors",
        "loras/styles/ink.safetensors",
    ]
    for item in schema.inputs:
        assert item.default == []
        assert item.socketless is True
        assert item.chip is True
        assert item.control_after_generate is False
        assert item.placeholder
    assert [(item.id, item.io_type) for item in schema.outputs] == [
        ("MODEL_NAMES", "STRING"),
    ]

    # Schema refresh picks up host changes without caching our own directory list.
    filenames["diffusion_models"].append("new.safetensors")
    refreshed = model_names.define_schema()
    assert "diffusion_models/new.safetensors" in refreshed.inputs[0].options
    assert "diffusion_models/new.safetensors" not in schema.inputs[0].options


def test_schema_uses_actual_paths_relative_to_models_directory(
    model_names, monkeypatch, tmp_path
):
    root = tmp_path / "models"
    paths = {
        "checkpoints": {"base.safetensors": root / "library/base.safetensors"},
        "diffusion_models": {"refiner.gguf": root / "unet/refiner.gguf"},
        "loras": {
            "ink.safetensors": root / "styles/ink.safetensors",
            "external.safetensors": tmp_path / "external.safetensors",
            "missing.safetensors": None,
        },
    }
    folders = ModuleType("folder_paths")
    folders.models_dir = str(root)
    folders.get_filename_list = lambda category: list(paths[category])
    folders.get_full_path = lambda category, name: paths[category][name]
    monkeypatch.setitem(sys.modules, "folder_paths", folders)

    schema = model_names.define_schema()

    assert schema.inputs[0].options == ["library/base.safetensors", "unet/refiner.gguf"]
    assert schema.inputs[1].options == ["styles/ink.safetensors"]


def test_schema_allows_empty_directories(model_names, monkeypatch):
    folder_paths = ModuleType("folder_paths")
    folder_paths.get_filename_list = lambda folder: []
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)
    schema = model_names.define_schema()
    assert all(item.options == item.default == [] for item in schema.inputs)


@pytest.mark.parametrize(
    ("models", "loras", "expected"),
    [
        ([], [], ""),
        (["model.safetensors"], [], "model.safetensors"),
        ([], ["ink.safetensors"], "ink.safetensors"),
        (
            ["z/base.safetensors", "a/refiner.ckpt"],
            ["styles/ink.safetensors", "detail.safetensors"],
            (
                "z/base.safetensors,a/refiner.ckpt,"
                "styles/ink.safetensors,detail.safetensors"
            ),
        ),
        (
            ["版本/model_v2.1.safetensors", "alt/model.gguf", "model.ckpt"],
            [
                "艺术 styles/ink-v1.2.safetensors",
                r"styles\detail.safetensors",
            ],
            (
                "版本/model_v2.1.safetensors,alt/model.gguf,model.ckpt,"
                "艺术 styles/ink-v1.2.safetensors,styles\\detail.safetensors"
            ),
        ),
        (
            ["one/base.safetensors", r"one\base.safetensors"],
            ["one/base.safetensors"],
            "one/base.safetensors,one\\base.safetensors,one/base.safetensors",
        ),
    ],
)
def test_exact_output_strings(model_names, models, loras, expected):
    original_models, original_loras = list(models), list(loras)
    assert model_names.execute(models, loras).result == (expected,)
    assert models == original_models
    assert loras == original_loras


@pytest.mark.parametrize("other_input", ["models", "loras"])
def test_rejects_distinct_paths_with_the_same_filename(model_names, other_input):
    inputs = {"models": ["checkpoints/base.safetensors"], "loras": []}
    inputs[other_input].append("loras/family/base.safetensors")
    with pytest.raises(ValueError, match="unique filenames across distinct paths"):
        model_names.execute(**inputs)


@pytest.mark.parametrize("input_name", ["models", "loras"])
@pytest.mark.parametrize("value", [None, "name.safetensors", {}, [42], [None]])
def test_rejects_invalid_selection_types(model_names, input_name, value):
    inputs = {"models": [], "loras": [], input_name: value}
    with pytest.raises(TypeError, match=f"{input_name} must be a list of filenames"):
        model_names.execute(**inputs)


@pytest.mark.parametrize(
    ("input_name", "filename"),
    [
        ("models", "base,refiner.safetensors"),
        ("loras", "style,ink.safetensors"),
    ],
)
def test_rejects_image_saver_delimiters(model_names, input_name, filename):
    inputs = {"models": [], "loras": [], input_name: [filename]}
    with pytest.raises(
        ValueError, match=f"ImageSaverMini cannot represent {input_name}"
    ):
        model_names.execute(**inputs)


@pytest.mark.parametrize("input_name", ["models", "loras"])
@pytest.mark.parametrize("filename", ["", "folder/", "folder\\"])
def test_rejects_empty_filenames(model_names, input_name, filename):
    inputs = {"models": [], "loras": [], input_name: [filename]}
    with pytest.raises(ValueError, match="empty filename"):
        model_names.execute(**inputs)


@pytest.mark.parametrize("input_name", ["models", "loras"])
@pytest.mark.parametrize(
    "filename",
    [
        "model v2.safetensors",
        " model.safetensors",
        "model.safetensors ",
        "bad\tname.safetensors",
        "bad\nname.safetensors",
        "bad\u00a0name.safetensors",
        "海.safetensors",
        "bad:name.safetensors",
        'bad"name.safetensors',
        "bad>name.safetensors",
        "bad%name.safetensors",
        "model",
        "model.",
        ".safetensors",
        ".",
        "..",
    ],
)
def test_rejects_invalid_basenames(model_names, input_name, filename):
    inputs = {"models": [], "loras": [], input_name: [f"nested/{filename}"]}
    with pytest.raises(
        ValueError, match=f"ImageSaverMini cannot represent {input_name}"
    ):
        model_names.execute(**inputs)


@pytest.mark.parametrize("input_name", ["models", "loras"])
@pytest.mark.parametrize(
    "reference",
    [
        "/base.safetensors",
        r"C:\models\base.safetensors",
        "C:base.safetensors",
        r"\\server\share\base.safetensors",
        "./base.safetensors",
        "../base.safetensors",
        "folder/../base.safetensors",
        r"folder\..\base.safetensors",
        "folder//base.safetensors",
        "bad,folder/base.safetensors",
        "bad\nfolder/base.safetensors",
        "bad\0folder/base.safetensors",
        " folder/base.safetensors",
    ],
)
def test_rejects_invalid_relative_references(model_names, input_name, reference):
    inputs = {"models": [], "loras": [], input_name: [reference]}
    with pytest.raises(
        ValueError, match=f"ImageSaverMini cannot represent {input_name}"
    ):
        model_names.execute(**inputs)
