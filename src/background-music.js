
const path = require("path");
const fs = require("fs/promises");
const { execFile, spawnSync } = require("child_process");
const { config } = require("./config");
const ytDlp = require("./yt-dlp");
const { getVideoInfo } = require("./vertical-renderer");

const DEFAULT_MUSIC_VOLUME = 0.35;
const DURATION_TOLERANCE_SECONDS = 0.6;

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

function shuffle(items, rng) {
  const result = [...items];
  for (let i = result.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rng() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}


function selectRandomPlaylist(playlists = config.backgroundMusic.playlists, rng = Math.random) {
  const pool = (Array.isArray(playlists) ? playlists : [])
    .map((p) => String(p).trim())
    .filter(Boolean);
  if (pool.length === 0) {
    throw new Error("No background-music playlists configured.");
  }
  const index = Math.floor(rng() * pool.length);
  return { url: pool[index], index, count: pool.length };
}


async function selectRandomPlaylistVideo(playlistUrl, {
  rng = Math.random,
  maxEntries,
  maxAttempts = 20,
  listVideos,
  entryFilter = ytDlp.isPlayableEntry,
  isPlayable,
} = {}) {
  const listFn = listVideos || ytDlp.listPlaylistVideos;
  const entries = await listFn(playlistUrl, { maxEntries });
  const candidates = (Array.isArray(entries) ? entries : []).filter(entryFilter);
  if (candidates.length === 0) {
    throw new Error("No playable music videos found in the selected playlist.");
  }

  const attempts = Math.min(Math.max(1, Number(maxAttempts) || 1), candidates.length);
  const sample = shuffle(candidates, rng).slice(0, attempts);
  const check = isPlayable || (async () => true);
  for (const candidate of sample) {
    if (await check(candidate)) {
      return { video: candidate, playlistUrl };
    }
  }

  throw new Error(`No downloadable music video found after ${attempts} attempt(s) in the selected playlist.`);
}


async function loopOrTrimMp3(inputPath, targetSeconds, outputPath) {
  const target = Number(targetSeconds);
  if (!Number.isFinite(target) || target <= 0) {
    throw new Error(`Invalid target duration for background music: ${targetSeconds}`);
  }
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await runFfmpeg([
    "-y",
    "-v", "error",
    "-stream_loop", "-1",
    "-i", inputPath,
    "-af", `atrim=0:${target},asetpts=N/SR/TB,apad`,
    "-t", String(target),
    "-c:a", "libmp3lame",
    "-q:a", "0",
    outputPath,
  ]);
}


async function mixBackgroundMusic({
  videoPath,
  musicPath,
  outputPath,
  targetDurationSeconds,
  hasOriginalAudio,
  musicVolume = config.backgroundMusic.musicVolume,
  originalVolume = 1,
}) {
  const target = Number(targetDurationSeconds);
  if (!Number.isFinite(target) || target <= 0) {
    throw new Error(`Invalid mix target duration: ${target}`);
  }
  const vol = clamp01(Number(musicVolume));

  const args = ["-y", "-v", "error", "-i", videoPath, "-stream_loop", "-1", "-i", musicPath];
  let filter;
  let mapOut;
  if (hasOriginalAudio) {
    filter =
      `[1:a]volume=${vol}[mus];` +
      `[0:a]volume=${clamp01(originalVolume)}[orig];` +
      `[orig][mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]`;
    mapOut = "[mix]";
  } else {
    filter = `[1:a]volume=${vol},apad,atrim=0:${target},asetpts=N/SR/TB[aout]`;
    mapOut = "[aout]";
  }

  args.push(
    "-filter_complex", filter,
    "-map", "0:v",
    "-map", mapOut,
    "-c:v", "copy",
    "-c:a", "aac",
    "-b:a", "160k",
    "-ar", "44100",
    "-ac", "2",
    "-t", String(target),
    "-movflags", "+faststart",
    outputPath
  );

  await runFfmpeg(args);
}

function clamp01(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return DEFAULT_MUSIC_VOLUME;
  return Math.min(1, Math.max(0, n));
}


async function buildMusicTrack({ videoUrl, workDir, targetDurationSeconds, cookiesFile } = {}) {
  const mp3Path = await ytDlp.downloadAudioMp3(videoUrl, workDir, { cookiesFile });
  const sourceInfo = await getVideoInfo(mp3Path);
  const sourceDuration = Number(sourceInfo.format?.duration) || 0;
  const finalPath = path.join(workDir, "music-final.mp3");
  await loopOrTrimMp3(mp3Path, targetDurationSeconds, finalPath);
  const finalInfo = await getVideoInfo(finalPath);
  const finalDuration = Number(finalInfo.format?.duration) || 0;
  return { mp3Path, finalPath, sourceDuration, finalDuration, targetDurationSeconds };
}


async function validateMixedOutput(outputPath, { expectedDuration, expectedHasAudio = true } = {}) {
  const resolved = path.resolve(outputPath);
  const exists = await fs.access(resolved).then(() => true).catch(() => false);
  if (!exists) {
    return { ok: false, issues: ["mixed output file does not exist"], details: null };
  }
  let info;
  try {
    info = await getVideoInfo(resolved);
  } catch {
    return { ok: false, issues: ["mixed output could not be decoded"], details: null };
  }
  const streams = Array.isArray(info?.streams) ? info.streams : [];
  const duration = Number(info.format?.duration) || 0;
  const hasAudio = Boolean(streams.find((s) => s.codec_type === "audio"));
  const issues = [];
  if (expectedHasAudio && !hasAudio) {
    issues.push("mixed output has no audio track");
  }
  if (expectedDuration && Math.abs(duration - expectedDuration) > DURATION_TOLERANCE_SECONDS) {
    issues.push(
      `mixed duration ${duration.toFixed(2)}s deviates from expected ${expectedDuration.toFixed(2)}s`
    );
  }
  return { ok: issues.length === 0, issues, details: { duration, hasAudio } };
}

function checkFfmpeg() {
  return spawnSync("ffmpeg", ["-version"], { encoding: "utf8", windowsHide: true }).status === 0;
}

module.exports = {
  checkFfmpeg,
  selectRandomPlaylist,
  selectRandomPlaylistVideo,
  loopOrTrimMp3,
  mixBackgroundMusic,
  buildMusicTrack,
  validateMixedOutput,
};
