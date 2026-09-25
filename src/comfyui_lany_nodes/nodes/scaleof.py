# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Compute the relative scale between two values."""

import math
import sys

from comfy_api.latest import io


class ScaleOf(io.ComfyNode):
    """Return target divided by source at full floating-point precision."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="LanyNodes_ScaleOf",
            display_name="ScaleOf",
            category="Lany Nodes",
            description=(
                "Divide target by source to get the relative scale, without rounding. "
                "For example, target 2.0 and source 1.5 produce 1.3333333333333333."
            ),
            inputs=[
                io.Float.Input(
                    name,
                    default=1.0,
                    min=-sys.float_info.max,
                    max=sys.float_info.max,
                    step=0.01,
                    round=False,
                )
                for name in ("target", "source")
            ],
            outputs=[io.Float.Output("scale")],
        )

    @classmethod
    def execute(cls, target: float = 1.0, source: float = 1.0) -> io.NodeOutput:
        if not math.isfinite(target) or not math.isfinite(source):
            raise ValueError("target and source must be finite numbers.")
        if source == 0:
            raise ValueError("source must be nonzero.")
        scale = target / source
        if not math.isfinite(scale):
            raise ValueError("scale must be a finite number.")
        return io.NodeOutput(scale)
