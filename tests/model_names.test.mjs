// SPDX-License-Identifier: AGPL-3.0-only
// SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

// Local DOM/lifecycle contracts, not a live ComfyUI compatibility check.
// Markup follows PrimeVue 4.2.5 MultiSelect, Chip and BaseComponent sources.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(
  new URL("../src/comfyui_lany_nodes/web/model_names.js", import.meta.url),
  "utf8",
);
const marker = "data-lany-model-names";
const badgeSelector = ".lany-model-names-number";
const alpha = "checkpoints/Alpha.safetensors";
const beta = "checkpoints/Beta.safetensors";
const gamma = "diffusion_models/Gamma.safetensors";

async function harness() {
  const h = { observers: [], ticks: [], writes: 0, refreshes: 0, hooks: [] };
  function mutation(record) {
    h.writes++;
    for (const observer of h.observers) {
      if (
        observer.targets.some(
          ([target, options]) =>
            (target === record.target ||
              (options.subtree && target.contains(record.target))) &&
            options[record.type] &&
            (record.type !== "attributes" ||
              !options.attributeFilter ||
              options.attributeFilter.includes(record.attributeName)),
        )
      ) {
        observer.records.push(record);
      }
    }
  }
  class Element {
    nodeType = 1;
    parentElement = null;
    children = [];
    attributes = new Map();
    listeners = new Map();
    text = "";
    constructor(tag, document) {
      this.tagName = tag.toUpperCase();
      this.ownerDocument = document;
    }
    setAttribute(name, value) {
      this.attributes.set(name, String(value));
      mutation({ type: "attributes", target: this, attributeName: name });
    }
    getAttribute(name) {
      return this.attributes.get(name) ?? null;
    }
    removeAttribute(name) {
      if (this.attributes.delete(name))
        mutation({ type: "attributes", target: this, attributeName: name });
    }
    set id(value) {
      this.setAttribute("id", value);
    }
    get id() {
      return this.getAttribute("id") ?? "";
    }
    set className(value) {
      this.setAttribute("class", value);
    }
    get className() {
      return this.getAttribute("class") ?? "";
    }
    set hidden(value) {
      if (value) this.setAttribute("hidden", "");
      else this.removeAttribute("hidden");
    }
    get hidden() {
      return this.attributes.has("hidden");
    }
    get textContent() {
      return (
        this.text + this.children.map((child) => child.textContent).join("")
      );
    }
    set textContent(value) {
      const removedNodes = [...this.children];
      for (const child of removedNodes) child.parentElement = null;
      this.children = [];
      this.text = String(value);
      mutation({
        type: "childList",
        target: this,
        addedNodes: [],
        removedNodes,
      });
    }
    insertBefore(child, before) {
      child.remove();
      const index =
        before === null ? this.children.length : this.children.indexOf(before);
      assert.ok(index >= 0, "insertion anchor must be a direct child");
      this.children.splice(index, 0, child);
      child.parentElement = this;
      mutation({
        type: "childList",
        target: this,
        addedNodes: [child],
        removedNodes: [],
      });
    }
    append(...children) {
      for (const child of children) this.insertBefore(child, null);
    }
    remove() {
      if (!this.parentElement) return;
      const target = this.parentElement;
      target.children.splice(target.children.indexOf(this), 1);
      this.parentElement = null;
      mutation({
        type: "childList",
        target,
        addedNodes: [],
        removedNodes: [this],
      });
    }
    replaceChildren(...children) {
      this.textContent = "";
      this.append(...children);
    }
    contains(element) {
      return (
        element === this ||
        this.children.some((child) => child.contains(element))
      );
    }
    matches(selector) {
      if (selector.startsWith("."))
        return this.className.split(/\s+/).includes(selector.slice(1));
      const parts = [...selector.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)];
      assert.equal(
        parts.map(([part]) => part).join(""),
        selector,
        `unsupported test selector: ${selector}`,
      );
      return parts.every(([, name, value]) =>
        value === undefined
          ? this.attributes.has(name)
          : this.getAttribute(name) === value,
      );
    }
    querySelectorAll(selector) {
      return this.children.flatMap((child) => [
        ...(child.matches(selector) ? [child] : []),
        ...child.querySelectorAll(selector),
      ]);
    }
    querySelector(selector) {
      return this.querySelectorAll(selector)[0] ?? null;
    }
    addEventListener(type, listener) {
      this.listeners.set(type, listener);
    }
    click() {
      this.listeners.get("click")?.();
    }
  }
  const document = {
    createElement(tag) {
      return new Element(tag, document);
    },
    getElementById(id) {
      const search = (element) =>
        element.id === id
          ? element
          : element.children.map(search).find(Boolean);
      return search(document.head) ?? search(document.body) ?? null;
    },
  };
  document.head = document.createElement("head");
  document.body = document.createElement("body");
  h.document = document;
  h.element = (tag, attributes = {}, text) => {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes))
      element.setAttribute(key, value);
    if (text !== undefined) element.textContent = text;
    return element;
  };
  class MutationObserver {
    targets = [];
    records = [];
    constructor(callback) {
      this.callback = callback;
      h.observers.push(this);
    }
    observe(target, options) {
      assert.notEqual(
        target,
        document.body,
        "must not observe document-wide mutations",
      );
      assert.notEqual(target, document, "must not observe the document");
      this.targets.push([target, options]);
    }
    disconnect() {
      this.targets = [];
      this.records = [];
    }
  }
  h.flush = () => {
    for (let pass = 0; pass < 20; pass++) {
      if (
        !h.ticks.length &&
        !h.observers.some((observer) => observer.records.length)
      )
        return;
      for (const observer of h.observers) {
        if (observer.records.length)
          observer.callback(observer.records.splice(0));
      }
      for (const tick of h.ticks.splice(0)) {
        h.refreshes++;
        tick();
      }
    }
    assert.fail("observer/render tick loop did not settle");
  };
  const app = {
    registerExtension(extension) {
      h.extension = extension;
    },
  };
  const context = vm.createContext({ document, MutationObserver });
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

  const nativeMixin = Object.freeze({
    mounted() {
      h.hooks.push("native mixin");
    },
  });
  h.component = Object.freeze({
    __name: "MultiSelectWidget",
    setup() {},
    render() {},
    mixins: Object.freeze([nativeMixin]),
    mounted() {
      h.hooks.push("mounted");
    },
    updated() {
      h.hooks.push("updated");
    },
    beforeUnmount() {
      h.hooks.push("beforeUnmount");
    },
  });
  const values = new WeakMap();
  h.setValue = (widget, value) =>
    values.set(
      widget,
      Array.isArray(value) ? Object.freeze([...value]) : value,
    );
  h.makeNode = (
    models = [],
    loras = [],
    comfyClass = "LanyNodes_ModelNames",
  ) => {
    const node = {
      comfyClass,
      widgets: ["models", "loras"].map((name, i) => {
        const widget = {
          name,
          type: "custom",
          component: h.component,
          inputSpec: Object.freeze({ multi_select: { chip: true } }),
          options: Object.freeze({ serialize: true }),
          callback() {
            assert.fail("adapter must not invoke selection callbacks");
          },
          get value() {
            return values.get(this);
          },
          set value(_) {
            assert.fail("adapter must not write widget values");
          },
        };
        h.setValue(widget, i === 0 ? models : loras);
        return widget;
      }),
    };
    return node;
  };
  h.payload = (node) =>
    JSON.stringify({
      workflow: {
        type: node.comfyClass,
        widgets_values: node.widgets.map((widget) => widget.value),
      },
      prompt: {
        class_type: node.comfyClass,
        inputs: Object.fromEntries(
          node.widgets.map((widget) => [widget.name, widget.value]),
        ),
      },
    });
  let listId = 0;
  h.mount = (widget, options = [alpha, beta, gamma]) => {
    const f = { widget, options, rows: new Map(), chips: new Map() };
    f.root = h.element("div");
    f.picker = h.element("div", { "data-pc-name": "multiselect" });
    f.combobox = h.element("input", {
      role: "combobox",
      "aria-expanded": "false",
    });
    f.labels = h.element("div", { "data-pc-section": "label" });
    f.picker.append(f.combobox, f.labels);
    f.root.append(f.picker);
    document.body.append(f.root);
    f.instance = {
      $el: f.root,
      $props: { widget },
      $nextTick(callback) {
        h.ticks.push(callback);
      },
    };
    f.hook = (name) => {
      const invoke = (definition) => {
        for (const mixin of definition.mixins ?? []) invoke(mixin);
        for (const hook of [definition[name]].flat().filter(Boolean))
          hook.call(f.instance);
      };
      invoke(widget.component);
    };
    f.checkbox = (section, selected) => {
      const checkbox = h.element("div", {
        "data-pc-name": section,
        "data-pc-extend": "checkbox",
      });
      const input = h.element("input", { type: "checkbox", tabindex: "-1" });
      const box = h.element("div", { "data-pc-section": "box" });
      const icon = h.element("svg", { "data-pc-section": `${section}.icon` });
      checkbox.append(input, box);
      if (selected) box.append(icon);
      return { checkbox, input, box, icon };
    };
    f.makeChip = (path) => {
      const chip = h.element("div", {
        "data-pc-name": "pcchip",
        "data-pc-extend": "chip",
        "aria-label": path,
        title: path,
      });
      const label = h.element("div", { "data-pc-section": "label" }, path);
      const remove = h.element("svg", {
        "data-pc-section": "removeicon",
        tabindex: "0",
        role: "button",
        "aria-label": "Remove",
      });
      remove.addEventListener("click", () =>
        f.select(widget.value.filter((value) => value !== path)),
      );
      chip.append(label, remove);
      f.chips.set(path, { chip, label, remove });
      return chip;
    };
    f.render = () => {
      f.chips.clear();
      f.labels.replaceChildren(
        ...(widget.value.length <= 3
          ? widget.value.map(f.makeChip)
          : [h.element("span", {}, `${widget.value.length} items selected`)]),
      );
      for (const [path, row] of f.rows) {
        const selected = widget.value.includes(path);
        row.item.setAttribute("aria-selected", String(selected));
        if (selected && !row.icon.parentElement) row.box.append(row.icon);
        if (!selected) row.icon.remove();
      }
    };
    f.select = (value) => {
      h.setValue(widget, value);
      f.render();
      f.hook("updated");
    };
    f.filter = (paths) => {
      f.rows.clear();
      f.list.replaceChildren(
        ...paths.map((path) => {
          const item = h.element("li", {
            role: "option",
            "aria-label": path,
            "aria-selected": String(widget.value.includes(path)),
            "aria-posinset": "1",
          });
          const label = h.element(
            "span",
            { "data-pc-section": "optionlabel" },
            path,
          );
          const checkbox = f.checkbox(
            "pcoptioncheckbox",
            widget.value.includes(path),
          );
          item.append(checkbox.checkbox, label);
          item.addEventListener("click", () =>
            f.select(
              widget.value.includes(path)
                ? widget.value.filter((value) => value !== path)
                : [...widget.value, path],
            ),
          );
          f.rows.set(path, { item, label, ...checkbox });
          return item;
        }),
      );
    };
    f.open = (inline = false) => {
      f.overlay = h.element("div");
      f.header = f.checkbox("pcheadercheckbox", true);
      f.list = h.element("ul", {
        id: `native-list-${++listId}`,
        role: "listbox",
      });
      f.overlay.append(f.header.checkbox, f.list);
      (inline ? f.picker : document.body).append(f.overlay);
      f.filter(options);
      f.combobox.setAttribute("aria-controls", f.list.id);
      f.combobox.setAttribute("aria-expanded", "true");
    };
    f.close = () => {
      f.overlay.remove();
      f.combobox.removeAttribute("aria-controls");
      f.combobox.setAttribute("aria-expanded", "false");
    };
    f.unmount = () => {
      f.hook("beforeUnmount");
      f.root.remove();
      f.overlay?.remove();
    };
    f.render();
    f.hook("mounted");
    return f;
  };
  h.ready = (models = [gamma, alpha, beta], options) => {
    const node = h.makeNode(models);
    h.extension.nodeCreated(node);
    const f = h.mount(node.widgets[0], options);
    f.node = node;
    f.open();
    h.flush();
    return f;
  };
  return h;
}

