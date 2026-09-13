// Real browser checks; every run preserves its own evidence, never inside the site.
import { chromium, expect } from "@playwright/test";
import { createServer } from "node:http";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve, extname } from "node:path";

const routes = ["", "join", "games", "games/a", "games/b", "commands", "commands/status", "commands/start", "commands/stop", "commands/switch", "commands/backup", "commands/reset", "help"];
const representative = new Set(["", "games", "games/b", "commands", "commands/reset"]);
const site = resolve(process.argv[2]);
const evidence = await mkdtemp(join(tmpdir(), "wishicraft-web-browser-"));
const types = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript" };
const served = new Set([...routes.map(r => r ? `${r}/index.html` : "index.html"), "404.html", "guide.css", "guide.js"]);
const server = createServer(async (req, res) => {
  let name = new URL(req.url, "http://localhost").pathname.replace(/^\/guide\//, "/").slice(1);
  if (!name || name.endsWith("/")) name += "index.html";
  if (!served.has(name)) { res.writeHead(404); res.end(); return; }
  res.setHeader("Content-Type", types[extname(name)]);
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
    page.on("request", request => { if (!request.url().startsWith(origin)) result.errors.push(`external: ${request.url()}`); });
    for (const route of routes) {
      const url = `${origin}/guide/${route ? route + "/" : ""}`;
      await page.goto(url);
      await page.reload();
      await expect(page.locator("h1")).toHaveCount(1);
      await expect(page.locator(".breadcrumbs [aria-current='page']")).toHaveText(await page.locator("h1").innerText());
      expect(await page.locator("main").evaluate(node => getComputedStyle(node).backgroundColor)).toBe("rgb(255, 255, 255)");
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      const order = await page.locator("h1,h2,h3").evaluateAll(nodes => nodes.map(n => Number(n.tagName[1])));
      for (let i = 1; i < order.length; i++) expect(order[i] - order[i - 1]).toBeLessThanOrEqual(1);
      await page.keyboard.press("Tab");
      await expect(page.locator(".skip")).toBeFocused();
      expect(await page.locator(".skip").evaluate(n => getComputedStyle(n).outlineStyle)).toBe("solid");
      await page.keyboard.press("Enter");
      await expect(page.locator("main")).toBeFocused();
      for (const link of await page.locator("a[href^='#']:not(.skip)").all()) {
        const href = await link.getAttribute("href");
        await link.click();
        await expect(page.locator(href)).toBeVisible();
      }
      const buttons = await page.locator("article button").all();
      for (const button of buttons) {
        const text = await button.locator("..").locator("code").textContent();
        expect(text).toMatch(/^\/mc (status|start|stop|switch|backup|reset)( [a-z]+:[a-z0-9-]+)*$/);
        await button.focus();
        await page.keyboard.press("Enter");
        await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(text);
      }
      // Follow every page link in an actual browser, including parent and mutual links.
      const destinations = [...new Set(await page.locator("a:not([href^='#'])").evaluateAll(nodes => nodes.map(n => n.href)))];
      for (const destination of destinations) {
        await page.goto(url);
        const link = page.locator("a");
        const index = await link.evaluateAll((nodes, href) => nodes.findIndex(n => n.href === href), destination);
        await link.nth(index).click();
        await expect(page).toHaveURL(destination);
        await expect(page.locator("h1")).toHaveCount(1);
      }
      await page.goto(url);
      if (representative.has(route)) {
        const name = route.replaceAll("/", "-") || "home";
        await page.screenshot({ path: join(evidence, `${label}-${name}.png`), fullPage: true });
        await page.screenshot({ path: join(evidence, `${label}-${name}-top.png`) });
      }
      result.checks.push({ route: route || "/", width, height, links: destinations.length, copies: buttons.length, reload: true, overflow: false });
    }
    // Tab traversal must reach every button without programmatically focusing it.
    await page.goto(`${origin}/guide/commands/reset/`);
    const visited = new Set();
    for (let i = 0; i < 65; i++) {
      await page.keyboard.press("Tab");
      const index = await page.evaluate(() => [...document.querySelectorAll("article button")].indexOf(document.activeElement));
      if (index >= 0) visited.add(index);
    }
    expect(visited.size).toBe(await page.locator("article button").count());
    await context.close();
  }
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  for (const route of routes) {
    await page.goto(`${origin}/${route ? route + "/" : ""}`);
    await page.reload();
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("article button")).toHaveCount(0);
  }
  await context.close();
  const denied = await browser.newPage();
  await denied.goto(`${origin}/commands/reset/`);
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
