/**
 * Breakout V1 Dynamic — Google Apps Script scheduler bridge.
 * Add this as a separate file named CloudScheduler.gs in the existing bound
 * Apps Script project. It does not replace or edit the existing Code.gs.
 *
 * Apps Script is the clock/dispatcher. The Python trading engine still runs on
 * GitHub-hosted Linux runners; no local computer remains powered on.
 */
const B1D_GH_API_ROOT = 'https://api.github.com';
const B1D_ACTIVE_RUN_STATES = { queued: true, requested: true, waiting: true, pending: true, in_progress: true };
const B1D_SCHEDULER_HANDLER = 'breakoutCloudSchedulerTick';

function installBreakoutCloudScheduler() {
  const cfg = b1d_getCloudConfig_();
  b1d_validateGitHubConfig_(cfg);
  // Validate token, repository, and the exact workflow filenames before creating a trigger.
  b1d_getJson_('/repos/' + cfg.owner + '/' + cfg.repo + '/actions/workflows/' + encodeURIComponent(cfg.botWorkflow));
  b1d_getJson_('/repos/' + cfg.owner + '/' + cfg.repo + '/actions/workflows/' + encodeURIComponent(cfg.monitorWorkflow));

  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === B1D_SCHEDULER_HANDLER) ScriptApp.deleteTrigger(trigger);
  });
  ScriptApp.newTrigger(B1D_SCHEDULER_HANDLER).timeBased().everyMinutes(5).create();
  PropertiesService.getScriptProperties().setProperty('B1D_SCHEDULER_ENABLED', 'true');
  PropertiesService.getScriptProperties().setProperty('B1D_SCHEDULER_INSTALLED_AT', new Date().toISOString());
  console.log('Breakout V1 Cloud Scheduler installed: 5-minute monitor cadence; 4-hour analysis cadence; UTC clock.');
}

function testBreakoutGitHubConnection() {
  const cfg = b1d_getCloudConfig_();
  b1d_validateGitHubConfig_(cfg);
  const bot = b1d_getJson_('/repos/' + cfg.owner + '/' + cfg.repo + '/actions/workflows/' + encodeURIComponent(cfg.botWorkflow));
  const monitor = b1d_getJson_('/repos/' + cfg.owner + '/' + cfg.repo + '/actions/workflows/' + encodeURIComponent(cfg.monitorWorkflow));
  if (bot.state !== 'active' || monitor.state !== 'active') {
    throw new Error('Both bot.yml and position-monitor.yml must be active workflows on the repository default branch.');
  }
  const result = {
    ok: true,
    repository: cfg.owner + '/' + cfg.repo,
    ref: cfg.ref,
    bot_workflow: bot.name,
    monitor_workflow: monitor.name,
    bot_state: bot.state,
    monitor_state: monitor.state
  };
  console.log(JSON.stringify(result));
  return result;
}

function breakoutCloudSchedulerTick() {
  const props = PropertiesService.getScriptProperties();
  if (props.getProperty('B1D_SCHEDULER_ENABLED') !== 'true') return;
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) {
    console.log('Scheduler tick skipped: another scheduler execution holds the lock.');
    return;
  }
  try {
    const cfg = b1d_getCloudConfig_();
    const nowMs = Date.now();
    const previousDispatch = Number(props.getProperty('B1D_LAST_DISPATCH_MS') || 0);
    // Protect against duplicate/near-duplicate time-trigger deliveries.
    if (previousDispatch && (nowMs - previousDispatch) < 210000) {
      console.log('Scheduler tick skipped: a workflow was dispatched less than 3.5 minutes ago.');
      return;
    }

    // Fail closed: if GitHub status cannot be read, do not dispatch another job.
    const runs = b1d_getJson_('/repos/' + cfg.owner + '/' + cfg.repo + '/actions/runs?branch=' + encodeURIComponent(cfg.ref) + '&per_page=100');
    const active = (runs.workflow_runs || []).filter(function(run) {
      const path = String(run.path || '');
      const isBotOrMonitor = path.indexOf(cfg.botWorkflow) >= 0 || path.indexOf(cfg.monitorWorkflow) >= 0;
      return isBotOrMonitor && !!B1D_ACTIVE_RUN_STATES[String(run.status || '')];
    });
    if (active.length) {
      const brief = active.slice(0, 5).map(function(run) {
        return String(run.name || run.path) + ':' + String(run.status) + '#' + String(run.id);
      }).join(', ');
      props.setProperty('B1D_LAST_SCHEDULER_RESULT', 'busy ' + new Date().toISOString() + ' ' + brief);
      console.log('No dispatch: an existing bot/monitor workflow is active: ' + brief);
      return;
    }

    const now = new Date();
    const blockHour = Math.floor(now.getUTCHours() / 4) * 4;
    const minuteIntoFourHourBlock = (now.getUTCHours() % 4) * 60 + now.getUTCMinutes();
    const slotKey = Utilities.formatDate(
      new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), blockHour, 0, 0)),
      'UTC', 'yyyy-MM-dd\'T\'HH:00\'Z\''
    );
    const lastAnalysisSlot = props.getProperty('B1D_LAST_ANALYSIS_SLOT_UTC') || '';
    // The Python runner rejects entries older than 90 minutes after the 4H candle closes.
    // Dispatch with a small reserve for GitHub queue/startup time.
    const analysisDue = minuteIntoFourHourBlock <= 85 && lastAnalysisSlot !== slotKey;
    const workflowFile = analysisDue ? cfg.botWorkflow : cfg.monitorWorkflow;
    const runKind = analysisDue ? 'analysis' : 'monitor';

    b1d_dispatchWorkflow_(cfg, workflowFile);
    props.setProperty('B1D_LAST_DISPATCH_MS', String(nowMs));
    props.setProperty('B1D_LAST_DISPATCH_KIND', runKind);
    props.setProperty('B1D_LAST_SCHEDULER_RESULT', 'dispatched ' + runKind + ' ' + new Date().toISOString());
    if (analysisDue) props.setProperty('B1D_LAST_ANALYSIS_SLOT_UTC', slotKey);
    console.log('Dispatched ' + runKind + ' workflow: ' + workflowFile + ' at ' + new Date().toISOString());
  } catch (err) {
    const message = String(err && err.message ? err.message : err).slice(0, 500);
    props.setProperty('B1D_LAST_SCHEDULER_RESULT', 'error ' + new Date().toISOString() + ' ' + message);
    console.error('Breakout scheduler error (no order was submitted by Apps Script): ' + message);
    throw err;
  } finally {
    lock.releaseLock();
  }
}