function number(element) {
  return element.querySelector(badgeSelector)?.textContent ?? null;
}
function assertNumbers(f) {
  for (const [path, { item }] of f.rows) {
    const index = f.widget.value.indexOf(path);
    assert.equal(number(item), index < 0 ? null : String(index + 1), path);
  }
  for (const [path, { chip }] of f.chips)
    assert.equal(number(chip), String(f.widget.value.indexOf(path) + 1), path);
}

test("installation preserves native components, widgets and workflow/API payloads", async () => {
  const h = await harness();
  const node = h.makeNode([gamma, alpha], ["loras/one.safetensors"]);
  const widgets = [...node.widgets];
  const before = h.payload(node);
  const callbacks = widgets.map((widget) => widget.callback);
  const specs = widgets.map((widget) => widget.inputSpec);
  h.extension.nodeCreated(node);
  const components = widgets.map((widget) => widget.component);
  for (const widget of widgets) {
    assert.notEqual(widget.component, h.component);
    for (const key of [
      "setup",
      "render",
      "mounted",
      "updated",
      "beforeUnmount",
    ])
      assert.equal(widget.component[key], h.component[key]);
    assert.equal(widget.component.mixins.length, 2);
    assert.equal(widget.component.mixins[0], h.component.mixins[0]);
  }
  h.extension.nodeCreated(node);
  h.extension.loadedGraphNode(node);
  const f = h.mount(widgets[0]);
  f.open();
  h.flush();
  f.hook("updated");
  h.flush();
  f.unmount();
  assert.deepEqual(h.hooks, [
    "native mixin",
    "mounted",
    "updated",
    "beforeUnmount",
  ]);
  assert.deepEqual(node.widgets, widgets);
  assert.deepEqual(
    widgets.map((widget) => widget.component),
    components,
  );
  assert.deepEqual(
    widgets.map((widget) => widget.callback),
    callbacks,
  );
  assert.deepEqual(
    widgets.map((widget) => widget.inputSpec),
    specs,
  );
  assert.equal(h.payload(node), before);
  assert.equal(h.component.mixins.length, 1);
  assert.equal(h.extension.name, "LanyNodes.ModelNames");
});

