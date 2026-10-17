// SPDX-License-Identifier: AGPL-3.0-only
// SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

// These doubles exercise local contracts, not compatibility with a running host.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { SourceTextModule, SyntheticModule, createContext } from "node:vm";

const ALWAYS = 0;
const NEVER = 2;
const BYPASS = 4;
const source = await readFile(
  new URL(
    "../src/comfyui_lany_nodes/web/fast_groups_muter.js",
    import.meta.url,
  ),
  "utf8",
);

class LGraphNode {
  constructor(title) {
    this.title = title;
    this.mode = ALWAYS;
    this.size = [140, 46];
    this.widgets = [];
    this.draws = 0;
  }
  // Like the host, adding a widget grows the node to fit but never shrinks it.
  addWidget(type, name, value, callback, options) {
    const widget = { type, name, value, callback, options };
    this.widgets.push(widget);
    const [width, height] = this.computeSize();
    this.size = [Math.max(this.size[0], width), Math.max(this.size[1], height)];
    return widget;
  }
  removeWidget(widget) {
    this.widgets.splice(this.widgets.indexOf(widget), 1);
  }
  computeSize() {
    return [210, 30 + 24 * this.widgets.length];
  }
  setDirtyCanvas() {
    this.draws++;
  }
}

async function harness() {
  const h = { timeouts: [], intervals: new Map(), nextTimer: 1 };
  const app = {
    registerExtension(extension) {
      h.extension = extension;
    },
  };
  const context = createContext({
    LGraphNode,
    LiteGraph: {
      registerNodeType(type, nodeClass) {
        h.type = type;
        h.Muter = nodeClass;
      },
    },
    setTimeout(callback) {
      h.timeouts.push(callback);
      return h.nextTimer++;
    },
    setInterval(callback, ms) {
      h.intervals.set(h.nextTimer, { callback, ms });
      return h.nextTimer++;
    },
    clearInterval(id) {
      h.intervals.delete(id);
    },
  });
  const module = new SourceTextModule(source, { context });
  await module.link((specifier) => {
    assert.equal(specifier, "../../scripts/app.js");
    return new SyntheticModule(
      ["app"],
      function () {
        this.setExport("app", app);
      },
      { context },
    );
  });
  await module.evaluate();
  h.extension.registerCustomNodes();

  h.graph = { nodes: [], groups: [] };
  h.addGroup = (title, boundingRect, graph = h.graph) => {
    const group = { title, boundingRect };
    graph.groups.push(group);
    return group;
  };
  // Nodes are 100x50, so a node at [x, y] has its center at [x + 50, y + 25].
  h.addNode = ([x, y], mode = ALWAYS, graph = h.graph) => {
    const node = { mode, boundingRect: [x, y, 100, 50] };
    graph.nodes.push(node);
    return node;
  };
  h.addMuter = (graph = h.graph) => {
    const muter = new h.Muter(h.Muter.title);
    muter.graph = graph;
    graph.nodes.push(muter);
    muter.onAdded(graph);
    return muter;
  };
  h.removeMuter = (muter) => {
    muter.graph.nodes.splice(muter.graph.nodes.indexOf(muter), 1);
    muter.onRemoved();
    muter.graph = null;
  };
  // Runs deferred work, as when a workflow finishes loading.
  h.settle = () => {
    for (const callback of h.timeouts.splice(0)) callback();
  };
  // Runs one periodic refresh.
  h.tick = () => {
    h.settle();
    for (const { callback } of h.intervals.values()) callback();
  };
  return h;
}

const labels = (muter) => muter.widgets.map((widget) => widget.label);
const values = (muter) => muter.widgets.map((widget) => widget.value);

// Both renderers store the new value before calling the widget callback.
function toggle(widget, value) {
  widget.value = value;
  widget.callback(value);
}

test("a virtual LanyNodes node in the Lany Nodes category", async () => {
  const h = await harness();
  assert.equal(h.type, "LanyNodes_FastGroupsMuter");
  assert.equal(h.Muter.category, "Lany Nodes");
  const muter = h.addMuter();
  h.settle();
  // ComfyUI never sends virtual nodes to the backend.
  assert.equal(muter.isVirtualNode, true);
  // Unsaved toggle values keep their refresh out of the undo history.
  assert.ok(!muter.serialize_widgets);
  assert.deepEqual(muter.widgets, []);
});

