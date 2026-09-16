import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const files = Object.fromEntries([
  '06-technoeconomic', '08-dashboard-state', '09-validation-run', '10-annual-run', '14-agent-state',
  '15-chat-action-cards', '17-agent-activity-rendering', '18-agent-actions', '19-chat-send-and-cache',
].map(name => [name, readFileSync(new URL('../frontend/js/' + name + '.js', import.meta.url), 'utf8')]));
function extract(name) {
  for (const source of Object.values(files)) {
    const match = source.match(new RegExp('        (?:async )?function ' + name + '\\([^]*?(?=\\n        (?:async )?function |$)'));
    if (match) return match[0];
  }
  throw new Error('Missing function ' + name);
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}
const noop = () => {};
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture() {
  let timerId = 0;
  const timers = new Map();
  const setTimer = (callback, delay) => {timers.set(++timerId, {callback, delay}); return timerId;};
  const clearTimer = id => timers.delete(id);
  const context = vm.createContext({
    AbortController, Response, ReadableStream, DOMException, Error, Map, Set,
    window: {setTimeout: setTimer, clearTimeout: clearTimer}, setTimeout: setTimer, clearTimeout: clearTimer,
    agentJobPollTimers: new Map(), agentJobPollRequests: new Map(), agentJobStartedAt: new Map(),
    agentJobSnapshots: new Map(), agentProposalSnapshots: new Map(), agentStateRefreshRevision: 0, agentWorkspaceRevision: 0,
    agentMutationRevision: 0, agentActivityOpenRevision: 0,
    activeChatAbortController: null, setSending: noop,
    agentRefreshBtn: {disabled: false}, latestJobId: null, annualLatestJobId: null,
    currentRunState: null, annualRunState: null, activeView: 'validation',
    agentServerState: {promoted_baselines: {validation: null, annual: null}, recent_job_ids: []},
    AGENT_POLL_MAX_FAILURES: 2, STATUS_POLL_MAX_DELAY_MS: 8000, MAX_RECENT_AGENT_RUNS: 20,
    syncTrackedMainRunFromAgentJob: noop, isAgentParameterSweepJob: () => false,
    renderAgentJobUpdate: noop, announceAgentCompletion: noop, rememberTerminalAgentJob: noop,
    moveAgentActivityToHistory: noop, reconcileTerminalAgentCards: noop,
    reconcileAgentActivityFilterAfterRefresh: noop, renderAgentActivity: noop,
    recoverSavedNonterminalActionJobs: async () => {}, updateAgentContext: noop,
    agentJobActivityKey: job => job.job_id, agentActivityTimestamp: () => 0,
    appendSystemNotice: noop, loadCurrentCalibration: async () => {},
  });
  vm.runInContext([
    'fetchWithDashboardTimeout', 'readAgentResponse', 'isAgentJobTerminal', 'putAgentJob',
    'putAgentProposal', 'normalizeAgentState', 'reconcileAgentSnapshots', 'dashboardOwnsJobPoll',
    'invalidateAgentJobPoll', 'scheduleAgentJobPoll', 'pollAgentJob', 'refreshAgentState',
    'invalidateAgentStateRefresh', 'postAgentAction',
  ].map(extract).join('\n'), context);
  return {context, timers};
}
function stateResponse(jobs, proposals = []) {
  return Response.json({jobs, proposals, promoted_baselines: {}, recent_job_ids: jobs.map(job => job.job_id)});
}

test('request deadline covers a stalled response body and releases its timer', async () => {
  const {context, timers} = fixture();
  context.fetch = async (_url, {signal}) => new Response(new ReadableStream({
    start(controller) {signal.addEventListener('abort', () => controller.error(signal.reason));},
  }));
  const request = context.fetchWithDashboardTimeout('/status', {}, 17);
  await tick();
  assert.equal(timers.size, 1, 'deadline must survive response headers');
  const deadline = [...timers.values()][0];
  assert.equal(deadline.delay, 17);
  deadline.callback();
  await assert.rejects(request, {name: 'AbortError'});
  assert.equal(timers.size, 0);
});

