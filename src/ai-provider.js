
const fs = require("fs/promises");
const path = require("path");
const crypto = require("crypto");
const os = require("os");
const { execFile } = require("child_process");
const { config } = require("./config");
const { fileExists } = require("./fs-utils");

class UnsupportedMediaError extends Error {
  constructor(message) {
    super(message);
    this.name = "UnsupportedMediaError";
  }
}

function runFfmpeg(args) {
  return new Promise((resolve, reject) => {
    execFile("ffmpeg", args, { maxBuffer: 50 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(`ffmpeg failed: ${error.message}\n${stderr}`));
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

function requireApiKey() {
  if (!config.openRouterApiKey) {
    throw new Error(
      "OPENROUTER_API_KEY is not configured. Add it to .env (https://openrouter.ai/keys)."
    );
  }
  return config.openRouterApiKey;
}

async function fetchWithRetry(url, options, { attempts = 4, timeoutMs = 120000 } = {}) {
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      const body = await response.text();
      if (response.ok) {
        return JSON.parse(body);
      }

      const message = safeErrorMessage(body);
      if (response.status === 400 && /video/i.test(message) && !/image/i.test(message)) {
        throw new UnsupportedMediaError(`Model rejected video input: ${message}`);
      }
      if (response.status === 429 || response.status >= 500) {


        lastError = new Error(`OpenRouter HTTP ${response.status}: ${message}`);
        await new Promise((resolve) => setTimeout(resolve, 2000 * attempt));
        continue;
      }
      throw new Error(`OpenRouter HTTP ${response.status}: ${message}`);
    } catch (error) {
      if (error.name === "AbortError") {
        lastError = new Error(`OpenRouter request timed out after ${timeoutMs}ms.`);
      } else {
        lastError = error;
      }
      if (error instanceof UnsupportedMediaError) {
        throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000 * attempt));
    } finally {
      clearTimeout(timer);
    }
  }
  throw lastError || new Error("OpenRouter request failed.");
}


function safeErrorMessage(body) {
  try {
    const parsed = JSON.parse(body);
    return String(parsed.error?.message || parsed.error || "unknown error").slice(0, 500);
  } catch {
    return String(body || "unknown error").slice(0, 500);
  }
}

async function chatCompletion(messages, { model, timeoutMs, maxTokens = 1024, temperature = 0.7 }) {
  const apiKey = requireApiKey();
  const payload = {
    model: model || config.openRouterModel,
    messages,
    max_tokens: maxTokens,
    temperature,
  };

  const data = await fetchWithRetry(
    `${config.openRouterBaseUrl}/chat/completions`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
    { timeoutMs: timeoutMs || 180000 }
  );

  const content = data?.choices?.[0]?.message?.content;
  if (typeof content !== "string" || !content.trim()) {
    throw new Error("OpenRouter returned an empty response.");
  }
  return content.trim();
}


function parseJsonResponse(text) {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = fenced ? fenced[1] : text;
  try {
    return JSON.parse(candidate);
  } catch {
    const start = candidate.indexOf("{");
    const end = candidate.lastIndexOf("}");
    if (start !== -1 && end > start) {
      try {
        return JSON.parse(candidate.slice(start, end + 1));
      } catch {

      }
    }
  }
  throw new Error("AI response was not valid JSON.");
}


async function prepareVideoForAnalysis(videoPath) {
  const stat = await fs.stat(videoPath);
  const MAX_BYTES = 35 * 1024 * 1024;
  if (stat.size <= MAX_BYTES) {
    return videoPath;
  }

  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "autovideo-preview-"));
  const previewPath = path.join(dir, `preview_${crypto.randomBytes(4).toString("hex")}.mp4`);
  await runFfmpeg([
    "-y",
    "-i", videoPath,
    "-vf", "scale='min(1280,iw)':-2",
    "-r", "30",
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-crf", "30",
    "-maxrate", "1.5M",
    "-bufsize", "3M",
    "-c:a", "aac",
    "-b:a", "96k",
    "-ar", "44100",
    "-movflags", "+faststart",
    previewPath,
  ]);

  const previewStat = await fs.stat(previewPath);
  if (previewStat.size > MAX_BYTES) {
    await fs.rm(dir, { recursive: true, force: true });
    throw new Error("Video too large to prepare for AI analysis.");
  }
  return previewPath;
}

