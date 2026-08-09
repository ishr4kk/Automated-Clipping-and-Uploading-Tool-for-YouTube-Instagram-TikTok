
const path = require("path");
const fs = require("fs/promises");
const crypto = require("crypto");
const { config } = require("./config");
const { ensureDirectories } = require("./fs-utils");
const ytDlp = require("./yt-dlp");
const renderer = require("./vertical-renderer");
const music = require("./background-music");
const ai = require("./ai-provider");
const videoCut = require("./video-cut");
const { getActiveAccount, getPlatformProfileDir, getAccountQueueDirs } = require("./account-manager")

const GREEN = "\x1b[32m";
const RED = "\x1b[31m";
const RESET = "\x1b[0m";
const CHECK = "\u2713";
const CROSS = "\u2717";

function log(message) {
  console.log(`[AUTO VIDEO] ${message}`);
}

function okLog(message) {
  console.log(`[AUTO VIDEO] ${GREEN}${CHECK}${RESET} ${message}`);
}

function failLog(message) {
  console.log(`[AUTO VIDEO] ${RED}${CROSS}${RESET} ${message}`);
}

function stageLabel(index, total) {
  return `[${index}/${total}]`;
}


function selectRandomChannel(channels = config.autoVideo.channels, rng = Math.random) {
  if (!Array.isArray(channels) || channels.length === 0) {
    throw new Error("No source channels configured.");
  }
  const index = Math.floor(rng() * channels.length);
  const url = channels[index];
  const match = url.match(/@([^/?#]+)/i);
  return { url, handle: match ? match[1] : url };
}


function keywordMovieRelevance(title = "", description = "") {
  const text = `${title}\n${description}`.toLowerCase();
  const titleOnly = title.toLowerCase();

  const negativePatterns = [
    /tutorial/i, /how to/i, /guide/i, /gameplay/i, /walkthrough/i, /let's play/i,
    /gaming/i, /gamer/i, /twitch/i, /news/i, /update/i, /announcement/i, /vlog/i,
    /reaction/i, /reacting to/i, /review/i, /unboxing/i, /podcast/i, /interview/i,
    /live stream/i, /livestream/i, /asmr/i, /my setup/i, /discussion/i, /top 10/i,
    /ranked/i, /gameplay/i, /game /i, /in game/i, /behind the scenes of (my|the channel)/i,
  ];
  for (const pattern of negativePatterns) {
    if (pattern.test(text)) {
      return { movieRelated: false, reason: `keyword: ${pattern.source}` };
    }
  }


  if (/subscribe/i.test(titleOnly)) {
    return { movieRelated: false, reason: "keyword: subscribe" };
  }

  const positivePatterns = [
    /movie/i, /film/i, /scene/i, /clip/i, /trailer/i, /cinema/i, /cinematic/i,
    /footage/i, /4k hdr/i, /act \d/i, /[a-z]+ \(\d{4}\)/i, /featuring/i, /marvel/i,
    /dc /i, /disney/i, /warner/i, /universal/i, /paramount/i, /sony pictures/i,
    /netflix/i, /20th century/i,
  ];
  for (const pattern of positivePatterns) {
    if (pattern.test(text)) {
      return { movieRelated: true, reason: `keyword: ${pattern.source}` };
    }
  }

  return { movieRelated: null, reason: "keyword: no signal" };
}

function shuffle(items, rng) {
  const result = [...items];
  for (let i = result.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rng() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}


async function selectRandomMovieVideo(channelUrl, { rng = Math.random, maxAttempts = 20, useAi = true, cookiesFile = null } = {}) {
  const catalog = await ytDlp.listChannelVideos(channelUrl);
  if (catalog.length === 0) {
    throw new Error("Channel catalog is empty or could not be listed.");
  }

  let lastSkipped = "";
  const candidates = shuffle(catalog, rng).slice(0, maxAttempts);

  for (const candidate of candidates) {
    let metadata;
    try {
      metadata = await ytDlp.fetchVideoInfo(candidate.url, { cookiesFile });
    } catch {
      continue;
    }

    let verdict = keywordMovieRelevance(metadata.title, metadata.description);
    if (verdict.movieRelated === null && useAi && config.openRouterApiKey) {
      try {
        const aiVerdict = await ai.judgeMovieRelevance(metadata);
        verdict = { movieRelated: aiVerdict.movieRelated, reason: `ai: ${aiVerdict.reason}` };
      } catch {
        verdict = { movieRelated: null, reason: "ai unavailable" };
      }
    }
    if (verdict.movieRelated === false) {
      lastSkipped = `${candidate.title} (${verdict.reason})`;
      continue;
    }
    if (verdict.movieRelated === null) {
      lastSkipped = `${candidate.title} (${verdict.reason})`;
      continue;
    }

    return {
      video: candidate,
      metadata,
      reason: verdict.reason,
    };
  }

  throw new Error(
    `No movie-related video found in catalog of ${catalog.length} entries. Last skipped: ${lastSkipped || "n/a"}`
  );
}


async function downloadSource(video, workDir, { cookiesFile = null } = {}) {
  const sourcePath = await ytDlp.downloadVideo(video.url, workDir, { cookiesFile });
  const { duration } = await ytDlp.validateSourceVideo(sourcePath);
  return { sourcePath, duration };
}


async function analyzeAndCaption({ sourcePath, metadata }) {
  const framesDir = path.join(path.dirname(sourcePath), "frames");
  const frames = await renderer.extractFrames(sourcePath, 6, framesDir);
  const analysis = await ai.analyzeMovieVideo({ videoPath: sourcePath, metadata, frames });
  const { caption } = await ai.generateRetentionCaption(analysis);
  return { analysis, frames, caption };
}


async function renderAndValidate({ sourcePath, outputPath, caption, sourceDuration }) {



  let startSeconds = 0;
  let limitSeconds = null;
  let reason = "";
  const cutConfig = videoCut.validateCutConfig({
    cut: config.autoVideo.videoCut,
    lengthSeconds: config.autoVideo.videoLengthSeconds,
  });
  if (cutConfig.mode === null) {
    const legacy = renderer.computeDurationLimit(sourceDuration);
    limitSeconds = legacy.limitSeconds;
    reason = legacy.reason;
  } else {
    const plan = videoCut.computeCutPlan(sourceDuration, {
      cut: cutConfig.mode,
      lengthSeconds: cutConfig.lengthSeconds,
    });
    startSeconds = plan.startSeconds;
    limitSeconds = plan.limitSeconds;
    reason = plan.reason;
  }
  log(`    Duration rule: ${reason}`);

  const renderResult = await renderer.renderVertical({
    inputPath: sourcePath,
    outputPath,
    caption,
    limitSeconds,
    startSeconds,
    captionImagePath: config.autoVideo.captionImage,
  });

  const validation = await renderer.validateRender({
    outputPath: renderResult.outputPath,
    expectedDuration: renderResult.expectedDuration,
    expectedHasAudio: renderResult.expectedHasAudio,
    plan: renderResult.plan,
    caption: renderResult.caption,
    captionImage: renderResult.captionImage,
  });

  if (!validation.ok) {
    throw new Error(`Rendered file failed validation: ${validation.issues.join("; ")}`);
  }
  return { renderResult, validation };
}


async function resolveOutputFinal({ renderPath, outputPath, finalDuration, hasOriginalAudio, workDir, cookiesFile, rng }) {
  const playlist = music.selectRandomPlaylist(config.backgroundMusic.playlists, rng);
  log(`    Music playlist ${playlist.index + 1}/${playlist.count}: ${playlist.url}`);




  const MUSIC_TRACK_ATTEMPTS = 6;
  let cachedEntries = null;
  const listOnce = async (playlistUrl, opts) => {
    if (!cachedEntries) {
      cachedEntries = await ytDlp.listPlaylistVideos(playlistUrl, opts);
    }
    return cachedEntries;
  };
  let video = null;
  let track = null;
  let lastError = "";
  for (let attempt = 1; attempt <= MUSIC_TRACK_ATTEMPTS; attempt += 1) {
    try {
      const pick = await music.selectRandomPlaylistVideo(playlist.url, {
        rng,
        maxEntries: config.backgroundMusic.maxEntries,
        listVideos: listOnce,
      });
      video = pick.video;
      log(`    Music track: ${video.title || video.id}`);
      track = await music.buildMusicTrack({
        videoUrl: video.url,
        workDir,
        targetDurationSeconds: finalDuration,
        cookiesFile,
      });
      lastError = "";
      break;
    } catch (error) {
      lastError = error.message;
      log(
        `    Music track attempt ${attempt}/${MUSIC_TRACK_ATTEMPTS} failed ` +
        `(${String(error.message).split("\n")[0]}); trying another`
      );
    }
  }
  if (!track) {
    throw new Error(`No downloadable music track found after ${MUSIC_TRACK_ATTEMPTS} attempts. Last error: ${lastError}`);
  }
  log(`    Music source ${track.sourceDuration.toFixed(1)}s -> final ${track.finalDuration.toFixed(1)}s`);

  await music.mixBackgroundMusic({
    videoPath: renderPath,
    musicPath: track.finalPath,
    outputPath,
    targetDurationSeconds: finalDuration,
    hasOriginalAudio,
    musicVolume: config.backgroundMusic.musicVolume,
  });

  const validation = await music.validateMixedOutput(outputPath, {
    expectedDuration: finalDuration,
    expectedHasAudio: true,
  });
  if (!validation.ok) {
    throw new Error(`Background music mix failed validation: ${validation.issues.join("; ")}`);
  }

  return {
    music: {
      title: video.title || video.id,
      url: video.url,
      playlistUrl: playlist.url,
      sourceDuration: track.sourceDuration,
      finalDuration: track.finalDuration,
      targetDuration: finalDuration,
    },
  };
}


async function generatePlatformCaptions(analysis, retentionCaption) {
  try {
    const meta = await ai.generatePlatformMetadata(analysis);
    return meta;
  } catch (error) {

    log(`    Platform metadata generation failed (${error.message}), using fallback captions`);
    return {
      youtube: { title: analysis.movie || "Movie Clip", description: "#trending #fyp #ForYou #Shorts #YouTubeShorts #viral" },
      tiktok: { caption: `${analysis.movie || "Movie Clip"} #foryou #CapCut #fyp #viral #movie #latest` },
      instagram: { caption: `${retentionCaption} #viral #fyp #latest #movie` },
    };
  }
}


function buildPlatformCaptionText(platform, platformCaptions) {
  if (platform === "youtube") {
    const ytMeta = platformCaptions.youtube || {};
    return [ytMeta.title || "", ytMeta.description || ""].filter(Boolean).join("\n\n");
  }
  if (platform === "tiktok") {
    return (platformCaptions.tiktok || {}).caption || "";
  }
  if (platform === "instagram") {
    return (platformCaptions.instagram || {}).caption || "";
  }
  return "";
}


async function saveToQueue({ videoPath, platformCaptions, selectedPlatforms, accountId, dirsOverride }) {
  const dirs = dirsOverride || getAccountQueueDirs(accountId);
  const targetPlatforms = selectedPlatforms.filter((platform) => dirs[platform]);
  if (!targetPlatforms.length) {
    return {};
  }


  const pendingDir = dirs[targetPlatforms[0]].pending;
  await ensureDirectories([pendingDir]);

  const ext = path.extname(videoPath);
  const baseName = path.basename(videoPath, ext);
  const destPath = path.join(pendingDir, `${baseName}${ext}`);

  await fs.copyFile(videoPath, destPath);

  const savedPaths = {};
  for (const platform of targetPlatforms) {
    const captionText = buildPlatformCaptionText(platform, platformCaptions);
    if (captionText) {
      const descPath = path.join(pendingDir, `${baseName}.${platform}.description`);
      await fs.writeFile(descPath, captionText, "utf8");
    }
    savedPaths[platform] = destPath;
  }

  return savedPaths;
}


async function runPipeline({
  upload = false,
  keepWork = false,
  platforms = null,
  accountId = null,
  rng = Math.random,
} = {}) {
  const musicEnabled = config.backgroundMusic.enabled;
  const totalStages = (musicEnabled ? 1 : 0) + 8;
  const jobId = `${new Date().toISOString().replace(/[:.]/g, "-")}-${crypto.randomBytes(3).toString("hex")}`;
  const workDir = path.join(config.autoVideo.workDir, jobId);
  const outputDir = config.autoVideo.outputDir;
  const outputPath = path.join(outputDir, `${jobId}.mp4`);
  const renderPath = path.join(workDir, "render.mp4");
  await ensureDirectories([workDir, outputDir]);


  const account = await getActiveAccount();
  const resolvedAccountId = accountId || account.id;
  const dirs = getAccountQueueDirs(resolvedAccountId);


  const allPlatforms = Object.keys(dirs).filter(p => ["youtube", "tiktok", "instagram"].includes(p));
  const selectedPlatforms = Array.isArray(platforms) && platforms.length
    ? platforms.filter(p => allPlatforms.includes(p))
    : allPlatforms;

  if (selectedPlatforms.length === 0) {
    return { ok: false, error: "No valid platforms selected." };
  }

  const context = { jobId, workDir, outputPath };
  let stageIndex = 0;
  let lastStageName = "";

  const stage = (name) => {
    stageIndex += 1;
    lastStageName = name;
    log(`\n${stageLabel(stageIndex, totalStages)} ${name}...`);
  };

  try {

    if (!config.openRouterApiKey) {
      throw new Error(
        `OPENROUTER_API_KEY is not configured. Set it in .env (https://openrouter.ai/keys) – it is required for movie-relevance verification, scene analysis, and caption generation.`
      );
    }




    try {
      videoCut.validateCutConfig({
        cut: config.autoVideo.videoCut,
        lengthSeconds: config.autoVideo.videoLengthSeconds,
      });
    } catch (error) {
      throw new Error(`Video cutting configuration error: ${error.message}`);
    }


    let cookiesFile = null;
    try {
      const profileDir = await getPlatformProfileDir("youtube", resolvedAccountId);
      const exported = await ytDlp.exportYoutubeCookies(profileDir, path.join(workDir, "cookies.txt"));
      if (exported.count > 0) {
        cookiesFile = exported.path;
        log(`YouTube session cookies exported (${exported.count} cookies)`);
      }
    } catch (error) {
      log(`No YouTube session cookies available (${error.message}); using fallback mode`);
    }


    stage("Selecting random source channel");
    const channel = selectRandomChannel(config.autoVideo.channels, rng);
    okLog(`Selected: ${channel.handle} (${channel.url})`);
    context.channel = channel;


    stage("Selecting random video");
    const selection = await selectRandomMovieVideo(channel.url, { rng, cookiesFile });
    okLog(`Selected: ${selection.metadata.title}`);
    context.selection = selection;


    stage("Validating content");
    okLog(`Movie-related content confirmed (${selection.reason})`);


    stage("Downloading source");
    const { sourcePath, duration } = await downloadSource(selection.video, workDir, { cookiesFile });
    okLog(`Download complete (${(duration / 60).toFixed(1)} min)`);
    context.sourcePath = sourcePath;
    context.sourceDuration = duration;


    stage("Analyzing video");
    const { analysis, caption } = await analyzeAndCaption({
      sourcePath,
      metadata: selection.metadata,
    });
    okLog(`Scene analysis complete${analysis.usedFrames ? " (frame-based)" : ""}`);
    log(`    Movie: ${analysis.movie || "unknown"}`);
    log(`    Scene: ${analysis.scene || "unknown"}`);
    context.analysis = analysis;


    stage("Generating retention caption");
    okLog(`Caption generated: "${caption}"`);
    context.caption = caption;


    stage("Rendering vertical video");
    const { renderResult, validation } = await renderAndValidate({
      sourcePath,
      outputPath: renderPath,
      caption,
      sourceDuration: duration,
    });
    okLog(
      `9:16 render complete (${renderResult.plan.canvasWidth}x${renderResult.plan.canvasHeight}, ` +
      `${renderResult.expectedDuration.toFixed(1)}s, caption ${renderResult.caption.lines.length} line(s))`
    );
    context.render = renderResult;
    const finalDuration = validation.details.duration || renderResult.expectedDuration;


    if (musicEnabled) {
      stage("Adding background music");
      const resolved = await resolveOutputFinal({
        renderPath,
        outputPath,
        finalDuration,
        hasOriginalAudio: renderResult.source.hasAudio,
        workDir,
        cookiesFile,
        rng,
      });
      context.music = resolved.music;
      okLog(
        `Background music added: "${resolved.music.title}" ` +
        `(${resolved.music.sourceDuration.toFixed(1)}s source, mixed to ${resolved.music.finalDuration.toFixed(1)}s)`
      );
    } else {
      await fs.copyFile(renderPath, outputPath);
    }


    stage("Generating platform-specific metadata");
    const platformCaptions = await generatePlatformCaptions(analysis, caption);
    okLog(`Platform metadata generated for: ${selectedPlatforms.join(", ")}`);
    log(`    YouTube title: "${platformCaptions.youtube?.title || ""}"`);
    log(`    TikTok caption: "${(platformCaptions.tiktok?.caption || "").slice(0, 80)}..."`);
    log(`    Instagram caption: "${(platformCaptions.instagram?.caption || "").slice(0, 80)}..."`);
    context.platformCaptions = platformCaptions;


    stage("Saving to upload queue");
    const savedPaths = await saveToQueue({
      videoPath: outputPath,
      platformCaptions,
      selectedPlatforms,
      accountId: resolvedAccountId,
    });
    for (const [platform, savedPath] of Object.entries(savedPaths)) {
      okLog(`[${platform}] Queued: ${path.basename(savedPath)}`);
    }
    context.savedPaths = savedPaths;

    log(`\n[COMPLETE] Video generated and queued for: ${selectedPlatforms.join(", ")}`);
    return {
      ok: true,
      videoId: null,
      outputPath,
      caption,
      channel: context.channel?.handle,
      analysis: context.analysis,
      music: context.music || null,
      platformCaptions,
      savedPaths,
      selectedPlatforms,
      accountId: resolvedAccountId,
    };
  } catch (error) {
    failLog(`${stageLabel(stageIndex, totalStages)} ${lastStageName || "pipeline"} failed`);
    log(`Reason: ${error.message}`);
    return {
      ok: false,
      stage: stageIndex,
      error: error.message,
      outputPath,
      videoId: null,
    };
  } finally {
    if (!keepWork) {
      await fs.rm(workDir, { recursive: true, force: true }).catch(() => {});
    }
  }
}

module.exports = {
  selectRandomChannel,
  keywordMovieRelevance,
  selectRandomMovieVideo,
  downloadSource,
  analyzeAndCaption,
  renderAndValidate,
  resolveOutputFinal,
  generatePlatformCaptions,
  saveToQueue,
  runPipeline,
};