test("Models, LoRAs, separate nodes and rendered instances number independently", async () => {
  const h = await harness();
  const nodes = [
    h.makeNode([gamma, alpha, beta], [beta, gamma]),
    h.makeNode([beta], [alpha, gamma]),
  ];
  const fixtures = [];
  for (const node of nodes) {
    h.extension.nodeCreated(node);
    for (const widget of node.widgets) fixtures.push(h.mount(widget));
  }
  fixtures.push(h.mount(nodes[0].widgets[0]));
  for (const f of fixtures) f.open();
  h.flush();
  for (const f of fixtures) assertNumbers(f);
  assert.equal(number(fixtures[0].rows.get(gamma).item), "1");
  assert.equal(number(fixtures[0].rows.get(alpha).item), "2");
  assert.equal(number(fixtures[1].rows.get(beta).item), "1");
  fixtures[0].unmount();
  h.flush();
  assertNumbers(fixtures[4]);
  assert.equal(h.document.head.children.length, 1);
});

test("filtering and row reuse use complete paths, never basenames or visible order", async () => {
  const h = await harness();
  const paths = [
    "diffusion_models/a/model.safetensors",
    "checkpoints/b/model.safetensors",
    'checkpoints/<model & "other">.safetensors',
  ];
  const f = h.ready([paths[2], paths[0], paths[1]], [...paths].sort());
  const old = f.rows.get(paths[0]).item;
  f.filter([paths[1]]);
  h.flush();
  assertNumbers(f);
  assert.equal(number(f.rows.get(paths[1]).item), "3");
  assert.equal(number(old), null);
  const row = f.rows.get(paths[1]);
  row.item.setAttribute("aria-label", paths[2]);
  row.label.textContent = paths[2];
  h.flush();
  assert.equal(number(row.item), "1");
  f.filter(paths);
  h.flush();
  assertNumbers(f);
  assert.equal(f.chips.get(paths[2]).label.textContent, paths[2]);
});