async function makeVideoContentPart(videoPath, mimeType = "video/mp4") {
  const buffer = await fs.readFile(videoPath);
  return { type: "video", video: `data:${mimeType};base64,${buffer.toString("base64")}` };
}

async function makeImageContentParts(framePaths) {
  const parts = [];
  for (const framePath of framePaths) {
    const buffer = await fs.readFile(framePath);
    parts.push({
      type: "image_url",
      image_url: { url: `data:image/jpeg;base64,${buffer.toString("base64")}` },
    });
  }
  return parts;
}


async function judgeMovieRelevance({ title, description = "", channel = "" }) {
  const system = [
    "You decide whether a YouTube video is movie-related content.",
    "Movie-related: movie clips, movie scenes, movie trailers, film footage, cinematic content.",
    "NOT movie-related: tutorials, news, gaming, vlogs, shorts unrelated to movies, channel announcements.",
    "Reply with STRICT JSON only: {\"movie_related\": boolean, \"reason\": \"short reason\"}.",
  ].join("\n");

  const user = [
    `Channel: ${channel}`,
    `Title: ${title}`,
    `Description: ${String(description || "").slice(0, 1500)}`,
    "Is this movie-related content?",
  ].join("\n");

  const content = await chatCompletion(
    [
      { role: "system", content: system },
      { role: "user", content },
    ],
    { maxTokens: 300, temperature: 0 }
  );
  const parsed = parseJsonResponse(content);
  return {
    movieRelated: Boolean(parsed.movie_related),
    reason: String(parsed.reason || "").slice(0, 300),
  };
}


async function analyzeMovieVideo({ videoPath, metadata, frames = [] }) {
  const system = [
    "You are a film analyst creating insights for a short-form video creator.",
    "Watch the provided movie clip and report what is actually happening in it.",
    "Be specific and accurate. Do not invent events that are not visible.",
    "Reply with STRICT JSON only:",
    '{"movie":"movie or franchise being shown (or null if unknown)",',
    '"scene":"what scene this is",',
    '"characters":["identifiable characters (or empty)"],',
    '"action":"main action/event in the clip",',
    '"context":"important context",',
    '"interestingPart":"the most interesting part of the scene",',
    '"whyInteresting":"why a viewer would care"}',
  ].join("\n");

  const user = [
    `Source video title: ${metadata?.title || ""}`,
    `Source description: ${String(metadata?.description || "").slice(0, 1500)}`,
    "Analyze the actual content of this clip.",
  ].join("\n");

  let usedFrames = false;
  let content;






  if (frames.length) {
    usedFrames = true;
    content = await chatCompletion(
      [
        { role: "system", content: system },
        {
          role: "user",
          content: [{ type: "text", text: user }, ...(await makeImageContentParts(frames))],
        },
      ],
      { model: config.openRouterFrameModel || undefined, maxTokens: 1024, temperature: 0.3 }
    );
  } else {
    try {
      const prepared = await prepareVideoForAnalysis(videoPath);
      const mimeType = prepared.endsWith(".mp4") ? "video/mp4" : "video/mp4";
      content = await chatCompletion(
        [
          { role: "system", content: system },
          {
            role: "user",
            content: [
              { type: "text", text: user },
              await makeVideoContentPart(prepared, mimeType),
            ],
          },
        ],
        { maxTokens: 1024, temperature: 0.3 }
      );
    } catch (error) {
      throw new Error(
        `AI could not analyze the clip (no frame fallback available): ${error.message}`
      );
    }
  }

  const parsed = parseJsonResponse(content);
  return {
    movie: String(parsed.movie || ""),
    scene: String(parsed.scene || ""),
    characters: Array.isArray(parsed.characters)
      ? parsed.characters.map((c) => String(c)).filter(Boolean)
      : [],
    action: String(parsed.action || ""),
    context: String(parsed.context || ""),
    interestingPart: String(parsed.interestingPart || ""),
    whyInteresting: String(parsed.whyInteresting || ""),
    usedFrames,
  };
}


