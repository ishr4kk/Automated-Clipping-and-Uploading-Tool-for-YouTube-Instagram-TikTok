
const path = require("path");
const fs = require("fs/promises");
const crypto = require("crypto");
const { execFile } = require("child_process");
const { machineConfig, PLATFORMS } = require("./config");
const { ensureDirectories, fileExists } = require("./src/fs-utils");
const ytDlp = require("./src/yt-dlp");
const pipeline = require("./src/auto-video-pipeline");
const renderer = require("./src/vertical-renderer");
const music = require("./src/background-music");
const videoCut = require("./src/video-cut");

const MAX_CAPTION_SIDECAR_CHARS = 2200;

function nowIso() {
  return new Date().toISOString();
}

function makeJobId() {
  return `${nowIso().replace(/[:.]/g, "-")}-${crypto.randomBytes(3).toString("hex")}`;
}

function runFfmpegDecodeCheck(filePath) {
  return new Promise((resolve, reject) => {
    execFile(
      "ffmpeg",
      ["-v", "error", "-i", filePath, "-f", "null", "-"],
      { maxBuffer: 64 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) {
          reject(
            new Error(`decode check failed: ${error.message}\n${String(stderr || "").slice(-500)}`)
          );
          return;
        }
        resolve({ stdout, stderr });
      }
    );
  });
}


function platformProfileCandidates(platform) {
  const root = machineConfig.projectRoot;
  const candidates = [path.join(root, ".profiles", "default", platform)];
  if (platform === "youtube") {
    candidates.push(path.join(root, ".profile-youtube"));
  } else if (platform === "instagram") {
    candidates.push(path.join(root, ".profile-instagram"));
  } else if (platform === "tiktok") {
    candidates.push(path.join(root, ".profile"));
  }
  return candidates;
}


async function resolveCookiesForPlatform(platform, workDir, logger) {
  for (const profileDir of platformProfileCandidates(platform)) {
    if (!(await fileExists(profileDir))) {
      continue;
    }
    try {
      const exported = await ytDlp.exportPlatformCookies(platform, profileDir, path.join(workDir, "cookies.txt"));
      if (exported.count > 0) {
        logger.log(`${platform} session cookies exported (${exported.count} cookies)`);
        return exported.path;
      }
    } catch (error) {
      logger.warn(`Cookie export from ${profileDir} failed (${error.message}); using fallback mode`);
    }
  }
  logger.log(`No ${platform} session cookies available; using fallback mode`);
  return null;
}


async function verifyFinalFile(filePath, expectedDuration) {
  const stat = await fs.stat(filePath);
  if (stat.size <= 0) {
    throw new Error(`Final file is empty (${filePath})`);
  }
  await runFfmpegDecodeCheck(filePath);
  const info = await renderer.getVideoInfo(filePath);
  const videoStream = (Array.isArray(info?.streams) ? info.streams : []).find(
    (s) => s.codec_type === "video"
  );
  const audioStream = (Array.isArray(info?.streams) ? info.streams : []).find(
    (s) => s.codec_type === "audio"
  );
  if (!videoStream) {
    throw new Error("Final file has no video stream.");
  }
  if (!audioStream) {
    throw new Error("Final file has no audio stream.");
  }
  const duration = Number(info.format?.duration) || 0;
  if (duration <= 0) {
    throw new Error("Final file has an invalid duration.");
  }
  if (expectedDuration && Math.abs(duration - expectedDuration) > 3) {
    throw new Error(
      `Final duration ${duration.toFixed(1)}s deviates from expected ${expectedDuration.toFixed(1)}s`
    );
  }
  return {
    size: stat.size,
    duration,
    width: Number(videoStream.width) || 0,
    height: Number(videoStream.height) || 0,
    hasAudio: Boolean(audioStream),
  };
}


async function atomicCopy(sourcePath, destDir, destName) {
  const tmpPath = path.join(destDir, `.${destName}.tmp-${crypto.randomBytes(4).toString("hex")}`);
  try {
    await fs.link(sourcePath, tmpPath);
  } catch {
    await fs.copyFile(sourcePath, tmpPath);
  }
  const destPath = path.join(destDir, destName);
  await fs.rename(tmpPath, destPath);
  return destPath;
}


function buildSidecarText(platformKey, platformCaptions) {
  const caps = platformCaptions || {};
  let text = "";
  if (platformKey === "yt") {
    const yt = caps.youtube || {};
    text = [yt.title || "", yt.description || ""].filter(Boolean).join("\n\n");
  } else if (platformKey === "tiktok") {
    text = (caps.tiktok || {}).caption || "";
  } else if (platformKey === "insta") {
    text = (caps.instagram || {}).caption || "";
  }
  return text.slice(0, MAX_CAPTION_SIDECAR_CHARS);
}


