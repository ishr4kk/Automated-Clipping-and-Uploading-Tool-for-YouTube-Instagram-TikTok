
const { execFile, spawn } = require("child_process");
const fs = require("fs/promises");
const path = require("path");
const { config } = require("./config");
const { getVideoInfo } = require("./vertical-renderer");

function findYtDlp() {
  const bundled = path.resolve(config.projectRoot, "autodownload", "yt-dlp.exe");
  return { executable: bundled, bundled };
}

function runYtDlpJson(args, { timeoutMs = 120000 } = {}) {
  return new Promise((resolve, reject) => {
    const { executable } = findYtDlp();
    execFile(executable, args, { maxBuffer: 256 * 1024 * 1024, timeout: timeoutMs }, (error, stdout) => {
      if (error) {
        reject(new Error(`yt-dlp failed: ${error.message}\n${String(error.stderr || "").slice(0, 800)}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout));
      } catch (parseError) {
        reject(new Error(`yt-dlp returned invalid JSON: ${parseError.message}`));
      }
    });
  });
}


function normalizeChannelUrl(channelUrl) {
  const trimmed = channelUrl.trim();
  const tabMatch = trimmed.replace(/\/+$/, "").match(/\/(videos|shorts|streams|playlists)$/i);
  if (tabMatch) {
    return trimmed;
  }
  return `${trimmed.replace(/\/+$/, "")}/videos`;
}


async function listChannelVideos(channelUrl, { maxEntries = config.autoVideo.maxEntries } = {}) {
  const normalizedUrl = normalizeChannelUrl(channelUrl);
  if (!/youtube\.com\/(@|channel|user|c\/)/i.test(normalizedUrl)) {
    throw new Error(`Invalid YouTube channel URL: ${channelUrl}`);
  }

  const args = [
    "--no-warnings",
    "--flat-playlist",
    "-J",
    "--playlist-end", String(maxEntries),
    normalizedUrl,
  ];

  const data = await runYtDlpJson(args, { timeoutMs: 180000 });
  const entries = Array.isArray(data?.entries) ? data.entries : [];
  return entries
    .filter((entry) => entry && typeof entry.id === "string")
    .map((entry) => ({
      id: entry.id,
      url: `https://www.youtube.com/watch?v=${entry.id}`,
      title: String(entry.title || ""),
      duration: entry.duration ? Number(entry.duration) : null,
      uploadDate: String(entry.upload_date || ""),
      channel: String(data.channel || entry.channel || ""),
    }));
}

const UNAVAILABLE_PLAYLIST_TITLE = /^\[(private video|deleted video|members only|unavailable)/i;


function isPlayableEntry(entry) {
  if (!entry || typeof entry.id !== "string") {
    return false;
  }
  return !UNAVAILABLE_PLAYLIST_TITLE.test(String(entry.title || ""));
}


async function listPlaylistVideos(playlistUrl, { maxEntries = config.autoVideo.maxEntries } = {}) {
  if (!/list=/i.test(playlistUrl)) {
    throw new Error(`Invalid YouTube playlist URL: ${playlistUrl}`);
  }

  const args = [
    "--no-warnings",
    "--flat-playlist",
    "-J",
    "--playlist-end", String(maxEntries),
    playlistUrl,
  ];

  const data = await runYtDlpJson(args, { timeoutMs: 180000 });
  const entries = Array.isArray(data?.entries) ? data.entries : [];
  return entries
    .filter(isPlayableEntry)
    .map((entry) => ({
      id: entry.id,
      url: `https://www.youtube.com/watch?v=${entry.id}`,
      title: String(entry.title || ""),
      duration: entry.duration ? Number(entry.duration) : null,
      playlistTitle: String(data.title || ""),
    }));
}


async function downloadAudioMp3(videoUrl, workDir, { cookiesFile } = {}) {
  await fs.mkdir(workDir, { recursive: true });
  const { executable } = findYtDlp();

  const buildArgs = (clientArgs) => {
    const args = [
      "--no-warnings",
      "--no-playlist",
      "-f", "ba/b",
      "-x",
      "--audio-format", "mp3",
      "--audio-quality", "0",
      "-o", path.join(workDir, "music.%(ext)s"),
    ];
    if (cookiesFile) args.push("--cookies", cookiesFile);
    if (clientArgs) args.push(...clientArgs);
    return [...args, videoUrl];
  };

  const runOnce = (args) => new Promise((resolve, reject) => {
    const child = spawn(executable, args, { windowsHide: true });
    let captured = "";
    const timeoutMs = 15 * 60 * 1000;
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("yt-dlp audio download timed out after 15 minutes."));
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      captured += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      captured += chunk.toString();
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(new Error(`yt-dlp could not start: ${error.message}`));
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code === 0) {
        resolve(captured);
      } else {
        reject(new Error(`yt-dlp audio download failed with exit code ${code}.\n${captured.slice(-800)}`));
      }
    });
  });

  try {
    await runOnce(buildArgs(null));
  } catch (error) {
    if (isBotCheckError(error)) {
      await runOnce(buildArgs(["--extractor-args", "youtube:player_client=android"]));
    } else {
      throw error;
    }
  }

  const downloaded = await matchAudioDownload(workDir);
  if (!downloaded) {
    throw new Error("Audio download finished but no music file was produced.");
  }
  return downloaded;
}


async function matchAudioDownload(workDir) {
  const entries = await fs.readdir(workDir);
  const file = entries.find((entry) => entry.startsWith("music.") && !/\.(part|ytdl|temp)$/i.test(entry));
  if (!file) {
    return null;
  }
  const audioPath = path.join(workDir, file);
  if (/\.mp3$/i.test(file)) {
    return audioPath;
  }
  const mp3Path = path.join(workDir, "music.mp3");
  await new Promise((resolve, reject) => {
    execFile("ffmpeg", ["-y", "-v", "error", "-i", audioPath, "-vn", "-c:a", "libmp3lame", "-q:a", "0", mp3Path], (error, stdout, stderr) => {
      if (error) {
        reject(new Error(`ffmpeg MP3 conversion failed: ${error.message}\n${stderr}`));
        return;
      }
      resolve();
    });
  });
  await fs.rm(audioPath, { force: true }).catch(() => {});
  return mp3Path;
}


function isBotCheckError(error) {
  return /confirm you[\u2018\u2019']re not a bot|sign in to confirm/i.test(String(error?.message || ""));
}


async function exportYoutubeCookies(profileDir, outputPath) {
  let playwright;
  try {
    playwright = require("playwright");
  } catch {
    throw new Error("Playwright is required to export YouTube session cookies.");
  }

  let context;
  try {
    context = await playwright.chromium.launchPersistentContext(profileDir, { headless: true });
    const cookies = await context.cookies();
    const lines = ["# Netscape HTTP Cookie File"];
    for (const cookie of cookies) {
      if (!/\.?(youtube\.com|google\.com|youtube-nocookie\.com|ytimg\.com|ggpht\.com)$/i.test(cookie.domain)) {
        continue;
      }
      if (!cookie.name || cookie.value === undefined) continue;


      if (cookie.name.startsWith("__Secure-") || cookie.name.startsWith("__Host-")) continue;

      const domainDot = cookie.domain.startsWith(".");
      const expires = cookie.expires > 0 ? Math.floor(cookie.expires) : 2147483647;
      const httpOnlyMarker = cookie.httpOnly ? "#HttpOnly_" : "";
      lines.push(
        `${httpOnlyMarker}${cookie.domain}\t${domainDot ? "TRUE" : "FALSE"}\t${cookie.path || "/"}\t` +
        `${cookie.secure ? "TRUE" : "FALSE"}\t${expires}\t${cookie.name}\t${cookie.value}`
      );
    }
    await fs.mkdir(path.dirname(outputPath), { recursive: true });
    await fs.writeFile(outputPath, lines.join("\n"), "utf8");
    return { count: lines.length - 1, path: outputPath };
  } finally {
    if (context) await context.close().catch(() => {});
  }
}


async function fetchVideoInfo(videoUrl, { cookiesFile } = {}) {
  const buildArgs = (clientArgs) => {
    const args = ["--no-warnings", "--skip-download", "-J"];
    if (cookiesFile) args.push("--cookies", cookiesFile);
    if (clientArgs) args.push(...clientArgs);
    return [...args, videoUrl];
  };

  let data;
  try {
    data = await runYtDlpJson(buildArgs(null), { timeoutMs: 120000 });
  } catch (error) {
    if (isBotCheckError(error)) {
      data = await runYtDlpJson(
        buildArgs(["--extractor-args", "youtube:player_client=android"]),
        { timeoutMs: 120000 }
      );
    } else {
      throw error;
    }
  }

  return {
    id: String(data.id || ""),
    url: videoUrl,
    title: String(data.title || ""),
    description: String(data.description || ""),
    duration: data.duration ? Number(data.duration) : null,
    channel: String(data.channel || data.uploader || ""),
    uploadDate: String(data.upload_date || ""),
    viewCount: data.view_count ? Number(data.view_count) : null,
  };
}


async function downloadVideo(videoUrl, workDir, { cookiesFile } = {}) {
  await fs.mkdir(workDir, { recursive: true });
  const { executable } = findYtDlp();

  const buildArgs = (clientArgs) => {



    const maxHeight = Number(config.autoVideo.maxDownloadHeight) || 0;
    const format = maxHeight > 0
      ? `bv*[height<=?${maxHeight}]+ba/b[height<=?${maxHeight}]/b`
      : "bv*+ba/b";
    const args = [
      "--no-warnings",
      "--no-playlist",
      "-f", format,
      "--merge-output-format", "mp4",
      "-o", path.join(workDir, "source.%(ext)s"),
    ];
    if (cookiesFile) args.push("--cookies", cookiesFile);
    if (clientArgs) args.push(...clientArgs);
    return [...args, videoUrl];
  };

  const runOnce = (args) => new Promise((resolve, reject) => {
    const child = spawn(executable, args, { windowsHide: true });
    let captured = "";
    const timeoutMs = 20 * 60 * 1000;
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("yt-dlp download timed out after 20 minutes."));
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      captured += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      captured += chunk.toString();
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(new Error(`yt-dlp could not start: ${error.message}`));
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code === 0) {
        resolve(captured);
      } else {
        reject(new Error(`yt-dlp download failed with exit code ${code}.\n${captured.slice(-800)}`));
      }
    });
  });

  let output;
  try {
    output = await runOnce(buildArgs(null));
  } catch (error) {
    if (isBotCheckError(error)) {
      output = await runOnce(buildArgs(["--extractor-args", "youtube:player_client=android"]));
    } else {
      throw error;
    }
  }

  const downloaded = matchDownloadedPath(output, workDir);
  if (!downloaded || !(await fs.access(downloaded).then(() => true).catch(() => false))) {
    throw new Error("Download finished but no video file was produced.");
  }
  return downloaded;
}

