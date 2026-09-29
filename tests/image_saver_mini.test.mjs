// SPDX-License-Identifier: AGPL-3.0-only
// SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

// DOM/API doubles check local behavior, not ComfyUI rendering compatibility.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(
  new URL("../src/comfyui_lany_nodes/web/image_saver_mini.js", import.meta.url),
  "utf8",
);
const buttonSource = await readFile(
  new URL("../src/comfyui_lany_nodes/web/buttons.js", import.meta.url),
  "utf8",
);

async function harness() {
  class Element {
    constructor(tag) {
      this.tagName = tag;
      this.style = {};
      this.attributes = {};
      this.children = [];
      this.listeners = new Map();
    }
    setAttribute(key, value) {
      this.attributes[key] = value;
    }
    append(child) {
      this.children.push(child);
    }
    remove() {
      this.removed = true;
    }
    addEventListener(type, listener) {
      this.listeners.set(type, listener);
    }
    removeEventListener(type, listener) {
      if (this.listeners.get(type) === listener) this.listeners.delete(type);
    }
    click(options = {}) {
      const event = {
        button: 0,
        stopPropagation() {
          this.stopped = true;
        },
        ...options,
      };
      this.listeners.get("click")?.(event);
      return event;
    }
  }
  const h = { changes: [], callbacks: [], lifecycle: [], dirty: 0 };
  const app = {
    registerExtension(extension) {
      h.extension = extension;
    },
  };
  const context = vm.createContext({
    document: { createElement: (tag) => new Element(tag) },
  });
  const module = new vm.SourceTextModule(source, { context });
  await module.link((specifier) => {
    if (specifier === "./buttons.js")
      return new vm.SourceTextModule(buttonSource, { context });
    assert.equal(specifier, "../../scripts/app.js");
    return new vm.SyntheticModule(
      ["app"],
      function () {
        this.setExport("app", app);
      },
      { context },
    );
  });
  await module.evaluate();

  h.makeNode = (format = "png", comfyClass = "LanyNodes_ImageSaverMini") => {
    const defaults = {
      format,
      path: "",
      filename: "%time_%model_%seed",
      models: "",
      seed: 0,
      steps: 20,
      width: 0,
      height: 0,
      time_format: "%Y-%m-%d-%H%M%S",
      jpg_quality: 80,
      optimize_png: false,
      png_embed_workflow: true,
      additional_hashes: "",
    };
    const node = {
      comfyClass,
      widgets: Object.entries(defaults).map(([name, value]) => ({
        name,
        value,
        type: name === "format" ? "combo" : "input",
        options: {},
        callback(value) {
          h.callbacks.push([this.name, value]);
          return "callback";
        },
      })),
      graph: {
        beforeChange() {
          h.changes.push("before");
        },
        afterChange() {
          h.changes.push("after");
        },
        setDirtyCanvas() {
          h.dirty++;
        },
      },
      addDOMWidget(name, type, element, options) {
        const widget = {
          name,
          type,
          element,
          options,
          onRemove() {
            h.lifecycle.push("widget removed");
          },
        };
        this.widgets.push(widget);
        return widget;
      },
      expandToFitContent() {
        this.expanded = true;
      },
      onConfigure() {
        h.lifecycle.push("configured");
        return "configured";
      },
      onRemoved() {
        h.lifecycle.push("removed");
        return "removed";
      },
    };
    h.extension.nodeCreated(node);
    return node;
  };
  h.find = (node, name) => node.widgets.find((widget) => widget.name === name);
  h.serialize = (node) =>
    node.widgets
      .filter((widget) => widget.serialize !== false)
      .map((widget) => widget.value);
  h.prompt = (node) =>
    Object.fromEntries(
      node.widgets
        .filter((widget) => widget.options.serialize !== false)
        .map((widget) => [widget.name, widget.value]),
    );
  h.restore = (node, values) => {
    node.widgets
      .filter((widget) => widget.serialize !== false)
      .forEach((widget, i) => {
        widget.value = values[i];
      });
    return node.onConfigure({ widgets_values: values });
  };
  h.node = h.makeNode();
  h.toolbar = h.find(h.node, "lany_image_saver_format");
  [h.png, h.jpg] = h.toolbar.element.children;
  return h;
}

