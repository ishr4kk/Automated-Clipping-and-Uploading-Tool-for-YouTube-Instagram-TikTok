
const path = require("path");
const fs = require("fs/promises");
const { spawnSync } = require("child_process");
const { machineConfig, PLATFORMS } = require("./config");
const { ensureDirectories } = require("./src/fs-utils");
const ytDlp = require("./src/yt-dlp");
const music = require("./src/background-music");
const { generateJob } = require("./machine");
const { createLogger, timestamp } = require("./logger");

const PLATFORM_ALIASES = {
  yt: "yt",
  youtube: "yt",
  tiktok: "tiktok",
  insta: "insta",
  instagram: "insta",
};

function parseArgs(argv) {
  const args = {
    count: 1,
    keep: false,
    stopOnError: false,
    help: false,
    platforms: null,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--count") {
      const value = Number(argv[i + 1]);
      args.count = Number.isFinite(value) && value >= 1 ? Math.floor(value) : 1;
      i += 1;
    } else if (arg === "--platforms") {
      args.platforms = argv[i + 1];
      i += 1;
    } else if (arg === "--keep") {
      args.keep = true;
    } else if (arg === "--stop-on-error") {
      args.stopOnError = true;
    } else if (arg === "--help" || arg === "-h") {
      args.help = true;
    }
  }
  return args;
}

function parsePlatforms(raw) {
  if (!raw) {
    return machineConfig.platforms;
  }
  const selected = raw
    .split(",")
    .map((p) => PLATFORM_ALIASES[p.trim().toLowerCase()])
    .filter(Boolean);
  return selected.length ? selected : machineConfig.platforms;
}

async function preflight(logger) {
  logger.log("Running environment preflight...");

  if (!music.checkFfmpeg()) {
    throw new Error("ffmpeg is not installed or not in PATH.");
  }
  logger.ok("ffmpeg available");

  const ffprobe = spawnSync("ffprobe", ["-version"], { encoding: "utf8", windowsHide: true });
  if (ffprobe.status !== 0) {
    throw new Error("ffprobe is not installed or not in PATH.");
  }
  logger.ok("ffprobe available");

  const { bundled } = ytDlp.findYtDlp();
  try {
    const stat = await fs.stat(bundled);
    if (!stat.isFile()) throw new Error("not a file");
  } catch {
    throw new Error(`yt-dlp.exe not found at ${bundled}. Download it into autodownload/.`);
  }
  logger.ok(`yt-dlp available (${bundled})`);

  if (!machineConfig.openRouterApiKey) {
    logger.warn(
      "OPENROUTER_API_KEY is not configured; running WITHOUT AI " +
      "(keyword-only movie relevance, metadata-based captions). " +
      "Set it in .env (https://openrouter.ai/keys) for scene analysis and AI captions."
    );
  } else {
    logger.ok("OpenRouter API key configured");
  }

  if (!machineConfig.autoVideo.channels.length) {
    throw new Error("No source channels configured (AUTO_VIDEO_CHANNELS is empty).");
  }
  logger.ok(`${machineConfig.autoVideo.channels.length} source channel(s) configured`);

  if (!machineConfig.backgroundMusic.enabled) {
    logger.warn("Background music is disabled (BACKGROUND_MUSIC_ENABLED=false).");
  }

  const captionImage = machineConfig.autoVideo.captionImage;
  if (captionImage) {
    try {
      const stat = await fs.stat(captionImage);
      if (stat.isFile()) {
        logger.ok(`Caption image: ${captionImage}`);
      } else {
        throw new Error("not a file");
      }
    } catch {
      logger.warn(`Configured caption image not found (${captionImage}); rendering without it`);
    }
  }
}


async function sweepEmptyWorkDirs() {
  let entries = [];
  try {
    entries = await fs.readdir(machineConfig.workDir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const dirPath = path.join(machineConfig.workDir, entry.name);
    try {
      const contents = await fs.readdir(dirPath);
      if (contents.length === 0) {
        await fs.rmdir(dirPath);
        console.log(`[VS AUTO] Swept stale empty work dir: ${dirPath}`);
      }
    } catch {

    }
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.help) {
    console.log(
      "Video Generation Machine\n\n" +
      "Usage: node \"vs auto/run.js\" [options]\n\n" +
      "Options:\n" +
      "  --count N             number of videos to generate (default 1)\n" +
      "  --platforms LIST      comma-separated: yt,tiktok,insta (default: all)\n" +
      "  --keep                keep job work dirs under work/ for debugging\n" +
      "  --stop-on-error       abort after the first failed job\n" +
      "  -h, --help            show this help\n"
    );
    return 0;
  }

  const runStarted = timestamp();
  const runStamp = runStarted.replace(/[:.]/g, "-");

  await sweepEmptyWorkDirs();
  await ensureDirectories([
    ...Object.values(machineConfig.uploadDirs),
    ...Object.values(machineConfig.doneDirs),
    machineConfig.workDir,
    machineConfig.logsDir,
    machineConfig.jobsDir,
  ]);

  const consoleLogger = createLogger(path.join(machineConfig.logsDir, "run-console.log"));

  try {
    await preflight(consoleLogger);
  } catch (error) {
    consoleLogger.fail(`Preflight failed: ${error.message}`);
    consoleLogger.close();
    return 1;
  }

  const platforms = parsePlatforms(args.platforms);
  consoleLogger.log(
    `Generating ${args.count} video(s) for platforms: ${platforms.join(", ")} ` +
    `(keepWork=${args.keep}, stopOnError=${args.stopOnError})`
  );

  const results = [];
  for (let i = 0; i < args.count; i += 1) {
    const jobLogger = createLogger(path.join(machineConfig.logsDir, `run-${runStamp}-job-${i + 1}.log`));
    jobLogger.log(`Job ${i + 1}/${args.count} started`);
    const result = await generateJob({
      platforms,
      keepWork: args.keep,
      logger: jobLogger,
    });
    results.push(result);
    if (result.ok) {
      jobLogger.ok(`Job ${i + 1}/${args.count} OK (jobId=${result.jobId})`);
    } else {
      jobLogger.fail(`Job ${i + 1}/${args.count} FAILED at stage ${result.stageName || result.stage}: ${result.error}`);
    }
    jobLogger.close();
    if (!result.ok && args.stopOnError) {
      consoleLogger.fail(`Stopping after failed job ${i + 1} (--stop-on-error)`);
      break;
    }
  }

  const failures = results.filter((r) => !r.ok);
  const ok = results.filter((r) => r.ok);

  consoleLogger.log("------------------------");
  consoleLogger.log(`Run summary: ${ok.length} succeeded, ${failures.length} failed (${results.length} total)`);
  for (const result of ok) {
    const platformsDelivered = Object.keys(result.manifest?.delivered || {}).join(", ") || "none";
    consoleLogger.ok(`  ${result.jobId} -> ${platformsDelivered}`);
  }
  for (const result of failures) {
    consoleLogger.fail(`  ${result.jobId} -> stage ${result.stageName || result.stage}: ${result.error}`);
  }
  consoleLogger.close();

  return failures.length ? 1 : 0;
}

main()
  .then((code) => {
    process.exitCode = code;
  })
  .catch((error) => {
    console.error(`[VS AUTO] Fatal: ${error.message}`);
    process.exitCode = 1;
  });
