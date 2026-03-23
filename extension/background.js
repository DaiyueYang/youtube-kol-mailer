/**
 * Background Service Worker
 *
 * Responsibilities:
 * 1. Relay API requests with session token header
 * 2. Store/manage session token in chrome.storage
 */

// API relay — sends X-Session-Token header for user identification
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'API') {
    callBackend(msg.method, msg.path, msg.body)
      .then(sendResponse)
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  if (msg.type === 'SET_SESSION') {
    chrome.storage.local.set({ session_token: msg.token });
    sendResponse({ ok: true });
    return false;
  }
  if (msg.type === 'GET_SESSION') {
    chrome.storage.local.get(['session_token'], r => sendResponse(r));
    return true;
  }
  if (msg.type === 'CLEAR_SESSION') {
    chrome.storage.local.remove('session_token');
    sendResponse({ ok: true });
    return false;
  }
});

async function callBackend(method, path, body) {
  const store = await chrome.storage.sync.get(['backend_url']);
  const base = store.backend_url || 'https://api.youtube-kol.com';
  const url = base + path;

  // Get session token
  const local = await chrome.storage.local.get(['session_token']);
  const token = local.session_token || '';

  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['X-Session-Token'] = token;

  const opts = { method: method || 'GET', headers };
  if (body) opts.body = JSON.stringify(body);

  const resp = await fetch(url, opts);
  const data = await resp.json();
  return { ok: resp.ok, status: resp.status, data };
}

// First install defaults
chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.sync.get(['backend_url'], r => {
    if (!r.backend_url) chrome.storage.sync.set({ backend_url: 'https://api.youtube-kol.com' });
  });
});
