// Real HTTP/session/CSRF/UI; local-only domain serializer and synthetic workflow outcomes.
import { chromium, expect } from '@playwright/test';
import { spawn } from 'node:child_process';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const evidence = await mkdtemp(join(tmpdir(), 'wishicraft-operations-browser-'));
const browser = await chromium.launch(process.argv.includes('--chrome') ? {channel:'chrome'} : {});
const report = {evidence, browser:browser.version(), cases:[]};
try {
  for (const [scenario, kind] of [['stopped','START'],['stopped','STOP'],['stopped','SWITCH'],['stopped','BACKUP'],['stopped','RESET'],['conflict','START'],['rejection','START'],['failure','START'],['players','SWITCH'],['player-role','START']]) {
    const child = spawn('tools/dev-env',['run','--','uv','run','python','-m','web.local','--port','0','--scenario',scenario]);
    try {
      const origin = await new Promise((resolve,reject) => {
        const timeout = setTimeout(() => reject(new Error('startup timeout')),20000);
        child.stdout.on('data',raw => {const m = raw.toString().match(/http:\/\/127.0.0.1:\d+/); if(m){clearTimeout(timeout);resolve(m[0]);}});
        child.once('exit',code => {clearTimeout(timeout);reject(new Error(`local exit ${code}`));});
      });
      const context = await browser.newContext({viewport:{width:390,height:844}});
      const page = await context.newPage(); const errors = []; page.on('pageerror',e=>errors.push(e.message));
      await page.goto(origin+'/manage/');
      await page.getByRole('link',{name:'Discordでログイン',exact:true}).click();
      await expect(page.locator(`[data-operation="${kind}"]`)).toBeVisible();
      if(scenario === 'player-role') {await expect(page.locator('[data-operation="BACKUP"]')).toHaveCount(0);await expect(page.locator('[data-operation="SWITCH"]')).toHaveCount(0);}
      await page.locator(`[data-operation="${kind}"]`).click();
      if(kind === 'RESET') {
        await expect(page.locator('#game-capability')).toContainText('Reset 非対応');
        await expect(page.locator('#review-operation')).toBeDisabled();
      }
      if(['SWITCH','RESET'].includes(kind)) await page.locator('#operation-game').selectOption({label:'Local Game 2'});
      await page.locator('#review-operation').click();
      await expect(page.locator('#operation-confirmation')).toBeVisible();
      if(kind === 'RESET') await expect(page.locator('#confirmation-detail')).toContainText('最後の外部BACKUP以降');
      let posts = 0; page.on('request',r=>{if(r.method()==='POST' && r.url().endsWith('/api/operations'))posts++;});
      await page.locator('#submit-operation').evaluate(b=>{b.click();b.click();});
      if(['conflict','rejection','players'].includes(scenario)) {
        await expect(page.locator('#operations-notice')).toContainText(scenario === 'rejection' ? '入力を確認' : '別の操作');
      } else {
        await expect(page.locator('#operations-notice')).toContainText('受付済み');
        await page.reload(); // Stable request survives response loss and refresh.
        await expect(page.locator('#operation-result')).toContainText(scenario === 'failure' ? '失敗' : '完了',{timeout:20000});
        await expect(page.locator('#new-operation')).toBeVisible();
      }
      expect(posts).toBe(1); expect(errors).toEqual([]);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
      await page.screenshot({path:join(evidence,scenario+'-'+kind+'.png'),fullPage:true});
      await page.setViewportSize({width:1440,height:1000});
      await page.screenshot({path:join(evidence,scenario+'-'+kind+'-desktop.png'),fullPage:true});
      report.cases.push({scenario,kind,posts,success:true}); await context.close();
    } finally {child.kill('SIGTERM');}
  }
} finally {await writeFile(join(evidence,'result.json'),JSON.stringify(report,null,2)); await browser.close(); console.log(evidence);}
