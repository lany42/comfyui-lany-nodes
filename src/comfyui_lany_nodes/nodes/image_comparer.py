# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Display corresponding entries from two image batches in the browser."""

from comfy_api.latest import io, ui


class ImageComparer(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="LanyNodes_ImageComparer",
            display_name="ImageComparer",
            category="Lany Nodes",
            description=(
                "Compare corresponding images from two nonempty batches of equal "
                "length. Image dimensions may differ. Right-click to download a PNG."
            ),
            inputs=[io.Image.Input("image_a"), io.Image.Input("image_b")],
            outputs=[],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, image_a: io.Image.Type, image_b: io.Image.Type) -> io.NodeOutput:
        count_a, count_b = image_a.shape[0], image_b.shape[0]
        if count_a == 0 or count_b == 0:
            raise ValueError("ImageComparer requires nonempty image batches.")
        if count_a != count_b:
            raise ValueError("ImageComparer requires image batches of equal length.")

        return io.NodeOutput(
            ui={
                "a_images": ui.PreviewImage(image_a).as_dict()["images"],
                "b_images": ui.PreviewImage(image_b).as_dict()["images"],
            }
        )
