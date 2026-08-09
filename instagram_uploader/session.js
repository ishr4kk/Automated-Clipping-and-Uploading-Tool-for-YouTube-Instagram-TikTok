
const { chromium } = require("playwright");
const { config } = require("./config");
const { SessionError } = require("./errors");

const SESSION_COOKIE_NAME = "sessionid";

function loadSessionId() {
  const raw = process.env.INSTAGRAMSESSIONID;
  const value = String(raw || "").trim();

  if (!value) {
    throw new SessionError(
      "INSTAGRAMSESSIONID is not set in .env — add your Instagram sessionid value " +
        "(use a logged-in browser's sessionid cookie)."
    );
  }
  if (value.includes("\n") || value.includes(" ") || value.length < 20) {
    throw new SessionError(
      "INSTAGRAMSESSIONID looks invalid (expected a long alphanumeric cookie value). Check the value in .env."
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
      domain: ".instagram.com",
      path: "/",
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
      expires: Math.floor(Date.now() / 1000) + 60 * 60 * 24 * 30,
    },
  ]);

  logger.log("Instagram session loaded from .env (value never logged)");
  return context;
}


async function assertLoggedIn(page, logger) {
  const url = page.url();
  if (/accounts\/login/i.test(url)) {
    throw new SessionError(
      "Instagram session is invalid or expired — redirected to the login page. " +
        "Re-login in a browser and put a fresh sessionid into INSTAGRAMSESSIONID in .env."
    );
  }
  const hasLoginForm = await page
    .locator("input[name='username'], input[name='password']")
    .first()
    .isVisible({ timeout: 1500 })
    .catch(() => false);
  if (hasLoginForm) {
    throw new SessionError(
      "Instagram session is invalid or expired — the login form is showing. " +
        "Re-login in a browser and put a fresh sessionid into INSTAGRAMSESSIONID in .env."
    );
  }
  const cookies = await page.context().cookies();
  const hasUserId = cookies.some(
    (c) => c.domain.includes("instagram.com") && c.name === "ds_user_id"
  );
  if (!hasUserId) {
    throw new SessionError(
      "Could not confirm the Instagram session (no authenticated cookies were issued). " +
        "Check the sessionid in .env and the network."
    );
  }
  return true;
}


async function verifySession({ context, logger }) {
  const page = await context.newPage();
  try {
    logger.log("Verifying Instagram session...");
    const response = await page.goto(config.homeUrl, {
      waitUntil: "domcontentloaded",
      timeout: config.navTimeoutMs,
    });
    if (!response) {
      throw new SessionError("Instagram did not respond (no HTTP response). Check the network.");
    }
    if (response.status() >= 500) {
      throw new SessionError(`Instagram returned HTTP ${response.status()} — service issue.`);
    }
    await page.waitForTimeout(6000);
    await assertLoggedIn(page, logger);
    logger.ok("Instagram session accepted — logged in");
    return { ok: true, detail: "session accepted" };
  } catch (error) {
    if (error instanceof SessionError) {
      throw error;
    }
    if (error.name === "TimeoutError") {
      throw new SessionError(
        "Timed out loading Instagram while verifying the session. Network issue or Instagram blocked the request."
      );
    }
    throw error;
  } finally {
    await page.close().catch(() => {});
  }
}

module.exports = { loadSessionId, launchBrowser, createSessionContext, verifySession, assertLoggedIn };
