# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""ComfyUI entry point for clone and ZIP installations."""

from .src.comfyui_lany_nodes import WEB_DIRECTORY, comfy_entrypoint

__all__ = ["WEB_DIRECTORY", "comfy_entrypoint"]
