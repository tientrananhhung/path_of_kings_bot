'use strict';
// ---------------------------------------------------------------- tiện ích
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const fmt = (n, d = 1) => (n === null || n === undefined ? '—' : Number(n).toFixed(d));
const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.headers.get('content-type')?.includes('json') ? r.json() : r.text();
}
const post = (p, body) => api(p, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
});

// ---------------------------------------------------------------- state
const S = {
  frameW: 410, frameH: 898,
  actions: [],          // trail: {kind, points, ts, source, blocked, reason, label}
  cands: [],            // candidate_blocked gần nhất
  cfg: null,
  rulesQuery: '',       // lọc danh sách luật ở tab Game Rules
  lastState: null,
  drag: null,
};
const TRAIL_MAX = 20;
const COLORS = {
  rule: '#58a6ff', ad_step: '#ff9f43', watchdog: '#bc8cff',
  manual: '#7ee787', blocked: '#f85149',
};

// ---------------------------------------------------------------- tabs
$$('#tabs button').forEach((b) => b.onclick = () => {
  $$('#tabs button').forEach((x) => x.classList.remove('active'));
  $$('.tab').forEach((x) => x.classList.remove('active'));
  b.classList.add('active');
  $('#tab-' + b.dataset.tab).classList.add('active');
  if (b.dataset.tab === 'cap') loadCaptures();
  if (b.dataset.tab === 'sess') loadSessions();
  if (b.dataset.tab === 'set') loadDoctor();
});

// ---------------------------------------------------------------- controls
$('#btn-start').onclick = () => post('/api/control/start');
$('#btn-pause').onclick = () => post('/api/control/pause');
$('#btn-stop').onclick = () => post('/api/control/stop');
$('#btn-kill').onclick = () => { if (confirm('KILL bot ngay?')) post('/api/control/kill'); };
$('#btn-clearlog').onclick = () => { $('#log').innerHTML = ''; };

const SYSLOG_KEY = 'pok.syslog';
function syncSyslog() {
  const on = $('#opt-syslog').checked;
  $('#log-mode').textContent = on ? '— đang hiện cả log hệ thống'
                                  : '— chỉ log cần thiết (bật thêm ở tab Settings)';
  try { localStorage.setItem(SYSLOG_KEY, on ? '1' : '0'); } catch (e) { /* private mode */ }
}
try { $('#opt-syslog').checked = localStorage.getItem(SYSLOG_KEY) === '1'; }
catch (e) { /* private mode */ }
$('#opt-syslog').onchange = syncSyslog;
syncSyslog();

// ---------------------------------------------------------------- WebSocket
let ws, wsTimer;
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => setBadge('#b-conn', 'kết nối', 'ok');
  ws.onclose = () => {
    setBadge('#b-conn', 'mất kết nối', 'err');
    clearTimeout(wsTimer);
    wsTimer = setTimeout(connect, 1500);
  };
  ws.onmessage = (ev) => {
    if (ev.data instanceof ArrayBuffer) return onFrame(ev.data);
    const msg = JSON.parse(ev.data);
    if (msg.kind === 'state') onState(msg.state);
    else if (msg.kind === 'event') onEvent(msg.event);
  };
}

// Header binary 12 byte: frame_id uint32 BE + ts double BE, rồi JPEG.
let lastURL = null;
function onFrame(buf) {
  const dv = new DataView(buf);
  const fid = dv.getUint32(0, false);
  const jpg = new Blob([buf.slice(12)], { type: 'image/jpeg' });
  const url = URL.createObjectURL(jpg);
  const img = $('#frame');
  img.onload = () => {
    if (img.naturalWidth) { S.frameW = img.naturalWidth; S.frameH = img.naturalHeight; }
    sizeCanvas();
    if (lastURL) URL.revokeObjectURL(lastURL);
    lastURL = url;
  };
  img.src = url;
  img.dataset.frameId = fid;
  scheduleOverlay();
}

function setBadge(sel, text, cls) {
  const el = $(sel);
  el.textContent = text;
  el.className = 'badge' + (cls ? ' ' + cls : ' dim');
}

