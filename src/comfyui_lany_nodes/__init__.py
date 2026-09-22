# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Utility, common, and experimental nodes for ComfyUI."""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .extension import LanyNodesExtension

WEB_DIRECTORY = str(Path(__file__).resolve().parent / "web")


async def comfy_entrypoint() -> "LanyNodesExtension":
    from .extension import LanyNodesExtension

    return LanyNodesExtension()


__all__ = ["WEB_DIRECTORY", "comfy_entrypoint"]