function removeBreakoutCloudScheduler() {
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === B1D_SCHEDULER_HANDLER) ScriptApp.deleteTrigger(trigger);
  });
  const props = PropertiesService.getScriptProperties();
  props.setProperty('B1D_SCHEDULER_ENABLED', 'false');
  props.setProperty('B1D_LAST_SCHEDULER_RESULT', 'disabled ' + new Date().toISOString());
  console.log('Breakout V1 Cloud Scheduler disabled.');
}

function getBreakoutCloudSchedulerStatus() {
  const props = PropertiesService.getScriptProperties();
  const status = {
    enabled: props.getProperty('B1D_SCHEDULER_ENABLED') === 'true',
    installed_at: props.getProperty('B1D_SCHEDULER_INSTALLED_AT') || null,
    last_dispatch_kind: props.getProperty('B1D_LAST_DISPATCH_KIND') || null,
    last_analysis_slot_utc: props.getProperty('B1D_LAST_ANALYSIS_SLOT_UTC') || null,
    last_result: props.getProperty('B1D_LAST_SCHEDULER_RESULT') || null,
    trigger_count: ScriptApp.getProjectTriggers().filter(function(t) {
      return t.getHandlerFunction() === B1D_SCHEDULER_HANDLER;
    }).length
  };
  console.log(JSON.stringify(status, null, 2));
  return status;
}

function b1d_getCloudConfig_() {
  const p = PropertiesService.getScriptProperties();
  const cfg = {
    token: p.getProperty('B1D_GITHUB_TOKEN') || '',
    owner: p.getProperty('B1D_GITHUB_OWNER') || '',
    repo: p.getProperty('B1D_GITHUB_REPO') || '',
    ref: p.getProperty('B1D_GITHUB_REF') || 'main',
    botWorkflow: p.getProperty('B1D_BOT_WORKFLOW') || 'bot.yml',
    monitorWorkflow: p.getProperty('B1D_MONITOR_WORKFLOW') || 'position-monitor.yml'
  };
  b1d_validateGitHubConfig_(cfg);
  return cfg;
}

function b1d_validateGitHubConfig_(cfg) {
  if (!cfg.token || cfg.token.length < 20) throw new Error('Missing Script Property B1D_GITHUB_TOKEN.');
  if (!/^[A-Za-z0-9_.-]+$/.test(cfg.owner)) throw new Error('Invalid or missing B1D_GITHUB_OWNER.');
  if (!/^[A-Za-z0-9_.-]+$/.test(cfg.repo)) throw new Error('Invalid or missing B1D_GITHUB_REPO.');
  if (!/^[A-Za-z0-9_.-]+$/.test(cfg.ref)) throw new Error('Invalid B1D_GITHUB_REF (use a branch name such as main).');
  if (!/^[A-Za-z0-9_.-]+\.yml$/.test(cfg.botWorkflow) || !/^[A-Za-z0-9_.-]+\.yml$/.test(cfg.monitorWorkflow)) {
    throw new Error('Workflow settings must be YAML filenames such as bot.yml and position-monitor.yml.');
  }
}

function b1d_getJson_(path) {
  return b1d_githubRequest_('get', path, null, [200]);
}

function b1d_dispatchWorkflow_(cfg, workflowFile) {
  const path = '/repos/' + cfg.owner + '/' + cfg.repo + '/actions/workflows/' + encodeURIComponent(workflowFile) + '/dispatches';
  b1d_githubRequest_('post', path, { ref: cfg.ref }, [204]);
}

function b1d_githubRequest_(method, path, payload, acceptedCodes) {
  const cfg = b1d_getConfigWithoutValidation_();
  const options = {
    method: method,
    headers: {
      Authorization: 'Bearer ' + cfg.token,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2026-03-10'
    },
    muteHttpExceptions: true
  };
  if (payload !== null && payload !== undefined) {
    options.contentType = 'application/json';
    options.payload = JSON.stringify(payload);
  }
  const response = UrlFetchApp.fetch(B1D_GH_API_ROOT + path, options);
  const code = response.getResponseCode();
  const body = response.getContentText();
  if (acceptedCodes.indexOf(code) < 0) {
    // Never include Authorization headers or token values in an exception/log.
    throw new Error('GitHub API returned HTTP ' + code + ' for ' + path + ': ' + body.slice(0, 300));
  }
  if (!body) return {};
  try { return JSON.parse(body); }
  catch (_) { throw new Error('GitHub API returned non-JSON data for ' + path); }
}

function b1d_getConfigWithoutValidation_() {
  const token = PropertiesService.getScriptProperties().getProperty('B1D_GITHUB_TOKEN') || '';
  if (!token) throw new Error('Missing Script Property B1D_GITHUB_TOKEN.');
  return { token: token };
}
