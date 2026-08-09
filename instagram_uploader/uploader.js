
const fs = require("fs/promises");
const path = require("path");
const crypto = require("crypto");
const { execFile } = require("child_process");
const { config } = require("./config");
const { SessionError, UploadError } = require("./errors");
const { assertLoggedIn } = require("./session");
const { buildReelCaption } = require("./caption");



function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function baseName(fileName) {
  const ext = path.extname(fileName);
  return fileName.slice(0, fileName.length - ext.length);
}

function isVideoFile(fileName) {
  return config.videoExtensions.includes(path.extname(fileName).toLowerCase());
}



async function scanVideos(logger) {
  try {
    await fs.access(config.uploadDir);
  } catch {
    logger.warn(`Upload dir missing: ${config.uploadDir}`);
    return [];
  }
  const entries = await fs.readdir(config.uploadDir, { withFileTypes: true });
  return entries
    .filter((e) => e.isFile() && !e.name.startsWith(".") && isVideoFile(e.name))
    .map((e) => e.name)
    .sort();
}

async function findSidecar(videoName) {
  const base = baseName(videoName);
  for (const ext of config.sidecarExtensions) {
    const candidate = path.join(config.uploadDir, `${base}${ext}`);
    try {
      const stat = await fs.stat(candidate);
      if (stat.isFile()) return candidate;
    } catch {

    }
  }
  return null;
}

async function readSidecar(sidecarPath) {
  return (await fs.readFile(sidecarPath, "utf8")).trim();
}

async function isStable(videoName) {
  const full = path.join(config.uploadDir, videoName);
  try {
    const sizeA = (await fs.stat(full)).size;
    if (sizeA <= 0) return false;
    await sleep(config.stabilityDelaySeconds * 1000);
    const sizeB = (await fs.stat(full)).size;
    return sizeB === sizeA && sizeB > 0;
  } catch {
    return false;
  }
}

function runFfmpegDecodeCheck(filePath) {
  return new Promise((resolve) => {
    execFile(
      "ffmpeg",
      ["-v", "error", "-i", filePath, "-f", "null", "-"],
      { maxBuffer: 64 * 1024 * 1024, timeout: 300000 },
      (error, stdout, stderr) => {
        if (error) {
          resolve({ ok: false, detail: String(stderr || error.message).trim().split("\n").pop().slice(-300) });
          return;
        }
        resolve({ ok: true, detail: "decode ok" });
      }
    );
  });
}


async function verifyVideo(videoName, logger) {
  const full = path.join(config.uploadDir, videoName);
  const decode = await runFfmpegDecodeCheck(full);
  if (!decode.ok) {
    return { ok: false, detail: decode.detail };
  }
  return new Promise((resolve) => {
    execFile(
      "ffprobe",
      ["-v", "error", "-show_entries", "format=duration", "-show_entries", "stream=codec_type", "-of", "json", full],
      { maxBuffer: 16 * 1024 * 1024, timeout: 120000 },
      (error, stdout, stderr) => {
        if (error) {
          if (error.code === "ENOENT") {
            logger.warn("ffprobe not found; skipping stream verification");
            resolve({ ok: true, detail: "unverified (no ffprobe)" });
            return;
          }
          resolve({ ok: false, detail: String(stderr || error.message).slice(-300) });
          return;
        }
        try {
          const info = JSON.parse(stdout || "{}");
          const streams = info.streams || [];
          const hasVideo = streams.some((s) => s.codec_type === "video");
          const hasAudio = streams.some((s) => s.codec_type === "audio");
          const duration = Number(info.format?.duration || 0);
          if (!hasVideo || !hasAudio || duration <= 0) {
            resolve({ ok: false, detail: `bad streams (video=${hasVideo} audio=${hasAudio} duration=${duration})` });
            return;
          }
          resolve({ ok: true, detail: `${duration.toFixed(1)}s` });
        } catch (exc) {
          resolve({ ok: false, detail: `ffprobe output unreadable: ${exc.message}` });
        }
      }
    );
  });
}



async function loadState(logger) {
  try {
    return JSON.parse(await fs.readFile(config.statePath, "utf8"));
  } catch {
    return { processed: {} };
  }
}

async function saveState(state) {
  await fs.mkdir(config.stateDir, { recursive: true });
  const tmp = `${config.statePath}.tmp-${crypto.randomBytes(4).toString("hex")}`;
  await fs.writeFile(tmp, JSON.stringify(state, null, 2), "utf8");
  await fs.rename(tmp, config.statePath);
}



