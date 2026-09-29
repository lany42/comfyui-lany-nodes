# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Exercise the loading and registration contracts without installing ComfyUI."""

import asyncio
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from comfyui_lany_nodes.extension import LanyNodesExtension

ROOT = Path(__file__).resolve().parents[1]
HOST_DOUBLE = Path(__file__).with_name("host_double.py")

LOAD_EXTENSION = """
import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

if sys.argv[1] == "package":
    import comfyui_lany_nodes as module
else:
    spec = importlib.util.spec_from_file_location(
        "comfyui-lany-nodes", sys.argv[1],
        submodule_search_locations=[sys.argv[2]],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

assert "comfy_api" not in sys.modules
assert "folder_paths" not in sys.modules
web_directory = Path(module.WEB_DIRECTORY)
assert web_directory.is_absolute()
expected_package = (
    Path(module.__file__).parent
    if sys.argv[1] == "package"
    else Path(sys.argv[2]) / "src" / "comfyui_lany_nodes"
)
assert web_directory == expected_package.resolve() / "web"
assert (web_directory / "seed.js").is_file()

spec = importlib.util.spec_from_file_location("host_double", sys.argv[3])
host_double = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host_double)
sys.modules.update(host_double.comfy_api_modules())

extension = asyncio.run(module.comfy_entrypoint())
assert isinstance(extension, sys.modules["comfy_api.latest"].ComfyExtension)
nodes = asyncio.run(extension.get_node_list())
assert "folder_paths" not in sys.modules
folder_paths = ModuleType("folder_paths")
folder_paths.get_filename_list = lambda folder: []
sys.modules["folder_paths"] = folder_paths
assert [node.define_schema().node_id for node in nodes] == [
    "LanyNodes_ScaleTo", "LanyNodes_ScaleOf", "LanyNodes_Context",
    "LanyNodes_Seed", "LanyNodes_ImageComparer", "LanyNodes_ModelNames",
    "LanyNodes_ImageSaverMini",
]
"""