// ---------------------------------------------------------------- events
function onEvent(ev) {
  const t = new Date((ev.ts || Date.now() / 1000) * 1000)
    .toLocaleTimeString('vi-VN', { hour12: false });
  // "log hệ thống" = chi tiết chẩn đoán. Nguồn tự đánh dấu `sys` chứ client
  // KHÔNG đoán theo nội dung chuỗi — đổi câu chữ tiếng Việt là vỡ ngay.
  // `classify` luôn thuộc nhóm này: nó là kết quả OCR định kỳ, không phải
  // sự kiện; lúc màn hình chuyển cảnh nó chạy ~7 lần/giây.
  const heThong = ev.type === 'classify' || (ev.type === 'log' && ev.sys);
  if (heThong && !$('#opt-syslog').checked) return;

  let cls = ev.type, text = '', key = '';

  if (ev.type === 'log') { cls = ev.level; text = ev.msg; key = `log|${ev.msg}`; }
  else if (ev.type === 'state') { text = `${ev.from} → ${ev.to}  ${ev.reason || ''}`; }
  else if (ev.type === 'action') {
    text = `${ev.kind} ${ev.blocked ? 'BỊ CHẶN(' + ev.block_reason + ')' : ''} `
         + `${ev.source} · ${ev.label || ''}`;
    cls = ev.blocked ? 'blocked' : 'action';
    pushAction(ev);
  } else if (ev.type === 'candidate_blocked') {
    cls = 'blocked';
    text = `ứng viên bị chặn [${ev.reason}] ${ev.label} @(${ev.cx},${ev.cy}) `
         + `nearby=${JSON.stringify(ev.nearby)}`;
    S.cands.unshift(ev); S.cands = S.cands.slice(0, 12);
  } else if (ev.type === 'classify') {
    text = `${ev.kind} — ${ev.reason} (hf=${ev.hf}, ${ev.texts} vùng chữ)`;
    // Gộp theo kind+reason, KHÔNG theo cả dòng: hf đổi vài phần trăm mỗi lần
    // nên hai dòng liên tiếp không bao giờ giống hệt và sẽ không gộp được.
    key = `classify|${ev.kind}|${ev.reason}`;
  } else { text = JSON.stringify(ev); }

  const box = $('#log');
  const cuoi = box.lastElementChild;

  // Cùng nội dung với dòng ngay trên -> đè lên dòng đó, đếm thay vì thêm dòng.
  // Lúc màn hình đang chuyển cảnh, engine OCR lại ~7 lần/giây và log ngập.
  if (key && cuoi && cuoi.dataset.key === key) {
    cuoi.dataset.n = String(Number(cuoi.dataset.n || 1) + 1);
    cuoi.innerHTML = `<span class="t">${t}</span> ${esc(text)}`
                   + ` <span class="pill">×${cuoi.dataset.n}</span>`;
    box.scrollTop = box.scrollHeight;
    return;
  }

  const div = document.createElement('div');
  div.className = cls;
  if (key) div.dataset.key = key;
  div.innerHTML = `<span class="t">${t}</span> ${esc(text)}`;
  box.appendChild(div);
  while (box.children.length > 400) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}

function pushAction(ev) {
  S.actions.unshift({ ...ev, at: performance.now() });
  S.actions = S.actions.slice(0, TRAIL_MAX);
  scheduleOverlay();
}

// ---------------------------------------------------------------- state UI
let lastTableAt = 0;
function onState(st) {
  S.lastState = st;
  const stateCls = { PANIC: 'err', STUCK: 'warn', GAME_PLAY: 'ok', AD_CLOSING: 'warn' };
  setBadge('#b-state', `${st.state} ${fmt(st.state_seconds, 0)}s`,
    stateCls[st.state] || (st.running ? 'ok' : ''));
  setBadge('#b-kind', st.classify ? st.classify.kind : '—', '');
  setBadge('#b-fps', `${fmt(st.capture_fps)} fps`
    + (st.capture_idle ? ' (ngủ)' : ''), st.capture_idle ? 'dim' : '');
  setBadge('#b-taps', `${st.taps_per_min}/min`, st.taps_per_min > 70 ? 'warn' : '');

  // Rebuild bảng bằng innerHTML rất đắt. State về ~30 lần/giây nhưng người đọc
  // không cần hơn 4 Hz.
  const now = performance.now();
  if (now - lastTableAt < 250) return;
  lastTableAt = now;

  const w = st.window;
  kv('#kv-state', [
    ['running', `${st.running}${st.paused ? ' (paused)' : ''}`],
    ['killed', st.killed],
    ['cửa sổ', w ? `${w.name} ${w.w}x${w.h} @(${w.x},${w.y})` : '— không thấy'],
    ['frame', st.frame_id],
    ['classify', st.classify ? `${st.classify.kind} · hf=${st.classify.hf}` : '—'],
    ['ad step', st.ad_step ?? '—'],
    ['VLM', st.vlm ? `${st.vlm.loaded ? 'đã nạp' : 'chưa nạp'} · ${st.vlm.device}/${st.vlm.dtype} · ${st.vlm.last_ms}ms` : '—'],
    ['VLM lỗi', st.vlm?.load_error || '—'],
    ['capture', `${fmt(st.capture_fps)} fps · chụp ${fmt(st.capture_grab_ms)}ms`
      + (st.capture_idle ? ' · ĐANG NGỦ (không ai xem)' : '')],
    ['capture lỗi', st.capture_error || '—'],
    ['quyền', st.perm ? (st.perm.ok ? 'đủ' : 'THIẾU') : '—'],
  ]);
  const s = st.stats || {};
  kv('#kv-stats', [
    ['uptime', `${fmt(s.uptime, 0)}s`],
    ['ticks', s.ticks], ['taps', s.taps], ['swipes', s.swipes],
    ['bị chặn', s.blocked],
    ['ads thấy / đóng / trượt', `${s.ads_seen} / ${s.ads_closed} / ${s.ads_failed}`],
    ['đóng ở bước', JSON.stringify(s.closed_by_step || {})],
    ['lý do chặn', JSON.stringify(s.block_reasons || {})],
    ['watchdog', JSON.stringify(s.watchdog || {})],
    ['stuck', s.stuck],
  ]);
  if (st.stream) {
    $('#st-scale').value = st.stream.scale;
    $('#st-quality').value = st.stream.quality;
    $('#st-fps').value = st.stream.fps;
  }
}