test("native deselection, reselection, chip removal, bulk operations and clearing renumber", async () => {
  const h = await harness();
  const f = h.ready();
  f.rows.get(alpha).item.click();
  h.flush();
  assert.deepEqual(f.widget.value, [gamma, beta]);
  assertNumbers(f);
  f.rows.get(alpha).item.click();
  h.flush();
  assert.deepEqual(f.widget.value, [gamma, beta, alpha]);
  assertNumbers(f);
  f.chips.get(gamma).remove.click();
  h.flush();
  assertNumbers(f);
  f.select([alpha, beta, gamma]);
  h.flush();
  assertNumbers(f);
  f.select([]);
  h.flush();
  assertNumbers(f);
  for (const { box, checkbox, item } of f.rows.values()) {
    assert.equal(box.getAttribute(marker), null);
    assert.equal(checkbox.getAttribute(marker), null);
    assert.equal(item.getAttribute("aria-describedby"), null);
  }
});

test("double-digit dropdown numbers preserve the native summary above three selections", async () => {
  const h = await harness();
  const paths = Array.from(
    { length: 12 },
    (_, i) => `checkpoints/${i}.safetensors`,
  );
  const f = h.ready([...paths].reverse(), paths);
  const summary = f.labels.children[0];
  assert.equal(summary.textContent, "12 items selected");
  assert.equal(f.labels.querySelector(badgeSelector), null);
  assert.equal(number(f.rows.get(paths[0]).item), "12");
  assertNumbers(f);
  f.hook("updated");
  h.flush();
  assert.equal(f.labels.children[0], summary);
  f.select(paths.slice(0, 3));
  h.flush();
  assertNumbers(f);
  assert.equal(f.chips.size, 3);
  const css = h.document.head.children[0].textContent;
  assert.match(css, /font-variant-numeric: tabular-nums/);
  assert.match(css, /min-inline-size: 2ch/);
  assert.match(css, /pointer-events: none/);
  assert.match(css, /color: inherit/);
});