test('request deadline aborts stalled headers and caller cancellation remains effective', async () => {
  const {context, timers} = fixture();
  let calls = 0;
  context.fetch = (_url, {signal}) => {
    calls += 1;
    return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason)));
  };
  const deadlineRequest = context.fetchWithDashboardTimeout('/status', {}, 17);
  [...timers.values()][0].callback();
  await assert.rejects(deadlineRequest, {name: 'AbortError'});
  const caller = new AbortController();
  const cancelled = context.fetchWithDashboardTimeout('/status', {signal: caller.signal});
  caller.abort();
  await assert.rejects(cancelled, {name: 'AbortError'});
  const before = calls;
  await assert.rejects(context.fetchWithDashboardTimeout('/status', {signal: caller.signal}), {name: 'AbortError'});
  assert.equal(calls, before, 'already cancelled requests must never be sent');
  assert.equal(timers.size, 0);
});

test('completed responses preserve original metadata, headers, JSON and bodyless responses', async () => {
  const {context, timers} = fixture();
  const original = Response.json({detail: 'missing'}, {status: 404, headers: {'X-Test': 'kept'}});
  context.fetch = async () => original;
  const response = await context.fetchWithDashboardTimeout('/missing');
  assert.equal(response, original, 'URL, redirect and response-type metadata remain on the original response');
  assert.equal(response.status, 404);
  assert.equal(response.ok, false);
  assert.equal(response.headers.get('X-Test'), 'kept');
  assert.deepEqual(await response.json(), {detail: 'missing'});
  context.fetch = async () => new Response(null, {status: 204});
  assert.equal((await context.fetchWithDashboardTimeout('/empty')).status, 204);
  assert.equal(timers.size, 0);
});

test('late status success or failure cannot recreate a removed job', async () => {
  for (const succeeds of [true, false]) {
    const {context, timers} = fixture();
    context.putAgentJob({job_id: 'j1', state: 'running'});
    const pending = deferred();
    context.fetchWithDashboardTimeout = () => pending.promise;
    const poll = context.pollAgentJob('j1');
    context.invalidateAgentJobPoll('j1');
    context.agentJobSnapshots.delete('j1');
    if (succeeds) pending.resolve(Response.json({job_id: 'j1', state: 'running'}));
    else pending.reject(new Error('offline'));
    await poll;
    assert.equal(context.agentJobSnapshots.has('j1'), false);
    assert.equal(context.agentJobPollRequests.size, 0);
    assert.equal(timers.size, 0);
  }
});

test('concurrent Agent polls share one owner and cannot overwrite a newer local update', async () => {
  const {context} = fixture();
  context.putAgentJob({job_id: 'j1', state: 'running'});
  const pending = deferred(); let calls = 0;
  context.fetchWithDashboardTimeout = () => {calls += 1; return pending.promise;};
  const poll = context.pollAgentJob('j1');
  await context.pollAgentJob('j1');
  assert.equal(calls, 1);
  context.putAgentJob({job_id: 'j1', state: 'running', cancel_requested: true});
  pending.resolve(Response.json({job_id: 'j1', state: 'running', cancel_requested: false}));
  await poll;
  assert.equal(context.agentJobSnapshots.get('j1').cancel_requested, true);
  assert.equal(context.agentJobPollRequests.size, 0);
  assert.equal(context.agentJobPollTimers.size, 1, 'newer nonterminal state still receives future updates');
});

test('Agent polling yields to direct Calibration and Annual polling, then recovers paused monitoring', async () => {
  for (const mode of ['validation', 'annual']) {
    const {context, timers} = fixture();
    context.putAgentJob({job_id: 'j1', state: 'running'});
    const idKey = mode === 'annual' ? 'annualLatestJobId' : 'latestJobId';
    const stateKey = mode === 'annual' ? 'annualRunState' : 'currentRunState';
    context[idKey] = 'j1'; context[stateKey] = {state: 'running'};
    context.fetchWithDashboardTimeout = () => {throw new Error('duplicate status request');};
    context.scheduleAgentJobPoll('j1');
    await context.pollAgentJob('j1');
    assert.equal(timers.size, 0);
    assert.equal(context.agentJobPollRequests.size, 0);
    context[stateKey] = {state: 'monitoring_error'};
    context.scheduleAgentJobPoll('j1');
    assert.equal(timers.size, 1);
  }
});

