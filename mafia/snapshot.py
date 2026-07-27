"""Inject a semantic DOM walker into the live page (engine of record = Chromium).

One walk order, one id space. snapshot / find_text / click MUST share it.
"""

from __future__ import annotations

# Shared enumeration — single source of truth for data-mafia-id.
# Hidden inputs skipped BEFORE id increment (find_text used to diverge here).
_WALK_CORE_JS = r"""
  const INTERESTING = new Set([
    "a","button","input","textarea","select",
    "h1","h2","h3","h4","h5","h6","p","li","label"
  ]);
  function roleOf(tag) {
    if (tag === "a") return "link";
    if (tag === "button") return "button";
    if (tag === "input" || tag === "textarea" || tag === "select") return "field";
    if (/^h[1-6]$/.test(tag)) return "heading";
    if (tag === "p" || tag === "li") return "text";
    if (tag === "label") return "label";
    return "generic";
  }
  function collapse(s) {
    return (s || "").replace(/\s+/g, " ").trim();
  }
  function isHiddenInput(el, tag) {
    return tag === "input" && (el.type || "").toLowerCase() === "hidden";
  }
  function isClickable(el, tag) {
    if (tag === "a" || tag === "button") return true;
    if (tag === "input") {
      const t = (el.type || "").toLowerCase();
      return t === "button" || t === "submit" || t === "image";
    }
    return false;
  }
  /** Walk DOM once: stamp data-mafia-id, return node list. */
  function walkAndStamp() {
    const nodes = [];
    let id = 0;
    const all = document.querySelectorAll("*");
    for (const el of all) {
      const tag = el.tagName.toLowerCase();
      if (!INTERESTING.has(tag)) continue;
      if (isHiddenInput(el, tag)) continue;
      id += 1;
      const text = collapse(
        el.innerText || el.value || el.getAttribute("aria-label") || ""
      );
      let href = null;
      if (tag === "a" && el.href) href = el.href;
      el.setAttribute("data-mafia-id", String(id));
      nodes.push({
        node_id: id,
        tag,
        role: roleOf(tag),
        text,
        href,
        clickable: isClickable(el, tag),
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
  // Same stamp + id space as snapshot/click
  const nodes = walkAndStamp();
  if (!ql) return nodes;
  return nodes.filter((n) => (n.text || "").toLowerCase().includes(ql));
}
"""
)
