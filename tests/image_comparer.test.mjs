// SPDX-License-Identifier: AGPL-3.0-only
// SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

// These small DOM/API doubles verify local contracts, not host rendering.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(
  new URL("../src/comfyui_lany_nodes/web/image_comparer.js", import.meta.url),
  "utf8",
);
const buttonSource = await readFile(
  new URL("../src/comfyui_lany_nodes/web/buttons.js", import.meta.url),
  "utf8",
);
const tick = () => new Promise((resolve) => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function results(count = 1, prefix = "") {
  const descriptors = (side) =>
    Array.from({ length: count }, (_, i) => ({
      filename: `${prefix}${side} ${i + 1}.png`,
      subfolder: "test & images",
      type: "temp",
    }));
  return { a_images: descriptors("a"), b_images: descriptors("b") };
}

async function harness(properties = {}) {
  const h = {
    decodes: [],
    frames: new Map(),
    timers: new Map(),
    fetched: [],
    anchors: [],
    revoked: [],
    blobs: [],
    forwarded: [],
    lifecycle: [],
    changes: [],
    draws: 0,
    executions: 0,
    bubbled: 0,
  };
  const captures = new Map();
  class Event {
    constructor(type, options = {}) {
      Object.assign(
        this,
        {
          type,
          button: 0,
          buttons: 0,
          pointerId: 1,
          isPrimary: type !== "click",
          clientX: 150,
          clientY: 100,
          bubbles: true,
          cancelable: true,
          ctrlKey: false,
          metaKey: false,
          altKey: false,
          shiftKey: false,
        },
        options,
      );
      this.type = type;
      this.stopped = false;
      this.defaultPrevented = false;
      this.target = null;
    }
    stopPropagation() {
      this.stopped = true;
    }
    preventDefault() {
      this.defaultPrevented = true;
    }
  }
  class Element {
    constructor(tag) {
      this.tagName = tag;
      this.children = [];
      this.attributes = {};
      this.listeners = new Map();
      this.style = {};
      this.textContent = "";
      this.rect = { left: 100, top: 60, width: 200, height: 100 };
      this.localWidth = 400;
    }
    append(...children) {
      for (const child of children) {
        child.remove();
        child.parent = this;
        this.children.push(child);
      }
    }
    remove() {
      if (this.parent)
        this.parent.children = this.parent.children.filter(
          (child) => child !== this,
        );
      this.parent = null;
    }
    contains(target) {
      return (
        target === this || this.children.some((child) => child.contains(target))
      );
    }
    setAttribute(key, value) {
      this.attributes[key] = String(value);
    }
    removeAttribute(key) {
      delete this.attributes[key];
    }
    get src() {
      return this.attributes.src;
    }
    set src(value) {
      this.attributes.src = value;
    }
    decode() {
      const pending = { ...deferred(), img: this, src: this.src };
      h.decodes.push(pending);
      return pending.promise;
    }
    getBoundingClientRect() {
      return this.rect;
    }
    get clientWidth() {
      return this.localWidth;
    }
    setPointerCapture(id) {
      captures.set(id, this);
    }
    hasPointerCapture(id) {
      return captures.get(id) === this;
    }
    releasePointerCapture(id) {
      if (!this.hasPointerCapture(id)) return;
      captures.delete(id);
      this.dispatchEvent(new Event("lostpointercapture", { pointerId: id }));
    }
    addEventListener(type, callback) {
      if (!this.listeners.has(type)) this.listeners.set(type, new Set());
      this.listeners.get(type).add(callback);
    }
    removeEventListener(type, callback) {
      this.listeners.get(type)?.delete(callback);
    }
    dispatchEvent(event) {
      event.target ??= this;
      for (const callback of this.listeners.get(event.type) ?? [])
        callback(event);
      if (!event.stopped && event.bubbles && this.parent)
        this.parent.dispatchEvent(event);
      return !event.defaultPrevented;
    }
    click() {
      if (this.disabled) return;
      if (this.tagName === "a") {
        h.anchors.push({
          filename: this.download,
          href: this.href,
          parent: this.parent,
        });
      }
      this.dispatchEvent(new Event("click"));
    }
  }
  const document = {
    createElement: (tag) => new Element(tag),
    body: new Element("body"),
  };
  for (const type of [
    "pointerdown",
    "pointermove",
    "pointerup",
    "mousedown",
    "mouseup",
    "mousemove",
    "click",
    "contextmenu",
    "wheel",
    "auxclick",
  ]) {
    document.body.addEventListener(type, (event) => {
      if (event.target.tagName !== "a") h.bubbled++;
    });
  }
  const canvasElement = new Element("canvas");
  for (const type of [
    "pointerdown",
    "pointermove",
    "pointerup",
    "pointercancel",
    "wheel",
  ]) {
    canvasElement.addEventListener(type, (event) => {
      h.forwarded.push(event);
      h.draws++;
      if (type === "pointerdown")
        canvasElement.setPointerCapture(event.pointerId);
      if (["pointerup", "pointercancel"].includes(type))
        canvasElement.releasePointerCapture(event.pointerId);
    });
  }
  h.makeGraph = () => ({
    nodes: new Map(),
    subgraphs: new Map(),
    getNodeById(id) {
      return this.nodes.get(String(id));
    },
    beforeChange: () => h.changes.push("before"),
    afterChange: () => h.changes.push("after"),
    setDirtyCanvas: () => h.draws++,
  });
  let nodeOutputs = {};
  const app = {
    registerExtension: (extension) => {
      h.extension = extension;
    },
    rootGraph: h.makeGraph(),
    get graph() {
      return this.rootGraph;
    },
    get nodeOutputs() {
      return nodeOutputs;
    },
    // ComfyApp dispatches this hook on assignment; history dispatches it explicitly.
    set nodeOutputs(value) {
      nodeOutputs = value;
      h.extension.onNodeOutputsUpdated?.(value);
    },
    canvas: {
      canvas: canvasElement,
      setDirty: () => h.draws++,
      read_only: false,
      dragging_canvas: false,
    },
    queuePrompt: () => h.executions++,
  };
  h.blob = new Blob(
    [
      Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l1sAAAAASUVORK5CYII=",
        "base64",
      ),
    ],
    { type: "image/png" },
  );
  h.respond = async () => ({ ok: true, blob: async () => h.blob });
  const api = {
    apiURL: (path) => `/comfy${path}`,
    fetchApi: (path, options) => {
      h.fetched.push({ path, options });
      return h.respond(path, options);
    },
  };
  let frameId = 0,
    timerId = 0;
  const context = vm.createContext({
    document,
    URLSearchParams,
    AbortController,
    PointerEvent: Event,
    WheelEvent: Event,
    URL: {
      createObjectURL: (blob) => {
        h.blobs.push(blob);
        return `blob:${h.blobs.length}`;
      },
      revokeObjectURL: (url) => h.revoked.push(url),
    },
    requestAnimationFrame: (callback) => {
      h.frames.set(++frameId, callback);
      return frameId;
    },
    cancelAnimationFrame: (id) => h.frames.delete(id),
    setTimeout: (callback) => {
      h.timers.set(++timerId, callback);
      return timerId;
    },
    clearTimeout: (id) => h.timers.delete(id),
  });
  const module = new vm.SourceTextModule(source, { context });
  await module.link((specifier) => {
    if (specifier === "./buttons.js") {
      return new vm.SourceTextModule(buttonSource, { context });
    }
    const name = specifier.endsWith("app.js") ? "app" : "api";
    return new vm.SyntheticModule(
      [name],
      function () {
        this.setExport(name, name === "app" ? app : api);
      },
      { context },
    );
  });
  await module.evaluate();
  h.makeNode = (
    comfyClass = "LanyNodes_ImageComparer",
    props = properties,
    { graph = app.rootGraph, id = graph.nodes.size + 1 } = {},
  ) => {
    const node = {
      id,
      graph,
      comfyClass,
      properties: { ...props },
      size: [100, 100],
      widgets: [],
      setSize(size) {
        this.size = size;
      },
      onExecuted(...args) {
        h.lifecycle.push({ name: "executed", receiver: this, args });
        return "executed";
      },
      onConfigure(...args) {
        h.lifecycle.push({ name: "configure", receiver: this, args });
        return "configured";
      },
      onPropertyChanged(...args) {
        h.lifecycle.push({ name: "property", receiver: this, args });
        return h.acceptProperty;
      },
      onRemoved(...args) {
        h.lifecycle.push({ name: "removed", receiver: this, args });
        this.graph.nodes.delete(String(this.id));
        return "removed";
      },
      addDOMWidget(name, type, root, options) {
        const widget = {
          name,
          type,
          element: root,
          options,
          onRemove() {
            h.lifecycle.push({ name: "widgetRemoved", receiver: this });
          },
        };
        this.widgets.push(widget);
        document.body.append(root);
        const previous = this.onRemoved;
        this.onRemoved = function (...args) {
          const result = previous.apply(this, args);
          widget.onRemove();
          return result;
        };
        return widget;
      },
    };
    graph.nodes.set(String(id), node);
    h.extension.nodeCreated(node);
    return node;
  };
  h.node = h.makeNode();
  h.widget = h.node.widgets[0];
  h.root = h.widget.element;
  [h.toolbar, h.viewport, h.downloadStatus] = h.root.children;
  [h.slider, h.click, h.navigation] = h.toolbar.children;
  [h.previous, h.counter, h.next] = h.navigation.children;
  [h.a, h.b, h.divider, h.status] = h.viewport.children;
  h.images = [h.a.children[0], h.b.children[0]];
  h.app = app;
  h.document = document;
  h.emit = (target, type, options = {}) => {
    const event = new Event(type, options);
    target.dispatchEvent(event);
    return event;
  };
  h.press = (target = h.viewport, options = {}) => {
    if (target.disabled) return;
    h.emit(target, "pointerdown", { buttons: 1, ...options });
    h.emit(target, "pointerup", options);
    h.emit(target, "click", options);
  };
  h.frame = () => {
    const callbacks = [...h.frames.values()];
    h.frames.clear();
    for (const callback of callbacks) callback();
  };
  h.resolvePair = async (offset = h.decodes.length - 2) => {
    h.decodes[offset].resolve();
    h.decodes[offset + 1].resolve();
    await tick();
  };
  h.load = async (message = results()) => {
    h.node.onExecuted(message);
    await h.resolvePair();
  };
  return h;
}

