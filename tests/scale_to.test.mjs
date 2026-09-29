// SPDX-License-Identifier: AGPL-3.0-only
// SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

// DOM doubles check local behavior, not ComfyUI rendering compatibility.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(
  new URL("../src/comfyui_lany_nodes/web/scale_to.js", import.meta.url),
  "utf8",
);

async function harness() {
  const h = {};
  const app = {
    registerExtension(extension) {
      h.extension = extension;
    },
  };
  const context = vm.createContext({
    document: { createElement: (tag) => ({ tagName: tag, style: {} }) },
  });
  const module = new vm.SourceTextModule(source, { context });
  await module.link((specifier) => {
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

  h.makeNode = (comfyClass = "LanyNodes_ScaleTo") => {
    const node = {
      comfyClass,
      widgets: ["width", "height", "scale"].map((name) => ({ name, value: 1 })),
      addDOMWidget(name, type, element, options) {
        const widget = { name, type, element, options };
        this.widgets.push(widget);
        return widget;
      },
      expandToFitContent() {},
      onExecuted() {
        return "executed";
      },
    };
    h.extension.nodeCreated(node);
    return node;
  };
  return h;
}

test("a nonserialized footer shows ScaleTo's ui.dimensions", async () => {
  const h = await harness();
  const node = h.makeNode();
  const footer = node.widgets.at(-1);
  assert.equal(footer.serialize, false);
  assert.equal(footer.options.serialize, false);
  // test_nodes.py pins this message shape from ScaleTo.execute(...).ui.
  assert.equal(node.onExecuted({ dimensions: ["(50x52)"] }), "executed");
  assert.equal(footer.element.textContent, "(50x52)");
  node.onExecuted({ dimensions: [50] });
  assert.equal(footer.element.textContent, "(50x52)");
  assert.equal(h.makeNode("OtherNode").widgets.length, 3);
});