test("only the owned dropdown is observed and recreated or inline dropdowns refresh", async () => {
  const h = await harness();
  const f = h.ready();
  const unrelatedNode = h.makeNode([gamma], [], "OtherNode");
  const unrelated = h.mount(unrelatedNode.widgets[0]);
  unrelated.open();
  h.flush();
  assert.equal(number(unrelated.rows.get(gamma).item), null);
  assert.deepEqual(
    h.observers.flatMap((observer) =>
      observer.targets.map(([target]) => target),
    ),
    [f.root, f.list],
  );
  const old = f.list;
  f.close();
  h.flush();
  assert.equal(old.querySelector(badgeSelector), null);
  assert.ok(
    !h.observers.some((observer) =>
      observer.targets.some(([target]) => target === old),
    ),
  );
  f.open();
  h.flush();
  assertNumbers(f);
  f.close();
  f.open(true);
  h.flush();
  assertNumbers(f);
  assert.deepEqual(
    h.observers.flatMap((observer) =>
      observer.targets.map(([target]) => target),
    ),
    [f.root],
  );
});

test("restoration, cloning, undo and redo read the current widget props on update", async () => {
  const h = await harness();
  const original = h.ready([alpha]);
  const restored = h.makeNode([beta, gamma, alpha]);
  // Cloned/promoted widgets can share a previously wrapped component definition.
  restored.widgets[0].component = original.widget.component;
  h.extension.loadedGraphNode(restored);
  assert.equal(restored.widgets[0].component, original.widget.component);
  const f = h.mount(restored.widgets[0]);
  f.open();
  h.flush();
  assertNumbers(f);
  for (const selection of [
    [alpha, beta, gamma],
    [beta, gamma, alpha],
    [alpha, beta, gamma],
  ]) {
    h.setValue(f.widget, selection);
    // Same selected rows/chips; only array order changes, so no DOM mutation.
    f.hook("updated");
    h.flush();
    assertNumbers(f);
  }
  const replacement = h.makeNode([gamma, beta, alpha]).widgets[0];
  f.instance.$props.widget = replacement;
  f.hook("updated");
  h.flush();
  assert.equal(number(f.rows.get(gamma).item), "1");
  assertNumbers(original);
});

