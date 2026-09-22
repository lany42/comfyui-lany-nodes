Do NOT update the README unless explicitly requested.
Do NOT add or update documentation in docs/ unless explicitly requested.

# Development workflow

Run from the repository root. Use Python 3.13+ and uv; `uv sync --locked`
installs the development environment. Update pyproject.toml and uv.lock
together. After Python changes, run these checks in order:

```sh
uv run --offline --locked ruff check --select I --fix .
uv run --offline --locked ruff check --fix .
uv run --offline --locked ruff format .
uv run --offline --locked ruff check .
uv run --offline --locked pytest
uv lock --check
uv build
```

Keep implementation in src/comfyui_lany_nodes and the root loader for
clone/ZIP loading. Keep package imports usable without ComfyUI by deferring
host imports to the extension entry point. Use ComfyUI's V3 API:
`io.ComfyNode`, `define_schema`, `execute`, and `io.NodeOutput`. Register nodes
explicitly in `LanyNodesExtension.get_node_list`; use `LanyNodes_` node IDs.

ComfyUI supplies runtime PyTorch and comfy_api. Keep runtime dependencies
empty unless an actual new dependency is needed; do not replace the host's
CUDA build. If tensor tests need PyTorch, add it only to the development
group through an explicit CPU index. Tests should run without a host
installation, GPU, network, or sibling checkout. Small host doubles test
local contracts, not compatibility with upstream ComfyUI by themselves.

Include the root loader, Python version file, AGENTS.md, lockfile, and tests
in source distributions; include LICENSE and COPYRIGHT in both builds.

Every Python source and test starts with:

```python
# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>
```

Use Conventional Commits: `<type>[optional scope][!]: <summary>`. Write an
imperative subject of at most 50 characters, with no trailing period. Follow
it with one blank line and a single short paragraph explaining what changed
and why in plain language. Limit the body to four lines, each at most 72
characters; avoid lists and exhaustive change logs.
