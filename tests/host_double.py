# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""A small ComfyUI V3 API double for local contracts, not host compatibility."""

from types import ModuleType, SimpleNamespace

SOCKET_TYPES = {
    "Model": "MODEL",
    "Clip": "CLIP",
    "Vae": "VAE",
    "Conditioning": "CONDITIONING",
    "Latent": "LATENT",
    "Image": "IMAGE",
    "Int": "INT",
    "Float": "FLOAT",
    "String": "STRING",
    "Boolean": "BOOLEAN",
    "Combo": "COMBO",
    "MultiCombo": "COMBO",
    "ControlNet": "CONTROL_NET",
    "UpscaleModel": "UPSCALE_MODEL",
    "AnyType": "*",
}


def socket_type(io_type):
    def socket(id, **options):
        return SimpleNamespace(id=id, io_type=io_type, **options)

    return SimpleNamespace(io_type=io_type, Input=socket, Output=socket, Type=object)


class NodeOutput:
    def __init__(self, *result, ui=None):
        self.result = result
        self.ui = ui


def comfy_api_modules():
    """Return fresh comfy_api modules for installation in sys.modules."""
    api = ModuleType("comfy_api")
    latest = ModuleType("comfy_api.latest")
    latest.ComfyExtension = type("ComfyExtension", (), {})
    latest.ui = SimpleNamespace(PreviewImage=None)
    latest.io = SimpleNamespace(
        ComfyNode=type("ComfyNode", (), {}),
        Schema=SimpleNamespace,
        NodeOutput=NodeOutput,
        Custom=socket_type,
        Hidden=SimpleNamespace(prompt="PROMPT", extra_pnginfo="EXTRA_PNGINFO"),
        **{name: socket_type(io_type) for name, io_type in SOCKET_TYPES.items()},
    )
    api.latest = latest
    return {"comfy_api": api, "comfy_api.latest": latest}
