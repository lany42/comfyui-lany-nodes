// SPDX-License-Identifier: AGPL-3.0-only
// SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

import { app } from "../../scripts/app.js";

const NODE_ID = "LanyNodes_ModelNames";
const MARKER = "data-lany-model-names";
const STYLE_ID = "lany-model-names-style";
const controllers = new WeakMap();
let descriptionId = 0;

// PrimeVue 4.2.5 MultiSelect/Chip/Checkbox adapter. Nested components receive
// pc-prefixed names from MultiSelect's pass-through props (BaseComponent).
// Require exact path labels; never infer order from rendered row positions.
const selectors = {
  picker: '[data-pc-name="multiselect"]',
  combobox: '[role="combobox"]',
  option: '[role="option"][aria-selected="true"]',
  optionLabel: '[data-pc-section="optionlabel"]',
  checkbox: '[data-pc-name="pcoptioncheckbox"][data-pc-extend="checkbox"]',
  box: '[data-pc-section="box"]',
  icon: '[data-pc-section="pcoptioncheckbox.icon"]',
  chip: '[data-pc-name="pcchip"][data-pc-extend="chip"]',
  chipLabel: '[data-pc-section="label"]',
};

function pickerElements(root) {
  const picker = root.matches(selectors.picker)
    ? root
    : root.querySelector(selectors.picker);
  const combobox = picker?.querySelector(selectors.combobox);
  const listId = combobox?.getAttribute("aria-controls");
  const list =
    combobox?.getAttribute("aria-expanded") === "true" && listId
      ? root.ownerDocument.getElementById(listId)
      : null;
  return {
    picker,
    list: list?.getAttribute("role") === "listbox" ? list : null,
  };
}

function decorations(picker, list, order) {
  const items = [];
  for (const row of list?.querySelectorAll(selectors.option) ?? []) {
    const path = row.getAttribute("aria-label");
    const label = row.querySelector(selectors.optionLabel);
    const checkbox = row.querySelector(selectors.checkbox);
    const box = checkbox?.querySelector(selectors.box);
    const icon = box?.querySelector(selectors.icon);
    if (
      !order.has(path) ||
      label?.textContent !== path ||
      !box ||
      icon?.parentElement !== box
    )
      continue;
    items.push({
      item: row,
      mount: box,
      number: order.get(path),
      markers: [
        [checkbox, "checkbox"],
        [box, "box"],
      ],
    });
  }
  for (const chip of picker?.querySelectorAll(selectors.chip) ?? []) {
    const label = chip.querySelector(selectors.chipLabel);
    const number = order.get(label?.textContent);
    if (!number || label.parentElement !== chip) continue;
    items.push({ item: chip, mount: chip, before: label, number, markers: [] });
  }
  return items;
}

