
const { execFile } = require("child_process");
const fs = require("fs/promises");
const path = require("path");
const os = require("os");

const CANVAS_WIDTH = 1080;
const CANVAS_HEIGHT = 1920;
const TARGET_ASPECT = CANVAS_WIDTH / CANVAS_HEIGHT;

const MAX_CLIP_SECONDS = 178;
const MIN_FULL_CLIP_SECONDS = 90;
const MAX_CAPTION_LINES = 3;

const CAPTION_FONT_SIZE = 48;
const CAPTION_BOX_BORDER = 26;
const CAPTION_LINE_SPACING = 12;


const CAPTION_IMAGE_PADDING = 40;
const CAPTION_IMAGE_MAX_HEIGHT_RATIO = 0.35;


const CAPTION_IMAGE_SCALE = 0.6;
const CAPTION_IMAGE_MIN_HEIGHT = 120;
const CAPTION_IMAGE_MAX_BAND_RATIO = 0.45;

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

function runFfprobe(args) {
  return new Promise((resolve, reject) => {
    execFile("ffprobe", args, { maxBuffer: 10 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(`ffprobe failed: ${error.message}\n${stderr}`));
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

async function getVideoInfo(inputPath) {
  const { stdout } = await runFfprobe([
    "-v", "quiet",
    "-print_format", "json",
    "-show_format",
    "-show_streams",
    inputPath,
  ]);
  return JSON.parse(stdout);
}

function getPrimaryVideoStream(videoInfo) {
  const streams = Array.isArray(videoInfo?.streams) ? videoInfo.streams : [];
  return streams.find((stream) => stream.codec_type === "video") || null;
}

function getPrimaryAudioStream(videoInfo) {
  const streams = Array.isArray(videoInfo?.streams) ? videoInfo.streams : [];
  return streams.find((stream) => stream.codec_type === "audio") || null;
}


function computeDurationLimit(durationSeconds) {
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) {
    throw new Error(`Invalid source duration: ${durationSeconds}`);
  }
  if (durationSeconds > MAX_CLIP_SECONDS) {
    return { limitSeconds: MAX_CLIP_SECONDS, reason: `clip longer than 2:58; using first ${MAX_CLIP_SECONDS}s` };
  }
  if (durationSeconds < MIN_FULL_CLIP_SECONDS) {
    return { limitSeconds: null, reason: "clip under 1.5 minutes; using entire clip" };
  }
  return { limitSeconds: null, reason: "clip between 1.5 and 2:58 minutes; using entire clip" };
}


function planComposition(width, height, { maxHeight = CANVAS_HEIGHT, regionY = 0 } = {}) {
  const w = Number(width);
  const h = Number(height);
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) {
    throw new Error(`Invalid source dimensions: ${width}x${height}`);
  }
  if (!Number.isFinite(maxHeight) || maxHeight <= 0) {
    throw new Error(`Invalid maxHeight: ${maxHeight}`);
  }

  const scale = Math.min(CANVAS_WIDTH / w, maxHeight / h);
  const fgW = Math.round(w * scale);
  const fgH = Math.round(h * scale);
  const fgX = Math.round((CANVAS_WIDTH - fgW) / 2);
  const fgY = Math.round(regionY + (maxHeight - fgH) / 2);



  const letterboxAbove = fgY;
  const useTopLetterbox = letterboxAbove >= 280;
  const captionZone = useTopLetterbox ? "top-letterbox" : "top-box";

  return {
    canvasWidth: CANVAS_WIDTH,
    canvasHeight: CANVAS_HEIGHT,
    maxHeight,
    regionY,
    fgW,
    fgH,
    fgX,
    fgY,
    fgAspect: w / h,
    captionZone,
  };
}


async function probeImageSize(imagePath) {
  const resolved = path.resolve(imagePath);
  const { stdout } = await runFfprobe([
    "-v", "error",
    "-select_streams", "v:0",
    "-show_entries", "stream=width,height",
    "-print_format", "json",
    resolved,
  ]);
  const parsed = JSON.parse(stdout);
  const stream = Array.isArray(parsed.streams) ? parsed.streams[0] : null;
  const width = Number(stream?.width) || 0;
  const height = Number(stream?.height) || 0;
  if (width <= 0 || height <= 0) {
    throw new Error(`Could not read image dimensions for ${imagePath}`);
  }
  return { width, height };
}


function planCaptionImage(imgWidth, imgHeight, srcWidth, srcHeight) {
  const iw = Number(imgWidth);
  const ih = Number(imgHeight);
  if (!Number.isFinite(iw) || !Number.isFinite(ih) || iw <= 0 || ih <= 0) {
    throw new Error(`Invalid caption image dimensions: ${imgWidth}x${imgHeight}`);
  }
  const imgAspect = iw / ih;
  const pad = CAPTION_IMAGE_PADDING;


  const maxW = Math.round((CANVAS_WIDTH - 2 * pad) * CAPTION_IMAGE_SCALE);


  let imgW = Math.round(maxW);
  let imgH = Math.round(imgW / imgAspect);
  const maxImgH = Math.round(CANVAS_HEIGHT * CAPTION_IMAGE_MAX_HEIGHT_RATIO);
  if (imgH > maxImgH) {
    imgH = maxImgH;
    imgW = Math.round(imgH * imgAspect);
  }


  let moviePlan = planComposition(srcWidth, srcHeight);
  let availableBottom = CANVAS_HEIGHT - (moviePlan.fgY + moviePlan.fgH);



  if (imgH + 2 * pad <= availableBottom) {
    const imgX = Math.round((CANVAS_WIDTH - imgW) / 2);
    const imgY = moviePlan.fgY + moviePlan.fgH + pad;
    return { imgW, imgH, imgX, imgY, moviePlan };
  }


  let bandHeight = imgH + 2 * pad;
  const maxBand = Math.round(CANVAS_HEIGHT * CAPTION_IMAGE_MAX_BAND_RATIO);
  if (bandHeight > maxBand) {
    bandHeight = maxBand;
    imgH = Math.max(CAPTION_IMAGE_MIN_HEIGHT, bandHeight - 2 * pad);
    imgW = Math.round(imgH * imgAspect);
    if (imgW > maxW) {
      imgW = maxW;
      imgH = Math.round(imgW / imgAspect);
    }
  }

  const regionMaxH = CANVAS_HEIGHT - bandHeight;
  moviePlan = planComposition(srcWidth, srcHeight, { maxHeight: regionMaxH, regionY: 0 });
  availableBottom = CANVAS_HEIGHT - (moviePlan.fgY + moviePlan.fgH);


  if (imgH > availableBottom - 2 * pad) {
    imgH = Math.max(CAPTION_IMAGE_MIN_HEIGHT, availableBottom - 2 * pad);
    imgW = Math.round(imgH * imgAspect);
    if (imgW > maxW) {
      imgW = maxW;
      imgH = Math.round(imgW / imgAspect);
    }
  }

  const imgX = Math.round((CANVAS_WIDTH - imgW) / 2);
  const imgY = Math.min(
    moviePlan.fgY + moviePlan.fgH + pad,
    CANVAS_HEIGHT - imgH - pad
  );
  return { imgW, imgH, imgX, imgY, moviePlan };
}


function estimateCaptionHeight(lineCount) {
  return (
    lineCount * CAPTION_FONT_SIZE +
    (lineCount - 1) * CAPTION_LINE_SPACING +
    CAPTION_BOX_BORDER * 2
  );
}


function wrapCaptionText(caption, maxCharsPerLine = 34, maxLines = MAX_CAPTION_LINES) {
  const text = String(caption || "").replace(/\s+/g, " ").trim();
  if (!text) {
    return [];
  }

  const words = text.split(" ");
  const lines = [];
  let current = "";
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= maxCharsPerLine) {
      current = candidate;
      continue;
    }
    if (current) {
      lines.push(current);
      current = "";
    }
    if (word.length > maxCharsPerLine) {
      let remainder = word;
      while (remainder.length > maxCharsPerLine && lines.length < maxLines) {
        lines.push(remainder.slice(0, maxCharsPerLine));
        remainder = remainder.slice(maxCharsPerLine);
      }
      if (lines.length < maxLines) {
        current = remainder;
      }
    } else {
      current = word;
    }
    if (lines.length >= maxLines) {
      break;
    }
  }
  if (current && lines.length < maxLines) {
    lines.push(current);
  }
  return lines.slice(0, maxLines);
}


