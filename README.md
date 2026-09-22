# ComfyUI Lany Nodes

Utility, common, and experimental nodes for ComfyUI. Requires Python 3.13+
and ComfyUI's V3 node API.

```bash
cd /path/to/ComfyUI/custom_nodes
git clone https://git.colorized.life/comfyui-lany-nodes.git comfyui-lany-nodes
# Restart ComfyUI.
```

## Nodes

| Display name | Node ID | Controls, in order | Outputs |
| --- | --- | --- | --- |
| ScaleTo | `LanyNodes_ScaleTo` | `width`, `height`, `scale` | `target_width`, `target_height` |

ScaleTo multiplies dimensions by `scale` and rounds to the nearest integers,
with exact halfway values rounded to the nearest even integer.

## License

Copyright © 2026 Lany Atwood <lany@colorized.life>. Licensed under
[AGPL-3.0-only](LICENSE); see [COPYRIGHT](COPYRIGHT).
