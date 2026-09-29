# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""ModelNames contracts tested with the shared API double and directory doubles."""

import sys
from types import ModuleType

import pytest

from comfyui_lany_nodes.nodes.model_names import ModelNames


def test_schema_discovers_registered_filenames(monkeypatch):
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

    schema = ModelNames.define_schema()
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

    # Schema refresh picks up host changes without caching our own directory list.
    filenames["diffusion_models"].append("new.safetensors")
    refreshed = ModelNames.define_schema()
    assert "diffusion_models/new.safetensors" in refreshed.inputs[0].options
    assert "diffusion_models/new.safetensors" not in schema.inputs[0].options


def test_schema_uses_actual_paths_relative_to_models_directory(monkeypatch, tmp_path):
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

    schema = ModelNames.define_schema()

    assert schema.inputs[0].options == ["library/base.safetensors", "unet/refiner.gguf"]
    assert schema.inputs[1].options == ["styles/ink.safetensors"]


@pytest.mark.parametrize(
    ("models", "loras", "expected"),
    [
        ([], [], ""),
        # Selection order, non-ASCII directories, and separators are preserved.
        (
            ["z/base.safetensors", "版本/model_v2.1.safetensors", "a/refiner.ckpt"],
            ["艺术 styles/ink-v1.2.safetensors", r"styles\detail.safetensors"],
            (
                "z/base.safetensors,版本/model_v2.1.safetensors,a/refiner.ckpt,"
                "艺术 styles/ink-v1.2.safetensors,styles\\detail.safetensors"
            ),
        ),
        # Repeated references to one file are not conflicts; the saver dedupes.
        (
            ["one/base.safetensors", r"one\base.safetensors"],
            ["one/base.safetensors"],
            "one/base.safetensors,one\\base.safetensors,one/base.safetensors",
        ),
    ],
)
def test_exact_output_strings(models, loras, expected):
    # Selections belong to the host's prompt; joining them must not mutate them.
    original_models, original_loras = list(models), list(loras)
    assert ModelNames.execute(models, loras).result == (expected,)
    assert (models, loras) == (original_models, original_loras)


def test_rejects_distinct_paths_with_the_same_filename():
    with pytest.raises(ValueError, match="unique filenames across distinct paths"):
        ModelNames.execute(
            ["checkpoints/base.safetensors"], ["loras/family/base.safetensors"]
        )


@pytest.mark.parametrize(
    ("input_name", "value"), [("models", "name.safetensors"), ("loras", [None])]
)
def test_rejects_invalid_selection_types(input_name, value):
    inputs = {"models": [], "loras": [], input_name: value}
    with pytest.raises(TypeError, match=f"{input_name} must be a list of filenames"):
        ModelNames.execute(**inputs)


def test_rejects_empty_filenames():
    with pytest.raises(ValueError, match="models must not contain an empty filename"):
        ModelNames.execute(["folder/"], [])


# Files on disk may use names ImageSaverMini cannot represent, so ModelNames
# rejects them early. test_image_saver_mini.py covers path structure in full.
@pytest.mark.parametrize(
    ("reference", "reason"),
    [
        (" nested/model.safetensors", "internal whitespace"),
        ("nested/model v2.safetensors", "internal whitespace"),
        ("sty,les/ink.safetensors", "commas, colons, quotes, or newlines"),
        ("nested/海.safetensors", "ASCII letters"),
        ("nested/model", "filename suffixes"),
        ("nested/.safetensors", "filename suffixes"),
        ("../base.safetensors", "relative markers"),
    ],
)
def test_rejects_references_image_saver_cannot_represent(reference, reason):
    with pytest.raises(
        ValueError, match=f"ImageSaverMini cannot represent loras .*{reason}"
    ):
        ModelNames.execute([], [reference])