function pickFontFile() {
  const candidates = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
  ];
  const fsSync = require("fs");
  return candidates.find((fontPath) => fsSync.existsSync(fontPath)) || "";
}

function escapeFilterPath(filePath) {
  return filePath.replace(/\\/g, "/").replace(/:/g, "\\:");
}


function buildDrawtextFilter({ textFilePath, fontFile, captionY }) {
  const options = [
    "drawtext",
    `textfile='${escapeFilterPath(textFilePath)}'`,
    `fontcolor=white`,
    `fontsize=${CAPTION_FONT_SIZE}`,
    `bordercolor=black`,
    `borderw=6`,
    `box=1`,
    `boxcolor=black@0.45`,
    `boxborderw=${CAPTION_BOX_BORDER}`,
    `line_spacing=${CAPTION_LINE_SPACING}`,
    `x=(w-text_w)/2`,
    `y=${Math.max(30, captionY)}`,
    `shadowcolor=black@0.4`,
    `shadowx=2`,
    `shadowy=2`,
  ];
  if (fontFile) {
    options.splice(1, 0, `fontfile='${escapeFilterPath(fontFile)}'`);
  }
  return `${options[0]}=${options.slice(1).join(":")}`;
}

async function renderVertical({ inputPath, outputPath, caption, limitSeconds, startSeconds = 0, captionImagePath }) {
  const resolvedInput = path.resolve(inputPath);
  await fs.access(resolvedInput);
  const resolvedOutput = path.resolve(outputPath);
  await fs.mkdir(path.dirname(resolvedOutput), { recursive: true });

  const videoInfo = await getVideoInfo(resolvedInput);
  const videoStream = getPrimaryVideoStream(videoInfo);
  if (!videoStream) {
    throw new Error("Source video has no video stream.");
  }
  const width = Number(videoStream.width) || 0;
  const height = Number(videoStream.height) || 0;
  const duration = Number(videoInfo.format?.duration) || 0;
  const hasAudio = Boolean(getPrimaryAudioStream(videoInfo));



  let imagePlan = null;
  let resolvedCaptionImage = null;
  if (captionImagePath) {
    const candidate = path.resolve(captionImagePath);
    const imageExists = await fs.access(candidate).then(() => true).catch(() => false);
    if (imageExists) {
      const { width: imgW, height: imgH } = await probeImageSize(candidate);
      imagePlan = planCaptionImage(imgW, imgH, width, height);
      resolvedCaptionImage = candidate;
    }
  }



  const plan = imagePlan ? imagePlan.moviePlan : planComposition(width, height);
  const lines = wrapCaptionText(caption);
  if (!lines.length) {
    throw new Error("Cannot render: caption is empty.");
  }
  const captionHeight = estimateCaptionHeight(lines.length);

  let captionY;
  if (plan.captionZone === "top-letterbox") {
    captionY = Math.max(30, Math.round((plan.fgY - captionHeight) / 2));
  } else {
    captionY = 70;
  }

  const workDir = await fs.mkdtemp(path.join(os.tmpdir(), "autovideo-caption-"));
  const textFilePath = path.join(workDir, "caption.txt");
  await fs.writeFile(textFilePath, lines.join("\n"), "utf8");

  const fontFile = pickFontFile();
  if (!fontFile) {
    await fs.rm(workDir, { recursive: true, force: true });
    throw new Error("No usable Windows system font found for caption rendering.");
  }
  const drawtext = buildDrawtextFilter({ textFilePath, fontFile, captionY, lineCount: lines.length });

  const maxThreads = Math.max(2, Math.floor(os.cpus().length / 2));
  const args = ["-y"];




  const startSecondsNumber = Number(startSeconds) || 0;
  if (startSecondsNumber > 0) {
    args.push("-ss", String(startSecondsNumber));
  }




  const filterParts = [
    `[0:v]split=2[bg][fg]`,
    `[bg]scale=${CANVAS_WIDTH}:${CANVAS_HEIGHT}:force_original_aspect_ratio=increase,crop=${CANVAS_WIDTH}:${CANVAS_HEIGHT},gblur=sigma=25[bg]`,
    `[fg]scale=${CANVAS_WIDTH}:${plan.maxHeight}:force_original_aspect_ratio=decrease[fg]`,
    `[bg][fg]overlay=${plan.fgX}:${plan.fgY}:shortest=1[base]`,
  ];

  if (imagePlan) {


    filterParts.push(
      `[1:v]scale=${imagePlan.imgW}:${imagePlan.imgH},format=rgba[capimg]`,
      `[base][capimg]overlay=${imagePlan.imgX}:${imagePlan.imgY}:shortest=1[withcap]`,
      `[withcap]${drawtext}[vout]`
    );
  } else {
    filterParts.push(`[base]${drawtext}[vout]`);
  }

  args.push("-i", resolvedInput);
  if (imagePlan) {


    args.push("-loop", "1", "-i", resolvedCaptionImage);
  }
  args.push("-filter_complex", filterParts.join(";"));
  args.push("-map", "[vout]");
  if (hasAudio) {
    args.push("-map", "0:a:0");
  }
  if (limitSeconds) {
    args.push("-t", String(limitSeconds));
  }
  args.push("-shortest");
  args.push("-r", "30");
  args.push("-c:v", "libx264");
  args.push("-crf", "22");
  args.push("-preset", "medium");
  args.push("-pix_fmt", "yuv420p");
  args.push("-threads", String(maxThreads));
  if (hasAudio) {
    args.push("-c:a", "aac");
    args.push("-b:a", "160k");
    args.push("-ar", "44100");
    args.push("-ac", "2");
  }
  args.push("-movflags", "+faststart");
  args.push(resolvedOutput);

  await runFfmpeg(args);

  await fs.rm(workDir, { recursive: true, force: true });



  const availableAfterSeek = Math.max(0, duration - startSecondsNumber);
  const expectedDuration = limitSeconds
    ? Math.min(limitSeconds, availableAfterSeek)
    : availableAfterSeek;
  return {
    outputPath: resolvedOutput,
    plan,
    caption: { lines, captionY, captionHeight },
    captionImage: imagePlan
      ? {
          imgW: imagePlan.imgW,
          imgH: imagePlan.imgH,
          imgX: imagePlan.imgX,
          imgY: imagePlan.imgY,
          imagePath: resolvedCaptionImage,
        }
      : null,
    source: { width, height, duration, hasAudio },
    expectedDuration,
    expectedHasAudio: hasAudio,
  };
}