function isA(h) {
  assert.equal(h.b.style.clipPath, "inset(0 100% 0 0)");
}
function isB(h) {
  assert.equal(h.b.style.clipPath, "inset(0)");
}
function filename(call) {
  return new URL(call.path, "http://localhost").searchParams.get("filename");
}

test("one nonserialized host DOM widget; mode is a property and lifecycle callbacks are chained", async () => {
  const h = await harness();
  assert.equal(h.node.widgets.length, 1);
  h.extension.nodeCreated(h.node);
  assert.equal(h.node.widgets.length, 1);
  assert.equal(h.makeNode("OtherNode").widgets.length, 0);
  assert.equal(h.widget.serialize, false);
  assert.equal(h.widget.options.serialize, false);
  assert.equal(h.widget.options.selectOn.length, 0);
  assert.deepEqual(h.node.properties, { comparer_mode: "slider" });
  assert.equal(h.node.onExecuted(results(), 17), "executed");
  assert.equal(h.node.onConfigure("saved"), "configured");
  assert.equal(h.lifecycle[0].receiver, h.node);
  assert.equal(h.lifecycle[0].args[1], 17);
  assert.equal(h.node.onRemoved(23), "removed");
  assert.equal(h.lifecycle.find((item) => item.name === "removed").args[0], 23);
  assert.equal(
    h.lifecycle.find((item) => item.name === "widgetRemoved").receiver,
    h.widget,
  );
});

