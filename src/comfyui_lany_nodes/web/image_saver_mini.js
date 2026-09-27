// SPDX-License-Identifier: AGPL-3.0-only
// SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

import { app } from "../../scripts/app.js";
import { button, setPressed } from "./buttons.js";

const NODE_ID = "LanyNodes_ImageSaverMini";
const states = new WeakMap();

function install(node) {
  const format = node.widgets?.find((widget) => widget.name === "format");
  if (!format) return;
  // Keep the schema widget as the source of truth for both workflow and API
  // serialization. The two DOM buttons are only an editor for that value.
  format.hidden = true;
  format.options ??= {};
  format.options.hidden = true;

  const toolbar = document.createElement("div");
  Object.assign(toolbar.style, {
    display: "flex",
    alignItems: "center",
    gap: "4px",
    height: "28px",
    width: "100%",
    color: "var(--input-text, #ddd)",
    fontSize: "12px",
  });
  toolbar.setAttribute("role", "group");
  toolbar.setAttribute("aria-label", "Output format");
  const buttons = ["png", "jpg"].map((value) => {
    const item = button(value, `Save ${value.toUpperCase()} images`);
    toolbar.append(item);
    return [value, item];
  });
  const spacer = document.createElement("div");
  spacer.setAttribute("aria-hidden", "true");
  spacer.style.pointerEvents = "none";

  function addDOM(name, element, height) {
    const widget = node.addDOMWidget(name, name, element, {
      serialize: false,
      selectOn: [],
      margin: 0,
      getMinHeight: () => height,
      getMaxHeight: () => height,
      getHeight: () => height,
      hideInPanel: true,
    });
    widget.serialize = false;
    return widget;
  }
  const toolbarWidget = addDOM("lany_image_saver_format", toolbar, 28);
  const spacerWidget = addDOM("lany_image_saver_spacer", spacer, 12);
  // Nonserialized widgets can move without changing saved widget indexes.
  node.widgets.splice(node.widgets.indexOf(toolbarWidget), 1);
  node.widgets.splice(node.widgets.indexOf(spacerWidget), 1);
  node.widgets.unshift(toolbarWidget);
  const advancedIndex = node.widgets.findIndex(
    (widget) => widget.name === "time_format",
  );
  node.widgets.splice(
    advancedIndex < 0 ? node.widgets.length : advancedIndex,
    0,
    spacerWidget,
  );

  let disposed = false;
  function refresh() {
    if (disposed) return;
    for (const [value, item] of buttons)
      setPressed(item, value === format.value);
    for (const widget of node.widgets) {
      if (
        !["jpg_quality", "optimize_png", "png_embed_workflow"].includes(
          widget.name,
        )
      )
        continue;
      const disabled =
        widget.name === "jpg_quality"
          ? format.value !== "jpg"
          : format.value !== "png";
      widget.disabled = disabled;
      widget.options ??= {};
      widget.options.disabled = disabled;
    }
    node.graph?.setDirtyCanvas(true, true);
  }

  const listeners = buttons.map(([value, item]) => {
    const choose = (event) => {
      if (
        disposed ||
        event.ctrlKey ||
        event.altKey ||
        event.metaKey ||
        event.shiftKey ||
        (event.button !== undefined && event.button !== 0)
      )
        return;
      event.stopPropagation();
      if (format.value === value) return;
      node.graph?.beforeChange();
      format.value = value;
      format.callback?.call(format, value);
      node.graph?.afterChange();
    };
    item.addEventListener("click", choose);
    return () => item.removeEventListener("click", choose);
  });

  const callback = format.callback;
  format.callback = function (...args) {
    const result = callback?.apply(this, args);
    refresh();
    return result;
  };
  const onConfigure = node.onConfigure;
  node.onConfigure = function (...args) {
    const result = onConfigure?.apply(this, args);
    refresh();
    return result;
  };

  function dispose() {
    if (disposed) return;
    disposed = true;
    for (const remove of listeners) remove();
    toolbar.remove();
    spacer.remove();
    states.delete(node);
  }
  const onRemove = toolbarWidget.onRemove;
  toolbarWidget.onRemove = function (...args) {
    try {
      return onRemove?.apply(this, args);
    } finally {
      dispose();
    }
  };
  const onRemoved = node.onRemoved;
  node.onRemoved = function (...args) {
    try {
      return onRemoved?.apply(this, args);
    } finally {
      dispose();
    }
  };
  const state = { refresh };
  states.set(node, state);
  refresh();
  node.expandToFitContent();
}

app.registerExtension({
  name: "LanyNodes.ImageSaverMini",
  nodeCreated(node) {
    if (node.comfyClass === NODE_ID && !states.has(node)) install(node);
  },
  loadedGraphNode(node) {
    states.get(node)?.refresh();
  },
});