test("a muter added before its groups shows them once loading finishes", async () => {
  const h = await harness();
  const muter = h.addMuter();
  h.addGroup("Group", [0, 0, 300, 300]);
  h.addNode([10, 10]);
  assert.deepEqual(muter.widgets, []);
  h.settle();
  assert.deepEqual(labels(muter), ["Group"]);
  assert.deepEqual(values(muter), [true]);
});

test("one toggle per group in natural title order, following group changes", async () => {
  const h = await harness();
  const tenth = h.addGroup("10. Tenth group", [0, 0, 300, 300]);
  const second = h.addGroup("2. second group", [400, 0, 300, 300]);
  const first = h.addGroup("1. First group", [800, 0, 300, 300]);
  const muter = h.addMuter();
  h.settle();
  assert.deepEqual(labels(muter), [
    "1. First group",
    "2. second group",
    "10. Tenth group",
  ]);
  assert.ok(muter.widgets.every((widget) => widget.type === "toggle"));
  assert.deepEqual([...muter.size], [210, 30 + 24 * 3]);

  h.addNode([1210, 10]);
  h.addGroup("3. Third group", [1200, 0, 300, 300]);
  h.tick();
  assert.deepEqual(labels(muter), [
    "1. First group",
    "2. second group",
    "3. Third group",
    "10. Tenth group",
  ]);
  assert.deepEqual(values(muter), [false, false, true, false]);
  assert.deepEqual([...muter.size], [210, 30 + 24 * 4]);

  first.title = "1. Renamed group";
  h.tick();
  assert.deepEqual(labels(muter), [
    "1. Renamed group",
    "2. second group",
    "3. Third group",
    "10. Tenth group",
  ]);
  second.title = "20. Renamed group";
  h.tick();
  assert.deepEqual(labels(muter), [
    "1. Renamed group",
    "3. Third group",
    "10. Tenth group",
    "20. Renamed group",
  ]);

  // Removing a group must not resize the node, or loading would mark it modified.
  h.graph.groups.splice(h.graph.groups.indexOf(tenth), 1);
  h.tick();
  assert.deepEqual(labels(muter), [
    "1. Renamed group",
    "3. Third group",
    "20. Renamed group",
  ]);
  assert.deepEqual([...muter.size], [210, 30 + 24 * 4]);
});

test("toggling off mutes the nodes centered in the group, and on unmutes them", async () => {
  const h = await harness();
  h.addGroup("Group", [0, 0, 300, 300]);
  const inside = h.addNode([10, 10]);
  const bypassed = h.addNode([150, 150], BYPASS);
  // Overlaps the group, but its center lies outside it.
  const overlapping = h.addNode([260, 10]);
  const outside = h.addNode([500, 500]);
  const muter = h.addMuter();
  // Muters are never muted, even inside a group.
  const other = h.addMuter();
  other.boundingRect = [100, 100, 100, 50];
  h.settle();
  const [widget] = muter.widgets;
  assert.equal(widget.value, true);

  toggle(widget, false);
  assert.deepEqual(
    [inside, bypassed, overlapping, outside, muter, other].map(
      (node) => node.mode,
    ),
    [NEVER, NEVER, ALWAYS, ALWAYS, ALWAYS, ALWAYS],
  );
  assert.equal(widget.value, false);
  assert.ok(muter.draws > 0);

  toggle(widget, true);
  assert.deepEqual(
    [inside, bypassed, overlapping, outside, muter, other].map(
      (node) => node.mode,
    ),
    [ALWAYS, ALWAYS, ALWAYS, ALWAYS, ALWAYS, ALWAYS],
  );
  assert.equal(widget.value, true);
});

test("toggles follow mode and position changes made elsewhere", async () => {
  const h = await harness();
  const group = h.addGroup("Group", [0, 0, 300, 300]);
  h.addGroup("Empty", [1000, 1000, 300, 300]);
  const node = h.addNode([10, 10]);
  const muter = h.addMuter();
  h.settle();
  const [empty, widget] = muter.widgets;
  assert.deepEqual(labels(muter), ["Empty", "Group"]);
  assert.equal(widget.value, true);

  node.mode = NEVER;
  h.tick();
  assert.equal(widget.value, false);
  // Only an active node counts as on.
  node.mode = BYPASS;
  h.tick();
  assert.equal(widget.value, false);

  node.mode = ALWAYS;
  node.boundingRect = [500, 500, 100, 50];
  h.tick();
  assert.equal(widget.value, false);
  group.boundingRect = [450, 450, 300, 300];
  h.tick();
  assert.equal(widget.value, true);

  // An empty group has nothing to turn on.
  toggle(empty, true);
  assert.equal(empty.value, false);
});

