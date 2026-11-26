#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class FakeRange {
  constructor(sheet, row, column, numRows, numColumns) {
    this.sheet = sheet;
    this.row = row;
    this.column = column;
    this.numRows = numRows;
    this.numColumns = numColumns;
  }
  getValues() {
    this.sheet.readCalls += 1;
    const result = [];
    for (let r = 0; r < this.numRows; r += 1) {
      const source = this.sheet.rows[this.row - 1 + r] || [];
      const row = [];
      for (let c = 0; c < this.numColumns; c += 1) {
        const value = source[this.column - 1 + c];
        row.push(value === undefined ? '' : value);
      }
      result.push(row);
    }
    return result;
  }
  setValues(values) {
    if (!Array.isArray(values) || values.length !== this.numRows) {
      throw new Error('FakeRange setValues row count mismatch');
    }
    values.forEach((source, r) => {
      if (!Array.isArray(source) || source.length !== this.numColumns) {
        throw new Error('FakeRange setValues column count mismatch');
      }
      const index = this.row - 1 + r;
      while (this.sheet.rows.length <= index) this.sheet.rows.push([]);
      for (let c = 0; c < this.numColumns; c += 1) {
        this.sheet.rows[index][this.column - 1 + c] = source[c];
      }
    });
    this.sheet.writeCalls += 1;
    return this;
  }
  setFontWeight() { return this; }
}

class FakeSheet {
  constructor(name) {
    this.name = name;
    this.rows = [];
    this.readCalls = 0;
    this.writeCalls = 0;
  }
  getLastRow() { return this.rows.length; }
  getRange(row, column, numRows, numColumns) {
    return new FakeRange(this, row, column, numRows, numColumns);
  }
  getDataRange() {
    const columns = Math.max(1, ...this.rows.map(row => row.length));
    return this.getRange(1, 1, Math.max(1, this.rows.length), columns);
  }
  appendRow(row) {
    this.rows.push(row.slice());
    this.writeCalls += 1;
    return this;
  }
  deleteRow(rowNumber) {
    this.rows.splice(rowNumber - 1, 1);
    this.writeCalls += 1;
  }
  setFrozenRows() {}
}

class FakeSpreadsheet {
  constructor() { this.sheets = new Map(); }
  getSheetByName(name) { return this.sheets.get(name) || null; }
  insertSheet(name) {
    const sheet = new FakeSheet(name);
    this.sheets.set(name, sheet);
    return sheet;
  }
  toast() {}
}

function makeContext() {
  const spreadsheet = new FakeSpreadsheet();
  const properties = new Map([
    ['SPREADSHEET_ID', 'test-sheet-id'],
    ['TELEGRAM_BOT_TOKEN', 'test-telegram-token'],
    ['TELEGRAM_CHAT_ID', '123456']
  ]);
  const telegramRequests = [];
  let uuid = 0;
  const context = {
    console: {
      log() {},
      warn() {},
      error() {}
    },
    SpreadsheetApp: {
      openById(id) {
        assert.equal(id, 'test-sheet-id');
        return spreadsheet;
      },
      getActiveSpreadsheet() { return spreadsheet; }
    },
    PropertiesService: {
      getScriptProperties() {
        return {
          getProperty(key) { return properties.has(key) ? properties.get(key) : null; },
          setProperty(key, value) { properties.set(key, String(value)); },
          deleteProperty(key) { properties.delete(key); }
        };
      }
    },
    LockService: {
      getScriptLock() {
        return { waitLock() {}, tryLock() { return true; }, releaseLock() {} };
      }
    },
    ContentService: {
      MimeType: { JSON: 'application/json' },
      createTextOutput(content) {
        return {
          content: String(content),
          setMimeType() { return this; }
        };
      }
    },
    HtmlService: {
      createHtmlOutput(content) { return { content: String(content) }; }
    },
    Utilities: {
      getUuid() { uuid += 1; return 'uuid-' + uuid; },
      formatDate(date) { return date.toISOString(); }
    },
    UrlFetchApp: {
      fetch(url, options) {
        telegramRequests.push({ url, options });
        return {
          getResponseCode() { return 200; },
          getContentText() { return '{"ok":true,"result":{"message_id":1}}'; }
        };
      }
    },
    ScriptApp: {
      getProjectTriggers() { return []; }
    },
    Date,
    JSON,
    Math,
    Object,
    Array,
    String,
    Number,
    RegExp,
    Error,
    Map,
    Set
  };
  vm.createContext(context);
  return { context, spreadsheet, telegramRequests, properties };
}

const sourcePath = path.join(__dirname, '..', 'google-apps-script', 'Code.gs');
const source = fs.readFileSync(sourcePath, 'utf8');
const { context, spreadsheet, telegramRequests } = makeContext();
vm.runInContext(source, context, { filename: 'Code.gs' });

const notification = context.buildReportNotification_([
  { kind: 'runner_booting', message: 'BOOT' },
  { kind: 'run_start', message: 'START' }
]);
assert.ok(notification.includes('\nSTART'), 'startup notification should contain a real newline');
assert.ok(!notification.includes('\\nSTART'), 'startup notification must not contain literal backslash-n');

