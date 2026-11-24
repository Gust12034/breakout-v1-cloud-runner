/** Breakout V1 Dynamic control plane for Google Apps Script + Google Sheets.
 * Keeps trade logic in Python. Stores reports/snapshots and handles Telegram commands.
 * Do not place secrets directly in this source file.
 */
const APP_NAME = 'Breakout V1 Dynamic';
const QUIET_EVENT_KINDS = { position_snapshot: true, warmup: true };
const STATE_HEADERS = ['key', 'value', 'updated_at'];
const EVENT_HEADERS = ['id', 'created_at', 'kind', 'message', 'payload_json'];
const POSITION_HEADERS = [
  'position_id', 'symbol', 'side', 'status', 'qty', 'entry_price', 'initial_stop',
  'current_stop', 'target', 'opened_at_ms', 'closed_at_ms', 'exit_price',
  'net_pnl_model', 'exchange_closed_pnl', 'exit_reason', 'data_json', 'created_at', 'updated_at'
];

function doGet(e) {
  const action = (e && e.parameter && e.parameter.action) || '';
  if (action === 'health') return jsonOutput_({ ok: true, app: APP_NAME, mode: 'google-apps-script' });
  return jsonOutput_({ ok: false, error: 'not_found', hint: 'Use action=health for a health check.' });
}

function doPost(e) {
  try {
    const params = (e && e.parameter) || {};
    if (params.route === 'telegram') return handleTelegramWebhook_(e, params);

    let body = {};
    try {
      body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    } catch (_) {
      return jsonOutput_({ ok: false, error: 'invalid_json' });
    }
    if (!isAuthorized_(body.key)) return jsonOutput_({ ok: false, error: 'unauthorized' });
    if (body.action === 'state') return jsonOutput_({ ok: true, ...getBotState_() });
    if (body.action === 'report') return handleReport_(body);
    return jsonOutput_({ ok: false, error: 'unknown_action' });
  } catch (err) {
    console.error(err && err.stack ? err.stack : err);
    return jsonOutput_({ ok: false, error: String(err && err.message ? err.message : err).slice(0, 500) });
  }
}

/**
 * Run once from the Apps Script editor opened through the intended Google Sheet.
 * Safe to run again: existing bot state and snapshots are preserved.
 */
function initializeDatabase() {
  const active = SpreadsheetApp.getActiveSpreadsheet();
  if (!active) {
    throw new Error(
      'No bound spreadsheet found. Open the intended Google Sheet, then Extensions > Apps Script, and run initializeDatabase from that project.'
    );
  }

  // Web-app executions cannot reliably infer the parent spreadsheet, so persist its ID here.
  scriptProps_().setProperty('SPREADSHEET_ID', active.getId());
  ensureSheet_(active, 'BotState', STATE_HEADERS);
  ensureSheet_(active, 'Events', EVENT_HEADERS);
  ensureSheet_(active, 'Positions', POSITION_HEADERS);

  // Do not reset an existing bot's paused flag or overwrite saved snapshots.
  ensureStateValueIfMissing_('paused', 'false');
  ensureStateValueIfMissing_('strategy_state_json', '{}');
  ensureStateValueIfMissing_('snapshot_json', '{}');
  ensureStateValueIfMissing_('updated_at', new Date().toISOString());

  active.toast('جداول Breakout V1 Dynamic بررسی و آماده شدند.', APP_NAME, 5);
  console.log('Initialized spreadsheet ID: ' + active.getId());
}

function ensureSheet_(spreadsheet, name, headers) {
  let sheet = spreadsheet.getSheetByName(name);
  if (!sheet) sheet = spreadsheet.insertSheet(name);
  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
  } else {
    const existing = sheet.getRange(1, 1, 1, headers.length).getValues()[0].map(String);
    if (headers.some((h, i) => existing[i] !== h)) {
      throw new Error('Unexpected headers in sheet ' + name + '. Do not rename or reorder its columns.');
    }
  }
  return sheet;
}