# A clone loads the same root file; the ZIP contains only the shipped sources.
@pytest.mark.parametrize("layout", ["package", "zip"])
def test_extension_loading(layout, tmp_path):
    root = ROOT
    if layout == "zip":
        archive = tmp_path / "source.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            for source in [
                ROOT / "__init__.py",
                *(ROOT / "src").rglob("*.py"),
                *(ROOT / "src").rglob("*.js"),
            ]:
                zipped.write(source, source.relative_to(ROOT))
        root = tmp_path / "comfyui-lany-nodes-main"
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(root)

    target = "package" if layout == "package" else str(root / "__init__.py")
    result = subprocess.run(
        [sys.executable, "-I", "-c", LOAD_EXTENSION, target, str(root), HOST_DOUBLE],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_requirements_mirror_project_dependencies():
    # Clone and ZIP installs read requirements.txt instead of pyproject.toml.
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    lines = (ROOT / "requirements.txt").read_text().splitlines()
    requirements = [line for line in lines if line and not line.startswith("#")]
    assert requirements == project["dependencies"]


PORT_FLAGS = ("optional", "force_input", "socketless", "is_output_list")
PORT_VALUES = ("min", "max", "control_after_generate")
SCHEMA_FLAGS = ("is_input_list", "is_output_node", "has_intermediate_output")


def describe(port):
    flags = [flag for flag in PORT_FLAGS if getattr(port, flag, False)]
    flags += [
        f"{name}={getattr(port, name)!r}"
        for name in PORT_VALUES
        if getattr(port, name, None) is not None
    ]
    if options := getattr(port, "options", None):
        flags.append(repr(options))
    return " ".join([f"{port.id}: {port.io_type}", *flags])


# Saved workflows store widget values by position and links by output slot.
# The frontend adds a serialized control widget to an INT named seed unless
# control_after_generate is False, and the host rejects saved values outside
# min/max or the combo options. Changing anything pinned here breaks existing
# workflows, so update it only as a deliberate break.
INTERFACES = {
    "LanyNodes_ScaleTo": {
        "inputs": [
            "width: INT min=0 max=9007199254740991",
            "height: INT min=0 max=9007199254740991",
            # Omitting max makes the frontend impose a limit of 2048.
            "scale: FLOAT min=0.0 max=1.7976931348623157e+308",
        ],
        "outputs": ["target_width: INT", "target_height: INT", "scale: FLOAT"],
        "flags": ["has_intermediate_output"],
    },
    "LanyNodes_ScaleOf": {
        "inputs": [
            "target: FLOAT min=-1.7976931348623157e+308 max=1.7976931348623157e+308",
            "source: FLOAT min=-1.7976931348623157e+308 max=1.7976931348623157e+308",
        ],
        "outputs": ["scale: FLOAT"],
        "flags": [],
    },
    "LanyNodes_Context": {
        "inputs": [
            "base_ctx: LANY_CONTEXT optional",
            "model: MODEL optional",
            "clip: CLIP optional",
            "vae: VAE optional",
            "positive: CONDITIONING optional",
            "negative: CONDITIONING optional",
            "latent: LATENT optional",
            "images: IMAGE optional",
            "seed: INT optional force_input",
            "width: INT optional force_input",
            "height: INT optional force_input",
            "scale: FLOAT optional force_input",
            "prompt_pos: STRING optional force_input",
            "prompt_neg: STRING optional force_input",
            "model_names: STRING optional force_input",
            "controlnet: CONTROL_NET optional",
            "upscale_model: UPSCALE_MODEL optional",
            "tile_plan: * optional",
            "api_client: * optional",
            "any_1: * optional",
            "any_2: * optional",
            "any_3: * optional",
            "any_4: * optional",
        ],
        "outputs": [
            "CONTEXT: LANY_CONTEXT",
            "MODEL: MODEL is_output_list",
            "CLIP: CLIP is_output_list",
            "VAE: VAE is_output_list",
            "POSITIVE: CONDITIONING is_output_list",
            "NEGATIVE: CONDITIONING is_output_list",
            "LATENT: LATENT is_output_list",
            "IMAGES: IMAGE is_output_list",
            "SEED: INT is_output_list",
            "WIDTH: INT is_output_list",
            "HEIGHT: INT is_output_list",
            "SCALE: FLOAT is_output_list",
            "PROMPT_POS: STRING is_output_list",
            "PROMPT_NEG: STRING is_output_list",
            "MODEL_NAMES: STRING is_output_list",
            "CONTROLNET: CONTROL_NET is_output_list",
            "UPSCALE_MODEL: UPSCALE_MODEL is_output_list",
            "TILE_PLAN: * is_output_list",
            "API_CLIENT: * is_output_list",
            "ANY_1: * is_output_list",
            "ANY_2: * is_output_list",
            "ANY_3: * is_output_list",
            "ANY_4: * is_output_list",
        ],
        "flags": ["is_input_list"],
    },
    "LanyNodes_Seed": {
        "inputs": [
            "seed: INT socketless min=-3 max=9007199254740991 control_after_generate=False"
        ],
        "outputs": ["SEED: INT"],
        "flags": [],
    },
    "LanyNodes_ImageComparer": {
        "inputs": ["image_a: IMAGE", "image_b: IMAGE"],
        "outputs": [],
        "flags": ["is_output_node"],
    },
    "LanyNodes_ModelNames": {
        "inputs": [
            "models: COMBO socketless control_after_generate=False",
            "loras: COMBO socketless control_after_generate=False",
        ],
        "outputs": ["MODEL_NAMES: STRING"],
        "flags": [],
    },
    "LanyNodes_ImageSaverMini": {
        "inputs": [
            "format: COMBO socketless ['png', 'jpg']",
            "images: IMAGE",
            "path: STRING",
            "filename: STRING",
            "models: STRING",
            "positive: STRING force_input",
            "negative: STRING force_input",
            "seed: INT min=0 max=18446744073709551615 control_after_generate=False",
            "steps: INT min=0 max=10000 control_after_generate=False",
            "width: INT min=0 max=9007199254740991",
            "height: INT min=0 max=9007199254740991",
            "time_format: STRING",
            "jpg_quality: INT min=1 max=100",
            "optimize_png: BOOLEAN",
            "png_embed_workflow: BOOLEAN",
            "additional_hashes: STRING",
        ],
        "outputs": [],
        "flags": ["is_output_node", "hidden: PROMPT", "hidden: EXTRA_PNGINFO"],
    },
}


def test_registered_node_interfaces(monkeypatch):
    folder_paths = ModuleType("folder_paths")
    folder_paths.get_filename_list = lambda folder: []
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)

    interfaces = {}
    for node in asyncio.run(LanyNodesExtension().get_node_list()):
        schema = node.define_schema()
        interfaces[schema.node_id] = {
            "inputs": [describe(port) for port in schema.inputs],
            "outputs": [describe(port) for port in schema.outputs],
            "flags": [
                *(flag for flag in SCHEMA_FLAGS if getattr(schema, flag, False)),
                *(f"hidden: {value}" for value in getattr(schema, "hidden", [])),
            ],
        }
    assert interfaces == INTERFACES