function pidAlive(pid) {
  if (!pid || !Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === "EPERM";
  }
}

async function acquireLock(logger) {
  await fs.mkdir(config.stateDir, { recursive: true });
  const entry = { pid: process.pid, startedAt: new Date().toISOString() };
  try {
    const handle = await fs.open(config.lockPath, "wx");
    await handle.writeFile(JSON.stringify(entry));
    await handle.close();
    logger.log(`Lock acquired (pid ${process.pid})`);
    return true;
  } catch (error) {
    if (error.code !== "EEXIST") throw error;
    let stale = true;
    try {
      const existing = JSON.parse(await fs.readFile(config.lockPath, "utf8"));
      stale = !pidAlive(existing.pid);
    } catch {

    }
    if (stale) {
      logger.warn("Stale lock detected (previous process died); reclaiming");
      await fs.rm(config.lockPath, { force: true });
      return acquireLock(logger);
    }
    return false;
  }
}

async function releaseLock() {
  await fs.rm(config.lockPath, { force: true });
}



async function moveToDone(videoName, sidecarPath, logger) {
  await fs.mkdir(config.doneDir, { recursive: true });
  const srcVideo = path.join(config.uploadDir, videoName);
  const dstVideo = path.join(config.doneDir, videoName);

  const videoExists = await fs
    .access(srcVideo)
    .then(() => true)
    .catch(() => false);
  if (!videoExists) {

    logger.warn(`${videoName} already gone from upload folder; skipping move`);
    return;
  }
  await fs.rename(srcVideo, dstVideo);
  if (sidecarPath) {
    const sidecarName = path.basename(sidecarPath);
    const exists = await fs
      .access(sidecarPath)
      .then(() => true)
      .catch(() => false);
    if (exists) {
      await fs.rename(sidecarPath, path.join(config.doneDir, sidecarName));
    }
  }
  logger.ok(`Moved ${videoName}${sidecarPath ? ` + ${path.basename(sidecarPath)}` : ""} -> queue/insta/done`);
}



async function waitForAny(page, selectors, timeoutMs, description, { attachedOnly = false } = {}) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    for (const selector of selectors) {
      try {
        const locator = page.locator(selector).first();
        if (attachedOnly) {
          if ((await locator.count()) > 0) {
            return locator;
          }
        } else if (await locator.isVisible({ timeout: 500 })) {
          return locator;
        }
      } catch (error) {
        lastError = error;
      }
    }
    await sleep(500);
  }
  throw new UploadError(
    `Timed out waiting for ${description} (${timeoutMs / 1000}s). ` +
      `Last error: ${lastError ? lastError.message.split("\n")[0] : "none"}`
  );
}


async function clickThroughNextSteps(page) {
  const deadline = Date.now() + 180000;
  while (Date.now() < deadline) {
    let clicked = false;
    for (const selector of config.selectors.nextButtons) {
      try {
        const locator = page.locator(selector).first();
        if (await locator.isVisible({ timeout: 500 })) {
          await locator.click({ timeout: 5000 });
          clicked = true;
          break;
        }
      } catch {

      }
    }
    if (!clicked) return;
    await sleep(2500);
  }
}

async function dismissReelsNotice(page) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    for (const selector of config.selectors.reelsNoticeOk) {
      try {
        const locator = page.locator(selector).first();
        if (await locator.isVisible({ timeout: 500 })) {
          await locator.click({ timeout: 5000 });
          return true;
        }
      } catch {

      }
    }
    await sleep(1000);
  }
  return false;
}

async function fillCaption(page, caption) {
  const box = await waitForAny(page, config.selectors.captionBox, 180000, "caption box");

  await box.click({ timeout: 8000 });
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.type(String(caption || ""), { delay: 2 });
  await sleep(500);
  const typed = await box.textContent().catch(() => "");
  if (String(caption).trim() && !(typed || "").includes(String(caption).slice(0, 20))) {
    await box.click({ timeout: 8000 });
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.type(String(caption), { delay: 5 });
    await sleep(500);
  }
  return box;
}

async function findShareButton(page) {
  const deadline = Date.now() + config.uploadTimeoutMs;
  while (Date.now() < deadline) {
    for (const selector of config.selectors.shareButtons) {
      try {
        const locator = page.locator(selector).first();
        if (await locator.isVisible({ timeout: 500 })) {
          const disabled = await locator.isDisabled().catch(() => false);
          if (!disabled) return locator;
        }
      } catch {

      }
    }
    await sleep(2000);
  }
  return null;
}