function getSpreadsheet_() {
  const id = scriptProps_().getProperty('SPREADSHEET_ID');
  if (!id) {
    throw new Error(
      'Missing Script Property: SPREADSHEET_ID. Open the intended Google Sheet > Extensions > Apps Script, run initializeDatabase once, then update the existing Web app deployment.'
    );
  }
  try {
    return SpreadsheetApp.openById(id);
  } catch (err) {
    throw new Error(
      'Cannot open the spreadsheet configured in SPREADSHEET_ID. Verify that the ID is from the intended Google Sheet and that the script owner has access. Details: ' +
      String(err && err.message ? err.message : err).slice(0, 180)
    );
  }
}

function getSheet_(name, headers) {
  return ensureSheet_(getSpreadsheet_(), name, headers);
}

function scriptProps_() { return PropertiesService.getScriptProperties(); }
function getRequiredProperty_(key) {
  const value = scriptProps_().getProperty(key);
  if (!value) throw new Error('Missing Script Property: ' + key);
  return value;
}
function isAuthorized_(key) {
  const expected = scriptProps_().getProperty('CONTROL_PLANE_TOKEN') || '';
  return !!expected && typeof key === 'string' && key.length === expected.length && key === expected;
}
function jsonOutput_(object) {
  return ContentService.createTextOutput(JSON.stringify(object)).setMimeType(ContentService.MimeType.JSON);
}
function safeJsonParse_(value, fallback) {
  try { return JSON.parse(value || ''); } catch (_) { return fallback; }
}
function asNumberOrNull_(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
function formatNumber_(value, digits) {
  const n = asNumberOrNull_(value);
  if (n === null) return '—';
  return n.toLocaleString('en-US', { maximumFractionDigits: digits === undefined ? 6 : digits });
}
function formatTime_(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number') {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '—';
    return date.toISOString().replace('T', ' ').replace('.000Z', ' UTC');
  }
  return String(value);
}
function sheetRowsAsObjects_(sheet, headers) {
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) return [];
  const keys = values[0].map(String);
  return values.slice(1).filter(row => row.some(cell => cell !== '' && cell !== null)).map(row => {
    const object = {};
    keys.forEach((key, i) => object[key] = row[i]);
    return object;
  });
}
function setStateValue_(key, value) {
  const sheet = getSheet_('BotState', STATE_HEADERS);
  const text = String(value);
  const chunkPrefix = key + '__chunk_';
  const last = sheet.getLastRow();
  const rows = last > 1 ? sheet.getRange(2, 1, last - 1, 3).getValues() : [];
  // Remove the previous value and any old chunks before writing the new version.
  for (let i = rows.length - 1; i >= 0; i--) {
    const storedKey = String(rows[i][0] || '');
    if (storedKey === key || storedKey.indexOf(chunkPrefix) === 0) {
      sheet.deleteRow(i + 2);
    }
  }
  const now = new Date().toISOString();
  // Google Sheets cells have a 50,000-character limit. Keep a margin below it.
  const chunkSize = 35000;
  if (text.length <= chunkSize) {
    sheet.appendRow([key, text, now]);
    return;
  }
  const count = Math.ceil(text.length / chunkSize);
  sheet.appendRow([key, '__CHUNKED__:' + count, now]);
  for (let i = 0; i < count; i++) {
    const part = text.slice(i * chunkSize, (i + 1) * chunkSize);
    const suffix = ('000' + i).slice(-3);
    sheet.appendRow([chunkPrefix + suffix, part, now]);
  }
}

