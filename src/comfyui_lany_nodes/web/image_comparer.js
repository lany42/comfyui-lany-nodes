// SPDX-License-Identifier: AGPL-3.0-only
// SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_ID = "LanyNodes_ImageComparer";
const states = new WeakMap();
const background = "#202020";

function element(tag, style = {}, text = "") {
  const result = document.createElement(tag);
  Object.assign(result.style, style);
  result.textContent = text;
  return result;
}

function imagePath(descriptor) {
  // Omitting preview/channel parameters serves the complete saved PNG.
  return `/view?${new URLSearchParams({
    filename: descriptor.filename,
    subfolder: descriptor.subfolder ?? "",
    type: descriptor.type ?? "temp",
  })}`;
}

function validImages(images) {
  return (
    Array.isArray(images) &&
    images.length > 0 &&
    images.every(
      (item) =>
        item && typeof item.filename === "string" && item.filename.length > 0,
    )
  );
}

function createComparer(node) {
  const root = element("div", {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
    height: "100%",
    width: "100%",
    minWidth: "0",
    overflow: "hidden",
    userSelect: "none",
    color: "var(--input-text, #ddd)",
    fontSize: "12px",
    touchAction: "none",
  });
  const toolbar = element("div", {
    display: "flex",
    alignItems: "center",
    gap: "4px",
    flex: "0 0 28px",
  });
  const button = (label, title) => {
    const item = element(
      "button",
      {
        font: "inherit",
        padding: "2px 6px",
        cursor: "pointer",
        color: "inherit",
        background: "var(--comfy-input-bg, #333)",
        border: "1px solid var(--border-color, #666)",
        borderRadius: "3px",
      },
      label,
    );
    item.type = "button";
    item.title = title;
    item.setAttribute("aria-label", title);
    return item;
  };
  const sliderButton = button("Slider", "Compare with the pointer");
  const clickButton = button("Click", "Click to switch images");
  const navigation = element("div", {
    display: "none",
    alignItems: "center",
    gap: "4px",
    marginLeft: "auto",
  });
  const previous = button("‹", "Previous pair");
  const next = button("›", "Next pair");
  const counter = element("span", { whiteSpace: "nowrap" });
  navigation.append(previous, counter, next);
  toolbar.append(sliderButton, clickButton, navigation);

  const viewport = element("div", {
    position: "relative",
    flex: "1 1 auto",
    minHeight: "128px",
    overflow: "hidden",
    background,
  });
  viewport.setAttribute("aria-label", "Image comparison");
  const layers = ["A", "B"].map((side) => {
    // Each layer includes its own opaque letterbox/transparency background.
    const layer = element("div", {
      position: "absolute",
      inset: "0",
      background,
      visibility: "hidden",
      pointerEvents: "none",
    });
    const img = element("img", {
      width: "100%",
      height: "100%",
      objectFit: "contain",
      objectPosition: "center",
      display: "block",
    });
    img.alt = `Image ${side}`;
    img.draggable = false;
    layer.append(img);
    viewport.append(layer);
    return { layer, img };
  });
  const divider = element("div", {
    position: "absolute",
    top: "0",
    bottom: "0",
    width: "1px",
    background: "#fff",
    display: "none",
    pointerEvents: "none",
  });
  const status = element(
    "div",
    {
      position: "absolute",
      inset: "0",
      display: "grid",
      placeItems: "center",
      padding: "8px",
      textAlign: "center",
      pointerEvents: "none",
    },
    "Run the node to compare images.",
  );
  status.setAttribute("role", "status");
  const downloadStatus = element("div", {
    flex: "0 0 16px",
    overflow: "hidden",
    whiteSpace: "nowrap",
    textOverflow: "ellipsis",
  });
  downloadStatus.setAttribute("role", "status");
  viewport.append(divider, status);
  root.append(toolbar, viewport, downloadStatus);

  let disposed = false;
  let mode;
  let pairs = [];
  let index = 0;
  let displayed = null;
  let visibleSide = 0;
  let generation = 0;
  let sliderGeneration = 0;
  let frame = null;
  let pointerX = null;
  let press = null;
  let clickReady = false;
  let pan = null;
  const listeners = [];
  const downloads = new Set();
  const objectURLs = new Map();
  const listen = (target, type, handler, options) => {
    target.addEventListener(type, handler, options);
    listeners.push(() => target.removeEventListener(type, handler, options));
  };

  function cancelSlider() {
    sliderGeneration++;
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    pointerX = null;
  }

  function reset() {
    cancelSlider();
    press = null;
    clickReady = false;
    visibleSide = 0;
    layers[1].layer.style.clipPath = "inset(0 100% 0 0)";
    divider.style.display = "none";
  }

  function setMode(value) {
    if (disposed) return;
    mode = value === "click" ? "click" : "slider";
    node.properties ??= {};
    node.properties.comparer_mode = mode;
    reset();
    for (const [item, active] of [
      [sliderButton, mode === "slider"],
      [clickButton, mode === "click"],
    ]) {
      item.setAttribute("aria-pressed", String(active));
      item.style.borderColor = active
        ? "var(--input-text, #ddd)"
        : "var(--border-color, #666)";
    }
    viewport.title =
      mode === "slider"
        ? "Move to reveal B. Right-click: left half downloads A, right half downloads B."
        : "Click to switch A / B. Right-click to download the visible image.";
  }

  function chooseMode(value) {
    if (value === mode) return;
    node.graph?.beforeChange();
    setMode(value);
    node.graph?.afterChange();
  }

  function scheduleSlider() {
    if (
      disposed ||
      !displayed ||
      mode !== "slider" ||
      pointerX === null ||
      frame !== null
    )
      return;
    const token = sliderGeneration;
    frame = requestAnimationFrame(() => {
      if (disposed || token !== sliderGeneration) return;
      frame = null;
      if (!displayed || mode !== "slider" || pointerX === null) return;
      // Complete geometry reads before any style writes. Both measurements
      // include the same viewport, so their ratio compensates graph zoom.
      const rect = viewport.getBoundingClientRect();
      const localWidth = viewport.clientWidth;
      if (rect.width <= 0 || localWidth <= 0) return;
      const fraction = Math.max(
        0,
        Math.min(1, (pointerX - rect.left) / rect.width),
      );
      layers[1].layer.style.clipPath = `inset(0 ${100 * (1 - fraction)}% 0 0)`;
      divider.style.left = `${100 * fraction}%`;
      divider.style.width = `${localWidth / rect.width}px`;
      divider.style.display = "block";
    });
  }

  function clearImages() {
    displayed = null;
    for (const { layer, img } of layers) {
      layer.style.visibility = "hidden";
      img.removeAttribute("src");
    }
  }

  async function selectPair(selected) {
    if (disposed || selected < 0 || selected >= pairs.length) return;
    const token = ++generation;
    index = selected;
    reset();
    clearImages();
    previous.disabled = index === 0;
    next.disabled = index === pairs.length - 1;
    counter.textContent = `${index + 1} / ${pairs.length}`;
    status.textContent = "Loading images…";
    status.style.display = "grid";
    downloadStatus.textContent = "";
    const pair = pairs[index];
    try {
      const decoding = layers.map(({ img }, side) => {
        img.src = api.apiURL(imagePath(pair[side]));
        return img.decode();
      });
      await Promise.all(decoding);
      if (disposed || token !== generation) return;
      reset();
      displayed = pair;
      for (const { layer } of layers) layer.style.visibility = "visible";
      status.style.display = "none";
    } catch {
      if (disposed || token !== generation) return;
      clearImages();
      status.textContent = "Unable to load this image pair.";
    }
  }

  function receive(message) {
    if (disposed) return;
    generation++;
    reset();
    clearImages();
    pairs = [];
    index = 0;
    downloadStatus.textContent = "";
    const a = message?.a_images;
    const b = message?.b_images;
    if (!validImages(a) || !validImages(b) || a.length !== b.length) {
      navigation.style.display = "none";
      status.textContent = "No matching image pairs received.";
      status.style.display = "grid";
      return;
    }
    pairs = a.map((descriptor, i) => [{ ...descriptor }, { ...b[i] }]);
    navigation.style.display = pairs.length > 1 ? "flex" : "none";
    void selectPair(0);
  }

  async function download(descriptor) {
    const controller = new AbortController();
    downloads.add(controller);
    const path = imagePath(descriptor);
    const filename = descriptor.filename;
    downloadStatus.textContent = "";
    try {
      const response = await api.fetchApi(path, {
        signal: controller.signal,
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      if (disposed) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      const timer = setTimeout(() => {
        URL.revokeObjectURL(url);
        objectURLs.delete(url);
      }, 1000);
      objectURLs.set(url, timer);
      anchor.href = url;
      anchor.download = filename;
      try {
        document.body.append(anchor);
        anchor.click();
      } finally {
        anchor.remove();
      }
    } catch {
      if (!disposed)
        downloadStatus.textContent = `Download failed: ${filename}`;
    } finally {
      downloads.delete(controller);
    }
  }

  const modified = (event) =>
    event.ctrlKey || event.metaKey || event.altKey || event.shiftKey;
  const navigating = (event) =>
    event.button === 1 ||
    event.buttons & 4 ||
    (event.button !== 2 &&
      (modified(event) ||
        app.canvas?.read_only ||
        app.canvas?.dragging_canvas));
  // Mouse clicks may have isPrimary=false; check it only on pointer down/up.
  const ordinary = (event) => event.button === 0 && !navigating(event);
  const forward = (event, canvas = app.canvas?.canvas) => {
    event.preventDefault();
    event.stopPropagation();
    const EventClass = event.type === "wheel" ? WheelEvent : PointerEvent;
    canvas?.dispatchEvent(new EventClass(event.type, event));
  };
  const finishPan = () => {
    const pointerId = pan?.pointerId;
    pan = null;
    if (pointerId !== undefined && root.hasPointerCapture(pointerId))
      root.releasePointerCapture(pointerId);
  };

  // Only navigation enters the canvas. Capturing a forwarded drag keeps its
  // move/up sequence intact when the pointer leaves this widget.
  listen(root, "pointerdown", (event) => {
    event.stopPropagation();
    press = null;
    clickReady = false;
    if (navigating(event)) {
      if (mode === "slider") reset();
      pan = { pointerId: event.pointerId, canvas: app.canvas?.canvas, event };
      forward(event, pan.canvas);
      // The host also captures on pointerdown. Capture last so that this
      // adapter receives the remaining events and can finish its state.
      root.setPointerCapture(event.pointerId);
    } else if (
      event.isPrimary !== false &&
      ordinary(event) &&
      viewport.contains(event.target)
    ) {
      press = { x: event.clientX, y: event.clientY, id: event.pointerId };
    }
  });
  listen(root, "pointermove", (event) => {
    event.stopPropagation();
    if (pan?.pointerId === event.pointerId) {
      pan.event = event;
      forward(event, pan.canvas);
      return;
    }
    if (
      press &&
      (modified(event) ||
        Math.hypot(event.clientX - press.x, event.clientY - press.y) > 5)
    )
      press = null;
    if (navigating(event)) {
      press = null;
      if (mode === "slider") reset();
      return;
    }
    if (viewport.contains(event.target) && mode === "slider") {
      pointerX = event.clientX;
      scheduleSlider();
    }
  });
  listen(root, "pointerup", (event) => {
    event.stopPropagation();
    if (pan?.pointerId === event.pointerId) {
      forward(event, pan.canvas);
      finishPan();
    } else {
      clickReady = Boolean(
        press &&
        press.id === event.pointerId &&
        event.isPrimary !== false &&
        ordinary(event) &&
        viewport.contains(event.target) &&
        Math.hypot(event.clientX - press.x, event.clientY - press.y) <= 5,
      );
    }
    press = null;
  });
  const cancelPointer = (event) => {
    event.stopPropagation();
    if (pan?.pointerId === event.pointerId) {
      forward(new PointerEvent("pointercancel", event), pan.canvas);
      finishPan();
    }
    press = null;
    clickReady = false;
    if (mode === "slider") reset();
  };
  listen(root, "pointercancel", cancelPointer);
  listen(root, "lostpointercapture", cancelPointer);
  listen(viewport, "pointerleave", () => {
    press = null;
    clickReady = false;
    if (mode === "slider") reset();
  });
  listen(
    root,
    "wheel",
    (event) => {
      press = null;
      clickReady = false;
      if (mode === "slider") reset();
      forward(event);
    },
    { passive: false },
  );
  listen(viewport, "click", (event) => {
    if (clickReady && ordinary(event) && mode === "click" && displayed) {
      visibleSide = 1 - visibleSide;
      layers[1].layer.style.clipPath = visibleSide
        ? "inset(0)"
        : "inset(0 100% 0 0)";
    }
    clickReady = false;
  });
  listen(viewport, "contextmenu", (event) => {
    event.preventDefault();
    event.stopPropagation();
    clickReady = false;
    if (!displayed || disposed) return;
    const pair = displayed;
    let side = visibleSide;
    if (mode === "slider") {
      const rect = viewport.getBoundingClientRect();
      if (rect.width <= 0) return;
      side = event.clientX <= rect.left + rect.width / 2 ? 0 : 1;
    }
    void download({ ...pair[side] });
  });
  // Compatibility mouse events must also remain local, including auxclick
  // (which would otherwise paste the primary selection on some platforms).
  for (const type of [
    "mousedown",
    "mouseup",
    "mousemove",
    "click",
    "dblclick",
    "contextmenu",
    "auxclick",
    "dragstart",
  ]) {
    listen(root, type, (event) => {
      event.stopPropagation();
      if (["contextmenu", "auxclick", "dragstart"].includes(type))
        event.preventDefault();
    });
  }
  listen(sliderButton, "click", (event) => {
    if (ordinary(event)) chooseMode("slider");
  });
  listen(clickButton, "click", (event) => {
    if (ordinary(event)) chooseMode("click");
  });
  listen(previous, "click", (event) => {
    if (ordinary(event)) void selectPair(index - 1);
  });
  listen(next, "click", (event) => {
    if (ordinary(event)) void selectPair(index + 1);
  });

  const widget = node.addDOMWidget(
    "lany_image_comparer",
    "lany_image_comparer",
    root,
    {
      serialize: false,
      selectOn: [],
      getMinHeight: () => 180,
      getHeight: () => "100%",
      // Host draws already caused by resize/zoom refresh the divider geometry.
      onDraw: scheduleSlider,
      onHide: () => {
        if (mode === "slider") reset();
      },
    },
  );
  widget.serialize = false;
  node.setSize([Math.max(400, node.size[0]), Math.max(350, node.size[1])]);
  setMode(node.properties?.comparer_mode);

  function dispose() {
    if (disposed) return;
    disposed = true;
    generation++;
    reset();
    if (pan) {
      forward(new PointerEvent("pointercancel", pan.event), pan.canvas);
      finishPan();
    }
    for (const remove of listeners) remove();
    listeners.length = 0;
    for (const controller of downloads) controller.abort();
    downloads.clear();
    for (const [url, timer] of objectURLs) {
      clearTimeout(timer);
      URL.revokeObjectURL(url);
    }
    objectURLs.clear();
    pairs = [];
    clearImages();
    root.remove();
    states.delete(node);
  }

  const onRemove = widget.onRemove;
  widget.onRemove = function (...args) {
    try {
      return onRemove?.apply(this, args);
    } finally {
      dispose();
    }
  };
  return { receive, setMode, dispose };
}

app.registerExtension({
  name: "LanyNodes.ImageComparer",

  onNodeOutputsUpdated(nodeOutputs) {
    const rootGraph = app.rootGraph ?? app.graph;
    for (const [locatorId, output] of Object.entries(nodeOutputs)) {
      // Subgraph locators are "graphUUID:nodeID"; root locators are just node IDs.
      const [id, localId] = locatorId.split(":");
      const graph =
        localId === undefined ? rootGraph : rootGraph?.subgraphs?.get(id);
      const node = graph?.getNodeById(localId ?? id);
      states.get(node)?.receive(output);
    }
  },

  nodeCreated(node) {
    if (node.comfyClass !== NODE_ID || states.has(node)) return;
    const state = createComparer(node);
    states.set(node, state);
    const onExecuted = node.onExecuted;
    node.onExecuted = function (message, ...args) {
      const result = onExecuted?.call(this, message, ...args);
      state.receive(message);
      return result;
    };
    const onConfigure = node.onConfigure;
    node.onConfigure = function (...args) {
      const result = onConfigure?.apply(this, args);
      state.setMode(this.properties?.comparer_mode);
      return result;
    };
    const onPropertyChanged = node.onPropertyChanged;
    node.onPropertyChanged = function (name, value, ...args) {
      const result = onPropertyChanged?.call(this, name, value, ...args);
      if (result !== false && name === "comparer_mode") state.setMode(value);
      return result;
    };
    const onRemoved = node.onRemoved;
    node.onRemoved = function (...args) {
      try {
        return onRemoved?.apply(this, args);
      } finally {
        state.dispose();
      }
    };
  },
});
