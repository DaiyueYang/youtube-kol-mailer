/**
 * YouTube KOL Assistant — Content Script
 *
 * Injected sidebar for KOL extraction and Bitable writing.
 * Uses X-Session-Token header (stored in chrome.storage.local) for auth.
 *
 * Email extraction strategy (priority order):
 * 1. ytInitialData / structured page data (full description, not affected by fold)
 * 2. DOM description containers (multiple selectors)
 * 3. Expanded about panels / dialogs (if user opened them)
 * 4. Full page text fallback
 */

if (document.getElementById('kol-ext-host')) {
  // Already injected — skip
} else {

// ── State ──
let lastUrl = '';

// ── API helper (via background) ──
function api(method, path, body) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ type: 'API', method, path, body }, resp => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      resolve(resp);
    });
  });
}

function setSession(token) {
  return new Promise(r => chrome.runtime.sendMessage({ type: 'SET_SESSION', token }, r));
}

// ============================================================
// Email Extraction — unified, multi-strategy
// ============================================================

const EMAIL_RE = /[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/g;
const EMAIL_BLACKLIST = [
  /@youtube\.com$/i, /@google\.com$/i, /@example\.com$/i,
  /^noreply@/i, /^no-reply@/i, /^support@/i, /^info@youtube/i,
  /^creator@/i, /^press@youtube/i,
];

/**
 * Extract first valid email from a text string.
 * Returns the email string, or '' if none found.
 */
function pickFirstValidEmail(text) {
  if (!text) return '';
  const matches = text.match(EMAIL_RE);
  if (!matches) return '';
  for (const email of matches) {
    if (!EMAIL_BLACKLIST.some(p => p.test(email))) return email;
  }
  return '';
}

/**
 * Main email extraction — tries strategies in priority order.
 * Returns first valid email found, or ''.
 */
function getEmail() {
  return extractEmailFromPageData()
      || extractEmailFromDescriptionDom()
      || extractEmailFromExpandedPanels()
      || extractEmailFromFullPage()
      || '';
}

/**
 * Strategy 1: Extract from ytInitialData (structured page data).
 * YouTube embeds a large JSON object in the page that contains the FULL
 * channel description, regardless of whether "more" is expanded.
 * This is the most reliable source.
 */
function extractEmailFromPageData() {
  // Method A: Read from ytInitialData global variable
  try {
    const ytData = window.ytInitialData;
    if (ytData) {
      const desc = findDescriptionInYtData(ytData);
      if (desc) {
        const email = pickFirstValidEmail(desc);
        if (email) return email;
      }
    }
  } catch (e) { /* ignore */ }

  // Method B: Find <script> tags containing ytInitialData
  try {
    for (const script of document.querySelectorAll('script')) {
      const text = script.textContent || '';
      if (!text.includes('ytInitialData')) continue;
      // Extract JSON from: var ytInitialData = {...};
      const match = text.match(/var\s+ytInitialData\s*=\s*(\{.+?\});\s*<\/script>/s)
                 || text.match(/var\s+ytInitialData\s*=\s*(\{.+\});/s);
      if (match) {
        try {
          const data = JSON.parse(match[1]);
          const desc = findDescriptionInYtData(data);
          if (desc) {
            const email = pickFirstValidEmail(desc);
            if (email) return email;
          }
        } catch (e) { /* JSON parse failed */ }
      }
    }
  } catch (e) { /* ignore */ }

  // Method C: meta description tag (sometimes contains email)
  const metaDesc = document.querySelector('meta[name="description"]')?.getAttribute('content') || '';
  const metaEmail = pickFirstValidEmail(metaDesc);
  if (metaEmail) return metaEmail;

  // Method D: ld+json structured data
  try {
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      const email = pickFirstValidEmail(script.textContent || '');
      if (email) return email;
    }
  } catch (e) { /* ignore */ }

  return '';
}

/**
 * Navigate the ytInitialData object to find the channel description text.
 * YouTube's structure varies, so we check multiple paths.
 */