function ensureStateValueIfMissing_(key, defaultValue) {
  const sheet = getSheet_('BotState', STATE_HEADERS);
  const last = sheet.getLastRow();
  const rows = last > 1 ? sheet.getRange(2, 1, last - 1, 3).getValues() : [];
  for (let i = 0; i < rows.length; i++) {
    if (String(rows[i][0]) === key) return;
  }
  sheet.appendRow([key, String(defaultValue), new Date().toISOString()]);
}
function getStateValues_() {
  const rows = sheetRowsAsObjects_(getSheet_('BotState', STATE_HEADERS), STATE_HEADERS);
  const raw = {};
  rows.forEach(row => raw[String(row.key)] = String(row.value));
  const output = {};
  Object.keys(raw).forEach(key => {
    const marker = raw[key];
    if (marker.indexOf('__CHUNKED__:') === 0) {
      const count = Number(marker.slice('__CHUNKED__:'.length));
      if (!Number.isInteger(count) || count < 1 || count > 100) {
        throw new Error('Invalid chunk metadata for BotState key: ' + key);
      }
      let joined = '';
      for (let i = 0; i < count; i++) {
        const suffix = ('000' + i).slice(-3);
        const partKey = key + '__chunk_' + suffix;
        if (raw[partKey] === undefined) throw new Error('Missing BotState chunk: ' + partKey);
        joined += raw[partKey];
      }
      output[key] = joined;
    } else if (key.indexOf('__chunk_') < 0) {
      output[key] = marker;
    }
  });
  return output;
}
function getBotState_() {
  const values = getStateValues_();
  return {
    paused: values.paused === 'true' || values.paused === '1',
    strategy_state: safeJsonParse_(values.strategy_state_json, {}),
    snapshot: safeJsonParse_(values.snapshot_json, {}),
    updated_at: values.updated_at || null
  };
}

function handleReport_(body) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  let events;
  try {
    events = Array.isArray(body.events) ? body.events.slice(0, 100) : [];
    const strategyState = body.strategy_state && typeof body.strategy_state === 'object' ? body.strategy_state : {};
    const snapshot = body.snapshot && typeof body.snapshot === 'object' ? body.snapshot : {};
    setStateValue_('strategy_state_json', JSON.stringify(strategyState));
    setStateValue_('snapshot_json', JSON.stringify(snapshot));
    setStateValue_('updated_at', new Date().toISOString());
    // Batch event persistence: one Sheets write for the Events tab instead of
    // one appendRow/openById round-trip per event.
    if (events.length) {
      const eventsSheet = getSheet_('Events', EVENT_HEADERS);
      const now = new Date().toISOString();
      const rows = events.map(evt => {
        evt = evt || {};
        const kind = String(evt.kind || 'event').slice(0, 100);
        const message = String(evt.message || kind).slice(0, 4000);
        const payload = evt.payload && typeof evt.payload === 'object' ? evt.payload : {};
        return [Utilities.getUuid(), now, kind, message, JSON.stringify(payload)];
      });
      const firstRow = eventsSheet.getLastRow() + 1;
      eventsSheet.getRange(firstRow, 1, rows.length, EVENT_HEADERS.length).setValues(rows);
      events.forEach(evt => {
        evt = evt || {};
        updatePositionFromEvent_(String(evt.kind || 'event').slice(0, 100),
          evt.payload && typeof evt.payload === 'object' ? evt.payload : {}, now);
      });
    }
  } finally {
    lock.releaseLock();
  }
  // One compact Telegram request per report keeps large scans responsive.
  // Full event detail remains available in the Events sheet.
  let notificationErrors = 0;
  let notificationsAttempted = 0;
  const notificationMessage = buildReportNotification_(events);
  if (notificationMessage) {
    notificationsAttempted = 1;
    try { telegramSend_(notificationMessage); }
    catch (err) {
      notificationErrors++;
      console.error('Telegram summary notification failed: ' + String(err).slice(0, 250));
    }
  }
  return jsonOutput_({
    ok: true,
    events_saved: events.length,
    notifications_attempted: notificationsAttempted,
    notification_errors: notificationErrors
  });
}

