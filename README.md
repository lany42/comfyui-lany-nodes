# ComfyUI Lany Nodes

The canonical home of this repository is at https://git.colorized.life/comfyui-lany-nodes/

Utility, common, and experimental nodes for ComfyUI. Requires Python 3.13+
and ComfyUI's V3 node API.

```bash
cd /path/to/ComfyUI/custom_nodes
git clone https://git.colorized.life/comfyui-lany-nodes.git comfyui-lany-nodes
# Restart ComfyUI.
```

## Nodes

All nodes are available in the **Lany Nodes** category.

| Display name | Node ID | Inputs / controls | Outputs |
| --- | --- | --- | --- |
| ScaleTo | `LanyNodes_ScaleTo` | `width`, `height`, `scale` | `target_width`, `target_height`, `scale` (unchanged) |
| ScaleOf | `LanyNodes_ScaleOf` | `target`, `source` (nonzero) | `scale` (`target / source`, without rounding) |
| Context | `LanyNodes_Context` | Optional `base_ctx` and optional context fields listed below | `CONTEXT`, followed by each context field in uppercase, in the order listed below |
| Seed | `LanyNodes_Seed` | `seed`; buttons: `randomize`, `new seed`, `use last seed` | `SEED` |
| ImageComparer | `LanyNodes_ImageComparer` | `image_a`, `image_b` (nonempty image batches of equal length); `Slider` / `Click` modes, previous / next pair, right-click PNG download | No output sockets; browser image comparison |

Context fields, in order: `model`, `clip`, `vae`, `positive`, `negative`,
`latent`, `images`, `seed`, `width`, `height`, `prompt_pos`, `prompt_neg`,
`model_names`, `controlnet`, `upscale_model`, `any_1`, `any_2`, `any_3`, `any_4`.

## License

Copyright © 2026 Lany Atwood <lany@colorized.life>. Licensed under
[AGPL-3.0-only](LICENSE); see [COPYRIGHT](COPYRIGHT).

Context and Seed are fresh implementations for ComfyUI's V3 node API, inspired by
rgthree's Context Big and Seed nodes in [rgthree-comfy](https://github.com/rgthree/rgthree-comfy).
No upstream source code is incorporated; see [COPYRIGHT](COPYRIGHT) for attribution.