function kv(sel, rows) {
  $(sel).innerHTML = rows.map(([k, v]) =>
    `<tr><th>${esc(k)}</th><td>${esc(v === undefined || v === null ? '—' : v)}</td></tr>`).join('');
}

// ---------------------------------------------------------------- overlay
function sizeCanvas() {
  const img = $('#frame'), cv = $('#overlay');
  const w = img.clientWidth || S.frameW;
  const h = img.clientHeight || S.frameH;
  if (cv.width === w && cv.height === h) return false;   // đừng cấp phát lại vô ích
  cv.width = w; cv.height = h;
  return true;
}

function drawOverlay() {
  const cv = $('#overlay');
  const ctx = cv.getContext('2d');
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (!$('#opt-overlay').checked) return;
  const W = cv.width, H = cv.height;
  const now = performance.now();
  const trail = $('#opt-trail').checked;
  const list = trail ? S.actions : S.actions.slice(0, 1);

  for (const a of list) {
    const age = now - a.at;
    const life = a.kind === 'swipe' ? 1200 : 800;
    let alpha = 1 - age / life;
    if (alpha <= 0) { if (!trail) continue; alpha = 0.14; }
    const color = a.blocked ? COLORS.blocked : (COLORS[a.source] || '#58a6ff');
    ctx.save();
    ctx.globalAlpha = Math.max(0.12, Math.min(1, alpha));
    ctx.strokeStyle = color; ctx.fillStyle = color;
    ctx.lineWidth = 2;

    const pts = (a.points || []).map((p) => [p[0] * W, p[1] * H]);
    if (a.kind === 'swipe' && pts.length > 1) {
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.setLineDash([6, 4]);
      ctx.lineDashOffset = -(age / 22) % 10;
      ctx.stroke();
      ctx.setLineDash([]);
      // mũi tên
      const n = pts.length - 1, p1 = pts[n], p0 = pts[Math.max(0, n - 2)];
      const ang = Math.atan2(p1[1] - p0[1], p1[0] - p0[0]);
      ctx.beginPath();
      ctx.moveTo(p1[0], p1[1]);
      ctx.lineTo(p1[0] - 10 * Math.cos(ang - 0.4), p1[1] - 10 * Math.sin(ang - 0.4));
      ctx.lineTo(p1[0] - 10 * Math.cos(ang + 0.4), p1[1] - 10 * Math.sin(ang + 0.4));
      ctx.closePath(); ctx.fill();
      ctx.beginPath(); ctx.arc(pts[0][0], pts[0][1], 4, 0, 7); ctx.fill();
      if (a.blocked) crossOut(ctx, pts[0][0], pts[0][1], 12);
      label(ctx, pts[0][0], pts[0][1] - 10, a);
    } else if (pts.length) {
      const [x, y] = pts[0];
      const r = a.kind === 'hold' ? 12 : 8 + (1 - Math.max(0, alpha)) * 16;
      ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.stroke();
      ctx.globalAlpha *= 0.45;
      ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 7); ctx.fill();
      ctx.globalAlpha = Math.max(0.12, Math.min(1, alpha));
      if (a.blocked) crossOut(ctx, x, y, 13);
      label(ctx, x, y - r - 4, a);
    }
    ctx.restore();
  }
}

// Một vòng rAF duy nhất cho cả trang. drawOverlay() KHÔNG tự schedule nữa.
let rafPending = false;
function scheduleOverlay() {
  if (rafPending) return;
  rafPending = true;
  requestAnimationFrame(() => {
    rafPending = false;
    drawOverlay();
    if (needsAnim()) scheduleOverlay();   // chỉ tiếp tục khi còn hiệu ứng mờ dần
  });
}
function needsAnim() {
  if (!$('#opt-overlay').checked || !S.actions.length) return false;
  const now = performance.now();
  return S.actions.some((a) => now - a.at < (a.kind === 'swipe' ? 1200 : 800));
}

function crossOut(ctx, x, y, r) {
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  ctx.moveTo(x - r, y - r); ctx.lineTo(x + r, y + r);
  ctx.moveTo(x - r, y + r); ctx.lineTo(x + r, y - r);
  ctx.stroke();
}

function label(ctx, x, y, a) {
  const txt = (a.blocked ? `⛔ ${a.block_reason} · ` : '') + (a.label || a.source);
  if (!txt) return;
  ctx.font = '10px -apple-system,system-ui,sans-serif';
  const w = ctx.measureText(txt).width + 8;
  const gx = Math.max(2, Math.min(ctx.canvas.width - w - 2, x - w / 2));
  ctx.globalAlpha *= 0.85;
  ctx.fillStyle = 'rgba(0,0,0,.6)';
  ctx.fillRect(gx, y - 12, w, 14);
  ctx.fillStyle = a.blocked ? COLORS.blocked : '#fff';
  ctx.fillText(txt, gx + 4, y - 2);
}