async function deliverToUploads({ finalPath, platformCaptions, platforms, jobId, logger }) {
  const delivered = {};
  for (const platformKey of platforms) {
    const dir = machineConfig.uploadDirs[platformKey];
    await ensureDirectories([dir]);

    const baseName = jobId;
    const videoName = `${baseName}.mp4`;
    const destPath = path.join(dir, videoName);

    if (await fileExists(destPath)) {
      logger.warn(`[${platformKey}] Output already exists, skipping: ${videoName}`);
      delivered[platformKey] = { skipped: true, reason: "already exists" };
      continue;
    }


    const copiedPath = await atomicCopy(finalPath, dir, videoName);
    const [srcStat, destStat] = [await fs.stat(finalPath), await fs.stat(copiedPath)];
    if (srcStat.size !== destStat.size) {
      await fs.rm(copiedPath, { force: true }).catch(() => {});
      throw new Error(`[${platformKey}] Copy verification failed: size mismatch after delivery`);
    }

    const sidecarText = buildSidecarText(platformKey, platformCaptions);
    let sidecarPath = null;
    if (sidecarText) {
      sidecarPath = path.join(dir, `${baseName}.description`);
      await fs.writeFile(sidecarPath, sidecarText, "utf8");
    }

    delivered[platformKey] = { video: copiedPath, sidecar: sidecarPath };
    logger.ok(`[${platformKey}] Delivered: ${videoName}${sidecarText ? " (+ sidecar)" : ""}`);
  }
  return delivered;
}