async function sampleRegionStats(videoPath, timestampSeconds, region) {
  const regionArg = region
    ? `crop=${region.w}:${region.h}:${region.x}:${region.y},`
    : "";
  const { stdout } = await runFfprobe([
    "-v", "error",
    "-ss", String(timestampSeconds),
    "-i", videoPath,
    "-frames:v", "1",
    "-vf", `${regionArg}signalstats,metadata=print:file=-`,
    "-f", "null",
    "-",
  ]).catch(async () => {

    const { stdout: out } = await runFfmpeg([
      "-v", "error",
      "-ss", String(timestampSeconds),
      "-i", videoPath,
      "-frames:v", "1",
      "-vf", `${regionArg}signalstats,metadata=print:file=-`,
      "-f", "null",
      "-",
    ]);
    return { stdout: out };
  });

  const stats = {};
  for (const match of stdout.matchAll(/(YAVG|YMIN|YMAX|YSTDDEV)\s*=\s*([\d.]+)/g)) {
    stats[match[1]] = Number(match[2]);
  }
  return stats;
}


function validateRenderChecks({
  exists,
  playable,
  resolution,
  expectedResolution,
  duration,
  expectedDuration,
  hasAudio,
  expectedHasAudio,
  frameStats,
  captionStats,
  captionImageStats,
}) {
  const issues = [];
  if (!exists) issues.push("output file does not exist");
  if (!playable) issues.push("output file could not be opened/decoded");
  if (
    expectedResolution &&
    resolution &&
    (resolution.width !== expectedResolution.width || resolution.height !== expectedResolution.height)
  ) {
    issues.push(`resolution ${resolution.width}x${resolution.height} is not ${expectedResolution.width}x${expectedResolution.height}`);
  }
  if (expectedDuration && duration) {
    const drift = Math.abs(duration - expectedDuration);
    if (drift > 2.5) {
      issues.push(`duration ${duration.toFixed(1)}s deviates from expected ${expectedDuration.toFixed(1)}s`);
    }
  }
  if (expectedHasAudio && !hasAudio) issues.push("expected audio track is missing");

  const frameSamples = Array.isArray(frameStats) ? frameStats : [];
  const blackFrames = frameSamples.filter((sample) => sample.yavg < 5);
  if (blackFrames.length) {
    issues.push(`${blackFrames.length} sampled frame(s) are black`);
  }

  if (captionStats) {
    const contrast = (captionStats.ymax || 0) - (captionStats.ymin || 0);
    if (contrast < 80 || (captionStats.yavg || 0) < 12) {
      issues.push("caption not detected in caption region (low contrast)");
    }
  }

  if (captionImageStats) {


    const contrast = (captionImageStats.ymax || 0) - (captionImageStats.ymin || 0);
    if (contrast < 25 || (captionImageStats.yavg || 0) < 8) {
      issues.push("caption image not detected in its region (low contrast)");
    }
  }

  return {
    ok: issues.length === 0,
    issues,
    details: { resolution, duration, hasAudio, frameSamples },
  };
}

