import { chromium } from "playwright";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1365, height: 900 } });
const pageErrors = [];
page.on("pageerror", error => pageErrors.push(error.message));

try {
  await page.goto("http://127.0.0.1:4173/", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#nexus-runtime-status:not([hidden])");
  const status = await page.locator("#nexus-runtime-status").innerText();
  if (!status.includes("미리보기 전용")) throw new Error("Static preview mode was not identified clearly");

  await page.getByRole("button", { name: "테마 시안" }).click();
  const options = page.locator(".design-option");
  if (await options.count() !== 4) throw new Error("Expected exactly four design theme options");

  const layouts = [
    ["Modern Creator Workspace", "creator"],
    ["Global Analytics Dashboard", "global"],
    ["Executive Intelligence", "executive"],
    ["Intelligence Dashboard", "intelligence"],
  ];
  const gridSnapshots = new Map();
  for (const [label, id] of layouts) {
    const option = options.filter({ hasText: label });
    await option.getByRole("button", { name: "이 시안 적용" }).click();
    const actual = await page.locator("html").getAttribute("data-layout");
    if (actual !== id) throw new Error(`Theme selection failed: expected ${id}, received ${actual}`);
    const expectedFirstTrack = { creator: 82, executive: 220, intelligence: 250 };
    if (id === "global") {
      await page.waitForFunction(() => {
        const node = document.querySelector(".nexus-shell");
        return node && getComputedStyle(node).gridTemplateColumns.trim().split(/\s+/).length === 1;
      });
    } else {
      await page.waitForFunction(({ layout, expected }) => {
        if (document.documentElement.dataset.layout !== layout) return false;
        const node = document.querySelector(".nexus-shell");
        if (!node) return false;
        const firstTrack = parseFloat(getComputedStyle(node).gridTemplateColumns);
        return Math.abs(firstTrack - expected) < 2;
      }, { layout: id, expected: expectedFirstTrack[id] }, { timeout: 2500 });
    }
    const columns = await page.locator(".nexus-shell").evaluate(node => getComputedStyle(node).gridTemplateColumns);
    gridSnapshots.set(id, columns);
  }
  if (new Set(gridSnapshots.values()).size !== 4) {
    throw new Error("The four design themes must each produce a distinct shell layout");
  }

  await page.getByRole("button", { name: "닫기" }).click();
  await page.locator("#nexus-layout").selectOption("creator");
  await page.locator("#nexus-theme").selectOption("forest");
  if (await page.locator("html").getAttribute("data-layout") !== "creator") {
    throw new Error("Changing the color skin unexpectedly changed the design layout");
  }
  if (await page.locator("html").getAttribute("data-theme") !== "forest") {
    throw new Error("Color skin selection did not apply");
  }

  await page.getByRole("button", { name: "샘플 넣기" }).click();
  if (!(await page.locator("#nexus-sample-data").isVisible())) {
    throw new Error("Sample data panel did not become visible");
  }
  await page.getByRole("button", { name: "샘플 제거" }).click();
  if (!(await page.locator("#nexus-sample-data").evaluate(node => node.hidden))) {
    throw new Error("Sample data panel was not removed");
  }

  await page.locator('.side-nav button[data-workspace="analytics"]').click();
  if (!(await page.locator('.workspace-view[data-workspace="analytics"]').evaluate(node => node.classList.contains("active")))) {
    throw new Error("Workspace navigation did not switch to Analytics");
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("#nexus-layout").selectOption("executive");
  if (await page.locator("html").getAttribute("data-layout") !== "executive") {
    throw new Error("Mobile theme selection failed");
  }
  // Exercise the authenticated local-runtime path with a deterministic API fixture.
  const authPage = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  let expireNextOverview = false;
  const apiCalls = [];
  await authPage.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    apiCalls.push(url.pathname);
    if (url.pathname === "/api/session/status") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        required: true, configured: true, authenticated: false
      }) });
    }
    if (url.pathname === "/api/session/login") {
      return route.fulfill({ status: 200, contentType: "application/json",
        headers: { "set-cookie": "nexus_session=mock-session; Path=/; HttpOnly; SameSite=Strict" },
        body: JSON.stringify({ ok: true }) });
    }
    if (url.pathname === "/api/overview" && expireNextOverview) {
      return route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "session expired" }) });
    }
    if (url.pathname === "/api/overview") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        channels: [], jobs: [], queue_pending: 0
      }) });
    }
    if (url.pathname.startsWith("/api/radar/")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        items: [], scan: null, data_status: "not_scanned"
      }) });
    }
    if (url.pathname === "/api/ops/metrics") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        queue_by_status: {}, pipeline_by_stage: {}, sources: [], radar_scans: {}, events_last_24h: 0
      }) });
    }
    if (url.pathname === "/api/events") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  await authPage.goto("http://127.0.0.1:4173/", { waitUntil: "domcontentloaded" });
  await authPage.waitForSelector("#nexus-login-overlay:not([hidden])");
  await authPage.locator("#nexus-login-password").fill("local-test-password");
  await authPage.locator("#nexus-login-submit").click();
  await authPage.waitForFunction(() => document.getElementById("nexus-login-overlay").hidden);
  await authPage.waitForFunction(() => document.getElementById("job-list").children.length > 0, null, { timeout: 5000 });
  if (!apiCalls.includes("/api/overview")) throw new Error("Successful login did not start the overview API request");
  const sessionCookies = await authPage.context().cookies("http://127.0.0.1:4173");
  const sessionCookie = sessionCookies.find(cookie => cookie.name === "nexus_session");
  if (!sessionCookie || !sessionCookie.httpOnly || sessionCookie.sameSite !== "Strict") {
    throw new Error("Login did not retain a secure HttpOnly/SameSite session cookie");
  }
  expireNextOverview = true;
  await authPage.evaluate(() => loadOverview().catch(() => null));
  await authPage.waitForSelector("#nexus-login-overlay:not([hidden])");
  if (!apiCalls.includes("/api/session/login")) throw new Error("Login endpoint was not called");
  await authPage.close();

  if (pageErrors.length) throw new Error("Browser runtime errors: " + pageErrors.join(" | "));
  process.stdout.write(JSON.stringify({
    result: "passed",
    themes: [...gridSnapshots.keys()],
    desktopGridLayouts: Object.fromEntries(gridSnapshots),
    sampleToggle: "passed",
    appearanceIndependence: "passed",
    workspaceNavigation: "passed",
    mobileThemeSelection: "passed",
    secureLoginAndSessionExpiry: "passed",
  }, null, 2));
} finally {
  await browser.close();
}