function buildReportNotification_(events) {
  const priority = {
    fatal_error: 0,
    entry_execution_uncertain: 0,
    top_coins_scan_failed: 0,
    demo_execution_universe_unavailable: 0,
    demo_execution_universe_empty: 0,
    symbol_error: 1,
    portfolio_risk_unknown: 1,
    pending_order_preflight_failed: 1,
    entry_protection_failed: 1,
    position_open: 2,
    position_closed: 2,
    top_coins_market_scan: 3,
    portfolio_run_summary: 4,
    position_monitor_summary: 4,
    run_end: 5
  };
  const indexed = (Array.isArray(events) ? events : [])
    .map((evt, index) => ({ evt: evt || {}, index: index }))
    .filter(item => Object.prototype.hasOwnProperty.call(priority, String(item.evt.kind || '')))
    .sort((a, b) => priority[String(a.evt.kind || '')] - priority[String(b.evt.kind || '')] || a.index - b.index);
  if (!indexed.length) return '';
  // Always preserve the final run status, even if higher-priority alerts exist.
  const runEnd = indexed.filter(item => String(item.evt.kind || '') === 'run_end').slice(-1)[0] || null;
  const chosen = indexed
    .filter(item => String(item.evt.kind || '') !== 'run_end')
    .slice(0, 5);
  if (runEnd) chosen.push(runEnd);
  chosen.sort((a, b) => a.index - b.index);
  const lines = ['🤖 گزارش Breakout V1 Dynamic'];
  chosen.forEach(item => {
    const evt = item.evt;
    const message = String(evt.message || evt.kind || 'event').trim().slice(0, 520);
    lines.push('\\n' + message);
  });
  if (indexed.length > chosen.length) {
    lines.push('\\n… ' + (indexed.length - chosen.length) + ' رویداد مهم دیگر در تب Events ذخیره شد.');
  }
  return lines.join('\\n').slice(0, 3500);
}

function saveEvent_(evt) {
  evt = evt || {};
  const kind = String(evt.kind || 'event').slice(0, 100);
  const message = String(evt.message || kind).slice(0, 4000);
  const payload = evt.payload && typeof evt.payload === 'object' ? evt.payload : {};
  const now = new Date().toISOString();
  const eventsSheet = getSheet_('Events', EVENT_HEADERS);
  eventsSheet.appendRow([Utilities.getUuid(), now, kind, message, JSON.stringify(payload)]);
  updatePositionFromEvent_(kind, payload, now);
}

