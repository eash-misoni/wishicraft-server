// Private local fixtures only: real session/CSRF, shared mutation and browser rendering.
import { chromium, expect } from '@playwright/test';
import { spawn } from 'node:child_process';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const evidence = await mkdtemp(join(tmpdir(), 'wishicraft-whitelist-browser-'));
const browser = await chromium.launch(process.argv.includes('--chrome') ? {channel:'chrome'} : {});
const child = spawn('tools/dev-env', ['run','--','uv','run','python','-m','web.local','--port','0','--scenario','whitelist']);
try {
  const origin = await new Promise((resolve,reject) => {
    const timeout = setTimeout(() => reject(new Error('startup timeout')), 20000);
    child.stdout.on('data', raw => {const m = raw.toString().match(/http:\/\/127.0.0.1:\d+/); if(m) {clearTimeout(timeout); resolve(m[0]);}});
    child.once('exit', code => {clearTimeout(timeout); reject(new Error(`local exit ${code}`));});
  });
  const page = await browser.newPage({viewport:{width:390,height:844}});
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin+'/manage/');
  await page.getByRole('link',{name:'Discordでログイン',exact:true}).click();
  await expect(page.locator('#common-whitelist')).toBeVisible();
  await expect(page.locator('#registered-games details')).toHaveCount(3);
  await page.locator('#common-players input').fill('FixtureOne');
  await page.getByRole('button',{name:'Commonへ追加',exact:true}).click();
  await expect(page.locator('#confirmation-detail')).toContainText('Common（全Game）');
  let posts = 0;
  page.on('request', r => {if(r.method()==='POST' && r.url().endsWith('/api/operations')) posts++;});
  await page.locator('#submit-operation').evaluate(b=>{b.click();b.click();});
  await expect(page.locator('#operation-result')).toContainText('Whitelistを保存');
  await page.reload();
  await expect(page.locator('#common-players')).toContainText('FixtureOne');
  await expect(page.locator('#registered-games')).toContainText('FixtureOne');
  expect(posts).toBe(1);
  await page.locator('#new-operation').click();
  const game = page.locator('#registered-games details').nth(2);
  await game.locator('summary').click();
  await game.locator('input').fill('FixtureOne');
  await game.getByRole('button',{name:'Game固有へ追加'}).click();
  await page.locator('#submit-operation').click();
  await expect(game).toContainText('Common ＋ Game固有');
  await page.locator('#new-operation').click();
  // Rerender closed details; reopen after the successful read-back.
  if (!(await game.evaluate(e=>e.open))) await game.locator('summary').click();
  await game.getByRole('button',{name:'Game固有から削除'}).click();
  await expect(page.locator('#confirmation-detail')).toContainText('Common由来の参加許可は残ります');
  await page.locator('#submit-operation').click();
  await expect(game.getByRole('button',{name:'Game固有から削除'})).toHaveCount(0);
  await expect(game).toContainText('FixtureOne');
  const guide = await page.request.get(origin+'/games/');
  expect(await guide.text()).not.toContain('FixtureOne');
  const caps = await page.request.get(origin+'/api/capabilities');
  expect(await caps.text()).not.toContain('11111111-1111-4111-8111-111111111111');
  expect(errors).toEqual([]);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
  await page.screenshot({path:join(evidence,'whitelist.png'),fullPage:true});
  await writeFile(join(evidence,'result.json'),JSON.stringify({success:true,posts,errors,browser:browser.version()},null,2));
} finally {child.kill('SIGTERM'); await browser.close(); console.log(evidence);}