test("history restores each comparer by locator without replaying execution callbacks", async () => {
  const h = await harness({ comparer_mode: "click" });
  const other = h.makeNode(undefined, { comparer_mode: "slider" });
  const unrelated = h.makeNode("OtherNode");
  const disposed = h.makeNode();
  disposed.widgets[0].onRemove();
  const subgraph = h.makeGraph();
  const subgraphId = "11111111-1111-4111-8111-111111111111";
  h.app.rootGraph.subgraphs.set(subgraphId, subgraph);
  const nested = h.makeNode(undefined, {}, { graph: subgraph, id: h.node.id });

  // History populates the output store, then explicitly invokes the extension hook.
  Object.assign(h.app.nodeOutputs, {
    [h.node.id]: results(2, "history "),
    [other.id]: results(1, "other "),
    [unrelated.id]: results(1, "unrelated "),
    [disposed.id]: results(1, "disposed "),
    999: results(1, "missing "),
    [`${subgraphId}:${nested.id}`]: results(1, "nested "),
  });
  h.extension.onNodeOutputsUpdated?.(h.app.nodeOutputs);
  assert.equal(h.decodes.length, 6);
  assert.equal(h.a.style.visibility, "hidden");
  for (const offset of [0, 2, 4]) await h.resolvePair(offset);

  for (const [node, prefix] of [
    [h.node, "history "],
    [other, "other "],
    [nested, "nested "],
  ]) {
    const viewport = node.widgets[0].element.children[1];
    for (const [side, layer] of viewport.children.slice(0, 2).entries()) {
      assert.equal(layer.style.visibility, "visible");
      const query = new URL(layer.children[0].src, "http://localhost")
        .searchParams;
      assert.equal(query.get("filename"), `${prefix}${side ? "b" : "a"} 1.png`);
    }
  }
  assert.equal(h.node.properties.comparer_mode, "click");
  assert.equal(other.properties.comparer_mode, "slider");
  assert.equal(h.counter.textContent, "1 / 2");
  isA(h);
  assert.equal(disposed.widgets[0].element.parent, null);
  assert.equal(
    h.lifecycle.some((event) => event.name === "executed"),
    false,
  );
  assert.equal(h.executions, 0);
  assert.equal(h.draws, 0);
  assert.deepEqual(h.changes, []);
});

