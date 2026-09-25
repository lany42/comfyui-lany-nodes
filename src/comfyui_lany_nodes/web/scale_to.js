// SPDX-License-Identifier: AGPL-3.0-only
// SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

import { app } from "../../scripts/app.js";

app.registerExtension({
  name: "LanyNodes.ScaleToDimensions",

  nodeCreated(node) {
    if (node.comfyClass !== "LanyNodes_ScaleTo") return;

    const footer = document.createElement("div");
    footer.textContent = "—";
    footer.title = "No computed dimensions have arrived yet.";
    Object.assign(footer.style, {
      color: "var(--input-text)",
      fontSize: "12px",
      height: "24px",
      lineHeight: "24px",
      minWidth: "0",
      overflow: "hidden",
      textAlign: "center",
      textOverflow: "ellipsis",
      whiteSpace: "nowrap",
      width: "100%",
    });

    const widget = node.addDOMWidget(
      "lany_dimensions",
      "lany_dimensions",
      footer,
      {
        serialize: false,
        getMinHeight: () => 24,
        getMaxHeight: () => 24,
        getHeight: () => 24,
        margin: 0,
      },
    );
    widget.serialize = false;
    node.expandToFitContent();

    const onExecuted = node.onExecuted;
    node.onExecuted = function (message, ...args) {
      const result = onExecuted?.call(this, message, ...args);
      const dimensions = message?.dimensions;
      if (
        Array.isArray(dimensions) &&
        dimensions.length > 0 &&
        dimensions.every((value) => typeof value === "string")
      ) {
        footer.textContent = dimensions.join(", ");
        footer.title = footer.textContent;
      }
      return result;
    };
  },

  loadedGraphNode(node) {
    if (node.comfyClass === "LanyNodes_ScaleTo") {
      node.expandToFitContent();
    }
  },
});