async function validateRender({ outputPath, expectedDuration, expectedHasAudio, plan, caption, captionImage }) {
  const resolved = path.resolve(outputPath);
  const exists = await fs.access(resolved).then(() => true).catch(() => false);
  if (!exists) {
    return validateRenderChecks({ exists: false });
  }

  let videoInfo;
  try {
    videoInfo = await getVideoInfo(resolved);
  } catch {
    return validateRenderChecks({ exists: true, playable: false });
  }

  const videoStream = getPrimaryVideoStream(videoInfo);
  if (!videoStream) {
    return validateRenderChecks({ exists: true, playable: false });
  }
  const resolution = { width: Number(videoStream.width), height: Number(videoStream.height) };
  const duration = Number(videoInfo.format?.duration) || 0;
  const hasAudio = Boolean(getPrimaryAudioStream(videoInfo));

  const durationToSample = Math.max(
    0.1,
    Math.min(Math.max(duration - 0.5, 0.1), duration / 2)
  );
  const frameStats = [];
  for (const fraction of [0.25, 0.5, 0.75]) {
    const timestamp = Math.max(0, Math.min(duration - 0.3, duration * fraction));
    const stats = await sampleRegionStats(resolved, timestamp, null);
    frameStats.push({ timestamp, yavg: stats.YAVG || 0, ymax: stats.YMAX || 0, ymin: stats.YMIN || 0 });
  }

  let captionStats = null;
  if (caption) {
    const region = {
      x: 0,
      y: Math.max(0, caption.captionY),
      w: plan ? plan.canvasWidth : CANVAS_WIDTH,
      h: Math.min(caption.captionHeight + 60, CANVAS_HEIGHT),
    };
    const stats = await sampleRegionStats(resolved, durationToSample, region);
    captionStats = { yavg: stats.YAVG || 0, ymax: stats.YMAX || 0, ymin: stats.YMIN || 0 };
  }

  let captionImageStats = null;
  if (captionImage) {
    const region = {
      x: Math.max(0, captionImage.imgX),
      y: Math.max(0, captionImage.imgY),
      w: Math.min(captionImage.imgW, CANVAS_WIDTH),
      h: Math.min(captionImage.imgH, CANVAS_HEIGHT),
    };
    const stats = await sampleRegionStats(resolved, durationToSample, region);
    captionImageStats = { yavg: stats.YAVG || 0, ymax: stats.YMAX || 0, ymin: stats.YMIN || 0 };
  }

  return validateRenderChecks({
    exists: true,
    playable: true,
    resolution,
    expectedResolution: { width: CANVAS_WIDTH, height: CANVAS_HEIGHT },
    duration,
    expectedDuration,
    hasAudio,
    expectedHasAudio,
    frameStats,
    captionStats,
    captionImageStats,
  });
}