test("workflow switching restores outputs to the current node with the same ID", async () => {
  const h = await harness();
  await h.load(results(1, "previous workflow "));
  h.node.onRemoved();
  h.app.rootGraph = h.makeGraph();
  const restored = h.makeNode(
    undefined,
    { comparer_mode: "click" },
    { id: h.node.id },
  );
  restored.onConfigure({});

  h.app.nodeOutputs = { [restored.id]: results(2, "restored ") };
  assert.equal(h.decodes.length, 4);
  await h.resolvePair();
  const [toolbar, viewport] = restored.widgets[0].element.children;
  assert.equal(restored.properties.comparer_mode, "click");
  assert.equal(toolbar.children[2].children[1].textContent, "1 / 2");
  assert.equal(viewport.children[0].style.visibility, "visible");
  assert.equal(viewport.children[1].style.clipPath, "inset(0 100% 0 0)");
  const query = new URL(
    viewport.children[0].children[0].src,
    "http://localhost",
  ).searchParams;
  assert.equal(query.get("filename"), "restored a 1.png");
  assert.ok(h.images.every((img) => img.src === undefined));
  assert.equal(
    h.lifecycle.filter((event) => event.name === "executed").length,
    1,
  );
  assert.equal(h.executions, 0);
});

test("restored outputs invalidate pending decodes and validate saved image pairs", async () => {
  const h = await harness();
  h.app.nodeOutputs = { [h.node.id]: results(2, "old ") };
  assert.equal(h.decodes.length, 2);
  h.app.nodeOutputs = { [h.node.id]: results(1, "new ") };
  assert.equal(h.decodes.length, 4);
  await h.resolvePair(2);
  await h.resolvePair(0);
  assert.equal(h.a.style.visibility, "visible");
  assert.equal(h.status.style.display, "none");
  assert.equal(h.counter.textContent, "1 / 1");
  assert.ok(h.images[0].src.includes("new"));

  h.app.nodeOutputs = {
    [h.node.id]: { a_images: results().a_images, b_images: [] },
  };
  assert.equal(h.a.style.visibility, "hidden");
  assert.equal(h.navigation.style.display, "none");
  assert.match(h.status.textContent, /No matching/);
  assert.ok(h.images.every((img) => img.src === undefined));
  assert.equal(
    h.lifecycle.some((event) => event.name === "executed"),
    false,
  );
});

test("selected pair alone loads; both layers decode before display with independent fitted backgrounds", async () => {
  const h = await harness();
  h.node.onExecuted(results(3));
  assert.equal(h.decodes.length, 2);
  for (const layer of [h.a, h.b]) {
    assert.equal(layer.style.visibility, "hidden");
    assert.equal(layer.style.background, "#202020");
    assert.equal(layer.children[0].style.objectFit, "contain");
    assert.equal(layer.children[0].style.objectPosition, "center");
  }
  h.images[0].naturalWidth = 1024;
  h.images[0].naturalHeight = 512;
  h.images[1].naturalWidth = 256;
  h.images[1].naturalHeight = 1024;
  h.decodes[0].resolve();
  await tick();
  assert.equal(h.a.style.visibility, "hidden");
  h.decodes[1].resolve();
  await tick();
  assert.equal(h.a.style.visibility, "visible");
  assert.equal(h.b.style.visibility, "visible");
  assert.equal(h.status.style.display, "none");
  isA(h);
  for (const { src } of h.decodes) {
    assert.ok(src.startsWith("/comfy/view?"));
    const query = new URL(src, "http://localhost").searchParams;
    assert.deepEqual([...query.keys()].sort(), [
      "filename",
      "subfolder",
      "type",
    ]);
    assert.equal(query.get("subfolder"), "test & images");
    assert.equal(query.get("type"), "temp");
  }
});

