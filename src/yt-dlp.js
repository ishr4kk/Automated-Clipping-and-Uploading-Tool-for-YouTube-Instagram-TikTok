
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


const SOURCE_PLATFORM_DOMAINS = {
  youtube: /(^|\.)youtube\.com$|youtu\.be/i,
  tiktok: /(^|\.)tiktok\.com$/i,
  instagram: /(^|\.)instagram\.com$|instagr\.am/i,
};


function detectSourcePlatform(channelUrl) {
  const value = String(channelUrl || "").trim();
  if (/^@[\w.-]+$/i.test(value)) return "tiktok";
  if (/^[\w.-]+$/i.test(value)) return "instagram";
  const host = value.replace(/^[a-z]+:\/\//i, "").split(/[/?#]/)[0].toLowerCase();
  if (/(^|\.)youtube\.com$|^youtu\.be$/.test(host)) return "youtube";
  if (/(^|\.)tiktok\.com$/.test(host)) return "tiktok";
  if (/(^|\.)instagram\.com$|^instagr\.am$/.test(host)) return "instagram";
  return null;
}


function normalizeChannelUrl(channelUrl) {
  const trimmed = String(channelUrl || "").trim();
  const platform = detectSourcePlatform(trimmed);
  if (!platform) {
    throw new Error(
      `Unsupported source channel: ${channelUrl}. Use a YouTube channel URL, TikTok ID (e.g. @user), or Instagram ID.`
    );
  }
  if (platform === "youtube") {
    const tabMatch = trimmed.replace(/\/+$/, "").match(/\/(videos|shorts|streams|playlists)$/i);
    if (tabMatch) {
      return trimmed;
    }
    return `${trimmed.replace(/\/+$/, "")}/videos`;
  }
  if (platform === "tiktok") {
    if (/^@/i.test(trimmed)) {
      return `https://www.tiktok.com/${trimmed}`;
    }
    return trimmed.replace(/\/+$/, "");
  }
  if (/^[\w.-]+$/i.test(trimmed)) {
    return `https://www.instagram.com/${trimmed}/`;
  }
  return `${trimmed.replace(/\/+$/, "")}/`;
}


function channelHandle(channelUrl) {
  const value = String(channelUrl || "").trim();
  const platform = detectSourcePlatform(value);
  if (platform === "tiktok") {
    const match = value.match(/@([^/?#]+)/i);
    return match ? `@${match[1]}` : value;
  }
  if (platform === "instagram") {
    const segments = value.replace(/^[a-z]+:\/\//i, "").split(/[/?#]/).filter(Boolean);
    const candidate = segments.length > 1 ? segments[1] : "";
    if (candidate && !/^(reel|reels|p|tv|stories|explore|tags)$/i.test(candidate)) {
      return `@${candidate}`;
    }
    const handle = value.replace(/\/+$/, "").split(/[?#]/)[0].split("/").pop();
    return handle && !/^(reel|reels|p|tv|stories|explore|tags)$/i.test(handle) ? `@${handle}` : value;
  }
  const match = value.match(/@([^/?#]+)/i);
  return match ? match[1] : value;
}


function buildVideoUrl(platform, entry) {
  if (typeof entry.url === "string" && entry.url) {
    return entry.url;
  }
  if (platform === "youtube") {
    return `https://www.youtube.com/watch?v=${entry.id}`;
  }
  if (platform === "tiktok") {
    const handle = channelHandle(entry.channel || entry.uploader || "").replace(/^@/, "");
    return handle
      ? `https://www.tiktok.com/@${handle}/video/${entry.id}`
      : `https://www.tiktok.com/video/${entry.id}`;
  }
  return `https://www.instagram.com/reel/${entry.id}/`;
}


async function listChannelVideos(channelUrl, { maxEntries = config.autoVideo.maxEntries, cookiesFile = null } = {}) {
  const platform = detectSourcePlatform(channelUrl);
  if (!platform) {
    throw new Error(
      `Unsupported source channel: ${channelUrl}. Use a YouTube channel URL, TikTok ID, or Instagram ID.`
    );
  }
  const normalizedUrl = normalizeChannelUrl(channelUrl);

  const args = [
    "--no-warnings",
    "--flat-playlist",
    "-J",
    "--playlist-end", String(maxEntries),
  ];
  if (cookiesFile) args.push("--cookies", cookiesFile);
  args.push(normalizedUrl);

  const data = await runYtDlpJson(args, { timeoutMs: 180000 });
  const entries = Array.isArray(data?.entries) ? data.entries : [];
  return entries
    .filter((entry) => entry && typeof entry.id === "string")
    .map((entry) => ({
      id: entry.id,
      url: buildVideoUrl(platform, entry),
      title: String(entry.title || ""),
      duration: entry.duration ? Number(entry.duration) : null,
      uploadDate: String(entry.upload_date || ""),
      channel: String(data.channel || entry.channel || ""),
      platform,
    }));
}

const UNAVAILABLE_PLAYLIST_TITLE = /^\[(private video|deleted video|members only|unavailable)/i;


function isPlayableEntry(entry) {
  if (!entry || typeof entry.id !== "string") {
    return false;
  }
  return !UNAVAILABLE_PLAYLIST_TITLE.test(String(entry.title || ""));
}


function detectPlaylistPlatform(playlistUrl) {
  const value = String(playlistUrl || "").trim();
  if (/^spotify:(playlist|album):/i.test(value)) return "spotify";
  const host = value.replace(/^[a-z]+:\/\//i, "").split(/[/?#]/)[0].toLowerCase();
  if (/music\.youtube\.com$/.test(host)) return "youtube-music";
  if (/(^|\.)youtube\.com$|^youtu\.be$/.test(host)) return "youtube";
  if (/(^|\.)spotify\.com$/.test(host)) return "spotify";
  return null;
}


function normalizePlaylistUrl(playlistUrl) {
  const value = String(playlistUrl || "").trim();
  const platform = detectPlaylistPlatform(value);
  if (!platform) {
    throw new Error(
      `Unsupported background-music playlist: ${playlistUrl}. Use a YouTube, YouTube Music, or Spotify playlist URL.`
    );
  }
  if (platform === "spotify") {
    const uriMatch = value.match(/^spotify:playlist:([A-Za-z0-9]+)/i);
    const urlMatch = value.match(/spotify\.com\/(?:intl-[a-z-]+\/)?playlist\/([A-Za-z0-9]+)/i);
    const id = uriMatch ? uriMatch[1] : urlMatch ? urlMatch[1] : "";
    if (!id) {
      throw new Error(`Invalid Spotify playlist URL: ${playlistUrl}`);
    }
    return { platform, url: `https://open.spotify.com/embed/playlist/${id}`, id };
  }
  if (platform === "youtube-music") {
    if (!/list=/i.test(value)) {
      throw new Error(`Invalid YouTube Music playlist URL: ${playlistUrl}`);
    }
    return { platform, url: value, id: null };
  }
  if (!/list=/i.test(value)) {
    throw new Error(`Invalid YouTube playlist URL: ${playlistUrl}`);
  }
  return { platform, url: value, id: null };
}


function spotifySearchUrl(artist, title) {
  const query = [artist, title].filter(Boolean).join(" ").trim().slice(0, 160);
  return `ytsearch1:${query}`;
}


async function fetchSpotifyTracks(playlistId, { maxEntries = config.autoVideo.maxEntries } = {}) {
  const endpoint = `https://open.spotify.com/embed/playlist/${playlistId}`;
  const response = await fetch(endpoint, {
    headers: { "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" },
    signal: AbortSignal.timeout(30000),
  });
  if (!response.ok) {
    throw new Error(`Spotify embed request failed with HTTP ${response.status}`);
  }
  const html = await response.text();
  const jsonMatch = html.match(/<script id="__NEXT_DATA__" type="application\/json">([\s\S]*?)<\/script>/);
  if (!jsonMatch) {
    throw new Error("Spotify embed returned no track data.");
  }
  let data;
  try {
    data = JSON.parse(jsonMatch[1]);
  } catch (error) {
    throw new Error(`Spotify embed data could not be parsed: ${error.message}`);
  }
  const entity = data?.props?.pageProps?.state?.data?.entity;
  const tracks = Array.isArray(entity?.trackList) ? entity.trackList : [];
  return {
    playlistTitle: String(entity?.title || entity?.name || ""),
    entries: tracks
      .filter((track) => track && typeof track.uri === "string" && (track.title || track.subtitle))
      .slice(0, Math.max(1, Number(maxEntries) || config.autoVideo.maxEntries))
      .map((track) => ({
        id: String(track.uri.split(":").pop() || track.uri),
        url: spotifySearchUrl(String(track.subtitle || ""), String(track.title || "")),
        title: String(track.title || ""),
        artist: String(track.subtitle || ""),
        duration: track.duration ? Number(track.duration) / 1000 : null,
        spotify: true,
      })),
  };
}


async function listPlaylistVideos(playlistUrl, { maxEntries = config.autoVideo.maxEntries } = {}) {
  const { platform, url, id } = normalizePlaylistUrl(playlistUrl);

  if (platform === "spotify") {
    const spotify = await fetchSpotifyTracks(id, { maxEntries });
    return spotify.entries;
  }

  const args = [
    "--no-warnings",
    "--flat-playlist",
    "-J",
    "--playlist-end", String(maxEntries),
    url,
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
  const candidates = entries.filter(
    (entry) => entry.startsWith("music.") && !/\.(part|ytdl|temp)$/i.test(entry)
  );
  const file =
    candidates.find((entry) => /\.mp3$/i.test(entry)) ||
    candidates.find((entry) => !/\.(m4a|webm|opus|m4b|ogg)$/i.test(entry)) ||
    candidates[0];
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


const PLATFORM_COOKIE_DOMAINS = {
  youtube: /\.?(youtube\.com|youtube-nocookie\.com|youtu\.be|google\.com|ytimg\.com|ggpht\.com)$/i,
  tiktok: /\.?(tiktok\.com|musical\.ly|byteoversea\.com|bytedance\.com|snssdk\.com)$/i,
  instagram: /\.?(instagram\.com|cdninstagram\.com|instagr\.am|facebook\.com)$/i,
};


async function exportPlatformCookies(platform, profileDir, outputPath) {
  const domainPattern = PLATFORM_COOKIE_DOMAINS[platform];
  if (!domainPattern) {
    throw new Error(`No cookie domain rules for platform: ${platform}`);
  }

  let playwright;
  try {
    playwright = require("playwright");
  } catch {
    throw new Error("Playwright is required to export session cookies.");
  }

  let context;
  try {
    context = await playwright.chromium.launchPersistentContext(profileDir, { headless: true });
    const cookies = await context.cookies();
    const lines = ["# Netscape HTTP Cookie File"];
    for (const cookie of cookies) {
      if (!domainPattern.test(cookie.domain)) {
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


async function exportYoutubeCookies(profileDir, outputPath) {
  return exportPlatformCookies("youtube", profileDir, outputPath);
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

  const downloaded = await matchDownloadedPath(output, workDir);
  if (!downloaded) {
    throw new Error("Download finished but no video file was produced.");
  }
  return downloaded;
}

async function matchDownloadedPath(stdout, workDir) {
  const patterns = [
    /\[Merger\] Merging formats into "([^"]+)"/,
    /\[download\] Destination: ([^\r\n]+)/,
  ];
  for (const pattern of patterns) {
    const match = stdout.match(pattern);
    if (match) {
      const candidate = match[1].trim();
      const resolved = path.isAbsolute(candidate)
        ? candidate
        : path.resolve(workDir, path.basename(candidate));
      if (await fs.access(resolved).then(() => true).catch(() => false)) {
        return resolved;
      }
    }
  }

  const entries = await fs.readdir(workDir).catch(() => []);
  const file = entries.find(
    (entry) => entry.startsWith("source.") && !/\.(part|ytdl|temp|m4a)$/i.test(entry)
  );
  if (file) {
    return path.join(workDir, file);
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
  detectSourcePlatform,
  normalizeChannelUrl,
  channelHandle,
  detectPlaylistPlatform,
  normalizePlaylistUrl,
  fetchSpotifyTracks,
  listChannelVideos,
  listPlaylistVideos,
  isPlayableEntry,
  fetchVideoInfo,
  downloadVideo,
  downloadAudioMp3,
  validateSourceVideo,
  cleanupPartialDownloads,
  exportPlatformCookies,
  exportYoutubeCookies,
  isBotCheckError,
};