test("toggles stay bound to their groups through sorting, renames, and removal", async () => {
  const h = await harness();
  const b = h.addGroup("2. B", [0, 0, 300, 300]);
  const a = h.addGroup("1. A", [400, 0, 300, 300]);
  const inB = h.addNode([10, 10]);
  const inA = h.addNode([410, 10]);
  const muter = h.addMuter();
  h.settle();

  toggle(muter.widgets[0], false);
  assert.deepEqual([inA.mode, inB.mode], [NEVER, ALWAYS]);
  assert.deepEqual(values(muter), [false, true]);

  a.title = "3. A";
  h.tick();
  assert.deepEqual(labels(muter), ["2. B", "3. A"]);
  assert.deepEqual(values(muter), [true, false]);
  toggle(muter.widgets[1], true);
  toggle(muter.widgets[0], false);
  assert.deepEqual([inA.mode, inB.mode], [ALWAYS, NEVER]);

  // A same-titled replacement gets a toggle bound to the new group.
  h.graph.groups.splice(h.graph.groups.indexOf(b), 1);
  h.addGroup("2. B", [800, 0, 300, 300]);
  const inNewB = h.addNode([810, 10]);
  h.tick();
  toggle(muter.widgets[0], false);
  assert.deepEqual([inNewB.mode, inB.mode], [NEVER, NEVER]);
  toggle(muter.widgets[0], true);
  assert.deepEqual([inNewB.mode, inB.mode], [ALWAYS, NEVER]);

  // A row left over from a deleted group changes nothing and disappears.
  h.graph.groups.splice(h.graph.groups.indexOf(a), 1);
  toggle(muter.widgets[1], false);
  assert.equal(inA.mode, ALWAYS);
  assert.deepEqual(labels(muter), ["2. B"]);
});

test("groups that share a title keep separate toggles", async () => {
  const h = await harness();
  h.addGroup("Same", [0, 0, 300, 300]);
  h.addGroup("Same", [400, 0, 300, 300]);
  const first = h.addNode([10, 10]);
  const second = h.addNode([410, 10]);
  const muter = h.addMuter();
  h.settle();
  assert.deepEqual(labels(muter), ["Same", "Same"]);

  toggle(muter.widgets[1], false);
  assert.deepEqual([first.mode, second.mode], [ALWAYS, NEVER]);
  assert.deepEqual(values(muter), [true, false]);
});

test("copies share one timer and one scan per graph, and stay in sync", async () => {
  const h = await harness();
  h.addGroup("Group", [0, 0, 300, 300]);
  const node = h.addNode([10, 10]);
  let mode = ALWAYS;
  let reads = 0;
  Object.defineProperty(node, "mode", {
    get() {
      reads++;
      return mode;
    },
    set(value) {
      mode = value;
    },
  });
  const copies = [h.addMuter(), h.addMuter(), h.addMuter()];
  const subgraph = { nodes: [], groups: [] };
  h.addGroup("Subgraph group", [0, 0, 300, 300], subgraph);
  const inner = h.addMuter(subgraph);
  h.settle();
  assert.equal(h.intervals.size, 1);
  assert.ok([...h.intervals.values()][0].ms >= 1000);
  assert.ok(copies.every((copy) => labels(copy).join() === "Group"));
  assert.deepEqual(labels(inner), ["Subgraph group"]);

  reads = 0;
  h.tick();
  assert.equal(reads, 1);

  // Toggling one copy updates the others without waiting for the timer.
  toggle(copies[0].widgets[0], false);
  assert.equal(mode, NEVER);
  assert.ok(copies.every((copy) => copy.widgets[0].value === false));

  for (const copy of copies) h.removeMuter(copy);
  assert.equal(h.intervals.size, 1);
  h.removeMuter(inner);
  assert.equal(h.intervals.size, 0);
});