function findDescriptionInYtData(data) {
  const paths = [
    // Channel about tab
    d => d?.metadata?.channelMetadataRenderer?.description,
    // Channel header
    d => d?.header?.c4TabbedHeaderRenderer?.channelHandleText?.runs?.map(r => r.text).join(''),
    // Microformat
    d => d?.microformat?.microformatDataRenderer?.description,
    // About page content
    d => {
      const tabs = d?.contents?.twoColumnBrowseResultsRenderer?.tabs || [];
      for (const tab of tabs) {
        const content = tab?.tabRenderer?.content;
        const about = content?.sectionListRenderer?.contents?.[0]?.itemSectionRenderer?.contents?.[0]?.channelAboutFullMetadataRenderer;
        if (about?.description?.simpleText) return about.description.simpleText;
        // Also check artistBio or channelMetadataRenderer in tabs
      }
      return null;
    },
    // Engagement panels (about panel)
    d => {
      const panels = d?.engagementPanels || [];
      for (const panel of panels) {
        const sec = panel?.engagementPanelSectionListRenderer;
        if (!sec) continue;
        const content = sec?.content?.sectionListRenderer?.contents;
        if (!content) continue;
        for (const item of content) {
          const renderer = item?.itemSectionRenderer?.contents?.[0];
          const aboutRenderer = renderer?.aboutChannelRenderer?.metadata?.aboutChannelViewModel;
          if (aboutRenderer?.description) return aboutRenderer.description;
        }
      }
      return null;
    },
  ];

  for (const pathFn of paths) {
    try {
      const result = pathFn(data);
      if (result && typeof result === 'string' && result.length > 10) return result;
    } catch (e) { /* path doesn't exist in this data structure */ }
  }
  return '';
}

/**
 * Strategy 2: Scan DOM description containers.
 * These may be truncated if "more" hasn't been clicked,
 * but we check multiple selectors for coverage.
 */
function extractEmailFromDescriptionDom() {
  const selectors = [
    '#description-container',
    '#about-container',
    'ytd-channel-about-metadata-renderer',
    'yt-attributed-string#description-container',
    '#channel-tagline',                          // some channels show tagline with email
    'ytd-text-inline-expander #plain-snippet-text', // newer layout snippet
    'ytd-text-inline-expander #snippet-text',
    '#description.ytd-channel-about-metadata-renderer',
    'yt-formatted-string#bio',
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (!el) continue;
    // Use textContent (includes hidden text) not innerText (only visible)
    const text = el.textContent || '';
    const email = pickFirstValidEmail(text);
    if (email) return email;
  }
  return '';
}

/**
 * Strategy 3: Scan expanded about panels / popups / dialogs.
 * If the user has clicked "more" or the about panel is open,
 * we scan those expanded containers.
 */
function extractEmailFromExpandedPanels() {
  const panelSelectors = [
    // About dialog / panel
    'ytd-engagement-panel-section-list-renderer[target-id="engagement-panel-structured-description"]',
    'ytd-engagement-panel-section-list-renderer',
    'tp-yt-paper-dialog',
    '#panels ytd-engagement-panel-section-list-renderer',
    // Expanded description area
    'ytd-text-inline-expander[is-expanded]',
    'ytd-text-inline-expander .content',
    '#description-inline-expander',
    '#description ytd-text-inline-expander',
  ];
  for (const sel of panelSelectors) {
    const el = document.querySelector(sel);
    if (!el) continue;
    const text = el.textContent || '';
    const email = pickFirstValidEmail(text);
    if (email) return email;
  }
  return '';
}

/**
 * Strategy 4: Full page text fallback.
 * Scans the entire page content as last resort.
 */
function extractEmailFromFullPage() {
  const content = document.querySelector('#content') || document.body;
  // Use textContent to get ALL text including hidden elements
  const text = content.textContent || '';
  return pickFirstValidEmail(text);
}

// ============================================================
// Other KOL field extraction
// ============================================================

function extractKol() {
  return {
    kol_name: getName(), source_url: getUrl(), email: getEmail(),
    followers_text: getSubs(), category: getCat(),
    language: 'English', platform: 'YouTube',
  };
}

function getName() {
  for (const s of [
    'yt-dynamic-text-view-model.channel-header-title-wiz .yt-core-attributed-string',
    '#channel-name yt-formatted-string#text', '#channel-name #text',
    '#upload-info #channel-name yt-formatted-string',
    'ytd-video-owner-renderer #channel-name a',
    'yt-formatted-string.ytd-channel-name',
  ]) { const el = document.querySelector(s); if (el?.textContent?.trim()) return el.textContent.trim(); }
  return document.querySelector('meta[property="og:title"]')?.getAttribute('content') || '';
}

