# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""ComfyUI V3 node registration."""

from comfy_api.latest import ComfyExtension, io

from .nodes.context import Context
from .nodes.scaleto import ScaleTo
from .nodes.seed import Seed


class LanyNodesExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [ScaleTo, Context, Seed]