test("slider reveals B on the left, coalesces moves, and compensates zoom", async () => {
  const h = await harness();
  await h.load();
  h.emit(h.viewport, "pointermove", { clientX: 120 });
  h.emit(h.viewport, "pointermove", { clientX: 150 });
  assert.equal(h.frames.size, 1);
  h.frame();
  assert.equal(h.b.style.clipPath, "inset(0 75% 0 0)");
  assert.equal(h.divider.style.left, "25%");
  assert.equal(h.divider.style.width, "2px");
  assert.equal(h.divider.style.display, "block");
  h.press();
  assert.equal(h.b.style.clipPath, "inset(0 75% 0 0)");
  h.viewport.rect = { left: 50, width: 800 };
  h.widget.options.onDraw();
  h.frame();
  assert.equal(h.divider.style.width, "0.5px");
  assert.equal(h.divider.style.left, "12.5%");
  for (const [clientX, expected] of [
    [0, "0%"],
    [900, "100%"],
  ]) {
    h.emit(h.viewport, "pointermove", { clientX });
    h.frame();
    assert.equal(h.divider.style.left, expected);
  }
  assert.equal(h.draws, 0);
  assert.equal(h.bubbled, 0);
});

test("leave cancels slider work and restores A; hidden widgets cancel and can reappear", async () => {
  const h = await harness();
  await h.load();
  h.emit(h.viewport, "pointermove");
  const stale = [...h.frames.values()][0];
  h.emit(h.viewport, "pointerleave");
  assert.equal(h.frames.size, 0);
  stale();
  isA(h);
  assert.equal(h.divider.style.display, "none");
  h.emit(h.viewport, "pointermove");
  h.frame();
  h.widget.options.onHide();
  isA(h);
  h.widget.options.onDraw();
  assert.equal(h.frames.size, 0);
  h.emit(h.viewport, "pointermove");
  h.frame();
  assert.equal(h.divider.style.display, "block");
});

test("Click repeatedly toggles, ignores motion and retains B on leave", async () => {
  const h = await harness();
  await h.load();
  h.press(h.click);
  for (let i = 0; i < 3; i++) {
    h.press();
    isB(h);
    h.press();
    isA(h);
  }
  h.press();
  isB(h);
  h.emit(h.viewport, "pointermove", { clientX: 250 });
  h.emit(h.viewport, "pointerleave");
  h.widget.options.onHide();
  isB(h);
  assert.equal(h.frames.size, 0);
  assert.equal(h.divider.style.display, "none");
  assert.equal(h.draws, 0);
  assert.equal(h.executions, 0);
  assert.equal(h.bubbled, 0);
});

test("mode persists, resets to A, and old Slider callbacks cannot override Click", async () => {
  const h = await harness();
  await h.load();
  h.emit(h.viewport, "pointermove");
  const stale = [...h.frames.values()][0];
  h.press(h.click);
  isA(h);
  assert.equal(h.node.properties.comparer_mode, "click");
  assert.deepEqual(h.changes, ["before", "after"]);
  h.press();
  isB(h);
  stale();
  isB(h);
  assert.equal(h.frames.size, 0);
  h.press(h.slider);
  isA(h);
  assert.equal(h.node.properties.comparer_mode, "slider");
  const restored = await harness({ comparer_mode: "click" });
  assert.equal(restored.click.attributes["aria-pressed"], "true");
  await restored.load();
  restored.press();
  isB(restored);
  restored.node.properties.comparer_mode = "slider";
  restored.node.onConfigure({});
  isA(restored);
  assert.equal(restored.slider.attributes["aria-pressed"], "true");
  restored.node.onPropertyChanged("comparer_mode", "click");
  assert.equal(restored.node.properties.comparer_mode, "click");
  restored.acceptProperty = false;
  restored.node.onPropertyChanged("comparer_mode", "slider");
  assert.equal(restored.node.properties.comparer_mode, "click");
  assert.equal(h.executions, 0);
});