function getPositionRowInfo_(positionId) {
  const sheet = getSheet_('Positions', POSITION_HEADERS);
  const last = sheet.getLastRow();
  if (last < 2) return { sheet: sheet, row: 0, object: null };
  const values = sheet.getRange(2, 1, last - 1, POSITION_HEADERS.length).getValues();
  for (let i = 0; i < values.length; i++) {
    if (String(values[i][0]) === String(positionId)) {
      const obj = {};
      POSITION_HEADERS.forEach((h, j) => obj[h] = values[i][j]);
      return { sheet: sheet, row: i + 2, object: obj };
    }
  }
  return { sheet: sheet, row: 0, object: null };
}
function savePositionRow_(info, obj) {
  const row = POSITION_HEADERS.map(h => obj[h] === undefined ? '' : obj[h]);
  if (info.row) info.sheet.getRange(info.row, 1, 1, POSITION_HEADERS.length).setValues([row]);
  else info.sheet.appendRow(row);
}
function updatePositionFromEvent_(kind, payload, now) {
  const id = payload.position_id ? String(payload.position_id) : '';
  if (!id) return;
  const info = getPositionRowInfo_(id);
  const old = info.object || {};
  const obj = Object.assign({}, old);
  obj.position_id = id;
  obj.updated_at = now;
  if (!obj.created_at) obj.created_at = now;
  if (kind === 'position_open' || kind === 'position_recovered') {
    obj.symbol = payload.symbol || 'UNKNOWN';
    obj.side = payload.side || 'UNKNOWN';
    obj.status = 'OPEN';
    obj.qty = asNumberOrNull_(payload.qty);
    obj.entry_price = asNumberOrNull_(payload.entry_price);
    obj.initial_stop = asNumberOrNull_(payload.initial_stop !== undefined ? payload.initial_stop : payload.sl_px);
    obj.current_stop = asNumberOrNull_(payload.current_stop !== undefined ? payload.current_stop : (payload.exchange_stop_last !== undefined ? payload.exchange_stop_last : payload.trail));
    obj.target = payload.tp_active ? asNumberOrNull_(payload.target !== undefined ? payload.target : (payload.exchange_target_last !== undefined ? payload.exchange_target_last : payload.tp_px)) : null;
    obj.opened_at_ms = asNumberOrNull_(payload.opened_at_ms !== undefined ? payload.opened_at_ms : payload.entry_time_ms) || Date.now();
    obj.data_json = JSON.stringify(payload);
  } else if (kind === 'position_update') {
    const stop = asNumberOrNull_(payload.current_stop);
    const target = asNumberOrNull_(payload.target);
    if (stop !== null) obj.current_stop = stop;
    if (target !== null) obj.target = target;
    obj.data_json = JSON.stringify(payload);
  } else if (kind === 'position_snapshot') {
    const qty = asNumberOrNull_(payload.qty);
    const entry = asNumberOrNull_(payload.entry_price);
    const stop = asNumberOrNull_(payload.current_stop);
    const target = asNumberOrNull_(payload.target);
    if (qty !== null) obj.qty = qty;
    if (entry !== null) obj.entry_price = entry;
    if (stop !== null) obj.current_stop = stop;
    if (target !== null) obj.target = target;
    obj.data_json = JSON.stringify(payload);
  } else if (kind === 'position_closed') {
    obj.status = 'CLOSED';
    const qty = asNumberOrNull_(payload.qty);
    const entry = asNumberOrNull_(payload.entry_price);
    const exitPrice = asNumberOrNull_(payload.exit_price);
    const closedAt = asNumberOrNull_(payload.closed_at_ms);
    const stop = asNumberOrNull_(payload.last_stop !== undefined ? payload.last_stop : payload.current_stop);
    const target = asNumberOrNull_(payload.target);
    const pnlModel = asNumberOrNull_(payload.net_pnl_model);
    const exchangePnl = asNumberOrNull_(payload.exchange_closed_pnl);
    if (qty !== null) obj.qty = qty;
    if (entry !== null) obj.entry_price = entry;
    if (exitPrice !== null) obj.exit_price = exitPrice;
    if (closedAt !== null) obj.closed_at_ms = closedAt;
    if (stop !== null) obj.current_stop = stop;
    if (target !== null) obj.target = target;
    if (pnlModel !== null) obj.net_pnl_model = pnlModel;
    if (exchangePnl !== null) obj.exchange_closed_pnl = exchangePnl;
    obj.exit_reason = payload.exit_reason || '';
    obj.data_json = JSON.stringify(payload);
  } else {
    return;
  }
  savePositionRow_(info, obj);
}

function telegramSend_(text, chatIdOverride) {
  const token = getRequiredProperty_('TELEGRAM_BOT_TOKEN');
  const chatId = chatIdOverride || getRequiredProperty_('TELEGRAM_CHAT_ID');
  const input = String(text || '');
  const chunks = [];
  let remaining = input;
  while (remaining.length > 3800) {
    let splitAt = remaining.lastIndexOf('\n', 3800);
    if (splitAt < 1000) splitAt = 3800;
    chunks.push(remaining.slice(0, splitAt));
    remaining = remaining.slice(splitAt).replace(/^\n+/, '');
  }
  if (remaining.length || chunks.length === 0) chunks.push(remaining);
  let lastData = null;
  chunks.forEach(chunk => {
    const response = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/sendMessage', {
      method: 'post', contentType: 'application/json', muteHttpExceptions: true,
      payload: JSON.stringify({ chat_id: String(chatId), text: chunk, disable_web_page_preview: true })
    });
    const data = safeJsonParse_(response.getContentText(), {});
    if (response.getResponseCode() < 200 || response.getResponseCode() >= 300 || !data.ok) {
      throw new Error('Telegram sendMessage failed: ' + response.getContentText().slice(0, 400));
    }
    lastData = data;
  });
  return lastData;
}

