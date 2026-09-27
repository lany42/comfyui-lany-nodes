# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Exercise the loading contract without installing ComfyUI."""

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

LOAD_EXTENSION = """
import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

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
assert (web_directory / "scale_to.js").is_file()
assert "LanyNodes.ScaleToDimensions" in (web_directory / "scale_to.js").read_text()
assert "LanyNodes.Seed" in (web_directory / "seed.js").read_text()
assert "LanyNodes.ImageComparer" in (web_directory / "image_comparer.js").read_text()
assert "LanyNodes.ImageSaverMini" in (web_directory / "image_saver_mini.js").read_text()
assert (web_directory / "buttons.js").is_file()

def socket_type(io_type):
    def socket(id, **options):
        return SimpleNamespace(id=id, io_type=io_type, **options)
    return SimpleNamespace(io_type=io_type, Input=socket, Output=socket, Type=object)

api = ModuleType("comfy_api")
latest = ModuleType("comfy_api.latest")
latest.ComfyExtension = type("ComfyExtension", (), {})
latest.ui = SimpleNamespace()
latest.io = SimpleNamespace(
    ComfyNode=type("ComfyNode", (), {}),
    Schema=SimpleNamespace,
    NodeOutput=SimpleNamespace,
    Custom=socket_type,
    Hidden=SimpleNamespace(prompt="PROMPT", extra_pnginfo="EXTRA_PNGINFO"),
    **{
        name: socket_type(io_type)
        for name, io_type in (
            ("Model", "MODEL"),
            ("Clip", "CLIP"),
            ("Vae", "VAE"),
            ("Conditioning", "CONDITIONING"),
            ("Latent", "LATENT"),
            ("Image", "IMAGE"),
            ("Int", "INT"),
            ("Float", "FLOAT"),
            ("String", "STRING"),
            ("MultiCombo", "COMBO"),
            ("Combo", "COMBO"),
            ("Boolean", "BOOLEAN"),
            ("ControlNet", "CONTROL_NET"),
            ("UpscaleModel", "UPSCALE_MODEL"),
            ("AnyType", "*"),
        )
    },
)
api.latest = latest
sys.modules["comfy_api"] = api
sys.modules["comfy_api.latest"] = latest

extension = asyncio.run(module.comfy_entrypoint())
assert isinstance(extension, latest.ComfyExtension)
nodes = asyncio.run(extension.get_node_list())
assert "folder_paths" not in sys.modules
folder_paths = ModuleType("folder_paths")
folder_paths.get_filename_list = lambda folder: []
sys.modules["folder_paths"] = folder_paths
assert [node.__name__ for node in nodes] == [
    "ScaleTo", "ScaleOf", "Context", "Seed", "ImageComparer", "ModelNames",
    "ImageSaverMini",
]
assert [node.define_schema().node_id for node in nodes] == [
    "LanyNodes_ScaleTo", "LanyNodes_ScaleOf", "LanyNodes_Context",
    "LanyNodes_Seed", "LanyNodes_ImageComparer", "LanyNodes_ModelNames",
    "LanyNodes_ImageSaverMini",
]
assert all(issubclass(node, latest.io.ComfyNode) for node in nodes)
"""


@pytest.mark.parametrize("layout", ["package", "clone", "zip"])
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
        [sys.executable, "-I", "-c", LOAD_EXTENSION, target, str(root)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