// -------------------------------------------------- click/drag lên ảnh
const vp = $('#viewport');
function relOf(e) {
  const r = $('#frame').getBoundingClientRect();
  return [
    Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
    Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
  ];
}
vp.addEventListener('mousedown', (e) => { S.drag = { from: relOf(e), t: Date.now() }; });
vp.addEventListener('mouseup', async (e) => {
  if (!S.drag) return;
  const to = relOf(e), from = S.drag.from;
  const dist = Math.hypot(to[0] - from[0], to[1] - from[1]);
  S.drag = null;
  if (window.__pickTarget) { window.__pickTarget(to); window.__pickTarget = null; return; }
  if (!$('#opt-tapmode').checked) {
    $('#vp-hint').textContent = `rel=(${to[0].toFixed(3)}, ${to[1].toFixed(3)})`;
    return;
  }
  if (dist > 0.06) {
    await post('/api/manual/swipe', { x0: from[0], y0: from[1], x1: to[0], y1: to[1], confirm: true });
  } else {
    await post('/api/manual/tap', { x: to[0], y: to[1], confirm: true });
  }
});
$('#opt-overlay').onchange = scheduleOverlay;

// Chế độ tap phải nhìn thấy rõ khi đang bật: một click lạc trên vùng ảnh sẽ
// tap thật xuống iPhone. Đã xảy ra thật trong lúc phát triển.
function syncTapMode() {
  const on = $('#opt-tapmode').checked;
  $('#lbl-tapmode').classList.toggle('armed', on);
  $('#vp-warn').textContent = on ? '⚠ click lên ảnh sẽ TAP THẬT xuống iPhone' : '';
}
$('#opt-tapmode').onchange = syncTapMode;
syncTapMode();
window.addEventListener('resize', () => { sizeCanvas(); scheduleOverlay(); });

// ---------------------------------------------------------------- config
async function loadConfig() {
  S.cfg = await api('/api/config');
  renderRules();
  renderAds();
}

// --- Game Rules ---
// Bỏ dấu tiếng Việt: gõ "ruong vang" phải tìm ra "Rương vàng end -> chọn CONTINUE".
function noDau(s) {
  return String(s).normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd').replace(/Đ/g, 'D').toLowerCase();
}

// Luật khớp khi từ khoá nằm trong TÊN, trong `when.contains` (chữ OCR phải thấy)
// hoặc trong `do.text` (chữ sẽ bấm) — ba chỗ đủ để trả lời "đã có event này chưa".
function ruleMatches(r, q) {
  if (!q) return true;
  const kho = noDau([r.name, (r.when || {}).contains, (r.do || {}).text]
    .filter(Boolean).join(' | '));
  return noDau(q).split(/\s+/).filter(Boolean).every((t) => kho.includes(t));
}

function renderRules() {
  const rules = (S.cfg.game.rule || []);
  const q = S.rulesQuery.trim();
  // GIỮ NGUYÊN index gốc trong data-idx — `rules-save` đọc DOM rồi ghi vào
  // S.cfg.game.rule[i]. Đánh số lại theo danh sách đã lọc là ghi đè nhầm luật.
  const hien = rules.map((r, i) => [r, i]).filter(([r]) => ruleMatches(r, q));
  $('#rules-count').textContent = q
    ? `${hien.length}/${rules.length} luật khớp` : `${rules.length} luật`;
  $('#rules-list').innerHTML = hien.map(([r, i]) => ruleHTML(r, i)).join('') ||
    (rules.length ? `<p class="hint">không luật nào khớp ${esc(q)} — chưa có event này</p>`
                  : '<p class="hint">chưa có luật nào</p>');
  $$('#rules-list [data-pick]').forEach((b) => b.onclick = () => {
    const [i, field] = b.dataset.pick.split(':');
    $('#vp-hint').textContent = 'click lên ảnh ở tab Dashboard để chọn điểm…';
    window.__pickTarget = (rel) => {
      const inp = $(`#rules-list [data-idx="${i}"][data-field="${field}"]`);
      if (inp) inp.value = `${rel[0].toFixed(3)}, ${rel[1].toFixed(3)}`;
      $('#vp-hint').textContent = `đã chọn (${rel[0].toFixed(3)}, ${rel[1].toFixed(3)})`;
    };
    $$('#tabs button')[0].click();
  });
  $$('#rules-list [data-del]').forEach((b) => b.onclick = () => {
    S.cfg.game.rule.splice(Number(b.dataset.del), 1);
    renderRules();
  });
}

