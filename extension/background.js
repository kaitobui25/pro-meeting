'use strict';

const BRIDGE = 'http://127.0.0.1:8796';
const BINDING = 'pro-meeting.owned-chat.v1';
const WAKE = 'pro-meeting.bridge-wake';
const CHAT_URL = 'https://chatgpt.com/';
let polling = false;
let active = null;

async function request(route, options = {}) {
  const reply = await fetch(BRIDGE + route, {
    cache: 'no-store',
    ...options,
    headers: {
      'X-Pro-Meeting-Extension-Id': chrome.runtime.id,
      ...(options.body ? { 'Content-Type': 'application/json' } : {})
    }
  });
  const data = await reply.json();
  if (!reply.ok) throw new Error(data.error || `bridge_http_${reply.status}`);
  return data;
}

function validChat(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' && ['chatgpt.com', 'chat.openai.com'].includes(parsed.hostname)
      && !parsed.pathname.startsWith('/share/');
  } catch { return false; }
}

async function ownedTab() {
  const stored = (await chrome.storage.local.get(BINDING))[BINDING];
  if (Number.isInteger(stored?.tabId)) {
    try {
      const tab = await chrome.tabs.get(stored.tabId);
      if (validChat(tab.url)) return tab;
    } catch { /* closed tab */ }
  }
  // Only create our own tab, never take over a personal or another app's tab.
  const tab = await chrome.tabs.create({ url: CHAT_URL, active: true });
  if (!Number.isInteger(tab?.id)) throw new Error('chat_tab_unavailable');
  await chrome.storage.local.set({ [BINDING]: { tabId: tab.id } });
  return tab;
}

async function awaitContent(tabId) {
  async function pingUntil(deadline) {
    while (Date.now() < deadline) {
      try {
        const reply = await chrome.tabs.sendMessage(tabId, { type: 'pm:ping' });
        if (reply?.ok) return true;
      } catch { /* Content script not injected yet */ }
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    return false;
  }
  // Reloading an unpacked extension invalidates scripts in tabs that are
  // already open. Reuse the same owned tab, refreshing it once if necessary.
  if (await pingUntil(Date.now() + 2500)) return;
  await chrome.tabs.reload(tabId);
  if (await pingUntil(Date.now() + 55_000)) return;
  throw new Error('chatgpt_content_not_ready_after_reload');
}

async function prepareChat(tabId) {
  await awaitContent(tabId);
  const deadline = Date.now() + 140_000;
  while (Date.now() < deadline) {
    try {
      const reply = await chrome.tabs.sendMessage(tabId, { type: 'pm:ready' });
      if (reply?.ready === true) return reply.modelMode || 'unverified';
    } catch { /* login route may reload */ }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw new Error('chatgpt_login_required_or_composer_unavailable');
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== 'pm:file') return false;
  (async () => {
    const binding = (await chrome.storage.local.get(BINDING))[BINDING];
    if (sender.tab?.id !== binding?.tabId || !validChat(sender.url) || message.id !== active) {
      throw new Error('audio_owner_mismatch');
    }
    const offset = message.offset;
    if (!Number.isInteger(offset) || offset < 0 || offset > 8 * 1024 * 1024) {
      throw new Error('audio_offset_invalid');
    }
    const result = await request(`/file?id=${encodeURIComponent(message.id)}&offset=${offset}`);
    return { ok: true, ...result };
  })().then(sendResponse, error => sendResponse({ ok: false, error: error.message }));
  return true;
});

async function execute(command) {
  if (!['prepare', 'transcribe'].includes(command?.type) || typeof command.id !== 'string') return;
  active = command.id;
  try {
    const tab = await ownedTab();
    const modelMode = await prepareChat(tab.id);
    if (command.type === 'prepare') {
      await request('/result', {
        method: 'POST', body: JSON.stringify({ id: command.id, ok: true, text: `ready; mode=${modelMode}` })
      });
      return;
    }
    const result = await chrome.tabs.sendMessage(tab.id, {
      type: 'pm:send',
      command: {
        id: command.id,
        prompt: command.prompt,
        filename: command.filename
      }
    });
    if (!result?.ok) throw new Error(result?.error || 'chatgpt_send_failed');
    await request('/result', {
      method: 'POST',
      body: JSON.stringify({ id: command.id, ok: true, text: result.text })
    });
  } catch (error) {
    try {
      await request('/result', {
        method: 'POST',
        body: JSON.stringify({ id: command.id, ok: false, error: error.message })
      });
    } catch { /* Python process may have exited */ }
  } finally {
    active = null;
  }
}

async function poll() {
  if (polling) return;
  polling = true;
  try {
    while (true) {
      try {
        const response = await request('/poll');
        if (response.command) await execute(response.command);
      } catch {
        await new Promise(resolve => setTimeout(resolve, 1200));
      }
    }
  } finally {
    polling = false;
  }
}

chrome.runtime.onInstalled.addListener(() => {
  void chrome.alarms.create(WAKE, { periodInMinutes: 0.5 });
  void poll();
});
chrome.runtime.onStartup.addListener(() => {
  void chrome.alarms.create(WAKE, { periodInMinutes: 0.5 });
  void poll();
});
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === WAKE) void poll(); });
void chrome.alarms.create(WAKE, { periodInMinutes: 0.5 });
void poll();
