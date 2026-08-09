
const path = require("path");
const dotenv = require("dotenv");

const uploaderRoot = __dirname;
const projectRoot = path.resolve(uploaderRoot, "..");


dotenv.config({ path: path.join(projectRoot, ".env"), override: true });

function envInt(name, defaultValue) {
  const raw = process.env[name];
  if (raw === undefined || raw === null || raw === "") return defaultValue;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : defaultValue;
}

function envNum(name, defaultValue) {
  const raw = process.env[name];
  if (raw === undefined || raw === null || raw === "") return defaultValue;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : defaultValue;
}

function envBool(name, defaultValue) {
  const raw = process.env[name];
  if (raw === undefined || raw === null || raw === "") return defaultValue;
  return raw.toString().toLowerCase() === "true";
}

function envStr(name, defaultValue) {
  const raw = process.env[name];
  return raw === undefined || raw === "" ? defaultValue : raw;
}

const stateDir = envStr("TIKTOK_UPLOADER_STATE_DIR", path.join(uploaderRoot, "state"));

const config = {
  root: projectRoot,
  uploaderRoot,



  uploadDir: envStr("TIKTOK_UPLOADER_UPLOAD_DIR", path.join(projectRoot, "queue", "tiktok", "upload")),
  doneDir: envStr("TIKTOK_UPLOADER_DONE_DIR", path.join(projectRoot, "queue", "tiktok", "done")),


  stateDir,
  statePath: path.join(stateDir, "processed.json"),
  lockPath: path.join(stateDir, "uploader.lock"),


  logFile: envStr("TIKTOK_UPLOADER_LOG_FILE", path.join(projectRoot, "logs", "tiktok-uploader.log")),


  videoExtensions: [".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"],
  sidecarExtensions: [".description", ".txt"],


  pollIntervalSeconds: envInt("TIKTOK_UPLOADER_POLL_SECONDS", 20),
  stabilityDelaySeconds: envInt("TIKTOK_UPLOADER_STABILITY_SECONDS", 8),
  missingSidecarWaitCycles: envInt("TIKTOK_UPLOADER_SIDECAR_WAIT_CYCLES", 3),



  delaySeconds: envNum("UPLOAD_DELAY_SECONDS", 0),


  maxRetries: envInt("TIKTOK_UPLOADER_MAX_RETRIES", 3),
  retryBackoffMs: [5000, 15000, 30000],

  sessionRetryIntervalMs: envInt("TIKTOK_UPLOADER_SESSION_RETRY_SECONDS", 120) * 1000,


  uploadUrl: envStr(
    "TIKTOK_UPLOADER_UPLOAD_URL",
    "https://www.tiktok.com/tiktokstudio/upload"
  ),
  navTimeoutMs: envInt("TIKTOK_UPLOADER_NAV_TIMEOUT_MS", 60000),

  uploadTimeoutMs: envInt("TIKTOK_UPLOADER_UPLOAD_TIMEOUT_MS", 10 * 60 * 1000),

  confirmTimeoutMs: envInt("TIKTOK_UPLOADER_CONFIRM_TIMEOUT_MS", 3 * 60 * 1000),


  headless: envBool("TIKTOK_UPLOADER_HEADLESS", true),

  browserChannels: ["chromium", "msedge", "chrome"],
  viewport: { width: 1366, height: 900 },
  locale: "en-US",
  userAgent:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",



  selectors: {
    fileInput: ['input[type="file"]'],
    captionBox: [
      'div[contenteditable="true"][data-e2e="post-textarea"]',
      "div.notranslate.public-DraftEditor-content",
      'div[contenteditable="true"]',
      'textarea[data-e2e="post-textarea"]',
      "textarea",
    ],
    postButton: [
      'button[data-e2e="post_video_button"]',
      'button[data-e2e="post_button"]',
      'button[data-e2e="post-button"]',
      "button:has-text('Post')",
    ],
    progressBar: [
      'div[data-e2e="video-progress"]',
      'div[data-e2e="upload-progress"]',
      "div[role='progressbar']",
    ],
    successSignals: [
      'div[data-e2e="post-success"]',
      "text=Your video is being posted",
      "text=Your video has been posted",
      "text=Video posted",
      "text=Posted successfully",
    ],
    loginSignals: [
      "input[name='username']",
      'input[data-e2e="login-username"]',
      "text=Log in to TikTok",
      "text=Sign up for TikTok",
    ],
  },
};

module.exports = { config };
