
const path = require("path");
const dotenv = require("dotenv");

const machineRoot = __dirname;


dotenv.config({ path: path.join(machineRoot, ".env"), override: true });


const { config: shared } = require("./src/config");

function getBoolean(value, defaultValue = false) {
  if (value === undefined || value === null || value === "") {
    return defaultValue;
  }
  return value.toString().toLowerCase() === "true";
}


const PLATFORMS = {
  yt: { folder: "yt", key: "youtube" },
  tiktok: { folder: "tiktok", key: "tiktok" },
  insta: { folder: "insta", key: "instagram" },
};

const DEFAULT_PLATFORMS = ["yt", "tiktok", "insta"];

const machineConfig = {
  root: machineRoot,
  projectRoot: machineRoot,




  uploadDirs: Object.fromEntries(
    Object.entries(PLATFORMS).map(([key, p]) => [key, path.join(machineRoot, "queue", p.folder, "upload")])
  ),
  doneDirs: Object.fromEntries(
    Object.entries(PLATFORMS).map(([key, p]) => [key, path.join(machineRoot, "queue", p.folder, "done")])
  ),

  workDir: path.join(machineRoot, "work"),
  logsDir: path.join(machineRoot, "logs"),
  jobsDir: path.join(machineRoot, "jobs"),


  platforms: (process.env.VS_MACHINE_PLATFORMS || DEFAULT_PLATFORMS.join(","))
    .split(",")
    .map((p) => p.trim().toLowerCase())
    .filter((p) => PLATFORMS[p]),


  keepWork: getBoolean(process.env.VS_MACHINE_KEEP_WORK, false),


  autoVideo: shared.autoVideo,
  backgroundMusic: shared.backgroundMusic,
  openRouterApiKey: shared.openRouterApiKey,
  openRouterBaseUrl: shared.openRouterBaseUrl,
  openRouterModel: shared.openRouterModel,
  openRouterFrameModel: shared.openRouterFrameModel,
};

module.exports = {
  machineConfig,
  PLATFORMS,
  DEFAULT_PLATFORMS,
};