function ruleHTML(r, i) {
  const w = r.when || {}, d = r.do || {};
  const pt = (v) => (Array.isArray(v) ? v.map((x) => Number(x).toFixed(3)).join(', ') : '');
  const pick = (f) => `<button class="mini" data-pick="${i}:${f}">chọn</button>`;
  return `<div class="rule">
    <div class="row">
      <input type="checkbox" data-idx="${i}" data-field="enabled" ${r.enabled ? 'checked' : ''}>
      <input type="text" class="name" data-idx="${i}" data-field="name" value="${esc(r.name || '')}">
      <span class="hint">priority</span>
      <input type="number" data-idx="${i}" data-field="priority" value="${r.priority ?? 50}">
      <span class="hint">cooldown_s</span>
      <input type="number" step="0.5" data-idx="${i}" data-field="cooldown_s"
             value="${r.cooldown_s ?? 2.0}">
      <label class="inline ${r.enters_ad ? 'armed' : ''}" title="Bấm/swipe cái này là chắc chắn vào xem quảng cáo -> bot chuyển sang AD_WATCHING ngay, không chờ classify tự nhận ra">
        <input type="checkbox" data-idx="${i}" data-field="enters_ad"
               ${r.enters_ad ? 'checked' : ''}> vào quảng cáo</label>
      <button class="mini danger" data-del="${i}">xoá</button>
    </div>
    <div class="row">
      <span class="hint">khi</span>
      <select data-idx="${i}" data-field="when.kind">
        ${['idle', 'color', 'template', 'text', 'always'].map((k) =>
          `<option ${w.kind === k ? 'selected' : ''}>${k}</option>`).join('')}
      </select>
      <span class="hint">seconds</span><input type="number" data-idx="${i}" data-field="when.seconds" value="${w.seconds ?? 12}">
      <span class="hint">at</span><input type="text" data-idx="${i}" data-field="when.at" value="${pt(w.at)}">${pick('when.at')}
      <span class="hint">rgb</span><input type="text" data-idx="${i}" data-field="when.rgb" value="${(w.rgb || []).join(', ')}">
      <span class="hint">tol</span><input type="number" data-idx="${i}" data-field="when.tolerance" value="${w.tolerance ?? 30}">
      <span class="hint">template</span><input type="text" data-idx="${i}" data-field="when.template" value="${esc(w.template || '')}">
      <span class="hint">min_score</span><input type="number" step="0.01" data-idx="${i}" data-field="when.min_score" value="${w.min_score ?? 0.8}">
      <span class="hint">contains</span><input type="text" data-idx="${i}" data-field="when.contains" value="${esc(w.contains || '')}">
      <span class="hint" title="Chữ phải nằm trong dải dọc này (0 = đỉnh, 1 = đáy). Để trống = cả màn hình. Dùng khi keyword cũng xuất hiện trên HUD/nav bar cố định.">y_min</span><input type="number" step="0.01" min="0" max="1" data-idx="${i}" data-field="when.y_min" value="${w.y_min ?? ''}">
      <span class="hint" title="Nav bar đáy màn hình đọc ra 'tauern | shop | pup raid | bosses | rank' -> luật 'pup raid' khớp ở MỌI màn. Tiêu đề dialog ở y/h≈0.19 nên y_max=0.5 tách được.">y_max</span><input type="number" step="0.01" min="0" max="1" data-idx="${i}" data-field="when.y_max" value="${w.y_max ?? ''}">
    </div>
    <div class="row">
      <span class="hint">làm</span>
      <select data-idx="${i}" data-field="do.action">
        ${['tap', 'tap_text', 'swipe', 'hold'].map((k) =>
          `<option ${d.action === k ? 'selected' : ''}>${k}</option>`).join('')}
      </select>
      <span class="hint">at</span><input type="text" data-idx="${i}" data-field="do.at" value="${pt(d.at)}">${pick('do.at')}
      <span class="hint">from</span><input type="text" data-idx="${i}" data-field="do.from" value="${pt(d.from)}">${pick('do.from')}
      <span class="hint">to</span><input type="text" data-idx="${i}" data-field="do.to" value="${pt(d.to)}">${pick('do.to')}
      <span class="hint">ms</span><input type="number" data-idx="${i}" data-field="do.duration_ms" value="${d.duration_ms ?? 220}">
      <span class="hint">text</span><input type="text" data-idx="${i}" data-field="do.text" value="${esc(d.text || '')}">
      <span class="hint">dy</span><input type="number" step="0.005" data-idx="${i}" data-field="do.dy" value="${d.dy ?? 0}">
    </div></div>`;
}

$('#rules-add').onclick = () => {
  S.cfg.game.rule = S.cfg.game.rule || [];
  S.cfg.game.rule.push({
    name: 'luật mới', enabled: false, priority: 50, cooldown_s: 2.0,
    enters_ad: false,
    when: { kind: 'idle', seconds: 12 }, do: { action: 'tap', at: [0.5, 0.5] },
  });
  // bộ lọc đang bật thì luật vừa thêm sẽ không khớp -> xoá lọc, nếu không
  // người dùng bấm "+ luật" mà chẳng thấy gì hiện ra
  S.rulesQuery = '';
  $('#rules-q').value = '';
  renderRules();
};

// Chỉ những field thuộc về từng loại điều kiện mới được lưu.
const WHEN_FIELDS = {
  idle: ['seconds'],
  color: ['at', 'rgb', 'tolerance'],
  template: ['template', 'region', 'min_score'],
  text: ['contains', 'y_min', 'y_max'],
  always: [],
};
const DO_FIELDS = {
  tap: ['at'], hold: ['at', 'ms'],
  tap_text: ['text', 'dy', 'hold_ms'],
  swipe: ['from', 'to', 'duration_ms', 'steps', 'hold_end_ms'],
};