function matchDownloadedPath(stdout, workDir) {
  const patterns = [
    /\[Merger\] Merging formats into "([^"]+)"/,
    /\[download\] Destination: ([^\r\n]+)/,
  ];
  for (const pattern of patterns) {
    const match = stdout.match(pattern);
    if (match) {
      const candidate = match[1].trim();
      if (path.isAbsolute(candidate)) return candidate;
      return path.resolve(workDir, path.basename(candidate));
    }
  }

  return null;
}


async function validateSourceVideo(videoPath, { minDurationSeconds = 5 } = {}) {
  const info = await getVideoInfo(videoPath);
  const duration = Number(info.format?.duration) || 0;
  if (duration < minDurationSeconds) {
    throw new Error(`Downloaded source is too short (${duration.toFixed(1)}s).`);
  }
  return { duration, info };
}

async function cleanupPartialDownloads(workDir) {
  const entries = await fs.readdir(workDir).catch(() => []);
  for (const entry of entries) {
    if (/\.(part|ytdl|temp)$/i.test(entry) || entry.startsWith("source.")) {
      await fs.rm(path.join(workDir, entry), { recursive: true, force: true }).catch(() => {});
    }
  }
}

module.exports = {
  findYtDlp,
  normalizeChannelUrl,
  listChannelVideos,
  listPlaylistVideos,
  isPlayableEntry,
  fetchVideoInfo,
  downloadVideo,
  downloadAudioMp3,
  validateSourceVideo,
  cleanupPartialDownloads,
  exportYoutubeCookies,
  isBotCheckError,
};
