# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Utility nodes built with ComfyUI's V3 API."""

import math
import sys
from fractions import Fraction

from comfy_api.latest import io


class ScaleTo(io.ComfyNode):
    """Scale dimensions, rounding halfway results to the nearest even integer."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="LanyNodes_ScaleTo",
            display_name="ScaleTo",
            category="Lany Nodes",
            has_intermediate_output=True,
            description=(
                "Multiply width and height by scale and round to the nearest integers. "
                "Exact halfway values round to the nearest even integer."
            ),
            inputs=[
                io.Int.Input("width", default=1024, min=0, max=2**53 - 1, step=1),
                io.Int.Input("height", default=1024, min=0, max=2**53 - 1, step=1),
                io.Float.Input(
                    "scale",
                    default=1.0,
                    min=0.0,
                    # Omitting max makes the frontend impose a limit of 2048.
                    max=sys.float_info.max,
                    step=0.01,
                    round=0.01,
                ),
            ],
            outputs=[
                io.Int.Output("target_width"),
                io.Int.Output("target_height"),
            ],
        )

    @classmethod
    def execute(cls, width: int, height: int, scale: float = 1.0) -> io.NodeOutput:
        if not math.isfinite(scale) or scale < 0:
            raise ValueError("scale must be a finite, nonnegative number.")
        # Preserve decimal halfway values and avoid overflow at large scales.
        factor = Fraction(str(scale))
        target_width = round(width * factor)
        target_height = round(height * factor)
        return io.NodeOutput(
            target_width,
            target_height,
            ui={"dimensions": [f"({target_width}x{target_height})"]},
        )