test('overlapping activity refreshes keep the newest response and its busy state', async () => {
  const {context} = fixture(); const requests = [];
  context.fetchWithDashboardTimeout = () => {const d = deferred(); requests.push(d); return d.promise;};
  const older = context.refreshAgentState(); const newer = context.refreshAgentState();
  requests[0].resolve(stateResponse([{job_id: 'j1', state: 'running'}]));
  await older;
  assert.equal(context.agentRefreshBtn.disabled, true, 'older response cannot release the newer request');
  requests[1].resolve(stateResponse([{job_id: 'j1', state: 'done'}]));
  await newer;
  assert.equal(context.agentJobSnapshots.get('j1').state, 'done');
  assert.equal(context.agentRefreshBtn.disabled, false);
  const third = context.refreshAgentState(); const fourth = context.refreshAgentState();
  requests[3].resolve(stateResponse([{job_id: 'j1', state: 'done'}])); await fourth;
  requests[2].resolve(stateResponse([{job_id: 'j1', state: 'running'}])); await third;
  assert.equal(context.agentJobSnapshots.get('j1').state, 'done');
});

test('activity refresh preserves concurrent status, deletion, proposal and baseline changes', async () => {
  const {context} = fixture();
  context.putAgentJob({job_id: 'j1', state: 'running'});
  context.putAgentJob({job_id: 'deleted', state: 'done'});
  context.putAgentProposal({proposal_id: 'dismissed'});
  const pending = deferred(); context.fetchWithDashboardTimeout = () => pending.promise;
  const refresh = context.refreshAgentState();
  context.putAgentJob({job_id: 'j1', state: 'done'});
  context.agentJobSnapshots.delete('deleted');
  context.agentProposalSnapshots.delete('dismissed');
  context.putAgentProposal({proposal_id: 'new'});
  context.agentServerState.promoted_baselines.validation = 'j1';
  context.agentServerState.recent_job_ids = ['j1'];
  pending.resolve(stateResponse([{job_id: 'j1', state: 'running'}, {job_id: 'deleted', state: 'done'}], [{proposal_id: 'dismissed'}]));
  await refresh;
  assert.equal(context.agentJobSnapshots.get('j1').state, 'done');
  assert.equal(context.agentJobSnapshots.has('deleted'), false);
  assert.deepEqual([...context.agentProposalSnapshots.keys()], ['new']);
  assert.equal(context.agentServerState.promoted_baselines.validation, 'j1');
  assert.deepEqual([...context.agentServerState.recent_job_ids], ['j1']);
});

test('invalidated activity refresh cannot restore a previous workspace', async () => {
  const {context} = fixture(); const pending = deferred();
  context.fetchWithDashboardTimeout = () => pending.promise;
  const refresh = context.refreshAgentState();
  context.agentStateRefreshRevision += 1;
  context.agentJobSnapshots.clear(); context.agentRefreshBtn.disabled = false;
  pending.resolve(stateResponse([{job_id: 'old', state: 'running'}]));
  await refresh;
  assert.equal(context.agentJobSnapshots.size, 0);
  assert.equal(context.agentJobPollTimers.size, 0);
});