test("only ordinary primary viewport clicks toggle; right-click, toolbar, drags and gestures do not", async () => {
  const h = await harness();
  await h.load(results(2));
  h.press(h.click);
  h.press(h.click);
  isA(h);
  h.emit(h.viewport, "click");
  isA(h); // No primary press in this viewport.
  h.press(h.viewport, { button: 2, buttons: 2 });
  isA(h);
  h.emit(h.viewport, "contextmenu", { button: 2 });
  isA(h);
  const requests = h.fetched.length;
  h.emit(h.toolbar, "contextmenu", { button: 2 });
  assert.equal(h.fetched.length, requests);
  isA(h);
  h.emit(h.viewport, "pointerdown", { buttons: 1 });
  h.emit(h.viewport, "pointermove", { buttons: 1, clientX: 180 });
  h.emit(h.viewport, "pointerup", { clientX: 150 });
  h.emit(h.viewport, "click");
  isA(h);
  for (const options of [
    { ctrlKey: true },
    { shiftKey: true },
    { altKey: true },
    { metaKey: true },
    { button: 1, buttons: 4 },
    { isPrimary: false },
  ]) {
    h.press(h.viewport, options);
    isA(h);
  }
  for (const nonPrimary of ["pointerdown", "pointerup"]) {
    h.emit(h.viewport, "pointerdown", {
      buttons: 1,
      isPrimary: nonPrimary !== "pointerdown",
    });
    h.emit(h.viewport, "pointerup", { isPrimary: nonPrimary !== "pointerup" });
    h.emit(h.viewport, "click");
    isA(h);
  }
  h.app.canvas.read_only = true;
  h.press();
  isA(h);
  h.app.canvas.read_only = false;
  h.press(h.next);
  isA(h);
  assert.equal(h.counter.textContent, "2 / 2");
});

test("batch navigation has boundaries, transient selection, and resets on every new result", async () => {
  const h = await harness();
  await h.load(results(3));
  h.press(h.click);
  assert.equal(h.counter.textContent, "1 / 3");
  assert.equal(h.previous.disabled, true);
  assert.equal(h.next.disabled, false);
  h.press(h.previous);
  assert.equal(h.decodes.length, 2);
  h.press();
  isB(h);
  h.press(h.next);
  isA(h);
  assert.equal(h.counter.textContent, "2 / 3");
  assert.equal(h.a.style.visibility, "hidden");
  await h.resolvePair();
  h.press(h.next);
  await h.resolvePair();
  assert.equal(h.counter.textContent, "3 / 3");
  assert.equal(h.next.disabled, true);
  assert.equal(h.previous.disabled, false);
  h.press(h.next);
  assert.equal(h.decodes.length, 6);
  h.press(h.previous);
  await h.resolvePair();
  assert.equal(h.counter.textContent, "2 / 3");
  await h.load(results(1, "new"));
  isA(h);
  assert.equal(h.navigation.style.display, "none");
  assert.equal(h.counter.textContent, "1 / 1");
  assert.deepEqual(h.node.properties, { comparer_mode: "click" });
  assert.equal(h.images[0], h.a.children[0]);
  assert.equal(h.images[1], h.b.children[0]);
});

test("out-of-order loads, failures and new executions cannot display mismatched pairs", async () => {
  const h = await harness();
  h.node.onExecuted(results(2));
  h.press(h.next);
  await h.resolvePair(0);
  assert.equal(h.a.style.visibility, "hidden");
  h.emit(h.viewport, "contextmenu");
  assert.equal(h.fetched.length, 0);
  h.decodes[2].resolve();
  await tick();
  assert.equal(h.a.style.visibility, "hidden");
  h.decodes[3].reject(new Error("broken PNG"));
  await tick();
  assert.match(h.status.textContent, /Unable to load/);
  assert.ok(h.images.every((img) => img.src === undefined));
  h.press(h.previous);
  h.node.onExecuted(results(1, "new"));
  h.decodes[4].reject(new Error("obsolete failure"));
  h.decodes[5].resolve();
  await tick();
  assert.equal(h.status.textContent, "Loading images…");
  await h.resolvePair(6);
  assert.equal(h.a.style.visibility, "visible");
  assert.ok(h.images[0].src.includes("newa"));
  h.node.onExecuted({ a_images: results().a_images, b_images: [] });
  assert.equal(h.a.style.visibility, "hidden");
  assert.match(h.status.textContent, /No matching/);
});

