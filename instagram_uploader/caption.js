

const HASHTAG_RE = /#([a-zA-Z0-9_\u00C0-\u024F][a-zA-Z0-9_\u00C0-\u024F]*)/g;


function extractHashtags(sidecarText) {
  const seen = new Set();
  const tags = [];
  const raw = String(sidecarText || "");
  let match;
  HASHTAG_RE.lastIndex = 0;
  while ((match = HASHTAG_RE.exec(raw)) !== null) {
    const full = match[0];
    const key = full.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      tags.push(full);
    }
  }
  return tags;
}


function buildReelCaption(sidecarText, options = {}) {
  const fixed = (options.fixedCaption || "").trim();
  const limit = options.maxCaptionChars || 2200;
  const tags = extractHashtags(sidecarText);

  const base = fixed || "".trim();
  let caption = tags.length ? `${base}\n\n${tags.join(" ")}` : base;
  caption = caption.replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();

  let truncated = false;
  if (caption.length > limit) {


    const kept = [];
    let length = base.length;
    for (const tag of tags) {
      const extra = (kept.length ? 1 : 0) + 1 + tag.length;
      if (length + extra > limit - 2) break;
      kept.push(tag);
      length += extra;
      truncated = true;
    }
    caption = kept.length ? `${base}\n\n${kept.join(" ")}` : base;
    caption = caption.trim();
  }

  return { caption, hashtags: tags, truncated };
}

module.exports = { buildReelCaption, extractHashtags };