test("unselected rows, select-all, native labels, icons and removal handlers stay intact", async () => {
  const h = await harness();
  const f = h.ready([gamma]);
  const selected = f.rows.get(gamma);
  const unselected = f.rows.get(alpha);
  const { chip, label, remove } = f.chips.get(gamma);
  const listener = remove.listeners.get("click");
  assert.equal(selected.icon.parentElement, selected.box);
  assert.equal(selected.icon.getAttribute("style"), null);
  assert.equal(unselected.box.getAttribute(marker), null);
  assert.equal(unselected.box.children.length, 0);
  assert.equal(f.header.box.getAttribute(marker), null);
  assert.equal(f.header.box.children.length, 1);
  assert.equal(f.header.checkbox.getAttribute("aria-describedby"), null);
  assert.equal(label.textContent, gamma);
  assert.equal(chip.getAttribute("title"), gamma);
  assert.equal(chip.getAttribute("aria-label"), gamma);
  assert.equal(remove.getAttribute("aria-label"), "Remove");
  assert.equal(
    chip.children.indexOf(label),
    chip.children.indexOf(chip.querySelector(badgeSelector)) + 1,
  );
  f.hook("updated");
  h.flush();
  assert.equal(remove.listeners.get("click"), listener);
  assert.equal(selected.item.getAttribute("aria-posinset"), "1");
});

test("accessible descriptions preserve existing labels and changing description metadata", async () => {
  const h = await harness();
  const node = h.makeNode([gamma]);
  h.extension.nodeCreated(node);
  const f = h.mount(node.widgets[0]);
  f.open();
  const row = f.rows.get(gamma).item;
  const chip = f.chips.get(gamma).chip;
  row.setAttribute("aria-describedby", "  native-tip  other-tip ");
  row.setAttribute("aria-description", "Native description");
  chip.setAttribute("aria-describedby", "");
  h.flush();
  const reference = row
    .getAttribute("aria-describedby")
    .trim()
    .split(/\s+/)
    .at(-1);
  const description = h.document.getElementById(reference);
  assert.equal(description.textContent, "Selection order 1.");
  assert.equal(description.hidden, true);
  assert.equal(
    row.querySelector(badgeSelector).getAttribute("aria-hidden"),
    "true",
  );
  row.setAttribute("aria-describedby", `new-tip ${reference}`);
  h.flush();
  f.unmount();
  h.flush();
  assert.equal(row.getAttribute("aria-describedby"), "new-tip");
  assert.equal(row.getAttribute("aria-description"), "Native description");
  assert.equal(row.getAttribute("aria-label"), gamma);
  assert.equal(chip.getAttribute("aria-describedby"), "");
  assert.equal(h.document.getElementById(reference), null);
});

test("native metadata restoration is exact and removed badges or descriptions recover", async () => {
  const h = await harness();
  const node = h.makeNode([gamma]);
  h.extension.nodeCreated(node);
  const f = h.mount(node.widgets[0]);
  f.open();
  const row = f.rows.get(gamma).item;
  row.setAttribute("aria-describedby", "  original   second ");
  h.flush();
  row.querySelector(badgeSelector).remove();
  h.flush();
  assert.equal(number(row), "1");
  const id = row.getAttribute("aria-describedby").trim().split(/\s+/).at(-1);
  h.document.getElementById(id).remove();
  h.flush();
  assert.equal(number(row), "1");
  row.setAttribute("aria-describedby", "  original   second ");
  h.flush();
  assert.match(row.getAttribute("aria-describedby"), /lany-model-names-order/);
  f.unmount();
  assert.equal(row.getAttribute("aria-describedby"), "  original   second ");
});

