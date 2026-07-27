"""Inject a semantic DOM walker into the live page (engine of record = Chromium).

One walk order, one id space. snapshot / find_text / click MUST share it.
Includes ARIA roles (div[role=button] etc.) so Gmail-class UIs are visible.
"""

from __future__ import annotations

# Shared enumeration — single source of truth for data-mafia-id.
_WALK_CORE_JS = r"""
  const TAG_INTERESTING = new Set([
    "a","button","input","textarea","select",
    "h1","h2","h3","h4","h5","h6","p","li","label","summary"
  ]);
  const ROLE_INTERESTING = new Set([
    "button","link","textbox","searchbox","checkbox","radio",
    "menuitem","tab","option","switch","combobox","listbox",
    "heading","img"
  ]);
  function roleOf(el, tag) {
    const ar = (el.getAttribute("role") || "").toLowerCase();
    if (ar) return ar;
    if (tag === "a") return "link";
    if (tag === "button") return "button";
    if (tag === "input" || tag === "textarea" || tag === "select") return "field";
    if (/^h[1-6]$/.test(tag)) return "heading";
    if (tag === "p" || tag === "li") return "text";
    if (tag === "label") return "label";
    if (tag === "summary") return "button";
    return "generic";
  }
  function collapse(s) {
    return (s || "").replace(/\s+/g, " ").trim();
  }
  function isHiddenInput(el, tag) {
    return tag === "input" && (el.type || "").toLowerCase() === "hidden";
  }
  function isInteresting(el, tag) {
    if (TAG_INTERESTING.has(tag)) return true;
    const ar = (el.getAttribute("role") || "").toLowerCase();
    if (ar && ROLE_INTERESTING.has(ar)) return true;
    if (el.isContentEditable) return true;
    return false;
  }
  function isClickable(el, tag, role) {
    if (tag === "a" || tag === "button" || tag === "summary") return true;
    if (role === "button" || role === "link" || role === "menuitem" || role === "tab") return true;
    if (tag === "input") {
      const t = (el.type || "").toLowerCase();
      return t === "button" || t === "submit" || t === "image" || t === "checkbox" || t === "radio";
    }
    return false;
  }
  function nodeText(el, tag) {
    return collapse(
      el.innerText ||
      el.value ||
      el.getAttribute("aria-label") ||
      el.getAttribute("title") ||
      el.getAttribute("placeholder") ||
      el.getAttribute("alt") ||
      ""
    );
  }
  /** Walk DOM once: stamp data-mafia-id, return node list. */
  function walkAndStamp() {
    const nodes = [];
    let id = 0;
    const all = document.querySelectorAll("*");
    for (const el of all) {
      const tag = el.tagName.toLowerCase();
      if (!isInteresting(el, tag)) continue;
      if (isHiddenInput(el, tag)) continue;
      // skip aria-hidden decorative
      if ((el.getAttribute("aria-hidden") || "").toLowerCase() === "true") continue;
      id += 1;
      const role = roleOf(el, tag);
      const text = nodeText(el, tag);
      let href = null;
      if (tag === "a" && el.href) href = el.href;
      else if (role === "link" && el.getAttribute("href")) href = el.href || el.getAttribute("href");
      el.setAttribute("data-mafia-id", String(id));
      nodes.push({
        node_id: id,
        tag,
        role,
        text,
        href,
        clickable: isClickable(el, tag, role),
      });
    }
    return nodes;
  }
"""

WALKER_JS = (
    "() => {\n"
    + _WALK_CORE_JS
    + r"""
  const nodes = walkAndStamp();
  return {
    view: "full",
    url: location.href,
    title: document.title || null,
    node_count: nodes.length,
    nodes,
  };
}
"""
)

CLICK_JS = r"""
(id) => {
  const el = document.querySelector('[data-mafia-id="' + id + '"]');
  if (!el) return { ok: false, error: "no node with id " + id };
  const text = (el.innerText || el.value || el.getAttribute("aria-label") || "")
    .replace(/\s+/g, " ").trim().slice(0, 200);
  const href = el.tagName.toLowerCase() === "a" ? (el.href || null) : null;
  el.click();
  return {
    ok: true,
    node_id: id,
    tag: el.tagName.toLowerCase(),
    text,
    href,
  };
}
"""

FIND_TEXT_JS = (
    "(q) => {\n"
    + _WALK_CORE_JS
    + r"""
  const ql = (q || "").toLowerCase();
  const nodes = walkAndStamp();
  if (!ql) return nodes;
  return nodes.filter((n) => (n.text || "").toLowerCase().includes(ql));
}
"""
)
