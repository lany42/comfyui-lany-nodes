# ComfyUI Lany Nodes

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
| ScaleTo | `LanyNodes_ScaleTo` | `width`, `height`, `scale` | `target_width`, `target_height` |
| Context | `LanyNodes_Context` | Optional `base_ctx` and the fields listed below | `CONTEXT`, followed by each field listed below |
| Seed | `LanyNodes_Seed` | `seed`; buttons: `randomize`, `new seed`, `use last seed` | `SEED` |

## License

Copyright © 2026 Lany Atwood <lany@colorized.life>. Licensed under
[AGPL-3.0-only](LICENSE); see [COPYRIGHT](COPYRIGHT).

Context and Seed are fresh implementations for ComfyUI's V3 node API, inspired by
rgthree's Context Big and Seed nodes in [rgthree-comfy](https://github.com/rgthree/rgthree-comfy).
No upstream source code is incorporated; see [COPYRIGHT](COPYRIGHT) for attribution.