test("updates coalesce, own mutations do not loop and unchanged refreshes do not write", async () => {
  const h = await harness();
  const f = h.ready();
  const beforeWrites = h.writes;
  const beforeRefreshes = h.refreshes;
  for (let i = 0; i < 10; i++) f.hook("updated");
  assert.equal(h.ticks.length, 1);
  h.flush();
  assert.equal(h.refreshes, beforeRefreshes + 1);
  assert.equal(h.writes, beforeWrites);
  assert.equal(h.observers.flatMap((observer) => observer.records).length, 0);
  f.filter([alpha]);
  f.hook("updated");
  h.flush();
  assert.equal(number(f.rows.get(alpha).item), "2");
  assert.equal(h.ticks.length, 0);
});

test("teardown cancels pending work, removes decorations and allows a fresh mount", async () => {
  const h = await harness();
  const f = h.ready();
  const oldRoot = f.root;
  const oldList = f.list;
  f.hook("updated");
  f.unmount();
  const writes = h.writes;
  h.flush();
  assert.equal(h.writes, writes);
  assert.equal(oldRoot.querySelector(badgeSelector), null);
  assert.equal(oldList.querySelector(badgeSelector), null);
  assert.equal(oldList.querySelector(`[${marker}]`), null);
  assert.ok(h.observers.every((observer) => !observer.targets.length));
  const remounted = h.mount(f.widget);
  remounted.open();
  h.flush();
  assertNumbers(remounted);
  const pending = h.mount(f.widget);
  pending.open();
  pending.unmount();
  h.flush();
  assert.equal(pending.list.querySelector(badgeSelector), null);
});

test("unknown components and non-target widgets are left intact", async () => {
  const h = await harness();
  const otherNode = h.makeNode([gamma], [], "OtherNode");
  h.extension.nodeCreated(otherNode);
  assert.equal(otherNode.widgets[0].component, h.component);
  const node = h.makeNode();
  const unknown = {
    name: "models",
    component: { __name: "OtherPicker" },
    value: [],
  };
  const legacy = { name: "models", type: "combo", value: [] };
  const unrelated = { name: "other", component: h.component, value: [] };
  const frozen = Object.freeze({
    name: "loras",
    component: h.component,
    value: [],
  });
  node.widgets = [unknown, legacy, unrelated, frozen];
  const components = node.widgets.map((widget) => widget.component);
  h.extension.nodeCreated(node);
  h.extension.loadedGraphNode(node);
  assert.deepEqual(
    node.widgets.map((widget) => widget.component),
    components,
  );
  assert.equal(h.observers.length, 0);
  assert.equal(h.document.head.children.length, 0);
});

test("unsupported markup or values retain native rendering and clear stale decoration", async () => {
  const h = await harness();
  const f = h.ready();
  const gammaRow = f.rows.get(gamma);
  gammaRow.label.textContent = "Gamma.safetensors";
  f.chips.get(gamma).label.textContent = "Gamma.safetensors";
  f.rows.get(alpha).checkbox.removeAttribute("data-pc-extend");
  h.flush();
  assert.equal(number(gammaRow.item), null);
  assert.equal(gammaRow.box.getAttribute(marker), null);
  assert.equal(gammaRow.icon.parentElement, gammaRow.box);
  assert.equal(number(f.chips.get(gamma).chip), null);
  assert.equal(number(f.rows.get(alpha).item), null);
  assert.equal(number(f.rows.get(beta).item), "3");
  const betaRow = f.rows.get(beta);
  betaRow.icon.setAttribute("data-pc-section", "unknown-icon");
  h.flush();
  assert.equal(number(betaRow.item), null);
  assert.equal(betaRow.box.getAttribute(marker), null);
  assert.equal(betaRow.icon.parentElement, betaRow.box);
  h.setValue(f.widget, "unsupported value");
  f.hook("updated");
  h.flush();
  assert.equal(f.root.querySelector(badgeSelector), null);
  assert.equal(f.list.querySelector(badgeSelector), null);
  h.setValue(f.widget, [gamma]);
  f.render();
  f.hook("updated");
  h.flush();
  f.picker.removeAttribute("data-pc-name");
  h.flush();
  assert.equal(f.root.querySelector(badgeSelector), null);
  assert.equal(f.list.querySelector(badgeSelector), null);
  f.instance.$el = { nodeType: 8 };
  f.hook("updated");
  h.flush();
  assert.ok(h.observers.every((observer) => !observer.targets.length));
});