test('a successful mutation prevents resurrection through nested baseline and saved-card reads', async () => {
  for (const restoreKind of ['baseline', 'saved-card']) {
    const {context} = fixture(); const nested = deferred(); let nestedStarted = false;
    const initial = {jobs: [], proposals: [], promoted_baselines: restoreKind === 'baseline' ? {validation: 'removed'} : {}};
    context.savedNonterminalActionJobIds = () => ['removed'];
    vm.runInContext(extract('recoverSavedNonterminalActionJobs'), context);
    context.fetchWithDashboardTimeout = (url, options = {}) => {
      if (url === '/api/agent/state') return Promise.resolve(Response.json(initial));
      if (options.method === 'POST') return Promise.resolve(Response.json({deleted: true}));
      nestedStarted = true; return nested.promise;
    };
    const refresh = context.refreshAgentState();
    await tick(); assert.equal(nestedStarted, true);
    await context.postAgentAction('/api/jobs/removed/delete');
    context.agentJobSnapshots.delete('removed');
    nested.resolve(Response.json({job_id: 'removed', state: 'done'}));
    await refresh;
    assert.equal(context.agentJobSnapshots.has('removed'), false, restoreKind);
    assert.equal(context.agentRefreshBtn.disabled, false);
  }
});

test('an older refresh cannot announce success after its annual-baseline await', async () => {
  const {context} = fixture(); const baseline = deferred(); const notices = [];
  context.activeView = 'annual'; context.appendSystemNotice = message => notices.push(message);
  context.fetchWithDashboardTimeout = async () => stateResponse([]);
  context.loadCurrentCalibration = () => baseline.promise;
  const refresh = context.refreshAgentState(true);
  await tick(); context.invalidateAgentStateRefresh(); baseline.resolve(null);
  await refresh;
  assert.deepEqual(notices, []);
});

test('workspace reset invalidates pending status, activity and action responses', async () => {
  const {context} = fixture(); const requests = [];
  const element = () => ({value: '', classList: {add: noop, remove: noop}});
  Object.assign(context, {
    calibrationWorkflowRevision: 0, validationPollRevision: 0, annualPollRevision: 0,
    annualRequestRevision: 0, pollTimer: null, annualPollTimer: null,
    chatInput: element(), chatSidebar: element(), chatHistoryPanel: element(), progressWrap: element(),
    errorBanner: element(), calibrationReviewPanel: element(), calibrationFactorPanel: element(),
    activeChatConversation: () => ({messages: [], draft: ''}),
  });
  for (const name of [
    'abortCalibrationReviewRequests', 'setCalibrationControlsLocked', 'setCalibrationReviewCollapsed',
    'clearAnnualFallbackConfirmation', 'autoResizeChatInput', 'syncChatComposerState',
    'rebuildAgentCompletionCardIndex', 'renderUncalibratedComparison', 'renderValidationRunContext',
    'clearRunImages', 'clearAnnualImages', 'resetTechnoeconomicWorkspace', 'setExcelLink', 'setAnnualExcelLink',
    'renderAnnualQuality', 'renderAnnualResultCalibration', 'renderAnnualCalibrationBaseline',
    'applyValidationDateDefaults', 'renderChatMessages', 'renderChatHistory', 'setChatOpen', 'switchMode',
  ]) context[name] = noop;
  vm.runInContext(['invalidateValidationStatusPoll', 'invalidateAnnualStatusPoll', 'resetClientState'].map(extract).join('\n'), context);
  context.fetchWithDashboardTimeout = () => {const d = deferred(); requests.push(d); return d.promise;};
  context.putAgentJob({job_id: 'old', state: 'running'});
  const poll = context.pollAgentJob('old');
  const refresh = context.refreshAgentState();
  const action = context.postAgentAction('/api/jobs/old/retry');
  const chatController = new AbortController(); context.activeChatAbortController = chatController;
  context.resetClientState();
  assert.equal(chatController.signal.aborted, true);
  assert.equal(context.activeChatAbortController, null);
  requests[0].resolve(Response.json({job_id: 'old', state: 'running'}));
  requests[1].resolve(stateResponse([{job_id: 'old', state: 'running'}]));
  requests[2].resolve(Response.json({job_id: 'old', state: 'queued'}));
  await Promise.all([poll, refresh]);
  await assert.rejects(action, /workspace changed/);
  assert.equal(context.agentJobSnapshots.size, 0);
  assert.equal(context.agentJobPollTimers.size, 0);
  assert.equal(context.agentJobPollRequests.size, 0);
  assert.equal(context.agentRefreshBtn.disabled, false);
});

