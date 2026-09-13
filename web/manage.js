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
function render(s) {
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
    target.replaceChildren(); notice.textContent = '情報を取得できません。現在の状態・人数は不明です。';
  } finally {
    clearTimeout(timeout); busy = false; button.disabled = false;
    timer = setTimeout(refresh, 60000);
  }
}
button.addEventListener('click', refresh);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
setInterval(() => {
  if (lastSuccess && Date.now() - lastSuccess > 75000) {
    target.replaceChildren(); notice.textContent = '表示の更新が止まっています。現在の状態は不明です。';
  }
}, 5000);
refresh();