test("Slider downloads A on left/midpoint and B on right using viewport halves at any zoom", async () => {
  const h = await harness();
  await h.load();
  for (const [left, width] of [
    [100, 200],
    [-80, 800],
  ]) {
    h.viewport.rect = { left, width };
    for (const [fraction, side] of [
      [0, "a"],
      [0.25, "a"],
      [0.5, "a"],
      [0.5001, "b"],
      [1, "b"],
    ]) {
      const event = h.emit(h.viewport, "contextmenu", {
        button: 2,
        clientX: left + width * fraction,
      });
      assert.equal(event.defaultPrevented, true);
      assert.equal(filename(h.fetched.at(-1)), `${side} 1.png`);
    }
  }
  await tick();
  assert.equal(h.draws, 0);
  assert.equal(h.bubbled, 0);
});

test("Click downloads the visible side regardless of position, preserving PNG bytes and filename", async () => {
  const h = await harness();
  await h.load();
  h.press(h.click);
  for (const clientX of [100, 200, 300]) {
    h.emit(h.viewport, "contextmenu", { button: 2, clientX });
    assert.equal(filename(h.fetched.at(-1)), "a 1.png");
  }
  h.press();
  isB(h);
  for (const clientX of [100, 200, 300]) {
    h.emit(h.viewport, "contextmenu", { button: 2, clientX });
    assert.equal(filename(h.fetched.at(-1)), "b 1.png");
  }
  await tick();
  assert.equal(h.anchors.length, 6);
  assert.equal(h.anchors.at(-1).filename, "b 1.png");
  assert.equal(h.anchors.at(-1).parent, h.document.body);
  assert.equal(
    h.document.body.children.filter((item) => item.tagName === "a").length,
    0,
  );
  for (const blob of h.blobs) assert.equal(blob, h.blob);
  for (const call of h.fetched) {
    assert.ok(call.path.startsWith("/view?"));
    assert.equal(call.path.includes("preview"), false);
    assert.equal(call.options.cache, "no-store");
  }
  for (const timer of h.timers.values()) timer();
  assert.equal(h.revoked.length, 6);
  assert.equal(h.draws, 0);
  assert.equal(h.executions, 0);
  isB(h);
});

test("downloads snapshot the displayed pair before fetch and blob decoding, even across execution", async () => {
  const h = await harness();
  const message = results(2);
  await h.load(message);
  const fetch = deferred(),
    blob = deferred();
  h.respond = () => fetch.promise;
  h.emit(h.viewport, "contextmenu", { clientX: 250 });
  h.press(h.next);
  await h.resolvePair();
  message.b_images[0].filename = "mutated.png";
  fetch.resolve({ ok: true, blob: () => blob.promise });
  await tick();
  await h.load(results(1, "new"));
  h.press(h.click);
  h.press();
  blob.resolve(h.blob);
  await tick();
  assert.equal(filename(h.fetched[0]), "b 1.png");
  assert.equal(h.anchors[0].filename, "b 1.png");
  assert.equal(h.blobs[0], h.blob);
  assert.equal(h.draws, 0);
  isB(h);
});

test("download failures report an error without changing comparison or invalidating the graph", async () => {
  const h = await harness();
  await h.load();
  h.press(h.click);
  h.press();
  for (const respond of [
    () => Promise.reject(new Error("network")),
    async () => ({ ok: false, status: 404 }),
    async () => ({
      ok: true,
      blob: () => Promise.reject(new Error("truncated")),
    }),
  ]) {
    h.respond = respond;
    h.emit(h.viewport, "contextmenu");
    await tick();
    assert.match(h.downloadStatus.textContent, /Download failed: b 1.png/);
    isB(h);
    assert.equal(h.a.style.visibility, "visible");
  }
  assert.equal(h.draws, 0);
  assert.equal(h.blobs.length, 0);
});

