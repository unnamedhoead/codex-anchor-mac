import { App } from '@modelcontextprotocol/ext-apps';
import { STR, type Lang } from './strings';

const app = new App({ name: 'codex-anchor-mac', version: '0.1.0' });
let st: any = null;
let lang: Lang = 'en';
try { lang = (localStorage.getItem('lang') as Lang) || 'en'; } catch {}
const T = () => STR[lang] as any;

const esc = (s: unknown) => String(s).replace(/[&<>]/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c] as string));

// Codex blocks localhost even when the origin is declared
// (openai/codex#45913), so every read and write goes through the server.
async function callTool(name: string, args: Record<string, unknown> = {}) {
  const res: any = await app.callServerTool({ name, arguments: args });
  const text = res?.content?.[0]?.text ?? '{}';
  try { return JSON.parse(text); } catch { return { error: text }; }
}

async function refresh() { render(await callTool('anchor_status')); }

function matches(pmset: string, expected: string) {
  const m = pmset.match(/(\d{1,2}):(\d{2})/);
  if (!m) return false;
  const [, h, mi] = m;
  return String(h).padStart(2, '0') + ':' + mi === expected;
}

function describeState(s: any) {
  if (!s.loaded) return T().notLoaded;
  const base = s.running ? T().running : T().loaded;
  // launchctl's run counter resets whenever the agent is re-bootstrapped, so
  // the log is the only honest answer to "did it run last night".
  if (s.lastRun) return `${base} · ${s.lastRun.status} ${s.lastRun.at}`;
  return `${base} · ${T().never}`;
}

function render(s: any) {
  st = s;
  document.getElementById('time')!.textContent = s.time || T().notConfigured;
  document.getElementById('state')!.textContent = describeState(s);
  document.getElementById('state')!.className = 'v ' + (s.loaded ? 'ok' : 'bad');
  document.getElementById('wake')!.textContent =
    s.pmsetWake === 'not set' ? T().notSet : s.pmsetWake;
  document.getElementById('expected')!.textContent = s.expectedWake || '-';
  document.getElementById('tz')!.textContent = s.timezone;
  document.getElementById('localtime')!.textContent =
    s.sameClock ? T().sameZone : `${s.localTime} (${s.systemTimezone})`;
  const sel = document.getElementById('tzpick') as HTMLSelectElement;
  if (!sel.options.length) {
    sel.innerHTML = s.timezones.map((t: any) =>
      `<option value="${esc(t.name)}"${t.name === s.timezone ? ' selected' : ''}>` +
      `${esc(t.label)}</option>`).join('');
  }
  if (s.time && !(document.getElementById('picker') as HTMLInputElement).value) {
    (document.getElementById('picker') as HTMLInputElement).value = s.time;
  }
  const warn = document.getElementById('warn')!;
  const w = (s.pmsetWake || '').replace(/(AM|PM)$/i, '').trim();
  const mismatch = s.expectedWake && !matches(w, s.expectedWake);
  // Home trouble outranks the other two: a missing or stale anchor.sh means
  // the job cannot run at all, where a wake mismatch only makes it late.
  const home = s.home || {};
  const homeBroken = home.versionDrift || home.scriptPresent === false;
  warn.textContent = homeBroken ? '⚠️ ' + home.summary
    : s.drifted ? '⚠️ ' + T().warnDrift(s.systemTimezone)
    : mismatch ? '⚠️ ' + T().warnWake : '';
  const fix = document.getElementById('fixhome') as HTMLButtonElement;
  fix.style.display = homeBroken ? '' : 'none';
  warn.className = 'note bad';
  const t = document.getElementById('toggle') as HTMLButtonElement;
  t.textContent = s.loaded ? T().disable : T().enable;
  document.getElementById('log')!.textContent = s.runs.length
    ? s.runs.join('\n') : T().noRuns;
}

function applyLang() {
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  for (const el of Array.from(document.querySelectorAll('[data-i18n]'))) {
    const v = T()[(el as HTMLElement).dataset.i18n!];
    if (typeof v === 'string') el.textContent = v;
  }
  document.getElementById('lang')!.textContent = T().langButton;
  if (st) render(st);
}

(document.getElementById('fixhome') as HTMLButtonElement).onclick = async (e) => {
  // anchor_install is the refresh path: it re-copies anchor.sh and rewrites
  // .version, which is the whole of what refreshing means.
  const target = e.target as HTMLButtonElement;
  target.disabled = true;
  const res = await callTool('anchor_install');
  target.disabled = false;
  renderSteps(res);
  if (res.status) render(res.status);
};

function renderSteps(res: any) {
  const box = document.getElementById('steps')!;
  box.innerHTML = (res.steps || []).map((s: any) =>
    `<div class="${s.ok ? 'ok' : 'bad'}">${s.ok ? '\u2713' : '\u2717'} ${esc(s.step)}` +
    `${s.detail ? ' \u2014 ' + esc(s.detail) : ''}</div>`).join('')
    || `<div class="bad">${esc(res.error || 'unknown error')}</div>`;
}

(document.getElementById('save') as HTMLButtonElement).onclick = async (e) => {
  const target = e.target as HTMLButtonElement;
  const v = (document.getElementById('picker') as HTMLInputElement).value;
  if (!v) return;
  const [hour, minute] = v.split(':').map(Number);
  target.disabled = true;
  const res = await callTool('anchor_set_time', {
    hour, minute,
    timezone: (document.getElementById('tzpick') as HTMLSelectElement).value,
  });
  target.disabled = false;
  renderSteps(res);
  if (res.status) render(res.status);
};

(document.getElementById('toggle') as HTMLButtonElement).onclick = async (e) => {
  const target = e.target as HTMLButtonElement;
  target.disabled = true;
  const res = await callTool('anchor_toggle', { enable: !st.loaded });
  target.disabled = false;
  if (res.status) render(res.status);
};

(document.getElementById('runnow') as HTMLButtonElement).onclick = async (e) => {
  if (!confirm(T().confirmRun as string)) return;
  const target = e.target as HTMLButtonElement;
  target.disabled = true;
  await callTool('anchor_run_now');
  setTimeout(() => { target.disabled = false; void refresh(); }, 4000);
};

(document.getElementById('lang') as HTMLButtonElement).onclick = () => {
  lang = lang === 'en' ? 'zh' : 'en';
  try { localStorage.setItem('lang', lang); } catch {}
  applyLang();
};

function setTheme(theme: unknown) {
  document.documentElement.dataset.theme = theme === 'dark' ? 'dark' : 'light';
}

(app as any).onhostcontextchanged = (ctx: any) => setTheme(ctx?.theme);

// esbuild's iife format has no top-level await, and the panel is served as
// one inlined script, so the startup sequence lives in a function.
async function start() {
  await app.connect();
  setTheme((app.getHostContext() as any)?.theme);
  applyLang();
  await refresh();
  setInterval(() => { void refresh(); }, 15000);
}

void start();
