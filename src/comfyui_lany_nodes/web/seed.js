// SPDX-License-Identifier: AGPL-3.0-only
// SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_ID = "LanyNodes_Seed";
const MAX_SEED = Number.MAX_SAFE_INTEGER;
const QUEUE_WRAPPER = Symbol.for("LanyNodes.Seed.queuePrompt");
const states = new WeakMap();

function randomSeed() {
  const words = crypto.getRandomValues(new Uint32Array(2));
  return (words[0] & 0x1fffff) * 2 ** 32 + words[1];
}

function resolveSeed(value, lastSeed) {
  if (!Number.isSafeInteger(value) || value < -3 || value > MAX_SEED) {
    throw new RangeError(
      "Seed must be -1, -2, -3, or a nonnegative safe integer.",
    );
  }
  if (value >= 0) return value;
  if (value === -1 || lastSeed === undefined) return randomSeed();
  if (value === -2) return lastSeed === MAX_SEED ? 0 : lastSeed + 1;
  return lastSeed === 0 ? MAX_SEED : lastSeed - 1;
}

function queuedNodeIds(output, targets) {
  if (!targets?.length) return new Set(Object.keys(output));
  const pending = Object.keys(output).filter((id) =>
    targets.some(
      (target) => id === String(target) || id.startsWith(`${target}:`),
    ),
  );
  const included = new Set();
  while (pending.length) {
    const id = pending.pop();
    if (included.has(id) || !Object.hasOwn(output, id)) continue;
    included.add(id);
    for (const value of Object.values(output[id].inputs ?? {})) {
      if (
        Array.isArray(value) &&
        value.length === 2 &&
        Number.isInteger(value[1])
      ) {
        pending.push(String(value[0]));
      }
    }
  }
  return included;
}

function locateNode(graph, workflow, executionId) {
  let nodes = workflow.nodes;
  let node;
  let saved;
  const path = executionId.split(":");
  for (const [index, id] of path.entries()) {
    node = graph?.getNodeById(id) ?? graph?.getNodeById(Number(id));
    saved = nodes?.find((item) => String(item.id) === id);
    if (!node || !saved || saved.mode === 2 || saved.mode === 4) return;
    if (index < path.length - 1) {
      graph = node.subgraph;
      nodes = workflow.definitions?.subgraphs?.find(
        (definition) => definition.id === saved.type,
      )?.nodes;
    }
  }
  return { node, saved };
}

function queuedSeeds(data, options, graph) {
  if (!data?.workflow || !data.output) return [];
  // Never associate a submitted workflow with another tab's node IDs.
  if (graph?.id && data.workflow.id && graph.id !== data.workflow.id) {
    if (
      Object.values(data.output).some((node) => node.class_type === NODE_ID)
    ) {
      throw new Error("The queued Seed workflow is no longer loaded.");
    }
    return [];
  }
  const seeds = [];
  for (const id of queuedNodeIds(
    data.output,
    options?.partialExecutionTargets,
  )) {
    const entry = data.output[id];
    if (
      entry.class_type !== NODE_ID ||
      !Object.hasOwn(entry.inputs ?? {}, "seed")
    ) {
      continue;
    }
    const located = locateNode(graph, data.workflow, id);
    const state = located && states.get(located.node);
    if (!state) continue;
    const index = located.node.widgets
      .filter((widget) => widget.serialize !== false)
      .indexOf(state.widget);
    seeds.push({
      id,
      state,
      saved: located.saved,
      index,
      value: entry.inputs.seed,
    });
  }
  return seeds;
}