function getUrl() {
  const u = location.href;
  const m = u.match(/(https?:\/\/www\.youtube\.com\/@[^\/\?]+)/) || u.match(/(https?:\/\/www\.youtube\.com\/channel\/[^\/\?]+)/);
  return m ? m[1] : u;
}

function getSubs() {
  for (const s of ['#subscriber-count','yt-formatted-string#subscriber-count']) {
    const el = document.querySelector(s); if (el?.textContent?.trim()) return el.textContent.trim();
  }
  return '';
}

function getCat() {
  const kw = document.querySelector('meta[name="keywords"]');
  if (kw) { const p = kw.getAttribute('content')?.split(',').map(s=>s.trim()).filter(Boolean)||[]; if (p.length) return p.slice(0,3).join(', '); }
  return '';
}

// ============================================================
// Sidebar UI
// ============================================================

function createSidebar() {
  const host = document.createElement('div');
  host.id = 'kol-ext-host';
  host.style.cssText = 'all:initial;position:fixed;top:0;right:0;z-index:2147483647;height:100vh;pointer-events:none;';
  document.body.appendChild(host);
  const shadow = host.attachShadow({ mode: 'open' });
  const style = document.createElement('style');
  style.textContent = CSS;
  shadow.appendChild(style);
  const root = document.createElement('div');
  root.innerHTML = HTML;
  shadow.appendChild(root);
  return shadow;
}

const CSS = `
:host{all:initial}*{margin:0;padding:0;box-sizing:border-box}
#panel{position:fixed;top:0;right:0;width:320px;height:100vh;background:#fff;border-left:1px solid #ddd;
  box-shadow:-2px 0 12px rgba(0,0,0,.08);display:flex;flex-direction:column;pointer-events:auto;
  font:13px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#333;transition:transform .2s}
#panel.hidden{transform:translateX(100%);pointer-events:none}
#toggle{position:fixed;top:50%;right:0;transform:translateY(-50%);width:28px;height:44px;background:#1a73e8;color:#fff;
  border:0;border-radius:6px 0 0 6px;cursor:pointer;pointer-events:auto;display:flex;align-items:center;justify-content:center;
  font-size:16px;box-shadow:-2px 0 6px rgba(0,0,0,.15);z-index:0}
#toggle.hidden{opacity:0;pointer-events:none}
.hdr{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-bottom:2px solid #1a73e8;flex-shrink:0}
.hdr h1{font-size:14px;font-weight:700;color:#1a73e8}
.hdr button{background:none;border:0;cursor:pointer;font-size:18px;color:#888;width:28px;height:28px;border-radius:4px}
.hdr button:hover{background:#f0f0f0;color:#333}
.body{flex:1;overflow-y:auto;padding:10px 12px}
.sec{margin-bottom:10px}.sec-t{font-size:11px;font-weight:600;color:#555;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
label{display:block;font-size:11px;color:#666;margin-bottom:1px}
input,select,textarea{width:100%;padding:5px 8px;border:1px solid #ddd;border-radius:4px;font:12px/1.4 inherit;outline:0}
input:focus,select:focus,textarea:focus{border-color:#1a73e8}
input[readonly]{background:#f8f8f8;color:#888}textarea{resize:vertical}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:6px}.fld{margin-bottom:5px}
.foot{padding:8px 12px;border-top:1px solid #eee;flex-shrink:0}
.btns{display:flex;gap:6px;margin-bottom:4px}
.btn{flex:1;padding:7px 8px;border:0;border-radius:4px;font:13px/1 inherit;font-weight:600;cursor:pointer}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-p{background:#1a73e8;color:#fff}.btn-p:hover:not(:disabled){background:#1557b0}
.btn-s{background:#f1f3f4;color:#333}.btn-s:hover:not(:disabled){background:#e0e0e0}
.btn-login{background:#00b578;color:#fff}.btn-login:hover{background:#009a63}
.msg{margin-top:6px;padding:6px 8px;border-radius:4px;font-size:12px;text-align:center}
.msg-ok{background:#e6f4ea;color:#137333}.msg-err{background:#fce8e6;color:#c5221f}.msg-info{background:#e8f0fe;color:#1a73e8}
.tag{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:700;background:#e8f0fe;color:#1967d2}
.user-bar{padding:6px 12px;background:#f8f9fa;border-bottom:1px solid #eee;font-size:11px;color:#666;flex-shrink:0}
`;

