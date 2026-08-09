
const fs = require("fs");
const path = require("path");

function timestamp() {
  return new Date().toISOString();
}

function createLogger(logFilePath) {
  const fsSync = require("fs");
  const pathModule = require("path");
  fsSync.mkdirSync(pathModule.dirname(logFilePath), { recursive: true });
  const stream = fsSync.createWriteStream(logFilePath, { flags: "a" });

  stream.on("error", (error) => {
    console.error(`[LOGGER] cannot write ${logFilePath}: ${error.message}`);
  });

  const write = (level, message) => {
    const line = `[${timestamp()}] [${level}] ${message}`;
    console.log(line);
    if (!stream.destroyed) {
      stream.write(`${line}\n`);
    }
  };

  return {
    log: (message) => write("INFO", message),
    ok: (message) => write("OK  ", message),
    warn: (message) => write("WARN", message),
    fail: (message) => write("FAIL", message),
    close: () => {
      if (!stream.destroyed) {
        stream.end();
      }
    },
  };
}

module.exports = { createLogger, timestamp };