function loadTeaTransport(context) {
  vm.runInContext(['technoeconomicPlainObject', 'normalizeTechnoeconomicApiError', 'technoeconomicFetchJson'].map(extract).join('\n'), context);
}

test('TEA deadlines bound stalled headers and bodies without retrying mutations', async () => {
  for (const method of ['GET', 'POST', 'DELETE']) {
    for (const stalledBody of [false, true]) {
      const {context, timers} = fixture(); loadTeaTransport(context); let calls = 0;
      context.fetch = (_url, {signal}) => {
        calls += 1;
        if (stalledBody) return Promise.resolve(new Response(new ReadableStream({
          start(controller) {signal.addEventListener('abort', () => controller.error(signal.reason));},
        })));
        return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason)));
      };
      const request = context.technoeconomicFetchJson('/api/technoeconomic/jobs', {method});
      await tick();
      const deadline = [...timers.values()][0];
      assert.equal(deadline.delay, 30000);
      deadline.callback();
      await assert.rejects(request, error => {
        assert.equal(error.code, 'request_timeout');
        if (method !== 'GET') assert.match(error.message, /may already have accepted/);
        return true;
      });
      assert.equal(calls, 1);
      assert.equal(timers.size, 0);
    }
  }
});

test('TEA caller cancellation remains distinct from transport timeout after headers', async () => {
  const {context, timers} = fixture(); loadTeaTransport(context); let calls = 0;
  context.fetch = async (_url, {signal}) => {
    calls += 1;
    return new Response(new ReadableStream({
      start(controller) {signal.addEventListener('abort', () => controller.error(signal.reason));},
    }));
  };
  const caller = new AbortController();
  const request = context.technoeconomicFetchJson('/api/technoeconomic/sources', {signal: caller.signal});
  await tick(); caller.abort();
  await assert.rejects(request, error => error.code === 'request_aborted');
  await assert.rejects(context.technoeconomicFetchJson('/api/technoeconomic/sources', {signal: caller.signal}), error => error.code === 'request_aborted');
  assert.equal(calls, 1);
  assert.equal(timers.size, 0);
});

test('TEA status polling resumes after a deadline instead of treating it as supersession', async () => {
  const {context, timers} = fixture(); loadTeaTransport(context);
  Object.assign(context, {
    technoeconomicStatusRequestRevision: 1, technoeconomicActiveJobId: 'tea_1',
    technoeconomicStatusAbortController: null, technoeconomicStatusTimer: null,
    technoeconomicPollFailureCount: 0, technoeconomicJob: {job_id: 'tea_1', state: 'running'},
    technoeconomicRenderJob: noop,
  });
  vm.runInContext(['technoeconomicScheduleStatusPoll', 'technoeconomicPollJob'].map(extract).join('\n'), context);
  context.fetch = (_url, {signal}) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason)));
  const poll = context.technoeconomicPollJob('tea_1');
  [...timers.values()][0].callback(); await poll;
  assert.equal(context.technoeconomicPollFailureCount, 1);
  assert.equal(context.technoeconomicActiveJobId, 'tea_1');
  assert.equal(timers.size, 1);
  assert.equal([...timers.values()][0].delay, 2000);
});

test('TEA transport retains JSON error contracts and clears successful request deadlines', async () => {
  const {context, timers} = fixture(); loadTeaTransport(context);
  context.fetch = async () => Response.json({job_id: 'tea_1', state: 'running'});
  assert.equal((await context.technoeconomicFetchJson('/status')).job_id, 'tea_1');
  context.fetch = async () => Response.json({detail: [{loc: ['body', 'n'], msg: 'Invalid sample count'}]}, {status: 422});
  await assert.rejects(context.technoeconomicFetchJson('/jobs', {method: 'POST'}), error => {
    assert.equal(error.code, 'validation_error'); assert.equal(error.fields[0].path, 'n'); return true;
  });
  context.fetch = async () => new Response('not JSON');
  await assert.rejects(context.technoeconomicFetchJson('/status'), error => error.code === 'invalid_response');
  assert.equal(timers.size, 0);
});