async function generateJob({
  platforms = machineConfig.platforms,
  keepWork = false,
  rng = Math.random,
  logger = null,
} = {}) {
  const musicEnabled = machineConfig.backgroundMusic.enabled;
  const jobId = makeJobId();
  const workDir = path.join(machineConfig.workDir, jobId);
  const renderPath = path.join(workDir, "render.mp4");
  const finalPath = path.join(workDir, "final.mp4");
  await ensureDirectories([workDir]);

  const log = logger || {
    log: (m) => console.log(`[${jobId}] INFO ${m}`),
    ok: (m) => console.log(`[${jobId}] OK   ${m}`),
    warn: (m) => console.log(`[${jobId}] WARN ${m}`),
    fail: (m) => console.log(`[${jobId}] FAIL ${m}`),
  };

  const selectedPlatforms = platforms.filter((p) => PLATFORMS[p]);
  const stageNames = [
    "Selecting random source channel",
    "Preparing session cookies",
    "Selecting random video",
    "Downloading source",
    "Analyzing scene + generating caption",
    "Rendering 9:16 vertical video",
    musicEnabled ? "Adding background music" : "Finalizing video",
    "Generating platform metadata",
    "Final verification",
    "Delivering to upload folders",
  ];
  const totalStages = stageNames.length;

  let stageIndex = 0;
  let lastStageName = "";
  const stage = (name) => {
    stageIndex += 1;
    lastStageName = name;
    log.log(`[${stageIndex}/${totalStages}] ${name}...`);
  };

  const context = { jobId, workDir, finalPath, renderPath };
  const manifestBase = {
    jobId,
    createdAt: nowIso(),
    status: "failed",
    platforms: selectedPlatforms,
    musicEnabled,
  };

  try {
    if (selectedPlatforms.length === 0) {
      throw new Error("No valid platforms selected.");
    }



    try {
      videoCut.validateCutConfig({
        cut: machineConfig.autoVideo.videoCut,
        lengthSeconds: machineConfig.autoVideo.videoLengthSeconds,
      });
    } catch (error) {
      throw new Error(`Video cutting configuration error: ${error.message}`);
    }


    stage(stageNames[0]);
    const channel = pipeline.selectRandomChannel(machineConfig.autoVideo.channels, rng);
    log.ok(`Selected channel: ${channel.handle} (${channel.platform})`);
    context.channel = channel;


    stage(stageNames[1]);
    const cookiesFile = await resolveCookiesForPlatform(channel.platform, workDir, log);


    stage(stageNames[2]);
    const selection = await pipeline.selectRandomMovieVideo(channel.url, { rng, cookiesFile });
    log.ok(`Selected video: ${selection.metadata.title}`);
    context.selection = selection;


    stage(stageNames[3]);
    const { sourcePath, duration } = await pipeline.downloadSource(selection.video, workDir, { cookiesFile });
    log.ok(`Download complete (${(duration / 60).toFixed(1)} min)`);
    context.sourcePath = sourcePath;
    context.sourceDuration = duration;


    stage(stageNames[4]);
    const { analysis, caption } = await pipeline.analyzeAndCaption({ sourcePath, metadata: selection.metadata });
    log.ok(`Scene analysis complete${analysis.usedFrames ? " (frame-based)" : ""}`);
    log.log(`    Movie: ${analysis.movie || "unknown"} | Scene: ${analysis.scene || "unknown"}`);
    log.log(`    Caption: "${caption}"`);
    context.analysis = analysis;
    context.caption = caption;


    stage(stageNames[5]);
    const { renderResult, validation } = await pipeline.renderAndValidate({
      sourcePath,
      outputPath: renderPath,
      caption,
      sourceDuration: duration,
    });
    log.ok(
      `9:16 render complete (${renderResult.plan.canvasWidth}x${renderResult.plan.canvasHeight}, ` +
      `${renderResult.expectedDuration.toFixed(1)}s, caption ${renderResult.caption.lines.length} line(s))`
    );
    context.render = renderResult;
    const finalDuration = validation.details.duration || renderResult.expectedDuration;


    stage(stageNames[6]);
    if (musicEnabled) {
      const resolved = await pipeline.resolveOutputFinal({
        renderPath,
        outputPath: finalPath,
        finalDuration,
        hasOriginalAudio: renderResult.source.hasAudio,
        workDir,
        cookiesFile,
        rng,
      });
      context.music = resolved.music;
      log.ok(
        `Background music added: "${resolved.music.title}" ` +
        `(${resolved.music.sourceDuration.toFixed(1)}s source -> ${resolved.music.finalDuration.toFixed(1)}s)`
      );
    } else {
      await fs.copyFile(renderPath, finalPath);
      log.ok("Music disabled; render copied to final output");
    }


    stage(stageNames[7]);
    const platformCaptions = await pipeline.generatePlatformCaptions(analysis, caption);
    log.ok(`Platform metadata generated for: ${selectedPlatforms.join(", ")}`);
    log.log(`    YouTube title: "${(platformCaptions.youtube || {}).title || ""}"`);
    log.log(`    TikTok caption: "${((platformCaptions.tiktok || {}).caption || "").slice(0, 80)}..."`);
    log.log(`    Instagram caption: "${((platformCaptions.instagram || {}).caption || "").slice(0, 80)}..."`);
    context.platformCaptions = platformCaptions;


    stage(stageNames[8]);
    const finalInfo = await verifyFinalFile(finalPath, finalDuration);
    log.ok(`Final file verified (${(finalInfo.size / 1024 / 1024).toFixed(1)} MB, ` +
      `${finalInfo.width}x${finalInfo.height}, ${finalInfo.duration.toFixed(1)}s, audio=${finalInfo.hasAudio})`);


    stage(stageNames[9]);
    const delivered = await deliverToUploads({
      finalPath,
      platformCaptions,
      platforms: selectedPlatforms,
      jobId,
      logger: log,
    });
    context.delivered = delivered;


    const manifest = {
      ...manifestBase,
      status: "ok",
      stage: stageIndex,
      channel: { handle: channel.handle, url: channel.url },
      video: {
        id: selection.video.id,
        url: selection.video.url,
        title: selection.metadata.title,
        sourceDurationSeconds: duration,
      },
      analysis: {
        movie: analysis.movie,
        scene: analysis.scene,
        characters: analysis.characters,
        action: analysis.action,
        usedFrames: analysis.usedFrames,
      },
      caption,
      music: context.music || null,
      finalFile: {
        path: finalPath,
        sizeBytes: finalInfo.size,
        width: finalInfo.width,
        height: finalInfo.height,
        durationSeconds: finalInfo.duration,
        hasAudio: finalInfo.hasAudio,
      },
      delivered,
    };
    await writeManifest(jobId, manifest);
    context.manifest = manifest;

    log.log(`[COMPLETE] Video delivered for: ${selectedPlatforms.join(", ")}`);
    return { ok: true, jobId, manifest };
  } catch (error) {
    log.fail(`[${stageIndex}/${totalStages}] ${lastStageName || "preflight"} failed: ${error.message}`);
    const manifest = {
      ...manifestBase,
      status: "failed",
      stage: stageIndex,
      stageName: lastStageName || "preflight",
      error: error.message,
      context: {
        channel: context.channel ? { handle: context.channel.handle, url: context.channel.url } : null,
        videoTitle: context.selection ? context.selection.metadata.title : null,
      },
    };
    await writeManifest(jobId, manifest).catch(() => {});
    return { ok: false, jobId, stage: stageIndex, stageName: lastStageName, error: error.message, manifest };
  } finally {
    if (!keepWork) {
      await fs.rm(workDir, { recursive: true, force: true }).catch(() => {});
    } else {
      log.log(`Work dir kept: ${workDir}`);
    }
  }
}

async function writeManifest(jobId, manifest) {
  await ensureDirectories([machineConfig.jobsDir]);
  const manifestPath = path.join(machineConfig.jobsDir, `${jobId}.json`);
  await fs.writeFile(manifestPath, JSON.stringify(manifest, null, 2), "utf8");
  return manifestPath;
}

module.exports = {
  generateJob,
  buildSidecarText,
  deliverToUploads,
  verifyFinalFile,
  makeJobId,
};