async function clickShare(page, shareButton) {


  try {
    await shareButton.click({ timeout: 8000 });
  } catch {
    await shareButton.click({ force: true, timeout: 8000 });
  }
}

async function closeSuccessDialog(page) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    for (const selector of config.selectors.successDoneButton) {
      try {
        const locator = page.locator(selector).first();
        if (await locator.isVisible({ timeout: 500 })) {
          await locator.click({ timeout: 5000 });
          return;
        }
      } catch {

      }
    }
    await sleep(1000);
  }
}

async function waitForSuccess(page, logger) {
  const deadline = Date.now() + config.confirmTimeoutMs;
  while (Date.now() < deadline) {

    for (const selector of config.selectors.successSignals) {
      try {
        const locator = page.locator(selector).first();
        if (await locator.isVisible({ timeout: 400 })) {
          logger.ok("Success notification detected");
          await closeSuccessDialog(page).catch(() => {});
          return true;
        }
      } catch {

      }
    }


    const url = page.url();
    if (/\/reel\/[A-Za-z0-9_-]+/.test(url)) {
      logger.ok("Redirected to the shared Reel page — upload confirmed");
      return true;
    }

    let errorText = null;
    try {
      const errorEl = page
        .locator("text=We couldn't share this")
        .or(page.locator("text=Something went wrong"))
        .or(page.locator("text=Unable to share"))
        .first();
      if (await errorEl.isVisible({ timeout: 400 })) {
        errorText = "Instagram reported a share error.";
      }
    } catch {

    }
    if (errorText) {
      throw new UploadError(errorText);
    }
    await sleep(2000);
  }
  throw new UploadError(
    `Timed out waiting for Instagram to confirm the Reel (${config.confirmTimeoutMs / 1000}s)`
  );
}

async function extractReelUrl(page) {
  try {
    const match = page.url().match(/\/reel\/([A-Za-z0-9_-]+)/);
    if (match) return `https://www.instagram.com/reel/${match[1]}/`;
  } catch {

  }
  return null;
}


async function uploadVideo({ context, videoPath, caption, logger }) {
  const page = await context.newPage();
  try {
    logger.log("Upload started");
    await page.goto(config.uploadUrl, {
      waitUntil: "domcontentloaded",
      timeout: config.navTimeoutMs,
    });
    await page.waitForTimeout(6000);
    await assertLoggedIn(page, logger);


    const createButton = await waitForAny(page, config.selectors.createButton, 30000, "create button");
    await createButton.click({ timeout: 10000 });
    logger.log("Composer opened");
    await page.waitForTimeout(3000);

    const fileInput = await waitForAny(page, config.selectors.fileInput, 30000, "file input", {
      attachedOnly: true,
    });
    await fileInput.setInputFiles(videoPath);
    logger.ok(`File attached: ${path.basename(videoPath)}`);


    await sleep(config.postFileDelayMs);
    await dismissReelsNotice(page);

    await clickThroughNextSteps(page);
    await fillCaption(page, caption);
    logger.ok("Caption loaded");

    const shareButton = await findShareButton(page);
    if (!shareButton) {
      throw new UploadError("Share button never became available.");
    }
    await clickShare(page, shareButton);
    logger.log("Share clicked — waiting for Instagram confirmation");

    await waitForSuccess(page, logger);
    const url = await extractReelUrl(page);
    logger.ok("Upload completed — Instagram confirmed the Reel");
    return { url };
  } catch (error) {
    await page
      .screenshot({ path: path.join(config.stateDir, `debug-${Date.now()}.png`), fullPage: true })
      .catch(() => {});
    if (error instanceof SessionError || error instanceof UploadError) {
      throw error;
    }
    throw new UploadError(`Instagram upload page error: ${error.message.split("\n")[0]}`, {
      cause: error,
    });
  } finally {
    await page.close().catch(() => {});
  }
}




