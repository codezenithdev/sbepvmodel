import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../frontend/js/03-form-reading-and-plots.js', import.meta.url), 'utf8');
function extract(name, text = source) {
  const match = text.match(new RegExp('        (?:async )?function ' + name + '\\([^]*?(?=\\n        (?:async )?function |$)'));
  assert.ok(match, name);
  return match[0];
}
function fixture() {
  let clock = 0;
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) {
      let src;
      elements.set(id, {
        dataset: {}, style: {}, complete: true, naturalWidth: 0, requests: [],
        onerror: () => {},
        get src() {return src;}, set src(value) {src = value; this.requests.push(value); this.complete = false; this.naturalWidth = 0;},
        getAttribute: name => name === 'src' ? src : null,
        removeAttribute(name) {if (name === 'src') {src = undefined; this.complete = true; this.naturalWidth = 0;}},
      });
    }
    return elements.get(id);
  };
  const context = vm.createContext({document: {getElementById: get}, Date: {now: () => ++clock}});
  vm.runInContext(['showImage', 'clearImage', 'applyInputPlots'].map(name => extract(name)).join('\n'), context);
  const plots = {measured_power_png: '/outputs/attempt-power.png', irradiance_png: '/outputs/attempt-sun.png?revision=1'};
  return {context, get, plots, update: () => context.applyInputPlots(plots, true, {reuseExisting: true})};
}

test('identical polling plots reuse loading and loaded images, while failures retry', () => {
  const {get, update} = fixture();
  const image = get('measuredPowerImg');
  const onerror = image.onerror;
  update(); update();
  assert.equal(image.requests.length, 1);
  image.complete = true; image.naturalWidth = 100; image.onload(); update();
  assert.equal(image.requests.length, 1);
  assert.equal(image.style.display, 'block');
  assert.equal(image.onerror, onerror);
  image.naturalWidth = 0; update();
  assert.equal(image.requests.length, 2);
});

test('new attempts, explicit refresh, clear, and restore keep their refresh behavior', () => {
  const {get, update, context, plots} = fixture();
  update();
  assert.match(get('irradianceImg').src, /\?revision=1&v=\d+$/);
  plots.measured_power_png = '/outputs/new-attempt.png'; update();
  assert.equal(get('measuredPowerImg').requests.length, 2);
  context.applyInputPlots(plots);
  assert.equal(get('measuredPowerImg').requests.length, 3);
  context.clearImage('measuredPowerImg', 'measuredPowerIcon', 'measuredPowerChartBox'); update();
  assert.equal(get('measuredPowerImg').requests.length, 4);
  context.applyInputPlots(plots, false);
  assert.equal(get('measuredPowerImg').src, plots.measured_power_png);
});

test('actual validation polling reuses running inputs but refreshes completion', async () => {
  const {context, get, plots} = fixture();
  const running = {state: 'running', progress: 40, stage: 'Computing', input_plots: plots};
  const replies = [running, running, {...running, state: 'done', result: {input_plots: plots}}];
  Object.assign(context, {
    validationPollRevision: 0, latestJobId: 'job1', pollTimer: null,
    fetchWithDashboardTimeout: async () => ({ok: true, json: async () => replies.shift()}),
    invalidateAgentJobPoll() {},
    setTimeout: () => 1, clearTimeout: () => {},
    setProgress() {}, putAgentJob() {}, renderAgentJobUpdate() {}, saveDashboardState() {},
    resetRunBtn() {}, refreshAgentState: async () => {},
    applyResult: result => context.applyInputPlots(result.input_plots),
  });
  const polling = readFileSync(new URL('../frontend/js/09-validation-run.js', import.meta.url), 'utf8');
  vm.runInContext(extract('pollStatus', polling), context);
  await context.pollStatus('job1'); await context.pollStatus('job1');
  assert.equal(get('measuredPowerImg').requests.length, 1);
  await context.pollStatus('job1');
  assert.equal(get('measuredPowerImg').requests.length, 2);
  assert.equal(replies.length, 0);
});
