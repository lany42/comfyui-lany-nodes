// SPDX-License-Identifier: AGPL-3.0-only
// SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

export function button(label, title) {
  const item = document.createElement("button");
  Object.assign(item.style, {
    font: "inherit",
    padding: "2px 6px",
    cursor: "pointer",
    color: "inherit",
    background: "var(--comfy-input-bg, #333)",
    border: "1px solid var(--border-color, #666)",
    borderRadius: "3px",
  });
  item.textContent = label;
  item.type = "button";
  item.title = title;
  item.setAttribute("aria-label", title);
  return item;
}

export function setPressed(item, active) {
  item.setAttribute("aria-pressed", String(active));
  item.style.borderColor = active
    ? "var(--input-text, #ddd)"
    : "var(--border-color, #666)";
}