/**
 * HTML output is intentional: ContentService responses may be delivered through a
 * Google redirect (302), which some webhook clients treat as a failed delivery.
 */
function telegramWebhookAck_(text) {
  return HtmlService.createHtmlOutput(String(text || 'OK'));
}

/**
 * De-duplicate Telegram webhook retries. Telegram re-sends the same update_id when
 * it believes delivery failed; without this guard that can send /start's help text
 * repeatedly. Keep a bounded history so Script Properties stay small.
 */
function claimTelegramUpdate_(updateId) {
  if (updateId === undefined || updateId === null) return true;

  const id = String(updateId);
  const propertyKey = 'TELEGRAM_RECENT_UPDATE_IDS';
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const raw = scriptProps_().getProperty(propertyKey);
    const parsed = safeJsonParse_(raw, []);
    const recent = Array.isArray(parsed) ? parsed.map(String) : [];
    if (recent.indexOf(id) !== -1) return false;
    recent.push(id);
    while (recent.length > 150) recent.shift();
    scriptProps_().setProperty(propertyKey, JSON.stringify(recent));
    return true;
  } finally {
    lock.releaseLock();
  }
}

function handleTelegramWebhook_(e, params) {
  const secret = scriptProps_().getProperty('TELEGRAM_WEBHOOK_SECRET') || '';
  if (!secret || !params.hook || params.hook !== secret) {
    return telegramWebhookAck_('Forbidden');
  }

  let update = {};
  try {
    update = JSON.parse((e && e.postData && e.postData.contents) || '{}');
  } catch (_) {
    return telegramWebhookAck_('OK');
  }

  const message = update.message || update.edited_message;
  if (!message || !message.chat || message.chat.id === undefined || !message.text) {
    return telegramWebhookAck_('OK');
  }

  const chatId = String(message.chat.id);
  const allowedChat = scriptProps_().getProperty('TELEGRAM_CHAT_ID') || '';
  if (!allowedChat || chatId !== String(allowedChat)) {
    return telegramWebhookAck_('OK');
  }

  // Claim the update before sending a reply so webhook retries cannot spam the chat.
  try {
    if (!claimTelegramUpdate_(update.update_id)) {
      console.log('Ignoring duplicate Telegram update_id: ' + update.update_id);
      return telegramWebhookAck_('OK');
    }
  } catch (err) {
    console.error('Could not check Telegram update duplication: ' + err);
    // Continue once rather than silently dropping a user's command.
  }

  let answer = '';
  try {
    answer = executeTelegramCommand_(String(message.text).trim());
  } catch (err) {
    answer = 'خطا در خواندن اطلاعات ذخیره‌شده: ' +
      String(err && err.message ? err.message : err).slice(0, 300);
  }

  try {
    telegramSend_(answer, chatId);
  } catch (err) {
    console.error('Could not answer Telegram command: ' + err);
  }

  return telegramWebhookAck_('OK');
}