function loadChatCardActions(context) {
  context.setAgentActivityOpen = noop;
  context.updateStoredChatActionCardStatus = noop;
  context.requestAgentCompletionExplanation = noop;
  vm.runInContext(['openAgentActivityFromChat', 'explainChatCardJob'].map(extract).join('\n'), context);
}

test('manual Open run keeps a snapshot updated while its status request was pending', async () => {
  const {context} = fixture(); loadChatCardActions(context); const pending = deferred();
  context.fetchWithDashboardTimeout = () => pending.promise;
  const open = context.openAgentActivityFromChat({job_id: 'j1', kind: 'run_complete'});
  context.putAgentJob({job_id: 'j1', state: 'done'});
  pending.resolve(Response.json({job_id: 'j1', state: 'running'})); await open;
  assert.equal(context.agentJobSnapshots.get('j1').state, 'done');
  assert.equal(context.agentActivitySelection, 'job:j1');
});

test('manual job reads cannot restore deleted/reset jobs or emit stale errors', async () => {
  for (const action of ['openAgentActivityFromChat', 'explainChatCardJob']) {
    for (const succeeds of [true, false]) {
      const {context} = fixture(); loadChatCardActions(context); const pending = deferred(); const effects = [];
      context.fetchWithDashboardTimeout = () => pending.promise;
      context.appendSystemNotice = () => effects.push('notice');
      context.setAgentActivityOpen = () => effects.push('open');
      context.requestAgentCompletionExplanation = () => effects.push('explain');
      const request = context[action](action === 'openAgentActivityFromChat' ? {job_id: 'j1', kind: 'run_complete'} : 'j1');
      context.invalidateAgentStateRefresh(); // Successful deletion and reset both invalidate mutations.
      context.agentJobSnapshots.delete('j1');
      if (succeeds) pending.resolve(Response.json({job_id: 'j1', state: 'done'}));
      else pending.reject(new Error('late error'));
      await request;
      assert.equal(context.agentJobSnapshots.size, 0, action);
      assert.deepEqual(effects, [], action);
    }
  }
});

test('latest Open-run click wins even if an older card responds last', async () => {
  const {context} = fixture(); loadChatCardActions(context); const requests = [];
  context.fetchWithDashboardTimeout = () => {const d = deferred(); requests.push(d); return d.promise;};
  const first = context.openAgentActivityFromChat({job_id: 'first', kind: 'run_complete'});
  const second = context.openAgentActivityFromChat({job_id: 'second', kind: 'run_complete'});
  requests[1].resolve(Response.json({job_id: 'second', state: 'done'})); await second;
  requests[0].resolve(Response.json({job_id: 'first', state: 'done'})); await first;
  assert.equal(context.agentActivitySelection, 'job:second');
  assert.equal(context.agentJobSnapshots.has('first'), false);
});

test('manual explanation uses a newer snapshot when its older status read succeeds or fails', async () => {
  for (const succeeds of [true, false]) {
    const {context} = fixture(); loadChatCardActions(context); const pending = deferred(); const explained = [];
    context.fetchWithDashboardTimeout = () => pending.promise;
    context.requestAgentCompletionExplanation = job => explained.push(job);
    const request = context.explainChatCardJob('j1');
    context.putAgentJob({job_id: 'j1', state: 'done', comparison: {fresh: true}});
    const latest = context.agentJobSnapshots.get('j1');
    if (succeeds) pending.resolve(Response.json({job_id: 'j1', state: 'running'}));
    else pending.reject(new Error('older status read failed'));
    await request;
    assert.equal(context.agentJobSnapshots.get('j1'), latest);
    assert.equal(explained[0], latest);
  }
});

