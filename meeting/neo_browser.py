"""Drive an existing, signed-in BrowserOS Neo through its local MCP server.

Neo uses CDP's native file picker, because ChatGPT no longer reliably accepts
synthetic file-input change events from Chrome content scripts.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4


_OPEN = r"""
const page = await browser.open('https://chatgpt.com/');
const ready = await page.waitForSelector(
  'form[data-chatgpt-composer] [contenteditable="true"]', { timeout: 25000 });
if (!ready.matched) throw new Error('neo_chatgpt_login_or_composer_unavailable');
const previous = await page.evaluate(() =>
  document.querySelector('form [contenteditable="true"]')?.textContent || '');
if (/\[\[PRO-MEETING:[0-9a-f-]{36}\]\]/.test(previous.value)) {
  const snap = await page.snapshot({ mode: 'interactive' });
  const field = snap.text.match(/textbox "Ask ChatGPT" \[ref=(e\d+)\]/);
  if (!field) throw new Error('neo_old_test_draft_not_accessible');
  try {
    await page.fill(field[1], '');
  } catch (error) {
    const cleared = await page.evaluate(() =>
      (document.querySelector('form [contenteditable="true"]')?.textContent || '').trim());
    if (cleared.value) throw error;
  }
}
await page.evaluate(() => {
  // Clear only leftover files owned by an interrupted Pro Meeting test.
  const button = [...document.querySelectorAll(
    'form [data-composer-attachments] button[aria-label^="Remove segment-"]')]
    .find(node => /^Remove segment-\d+(?:\(\d+\))?\.wav$/.test(node.getAttribute('aria-label') || ''));
  button?.click();
});
return { pageId: page.id };
"""


_SELECT_MODE = r"""
const page = browser.page(__PAGE_ID__);
const opened = await page.evaluate(() => {
  const button = document.querySelector('form button[aria-label="Select ChatGPT model"]');
  if (!button) return false;
  button.click();
  return true;
});
if (!opened.value) throw new Error('neo_model_selector_missing');
const available = await page.waitForSelector('[role="menu"] [role="menuitem"]', { timeout: 5000 });
if (!available.matched) throw new Error('neo_model_menu_not_open');
const power = await page.evaluate(() => {
  const option = document.querySelector('[role="menu"] [role="menuitem"][aria-label="Power"]');
  if (!option) return false;
  option.click();
  return true;
});
if (!power.value) throw new Error('neo_model_power_not_available');
const slider = await page.waitForSelector('[role="menu"] [role="slider"]', { timeout: 5000 });
if (!slider.matched) throw new Error('neo_model_power_slider_not_available');
const bounds = await page.evaluate(() => {
  const thumb = document.querySelector('[role="menu"] [role="slider"]');
  const root = thumb?.parentElement?.parentElement;
  const rect = root?.getBoundingClientRect();
  return rect && { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
});
if (!bounds.value) throw new Error('neo_model_slider_bounds_missing');
const x = bounds.value.x + (__LEVEL__ === 0 ? 14 : bounds.value.width / 2);
const y = bounds.value.y + bounds.value.height / 2;
await page.cdp('Input.dispatchMouseEvent', JSON.stringify({
  type: 'mousePressed', x, y, button: 'left', clickCount: 1
}));
await page.cdp('Input.dispatchMouseEvent', JSON.stringify({
  type: 'mouseReleased', x, y, button: 'left', clickCount: 1
}));
const selected = await page.waitForSelector(
  '[role="menu"] [role="slider"][aria-valuenow="__LEVEL__"]', { timeout: 5000 });
if (!selected.matched) throw new Error('neo_model_mode_not_confirmed:__MODE__');
await page.evaluate(() => document.querySelector('form [contenteditable="true"]')?.click());
return { mode: '__MODE__' };
"""


_ATTACH = r"""
const page = browser.page(__PAGE_ID__);
const status = await page.evaluate(() => {
  const form = document.querySelector('form[data-chatgpt-composer]');
  return {
    ready: !!form?.querySelector('[contenteditable="true"]'),
    draft: !!form?.querySelector('[contenteditable="true"]')?.textContent?.trim(),
    attachment: !!form?.querySelector('[data-composer-attachments]:not([hidden]) button'),
    generating: !!form?.querySelector('button[aria-label="Stop"]'),
    before: document.querySelectorAll('[data-content-search-unit-key$=":assistant"]').length
  };
});
if (!status.value.ready || status.value.draft || status.value.attachment || status.value.generating) {
  throw new Error('neo_chatgpt_composer_busy:' + JSON.stringify(status.value));
}
const dom = await page.cdp('DOM.getDocument', '{}');
const input = await page.cdp('DOM.querySelector', JSON.stringify({
  nodeId: dom.root.nodeId,
  selector: 'form input[type="file"][aria-label="Attach files"]'
}));
if (!input.nodeId) throw new Error('neo_native_file_input_not_found');
await page.cdp('DOM.setFileInputFiles', JSON.stringify({
  nodeId: input.nodeId, files: [__FILE_PATH__]
}));
const attached = await page.waitForSelector(
  'form [data-composer-attachments]:not([hidden]) button[aria-label^="Remove "]',
  { timeout: 20000 }
);
if (!attached.matched) throw new Error('neo_native_audio_attachment_not_visible');
return { attached: true };
"""


_FILL = r"""
const page = browser.page(__PAGE_ID__);
const exists = await page.evaluate(() => !!document.querySelector(
  'form [data-composer-attachments]:not([hidden]) button[aria-label^="Remove "]'));
if (!exists.value) throw new Error('neo_audio_attachment_lost_before_prompt');
const focused = await page.evaluate(() => {
  const editor = document.querySelector('form [contenteditable="true"]');
  if (!editor || editor.textContent.trim()) return false;
  editor.focus();
  return true;
});
if (!focused.value) throw new Error('neo_chatgpt_editor_not_empty');
// Native CDP typing is one operation rather than Neo's per-character fill.
await page.cdp('Input.insertText', JSON.stringify({ text: __PROMPT__ }));
const checked = await page.evaluate(() =>
  document.querySelector('form [contenteditable="true"]')?.textContent || '');
const compact = value => String(value).replace(/\s+/g, '');
if (compact(checked.value) !== compact(__PROMPT__)) {
  throw new Error('neo_chatgpt_prompt_not_confirmed');
}
return { filled: true };
"""


_FILL_TEXT = r"""
const page = browser.page(__PAGE_ID__);
const focused = await page.evaluate(() => {
  const editor = document.querySelector('form [contenteditable="true"]');
  if (!editor || editor.textContent.trim()) return false;
  if (document.querySelector('form [data-composer-attachments]:not([hidden]) button')) return false;
  editor.focus();
  return true;
});
if (!focused.value) throw new Error('neo_text_composer_not_empty');
await page.cdp('Input.insertText', JSON.stringify({ text: __PROMPT__ }));
const checked = await page.evaluate(() =>
  document.querySelector('form [contenteditable="true"]')?.textContent || '');
const compact = value => String(value).replace(/\s+/g, '');
if (compact(checked.value) !== compact(__PROMPT__)) throw new Error('neo_text_prompt_not_confirmed');
return { filled: true };
"""


_SUBMIT = r"""
const page = browser.page(__PAGE_ID__);
const canSend = await page.waitForSelector(
  'form button[type="submit"]:not([disabled])', { timeout: 15000 });
if (!canSend.matched) throw new Error('neo_chatgpt_send_button_disabled');
// After this click, an uncertain receipt must never trigger an automatic retry.
const bounds = await page.evaluate(() => {
  const button = document.querySelector('form button[type="submit"]');
  if (!button || button.disabled) return null;
  const rect = button.getBoundingClientRect();
  return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
});
if (!bounds.value) throw new Error('neo_chatgpt_send_button_not_ready');
await page.cdp('Input.dispatchMouseEvent', JSON.stringify({
  type: 'mousePressed', x: bounds.value.x, y: bounds.value.y,
  button: 'left', clickCount: 1
}));
await page.cdp('Input.dispatchMouseEvent', JSON.stringify({
  type: 'mouseReleased', x: bounds.value.x, y: bounds.value.y,
  button: 'left', clickCount: 1
}));
// ChatGPT navigates from / to /c/... on first send. Neo can assign a new
// page id during navigation; verify the unique receipt in subsequent reads.
return { sent: true };
"""


_CHECK = """
const candidates = (await browser.pages.list()).filter(item =>
  item.url.startsWith('https://chatgpt.com/c/'));
for (const item of candidates) {
  const page = browser.page(item.pageId);
  try {
    const answer = await page.evaluate(() => {
      const receipt = [...document.querySelectorAll(
        '[data-chatgpt-search-unit-key$=":user"]')]
        .find(node => node.textContent.includes(__MARKER__));
      if (!receipt) return { found: false };
      // Associate the response with this receipt, not a count of virtualized
      // assistant elements, which ChatGPT can change while rendering a turn.
      const rows = [...document.querySelectorAll(
        '[data-content-search-unit-key$=":assistant"]')]
        .filter(row => receipt.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING);
      const last = rows.at(-1);
      const body = last?.querySelector('.markdown, [data-markdown-text-style="assistant-message"]');
      const text = (body?.innerText || last?.innerText || '').trim()
        .replace(/^ChatGPT said:\\s*/, '');
      return {
        found: true,
        hasAnswer: !!last,
        text,
        generating: !!document.querySelector(
          'form button[aria-label="Stop"], form button[data-testid="stop-button"]')
      };
    });
    if (answer.value.found) return { ...answer.value, pageId: item.pageId };
  } catch { /* A tab can navigate or close between listing and evaluating. */ }
}
return { found: false };
"""


class NeoBrowser:
    def __init__(self) -> None:
        self.endpoint = os.getenv("PRO_MEETING_NEO_MCP_URL", "http://127.0.0.1:9010/mcp")
        self.session: str | None = None
        self.next_id = 1
        self.page_id: int | None = None
        self.mode = os.getenv('PRO_MEETING_CHATGPT_MODE', 'instant').strip().lower()
        if self.mode not in ('instant', 'medium'):
            raise ValueError('PRO_MEETING_CHATGPT_MODE chỉ nhận instant hoặc medium')
        self.last_timing: dict[str, float | str] = {}

    def _rpc(self, method: str, params: dict) -> dict:
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if not method.startswith("notifications/"):
            message["id"] = self.next_id
            self.next_id += 1
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session:
            headers["mcp-session-id"] = self.session
        request = Request(self.endpoint, data=json.dumps(message).encode("utf-8"),
                          headers=headers, method="POST")
        try:
            with urlopen(request, timeout=45) as reply:
                self.session = reply.headers.get("mcp-session-id", self.session)
                raw = reply.read().decode("utf-8")
        except (URLError, OSError) as error:
            raise RuntimeError(f"Không kết nối được BrowserOS Neo MCP ({self.endpoint}): {error}") from error
        entries = [line[6:] for line in raw.splitlines() if line.startswith("data: {")]
        if entries:
            response = json.loads(entries[-1])
        elif raw.strip().startswith("{"):
            response = json.loads(raw)
        elif method.startswith("notifications/"):
            return {}
        else:
            raise RuntimeError("BrowserOS Neo MCP không trả về kết quả JSON-RPC")
        if response.get("error"):
            raise RuntimeError(f"BrowserOS Neo MCP: {response['error']}")
        return response.get("result") or {}

    def _run(self, code: str) -> dict:
        result = self._rpc("tools/call", {"name": "run", "arguments": {"code": code}})
        structured = result.get("structuredContent") or {}
        if not structured.get("ok"):
            raise RuntimeError(f"BrowserOS Neo: {structured.get('error') or result.get('content')}")
        value = structured.get("value") or {}
        # page.evaluate() returns {page, value} inside a Neo run.
        return value.get("value", value) if isinstance(value, dict) else value

    def prepare(self) -> None:
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "pro-meeting", "version": "1.0"},
        })
        self._rpc("notifications/initialized", {})
        page = self._run(_OPEN)
        self.page_id = page["pageId"]
        selected = self._run(_SELECT_MODE.replace('__PAGE_ID__', str(self.page_id))
                             .replace('__LEVEL__', '0' if self.mode == 'instant' else '1')
                             .replace('__MODE__', self.mode))
        if selected.get('mode') != self.mode:
            raise RuntimeError(f'Neo chưa chọn được {self.mode}')

    def transcribe_translate(self, audio: Path, prompt: str, timeout: int) -> str:
        if self.page_id is None:
            raise RuntimeError("BrowserOS Neo chưa mở tab ChatGPT")
        if not audio.is_file():
            raise RuntimeError(f"Không tìm thấy WAV: {audio}")
        marker = f"[[PRO-MEETING:{uuid4()}]]"
        started = time.monotonic()
        attach_code = (_ATTACH.replace('__PAGE_ID__', str(self.page_id))
                       .replace('__FILE_PATH__', json.dumps(str(audio.resolve()))))
        attachment = self._run(attach_code)
        if not attachment.get('attached'):
            raise RuntimeError('Neo không xác nhận được WAV trong ô soạn')
        upload_seconds = time.monotonic() - started
        fill_code = (_FILL.replace('__PAGE_ID__', str(self.page_id))
                     .replace('__PROMPT__', json.dumps(prompt + '\n' + marker, ensure_ascii=True)))
        filled = self._run(fill_code)
        if not filled.get('filled'):
            raise RuntimeError('Neo không xác nhận được prompt trong ô soạn')
        fill_seconds = time.monotonic() - started - upload_seconds
        sent = self._run(_SUBMIT.replace('__PAGE_ID__', str(self.page_id)))
        if not sent.get("sent"):
            raise RuntimeError("Neo không xác nhận được đã gửi âm thanh")
        self.last_timing = {
            'mode': self.mode,
            'upload_seconds': round(upload_seconds, 2),
            'fill_seconds': round(fill_seconds, 2),
            'send_seconds': round(time.monotonic() - started, 2),
        }
        check_code = _CHECK.replace("__MARKER__", json.dumps(marker))
        deadline = time.monotonic() + timeout
        last_text = ""
        stable_since = time.monotonic()
        first_response_seconds: float | None = None
        while time.monotonic() < deadline:
            state = self._run(check_code)
            if state.get("found"):
                self.page_id = state["pageId"]
            if state.get("hasAnswer"):
                text = state.get("text", "")
                if text and first_response_seconds is None:
                    first_response_seconds = time.monotonic() - started
                if text != last_text:
                    last_text = text
                    stable_since = time.monotonic()
                elif ("NGUYÊN VĂN" in text and "BẢN DỊCH TIẾNG VIỆT" in text
                      and not state.get("generating") and time.monotonic() - stable_since >= 1.2):
                    self.last_timing.update({
                        'first_response_seconds': first_response_seconds or 0,
                        'total_seconds': time.monotonic() - started,
                    })
                    return text
            time.sleep(0.8)
        raise TimeoutError("Neo ChatGPT không trả lời đủ phiên âm và bản dịch trong thời hạn")

    def translate_text(self, original: str, timeout: int = 180) -> str:
        """Fast-path candidate: local Japanese ASR followed by web text translation."""
        if self.page_id is None or not original.strip():
            raise RuntimeError('Không có tab Neo hoặc nguyên văn để dịch')
        started = time.monotonic()
        marker = f'[[PRO-MEETING:{uuid4()}]]'
        prompt = ('Dịch đoạn tiếng Nhật sau sang tiếng Việt, chính xác, ngắn gọn, '
                  'không giải thích. Chỉ trả bản dịch tiếng Việt.\n'
                  + original.strip() + '\n' + marker)
        code = (_FILL_TEXT.replace('__PAGE_ID__', str(self.page_id))
                .replace('__PROMPT__', json.dumps(prompt, ensure_ascii=True)))
        if not self._run(code).get('filled'):
            raise RuntimeError('Neo không nhập được nguyên văn để dịch')
        if not self._run(_SUBMIT.replace('__PAGE_ID__', str(self.page_id))).get('sent'):
            raise RuntimeError('Neo không xác nhận gửi lệnh dịch')
        sent_seconds = time.monotonic() - started
        check_code = _CHECK.replace('__MARKER__', json.dumps(marker))
        stable = started
        previous = ''
        while time.monotonic() - started < timeout:
            state = self._run(check_code)
            if state.get('found'):
                self.page_id = state['pageId']
            if state.get('hasAnswer'):
                text = state.get('text', '').strip()
                if text != previous:
                    previous = text
                    stable = time.monotonic()
                elif text and not state.get('generating') and time.monotonic() - stable >= 1.2:
                    self.last_timing = {'mode': self.mode, 'send_seconds': round(sent_seconds, 2),
                                        'total_seconds': round(time.monotonic() - started, 2)}
                    return text
            time.sleep(0.8)
        raise TimeoutError('Neo không hoàn thành dịch văn bản trong thời hạn')
