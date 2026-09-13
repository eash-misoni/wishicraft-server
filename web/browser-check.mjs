// Real browser checks and screenshots, isolated in a fresh temporary root each run.
import { chromium, expect } from "@playwright/test";
import { createServer } from "node:http";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const site = resolve(process.argv[2]);
const evidence = await mkdtemp(join(tmpdir(), "wishicraft-web-browser-"));
const types = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript" };
const served = new Set(["index.html", "404.html", "guide.css", "guide.js"]);
const server = createServer(async (req, res) => {
  const path = new URL(req.url, "http://localhost").pathname;
  const name = path === "/" || path === "/guide/" ? "index.html" : path.replace(/^\/guide\//, "").replace(/^\//, "");
  if (!served.has(name)) { res.writeHead(404); res.end(); return; }
  res.setHeader("Content-Type", types[name.slice(name.lastIndexOf("."))]);
  res.end(await readFile(join(site, name)));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
const result = { evidence, checks: [], errors: [], browser: null };
try {
  browser = await chromium.launch(process.argv.includes("--chrome") ? { channel: "chrome" } : {});
  result.browser = browser.version();
  for (const [label, width, height] of [["mobile", 390, 844], ["narrow", 320, 740], ["desktop", 1440, 1000]]) {
    const context = await browser.newContext({ viewport: { width, height }, permissions: ["clipboard-read", "clipboard-write"] });
    const page = await context.newPage();
    page.on("pageerror", error => result.errors.push(error.message));
    page.on("requestfailed", request => result.errors.push(`request failed: ${request.url()}`));
    page.on("response", response => { if (response.status() >= 400) result.errors.push(`HTTP ${response.status()}: ${response.url()}`); });
    const external = [];
    page.on("request", request => { if (!request.url().startsWith(origin)) external.push(request.url()); });
    await page.goto(`${origin}/guide/`);
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("h2")).toHaveCount(6);
    await page.keyboard.press("Tab");
    await expect(page.locator(".skip")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("main")).toBeFocused();
    const buttonCount = await page.locator("article button").count();
    const visited = new Set();
    for (let tab = 0; tab < buttonCount + 20; tab++) {
      await page.keyboard.press("Tab");
      const index = await page.evaluate(() => [...document.querySelectorAll("article button")].indexOf(document.activeElement));
      if (index >= 0) visited.add(index);
    }
    expect(visited.size).toBe(buttonCount);
    const overflows = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    expect(overflows).toBe(false);
    for (const link of await page.locator("a[href^='#']:not(.skip)").all()) {
      const href = await link.getAttribute("href");
      await link.click();
      await expect(page.locator(href)).toBeVisible();
      expect(new URL(page.url()).hash).toBe(href);
    }
    await expect(page.getByRole("heading", { name: "B · Wishicraft Vanilla B" })).toBeVisible();
    for (const button of await page.locator("article button").all()) {
      const text = await button.locator("..").locator("code").textContent();
      await button.focus();
      await page.keyboard.press("Enter");
      await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(text);
      expect(text).not.toMatch(/[\n\r]/);
    }
    const headingOrder = await page.locator("h1, h2, h3").evaluateAll(nodes => nodes.map(node => Number(node.tagName[1])));
    for (let i = 1; i < headingOrder.length; i++) expect(headingOrder[i] - headingOrder[i - 1]).toBeLessThanOrEqual(1);
    expect(external).toEqual([]);
    await page.evaluate(() => { document.querySelector("#copy-feedback").textContent = ""; });
    await page.goto(`${origin}/guide/`);
    await page.screenshot({ path: join(evidence, `${label}-top.png`) });
    await page.screenshot({ path: join(evidence, `${label}.png`), fullPage: true });
    await page.locator("#commands").scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(evidence, `${label}-commands.png`) });
    await page.locator("#reset").scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(evidence, `${label}-reset.png`) });
    result.checks.push({ label, width, height, links: "pass", clipboard: "pass", keyboard: "pass", overflow: false, externalRequests: 0 });
    await context.close();
  }
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto(origin);
  await expect(page.locator("#reset")).toBeVisible();
  await expect(page.locator("article button")).toHaveCount(0);
  await context.close();
  const denied = await browser.newPage();
  await denied.goto(origin);
  await denied.evaluate(() => Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.reject(new Error("denied")) } }));
  await denied.locator("article button").first().click();
  await expect(denied.locator("#copy-feedback")).toContainText("コピーできませんでした");
  expect(result.errors).toEqual([]);
  result.status = "passed";
} catch (error) {
  result.status = "failed";
  result.failure = error.message;
  process.exitCode = 1;
} finally {
  await browser?.close();
  server.close();
  await writeFile(join(evidence, "result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
}
