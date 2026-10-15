(() => {
  'use strict';

  const VERSION = 1;
  if (globalThis.__PRO_MEETING_CONTENT__?.version === VERSION) return;
  globalThis.__PRO_MEETING_CONTENT__ = { version: VERSION };

  const EDITORS = '#prompt-textarea, form [contenteditable="true"][role="textbox"]';
  const SEND = 'button[data-testid="send-button"], button[aria-label^="Send" i], form button[type="submit"]';
  const STOP = 'button[data-testid="stop-button"], button[data-testid="composer-stop-button"], button[aria-label="Stop generating"], button[aria-label="Stop streaming"], button[aria-label="Stop answering"]';
  const USER = '[data-message-author-role="user"], [data-content-search-unit-key$=":user"], [data-chatgpt-search-unit-key$=":user"]';
  const ASSISTANT = '[data-message-author-role="assistant"], [data-content-search-unit-key$=":assistant"], [data-chatgpt-search-unit-key$=":assistant"]';
  let working = false;

  function visible(node) {
    return !!node?.isConnected && node.getClientRects().length > 0 &&
      !node.closest('[hidden], [aria-hidden="true"], [inert]');
  }

  function uniqueVisible(selector, scope = document) {
    const found = [...scope.querySelectorAll(selector)].filter(visible);
    return found.length === 1 ? found[0] : null;
  }

  function composer() {
    const editor = document.querySelector('#prompt-textarea');
    if (visible(editor)) return editor;
    return uniqueVisible('form [contenteditable="true"][role="textbox"]');
  }

  function host() { return composer()?.closest('form') || null; }

  function sendButton() {
    const form = host();
    if (!form) return null;
    return uniqueVisible(SEND, form) || (() => {
      const buttons = [...form.querySelectorAll('button[class*="size-token-button-composer"][class*="bg-composer-primary"]')].filter(visible);
      return buttons.length === 1 ? buttons[0] : null;
    })();
  }

  function generating() { return [...document.querySelectorAll(STOP)].some(visible); }

  function enabled(node) { return !!node && !node.disabled && node.getAttribute('aria-disabled') !== 'true'; }

  function waitFor(check, timeout = 30_000) {
    return new Promise(resolve => {
      const deadline = Date.now() + timeout;
      function tick() {
        let value = null;
        try { value = check(); } catch { /* DOM changed */ }
        if (value) return resolve(value);
        if (Date.now() >= deadline) return resolve(null);
        setTimeout(tick, 160);
      }
      tick();
    });
  }

  // Fast-mode preference is scoped to the Pro Meeting-owned ChatGPT tab.
  // UI labels and available modes vary with the user's ChatGPT plan.
  // Never claim Instant if the actual picker cannot be verified.
  let preparedMode = null;
  async function preferInstantMode() {
    if (preparedMode) return preparedMode;
    const picker = [...document.querySelectorAll(
      '#model-switcher-dropdown-button, [data-testid="model-switcher-dropdown-button"], button[aria-label*="model" i]'
    )].filter(visible).find(node => !node.closest('form'));
    if (!picker) return 'unverified';

    const selected = (picker.innerText || picker.textContent || '').trim();
    if (/\bInstant\b/i.test(selected)) return (preparedMode = 'Instant');
    if (/\bMedium\b/i.test(selected)) return (preparedMode = 'Medium');
    // Don't open uncertain model menus: they can block ChatGPT's upload control
    // and are not consistent across subscription plans/website releases.
    return 'unverified';
  }

  function decodeB64(value) {
    const binary = atob(value);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  async function getAudio(command) {
    const pieces = [];
    let offset = 0;
    let size = null;
    do {
      const data = await chrome.runtime.sendMessage({ type: 'pm:file', id: command.id, offset });
      if (!data?.ok || data.id !== command.id || data.offset !== offset || typeof data.base64 !== 'string') {
        throw new Error(data?.error || 'audio_chunk_invalid');
      }
      if (size === null) size = data.size;
      if (!Number.isInteger(size) || size <= 0 || size > 8 * 1024 * 1024 || data.size !== size) throw new Error('audio_size_invalid');
      pieces.push(decodeB64(data.base64));
      if (data.nextOffset <= offset || data.nextOffset > size) throw new Error('audio_offset_invalid');
      offset = data.nextOffset;
    } while (offset < size);
    return new File(pieces, command.filename, { type: 'audio/wav' });
  }

  function pickFileInput() {
    const form = host();
    if (!form) return null;
    const inputs = [...form.querySelectorAll('input[type="file"]')].filter(node => {
      if (node.disabled) return false;
      const accept = (node.getAttribute('accept') || '').toLowerCase();
      return !accept || accept.includes('audio/') || accept.includes('.wav');
    });
    return inputs.length === 1 ? inputs[0] : null;
  }

  function existingAttachment() {
    const form = host();
    return !!form?.querySelector('[data-composer-attachments] [role="button"], [data-inline-file-uploading], [role="progressbar"]');
  }

  async function uploadAudio(command) {
    if (existingAttachment()) throw new Error('composer_has_another_attachment');
    let input = pickFileInput();
    if (!input) {
      const plus = uniqueVisible('#composer-plus-btn, button[data-testid="composer-plus-btn"]');
      if (plus) plus.click();
      input = pickFileInput();
    }
    if (!input) throw new Error('chatgpt_audio_upload_input_unavailable');

    const file = await getAudio(command);
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));

    // Never send prompt-only text if ChatGPT rejected the audio.
    const attached = await waitFor(() => {
      const form = host();
      if (!form) return null;
      const attachment = form.querySelector('[data-composer-attachments]');
      if (!attachment || !attachment.textContent?.includes(command.filename)) {
        const label = [...form.querySelectorAll('[aria-label], img[alt]')]
          .some(node => (node.getAttribute('aria-label') || node.getAttribute('alt') || '').includes(command.filename));
        if (!label) return null;
      }
      return !form.querySelector('[data-inline-file-uploading], [role="progressbar"], [aria-busy="true"]') || null;
    }, 90_000);
    if (!attached) {
      const form = host();
      const attachment = form?.querySelector('[data-composer-attachments]');
      const fileInput = pickFileInput();
      const labels = [...(form?.querySelectorAll('[aria-label], img[alt]') || [])];
      const info = {
        fileInputPresent: !!fileInput,
        fileAccept: (fileInput?.getAttribute('accept') || '').slice(0, 180),
        selectedFile: !![...(fileInput?.files || [])].find(file => file.name === command.filename),
        attachmentRegion: !!attachment,
        attachmentFilenameVisible: !!attachment?.textContent?.includes(command.filename),
        filenameInAccessibleLabel: labels.some(node => (node.getAttribute('aria-label') || node.getAttribute('alt') || '').includes(command.filename)),
        uploadSpinner: !!form?.querySelector('[data-inline-file-uploading], [role="progressbar"], [aria-busy="true"]'),
        alertCount: document.querySelectorAll('[role="alert"], [data-sonner-toast], [data-testid*="toast"]').length,
        // Diagnostic flags only, not the text of private conversations.
        possibleUploadError: [...document.querySelectorAll('[role="alert"], [data-sonner-toast], [data-testid*="toast"]')]
          .some(node => /upload|limit|quota|failed|error|unsupported|try again|tải|lỗi|giới hạn/i.test(node.textContent || '')),
        attachmentElements: attachment?.querySelectorAll('div, button').length || 0,
      };
      throw new Error(`chatgpt_audio_upload_not_confirmed:${JSON.stringify(info)}`);
    }
  }

  function insertPrompt(text) {
    const input = composer();
    if (!input || (input.textContent || '').trim()) throw new Error('composer_has_user_draft');
    input.focus();
    const source = document.createElement('div');
    text.split('\n').forEach((line, index) => {
      if (index) source.appendChild(document.createElement('br'));
      source.appendChild(document.createTextNode(line));
    });
    const inserted = document.execCommand('insertHTML', false, source.innerHTML);
    if (!inserted || (input.textContent || '').replace(/\s+/g, '') !== text.replace(/\s+/g, '')) {
      throw new Error('composer_insert_failed');
    }
  }

  function messages(selector) {
    const candidates = [...document.querySelectorAll(selector)];
    return candidates.filter(node => !candidates.some(parent => parent !== node && parent.contains(node)));
  }

  function assistantMessages() {
    const explicit = messages(ASSISTANT);
    const roots = [...document.querySelectorAll('section[data-testid^="conversation-turn"][data-turn="assistant"]')]
      .filter(root => !explicit.some(node => root.contains(node)));
    return [...explicit, ...roots].sort((a, b) => {
      const order = a.compareDocumentPosition(b);
      return order & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : order & Node.DOCUMENT_POSITION_PRECEDING ? 1 : 0;
    });
  }

  function answerBody(row) {
    const root = row.closest('section[data-testid^="conversation-turn"][data-turn="assistant"]') || row;
    const sections = [...root.querySelectorAll('.markdown, [data-markdown-text-style="assistant-message"]')]
      .filter(node => !node.closest('[data-message-author-role="user"]'));
    const selected = sections.filter(node => !sections.some(parent => parent !== node && parent.contains(node)));
    if (selected.length) return selected.map(node => (node.innerText || node.textContent || '').trim()).filter(Boolean).join('\n\n');
    return (row.innerText || row.textContent || '').trim();
  }

  function completedAnswer(row) {
    const root = row.closest('section[data-testid^="conversation-turn"], [data-turn-key]') || row;
    return !!root.querySelector('button[data-testid="copy-turn-action-button"]');
  }

  async function deliver(command) {
    if (!composer()) throw new Error('chatgpt_login_required');
    if ((composer().textContent || '').trim() || generating()) throw new Error('chatgpt_composer_busy');
    if (!/^[0-9a-f-]{36}$/i.test(command.id) || !/^segment-\d+\.wav$/.test(command.filename)) {
      throw new Error('invalid_audio_command');
    }
    const marker = `[[PRO-MEETING:${command.id}]]`;
    const prompt = `${command.prompt}\n${marker}`;
    const before = assistantMessages().length;
    await uploadAudio(command);
    insertPrompt(prompt);
    const button = await waitFor(() => enabled(sendButton()) && !generating() ? sendButton() : null);
    if (!button || !composer()?.textContent?.includes(marker)) throw new Error('send_button_not_ready');

    // From this point a missed receipt is uncertain: caller must not retry.
    button.click();
    const receipt = await waitFor(() => messages(USER).find(node => (node.textContent || '').includes(marker)), 35_000);
    if (!receipt) throw new Error('send_receipt_uncertain');

    let lastText = '';
    let lastChanged = Date.now();
    let sawGenerating = generating();
    let prematureAnswer = '';
    const answer = await waitFor(() => {
      if (generating()) sawGenerating = true;
      const rows = assistantMessages();
      if (rows.length <= before) return null;
      const row = rows.at(-1);
      if (!(receipt.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING)) return null;
      const text = answerBody(row);
      if (!text || text !== lastText) {
        lastText = text;
        lastChanged = Date.now();
        return null;
      }
      if (generating()) return null;
      const stableFor = Date.now() - lastChanged;
      const complete = completedAnswer(row);
      if (!complete && !(sawGenerating && stableFor >= 5000) && stableFor < 12000) return null;
      if (!text.includes('NGUYÊN VĂN') || !text.includes('BẢN DỊCH TIẾNG VIỆT')) {
        prematureAnswer = text.slice(0, 250);
        // A final refusal/error should fail explicitly, not be mistaken for a transcript.
        if (complete && stableFor >= 5000) return { error: `chatgpt_unexpected_reply: ${prematureAnswer}` };
        return null;
      }
      return text;
    }, 360_000);
    if (!answer) throw new Error('chatgpt_reply_timeout');
    if (answer?.error) throw new Error(answer.error);
    return answer;
  }

  chrome.runtime.onMessage.addListener((message, _sender, respond) => {
    if (message?.type === 'pm:ping') {
      respond({ ok: true });
      return false;
    }
    if (message?.type === 'pm:ready') {
      if (!composer()) {
        respond({ ready: false });
        return false;
      }
      preferInstantMode().then(
        mode => respond({ ready: true, modelMode: mode }),
        () => respond({ ready: true, modelMode: 'unverified' })
      );
      return true;
    }
    if (message?.type !== 'pm:send') return false;
    if (working) {
      respond({ ok: false, error: 'chatgpt_tab_busy' });
      return false;
    }
    working = true;
    deliver(message.command).then(
      text => respond({ ok: true, text }),
      error => respond({ ok: false, error: String(error.message || error) })
    ).finally(() => { working = false; });
    return true;
  });
})();
