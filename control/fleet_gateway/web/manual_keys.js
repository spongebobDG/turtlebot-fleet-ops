(function attachManualKeys(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.FleetManualKeys = api;
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
  "use strict";

  const COMMANDS = Object.freeze({
    w: Object.freeze({ key: "w", linearX: 0.05, angularZ: 0.0, label: "W · 전진" }),
    a: Object.freeze({ key: "a", linearX: 0.0, angularZ: 0.3, label: "A · 좌회전" }),
    s: Object.freeze({ key: "s", linearX: -0.05, angularZ: 0.0, label: "S · 후진" }),
    d: Object.freeze({ key: "d", linearX: 0.0, angularZ: -0.3, label: "D · 우회전" }),
  });

  const commandForKey = (key) => COMMANDS[String(key || "").toLowerCase()] || null;

  const isEditableTarget = (target) => {
    if (!target) return false;
    if (target.isContentEditable) return true;
    return ["INPUT", "TEXTAREA", "SELECT"].includes(String(target.tagName || "").toUpperCase());
  };

  return { commandForKey, isEditableTarget };
}));
