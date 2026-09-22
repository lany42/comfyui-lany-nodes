# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Seed values resolved by the browser before queue submission."""

from comfy_api.latest import io

MAX_SEED = 2**53 - 1


class Seed(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="LanyNodes_Seed",
            display_name="Seed",
            category="Lany Nodes",
            description=(
                "Produce a fixed seed, or use -1 to randomize, -2 to increment, "
                "and -3 to decrement the last queued seed. These modes require "
                "the browser controls; stepping wraps within the seed range."
            ),
            inputs=[
                io.Int.Input(
                    "seed",
                    default=-1,
                    min=-3,
                    max=MAX_SEED,
                    step=1,
                    socketless=True,
                    control_after_generate=False,
                ),
            ],
            outputs=[io.Int.Output("SEED")],
        )

    @classmethod
    def execute(cls, seed: int) -> io.NodeOutput:
        if type(seed) is not int:
            raise TypeError("seed must be an integer.")
        if seed in (-1, -2, -3):
            raise NotImplementedError(
                "Seed modes -1, -2, and -3 require the ComfyUI browser controls "
                "to resolve a fixed seed before submission."
            )
        if not 0 <= seed <= MAX_SEED:
            raise ValueError(f"seed must be between 0 and {MAX_SEED}.")
        return io.NodeOutput(seed)