async function generateRetentionCaption(analysis) {
  const system = [
    "You write viewer-retention captions for vertical short-form movie clips.",
    "Rules:",
    "- Relate directly to the analyzed scene.",
    "- Accurately represent what happens (no false claims).",
    "- Create curiosity and encourage watching until the end.",
    "- Never use generic captions unrelated to the scene.",
    "- Maximum 90 characters. No hashtags. No emoji unless essential.",
    "Reply with STRICT JSON only: {\"caption\": \"...\"}.",
  ].join("\n");

  const user = [
    `Movie: ${analysis.movie || "unknown"}`,
    `Scene: ${analysis.scene || "unknown"}`,
    `Characters: ${(analysis.characters || []).join(", ") || "unknown"}`,
    `Action: ${analysis.action || "unknown"}`,
    `Context: ${analysis.context || "unknown"}`,
    `Most interesting part: ${analysis.interestingPart || "unknown"}`,
    `Why interesting: ${analysis.whyInteresting || "unknown"}`,
    "Write the retention caption now.",
  ].join("\n");

  const content = await chatCompletion(
    [
      { role: "system", content: system },
      { role: "user", content: user },
    ],
    { maxTokens: 300, temperature: 0.8 }
  );
  const parsed = parseJsonResponse(content);
  const caption = String(parsed.caption || "").replace(/\s+/g, " ").trim();
  if (!caption) {
    throw new Error("AI returned an empty caption.");
  }
  return { caption };
}


async function generatePlatformMetadata(analysis) {
  const movieName = analysis.movie || "unknown movie";
  const characters = (analysis.characters || []).join(", ") || "unknown characters";
  const scene = analysis.scene || "unknown scene";
  const action = analysis.action || "";

  const system = [
    "You generate platform-specific social media metadata for a short movie clip.",
    "Use ONLY the information provided — do not invent movie names, character names, or scenes.",
    "Each platform has specific rules you must follow exactly.",
    "Reply with STRICT JSON only (no markdown fences).",
  ].join("\n");

  const user = [
    `Movie/franchise: ${movieName}`,
    `Characters visible: ${characters}`,
    `Scene: ${scene}`,
    `Action: ${action}`,
    `Interesting part: ${analysis.interestingPart || ""}`,
    "",
    "Generate metadata for all 3 platforms:",
    "",
    "YOUTUBE SHORTS:",
    "- title: ONLY the movie name OR main character name (no descriptive sentence). Append: #Shorts #YouTubeShorts #viral",
    "- description: relevant hashtags starting with #trending #fyp #ForYou plus movie/character hashtags",
    "",
    "TIKTOK:",
    "- caption: ONLY the identified movie name OR main character name. No sentence. Include: #foryou #CapCut #fyp #viral #movie #latest plus relevant movie/character hashtags",
    "",
    "INSTAGRAM:",
    "- caption: relevant description based on the actual clip content. Include: #viral #fyp #latest #movie plus relevant movie/character hashtags",
    "",
    'Return JSON: {"youtube":{"title":"...","description":"..."},"tiktok":{"caption":"..."},"instagram":{"caption":"..."}}',
  ].join("\n");

  const content = await chatCompletion(
    [
      { role: "system", content: system },
      { role: "user", content: user },
    ],
    { maxTokens: 800, temperature: 0.7 }
  );

  const parsed = parseJsonResponse(content);


  const ytTitle = String(parsed?.youtube?.title || movieName).trim();
  const ytDesc = String(parsed?.youtube?.description || "#trending #fyp #ForYou").trim();
  const ttCaption = String(parsed?.tiktok?.caption || movieName).trim();
  const igCaption = String(parsed?.instagram?.caption || scene).trim();

  return {
    youtube: {
      title: ytTitle,
      description: ytDesc,
    },
    tiktok: {
      caption: ttCaption,
    },
    instagram: {
      caption: igCaption,
    },
  };
}

module.exports = {
  UnsupportedMediaError,
  chatCompletion,
  parseJsonResponse,
  judgeMovieRelevance,
  analyzeMovieVideo,
  generateRetentionCaption,
  generatePlatformMetadata,
  prepareVideoForAnalysis,
};
