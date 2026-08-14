
const { config } = require("./config");
const { createLogger } = require("./logger");
const { SessionError, UploadError } = require("./errors");
const session = require("./session");
const uploader = require("./uploader");

function parseArgs(argv) {
  const args = { once: false, checkSession: false, delay: null };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--once") args.once = true;
    else if (arg === "--check-session") args.checkSession = true;
    else if (arg === "--delay") {
      const parsed = Number(argv[i + 1]);
      if (Number.isFinite(parsed) && parsed >= 0) args.delay = parsed;
      i += 1;
    }
  }
  return args;
}

function applyDelay(args, logger) {
  if (args.delay !== null) {
    config.delaySeconds = args.delay;
    logger.log(`Inter-video delay: ${config.delaySeconds}s (from --delay)`);
  } else if (config.delaySeconds > 0) {
    logger.log(`Inter-video delay: ${config.delaySeconds}s`);
  }
}

async function checkSession(logger) {
  const sessionId = session.loadSessionId();
  const browser = await session.launchBrowser(logger);
  try {
    const context = await session.createSessionContext(browser, sessionId, logger);
    const result = await session.verifySession({ context, logger });
    await context.close().catch(() => {});
    return result;
  } finally {
    await browser.close().catch(() => {});
  }
}

async function runOnce(logger) {
  const sessionId = session.loadSessionId();
  const browser = await session.launchBrowser(logger);
  let context = null;
  let state;
  try {
    context = await session.createSessionContext(browser, sessionId, logger);
    await session.verifySession({ context, logger });
    state = await uploader.loadState(logger);
    const result = await uploader.runCycle({ context, state, logger });
    await uploader.saveState(state);
    return result;
  } finally {
    if (context) await context.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}

async function watchForever(logger) {
  const sessionId = session.loadSessionId();
  let browser = null;
  let context = null;
  let state = await uploader.loadState(logger);
  let missingSidecarSince = {};
  let sessionBackoffUntil = 0;
  let quietCycle = false;

  logger.log("=".repeat(60));
  logger.log("Instagram Reels auto-uploader started");
  logger.log(`  Upload dir: ${config.uploadDir}`);
  logger.log(`  Done dir:   ${config.doneDir}`);
  logger.log(`  Poll:       every ${config.pollIntervalSeconds}s`);
  logger.log(`  Session:    loaded from .env (value never logged)`);
  logger.log(`  Headless:   ${config.headless}`);
  logger.log("=".repeat(60));

  const shutdown = async () => {
    logger.log("Shutting down...");
    await uploader.releaseLock().catch(() => {});
    if (context) await context.close().catch(() => {});
    if (browser) await browser.close().catch(() => {});
    logger.close();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  while (true) {
    try {
      if (!browser) {
        browser = await session.launchBrowser(logger);
        context = await session.createSessionContext(browser, sessionId, logger);
        await session.verifySession({ context, logger });
        sessionBackoffUntil = 0;
      }

      const result = await uploader.runCycle({ context, state, logger, missingSidecarSince, quiet: quietCycle });
      missingSidecarSince = result.missingSidecarSince;
      quietCycle = result.videos === 0;
      await uploader.saveState(state);
    } catch (error) {
      if (error instanceof SessionError) {
        logger.fail(`Session problem: ${error.message}`);
        sessionBackoffUntil = Date.now() + config.sessionRetryIntervalMs;
        if (context) await context.close().catch(() => {});
        if (browser) await browser.close().catch(() => {});
        context = null;
        browser = null;
        logger.warn(`Retrying session in ${config.sessionRetryIntervalMs / 1000}s...`);
        await new Promise((resolve) => setTimeout(resolve, config.sessionRetryIntervalMs));
        continue;
      }
      if (error instanceof UploadError) {
        logger.fail(`Upload problem: ${error.message}`);
      } else {
        logger.fail(`Cycle error: ${error.message}`);
      }
      await new Promise((resolve) => setTimeout(resolve, config.pollIntervalSeconds * 1000));
      continue;
    }

    const waitMs =
      sessionBackoffUntil > Date.now()
        ? sessionBackoffUntil - Date.now()
        : config.pollIntervalSeconds * 1000;
    await new Promise((resolve) => setTimeout(resolve, waitMs));
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const logger = createLogger(config.logFile);
  applyDelay(args, logger);

  if (args.checkSession) {
    const result = await checkSession(logger);
    logger.ok(`Session check passed: ${result.detail}`);
    logger.close();
    return 0;
  }

  if (args.once) {
    const locked = await uploader.acquireLock(logger);
    if (!locked) {
      logger.fail("Another uploader instance is running (lock held). Exiting.");
      logger.close();
      return 1;
    }
    try {
      const result = await runOnce(logger);
      const failed = result.processed.filter((r) => r.status !== "ok" && r.status !== "already-posted");
      logger.log(
        `Cycle finished: ${result.processed.length} handled, ${failed.length} failed, ${result.videos} video(s) in queue`
      );
      return failed.length > 0 ? 1 : 0;
    } finally {
      await uploader.releaseLock().catch(() => {});
      logger.close();
    }
  }

  const locked = await uploader.acquireLock(logger);
  if (!locked) {
    logger.fail("Another uploader instance is running (lock held). Exiting.");
    logger.close();
    return 1;
  }
  await watchForever(logger);
  return 0;
}

if (require.main === module) {
  main()
    .then((code) => process.exit(code))
    .catch(async (error) => {
      const logger = createLogger(config.logFile);
      logger.fail(`Fatal: ${error.message}`);
      logger.close();
      process.exit(1);
    });
}

module.exports = { main, parseArgs };