function executeTelegramCommand_(raw) {
  const parts = raw.split(/\s+/);
  const command = String(parts[0] || '').split('@')[0].toLowerCase();
  const args = parts.slice(1);
  if (command === '/start' || command === '/help') {
    return '🤖 کنترل Breakout V1 Dynamic\n\n/status — آخرین وضعیت ذخیره‌شده\n/positions — پوزیشن‌های باز ثبت‌شده\n/trades [تعداد] — معاملات بسته‌شده\n/trades page [شماره] — صفحه تاریخچه\n/events [تعداد] — رویدادهای اخیر\n/events page [شماره] — صفحه رویدادها\n/pause — توقف ورودهای جدید در اجرای بعدی\n/resume — فعال‌کردن ورودهای جدید\n\nاین فرمان‌ها فقط از داده‌های ذخیره‌شده در Google Sheets استفاده می‌کنند و برای پاسخ‌دادن صرافی را query نمی‌کنند.';
  }
  if (command === '/status') {
    const state = getBotState_();
    const snap = state.snapshot || {};
    const lines = [
      '📊 وضعیت ذخیره‌شده Breakout V1 Dynamic',
      'وضعیت آخرین اجرا: ' + (snap.run_status || 'نامشخص'),
      'شروع آخرین اجرا: ' + formatTime_(snap.run_started_at),
      'پایان آخرین اجرا: ' + formatTime_(snap.run_finished_at),
      'آخرین پاسخ موفق API: ' + formatTime_(snap.last_api_success_at),
      'نمادها: ' + (Array.isArray(snap.symbols) ? snap.symbols.join(', ') : '—'),
      'منبع داده: ' + (snap.signal_data_source || '—'),
      'سفارش‌گذاری فعال: ' + (snap.trading_enabled ? 'بله (تنظیم‌شده)' : 'خیر'),
      'ورودهای جدید: ' + (state.paused ? '⏸️ متوقف' : '✅ فعال'),
      'آخرین ثبت پایگاه داده: ' + formatTime_(state.updated_at)
    ];
    const perSymbol = snap.symbol_status || {};
    Object.keys(perSymbol).slice(0, 10).forEach(symbol => {
      const s = perSymbol[symbol] || {};
      const pos = s.position;
      lines.push('\n' + symbol + ' — آخرین کندل کامل: ' + formatTime_(s.last_closed_candle));
      lines.push('آخرین کندل پردازش‌شده: ' + formatTime_(s.last_processed_candle) + ' | سرمایه مدل: ' + formatNumber_(s.strategy_equity, 2));
      if (pos) lines.push('پوزیشن شناخته‌شده: ' + pos.side + ' | ورود ' + formatNumber_(pos.entry_price) + ' | حد ' + formatNumber_(pos.current_stop));
      if (s.reconciliation_pending) lines.push('⚠️ تطبیق تاریخچه خروج در انتظار است.');
    });
    lines.push('\nℹ️ این اطلاعات از آخرین snapshot ذخیره‌شده است، نه داده زنده صرافی.');
    return lines.join('\n');
  }
  if (command === '/positions') {
    const rows = sheetRowsAsObjects_(getSheet_('Positions', POSITION_HEADERS), POSITION_HEADERS)
      .filter(p => String(p.status) === 'OPEN').sort((a, b) => Number(b.opened_at_ms || 0) - Number(a.opened_at_ms || 0)).slice(0, 20);
    if (!rows.length) return 'هیچ پوزیشن بازی در پایگاه داده ثبت نشده است.';
    return '📍 پوزیشن‌های باز ثبت‌شده در Google Sheets\n\n' + rows.map((p, i) => {
      const d = safeJsonParse_(p.data_json, {});
      return (i + 1) + ') ' + p.symbol + ' ' + p.side + '\n' +
        'حجم: ' + formatNumber_(p.qty) + ' | ورود: ' + formatNumber_(p.entry_price) + '\n' +
        'حد ضرر اولیه: ' + formatNumber_(p.initial_stop) + ' | حد فعلی: ' + formatNumber_(p.current_stop) + '\n' +
        'حد سود: ' + formatNumber_(p.target) + ' | اهرم آخرین گزارش: ' + formatNumber_(d.leverage_last_seen) + 'x\n' +
        'قیمت مرجع آخرین گزارش: ' + formatNumber_(d.mark_price_last_seen) + '\n' +
        'PnL شناور آخرین گزارش: ' + formatNumber_(d.unrealised_pnl_last_seen, 4) + ' USDT\n' +
        'زمان ورود: ' + formatTime_(p.opened_at_ms) + '\nشناسه: ' + p.position_id;
    }).join('\n\n');
  }
  if (command === '/trades') {
    const pageMode = String(args[0] || '').toLowerCase() === 'page';
    const page = pageMode ? Math.max(1, parseInt(args[1] || '1', 10) || 1) : 1;
    const n = pageMode ? 20 : Math.min(30, Math.max(1, parseInt(args[0] || '10', 10) || 10));
    const all = sheetRowsAsObjects_(getSheet_('Positions', POSITION_HEADERS), POSITION_HEADERS)
      .filter(p => String(p.status) === 'CLOSED').sort((a, b) => Number(b.closed_at_ms || 0) - Number(a.closed_at_ms || 0));
    if (!all.length) return 'هنوز معامله بسته‌شده‌ای در پایگاه داده ثبت نشده است.';
    const pages = Math.max(1, Math.ceil(all.length / n));
    const rows = all.slice((page - 1) * n, page * n);
    if (!rows.length) return 'این صفحه خالی است؛ تعداد کل صفحات: ' + pages;
    return '📚 تاریخچه معاملات بسته‌شده — صفحه ' + page + '/' + pages + '\nنمایش ' + rows.length + ' مورد از ' + all.length + '\n\n' + rows.map((p, i) =>
      ((page - 1) * n + i + 1) + ') ' + p.symbol + ' ' + p.side + '\nورود: ' + formatNumber_(p.entry_price) + ' → خروج: ' + formatNumber_(p.exit_price) + '\n' +
      'حجم: ' + formatNumber_(p.qty) + ' | PnL مدل: ' + formatNumber_(p.net_pnl_model, 4) + ' USDT\n' +
      'PnL گزارش صرافی: ' + formatNumber_(p.exchange_closed_pnl, 4) + ' USDT\nعلت: ' + (p.exit_reason || '—') + '\nبسته‌شدن: ' + formatTime_(p.closed_at_ms)
    ).join('\n\n');
  }
  if (command === '/events') {
    const pageMode = String(args[0] || '').toLowerCase() === 'page';
    const page = pageMode ? Math.max(1, parseInt(args[1] || '1', 10) || 1) : 1;
    const n = pageMode ? 20 : Math.min(30, Math.max(1, parseInt(args[0] || '10', 10) || 10));
    const all = sheetRowsAsObjects_(getSheet_('Events', EVENT_HEADERS), EVENT_HEADERS).sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    const pages = Math.max(1, Math.ceil(all.length / n));
    const rows = all.slice((page - 1) * n, page * n);
    if (!rows.length) return 'رویدادی در این صفحه ثبت نشده است.';
    return '🧾 رویدادها — صفحه ' + page + '/' + pages + '\n\n' + rows.map(e => '[' + e.created_at + '] ' + e.kind + '\n' + e.message).join('\n\n');
  }
  if (command === '/pause' || command === '/resume') {
    const lock = LockService.getScriptLock();
    lock.waitLock(15000);
    try {
      const paused = command === '/pause';
      setStateValue_('paused', paused ? 'true' : 'false');
      const message = paused ? 'کاربر ورودهای جدید را با /pause متوقف کرد.' : 'کاربر ورودهای جدید را با /resume فعال کرد.';
      saveEvent_({ kind: paused ? 'manual_pause' : 'manual_resume', message: message, payload: {} });
      return paused
        ? '⏸️ ورودهای جدید در اجرای بعدی متوقف می‌شوند. مدیریت پوزیشن‌های باز ادامه می‌یابد و حد ضرر ثبت‌شده در صرافی حذف نمی‌شود.'
        : '▶️ ورودهای جدید در اجرای بعدی دوباره فعال می‌شوند.';
    } finally { lock.releaseLock(); }
  }
  return 'فرمان ناشناخته است. از /help استفاده کن.';
}