const events = [];
for (let i = 0; i < 125; i += 1) {
  events.push({ kind: 'warmup', message: 'warmup-' + i, payload: { symbol: 'COIN' + i } });
}
events.push({
  kind: 'position_open',
  message: 'position opened',
  payload: {
    position_id: 'position-test-1', symbol: 'BTCUSDT', side: 'Buy',
    qty: 0.01, entry_price: 50000, initial_stop: 49000,
    current_stop: 49000, target: 52000, tp_active: true, opened_at_ms: 1000
  }
});
events.push({
  kind: 'position_update',
  message: 'position stop updated',
  payload: { position_id: 'position-test-1', current_stop: 50500, target: 52000 }
});
events.push({
  kind: 'position_closed',
  message: 'position closed',
  payload: {
    position_id: 'position-test-1', qty: 0.01, entry_price: 50000,
    exit_price: 51000, closed_at_ms: 2000, last_stop: 50500,
    target: 52000, net_pnl_model: 9.5, exchange_closed_pnl: 9.4, exit_reason: 'test'
  }
});
events.push({
  kind: 'top_coins_market_scan',
  message: 'market scan complete: 100/100',
  payload: { oversized_detail: 'x'.repeat(60000) }
});
events.push({
  kind: 'run_end',
  message: 'RUN FINISHED SUCCESSFULLY',
  payload: { status: 'success' }
});

const reportSnapshot = {
  run_status: 'success',
  run_mode: 'four_hour_analysis_and_execution',
  run_started_at: '2026-11-26 10:00:00 UTC',
  run_finished_at: '2026-11-26 10:00:45 UTC',
  analyze_top_coins: true,
  trading_enabled: false,
  market_scan: { requested_count: 100, analyzed_count: 100, error_count: 0, complete: true }
};
const response = context.handleReport_({
  events,
  strategy_state: { symbols: {} },
  snapshot: reportSnapshot
});
const responseData = JSON.parse(response.content);
assert.equal(responseData.ok, true);
assert.equal(responseData.events_received, events.length);
assert.equal(responseData.events_saved, events.length, 'all events above 100 must be persisted');
assert.equal(responseData.run_end_events_saved, 1, 'run_end must be counted and persisted');
assert.equal(responseData.notification_status, 'sent');
assert.equal(responseData.delivery_metadata_saved, true);
assert.equal(telegramRequests.length, 1, 'one compact report should cause one Telegram request');

const eventsSheet = spreadsheet.getSheetByName('Events');
assert.equal(eventsSheet.getLastRow() - 1, events.length);
const storedKinds = eventsSheet.rows.slice(1).map(row => row[2]);
assert.equal(storedKinds[storedKinds.length - 1], 'run_end', 'the final run_end event must not be truncated');
const largePayloadRow = eventsSheet.rows.find(row => row[2] === 'top_coins_market_scan');
const compactPayload = JSON.parse(largePayloadRow[4]);
assert.equal(compactPayload._truncated, true, 'oversized event payload should be compacted');
assert.ok(largePayloadRow[4].length <= 40000, 'event cell must remain below the safe cell limit');

const positionsSheet = spreadsheet.getSheetByName('Positions');
assert.equal(positionsSheet.getLastRow(), 2, 'one position record should be persisted');
assert.equal(positionsSheet.rows[1][0], 'position-test-1');
assert.equal(positionsSheet.rows[1][3], 'CLOSED', 'open/update/close events must be applied in order');
assert.equal(Number(positionsSheet.rows[1][11]), 51000);

const storedState = context.getBotState_();
assert.equal(storedState.snapshot.report_delivery.events_saved, events.length);
assert.equal(storedState.snapshot.report_delivery.notification_status, 'sent');

const beforeOverflow = eventsSheet.getLastRow();
assert.throws(
  () => context.handleReport_({
    events: new Array(2001).fill({ kind: 'warmup', message: 'overflow', payload: {} }),
    strategy_state: {},
    snapshot: reportSnapshot
  }),
  /supported maximum/,
  'over-limit report should fail explicitly instead of silently discarding events'
);
assert.equal(eventsSheet.getLastRow(), beforeOverflow, 'rejected report must not append partial rows');

context.setStateValue_('preserve-old-value', 'previous-good-value');
assert.throws(
  () => context.setStateValue_('preserve-old-value', 'x'.repeat(35000 * 101)),
  /100-chunk limit/,
  'oversized BotState values should fail before deleting the previous value'
);
assert.equal(context.getStateValues_()['preserve-old-value'], 'previous-good-value');

console.log('PASS: real newline formatting and startup notifications');
console.log('PASS: complete event persistence beyond 100 items and run_end retention');
console.log('PASS: event-cell compaction below the safe Sheets cell limit');
console.log('PASS: batched position lifecycle update (open -> update -> closed)');
console.log('PASS: report-delivery telemetry is stored in BotState snapshot');
console.log('PASS: oversized event batches fail closed without partial append');
console.log('PASS: oversized state values preserve the previous good value');