test("format controls and spacer are nonserialized and ordered without prompt text widgets", async () => {
  const h = await harness();
  assert.equal(h.extension.name, "LanyNodes.ImageSaverMini");
  assert.equal(h.node.widgets[0], h.toolbar);
  assert.deepEqual(
    h.toolbar.element.children.map((item) => item.textContent),
    ["png", "jpg"],
  );
  const format = h.find(h.node, "format");
  assert.equal(format.hidden, true);
  assert.equal(format.options.hidden, true);
  assert.equal(format.value, "png");
  assert.equal(h.png.attributes["aria-pressed"], "true");
  assert.equal(h.jpg.attributes["aria-pressed"], "false");
  const spacer = h.find(h.node, "lany_image_saver_spacer");
  const index = h.node.widgets.indexOf(spacer);
  assert.equal(h.node.widgets[index - 1].name, "height");
  assert.equal(h.node.widgets[index + 1].name, "time_format");
  for (const widget of [spacer, h.toolbar]) {
    assert.equal(widget.serialize, false);
    assert.equal(widget.options.serialize, false);
  }
  assert.equal(h.find(h.node, "positive"), undefined);
  assert.equal(h.find(h.node, "negative"), undefined);
  assert.equal(h.node.expanded, true);
  assert.equal(h.prompt(h.node).format, "png");
  assert.equal(h.prompt(h.node).path, "");
  assert.equal(Object.keys(h.prompt(h.node)).length, 13);
  const count = h.node.widgets.length;
  h.extension.nodeCreated(h.node);
  assert.equal(h.node.widgets.length, count);
  assert.equal(h.makeNode("png", "OtherNode").widgets.length, 13);
});

test("buttons update the API value, pressed style, disabled controls, and graph undo transaction", async () => {
  const h = await harness();
  const quality = h.find(h.node, "jpg_quality");
  assert.equal(quality.disabled, true);
  assert.equal(quality.options.disabled, true);
  quality.value = 93;
  assert.equal(h.jpg.click().stopped, true);
  assert.equal(h.prompt(h.node).format, "jpg");
  assert.equal(h.jpg.attributes["aria-pressed"], "true");
  // The format combo is hidden, so the border is the visible selection cue.
  assert.equal(h.jpg.style.borderColor, "var(--input-text, #ddd)");
  assert.equal(h.png.attributes["aria-pressed"], "false");
  assert.equal(quality.disabled, false);
  for (const name of ["optimize_png", "png_embed_workflow"]) {
    assert.equal(h.find(h.node, name).disabled, true);
    assert.equal(h.find(h.node, name).options.disabled, true);
  }
  assert.deepEqual(h.changes, ["before", "after"]);
  assert.deepEqual(h.callbacks, [["format", "jpg"]]);
  h.jpg.click();
  assert.equal(h.changes.length, 2);
  h.png.click();
  assert.equal(quality.value, 93);
  assert.equal(quality.disabled, true);
  assert.equal(h.find(h.node, "png_embed_workflow").disabled, false);
  assert.ok(h.dirty >= 3);
});

test("workflow restore, clone, undo/redo, and loadedGraphNode refresh the existing schema value", async () => {
  const h = await harness();
  const before = h.serialize(h.node);
  h.find(h.node, "path").value = "portraits/day";
  h.jpg.click();
  const after = h.serialize(h.node);
  assert.equal(after[0], "jpg");
  assert.equal(after.length, before.length);
  const clone = h.makeNode();
  assert.equal(h.restore(clone, after), "configured");
  const cloneButtons = h.find(clone, "lany_image_saver_format").element
    .children;
  assert.equal(cloneButtons[1].attributes["aria-pressed"], "true");
  assert.equal(h.prompt(clone).format, "jpg");
  assert.equal(h.prompt(clone).path, "portraits/day");
  h.restore(h.node, before);
  assert.equal(h.png.attributes["aria-pressed"], "true");
  h.restore(h.node, after);
  assert.equal(h.jpg.attributes["aria-pressed"], "true");
  h.find(h.node, "format").value = "png";
  h.extension.loadedGraphNode(h.node);
  assert.equal(h.png.attributes["aria-pressed"], "true");
  assert.deepEqual(h.changes, ["before", "after"]);
});

test("modified clicks do not change format, callbacks retain their result, and removal cleans listeners", async () => {
  const h = await harness();
  for (const options of [
    { ctrlKey: true },
    { altKey: true },
    { metaKey: true },
    { shiftKey: true },
    { button: 2 },
  ])
    h.jpg.click(options);
  assert.equal(h.prompt(h.node).format, "png");
  assert.deepEqual(h.changes, []);
  const format = h.find(h.node, "format");
  format.value = "jpg";
  assert.equal(format.callback("jpg"), "callback");
  assert.equal(h.jpg.attributes["aria-pressed"], "true");
  assert.equal(h.node.onRemoved(), "removed");
  assert.equal(h.toolbar.element.removed, true);
  assert.equal(h.find(h.node, "lany_image_saver_spacer").element.removed, true);
  assert.equal(h.png.listeners.size, 0);
  assert.equal(h.jpg.listeners.size, 0);
  h.toolbar.onRemove();
  assert.deepEqual(h.lifecycle, ["removed", "widget removed"]);
  h.png.click();
  assert.equal(format.value, "jpg");
});