// Đọc các ô đang hiện về S.cfg. Phải gọi TRƯỚC mỗi lần render lại, nếu không
// những gì vừa gõ mà chưa Lưu sẽ bay mất khi lọc danh sách.
function syncRulesFromDOM() {
  const rules = S.cfg.game.rule || [];
  $$('#rules-list [data-idx]').forEach((el) => {
    const i = Number(el.dataset.idx), f = el.dataset.field;
    if (!rules[i]) return;
    let v = el.type === 'checkbox' ? el.checked : el.value;
    if (el.type === 'number') v = Number(v);
    const parts = f.split('.');
    const isPoint = ['at', 'from', 'to'].includes(parts[parts.length - 1]);
    const isRGB = parts[parts.length - 1] === 'rgb';
    if (isPoint || isRGB) {
      const raw = String(v).trim();
      // Ô rỗng phải bị BỎ, không được thành [0]: Number('') === 0.
      const nums = raw === '' ? []
        : raw.split(',').map((x) => Number(x.trim())).filter((x) => !Number.isNaN(x));
      v = nums.length >= 2 ? nums : undefined;
    }
    if (typeof v === 'string' && v.trim() === '') v = undefined;
    let node = rules[i];
    for (const p of parts.slice(0, -1)) node = (node[p] = node[p] || {});
    if (v === undefined || v === '') delete node[parts[parts.length - 1]];
    else node[parts[parts.length - 1]] = v;
  });
}

$('#rules-q').oninput = () => {
  syncRulesFromDOM();
  S.rulesQuery = $('#rules-q').value;
  renderRules();
};

$('#rules-save').onclick = async () => {
  const rules = S.cfg.game.rule || [];
  syncRulesFromDOM();
  // Dọn field không thuộc loại điều kiện / hành động đang chọn.
  for (const r of rules) {
    const wk = (r.when || {}).kind || 'always';
    const dk = (r.do || {}).action || 'tap';
    for (const k of Object.keys(r.when || {})) {
      if (k !== 'kind' && !(WHEN_FIELDS[wk] || []).includes(k)) delete r.when[k];
    }
    for (const k of Object.keys(r.do || {})) {
      if (k !== 'action' && !(DO_FIELDS[dk] || []).includes(k)) delete r.do[k];
    }
  }
  await post('/api/config/game', S.cfg.game);
  alert('đã lưu và reload nóng');
};

// --- Ads ---
const ADS_FIELDS = [
  ['min_watch_seconds', 'number'], ['rescan_interval_s', 'number'],
  ['rescan_max_s', 'number'], ['vlm_band_top', 'number'],
  ['edge_band_pct', 'number'], ['max_area_pct', 'number'],
  ['confirm_delay_s', 'number'],
];
function renderAds() {
  const a = S.cfg.ads;
  $('#ads-form').innerHTML = ADS_FIELDS.map(([k]) =>
    `<tr><td>${k}</td><td><input id="ads-${k}" type="number" step="any" value="${a[k] ?? ''}"></td></tr>`
  ).join('') + `
    <tr><td>vlm.enabled</td><td><input id="ads-vlm-en" type="checkbox" ${a.vlm?.enabled ? 'checked' : ''}></td></tr>
    <tr><td>vlm.model</td><td><input id="ads-vlm-model" type="text" value="${esc(a.vlm?.model || '')}"></td></tr>
    <tr><td>vlm.device</td><td><input id="ads-vlm-dev" type="text" value="${esc(a.vlm?.device || 'mps')}"></td></tr>
    <tr><td>vlm.dtype</td><td><input id="ads-vlm-dt" type="text" value="${esc(a.vlm?.dtype || 'float16')}"></td></tr>
    <tr><td>vlm.beams</td><td><input id="ads-vlm-beams" type="number" value="${a.vlm?.beams ?? 1}"></td></tr>
    <tr><td>vlm.prompts</td><td><input id="ads-vlm-prompts" type="text" value="${(a.vlm?.prompts || []).join(', ')}"></td></tr>`;
  $('#ads-kw').value = (a.close_keywords || []).join('\n');
  $('#ads-ckw').value = (a.classify_keywords || []).join('\n');
  $('#ads-block').value = (a.blocklist || []).join('\n');
}
$('#ads-save').onclick = async () => {
  const a = S.cfg.ads;
  ADS_FIELDS.forEach(([k]) => { a[k] = Number($('#ads-' + k).value); });
  a.vlm = a.vlm || {};
  a.vlm.enabled = $('#ads-vlm-en').checked;
  a.vlm.model = $('#ads-vlm-model').value.trim();
  a.vlm.device = $('#ads-vlm-dev').value.trim();
  a.vlm.dtype = $('#ads-vlm-dt').value.trim();
  a.vlm.beams = Number($('#ads-vlm-beams').value);
  a.vlm.prompts = $('#ads-vlm-prompts').value.split(',').map((x) => x.trim()).filter(Boolean);
  a.close_keywords = $('#ads-kw').value.split('\n').map((x) => x.trim()).filter(Boolean);
  a.classify_keywords = $('#ads-ckw').value.split('\n').map((x) => x.trim()).filter(Boolean);
  a.blocklist = $('#ads-block').value.split('\n').map((x) => x.trim()).filter(Boolean);
  await post('/api/config/ads', a);
  alert('đã lưu');
};
$('#ads-run').onclick = () => runProbe('#ads-result', $('#ads-vlm').checked);