function installStyle(document) {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    .lany-model-names-number {
      display: inline-grid;
      place-items: center;
      flex: 0 0 auto;
      min-inline-size: 2ch;
      font-size: 0.85em;
      font-variant-numeric: tabular-nums;
      line-height: 1;
      color: inherit;
      pointer-events: none;
    }
    .lany-model-names-chip-number {
      border: 1px solid currentColor;
      border-radius: 0.25em;
      padding: 0.15em 0.25em;
    }
    [${MARKER}="checkbox"], [${MARKER}="box"] {
      width: auto;
      min-width: 1.25rem;
      flex-shrink: 0;
    }
    [${MARKER}="box"] { padding-inline: 0.15em; }
    [${MARKER}="box"] > ${selectors.icon} { display: none; }
  `;
  document.head.append(style);
}

function setAttribute(element, name, value) {
  if (element.getAttribute(name) !== value) element.setAttribute(name, value);
}

function setText(element, text) {
  if (element.textContent !== text) element.textContent = text;
}

function descriptionTokens(value) {
  return value?.match(/\S+/g) ?? [];
}

function removeDecoration(record) {
  record.badge.remove();
  record.description.remove();
  for (const [element, value] of record.markers) {
    if (element.getAttribute(MARKER) === value) element.removeAttribute(MARKER);
  }
  const current = record.item.getAttribute("aria-describedby");
  const tokens = descriptionTokens(current);
  if (!tokens.includes(record.description.id)) return;
  const remaining = tokens
    .filter((id) => id !== record.description.id)
    .join(" ");
  // Restore the original formatting/absence when no other author changed it.
  const value =
    remaining === descriptionTokens(record.originalDescription).join(" ")
      ? record.originalDescription
      : remaining || null;
  if (value === null) record.item.removeAttribute("aria-describedby");
  else setAttribute(record.item, "aria-describedby", value);
}

function createDecoration(spec) {
  const document = spec.item.ownerDocument;
  const badge = document.createElement("span");
  badge.className = `lany-model-names-number${spec.before ? " lany-model-names-chip-number" : ""}`;
  badge.setAttribute("aria-hidden", "true");
  const description = document.createElement("span");
  do {
    description.id = `lany-model-names-order-${++descriptionId}`;
  } while (document.getElementById(description.id));
  description.hidden = true;
  spec.mount.insertBefore(badge, spec.before ?? null);
  spec.item.append(description);
  return {
    ...spec,
    badge,
    description,
    originalDescription: spec.item.getAttribute("aria-describedby"),
  };
}

function createController(instance) {
  let disposed = false;
  let pending = false;
  const records = new Map();
  const rootObserver = new MutationObserver(schedule);
  const listObserver = new MutationObserver(schedule);
  const observerOptions = {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: [
      "aria-controls",
      "aria-expanded",
      "aria-selected",
      "aria-label",
      "aria-describedby",
      "data-pc-name",
      "data-pc-section",
      "data-pc-extend",
    ],
  };

  function refresh() {
    // Ignore our own synchronous mutations, including description references.
    // Each pass reads the complete current DOM/value before observing again.
    rootObserver.disconnect();
    listObserver.disconnect();
    const root = instance.$el;
    const { picker, list } = root?.nodeType === 1 ? pickerElements(root) : {};
    const value = instance.$props.widget?.value;
    const order = new Map();
    if (Array.isArray(value)) {
      value.forEach((path, index) => {
        if (typeof path === "string" && !order.has(path))
          order.set(path, index + 1);
      });
    }
    const wanted = decorations(picker, list, order);
    const current = new Map(wanted.map((spec) => [spec.item, spec]));
    for (const [item, record] of records) {
      const spec = current.get(item);
      if (
        !spec ||
        spec.mount !== record.mount ||
        spec.before !== record.before ||
        record.badge.parentElement !== spec.mount ||
        record.description.parentElement !== item
      ) {
        removeDecoration(record);
        records.delete(item);
      }
    }
    if (wanted.length) installStyle(root.ownerDocument);
    for (const spec of wanted) {
      let record = records.get(spec.item);
      if (!record) {
        record = createDecoration(spec);
        records.set(spec.item, record);
      }
      setText(record.badge, String(spec.number));
      setText(record.description, `Selection order ${spec.number}.`);
      const descriptions = spec.item.getAttribute("aria-describedby");
      if (!descriptionTokens(descriptions).includes(record.description.id)) {
        setAttribute(
          spec.item,
          "aria-describedby",
          [descriptions, record.description.id].filter(Boolean).join(" "),
        );
      }
      // Only hide the checkmark after its replacement is installed.
      for (const [element, marker] of spec.markers)
        setAttribute(element, MARKER, marker);
    }
    if (root?.nodeType === 1) rootObserver.observe(root, observerOptions);
    if (list && !root.contains(list))
      listObserver.observe(list, observerOptions);
  }

  function schedule() {
    if (disposed || pending) return;
    pending = true;
    instance.$nextTick(() => {
      pending = false;
      if (!disposed) refresh();
    });
  }

  function dispose() {
    disposed = true;
    rootObserver.disconnect();
    listObserver.disconnect();
    for (const record of records.values()) removeDecoration(record);
    records.clear();
  }

  return { schedule, dispose };
}

const numberingMixin = {
  mounted() {
    const controller = createController(this);
    controllers.set(this, controller);
    controller.schedule();
  },
  updated() {
    controllers.get(this)?.schedule();
  },
  beforeUnmount() {
    controllers.get(this)?.dispose();
    controllers.delete(this);
  },
};

function install(node) {
  if (node.comfyClass !== NODE_ID) return;
  for (const widget of node.widgets ?? []) {
    if (!["models", "loras"].includes(widget.name)) continue;
    const component = widget.component;
    if (
      !component ||
      typeof component !== "object" ||
      (component.__name ?? component.name) !== "MultiSelectWidget" ||
      component.mixins?.includes(numberingMixin)
    )
      continue;
    const descriptor = Object.getOwnPropertyDescriptor(widget, "component");
    if (descriptor && !descriptor.writable && !descriptor.set) continue;
    if (!descriptor && !Object.isExtensible(widget)) continue;
    // Vue merges mixin lifecycle hooks with the original component's hooks.
    // Never capture this widget: cloned widgets can reuse the component copy.
    widget.component = {
      ...component,
      mixins: [...(component.mixins ?? []), numberingMixin],
    };
  }
}

app.registerExtension({
  name: "LanyNodes.ModelNames",
  nodeCreated: install,
  loadedGraphNode: install,
});
