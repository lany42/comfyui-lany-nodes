// SPDX-License-Identifier: AGPL-3.0-only
// SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

// These doubles exercise local contracts, not compatibility with a running host.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { SourceTextModule, SyntheticModule, createContext } from "node:vm";

const MAX_SEED = Number.MAX_SAFE_INTEGER;
const source = await readFile(
  new URL("../src/comfyui_lany_nodes/web/seed.js", import.meta.url),
  "utf8",
);
const tick = () => new Promise((resolve) => setImmediate(resolve));

function makeGraph(id) {
  return {
    id,
    nodes: [],
    dirty: 0,
    getNodeById(id) {
      return this.nodes.find((node) => String(node.id) === String(id));
    },
    setDirtyCanvas() {
      this.dirty++;
    },
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function payload(graph) {
  const output = {};
  const definitions = new Map();
  const serialize = (node) => {
    const widgets =
      node.widgets?.filter((widget) => widget.serialize !== false) ?? [];
    return {
      id: node.id,
      type: node.subgraph?.id ?? node.comfyClass,
      mode: node.mode ?? 0,
      widgets_values: widgets.map((widget) => widget.value),
      widgets_values_named: Object.fromEntries(
        widgets.map((widget) => [widget.name, widget.value]),
      ),
    };
  };
  function visit(current, prefix = "") {
    for (const node of current.nodes) {
      if (node.subgraph && !definitions.has(node.subgraph.id)) {
        definitions.set(node.subgraph.id, {
          id: node.subgraph.id,
          nodes: node.subgraph.nodes.map(serialize),
        });
      }
      if (node.mode === 2 || node.mode === 4) continue;
      const id = prefix + node.id;
      if (node.subgraph) {
        visit(node.subgraph, id + ":");
      } else {
        output[id] = {
          class_type: node.comfyClass,
          inputs: node.promptInputs ?? { seed: node.widgets[0].value },
          _meta: { title: node.comfyClass },
        };
      }
    }
  }
  visit(graph);
  return {
    output,
    workflow: {
      id: graph.id,
      nodes: graph.nodes.map(serialize),
      definitions: { subgraphs: [...definitions.values()] },
    },
  };
}

async function harness(words = []) {
  const h = { calls: [], draws: 0, words, extensions: [] };
  h.app = {
    rootGraph: makeGraph("workflow"),
    canvas: { setDirty() {} },
    registerExtension(extension) {
      h.extensions.push(extension);
    },
  };
  h.respond = () => ({ prompt_id: `prompt-${h.calls.length}` });
  h.api = {
    async queuePrompt(...args) {
      h.calls.push({ receiver: this, args });
      return h.respond(...args);
    },
  };
  const context = createContext({
    crypto: {
      getRandomValues(array) {
        assert.equal(array.length, 2);
        h.draws++;
        array.set(h.words.shift() ?? [0, 41]);
        return array;
      },
    },
  });
  const module = new SourceTextModule(source, { context });
  await module.link((specifier) => {
    const name = specifier.endsWith("/app.js") ? "app" : "api";
    assert.ok(
      specifier === "../../scripts/app.js" ||
        specifier === "../../scripts/api.js",
    );
    return new SyntheticModule(
      [name],
      function () {
        this.setExport(name, h[name]);
      },
      { context },
    );
  });
  await module.evaluate();
  assert.equal(h.extensions.length, 1);
  h.extension = h.extensions[0];
  h.extension.setup();
  h.addNode = (
    id,
    seed = -1,
    graph = h.app.rootGraph,
    comfyClass = "LanyNodes_Seed",
  ) => {
    const node = {
      id,
      comfyClass,
      graph,
      mode: 0,
      widgets: [
        {
          name: "seed",
          type: "number",
          value: seed,
          callback(value) {
            this.callbackValue = value;
          },
        },
      ],
      addWidget(type, name, value, callback, options) {
        const widget = { type, name, value, callback, options };
        this.widgets.push(widget);
        return widget;
      },
      expandToFitContent() {},
    };
    graph.nodes.push(node);
    h.extension.nodeCreated(node);
    return node;
  };
  h.queue = (options) =>
    h.api.queuePrompt(0, payload(h.app.rootGraph), options);
  h.seedSent = (index = h.calls.length - 1, id = "1") =>
    h.calls[index].args[1].output[id].inputs.seed;
  return h;
}

function press(node, label) {
  node.widgets.find((widget) => widget.name === label).callback();
}

function seedWidget(node) {
  return node.widgets[0];
}
function lastButton(node) {
  return node.widgets.find((widget) => widget.name === "use last seed");
}

test("three nonserialized buttons, without changing existing seed values or other node types", async () => {
  const h = await harness();
  const node = h.addNode("1", 19);
  assert.deepEqual(
    node.widgets.map((widget) => widget.name),
    ["seed", "randomize", "new seed", "use last seed"],
  );
  assert.ok(
    node.widgets
      .slice(1)
      .every(
        (widget) =>
          widget.serialize === false && widget.options.serialize === false,
      ),
  );
  assert.equal(lastButton(node).disabled, true);
  press(node, "use last seed");
  assert.equal(seedWidget(node).value, 19);
  h.extension.nodeCreated(node);
  assert.equal(node.widgets.length, 4);
  assert.equal(
    h.addNode("2", 9, h.app.rootGraph, "OtherNode").widgets.length,
    1,
  );
  const wrapper = h.api.queuePrompt;
  h.extension.setup();
  assert.equal(h.api.queuePrompt, wrapper);
});

test("new seed samples the full safe-integer range; randomize selects -1", async () => {
  const h = await harness([
    [0, 0],
    [0xffffffff, 0xffffffff],
    [0xffe00001, 23],
  ]);
  const node = h.addNode("1");
  for (const expected of [0, MAX_SEED, 2 ** 32 + 23]) {
    press(node, "new seed");
    assert.equal(seedWidget(node).value, expected);
    assert.equal(seedWidget(node).callbackValue, expected);
    assert.equal(lastButton(node).disabled, true);
  }
  press(node, "randomize");
  assert.equal(seedWidget(node).value, -1);
  assert.equal(h.draws, 3);
  assert.equal(node.graph.dirty, 4);
  assert.equal(h.calls.length, 0);
});

test("random mode resolves once per submission, preserves visible mode, and records queued history", async () => {
  const h = await harness([
    [0, 10],
    [0, 20],
  ]);
  const node = h.addNode("1");
  const data = payload(h.app.rootGraph);
  const original = JSON.stringify(data);
  const first = await h.api.queuePrompt(0, data);
  assert.equal(first.prompt_id, "prompt-1");
  assert.equal(h.seedSent(), 10);
  assert.equal(h.calls[0].args[1].workflow.nodes[0].widgets_values[0], 10);
  assert.equal(data.output["1"].inputs.seed, 10);
  assert.equal(data.workflow.nodes[0].widgets_values[0], 10);
  assert.equal(JSON.stringify(payload(h.app.rootGraph)), original);
  assert.equal(seedWidget(node).value, -1);
  assert.equal(lastButton(node).disabled, false);
  await h.queue();
  assert.equal(h.seedSent(), 20);
  assert.equal(h.draws, 2);
  press(node, "use last seed");
  assert.equal(seedWidget(node).value, 20);
  await h.queue();
  assert.equal(h.seedSent(), 20);
  assert.equal(h.draws, 2);
});

for (const mode of [-1, -2, -3]) {
  test(`mode ${mode} saves a reproducible seed for named-value restoration`, async () => {
    const h = await harness([[0, 123]]);
    const node = h.addNode("1", mode);
    node.widgets.push({ name: "unrelated", value: "keep" });
    const data = payload(h.app.rootGraph);
    const originalWorkflow = data.workflow;
    const original = JSON.stringify(originalWorkflow);
    await h.api.queuePrompt(0, data);
    for (const workflow of [h.calls[0].args[1].workflow, data.workflow]) {
      const saved = workflow.nodes[0];
      assert.equal(saved.widgets_values[0], 123);
      assert.equal(saved.widgets_values_named.seed, 123);
      assert.equal(saved.widgets_values[1], "keep");
      assert.equal(saved.widgets_values_named.unrelated, "keep");
    }
    assert.equal(JSON.stringify(originalWorkflow), original);
    assert.equal(seedWidget(node).value, mode);

    const saved = JSON.parse(JSON.stringify(data.workflow)).nodes[0];
    const restored = await harness();
    restored.addNode(saved.id, saved.widgets_values_named.seed);
    await restored.queue();
    assert.equal(restored.seedSent(), 123);
    assert.equal(restored.draws, 0);
  });
}

for (const [mode, next] of [
  [-2, 42],
  [-3, 40],
]) {
  test(`mode ${mode} starts randomly, then steps from the last queued value`, async () => {
    const h = await harness();
    const node = h.addNode("1", mode);
    await h.queue();
    assert.equal(h.seedSent(), 41);
    await h.queue();
    assert.equal(h.seedSent(), next);
    assert.equal(h.calls[1].args[1].workflow.nodes[0].widgets_values[0], next);
    assert.equal(
      h.calls[1].args[1].workflow.nodes[0].widgets_values_named.seed,
      next,
    );
    assert.equal(seedWidget(node).value, mode);
    assert.equal(h.draws, 1);
    press(node, "use last seed");
    assert.equal(seedWidget(node).value, next);
  });
}

for (const [initial, mode, expected] of [
  [MAX_SEED, -2, 0],
  [0, -3, MAX_SEED],
  [0, -2, 1],
]) {
  test(`stepping ${initial} with ${mode} produces ${expected}`, async () => {
    const h = await harness();
    const node = h.addNode("1", initial);
    await h.queue();
    seedWidget(node).value = mode;
    await h.queue();
    assert.equal(h.seedSent(), expected);
    press(node, "use last seed");
    assert.equal(seedWidget(node).value, expected);
    assert.equal(h.draws, 0);
  });
}

test("new fixed values do not overwrite history until queued", async () => {
  const h = await harness([[0, 88]]);
  const node = h.addNode("1", 0);
  await h.queue();
  press(node, "new seed");
  assert.equal(seedWidget(node).value, 88);
  press(node, "use last seed");
  assert.equal(seedWidget(node).value, 0);
});

test("independent nodes advance through a batch without sharing history", async () => {
  const h = await harness();
  const first = h.addNode("1", 10);
  const second = h.addNode("2", 90);
  await h.queue();
  seedWidget(first).value = -2;
  seedWidget(second).value = -3;
  for (let i = 1; i <= 3; i++) {
    await h.queue();
    assert.equal(h.seedSent(undefined, "1"), 10 + i);
    assert.equal(h.seedSent(undefined, "2"), 90 - i);
  }
});

test("overlapping requests use accepted history in order, preserving arguments and return values", async () => {
  const h = await harness();
  const node = h.addNode("1", 10);
  await h.queue();
  seedWidget(node).value = -2;
  const gate = deferred();
  const response = { prompt_id: "accepted", extra: "unchanged" };
  h.respond = () => (h.calls.length === 2 ? gate.promise : response);
  const receiver = { custom: true };
  const options = {
    partialExecutionTargets: ["1"],
    previewMethod: "latent2rgb",
  };
  const extra = { futureOption: true };
  const first = h.api.queuePrompt.call(
    receiver,
    -1,
    payload(h.app.rootGraph),
    options,
    extra,
  );
  const second = h.queue();
  await tick();
  assert.equal(h.calls.length, 2);
  assert.equal(h.seedSent(), 11);
  assert.equal(h.calls[1].receiver, receiver);
  assert.equal(h.calls[1].args[0], -1);
  assert.equal(h.calls[1].args[2], options);
  assert.equal(h.calls[1].args[3], extra);
  gate.resolve(response);
  assert.equal(await first, response);
  assert.equal(await second, response);
  assert.equal(h.seedSent(), 12);
  press(node, "use last seed");
  assert.equal(seedWidget(node).value, 12);
});

test("rejected submissions neither advance history nor poison later requests", async () => {
  const h = await harness();
  const node = h.addNode("1", 50);
  await h.queue();
  seedWidget(node).value = -2;
  const error = new Error("queue rejected");
  h.respond = () => {
    throw error;
  };
  const rejectedData = payload(h.app.rootGraph);
  const beforeRejection = JSON.stringify(rejectedData);
  await assert.rejects(
    h.api.queuePrompt(0, rejectedData),
    (actual) => actual === error,
  );
  assert.equal(JSON.stringify(rejectedData), beforeRejection);
  assert.equal(h.seedSent(), 51);
  press(node, "use last seed");
  assert.equal(seedWidget(node).value, 50);
  seedWidget(node).value = -2;
  h.respond = () => ({ node_errors: { bad: true } });
  await h.queue();
  press(node, "use last seed");
  assert.equal(seedWidget(node).value, 50);
  seedWidget(node).value = -2;
  h.respond = () => ({ prompt_id: "accepted" });
  await h.queue();
  assert.equal(h.seedSent(), 51);
});

test("overlapping submissions can reuse a prompt object without mixing seed metadata", async () => {
  const h = await harness();
  const node = h.addNode("1", 10);
  await h.queue();
  seedWidget(node).value = -2;
  const data = payload(h.app.rootGraph);
  await Promise.all([h.api.queuePrompt(0, data), h.api.queuePrompt(0, data)]);
  for (const [index, expected] of [
    [1, 11],
    [2, 12],
  ]) {
    assert.equal(h.seedSent(index), expected);
    assert.equal(
      h.calls[index].args[1].workflow.nodes[0].widgets_values[0],
      expected,
    );
    assert.equal(
      h.calls[index].args[1].workflow.nodes[0].widgets_values_named.seed,
      expected,
    );
  }
  assert.equal(data.output["1"].inputs.seed, 12);
  assert.equal(data.workflow.nodes[0].widgets_values[0], 12);
  assert.equal(data.workflow.nodes[0].widgets_values_named.seed, 12);
});

test("a first failed random submission leaves use last seed unavailable", async () => {
  const h = await harness();
  const node = h.addNode("1");
  h.respond = () => {
    throw new Error("failed");
  };
  await assert.rejects(h.queue(), /failed/);
  assert.equal(lastButton(node).disabled, true);
  press(node, "use last seed");
  assert.equal(seedWidget(node).value, -1);
});

test("save, export, and repeated graph serialization have no side effects", async () => {
  const h = await harness();
  const node = h.addNode("1", -2);
  for (let i = 0; i < 4; i++) {
    const data = payload(h.app.rootGraph);
    assert.equal(data.output["1"].inputs.seed, -2);
    assert.deepEqual(data.workflow.nodes[0].widgets_values, [-2]);
  }
  assert.equal(h.draws, 0);
  assert.equal(h.calls.length, 0);
  assert.equal(lastButton(node).disabled, true);
});

test("editing the live seed during a request does not change the submitted value", async () => {
  const h = await harness();
  const node = h.addNode("1", 7);
  const gate = deferred();
  h.respond = () => gate.promise;
  const queued = h.queue();
  seedWidget(node).value = 99;
  await tick();
  assert.equal(h.seedSent(), 7);
  gate.resolve({ prompt_id: "accepted" });
  await queued;
  assert.equal(seedWidget(node).value, 99);
  press(node, "use last seed");
  assert.equal(seedWidget(node).value, 7);
});

test("reload clears history and old requests cannot restore it", async () => {
  const h = await harness();
  const node = h.addNode("1", 9);
  await h.queue();
  const gate = deferred();
  h.respond = () => gate.promise;
  const queued = h.queue();
  await tick();
  h.extension.loadedGraphNode(node);
  assert.equal(lastButton(node).disabled, true);
  gate.resolve({ prompt_id: "old-request" });
  await queued;
  assert.equal(lastButton(node).disabled, true);
  seedWidget(node).value = -2;
  press(node, "use last seed");
  assert.equal(seedWidget(node).value, -2);
  h.respond = () => ({ prompt_id: "new-request" });
  await h.queue();
  assert.equal(h.seedSent(), 41);
  press(node, "use last seed");
  assert.equal(seedWidget(node).value, 41);
});

test("a newly loaded node with the same ID does not inherit history", async () => {
  const h = await harness();
  h.addNode("1", 75);
  await h.queue();
  h.app.rootGraph = makeGraph("other-workflow");
  const replacement = h.addNode("1", -2);
  assert.equal(lastButton(replacement).disabled, true);
  await h.queue();
  assert.equal(h.seedSent(), 41);
});

test("partial execution follows dependencies and does not advance unrelated seeds", async () => {
  const h = await harness([[0, 101]]);
  const used = h.addNode("1");
  const unused = h.addNode("2");
  const consumer = h.addNode("3", 0, h.app.rootGraph, "Consumer");
  consumer.promptInputs = { seed: ["1", 0] };
  await h.queue({ partialExecutionTargets: ["3"] });
  assert.equal(h.seedSent(undefined, "1"), 101);
  assert.equal(h.seedSent(undefined, "2"), -1);
  assert.equal(lastButton(used).disabled, false);
  assert.equal(lastButton(unused).disabled, true);
  assert.equal(h.draws, 1);
});

test("muted and bypassed seeds keep no history", async () => {
  const h = await harness();
  const muted = h.addNode("1");
  const bypassed = h.addNode("2");
  muted.mode = 2;
  bypassed.mode = 4;
  await h.queue();
  assert.equal(h.draws, 0);
  assert.equal(lastButton(muted).disabled, true);
  assert.equal(lastButton(bypassed).disabled, true);
});

test("full nested paths distinguish repeated local IDs and update corresponding metadata", async () => {
  const h = await harness([
    [0, 10],
    [0, 20],
    [0, 30],
  ]);
  h.addNode("1");
  const left = makeGraph("left-definition");
  const inner = makeGraph("inner-definition");
  const right = makeGraph("right-definition");
  h.app.rootGraph.nodes.push(
    { id: "4", subgraph: left },
    { id: "5", subgraph: right },
  );
  left.nodes.push({ id: "8", subgraph: inner });
  const innerSeed = h.addNode("1", -1, inner);
  h.addNode("1", -1, right);
  await h.queue();
  assert.equal(h.seedSent(undefined, "1"), 10);
  assert.equal(h.seedSent(undefined, "4:8:1"), 20);
  assert.equal(h.seedSent(undefined, "5:1"), 30);
  const workflow = h.calls[0].args[1].workflow;
  for (const [saved, expected] of [
    [workflow.nodes[0], 10],
    [
      workflow.definitions.subgraphs.find((item) => item.id === inner.id)
        .nodes[0],
      20,
    ],
    [
      workflow.definitions.subgraphs.find((item) => item.id === right.id)
        .nodes[0],
      30,
    ],
  ]) {
    assert.equal(saved.widgets_values[0], expected);
    assert.equal(saved.widgets_values_named.seed, expected);
  }
  press(innerSeed, "use last seed");
  assert.equal(seedWidget(innerSeed).value, 20);
});

test("instances of one subgraph share their Seed widget and one seed per submission", async () => {
  const h = await harness();
  const definition = makeGraph("shared-definition");
  h.app.rootGraph.nodes.push(
    { id: "4", subgraph: definition },
    { id: "5", subgraph: definition },
  );
  const seed = h.addNode("1", -2, definition);
  await h.queue();
  assert.equal(h.seedSent(undefined, "4:1"), 41);
  assert.equal(h.seedSent(undefined, "5:1"), 41);
  assert.equal(h.draws, 1);
  await h.queue();
  assert.equal(h.seedSent(undefined, "4:1"), 42);
  assert.equal(h.seedSent(undefined, "5:1"), 42);
  press(seed, "use last seed");
  assert.equal(seedWidget(seed).value, 42);
});

test("partial execution can target a subgraph path", async () => {
  const h = await harness();
  const unused = h.addNode("1");
  const definition = makeGraph("definition");
  h.app.rootGraph.nodes.push({ id: "4", subgraph: definition });
  h.addNode("1", -2, definition);
  await h.queue({ partialExecutionTargets: ["4"] });
  assert.equal(h.seedSent(undefined, "4:1"), 41);
  assert.equal(lastButton(unused).disabled, true);
  assert.equal(h.draws, 1);
});

test("requests retain captured node references when the active tab changes", async () => {
  const h = await harness();
  const oldNode = h.addNode("1", 18);
  const gate = deferred();
  h.respond = () => gate.promise;
  const queued = h.queue();
  h.app.rootGraph = makeGraph("new-workflow");
  const newNode = h.addNode("1", 90);
  gate.resolve({ prompt_id: "old-workflow-request" });
  await queued;
  press(oldNode, "use last seed");
  assert.equal(seedWidget(oldNode).value, 18);
  assert.equal(lastButton(newNode).disabled, true);
});

test("mismatched workflow IDs cannot substitute another tab's history", async () => {
  const h = await harness();
  h.addNode("1");
  const data = payload(h.app.rootGraph);
  h.app.rootGraph.id = "different-workflow";
  await assert.rejects(h.api.queuePrompt(0, data), /no longer loaded/);
  assert.equal(h.calls.length, 0);
});

test("requests without frontend workflow data pass through without a headless fallback", async () => {
  const h = await harness();
  const node = h.addNode("1");
  const data = {
    output: { 1: { class_type: "LanyNodes_Seed", inputs: { seed: -1 } } },
  };
  await h.api.queuePrompt(0, data);
  assert.equal(h.calls[0].args[1], data);
  assert.equal(h.seedSent(), -1);
  assert.equal(h.draws, 0);
  assert.equal(lastButton(node).disabled, true);
});

test("object-shaped workflow widget values are updated without mutation", async () => {
  const h = await harness();
  h.addNode("1");
  const data = payload(h.app.rootGraph);
  data.workflow.nodes[0].widgets_values = { seed: -1, unrelated: "keep" };
  const originalValues = data.workflow.nodes[0].widgets_values;
  await h.api.queuePrompt(0, data);
  const values = h.calls[0].args[1].workflow.nodes[0].widgets_values;
  assert.equal(values.seed, 41);
  assert.equal(values.unrelated, "keep");
  assert.equal(data.workflow.nodes[0].widgets_values.seed, 41);
  assert.equal(originalValues.seed, -1);
});

test("legacy workflows without named widget values still resolve their seed", async () => {
  const h = await harness();
  h.addNode("1");
  const data = payload(h.app.rootGraph);
  delete data.workflow.nodes[0].widgets_values_named;
  await h.api.queuePrompt(0, data);
  const saved = data.workflow.nodes[0];
  assert.equal(h.seedSent(), 41);
  assert.equal(saved.widgets_values[0], 41);
  assert.equal(Object.hasOwn(saved, "widgets_values_named"), false);
});

for (const value of [-4, MAX_SEED + 1, 1.5, NaN, Infinity, true, "42"]) {
  test(`invalid submitted seed ${String(value)} fails before queueing`, async () => {
    const h = await harness();
    const node = h.addNode("1", value);
    await assert.rejects(h.queue(), /nonnegative safe integer/);
    assert.equal(h.calls.length, 0);
    assert.equal(lastButton(node).disabled, true);
  });
}
