# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""ComfyUI V3 node registration."""

from comfy_api.latest import ComfyExtension, io

from .nodes.context import Context
from .nodes.image_comparer import ImageComparer
from .nodes.image_saver_mini import ImageSaverMini
from .nodes.model_names import ModelNames
from .nodes.scaleof import ScaleOf
from .nodes.scaleto import ScaleTo
from .nodes.seed import Seed


class LanyNodesExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [
            ScaleTo,
            ScaleOf,
            Context,
            Seed,
            ImageComparer,
            ModelNames,
            ImageSaverMini,
        ]
