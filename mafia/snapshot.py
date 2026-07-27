"""Inject a semantic DOM walker into the live page (engine of record = Chromium)."""

from __future__ import annotations

WALKER_JS = r"""
() => {
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
  const nodes = [];
  let id = 0;
  const all = document.querySelectorAll("*");
  for (const el of all) {
    const tag = el.tagName.toLowerCase();
    if (!INTERESTING.has(tag)) continue;
    if (tag === "input" && (el.type || "").toLowerCase() === "hidden") continue;
    id += 1;
    const text = collapse(el.innerText || el.value || el.getAttribute("aria-label") || "");
    let href = null;
    if (tag === "a" && el.href) href = el.href;
    const clickable = tag === "a" || tag === "button" ||
      (tag === "input" && ["button","submit"].includes((el.type||"").toLowerCase()));
    // Stamp so click(node_id) can find the same element.
    el.setAttribute("data-mafia-id", String(id));
    nodes.push({
      node_id: id,
      tag,
      role: roleOf(tag),
      text,
      href,
      clickable,
    });
  }
  return {
    view: "full",
    url: location.href,
    title: document.title || null,
    node_count: nodes.length,
    nodes,
  };
}
"""

CLICK_JS = r"""
(id) => {
  const el = document.querySelector('[data-mafia-id="' + id + '"]');
  if (!el) return { ok: false, error: "no node with id " + id };
  el.click();
  return { ok: true, node_id: id, tag: el.tagName.toLowerCase() };
}
"""

FIND_TEXT_JS = r"""
(q) => {
  const ql = (q || "").toLowerCase();
  const INTERESTING = new Set([
    "a","button","input","textarea","select",
    "h1","h2","h3","h4","h5","h6","p","li","label"
  ]);
  const out = [];
  let id = 0;
  for (const el of document.querySelectorAll("*")) {
    const tag = el.tagName.toLowerCase();
    if (!INTERESTING.has(tag)) continue;
    id += 1;
    const text = (el.innerText || el.value || "").replace(/\s+/g, " ").trim();
    if (ql && text.toLowerCase().includes(ql)) {
      out.push({
        node_id: id,
        tag,
        text,
        href: tag === "a" ? el.href : null,
        clickable: tag === "a" || tag === "button",
      });
    }
  }
  return out;
}
"""