async function processVideo(videoName, sidecarPath, state, { context, logger }) {
  const base = baseName(videoName);
  const record = {
    base,
    video: videoName,
    sidecar: sidecarPath ? path.basename(sidecarPath) : null,
    status: "failed",
    attempts: 0,
    error: null,
  };


  if (state.processed[base]) {
    logger.warn(`${videoName} already processed (recorded); moving to done`);
    await moveToDone(videoName, sidecarPath, logger);
    return { ...record, status: "already-posted" };
  }


  let sidecarText = "";
  if (sidecarPath) {
    try {
      sidecarText = await readSidecar(sidecarPath);
      logger.log(`Description loaded (${sidecarText.length} chars)`);
    } catch (error) {
      logger.fail(`Could not read ${path.basename(sidecarPath)}: ${error.message}`);
    }
  }
  const { caption, hashtags, truncated } = buildReelCaption(sidecarText, {
    fixedCaption: config.fixedCaption,
    maxCaptionChars: config.maxCaptionChars,
  });
  logger.log(
    `Caption generated (${caption.length} chars, ${hashtags.length} hashtag(s)` +
      `${truncated ? ", truncated to fit limit" : ""})`
  );

  const verified = await verifyVideo(videoName, logger);
  if (!verified.ok) {
    record.error = `video failed verification: ${verified.detail}`;
    logger.fail(`${videoName} — ${record.error} (kept in upload folder)`);
    return record;
  }
  logger.log(`${videoName} verified (${verified.detail})`);

  const attempts = config.maxRetries + 1;
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    record.attempts = attempt;
    try {
      const result = await uploadVideo({
        context,
        videoPath: path.join(config.uploadDir, videoName),
        caption,
        logger,
      });

      state.processed[base] = {
        url: result.url,
        video: videoName,
        uploadedAt: new Date().toISOString(),
      };
      await saveState(state);
      await moveToDone(videoName, sidecarPath, logger);
      record.status = "ok";
      record.url = result.url;
      logger.ok(`DONE: ${videoName} shared${result.url ? ` -> ${result.url}` : ""}`);
      return record;
    } catch (error) {
      lastError = error;
      if (error instanceof SessionError) {
        record.error = error.message;
        logger.fail(`${videoName} — ${error.message}`);
        return record;
      }
      if (attempt < attempts) {
        const backoff = config.retryBackoffMs[Math.min(attempt - 1, config.retryBackoffMs.length - 1)];
        logger.warn(
          `${videoName} upload attempt ${attempt}/${attempts} failed (${error.message}); retrying in ${backoff / 1000}s`
        );
        await sleep(backoff);
      }
    }
  }

  record.error = lastError ? lastError.message : "unknown error";
  logger.fail(`${videoName} failed after ${attempts} attempts: ${record.error} (kept in upload folder)`);
  return record;
}


async function runCycle({ context, state, logger, missingSidecarSince = {}, processVideo: processVideoImpl = processVideo, quiet = false }) {
  state.processed = state.processed || {};
  const videos = await scanVideos(logger);
  if (videos.length === 0) {
    if (!quiet) {
      logger.log("Scanning queue/insta/upload... no videos pending");
    }
    return { processed: [], missingSidecarSince, videos: 0 };
  }

  if (quiet) {
    logger.log("New videos detected in queue/insta/upload");
  }
  logger.log(`Scanning queue/insta/upload... ${videos.length} video(s) pending`);
  const processed = [];

  for (let index = 0; index < videos.length; index += 1) {
    const videoName = videos[index];
    const base = baseName(videoName);
    let sidecarPath = await findSidecar(videoName);

    if (!sidecarPath) {
      const seen = (missingSidecarSince[base] || 0) + 1;
      missingSidecarSince[base] = seen;
      if (seen < config.missingSidecarWaitCycles) {
        logger.log(`${videoName}: no sidecar yet (cycle ${seen}/${config.missingSidecarWaitCycles}); deferring`);
        continue;
      }
      logger.warn(`${videoName}: no sidecar after ${seen} cycles; proceeding with fixed caption only`);
    } else {
      delete missingSidecarSince[base];
    }

    if (!(await isStable(videoName))) {
      logger.warn(`${videoName} still being written; deferring`);
      continue;
    }

    logger.log(`Uploading: ${videoName}`);
    processed.push(await processVideoImpl(videoName, sidecarPath, state, { context, logger }));



    if (config.delaySeconds > 0 && index < videos.length - 1) {
      logger.log(`Waiting ${config.delaySeconds} seconds before next upload`);
      await sleep(config.delaySeconds * 1000);
    }
  }

  for (const base of Object.keys(missingSidecarSince)) {
    if (!videos.some((v) => baseName(v) === base)) {
      delete missingSidecarSince[base];
    }
  }

  return { processed, missingSidecarSince, videos: videos.length };
}

module.exports = {
  scanVideos,
  findSidecar,
  readSidecar,
  isStable,
  verifyVideo,
  loadState,
  saveState,
  acquireLock,
  releaseLock,
  moveToDone,
  uploadVideo,
  waitForSuccess,
  processVideo,
  runCycle,
  baseName,
};