test("local wheel and captured graph-pan adapter preserves coordinates and suppresses comparison", async () => {
  const h = await harness();
  await h.load();
  h.press(h.click);
  const wheel = h.emit(h.viewport, "wheel", {
    deltaX: 2,
    deltaY: 25,
    deltaMode: 1,
    ctrlKey: true,
  });
  assert.equal(wheel.defaultPrevented, true);
  assert.equal(h.forwarded[0].deltaY, 25);
  assert.equal(h.forwarded[0].deltaMode, 1);
  assert.equal(h.forwarded[0].ctrlKey, true);
  h.emit(h.viewport, "pointerdown", { button: 1, buttons: 4 });
  assert.equal(h.root.hasPointerCapture(1), true);
  h.emit(h.root, "pointermove", { button: -1, buttons: 4, clientX: 500 });
  h.emit(h.root, "pointerup", { button: 1, clientX: 500 });
  assert.equal(h.root.hasPointerCapture(1), false);
  assert.deepEqual(
    h.forwarded.map((event) => event.type),
    ["wheel", "pointerdown", "pointermove", "pointerup"],
  );
  assert.equal(h.forwarded[2].clientX, 500);
  h.emit(h.viewport, "click");
  isA(h);
  const forwarded = h.forwarded.length;
  h.emit(h.viewport, "pointermove");
  assert.equal(h.forwarded.length, forwarded);
  assert.equal(h.bubbled, 0);
});

test("loading and failed pairs disable Click and downloads; obsolete success cannot replace a new pair", async () => {
  const h = await harness();
  h.press(h.click);
  h.node.onExecuted(results(1, "old"));
  h.press();
  isA(h);
  h.emit(h.viewport, "contextmenu");
  assert.equal(h.fetched.length, 0);
  h.node.onExecuted(results(1, "new"));
  await h.resolvePair(2);
  h.press();
  isB(h);
  await h.resolvePair(0);
  isB(h);
  h.emit(h.viewport, "contextmenu");
  assert.equal(filename(h.fetched[0]), "newb 1.png");
  h.node.onExecuted(results());
  h.decodes[4].reject();
  await tick();
  h.press();
  isA(h);
  h.emit(h.viewport, "contextmenu");
  assert.equal(h.fetched.length, 1);
});

test("instances keep independent modes, results and handlers", async () => {
  const h = await harness();
  await h.load();
  const other = h.makeNode();
  other.onExecuted(results(1, "other"));
  await h.resolvePair();
  h.press(h.click);
  h.press();
  isB(h);
  const otherRoot = other.widgets[0].element;
  const otherViewport = otherRoot.children[1];
  assert.equal(other.properties.comparer_mode, "slider");
  h.emit(otherViewport, "contextmenu", { clientX: 150 });
  assert.equal(filename(h.fetched[0]), "othera 1.png");
  h.node.onRemoved();
  h.emit(otherViewport, "pointermove");
  h.frame();
  assert.equal(otherViewport.children[1].style.clipPath, "inset(0 75% 0 0)");
});

test("disposal releases listeners, image sources, URLs and pending work without stale effects", async () => {
  const h = await harness();
  await h.load();
  h.emit(h.viewport, "contextmenu");
  await tick();
  const fetch = deferred();
  h.respond = () => fetch.promise;
  h.emit(h.viewport, "contextmenu");
  h.node.onExecuted(results(1, "new"));
  await h.resolvePair();
  h.emit(h.viewport, "pointermove");
  const staleFrame = [...h.frames.values()][0];
  h.node.onRemoved();
  assert.equal(h.frames.size, 0);
  assert.equal(h.timers.size, 0);
  assert.equal(h.root.parent, null);
  assert.ok(h.images.every((img) => img.src === undefined));
  assert.equal(h.fetched[1].options.signal.aborted, true);
  assert.deepEqual(h.revoked, ["blob:1"]);
  const elements = (item) => [item, ...item.children.flatMap(elements)];
  assert.ok(
    elements(h.root).every((item) =>
      [...item.listeners.values()].every((handlers) => handlers.size === 0),
    ),
  );
  fetch.resolve({ ok: true, blob: async () => h.blob });
  await tick();
  staleFrame();
  h.node.onExecuted(results());
  assert.equal(h.anchors.length, 1);
  assert.equal(h.decodes.length, 4);
  assert.equal(h.draws, 0);
});

test("widget removal alone invalidates pending decodes and cleans up captured pan", async () => {
  const h = await harness();
  h.node.onExecuted(results());
  h.emit(h.viewport, "pointerdown", { button: 1, buttons: 4 });
  h.widget.onRemove();
  await h.resolvePair();
  assert.equal(h.a.style.visibility, "hidden");
  assert.equal(h.root.hasPointerCapture(1), false);
  assert.deepEqual(
    h.forwarded.map((event) => event.type),
    ["pointerdown", "pointercancel"],
  );
  assert.equal(h.frames.size, 0);
});