// ---------------------------------------------------------------- probe
$('#probe-run').onclick = () => runProbe('#probe-result', $('#probe-vlm').checked, true);

async function runProbe(target, withVlm, drawToo) {
  const el = $(target);
  el.innerHTML = '<p class="hint">đang chạy… VLM có thể mất vài giây/góc</p>';
  let r;
  try { r = await post('/api/probe', { vlm: withVlm }); }
  catch (e) { el.innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }

  const cand = (c) => `<tr>
    <td>${esc(c.label)}</td><td>${esc(c.origin)}</td>
    <td>(${c.cx}, ${c.cy})</td><td>${c.w}×${c.h}</td>
    <td>${c.blocked ? `<span class="pill blk">⛔ ${c.block_reason}</span>` : '<span class="pill ok">qua</span>'}</td>
    <td>${esc(JSON.stringify(c.nearby || []))}</td></tr>`;

  let html = `<table>
    <tr><th>frame</th><td>${r.frame_id} · ${r.size.join('×')}</td></tr>
    <tr><th>hf (mật độ cạnh)</th><td>${r.hf} · ${r.hf_ms}ms — ngưỡng 1.0, dưới là hình nền desktop</td></tr>
    <tr><th>classify</th><td><b>${r.classify.kind}</b> — ${esc(r.classify.reason)} · ${r.classify_ms}ms</td></tr>
    <tr><th>OCR</th><td>${r.texts.length} vùng chữ</td></tr>
    <tr><th>bước 2 (OCR keyword)</th><td>${r.ocr_candidates.length} ứng viên qua lọc · ${r.ocr_step_ms}ms</td></tr>
    <tr><th>bước 2b (dò dấu ✕)</th><td>${(r.icon_candidates || []).length} ứng viên qua lọc · ${r.icon_step_ms ?? '—'}ms</td></tr>
  </table>`;

  if (r.ocr_candidates.length) {
    html += `<h4>Ứng viên từ OCR</h4><table>
      <tr><th>label</th><th>origin</th><th>tâm</th><th>kt</th><th>lọc</th><th>chữ quanh</th></tr>
      ${r.ocr_candidates.map(cand).join('')}</table>`;
  }
  if (r.icon_candidates?.length) {
    html += `<h4>Bước 2b — dấu ✕ dò bằng OpenCV (quét cả frame)</h4><table>
      <tr><th>label</th><th>origin</th><th>tâm</th><th>kt</th><th>lọc</th><th>chữ quanh</th></tr>
      ${r.icon_candidates.map(cand).join('')}</table>`;
  }
  if (r.vlm?.length) {
    html += `<h4>Bước 3 — VLM trên crop góc</h4><table>
      <tr><th>góc</th><th>ms</th><th>ứng viên</th><th>chi tiết</th></tr>
      ${r.vlm.map((v) => `<tr><td>${v.corner}</td><td>${v.ms}</td>
        <td>${v.candidates.length}</td>
        <td>${v.error ? '<span class="pill blk">' + esc(v.error) + '</span>'
          : v.candidates.map((c) => `${esc(c.label)}@(${c.cx},${c.cy})`).join(', ') || '—'}</td>
        </tr>`).join('')}</table>`;
  }
  if (r.blocked?.length) {
    html += `<h4>Bị lọc an toàn chặn (${r.blocked.length})</h4><table>
      <tr><th>lý do</th><th>label</th><th>origin</th><th>tâm</th><th>chữ quanh</th></tr>
      ${r.blocked.map((b) => `<tr><td><span class="pill blk">${b.reason}</span></td>
        <td>${esc(b.label)}</td><td>${esc(b.origin)}</td>
        <td>(${b.cx}, ${b.cy})</td><td>${esc(JSON.stringify(b.nearby))}</td></tr>`).join('')}</table>`;
  }
  html += `<h4>Toàn bộ chữ OCR đọc được</h4><table>
    <tr><th>conf</th><th>tâm</th><th>text</th></tr>
    ${r.texts.map((t) => `<tr><td>${t.conf}</td><td>(${t.cx}, ${t.cy})</td>
      <td>${esc(t.text)}</td></tr>`).join('')}</table>`;
  el.innerHTML = html;

  if (drawToo) drawProbe(r);
}

function drawProbe(r) {
  const img = $('#probe-img');
  img.src = $('#frame').src;
  img.onload = () => {
    const cv = $('#probe-canvas');
    cv.width = img.clientWidth; cv.height = img.clientHeight;
    const ctx = cv.getContext('2d');
    const sx = cv.width / r.size[0], sy = cv.height / r.size[1];
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.font = '10px system-ui';
    for (const t of r.texts) {
      ctx.strokeStyle = 'rgba(88,166,255,.55)'; ctx.lineWidth = 1;
      ctx.strokeRect((t.cx - t.w / 2) * sx, (t.cy - t.h / 2) * sy, t.w * sx, t.h * sy);
    }
    const all = [...r.ocr_candidates, ...(r.icon_candidates || []),
      ...(r.vlm || []).flatMap((v) => v.candidates)];
    for (const c of all) {
      ctx.strokeStyle = c.blocked ? '#f85149' : '#3fb950';
      ctx.lineWidth = 2;
      ctx.strokeRect((c.cx - c.w / 2) * sx, (c.cy - c.h / 2) * sy, c.w * sx, c.h * sy);
      ctx.fillStyle = ctx.strokeStyle;
      ctx.fillText(`${c.label}${c.blocked ? ' ⛔' + c.block_reason : ''}`,
        (c.cx - c.w / 2) * sx, (c.cy - c.h / 2) * sy - 3);
    }
  };
}