function loadCompletionExplanation(context) {
  const origin = {id: 'origin', messages: [], title: 'Original conversation'};
  const other = {id: 'other', messages: []};
  const effects = [];
  Object.assign(context, {
    chatConversations: [origin, other], activeChatConversationId: origin.id, chatMessages: origin.messages,
    agentExplainedJobs: new Set(), CHAT_REQUEST_TIMEOUT_MS: 60000,
    chatConversationForActionCard: () => origin, activeChatConversation: () => context.chatConversations.find(c => c.id === context.activeChatConversationId),
    saveDashboardState: () => effects.push('save'),
    appendMessage: () => ({querySelector: () => null, parentElement: {remove: () => effects.push('remove spinner')}}),
    assistantMessageFromResponse: reply => ({role: 'assistant', content: reply}), trimChatMessages: messages => messages,
    renderChatMessages: noop, renderChatFollowups: noop, renderChatHistory: noop,
    appendSystemNotice: message => effects.push('notice:' + message),
  });
  vm.runInContext(extract('requestAgentCompletionExplanation'), context);
  return {origin, other, effects, job: {job_id: 'j1', state: 'done', mode: 'validation', request: {}, comparison: {}}};
}

test('in-flight explanations cannot enter a reset or removed-origin conversation', async () => {
  for (const invalidation of ['reset', 'remove origin']) {
    for (const succeeds of [true, false]) {
      const {context} = fixture(); const {origin, other, effects, job} = loadCompletionExplanation(context); const pending = deferred();
      context.fetchWithDashboardTimeout = () => pending.promise;
      const explanation = context.requestAgentCompletionExplanation(job);
      if (invalidation === 'reset') context.agentWorkspaceRevision += 1;
      else context.chatConversations = [other];
      context.activeChatConversationId = other.id; context.chatMessages = other.messages;
      if (succeeds) pending.resolve(Response.json({reply: 'stale explanation'}));
      else pending.reject(new Error('stale failure'));
      await explanation;
      assert.equal(origin.messages.length, 0);
      assert.equal(other.messages.length, 0);
      assert.equal(context.agentExplainedJobs.has(job.job_id), false);
      assert.equal(effects.some(effect => effect.startsWith('notice:')), false);
      assert.equal(effects.filter(effect => effect === 'save').length, 1, 'invalid response must not persist into the new workspace');
      assert.equal(effects.includes('remove spinner'), true);
    }
  }
});

test('switching conversations keeps a valid explanation in its original conversation', async () => {
  const {context} = fixture(); const {origin, other, job} = loadCompletionExplanation(context); const pending = deferred();
  context.fetchWithDashboardTimeout = () => pending.promise;
  const explanation = context.requestAgentCompletionExplanation(job);
  context.activeChatConversationId = other.id; context.chatMessages = other.messages;
  pending.resolve(Response.json({reply: 'original result explanation'})); await explanation;
  assert.equal(origin.messages[0].content, 'original result explanation');
  assert.equal(origin.unread, true);
  assert.equal(other.messages.length, 0);
});

test('a stalled explanation times out once and releases its pending marker', async () => {
  const {context, timers} = fixture(); const {effects, job} = loadCompletionExplanation(context); let calls = 0;
  context.fetch = (_url, {signal}) => {
    calls += 1;
    return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason)));
  };
  const explanation = context.requestAgentCompletionExplanation(job);
  const deadline = [...timers.values()][0];
  assert.equal(deadline.delay, 60000); deadline.callback(); await explanation;
  assert.equal(calls, 1);
  assert.equal(context.agentExplainedJobs.has(job.job_id), false);
  assert.equal(timers.size, 0);
  assert.equal(effects.some(effect => effect.startsWith('notice:')), true);
});