function workflowWithSeeds(workflow, changes) {
  const updateNodes = (nodes) =>
    nodes?.map((node) => {
      const change = changes.get(node);
      if (!change) return node;
      const values = node.widgets_values;
      const widgets = Array.isArray(values) ? [...values] : { ...values };
      widgets[Array.isArray(values) ? change.index : "seed"] = change.seed;
      const updated = { ...node, widgets_values: widgets };
      if (node.widgets_values_named) {
        updated.widgets_values_named = {
          ...node.widgets_values_named,
          seed: change.seed,
        };
      }
      return updated;
    });
  const result = { ...workflow, nodes: updateNodes(workflow.nodes) };
  if (workflow.definitions?.subgraphs) {
    result.definitions = {
      ...workflow.definitions,
      subgraphs: workflow.definitions.subgraphs.map((definition) => ({
        ...definition,
        nodes: updateNodes(definition.nodes),
      })),
    };
  }
  return result;
}

function installQueueAdapter() {
  if (api.queuePrompt[QUEUE_WRAPPER]) return;
  const original = api.queuePrompt;
  let pending = Promise.resolve();
  const queuePrompt = async function (number, data, ...args) {
    // Capture node references now, before another request or tab can intervene.
    const seeds = queuedSeeds(data, args[0], app.rootGraph ?? app.graph);
    const snapshot = seeds.length ? { ...data } : data;
    const submit = async () => {
      const resolved = new Map();
      const changes = new Map();
      let submitted = snapshot;
      if (seeds.length) {
        const output = { ...snapshot.output };
        for (const { id, state, saved, index, value } of seeds) {
          // Subgraph instances may share one underlying Seed widget.
          let resolution = resolved.get(state);
          if (resolution && resolution.value !== value) {
            throw new Error(
              "A shared Seed control has conflicting submitted values.",
            );
          }
          if (!resolution) {
            resolution = { value, seed: resolveSeed(value, state.lastSeed) };
            resolved.set(state, resolution);
          }
          const seed = resolution.seed;
          output[id] = {
            ...output[id],
            inputs: { ...output[id].inputs, seed },
          };
          changes.set(saved, { index, seed });
        }
        submitted = {
          ...snapshot,
          output,
          workflow: workflowWithSeeds(snapshot.workflow, changes),
        };
      }
      const response = await original.call(this, number, submitted, ...args);
      if (response?.prompt_id && resolved.size) {
        // ComfyUI records this object in its queue history after we return.
        data.output = submitted.output;
        data.workflow = submitted.workflow;
        for (const [state, { seed }] of resolved) {
          if (states.get(state.node) !== state) continue;
          state.lastSeed = seed;
          state.lastButton.disabled = false;
        }
        app.canvas?.setDirty(true, true);
      }
      return response;
    };
    const result = pending.then(submit);
    // A rejected request must not prevent later submissions.
    pending = result.then(
      () => {},
      () => {},
    );
    return result;
  };
  Object.defineProperty(queuePrompt, QUEUE_WRAPPER, { value: true });
  api.queuePrompt = queuePrompt;
}

app.registerExtension({
  name: "LanyNodes.Seed",

  setup() {
    installQueueAdapter();
  },

  nodeCreated(node) {
    if (node.comfyClass !== NODE_ID || states.has(node)) return;
    const widget = node.widgets?.find((item) => item.name === "seed");
    if (!widget) return;
    const state = { node, widget, lastSeed: undefined, lastButton: undefined };
    states.set(node, state);
    const setSeed = (value) => {
      widget.value = value;
      widget.callback?.call(widget, value);
      node.graph?.setDirtyCanvas(true, true);
    };
    const addButton = (label, callback) => {
      const button = node.addWidget("button", label, null, callback, {
        serialize: false,
      });
      button.serialize = false;
      return button;
    };
    addButton("randomize", () => setSeed(-1));
    addButton("new seed", () => setSeed(randomSeed()));
    state.lastButton = addButton("use last seed", () => {
      const lastSeed = states.get(node)?.lastSeed;
      if (lastSeed !== undefined) setSeed(lastSeed);
    });
    state.lastButton.disabled = true;
    node.expandToFitContent();
  },

  loadedGraphNode(node) {
    const state = states.get(node);
    if (!state) return;
    // Replace the state object so an old in-flight request cannot restore it.
    states.set(node, { ...state, lastSeed: undefined });
    state.lastButton.disabled = true;
  },
});
