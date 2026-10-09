// Shared pieces of the Star atlas screens: platform marks, image plates, the state stamp,
// counters that run up to their collected value, and formatters. Collected text always goes in
// through textContent, never innerHTML.

export const PLATFORM_CODE = { website: "WEB", facebook: "FB", instagram: "IG", tiktok: "TT", youtube: "YT", x: "X" };
export const PLATFORM_NAME = {
  website: "Website", facebook: "Facebook", instagram: "Instagram", tiktok: "TikTok", youtube: "YouTube", x: "X",
};
export const PRESET_NAMES = { G1: "G1 Debate prep", G2: "G2 Respond to this post", G3: "G3 Background check" };
export const STATUS_TEXT = {
  queued: "queued", running: "running", done: "done", failed: "failed", skipped: "skipped",
  not_implemented: "not built yet",
};
export const STATE_WORD = { live: "Live", cached: "Cached", sample: "Sample", idle: "No run" };

const reduced = matchMedia("(prefers-reduced-motion: reduce)");
export const reducedMotion = () => reduced.matches;

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null && text !== "") node.textContent = text;
  return node;
}

const SVG_NS = "http://www.w3.org/2000/svg";
export function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

const PRAGUE = "Europe/Prague";
export function formatClock(ms, seconds = false) {
  return new Date(ms).toLocaleTimeString("en-GB", {
    hour: "2-digit", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}), timeZone: PRAGUE,
  });
}
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function pragueParts(ms) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: PRAGUE,
  }).formatToParts(new Date(ms));
  return Object.fromEntries(parts.map((p) => [p.type, p.value]));
}
export function formatDay(iso) {
  if (!iso) return "";
  const p = pragueParts(Date.parse(iso));
  return `${Number(p.day)} ${MONTHS[Number(p.month) - 1]}`;
}
export function formatDayTime(ms) {
  const p = pragueParts(ms);
  return `${Number(p.day)} ${MONTHS[Number(p.month) - 1]} ${p.hour}:${p.minute}`;
}
export function formatElapsed(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
export const formatUsd = (value) => `$${value.toFixed(2)}`;
export const formatInt = (value) => Math.round(value).toLocaleString("cs-CZ");

// A platform's letter code in the one engraved box style.
export function platformMark(platform, extraClass = "") {
  const mark = el("span", `mark ${extraClass}`.trim(), PLATFORM_CODE[platform] || platform);
  mark.dataset.platform = platform;
  return mark;
}

// A counter that runs up to its new collected value. Reduced motion sets it at once.
export function tick(node, value, { format = formatInt, animate = true } = {}) {
  const from = Number(node.dataset.value ?? 0);
  node.dataset.value = String(value);
  cancelAnimationFrame(node._tick);
  if (!animate || reducedMotion() || from === value) {
    node.textContent = format(value);
    return;
  }
  const start = performance.now();
  const duration = 650;
  const step = (now) => {
    const k = Math.min(1, (now - start) / duration);
    const eased = 1 - (1 - k) ** 3;
    node.textContent = format(from + (value - from) * eased);
    if (k < 1) node._tick = requestAnimationFrame(step);
  };
  node._tick = requestAnimationFrame(step);
}

// Width of a plate at a given height, from the item's true aspect ratio.
export function plateWidth(item, height) {
  if (item.width && item.height) return Math.round((height * item.width) / item.height);
  return null;
}

// One image plate. Real runs show the downloaded image. SAMPLE runs show a flat tinted frame in the
// item's true aspect ratio, marked with the platform and "post image". An item without an image
// shows what arrived (its date and first words) instead of a placeholder.
export function plate(item, { height, sample = false, number = null } = {}) {
  const hasImage = Boolean(item.thumb && item.media_kind === "image");
  const width = plateWidth(item, height);
  let node;
  if (hasImage) {
    node = el("a", "plate plate-image");
    node.href = item.url;
    node.target = "_blank";
    node.rel = "noopener noreferrer";
    const img = el("img");
    img.src = item.thumb;
    img.alt = item.text ? item.text.slice(0, 90) : `${PLATFORM_NAME[item.platform] || item.platform} post image`;
    img.decoding = "async";
    node.append(img);
    if (!width) {
      img.addEventListener("load", () => {
        if (img.naturalHeight) node.style.width = `${Math.round((height * img.naturalWidth) / img.naturalHeight)}px`;
      }, { once: true });
    }
  } else if (sample && item.width && item.height) {
    node = el("span", "plate plate-sample");
    node.style.setProperty("--tint", `var(--sw-sample-${item.platform}, var(--sw-surface-raised))`);
    const cross = svg("svg", { class: "plate-cross", viewBox: "0 0 100 100", preserveAspectRatio: "none", "aria-hidden": "true" });
    cross.append(svg("line", { x1: 0, y1: 0, x2: 100, y2: 100 }), svg("line", { x1: 100, y1: 0, x2: 0, y2: 100 }));
    const label = el("span", "plate-label");
    label.append(el("b", "", PLATFORM_CODE[item.platform] || item.platform), el("span", "", "post image"));
    node.append(cross, label);
    if (width < 92) node.classList.add("plate-narrow");
  } else {
    node = sample ? el("span", "plate plate-slip") : el("a", "plate plate-slip");
    if (!sample) {
      node.href = item.url;
      node.target = "_blank";
      node.rel = "noopener noreferrer";
    }
    node.append(
      el("span", "slip-date", formatDay(item.published_at) || (item.kind === "page" ? "page" : item.kind)),
      el("span", "slip-text", item.text || item.url),
    );
  }
  node.style.height = `${height}px`;
  if (width && (hasImage || node.classList.contains("plate-sample"))) node.style.width = `${width}px`;
  if (item.kind === "video") node.classList.add("plate-video");
  if (number !== null) node.dataset.number = number;
  node.dataset.platform = item.platform;
  node.title = [PLATFORM_NAME[item.platform], formatDay(item.published_at), item.text].filter(Boolean).join(" · ");
  return node;
}

// The masthead stamp: LIVE, CACHED or SAMPLE, a word in a frame, never colour alone.
export function renderStamp(stamp, mode, { finished = false } = {}) {
  stamp.dataset.state = mode;
  stamp.dataset.finished = finished ? "yes" : "no";
  stamp.replaceChildren(el("span", "stamp-word", STATE_WORD[mode] || mode));
  if (mode === "sample") stamp.append(el("span", "stamp-note", "design sample · not real data"));
  if (mode === "cached") stamp.append(el("span", "stamp-note", "replay of a recorded run"));
  if (mode === "live") stamp.append(el("span", "stamp-note", finished ? "run finished" : "running now"));
}

// Links between the screens keep the same source.
export function wireScreenLinks(query) {
  for (const link of document.querySelectorAll("[data-screen-link]")) {
    link.href = `${link.dataset.screenLink}${query}`;
  }
}
