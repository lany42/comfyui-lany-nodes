// SPDX-License-Identifier: AGPL-3.0-only
// SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

import { app } from "../../scripts/app.js";

const NODE_ID = "LanyNodes_FastGroupsMuter";
// LiteGraph's saved node modes.
const ALWAYS = 0;
const NEVER = 2;
const REFRESH_MS = 1000;
// Numeric collation keeps "10. Group" after "2. Group".
const titles = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});
// Every muter shares one timer and one scan per graph.
const muters = new Set();
let refreshTimer;
let pendingRefresh;

// LGraphGroup.recomputeInsideNodes's center test, without mutating the group.
// Indexed reads keep the scan from allocating per node and group.
function centeredIn(bounds, node) {
  const rect = node.boundingRect;
  const x = rect[0] + rect[2] / 2;
  const y = rect[1] + rect[3] / 2;
  return (
    x >= bounds[0] &&
    x < bounds[0] + bounds[2] &&
    y >= bounds[1] &&
    y < bounds[1] + bounds[3]
  );
}

// Sorts the graph's groups and finds those holding an active node, reading
// each node once and stopping when every group is active.
function scanGraph(graph) {
  const groups = [...graph.groups].sort((a, b) =>
    titles.compare(a.title, b.title),
  );
  const bounds = groups.map((group) => [...group.boundingRect]);
  const active = groups.map(() => false);
  let inactive = groups.length;
  for (const node of graph.nodes) {
    if (!inactive) break;
    if (node.mode !== ALWAYS || muters.has(node)) continue;
    for (let index = 0; index < bounds.length; index++) {
      if (!active[index] && centeredIn(bounds[index], node)) {
        active[index] = true;
        inactive--;
      }
    }
  }
  return { groups, active };
}

function refreshMuters() {
  const scans = new Map();
  for (const muter of muters) {
    const graph = muter.graph;
    if (!graph) continue;
    if (!scans.has(graph)) scans.set(graph, scanGraph(graph));
    muter.showGroups(scans.get(graph));
  }
}

app.registerExtension({
  name: "LanyNodes.FastGroupsMuter",

  registerCustomNodes() {
    class FastGroupsMuter extends LGraphNode {
      static title = "FastGroupsMuter";

      constructor(title) {
        super(title);
        // Frontend only: ComfyUI leaves virtual nodes out of the prompt.
        this.isVirtualNode = true;
        this.groupRows = [];
      }

      onAdded() {
        muters.add(this);
        refreshTimer ??= setInterval(refreshMuters, REFRESH_MS);
        // Deferred until a loading workflow has also added its groups.
        pendingRefresh ??= setTimeout(() => {
          pendingRefresh = undefined;
          refreshMuters();
        });
      }

      onRemoved() {
        muters.delete(this);
        if (!muters.size) {
          clearInterval(refreshTimer);
          refreshTimer = undefined;
        }
      }

      showGroups({ groups, active }) {
        const rows = this.groupRows;
        const changed =
          groups.length !== rows.length ||
          groups.some(
            (group, index) =>
              group !== rows[index].group || group.title !== rows[index].title,
          );
        if (changed) {
          for (const { widget } of rows) this.removeWidget(widget);
          // addWidget only grows the node, so loading never resizes it.
          this.groupRows = groups.map((group) => {
            const widget = this.addWidget("toggle", group.title, false, (on) =>
              this.setGroupMode(group, on),
            );
            // Duplicate names get renamed by the frontend; labels are shown.
            widget.label = group.title;
            return { group, title: group.title, widget };
          });
        }
        let dirty = changed;
        for (const [index, { widget }] of this.groupRows.entries()) {
          if (widget.value !== active[index]) {
            widget.value = active[index];
            dirty = true;
          }
        }
        if (dirty) this.setDirtyCanvas(true, false);
      }

      setGroupMode(group, on) {
        const graph = this.graph;
        // A row can outlive its group until the next refresh.
        if (graph?.groups.includes(group)) {
          const bounds = [...group.boundingRect];
          for (const node of graph.nodes) {
            if (!muters.has(node) && centeredIn(bounds, node)) {
              node.mode = on ? ALWAYS : NEVER;
            }
          }
        }
        // Update every copy now rather than at the next refresh.
        refreshMuters();
        this.setDirtyCanvas(true, true);
      }
    }

    LiteGraph.registerNodeType(NODE_ID, FastGroupsMuter);
    // registerNodeType derives the category from the type, so set it after.
    FastGroupsMuter.category = "Lany Nodes";
  },
});