// ---------------------------------------------------------------- capture
$('#cap-shot').onclick = async () => { await post('/api/capture/shot'); loadCaptures(); };
$('#cap-reload').onclick = loadCaptures;
const TAGS = ['', 'text_button', 'icon_only', 'countdown', 'playable', 'redirect', 'game'];

async function loadCaptures() {
  const r = await api('/api/capture/list');
  $('#cap-counts').innerHTML = Object.entries(r.counts)
    .map(([k, v]) => `<span>${esc(k)}: <b>${v}</b></span>`).join('')
    + `<span>tổng: <b>${r.items.length}</b></span>`;
  $('#cap-grid').innerHTML = r.items.map((it) => `<figure>
    <img src="/api/capture/file/${encodeURIComponent(it.name)}" loading="lazy"
         onclick="window.open(this.src)">
    <figcaption>${esc(it.name)}</figcaption>
    <select data-name="${esc(it.name)}">
      ${TAGS.map((t) => `<option value="${t}" ${it.tag === t ? 'selected' : ''}>${t || '(chưa gắn)'}</option>`).join('')}
    </select>
    <button class="mini danger" data-delcap="${esc(it.name)}">xoá</button>
  </figure>`).join('') || '<p class="hint">chưa có ảnh nào. Bấm "Chụp ngay" hoặc ⌃⌥⌘C</p>';

  $$('#cap-grid select').forEach((s) => s.onchange = () =>
    post('/api/capture/tag', { name: s.dataset.name, tag: s.value }).then(loadCaptures));
  $$('#cap-grid [data-delcap]').forEach((b) => b.onclick = () => {
    if (confirm('xoá ' + b.dataset.delcap + '?'))
      post('/api/capture/delete', { name: b.dataset.delcap }).then(loadCaptures);
  });
}

// ---------------------------------------------------------------- sessions
$('#sess-reload').onclick = loadSessions;
async function loadSessions() {
  const r = await api('/api/sessions');
  $('#sess-list').innerHTML = r.items.map((it) => {
    const s = it.stats || {};
    return `<div class="sessrow">
      <b>${esc(it.name)}</b>
      <span class="hint">${fmt(s.uptime, 0)}s</span>
      <span>ads ${s.ads_seen ?? '—'}/${s.ads_closed ?? '—'}</span>
      <span>taps ${s.taps ?? '—'}</span>
      <span>chặn ${s.blocked ?? '—'}</span>
      <span>stuck ${s.stuck ?? '—'}</span>
      <span class="hint">bước: ${esc(JSON.stringify(s.closed_by_step || {}))}</span>
      <button class="mini" data-sess="${esc(it.name)}">xem events</button>
    </div>`;
  }).join('') || '<p class="hint">chưa có phiên nào</p>';
  $$('#sess-list [data-sess]').forEach((b) => b.onclick = async () => {
    const d = await api(`/api/sessions/${encodeURIComponent(b.dataset.sess)}/events`);
    $('#sess-events').innerHTML = d.items.map((e) =>
      `<div class="${e.type === 'log' ? e.level : e.type}">${esc(JSON.stringify(e))}</div>`).join('');
  });
}

// ---------------------------------------------------------------- doctor
$('#doc-reload').onclick = loadDoctor;
async function loadDoctor() {
  const d = await api('/api/doctor');
  const w = d.window;
  kv('#kv-doctor', [
    ['Screen Recording', d.perm.screen_recording ? 'OK' : 'THIẾU'],
    ['Accessibility', d.perm.accessibility ? 'OK' : 'THIẾU'],
    ['cửa sổ', w ? `${w.name} id=${w.id} pid=${w.pid} ${w.w}x${w.h} @(${w.x},${w.y})` : 'không thấy'],
    ['scale (pixel/point)', d.scale ?? '—'],
    ['capture FPS', fmt(d.capture_fps)],
    ['capture lỗi', d.capture_error || '—'],
    ['ring buffer', d.ring],
    ['VLM', `${d.vlm.model} · ${d.vlm.device}/${d.vlm.dtype} · beams=${d.vlm.beams} · ${d.vlm.loaded ? 'đã nạp' : 'chưa nạp'}`],
    ['VLM lỗi', d.vlm.load_error || '—'],
    ['hotkey lỗi', d.hotkey_error || '—'],
  ]);
  if (!d.perm.ok) $('#kv-doctor').insertAdjacentHTML('afterend',
    `<p class="hint danger-text">${esc(d.perm.hint)}</p>`);
}

$('#st-save').onclick = async () => {
  await post('/api/stream', {
    scale: Number($('#st-scale').value),
    quality: Number($('#st-quality').value),
    fps: Number($('#st-fps').value),
  });
};

// ---------------------------------------------------------------- boot
loadConfig().catch((e) => console.error(e));
loadDoctor().catch(() => {});
connect();
