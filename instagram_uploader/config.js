
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

const stateDir = envStr("INSTA_UPLOADER_STATE_DIR", path.join(uploaderRoot, "state"));

const config = {
  root: projectRoot,
  uploaderRoot,



  uploadDir: envStr("INSTA_UPLOADER_UPLOAD_DIR", path.join(projectRoot, "queue", "insta", "upload")),
  doneDir: envStr("INSTA_UPLOADER_DONE_DIR", path.join(projectRoot, "queue", "insta", "done")),


  stateDir,
  statePath: path.join(stateDir, "processed.json"),
  lockPath: path.join(stateDir, "uploader.lock"),


  logFile: envStr("INSTA_UPLOADER_LOG_FILE", path.join(projectRoot, "logs", "instagram-uploader.log")),


  videoExtensions: [".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"],
  sidecarExtensions: [".description", ".txt"],


  pollIntervalSeconds: envInt("INSTA_UPLOADER_POLL_SECONDS", 20),
  stabilityDelaySeconds: envInt("INSTA_UPLOADER_STABILITY_SECONDS", 8),
  missingSidecarWaitCycles: envInt("INSTA_UPLOADER_SIDECAR_WAIT_CYCLES", 3),



  delaySeconds: envNum("UPLOAD_DELAY_SECONDS", 0),


  maxRetries: envInt("INSTA_UPLOADER_MAX_RETRIES", 3),
  retryBackoffMs: [5000, 15000, 30000],
  sessionRetryIntervalMs: envInt("INSTA_UPLOADER_SESSION_RETRY_SECONDS", 120) * 1000,


  homeUrl: "https://www.instagram.com/",


  uploadUrl: envStr("INSTA_UPLOADER_UPLOAD_URL", "https://www.instagram.com/"),
  navTimeoutMs: envInt("INSTA_UPLOADER_NAV_TIMEOUT_MS", 60000),
  uploadTimeoutMs: envInt("INSTA_UPLOADER_UPLOAD_TIMEOUT_MS", 10 * 60 * 1000),
  confirmTimeoutMs: envInt("INSTA_UPLOADER_CONFIRM_TIMEOUT_MS", 5 * 60 * 1000),


  postFileDelayMs: envInt("INSTA_UPLOADER_POST_FILE_DELAY_MS", 20000),


  headless: envBool("INSTA_UPLOADER_HEADLESS", true),
  browserChannels: ["chromium", "msedge", "chrome"],
  viewport: { width: 1366, height: 900 },
  locale: "en-US",
  userAgent:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",



  fixedCaption:
    "Tonight, V stepped into the crowd, taking in live performances at Vogue World: Hollywood. " +
    "Known for his own standout fashion moments, he kept it effortlessly stylish in look worthy of the runway.",
  maxCaptionChars: 2200,




  selectors: {

    createButton: ["a[href='#']:has(svg[aria-label='New post'])", "svg[aria-label='New post']"],
    fileInput: ['input[type="file"]'],


    reelsNoticeOk: ["div[role='dialog']:has-text('shared as reels') button:has-text('OK')"],

    nextButtons: [
      "div[role='button']:has-text('Next')",
      "button:has-text('Next')",
      "div[role='button']:has-text('Trim')",
    ],
    captionBox: [
      "div[role='textbox'][aria-label='Write a caption...']",
      "div[role='textbox'][aria-label*='caption']",
      "div[role='textbox']",
      "textarea[aria-label*='caption']",
      "textarea",
    ],
    shareButtons: [
      "div[role='dialog'] div[role='button']:has-text('Share')",
      "div[role='button']:has-text('Share')",
      "button:has-text('Share')",
    ],
    successSignals: [
      "text=Reel shared",
      "text=Your reel has been shared.",
      "text=Your reel was shared",
    ],

    successDoneButton: ["div[role='dialog']:has-text('Reel shared') div[role='button']:has-text('Done')"],
    loginSignals: [
      "input[name='username']",
      "input[name='password']",
      "text=Log in to Instagram",
      "text=Sign up to see photos and videos",
    ],
  },
};

module.exports = { config };
