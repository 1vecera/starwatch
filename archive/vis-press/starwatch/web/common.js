// Shared helpers for every screen: DOM building, platform marks, formatting, image frames in true
// aspect ratios, counters that run to their collected value, and the masthead's state bug.
// Collected text only ever goes in through textContent, never innerHTML.

export const PLATFORMS = {
  website: { code: "WEB", name: "Website" },
  facebook: { code: "FB", name: "Facebook" },
  instagram: { code: "IG", name: "Instagram" },
  tiktok: { code: "TT", name: "TikTok" },
  youtube: { code: "YT", name: "YouTube" },
  x: { code: "X", name: "X" },
};
export const PLATFORM_ORDER = ["website", "facebook", "instagram", "tiktok", "youtube", "x"];

export const PRESET_NAMES = { G1: "G1 Debate prep", G2: "G2 Respond to this post", G3: "G3 Background check" };

export const STATUS_WORDS = {
  queued: "Queued",
  running: "Collecting",
  done: "Done",
  failed: "Failed",
  skipped: "Skipped",
  not_implemented: "Not built yet",
};

export const COVERAGE_WORDS = {
  collected: "Collected",
  unavailable: "Missing",
  not_found: "Not found",
  skipped: "Skipped",
};

const PRAGUE = "Europe/Prague";

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null && text !== "") node.textContent = text;
  return node;
}

export function link(href, className, text) {
  const node = el("a", className, text);
  if (href) {
    node.href = href;
    node.target = "_blank";
    node.rel = "noopener noreferrer";
  }
  return node;
}

export function pmark(platform, { gap = false } = {}) {
  const mark = el("span", "pmark", PLATFORMS[platform]?.code || String(platform || "?").toUpperCase());
  mark.dataset.platform = platform;
  if (gap) mark.dataset.gap = "";
  mark.title = PLATFORMS[platform]?.name || platform;
  return mark;
}

export function motionAllowed() {
  return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Mark a node as arriving now (animated) unless the event is backlog or motion is reduced. */
export function arrive(node, animate, delayMs = 0) {
  if (!animate || !motionAllowed()) return node;
  node.classList.add("arriving");
  if (delayMs) node.style.animationDelay = `${delayMs}ms`;
  node.addEventListener("animationend", () => node.classList.remove("arriving"), { once: true });
  return node;
}

// --- formatting ----------------------------------------------------------------------------------

export function clockTime(iso, { seconds = false } = {}) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}), timeZone: PRAGUE,
  });
}

export function longDate(iso) {
  return new Date(iso || Date.now()).toLocaleDateString("en-GB", {
    weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: PRAGUE,
  });
}

export function shortDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 10);
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: PRAGUE });
}

export function dayMonth(iso) {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: PRAGUE });
}