async function extractFrames(inputPath, count = 6, outDir) {
  const resolvedInput = path.resolve(inputPath);
  const info = await getVideoInfo(resolvedInput);
  const videoStream = getPrimaryVideoStream(info);
  if (!videoStream) {
    throw new Error("Cannot extract frames: source has no video stream.");
  }
  const duration = Number(info.format?.duration) || 0;
  if (duration <= 0) {
    throw new Error("Cannot extract frames: unknown duration.");
  }

  await fs.mkdir(outDir, { recursive: true });
  const framePaths = [];
  const target = Math.min(count, 8);

  for (let index = 0; index < target; index += 1) {
    const fraction = target === 1 ? 0.5 : index / (target - 1);
    const timestamp = Math.max(
      0.1,
      Math.min(Math.max(duration - 0.2, 0.1), Math.max(0.1, duration * fraction))
    );
    const framePath = path.join(outDir, `frame_${String(index).padStart(2, "0")}.jpg`);
    await runFfmpeg([
      "-y",
      "-v", "error",
      "-ss", String(timestamp),
      "-i", resolvedInput,
      "-frames:v", "1",
      "-vf", "scale=640:-2",
      "-q:v", "4",
      framePath,
    ]);
    framePaths.push(framePath);
  }
  return framePaths;
}

module.exports = {
  CANVAS_WIDTH,
  CANVAS_HEIGHT,
  computeDurationLimit,
  planComposition,
  planCaptionImage,
  probeImageSize,
  wrapCaptionText,
  estimateCaptionHeight,
  pickFontFile,
  buildDrawtextFilter,
  renderVertical,
  validateRender,
  validateRenderChecks,
  extractFrames,
  getVideoInfo,
};