function loadChatSender(context) {
  const origin = {id: 'chat-origin', messages: []}; const effects = [];
  const bubble = () => ({parentElement: {
    classList: {remove: noop, toggle: noop}, removeAttribute: noop,
    remove: () => effects.push('remove bubble'),
  }});
  Object.assign(context, {
    chatInput: {value: 'Run a scenario', focus: noop}, chatIsSending: false, chatHydrationPending: false,
    chatMessages: origin.messages, chatConversations: [origin], activeChatConversationId: origin.id,
    CHAT_REQUEST_TIMEOUT_MS: 60000, activeMode: 'validation',
    autoResizeChatInput: noop, syncChatComposerState: noop, appendMessage: bubble,
    trimChatMessages: messages => messages, saveDashboardState: noop,
    activeChatConversation: () => context.chatConversations.find(c => c.id === context.activeChatConversationId),
    setSending: sending => {context.chatIsSending = sending;}, getCanonicalCurrentConfig: () => ({}),
    normalizeAgentAction: data => data.action || null, agentActionSummary: () => 'Scenario queued', buildChatActionCard: () => ({}),
    renderMessageBubbleContent: noop, isClarificationReply: () => false,
    assistantMessageFromResponse: reply => ({role: 'assistant', content: reply}), applyMessageMeta: noop,
    handleAgentAction: () => effects.push('action'), renderExternalEvidence: noop, scrollChatToBottom: noop,
    appendSystemNotice: message => effects.push('notice:' + message), renderChatFollowups: noop,
    isChatMobile: () => true, document: {},
  });
  vm.runInContext(['sendMessage', 'cancelChatRequest'].map(extract).join('\n'), context);
  return {origin, effects};
}

test('old chat replies and finally blocks cannot mutate a reset workspace or release a newer send', async () => {
  const {context} = fixture(); const {effects} = loadChatSender(context); const requests = [];
  context.fetch = () => {const d = deferred(); requests.push(d); return d.promise;};
  const older = context.sendMessage();
  const olderController = context.activeChatAbortController;
  context.agentWorkspaceRevision += 1;
  olderController.abort(); context.activeChatAbortController = null; context.setSending(false);
  context.chatMessages = []; context.chatInput.value = 'New workspace question';
  const newer = context.sendMessage(); const newerController = context.activeChatAbortController;
  requests[0].resolve(Response.json({action: {type: 'job_started', job: {job_id: 'stale'}}})); await older;
  assert.equal(context.activeChatAbortController, newerController);
  assert.equal(context.chatIsSending, true);
  assert.equal(context.latestJobId, null);
  assert.deepEqual(effects, []);
  context.cancelChatRequest();
  requests[1].resolve(Response.json({reply: 'cancelled newer reply'})); await newer;
  assert.equal(context.chatIsSending, false);
  assert.equal(context.chatMessages.some(message => message.role === 'assistant'), false);
});

test('chat body cancellation cannot become a fallback assistant reply or scenario action', async () => {
  const {context} = fixture(); const {effects} = loadChatSender(context); const body = deferred();
  context.fetch = async () => ({ok: true, json: () => body.promise});
  const sending = context.sendMessage(); await tick();
  context.cancelChatRequest(); body.reject(new DOMException('cancelled body', 'AbortError')); await sending;
  assert.equal(context.chatMessages.filter(message => message.role === 'assistant').length, 0);
  assert.equal(effects.includes('action'), false);
  assert.equal(effects.some(effect => effect.includes('response canceled')), true);
  assert.equal(context.activeChatAbortController, null);
  assert.equal(context.chatIsSending, false);
});

test('chat replies from a removed origin do not enter another active conversation', async () => {
  const {context} = fixture(); const {effects} = loadChatSender(context); const pending = deferred();
  context.fetch = () => pending.promise;
  const sending = context.sendMessage();
  const other = {id: 'other', messages: []};
  context.chatConversations = [other]; context.activeChatConversationId = other.id; context.chatMessages = other.messages;
  pending.resolve(Response.json({action: {type: 'job_started', job: {job_id: 'stale'}}})); await sending;
  assert.equal(other.messages.length, 0);
  assert.equal(context.latestJobId, null);
  assert.deepEqual(effects, []);
  assert.equal(context.chatIsSending, false);
});
