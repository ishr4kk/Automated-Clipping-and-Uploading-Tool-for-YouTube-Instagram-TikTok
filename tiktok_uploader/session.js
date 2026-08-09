
const fs = require("fs/promises");
const { chromium } = require("playwright");
const { config } = require("./config");
const { SessionError } = require("./errors");

const SESSION_COOKIE_NAME = "sessionid";

function loadSessionId() {
  const raw = process.env.TIKTOKSESSIONID;
  const value = String(raw || "").trim();

  if (!value) {
    throw new SessionError(
      "TIKTOKSESSIONID is not set in .env — add your TikTok sessionid value (profile -> Share profile -> Copy link is not a session; use a logged-in browser's sessionid cookie)."
    );
  }
  if (value.includes("\n") || value.includes("=") || value.length < 20) {
    throw new SessionError(
      "TIKTOKSESSIONID looks invalid (expected a long alphanumeric cookie value). Check the value in .env."
    );
  }
  return value;
}

async function launchBrowser(logger) {
  const failures = [];
  for (const channel of config.browserChannels) {
    const launchOptions = {
      headless: config.headless,
      args: [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1366,900",
      ],
    };
    if (channel !== "chromium") {
      launchOptions.channel = channel;
    }
    try {
      const browser = await chromium.launch(launchOptions);
      logger.log(`Browser launched (${channel}, headless=${config.headless})`);
      return browser;
    } catch (error) {
      failures.push(`${channel}: ${error.message.split("\n")[0]}`);
    }
  }
  throw new SessionError(
    `Could not launch any browser. Tried: ${failures.join(" | ")}. ` +
      "Install Chromium with: npx playwright install chromium"
  );
}

async function createSessionContext(browser, sessionId, logger) {
  const context = await browser.newContext({
    locale: config.locale,
    viewport: config.viewport,
    userAgent: config.userAgent,
  });



  await context.addCookies([
    {
      name: SESSION_COOKIE_NAME,
      value: sessionId,
      domain: ".tiktok.com",
      path: "/",
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
      expires: Math.floor(Date.now() / 1000) + 60 * 60 * 24 * 30,
    },
  ]);

  logger.log("TikTok session loaded from .env (value never logged)");
  return context;
}

async function looksLikeLoginPage(page) {
  const url = page.url();
  if (/\/login|login\/|passport\//i.test(url)) {
    return true;
  }
  for (const selector of config.selectors.loginSignals) {
    try {
      const locator = page.locator(selector).first();
      if (await locator.isVisible({ timeout: 1000 })) {
        return true;
      }
    } catch {

    }
  }
  return false;
}


async function assertLoggedIn(page, timeoutMs) {
  try {
    await page.waitForSelector("text=Select video to upload", {
      state: "visible",
      timeout: timeoutMs,
    });
    return true;
  } catch {

  }
  await page.waitForTimeout(2000);
  if (await looksLikeLoginPage(page)) {
    throw new SessionError(
      "TikTok session is invalid or expired — TikTok opened the login screen. " +
        "Re-login in a browser and put a fresh sessionid into TIKTOKSESSIONID in .env."
    );
  }
  const stillVisible = await page
    .locator("text=Select video to upload")
    .isVisible({ timeout: 1500 })
    .catch(() => false);
  if (stillVisible) return true;
  throw new SessionError(
    "Could not confirm the TikTok session: the upload page did not render. " +
      "Check the network and try again."
  );
}


async function verifySession({ context, logger, options = {} }) {
  const page = options.page || (await context.newPage());
  try {
    logger.log("Verifying TikTok session...");
    const response = await page.goto(config.uploadUrl, {
      waitUntil: "domcontentloaded",
      timeout: config.navTimeoutMs,
    });

    if (!response) {
      throw new SessionError("TikTok did not respond (no HTTP response). Check the network.");
    }
    if (response.status() >= 500) {
      throw new SessionError(`TikTok returned HTTP ${response.status()} — service issue.`);
    }


    const botText = await page
      .locator("text=Verify you are human")
      .isVisible({ timeout: 1500 })
      .catch(() => false);
    if (botText) {
      throw new SessionError(
        "TikTok is showing a bot check ('Verify you are human'). Try TIKTOK_UPLOADER_HEADLESS=false (headed browser) or a different session."
      );
    }


    await assertLoggedIn(page, 30000);


    await page.waitForLoadState("networkidle", { timeout: 30000 }).catch(() => {});
    logger.ok("TikTok session accepted — upload page ready");
    return { ok: true, detail: "session accepted", uploadPage: page };
  } catch (error) {
    if (error instanceof SessionError) {
      await page.close().catch(() => {});
      throw error;
    }
    if (error.name === "TimeoutError") {
      await page.close().catch(() => {});
      throw new SessionError(
        "Timed out loading TikTok while verifying the session. Network issue or TikTok blocked the request."
      );
    }
    await page.close().catch(() => {});
    throw error;
  }
}

module.exports = { loadSessionId, launchBrowser, createSessionContext, verifySession, assertLoggedIn, looksLikeLoginPage };
