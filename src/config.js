const path = require("path");
const dotenv = require("dotenv");




const projectRoot = path.resolve(__dirname, "..");
dotenv.config({ path: path.join(projectRoot, ".env"), override: true });

function getBoolean(value, defaultValue = false) {
  if (value === undefined || value === null || value === "") {
    return defaultValue;
  }
  return value.toString().toLowerCase() === "true";
}

function resolveOptionalProjectPath(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) {
    return "";
  }
  return path.resolve(projectRoot, trimmed);
}

const config = {
  projectRoot,
  queueDir: path.resolve(projectRoot, process.env.QUEUE_DIR || "queue/default/platform/pending"),
  postedDir: path.resolve(projectRoot, process.env.POSTED_DIR || "queue/default/platform/posted"),
  failedDir: path.resolve(projectRoot, process.env.FAILED_DIR || "queue/default/platform/failed"),
  profileDir: path.resolve(projectRoot, process.env.BROWSER_PROFILE_DIR || ".profile"),
  instagramQueueDir: path.resolve(
    projectRoot,
    process.env.INSTAGRAM_QUEUE_DIR || "queue/default/platform/pending"
  ),
  instagramPostedDir: path.resolve(
    projectRoot,
    process.env.INSTAGRAM_POSTED_DIR || "queue/default/platform/posted"
  ),
  instagramFailedDir: path.resolve(
    projectRoot,
    process.env.INSTAGRAM_FAILED_DIR || "queue/default/platform/failed"
  ),
  instagramProfileDir: path.resolve(
    projectRoot,
    process.env.INSTAGRAM_PROFILE_DIR || ".profile-instagram"
  ),
  youtubeQueueDir: path.resolve(
    projectRoot,
    process.env.YOUTUBE_QUEUE_DIR || "queue/default/platform/pending"
  ),
  youtubePostedDir: path.resolve(
    projectRoot,
    process.env.YOUTUBE_POSTED_DIR || "queue/default/platform/posted"
  ),
  youtubeFailedDir: path.resolve(
    projectRoot,
    process.env.YOUTUBE_FAILED_DIR || "queue/default/platform/failed"
  ),
  youtubeProfileDir: path.resolve(
    projectRoot,
    process.env.YOUTUBE_PROFILE_DIR || ".profile-youtube"
  ),


  postPlatforms: (process.env.POST_PLATFORMS || "tiktok,instagram,youtube")
    .split(",")
    .map((p) => p.trim().toLowerCase())
    .filter(Boolean),

  uploadPlatformOrder: (process.env.UPLOAD_PLATFORM_ORDER || "youtube,tiktok,instagram")
    .split(",")
    .map((p) => p.trim().toLowerCase())
    .filter(Boolean),

  uploadMaxAttempts: Number(process.env.UPLOAD_MAX_ATTEMPTS || 3),
  cronExpression: process.env.CRON_EXPRESSION || "0 */2 * * *",
  instagramCronExpression: process.env.INSTAGRAM_CRON_EXPRESSION || "0 */2 * * *",
  youtubeCronExpression: process.env.YOUTUBE_CRON_EXPRESSION || "0 */2 * * *",
  timezone: process.env.TZ || "UTC",
  browserLocale: process.env.BROWSER_LOCALE || "en-US",
  headless: getBoolean(process.env.HEADLESS, false),
  postDelayMs: Number(process.env.POST_DELAY_MS || 15000),
  postPublishHoldMs: Number(process.env.POST_PUBLISH_HOLD_MS || 25000),
  failureHoldMs: Number(process.env.FAILURE_HOLD_MS || 8000),
  autoAddSound: getBoolean(process.env.AUTO_ADD_SOUND, false),
  randomQueueOrder: getBoolean(process.env.RANDOM_QUEUE_ORDER, false),
  defaultSoundQuery: process.env.DEFAULT_SOUND_QUERY || "",
  defaultCaption: process.env.DEFAULT_CAPTION || "",
  uploadPageUrl:
    process.env.TIKTOK_UPLOAD_URL || "https://www.tiktok.com/tiktokstudio/upload",
  instagramUploadPageUrl:
    process.env.INSTAGRAM_UPLOAD_URL || "https://www.instagram.com/create/style/",
  youtubeUploadPageUrl:
    process.env.YOUTUBE_UPLOAD_URL || "https://studio.youtube.com",
  dashboardHost: process.env.DASHBOARD_HOST || "127.0.0.1",
  dashboardPort: Number(process.env.DASHBOARD_PORT || 3000),
  dashboardAllowRemote: getBoolean(process.env.DASHBOARD_ALLOW_REMOTE, false),
  uniquifyInputDir: path.resolve(
    projectRoot,
    process.env.UNIQUIFY_INPUT_DIR || "queue/uniquify-input"
  ),
  uniquifyOutputDir: path.resolve(
    projectRoot,
    process.env.UNIQUIFY_OUTPUT_DIR || "queue/uniquify-output"
  ),
  uniquifyLogoImage: resolveOptionalProjectPath(process.env.UNIQUIFY_LOGO_IMAGE),
  uniquifyIntroSeconds: Number(process.env.UNIQUIFY_INTRO_SECONDS || 1),
  uniquifyEndHoldSeconds: Number(process.env.UNIQUIFY_END_HOLD_SECONDS || 0.4),


  autoDownload: {
    channel: process.env.WATCH_CHANNEL || "",
    interval: Number(process.env.WATCH_INTERVAL || 10),
    maxVideos: Number(process.env.WATCH_MAX_VIDEOS || 5),
    minViews: Number(process.env.WATCH_MIN_VIEWS || 0),
    platforms: (process.env.AUTO_POST_PLATFORMS || "tiktok")
      .split(",")
      .map((p) => p.trim().toLowerCase()),
  },


  openRouterApiKey: process.env.OPENROUTER_API_KEY || "",
  openRouterBaseUrl: process.env.OPENROUTER_BASE_URL || "https://openrouter.ai/api/v1",
  openRouterModel: process.env.OPENROUTER_MODEL || "google/gemini-2.5-flash",
  openRouterFrameModel: process.env.OPENROUTER_FRAME_MODEL || "",


  autoVideo: {
    channels: (process.env.AUTO_VIDEO_CHANNELS ||
      "https://www.youtube.com/@ApexClips4k," +
      "https://www.youtube.com/@MMC4KHDR," +
      "https://www.youtube.com/@4KClipsAndTrailers," +
      "https://www.youtube.com/@FilmeyBox/videos," +
      "https://www.youtube.com/@snok_verse")
      .split(",")
      .map((c) => c.trim())
      .filter(Boolean),
    workDir: resolveOptionalProjectPath(
      process.env.AUTO_VIDEO_WORK_DIR || "queue/auto-video/work"
    ),
    outputDir: resolveOptionalProjectPath(
      process.env.AUTO_VIDEO_OUTPUT_DIR || "queue/auto-video/output"
    ),
    maxEntries: Number(process.env.AUTO_VIDEO_MAX_ENTRIES || 2000),
    maxDownloadBytes: Number(process.env.AUTO_VIDEO_MAX_DOWNLOAD_MB || 1500) * 1024 * 1024,



    maxDownloadHeight: Number(process.env.AUTO_VIDEO_MAX_DOWNLOAD_HEIGHT || 1080),


    captionImage: resolveOptionalProjectPath(
      process.env.AUTO_VIDEO_CAPTION_IMAGE || "user-assets/caption.png"
    ),



    videoCut: process.env.VIDEO_CUT || "",
    videoLengthSeconds: Number(process.env.VIDEO_LENGTH_SECONDS || 0),
  },




  backgroundMusic: {
    enabled: getBoolean(process.env.BACKGROUND_MUSIC_ENABLED, true),
    playlists: (process.env.BACKGROUND_MUSIC_PLAYLISTS ||
      "https://www.youtube.com/playlist?list=PLb5UZhE8lIP0PrpAyOr0Fa4arqcO8UDIk," +
      "https://www.youtube.com/playlist?list=PLxJLvOh-uoSeDwIR83p6jfSUdL6AoJROC")
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean),



    musicVolume: Number(process.env.BACKGROUND_MUSIC_VOLUME || 0.15),
    maxEntries: Number(process.env.BACKGROUND_MUSIC_MAX_ENTRIES || 2000),
  },


  youtubeOAuthClientSecret: resolveOptionalProjectPath(
    process.env.YOUTUBE_OAUTH_CLIENT_SECRET || "client_secret.json"
  ),
  youtubeOAuthTokenFile: resolveOptionalProjectPath(
    process.env.YOUTUBE_OAUTH_TOKEN_FILE || ".google-oauth/youtube-token.json"
  ),
  youtubePrivacyStatus: process.env.YOUTUBE_PRIVACY_STATUS || "public",
  youtubeCategoryId: process.env.YOUTUBE_CATEGORY_ID || "22",
};


config.platformQueues = {
  tiktok: config.queueDir,
  instagram: config.instagramQueueDir,
  youtube: config.youtubeQueueDir,
};

module.exports = {
  config,
};
