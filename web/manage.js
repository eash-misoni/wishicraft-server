const target = document.querySelector('#status');
const notice = document.querySelector('#notice');
const button = document.querySelector('#refresh');
const labels = {unknown: '不明', not_expected: '現在は観測対象外', fresh: '新しい観測', stale: '古い観測',
  complete: '取得完了', partial: '一部不明', known: '確認済み'};
const text = value => labels[value] ?? String(value ?? '不明');
const time = value => value ? new Date(value).toLocaleString('ja-JP', {timeZoneName: 'short'}) : '不明';
function section(title, rows) {
  const card = document.createElement('section'); card.className = 'card';
  const heading = document.createElement('h2'); heading.textContent = title; card.append(heading);
  const dl = document.createElement('dl');
  for (const [name, value] of rows) {
    const dt = document.createElement('dt'); dt.textContent = name;
    const dd = document.createElement('dd'); dd.textContent = String(value); dl.append(dt, dd);
  }
  card.append(dl); target.append(card);
}
let busy = false, timer, lastSuccess = 0;
let latestStatus;
function render(s) {
  latestStatus = s;
  target.replaceChildren();
  section('状態とGame', [['Desired state', text(s.desired_state)],
    ['選択Game', s.selected_game.name ?? '不明'], ['観測Game', s.observed_game.name ?? '不明'],
    ['観測されたホスト', text(s.observed_state)], ['観測runtime', text(s.runtime_state)],
    ['Health', text(s.health)], ['最終観測時のHealth', text(s.last_observed_health)],
    ['Gameの不一致', s.game_mismatch === null ? '不明' : s.game_mismatch ? 'あり' : 'なし'],
    ['観測されたdiscrepancy', s.discrepancy === null ? '不明' : s.discrepancy ? 'あり' : 'なし']]);
  section('Minecraftと人数', [['Protocol', text(s.protocol)],
    ['人数', s.players.state === 'known' ? `${s.players.count}人` : text(s.players.state)],
    ['人数の観測時刻', time(s.players.at)],
    ['heartbeat期待', s.heartbeat.expected === null ? '不明' : s.heartbeat.expected ? 'あり' : '現在は観測対象外'],
    ['heartbeat鮮度', text(s.heartbeat.freshness)], ['heartbeat観測時刻', time(s.heartbeat.at)]]);
  const op = s.current_operation;
  section('Operation', op ? [['種類', op.type], ['状態', op.status], ['主要進捗', op.progress],
    ['更新時刻', time(op.updated_at)], ['進捗鮮度', text(op.freshness)],
    ['進行', op.terminal ? '完了済み・current参照の更新待ち' : '進行中'],
    ...op.milestones.map(m => [m.label, time(m.at)])] : [['進行中', s.operation_pending ? '取得できません' : 'なし']]);
  section('観測時刻', [['最終状態観測', time(s.observation.at)],
    ['観測鮮度', text(s.observation.freshness)], ['取得結果', text(s.quality)],
    ['表示取得時刻', time(s.generated_at)]]);
  notice.textContent = s.quality === 'partial' ? '一部の情報を確認できません。正常とは判断できません。' :
    s.operation_pending ? 'Operation進行・更新待ちです。人数は現在値として扱いません。' : '保存された観測結果です。';
}
async function refresh() {
  if (busy || document.hidden) return;
  busy = true; button.disabled = true; clearTimeout(timer);
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch('/api/status', {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
    if (response.status === 401) { target.replaceChildren(); location.assign('/manage/'); return; }
    if (!response.ok) throw new Error('unavailable');
    render(await response.json()); lastSuccess = Date.now();
  } catch {
    latestStatus = null; target.replaceChildren(); notice.textContent = '情報を取得できません。現在の状態・人数は不明です。';
  } finally {
    clearTimeout(timeout); busy = false; button.disabled = false;
    timer = setTimeout(refresh, 60000);
  }
}
button.addEventListener('click', refresh);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
setInterval(() => {
  if (lastSuccess && Date.now() - lastSuccess > 75000) {
    latestStatus = null; target.replaceChildren(); notice.textContent = '表示の更新が止まっています。現在の状態は不明です。';
  }
}, 5000);
refresh();


const opNotice = document.querySelector('#operations-notice');
const opButtons = document.querySelector('#operation-buttons');
const opForm = document.querySelector('#operation-form');
const confirmation = document.querySelector('#operation-confirmation');
const gameSelect = document.querySelector('#operation-game');
const seedSelect = document.querySelector('#operation-seed');
const checkButton = document.querySelector('#check-operation');
const retryButton = document.querySelector('#retry-operation');
const newButton = document.querySelector('#new-operation');
const storageKey = 'wishicraft-pending-operation-v1'; // Request only: no session, identity or CSRF token.
let capabilities, chosen, draft, pending, opBusy = false, opTimer, terminal = false;
try { pending = JSON.parse(localStorage.getItem(storageKey) || 'null'); } catch { pending = null; }
const opNames = {CREATE:'Gameを作成', START:'起動', STOP:'停止', SWITCH:'Game切替', BACKUP:'バックアップ', RESET:'ワールドリセット'};
const help = {
  CREATE:'persistent metadataとして登録します。EC2・Minecraftの起動、world生成は行いません。後からSTARTまたはSWITCHしてください。公開ガイドへは掲載されません。',

  START:'登録済みGameを起動します。別Gameの稼働中は切り替えません。',
  STOP:'backendが実runtimeを確認し、保存・正常停止します。選択Gameから停止対象を推測しません。',
  SWITCH:'現在のGameを保存・正常停止して対象Gameへ切り替えます。正常稼働・観測人数0が必要で、backendと停止直前のhostで再確認します。',
  BACKUP:'停止中・正常な共有Data EBS全体のSnapshotを作成します。登録済みGameを含む保護で、単一Gameだけの保存ではありません。',
  RESET:'選択中かつ稼働中の対応Game、観測人数0が必要です。地形・持ち物・位置・進捗を新しくします。旧worldの同じEBS上での保持は外部バックアップとは別で、EBS喪失時には最後の外部BACKUP以降を失い得ます。毎回Snapshotは作りません。'
};
const errors = {forbidden:'この操作の権限がありません。', invalid_input:'入力を確認してください。',
  confirmation_required:'実行内容の確認が必要です。', unsupported_capability:'このGameはReset非対応です。',
  conflict:'別の操作が進行中、または安全に受付できない状態です。', request_conflict:'この要求IDは別内容に使用済みです。',
  csrf_rejected:'セッションを確認できません。再ログイン後に同じ要求を照合してください。',
  result_unknown:'受付結果が不明です。新しい要求を作らず、同じ要求の結果を照合してください。'};
async function opFetch(path, options = {}) {
  const control = new AbortController(); const timeout = setTimeout(() => control.abort(), 15000);
  try {
    const r = await fetch(path, {credentials:'same-origin', cache:'no-store', signal:control.signal, ...options});
    if (r.status === 401) { location.assign('/manage/'); throw new Error('login'); }
    return {status:r.status, ok:r.ok, body:await r.json()};
  } finally { clearTimeout(timeout); }
}
function capabilityDetail() {
  const g = capabilities.games.find(g => g.key === gameSelect.value);
  document.querySelector('#game-capability').textContent = !g ? '' :
    `Reset ${g.reset ? '対応' : '非対応'} / 選択world: ${g.world === 'never_started' ? '未起動（Registered）' : g.world === 'managed' ? 'Resetで作成された保存領域' : '初期保存領域'} / 登録更新: ${time(g.world_updated_at)}` +
    (g.reset ? ` / 旧worldは直近${g.retain_previous}個と初期anchorを保持。それ以前は成功後に整理します。` : '');
  document.querySelector('#review-operation').disabled = chosen === 'RESET' && (!g?.reset || g?.materialized === false);
}
function choose(kind) {
  if (pending || opBusy) return;
  chosen = kind; opForm.hidden = false; confirmation.hidden = true;
  document.querySelector('#operation-title').textContent = opNames[kind];
  document.querySelector('#operation-help').textContent = help[kind];
  document.querySelector('#game-label').hidden = !['START','SWITCH','RESET'].includes(kind);
  document.querySelector('#seed-label').hidden = kind !== 'RESET';
  document.querySelector('#creation-fields').hidden = kind !== 'CREATE';
  capabilityDetail(); gameSelect.focus();
}
function renderOperation(op) {
  const result = document.querySelector('#operation-result'); result.replaceChildren();
  if (!op) { result.textContent = '記録を確認できません。進行中の要求がある場合は新しく発行せず照合してください。'; return; }
  terminal = op.terminal;
  if (pending) opNotice.textContent = terminal ? (op.status === 'SUCCEEDED' ? '操作が完了しました。' : '操作は正常完了していません。結果と現在状態を確認してください。') : op.status === 'PENDING' ? '受付済みです。進捗を追跡しています。' : '操作を実行中です。';
  const states = {PENDING:'受付済み', RUNNING:'実行中', SUCCEEDED:'完了', FAILED:'失敗', TIMED_OUT:'期限超過', CANCELLED:'中止'};
  for (const line of [`${opNames[op.type] ?? op.type} · ${states[op.status]}`, `対象: ${op.game ?? '不明'} / 実行者: ${op.actor} (${op.source})`,
    op.progress, `受付: ${time(op.requested_at)} / 更新: ${time(op.updated_at)}`,
    ...op.milestones.map(m => `${m.label}: ${time(m.at)}`),
    ...(op.error ? ['操作は正常完了していません。現在状態と管理者の確認が必要です。自動再実行はしません。'] : []),
    ...(op.cleanup_pending ? ['旧world整理は未完了です。データを保持しています。'] : [])]) {
    const p = document.createElement('p'); p.textContent = line; result.append(p);
  }
  if (pending) { newButton.hidden = !terminal; retryButton.hidden = true; }
}
async function track() {
  if (opBusy || document.hidden) return;
  opBusy = true; clearTimeout(opTimer);
  try {
    const r = await opFetch(pending ? '/api/operations/request/' + encodeURIComponent(pending.request_id) : '/api/operations/current');
    if (!r.ok) throw new Error('read');
    renderOperation(r.body.operation);
    if (r.body.operation?.type === 'CREATE' && r.body.operation.status === 'SUCCEEDED') {
      const caps = await opFetch('/api/capabilities');
      if (caps.ok) { capabilities = caps.body; renderGames(); gameSelect.replaceChildren();
        for (const g of capabilities.games) { const o = document.createElement('option'); o.value = g.key; o.textContent = gameLabel(g); gameSelect.append(o); }
      }
    }
    if (pending) {
      checkButton.hidden = false;
      retryButton.hidden = r.body.outcome !== 'not_recorded';
      if (!r.body.operation) opNotice.textContent = 'まだ受付記録を確認できません。同じ要求IDでの再送だけが可能です。';
    }
  } catch { opNotice.textContent = '結果を取得できません。同じ要求を保持しています。'; }
  finally { opBusy = false; opTimer = setTimeout(track, pending && !terminal ? 5000 : 15000); }
}
async function submit() {
  if (opBusy || !pending) return;
  opBusy = true; clearTimeout(opTimer);
  document.querySelector('#submit-operation').disabled = true; retryButton.disabled = true;
  try {
    const r = await opFetch('/api/operations', {method:'POST', headers:{'Content-Type':'application/json', 'X-CSRF-Token':capabilities.csrf_token}, body:JSON.stringify(pending)});
    opNotice.textContent = r.ok ? '受付済みです。Minecraft操作の完了は下の実行結果で確認してください。' : errors[r.body.error] || errors.result_unknown;
    if (r.body.outcome === 'rejected') { newButton.hidden = false; retryButton.hidden = true; }
    if (r.body.operation) renderOperation(r.body.operation);
  } catch { opNotice.textContent = errors.result_unknown; }
  finally { opBusy = false; retryButton.disabled = false; checkButton.hidden = false; opTimer = setTimeout(track, 1000); }
}
async function initOperations() {
  try {
    const r = await opFetch('/api/capabilities'); if (!r.ok) throw new Error('capabilities');
    capabilities = r.body;
    renderGames();
    for (const g of capabilities.games) { const o = document.createElement('option'); o.value = g.key; o.textContent = gameLabel(g); gameSelect.append(o); }
    for (const kind of capabilities.allowed) {
      const b = document.createElement('button'); b.type = 'button'; b.textContent = opNames[kind]; b.dataset.operation = kind; b.disabled = Boolean(pending);
      b.addEventListener('click', () => choose(kind)); opButtons.append(b);
    }
    opNotice.textContent = pending ? '前の要求を照合しています。' : '実行したい操作を選択してください。';
    track();
  } catch { opNotice.textContent = '操作情報を取得できません。再ログインまたは表示の再読み込みが必要です。'; }
}
opForm.addEventListener('submit', e => {
  e.preventDefault(); if (pending || opBusy) return;
  if (chosen === 'CREATE') {
    draft = {type:'CREATE', confirm:true, creation:{display_name:document.querySelector('#creation-name').value,
      seed:document.querySelector('#creation-seed').value || null, reset:document.querySelector('#creation-reset').checked}};
    document.querySelector('#confirmation-detail').textContent = `${draft.creation.display_name} / seed: ${draft.creation.seed ?? 'random（登録時に一度固定）'} / RESET: ${draft.creation.reset ? '有効。fixed seedはinitial seedと同じ。旧world直近3個とinitial anchorを保持。EBS喪失時は最後のBACKUP以降を失い得ます。' : '無効'}。${help.CREATE}`;
    confirmation.hidden = false; opForm.hidden = true; document.querySelector('#submit-operation').disabled = false;
    document.querySelector('#submit-operation').focus(); return;
  }
  draft = {type:chosen, game:['START','SWITCH','RESET'].includes(chosen) ? gameSelect.value : null, confirm:['SWITCH','RESET'].includes(chosen), seed:chosen === 'RESET' ? seedSelect.value : null};
  const g = capabilities.games.find(g => g.key === gameSelect.value);
  document.querySelector('#confirmation-detail').textContent = `${opNames[chosen]} / 観測Game: ${latestStatus?.observed_game.name ?? '不明'} → ${draft.game ? g.name : chosen === 'STOP' ? '実runtimeの正常停止' : '共有volumeのSnapshot'}。${help[chosen]} ` + (chosen === 'RESET' ? `seed: ${draft.seed}。旧worldは直近${g.retain_previous}個を保持し、それ以前は整理します。初期anchorは保持します。` : '');
  confirmation.hidden = false; opForm.hidden = true; document.querySelector('#submit-operation').disabled = false;
  document.querySelector('#submit-operation').focus();
});
document.querySelector('#submit-operation').addEventListener('click', () => {
  if (pending || opBusy) return;
  const next = {request_id:crypto.randomUUID(), ...draft};
  try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { opNotice.textContent = '要求を保存できないため送信しません。browserの保存設定を確認してください。'; return; }
  pending = next; opButtons.querySelectorAll('button').forEach(b => {b.disabled = true;}); confirmation.hidden = true; submit();
});
gameSelect.addEventListener('change', capabilityDetail);
document.querySelector('#cancel-operation').addEventListener('click', () => {opForm.hidden = true;});
document.querySelector('#back-operation').addEventListener('click', () => {confirmation.hidden = true; opForm.hidden = false;});
checkButton.addEventListener('click', track); retryButton.addEventListener('click', submit);
newButton.addEventListener('click', () => { if(opBusy) return; localStorage.removeItem(storageKey); pending = null; terminal = false; opButtons.querySelectorAll('button').forEach(b => {b.disabled = false;}); newButton.hidden = true; checkButton.hidden = true; retryButton.hidden = true; opNotice.textContent = '実行したい操作を選択してください。'; });
document.addEventListener('visibilitychange', () => {if (!document.hidden && capabilities) track();});
initOperations();

function gameLabel(g) {
  return g.name + (capabilities.games.filter(other => other.name === g.name).length > 1 ? ' · ' + g.key.slice(0, 8) : '');
}
function renderGames() {
  const list = document.querySelector('#registered-games'); list.replaceChildren();
  const counts = new Map();
  for (const g of capabilities.games) counts.set(g.name, (counts.get(g.name) || 0) + 1);
  for (const g of capabilities.games) {
    const detail = document.createElement('details');
    const title = document.createElement('summary');
    title.textContent = g.name + (counts.get(g.name) > 1 ? ' · ' + g.key.slice(0, 8) : '') +
      (g.materialized === false ? ' — Registered / Never started' : ' — 起動済み');
    detail.append(title);
    const p = document.createElement('p');
    p.textContent = `RESET: ${g.reset ? '有効' : '無効'} / Initial seed: ${g.seed ?? '既存設定'} / 保存領域: ${g.world} / ${g.selected ? '選択中' : '未選択'} / ${g.observed_running ? '最終観測で稼働中' : '稼働の観測なし'} (${time(g.observed_at)})`;
    detail.append(p);
    for (const kind of ['START', 'SWITCH']) {
      if (!capabilities.allowed.includes(kind)) continue;
      const b = document.createElement('button'); b.type = 'button'; b.textContent = opNames[kind];
      b.addEventListener('click', () => {if (pending || opBusy) return; gameSelect.value = g.key; choose(kind);}); detail.append(b);
    }
    list.append(detail);
  }
}