const HTML = `
<button id="toggle" class="hidden" title="展开">&#9664;</button>
<div id="panel">
  <div class="hdr"><h1>KOL Assistant</h1><button id="btn-close" title="收起">&times;</button></div>
  <div class="user-bar" id="user-bar">检测登录状态...</div>
  <div class="body">
    <div id="status" class="msg msg-info">加载中...</div>
    <div class="sec"><div class="sec-t">KOL 信息</div>
      <div class="fld"><label>频道名称</label><input id="f-name" readonly></div>
      <div class="fld"><label>频道链接</label><input id="f-url" readonly></div>
      <div class="fld"><label>邮箱</label><input id="f-email" placeholder="未抓取到可手动填写"></div>
      <div class="row2"><div class="fld"><label>订阅数</label><input id="f-subs" readonly></div>
      <div class="fld"><label>分类</label><input id="f-cat" readonly></div></div>
    </div>
    <div class="sec"><div class="sec-t">邮件模板</div>
      <div class="fld"><select id="f-tmpl"><option value="">加载中...</option></select></div>
    </div>
    <div class="sec"><div class="fld"><label>备注（可选）</label><textarea id="f-notes" rows="2"></textarea></div></div>
  </div>
  <div class="foot">
    <div class="btns">
      <button class="btn btn-s" id="btn-refresh">刷新页面</button>
      <button class="btn btn-p" id="btn-write">写入 KOL 表格</button>
    </div>
    <div class="btns">
      <button class="btn btn-login" id="btn-login" style="display:none">登录飞书</button>
      <button class="btn btn-s" id="btn-admin">打开后台管理</button>
    </div>
    <div id="write-msg"></div>
  </div>
</div>`;

// ============================================================
// Init & Event Handlers
// ============================================================
const shadow = createSidebar();
const $ = id => shadow.getElementById(id);

// Toggle
$('btn-close').onclick = () => { $('panel').classList.add('hidden'); $('toggle').classList.remove('hidden'); };
$('toggle').onclick = () => { $('panel').classList.remove('hidden'); $('toggle').classList.add('hidden'); };

// Refresh
$('btn-refresh').onclick = () => location.reload();

// Admin
$('btn-admin').onclick = () => {
  chrome.storage.sync.get(['backend_url'], r => {
    window.open((r.backend_url || 'https://api.youtube-kol.com') + '/admin/', '_blank');
  });
};

// Login
$('btn-login').onclick = () => {
  chrome.storage.sync.get(['backend_url'], r => {
    const base = r.backend_url || 'https://api.youtube-kol.com';
    const state = 'ext_' + Math.random().toString(36).slice(2, 14);
    window.open(base + '/api/auth/login?ext_state=' + state, '_blank');
    $('write-msg').innerHTML = '<div class="msg msg-info">请在新标签页完成飞书授权...</div>';
    const poller = setInterval(async () => {
      try {
        const resp = await api('GET', '/api/auth/session-token?state=' + state);
        if (resp.data?.success && resp.data?.session_token) {
          clearInterval(poller);
          await setSession(resp.data.session_token);
          loadUserStatus();
          loadTemplates();
          $('write-msg').innerHTML = '<div class="msg msg-ok">登录成功</div>';
        }
      } catch (e) { /* keep polling */ }
    }, 2000);
    setTimeout(() => {
      clearInterval(poller);
      if ($('write-msg').innerHTML.includes('请在新标签页'))
        $('write-msg').innerHTML = '<div class="msg msg-err">登录超时，请重试</div>';
    }, 180000);
  });
};

// Write KOL
$('btn-write').onclick = async () => {
  const name = $('f-name').value.trim();
  const tmpl = $('f-tmpl').value;
  const wmsg = $('write-msg');
  if (!name) { wmsg.innerHTML = '<div class="msg msg-err">频道名称为空</div>'; return; }
  if (!tmpl) { wmsg.innerHTML = '<div class="msg msg-err">请选择模板</div>'; return; }
  $('btn-write').disabled = true;
  wmsg.innerHTML = '<div class="msg msg-info">正在写入...</div>';
  try {
    const resp = await api('POST', '/api/kols/upsert', {
      kol_name: name, channel_name: name,
      email: $('f-email').value.trim(), source_url: $('f-url').value.trim(),
      followers_text: $('f-subs').value.trim(), category: $('f-cat').value.trim(),
      template_key: tmpl, template_name: $('f-tmpl').selectedOptions[0]?.textContent || '',
      notes: $('f-notes').value.trim(), platform: 'YouTube', language: 'English',
    });
    if (resp.ok && resp.data?.success)
      wmsg.innerHTML = `<div class="msg msg-ok">写入成功 ${esc(resp.data.data?.kol_id||'')}</div>`;
    else
      wmsg.innerHTML = `<div class="msg msg-err">${esc(resp.data?.detail||resp.data?.message||resp.error||'失败')}</div>`;
  } catch (e) {
    wmsg.innerHTML = `<div class="msg msg-err">${esc(e.message)}</div>`;
  } finally { $('btn-write').disabled = false; }
};