export function elapsed(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function elapsedWords(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(s / 60);
  return m ? `${m} min ${s % 60} s` : `${s} s`;
}

export const usd = (n) => `$${(Number(n) || 0).toFixed(2)}`;
export const count = (n) => Math.round(Number(n) || 0).toLocaleString("en-GB");
export const plural = (n, one, many = `${one}s`) => `${count(n)} ${n === 1 ? one : many}`;
export const timecode = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function compact(n) {
  const v = Number(n) || 0;
  if (v >= 1e6) return `${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)}M`;
  if (v >= 1e4) return `${(v / 1e3).toFixed(v >= 1e5 ? 0 : 1)}k`;
  return count(v);
}

/** Run a number up to its collected value. Jumps straight there for backlog or reduced motion. */
export function tick(node, to, { format = count, animate = true, ms = 450 } = {}) {
  const from = Number(node.dataset.value ?? to);
  node.dataset.value = String(to);
  if (!animate || !motionAllowed() || from === to) {
    node.textContent = format(to);
    return;
  }
  const start = performance.now();
  const token = Symbol("tick");
  node._tick = token;
  const step = (now) => {
    if (node._tick !== token) return;
    const t = Math.min(1, (now - start) / ms);
    const eased = 1 - (1 - t) ** 3;
    node.textContent = format(from + (to - from) * eased);
    if (t < 1) requestAnimationFrame(step);
    else node.textContent = format(to);
  };
  requestAnimationFrame(step);
}

// --- image frames --------------------------------------------------------------------------------

function ratioOf(item) {
  if (item.width && item.height) return item.width / item.height;
  if (item.kind === "page") return 1.9;
  return 1;
}

/**
 * One collected item as an image frame in its true aspect ratio.
 * Real image: the downloaded file. Sample mode: a flat tinted frame marked with the platform and
 * "post image". A real item without an image: what arrived, as text, never a placeholder picture.
 */
export function frame(item, { sample = false, height = "var(--sw-thumb-lane)" } = {}) {
  const ratio = item.thumb ? ratioOf(item) : sample && item.width && item.height ? ratioOf(item) : item.kind === "page" ? 1.9 : 1.25;
  const node = el("span", "frame");
  node.style.setProperty("--frame-h", height);
  node.style.setProperty("--ar", ratio.toFixed(4));
  node.dataset.platform = item.platform;
  node.dataset.itemId = item.id;
  if (item.thumb && item.media_kind === "video") {
    node.classList.add("frame-img");
    const video = el("video");
    video.src = item.thumb;
    video.muted = true;
    video.preload = "metadata";
    video.playsInline = true;
    node.append(video);
  } else if (item.thumb) {
    node.classList.add("frame-img");
    const img = el("img");
    img.src = item.thumb;
    img.alt = item.text ? item.text.slice(0, 90) : `${PLATFORMS[item.platform]?.name || item.platform} ${item.kind}`;
    img.decoding = "async";
    if (!(item.width && item.height)) {
      img.addEventListener("load", () => {
        if (img.naturalWidth && img.naturalHeight) {
          node.style.setProperty("--ar", (img.naturalWidth / img.naturalHeight).toFixed(4));
        }
      }, { once: true });
    }
    node.append(img);
  } else if (sample && item.width && item.height) {
    node.classList.add("frame-sample");
    if (ratio < 0.7) node.dataset.narrow = "";
    const label = el("span", "frame-label");
    label.append(el("b", "", PLATFORMS[item.platform]?.code || item.platform), document.createTextNode("post image"));
    node.append(label);
  } else {
    node.classList.add("frame-text");
    node.append(
      el("span", "frame-text-kind", item.kind === "page" ? "Page" : item.kind),
      el("span", "frame-text-body", item.kind === "page" ? breakable(pagePath(item.url)) : shortDate(item.published_at) || "no image"),
    );
  }
  if (item.kind === "video") node.append(el("span", "video-mark"));
  node.title = [PLATFORMS[item.platform]?.name, shortDate(item.published_at), item.text].filter(Boolean).join(" · ");
  return node;
}

export function frameWidthRem(item, heightRem, sample) {
  const ratio = item.thumb ? ratioOf(item) : sample && item.width && item.height ? ratioOf(item) : item.kind === "page" ? 1.9 : 1.25;
  return heightRem * ratio;
}

/** Let long paths wrap after slashes and hyphens instead of mid-word. */
export function breakable(text) {
  return String(text).replace(/([/\-_.])/g, "$1\u200b");
}

export function pagePath(url) {
  try {
    const u = new URL(url);
    return u.pathname === "/" ? u.hostname : decodeURIComponent(u.pathname).replace(/\/$/, "");
  } catch {
    return url;
  }
}

export function host(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

// --- masthead ------------------------------------------------------------------------------------

/**
 * The state bug and folio every screen carries. `view` comes from source.js:
 * { state: "idle" | "live" | "cached" | "sample", running, speed, recordedAt }.
 */
export function renderStateBug(node, view) {
  node.dataset.state = view.state;
  node.dataset.running = view.running ? "yes" : "no";
  const words = { idle: "No run", live: "Live", cached: "Cached", sample: "Sample" };
  node.replaceChildren(document.createTextNode(words[view.state] || view.state));
}

export function stateLine(view, run, nowMs) {
  if (!run) return "";
  const finished = Boolean(run.finishedAt);
  const end = finished ? Date.parse(run.finishedAt) : nowMs;
  const span = elapsed(end - Date.parse(run.startedAt));
  const pace = view.speed && view.speed !== 1 ? ` · ${view.speed}× pace` : "";
  if (view.state === "sample") return `design data, not a real run · ${span}${finished ? " total" : ""}${pace}`;
  if (view.state === "cached") return `replay of run ${dayMonth(run.startedAt)} ${clockTime(run.startedAt)} · ${span}${pace}`;
  return `run ${clockTime(run.startedAt)} · ${span} ${finished ? "total" : "elapsed"}`;
}
