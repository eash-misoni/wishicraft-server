// Real loopback HTTP + fake OAuth + session + JSON + DOM. Every run has fresh evidence.
import { chromium, expect } from '@playwright/test';
import { spawn } from 'node:child_process';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const evidence = await mkdtemp(join(tmpdir(), 'wishicraft-foundation-browser-'));
const browser = await chromium.launch(process.argv.includes('--chrome') ? {channel: 'chrome'} : {});
const report = {evidence, browser: browser.version(), scenarios: []};
async function checkCandidatePlacement(page, candidate) {
  await page.unroute('**/api/restore-candidates**');
  const items = Array.from({length:10}, (_, index) => ({...candidate, key:`fixture-${index}`,
    games:[{...candidate.games[0], name:`Saved Game ${index}`}]}));
  let detailReads = 0, releaseDetail, holdDetail = false, detailStatus = 200;
  await page.route('**/api/restore-candidates**', async route => {
    const url = new URL(route.request().url());
    const selected = items.find(item => url.pathname.endsWith('/' + item.key));
    if (selected) {
      detailReads++;
      if (holdDetail) await new Promise(resolve => {releaseDetail = resolve;});
    }
    await route.fulfill({status:selected ? detailStatus : 200, contentType:'application/json',
      body:JSON.stringify(selected ? detailStatus === 200 ? {schema_version:1, candidate:selected} : {error:'temporarily_unavailable'} :
        {schema_version:1, items:url.search ? [items[9]] : items, next_cursor:url.search ? null : 'next-range', order:'page_time_desc', page_limit:10})});
  });
  const detail = page.locator('#candidate-detail');
  const heading = detail.locator('h3');
  const notice = detail.getByRole('status');
  for (const [width, height] of [[390,844], [320,568], [1440,1000]]) {
    await page.setViewportSize({width, height});
    await page.locator('#candidates-refresh').click();
    const cards = page.locator('#candidates-list > article');
    await expect(cards).toHaveCount(10);
    await expect(detail).toBeHidden();
    const firstButton = cards.nth(1).getByRole('button', {name:'記録の詳細', exact:true});
    const secondButton = cards.nth(7).getByRole('button', {name:'記録の詳細', exact:true});
    holdDetail = true;
    const before = detailReads;
    try {
      if (width === 320) {await firstButton.focus(); await firstButton.press('Enter');}
      else if (width === 390) await firstButton.tap();
      else await firstButton.click();
      await expect.poll(() => detailReads).toBe(before + 1);
      // Content existence alone misses results below a long list. Check ownership,
      // actual viewport intersection and focus while the response is still pending.
      await expect(cards.nth(1).locator('#candidate-detail')).toHaveCount(1);
      await expect(heading).toBeFocused();
      await expect(heading).toBeInViewport({ratio:1});
      await expect(notice).toBeInViewport({ratio:1});
      await expect(notice).toContainText('詳細を読み込み中');
      await expect(detail).toHaveAttribute('aria-busy', 'true');
      await expect(firstButton).toHaveAttribute('aria-expanded', 'true');
      await expect(secondButton).toBeDisabled();
      await expect(page.locator('#candidates-refresh')).toBeDisabled();
      await expect(page.locator('#candidates-next')).toBeDisabled();
      await firstButton.evaluate(button => {button.click(); button.click();});
      await secondButton.evaluate(button => button.click());
      expect(detailReads).toBe(before + 1);
      expect(await cards.last().evaluate(card => card.getBoundingClientRect().top > innerHeight)).toBe(true);
    } finally {holdDetail = false; releaseDetail?.();}
    await expect(notice).toContainText('保存された記録を読み直しました');
    await expect(detail).toContainText('Saved Game 1');
    await expect(detail).toHaveAttribute('aria-busy', 'false');
    await expect(heading).toBeInViewport({ratio:1});
    await expect(notice).toBeInViewport({ratio:1});
    await expect(secondButton).toBeEnabled();

    detailStatus = width === 320 ? 404 : 503;
    await secondButton.click();
    await expect(cards.nth(7).locator('#candidate-detail')).toHaveCount(1);
    await expect(firstButton).toHaveAttribute('aria-expanded', 'false');
    await expect(secondButton).toHaveAttribute('aria-expanded', 'true');
    await expect(notice).toContainText('詳細を取得できません');
    await expect(detail.locator('dl')).toHaveCount(0);
    await expect(heading).toBeFocused();
    await expect(notice).toBeInViewport({ratio:1});
    detailStatus = 200;
    await secondButton.click();
    await expect(detail).toContainText('Saved Game 7');
    await expect(detail).not.toContainText('Saved Game 1');
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await page.screenshot({path:join(evidence, `candidate-detail-${width}.png`)});
    await page.locator('#candidates-next').click();
    await expect(cards).toHaveCount(1);
    await expect(detail).toBeHidden();
    await expect(detail).toBeEmpty();
    await cards.first().getByRole('button', {name:'記録の詳細', exact:true}).click();
    await expect(detail).toContainText('Saved Game 9');
    await page.locator('#candidates-refresh').click();
    await expect(cards).toHaveCount(10);
    await expect(detail).toBeEmpty();
    await expect(detail).toBeHidden();
    await expect(page.locator('#candidates-list button[aria-expanded="true"]')).toHaveCount(0);
  }
  await page.setViewportSize({width:390, height:844});
}
try {
  for (const scenario of ['stopped', 'running', 'players', 'stale', 'unknown', 'transition']) {
    const child = spawn('tools/dev-env', ['run', '--', 'uv', 'run', 'python', '-m', 'web.local', '--port', '0', '--scenario', scenario]);
    let origin;
    try {
      origin = await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('local startup timed out')), 20000);
        child.stdout.on('data', raw => {
          const match = raw.toString().match(/http:\/\/127.0.0.1:\d+/);
          if (match) { clearTimeout(timeout); resolve(match[0]); }
        });
        child.once('exit', code => { clearTimeout(timeout); reject(new Error(`local exit ${code}`)); });
      });
      const context = await browser.newContext({viewport: {width: 390, height: 844}, hasTouch:true});
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(origin);
      await expect(page.locator('h1')).toHaveCount(1);
      expect((await context.request.get(origin + '/api/status')).status()).toBe(401);
      await page.getByRole('link', {name: '管理', exact: true}).click();
      await page.getByRole('link', {name: 'Discordでログイン', exact: true}).click();
      await expect(page.locator('#status .card')).toHaveCount(4);
      const data = await (await context.request.get(origin + '/api/status')).json();
      const expected = scenario === 'players' ? '3人' : scenario === 'running' ? '0人' :
                       scenario === 'stopped' ? '現在は観測対象外' : '不明';
      await expect(page.locator('dt').filter({hasText: /^人数$/}).locator('+ dd')).toHaveText(expected);
      if (scenario === 'transition') await expect(page.locator('#status')).toContainText('SWITCH');
      if (scenario === 'stopped') {
        // HTTP/session authorization is covered server-side; exercise candidate DOM states here.
        const candidate = {key:'U05BUFNIT1Qjc25hcC0wMDAwMDAwMA', acquired_at:'2026-09-08T01:02:03.000000Z',
          recorded_at:'2026-09-08T01:02:06.000000Z', provenance_version:2, coverage:'shared_volume',
          games:[{key:'historical-game', name:'<img src=x onerror=alert(1)>', generation:1, materialization:'MATERIALIZED'},
            {key:'other-game', name:'Other saved Game', generation:null, materialization:'UNMATERIALIZED'}],
          snapshot_presence:'unknown', restorability:'unknown'};
        await expect(page.locator('#candidates-notice')).toContainText('候補を取得できません');
        let candidateReads = 0;
        await page.route('**/api/restore-candidates**', async route => {
          candidateReads++;
          const url = new URL(route.request().url());
          await new Promise(resolve => setTimeout(resolve, 100));
          const body = url.pathname.endsWith('/' + candidate.key) ? {schema_version:1, candidate} :
            {schema_version:1, items:url.search ? [candidate] : [], next_cursor:url.search ? null : 'next-range', order:'page_time_desc', page_limit:10};
          await route.fulfill({status:200, contentType:'application/json', body:JSON.stringify(body)});
        });
        await page.locator('#candidates-refresh').evaluate(button => {button.click(); button.click();});
        await expect(page.locator('#candidates-notice')).toContainText('続きの範囲があります');
        expect(candidateReads).toBe(1);
        await page.locator('#candidates-next').click();
        await expect(page.locator('#candidates-list')).toContainText('Other saved Game');
        await expect(page.locator('#candidates-list')).toContainText('<img src=x onerror=alert(1)>');
        await expect(page.locator('#candidates-list img')).toHaveCount(0);
        await expect(page.locator('#candidates-list')).toContainText('保存時点の世代');
        await page.getByRole('button', {name:'記録の詳細', exact:true}).click();
        await expect(page.locator('#candidate-detail')).toContainText('候補記録の詳細');
        await expect(page.locator('#candidate-detail')).toContainText('記録時刻（UTC）');
        await expect(page.locator('#candidate-detail')).toContainText('未確認');
        await expect(page.locator('#candidate-detail')).toContainText('未生成の記録');
        await checkCandidatePlacement(page, candidate);
        await page.unroute('**/api/restore-candidates**');
        await page.route('**/api/restore-candidates**', route => route.fulfill({status:503, body:'{"error":"temporarily_unavailable"}'}));
        await page.locator('#candidates-refresh').click();
        await expect(page.locator('#candidates-notice')).toContainText('候補なしとは判断できません');
        await expect(page.locator('#candidates-list')).toBeEmpty();
        await expect(page.locator('#candidate-detail')).toBeEmpty();
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await page.screenshot({path: join(evidence, `${scenario}.png`), fullPage: true});
      await page.setViewportSize({width: 1440, height: 1000});
      await page.screenshot({path: join(evidence, `${scenario}-desktop.png`), fullPage: true});
      // Duplicate refresh clicks share one in-flight fetch. A read failure removes old counts.
      let requests = 0;
      await page.route('**/api/status', async route => {
        requests++; await new Promise(resolve => setTimeout(resolve, 200));
        await route.fulfill({status: 503, body: '{"error":"temporarily_unavailable"}'});
      });
      await page.locator('#refresh').evaluate(button => {button.click(); button.click();});
      await expect(page.locator('#notice')).toContainText('現在の状態・人数は不明');
      expect(requests).toBe(1);
      await expect(page.locator('#status')).toBeEmpty();
      await page.unroute('**/api/status');
      await page.getByRole('button', {name: 'ログアウト'}).click();
      await expect(page).toHaveURL(origin + '/');
      expect((await context.request.get(origin + '/api/status')).status()).toBe(401);
      expect(errors).toEqual([]);
      report.scenarios.push({scenario, players: data.players, checks: 'navigation/auth/status/responsive/failure/duplicate/logout'});
      await context.close();
    } finally { child.kill('SIGTERM'); }
  }
} finally {
  await writeFile(join(evidence, 'result.json'), JSON.stringify(report, null, 2));
  await browser.close();
  console.log(evidence);
}