// ── Fill KOL data ──
function fillKol() {
  const d = extractKol();
  $('f-name').value = d.kol_name; $('f-url').value = d.source_url;
  $('f-email').value = d.email; $('f-subs').value = d.followers_text; $('f-cat').value = d.category;
  $('write-msg').innerHTML = '';
  if (d.kol_name) {
    $('status').className = 'msg msg-ok';
    $('status').textContent = '已抓取: ' + d.kol_name + (d.email ? '' : ' (未找到邮箱)');
  } else {
    $('status').className = 'msg msg-info';
    $('status').textContent = '未检测到频道信息';
  }
  return d; // return for retry logic to check
}

// ── Load templates ──
async function loadTemplates() {
  try {
    const resp = await api('GET', '/api/templates?channel=youtube&enabled_only=true');
    const sel = $('f-tmpl');
    sel.innerHTML = '<option value="">-- 选择模板 --</option>';
    const ts = resp.data?.data?.templates || resp.data?.templates || [];
    for (const t of ts) { if (!t.enabled) continue; const o = document.createElement('option'); o.value = t.template_key; o.textContent = t.template_name; sel.appendChild(o); }
  } catch (e) { $('f-tmpl').innerHTML = '<option value="">加载失败</option>'; }
}

// ── Load user status ──
async function loadUserStatus() {
  const bar = $('user-bar');
  try {
    const resp = await api('GET', '/api/auth/status');
    const d = resp.data || resp;
    if (d.logged_in) {
      bar.innerHTML = '✓ ' + esc(d.display_name || '已登录') +
        (d.has_bitable ? ' | <span class="tag">Bitable ✓</span>' : ' | <span class="tag" style="background:#fce8e6;color:#c5221f">Bitable ✗</span>');
      $('btn-login').style.display = 'none';
    } else {
      bar.innerHTML = '未登录飞书';
      $('btn-login').style.display = '';
    }
  } catch (e) {
    bar.innerHTML = '后端连接失败';
    $('btn-login').style.display = '';
  }
}

// ── SPA navigation ──
document.addEventListener('yt-navigate-finish', () => onNav());
document.addEventListener('yt-navigate-start', () => { clearFields(); $('status').className='msg msg-info'; $('status').textContent='页面切换中...'; });
const _push = history.pushState; history.pushState = function() { _push.apply(this, arguments); setTimeout(onNav, 100); };
const _repl = history.replaceState; history.replaceState = function() { _repl.apply(this, arguments); setTimeout(onNav, 100); };
window.addEventListener('popstate', () => setTimeout(onNav, 300));
setInterval(() => { if (location.href !== lastUrl) onNav(); }, 800);

function clearFields() { $('f-name').value=''; $('f-url').value=''; $('f-email').value=''; $('f-subs').value=''; $('f-cat').value=''; $('write-msg').innerHTML=''; }

let navTimer = null;
function onNav() {
  lastUrl = location.href;
  clearFields();
  $('status').className = 'msg msg-info'; $('status').textContent = '正在抓取...';
  if (navTimer) clearTimeout(navTimer);
  let n = 0;
  function tryFill() {
    const d = fillKol();
    n++;
    // Retry if EITHER name or email is still missing (up to 5 attempts, increasing delay)
    const needRetry = !d.kol_name || !d.email;
    if (needRetry && n < 5) {
      navTimer = setTimeout(tryFill, 500 + n * 500); // 1s, 1.5s, 2s, 2.5s
    }
  }
  navTimer = setTimeout(tryFill, 600);
}

// ── Startup ──
setTimeout(() => { lastUrl = location.href; fillKol(); loadTemplates(); loadUserStatus(); }, 800);

function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

} // end guard
