import {expect, test} from '@playwright/test';
import {readFileSync, readdirSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'frontend');
function dashboard() {
  let html = readFileSync(join(root, 'html/document.template.html'), 'utf8').replace(/\r\n?/g, '\n');
  for (const [slot, dir, pattern] of [
    ['{{CSS}}', 'css', /\.css$/], ['{{MARKUP}}', 'html', /^\d.*\.html$/], ['{{JS}}', 'js', /\.js$/],
  ]) {
    const content = readdirSync(join(root, dir)).filter(name => pattern.test(name)).sort()
      .map(name => readFileSync(join(root, dir, name), 'utf8').replace(/\r\n?/g, '\n').replace(/\n$/, '')).join('\n');
    html = html.replace(slot, () => content);
  }
  return html;
}

async function openDashboard(page, options = {}) {
  await page.addInitScript(({savedView, delayedSession, changedSession, delayedBaseline, blockedStorage, collection, savedChatOpen, teaSource}) => {
    const key = 'sb-energy-dashboard-state-v1';
    if (savedView && !localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify({
      serverSessionId: changedSession ? 'old-session' : 'landing-session',
      activeView: savedView, activeMode: savedView === 'validation' ? 'validation' : 'annual',
      chatMessages: [], chatDraft: 'Preserved draft', chatOpen: savedChatOpen === true,
    }));
    if (collection) localStorage.setItem('sb-energy-data-collection-active-id-v1', 'collect_0123456789abcdef01234567');
    if (blockedStorage) {
      for (const method of ['getItem', 'setItem', 'removeItem']) Storage.prototype[method] = () => {throw new Error('Storage unavailable');};
    }
    window.__landing = {posts: 0, baselineAborted: false};
    const json = (data, status = 200) => new Response(JSON.stringify(data), {status, headers: {'Content-Type': 'application/json'}});
    const nativeTimeout = window.setTimeout.bind(window);
    // Exercise the real abort deadline without waiting eight seconds in every test.
    if (delayedBaseline) window.setTimeout = (handler, ms, ...args) => nativeTimeout(handler, ms === 8000 ? 50 : ms, ...args);
    window.fetch = async (input, init = {}) => {
      const path = new URL(typeof input === 'string' ? input : input.url, location.origin).pathname;
      if ((init.method || 'GET').toUpperCase() !== 'GET') {window.__landing.posts++; return json({}, 400);}
      if (path === '/api/session') {
        if (delayedSession) return new Promise(resolve => {window.__landing.releaseSession = () => resolve(json({session_id: 'landing-session'}));});
        return json({session_id: 'landing-session'});
      }
      if (path === '/api/current-calibration') {
        if (delayedBaseline) return new Promise((_resolve, reject) => {
          const abort = () => {window.__landing.baselineAborted = true; reject(new DOMException('Timed out', 'AbortError'));};
          if (init.signal?.aborted) abort(); else init.signal?.addEventListener('abort', abort, {once: true});
        });
        return json({available: false});
      }
      if (path === '/api/agent/state') return json({proposals: [], jobs: [], recent_job_ids: [], promoted_baselines: {validation: null, annual: null}});
      if (path === '/api/technoeconomic/sources') return json({sources: teaSource ? [{
        source_annual_job_id: 'annual-landing-fixture', eligible: true,
        eligible_years: [2024, 2025], solectria_installed_wdc: 139181, solaredge_installed_wdc: 142321,
        annual_energy_by_year: [
          {year: 2024, solectria_kwh: 190000, solaredge_kwh: 205000},
          {year: 2025, solectria_kwh: 191000, solaredge_kwh: 206000},
        ],
        provenance: {completed_at: '2026-08-20T12:00:00Z', operating_limit: {curtailment_enabled: true, curtailment_limit_kw: 125}},
      }] : []});
      if (path === '/api/saved-results') return json({saved_results: [], limit: 10});
      if (path.startsWith('/api/data-collections/')) return json({
        collection_id: 'collect_0123456789abcdef01234567', state: 'completed', progress: 100, stage: 'Collection complete',
        request: {from_date: '2026-08-01', from_time: '00:00', to_date: '2026-08-02', to_time: '00:00', interval_value: 1, interval_unit: 'hours', data_groups: ['solaredge', 'solectria']},
        result: {row_count: 1234567890, series: ['solaredge_measured_power', 'solectria_measured_power'],
          measured_energy_kwh: {solaredge_measured_power: 123456789012345, solectria_measured_power: 123456789012345},
          filename: 'fixture.csv', sha256: 'a'.repeat(64), workbook: {filename: 'fixture.xlsx', sha256: 'b'.repeat(64)},
          quality: {status: 'pass', issue_count: 0, summary: {}}, plots: {}},
      });
      return json({detail: 'Fixture unavailable'}, 404);
    };
  }, options);
  const html = dashboard();
  await page.route('http://landing.test/**', async route => {
    if (new URL(route.request().url()).pathname === '/') await route.fulfill({contentType: 'text/html', body: html});
    else await route.fulfill({status: 404, body: ''});
  });
  await page.goto('http://landing.test/');
}

async function expectCollection(page) {
  await expect(page.locator('body')).toHaveClass('dashboard-mode-collect-data');
  await expect(page.locator('#collectDataTab')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#collectDataPanel')).toBeVisible();
  await expect(page.locator('#dashboardTitle')).toHaveText('Collect Bazefield Data');
}

for (const savedView of [undefined, 'validation', 'annual', 'technoeconomic']) {
  test(`Data Collection opens after fresh load and reload with ${savedView || 'empty'} storage`, async ({page}) => {
    await openDashboard(page, {savedView});
    await expect.poll(() => page.evaluate(() => chatHydrationPending)).toBe(false);
    await expectCollection(page);
    if (savedView) expect(await page.evaluate(() => chatDraft)).toBe('Preserved draft');
    await page.locator('#validationTab').click();
    await expect(page.locator('body')).toHaveClass('dashboard-mode-validation');
    await page.reload();
    await expect.poll(() => page.evaluate(() => chatHydrationPending)).toBe(false);
    await expectCollection(page);
    expect(await page.evaluate(() => window.__landing.posts)).toBe(0);
  });
}

for (const changedSession of [false, true]) {
  test(`late restoration preserves an explicit tab choice; changed session=${changedSession}`, async ({page}) => {
    await openDashboard(page, {savedView: 'validation', delayedSession: true, changedSession});
    await expectCollection(page);
    await page.locator('#annualTab').click();
    await page.evaluate(() => window.__landing.releaseSession());
    await expect.poll(() => page.evaluate(() => chatHydrationPending)).toBe(false);
    await expect(page.locator('body')).toHaveClass('dashboard-mode-annual');
    expect(await page.evaluate(() => window.__landing.posts)).toBe(0);
  });

  test(`late restoration preserves an open TEA editor and edits; changed session=${changedSession}`, async ({page}) => {
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    await openDashboard(page, {savedView: 'validation', delayedSession: true, changedSession, teaSource: true});
    await expectCollection(page);
    await expect(page.locator('#technoeconomicStandaloneSourceStatus')).toHaveText('Calibrated annual energy is ready');
    await page.locator('#technoeconomicTab').click();
    await page.locator('#technoeconomicEditAssumptionsBtn').click();
    const dialog = page.locator('#technoeconomicAssumptionsDialog');
    const costsTab = dialog.getByRole('tab', {name: 'System costs', exact: true});
    const costYear = page.locator('#technoeconomicStandaloneCostYear');
    const optimizerPrice = page.locator('#technoeconomicSharedOptimizerPrice');
    await costYear.fill('2030');
    await costsTab.click();
    await optimizerPrice.fill('40');
    await page.evaluate(() => window.__landing.releaseSession());
    await expect.poll(() => page.evaluate(() => chatHydrationPending)).toBe(false);
    await expect(page.locator('body')).toHaveClass('dashboard-mode-technoeconomic');
    await expect(dialog).toBeVisible();
    await expect(costsTab).toHaveAttribute('aria-selected', 'true');
    await expect(costYear).toHaveValue('2030');
    await expect(optimizerPrice).toHaveValue('40');
    await expect(page.locator('#technoeconomicStandaloneSourceSelect')).toHaveValue('annual-landing-fixture');
    await expect(page.locator('#technoeconomicConfirmDialog')).not.toBeVisible();
    expect(await page.evaluate(() => window.__landing.posts)).toBe(0);
    expect(pageErrors).toEqual([]);
  });
}

test('unavailable browser storage does not prevent the landing view', async ({page}) => {
  await openDashboard(page, {blockedStorage: true});
  await expect.poll(() => page.evaluate(() => chatHydrationPending)).toBe(false);
  await expectCollection(page);
});

test('a stalled baseline read times out without trapping startup', async ({page}) => {
  await openDashboard(page, {delayedBaseline: true});
  await expectCollection(page);
  await expect.poll(() => page.evaluate(() => window.__landing.baselineAborted)).toBe(true);
  await expect.poll(() => page.evaluate(() => chatHydrationPending)).toBe(false);
  await expect(page.locator('#collectDataSubmit')).toBeEnabled();
});

test('collection controls and completed summaries fit phone, tablet and desktop widths', async ({page}) => {
  await openDashboard(page, {collection: true});
  await page.locator('#collectDataTab').click();
  await expect(page.locator('#collectDataSummary')).toBeVisible();
  for (const width of [320, 390, 560, 561, 768, 900, 901, 1024, 1180, 1181, 1440]) {
    await page.setViewportSize({width, height: 900});
    if ([390, 1440].includes(width)) await page.screenshot({path: test.info().outputPath(`collection-${width}.png`), fullPage: true});
    const dimensions = await page.evaluate(() => ({
      page: document.documentElement.scrollWidth, viewport: innerWidth,
      controls: [...document.querySelectorAll('#collectDataForm .date-input')].map(input => {
        const field = input.getBoundingClientRect();
        const card = input.closest('.collect-data-card').getBoundingClientRect();
        return {left: field.left, right: field.right, cardLeft: card.left, cardRight: card.right, height: field.height};
      }),
    }));
    expect(dimensions.page, `page width at ${width}`).toBeLessThanOrEqual(dimensions.viewport + 1);
    for (const field of dimensions.controls) {
      expect(field.left, `left edge at ${width}`).toBeGreaterThanOrEqual(field.cardLeft);
      expect(field.right, `right edge at ${width}`).toBeLessThanOrEqual(field.cardRight);
      expect(field.height).toBeGreaterThanOrEqual(44);
    }
  }

});

// A 1280x900 display at 200% browser zoom has a 640x450 CSS viewport and DPR 2.
// CSS `zoom` does not resize media queries and is not equivalent to browser zoom.
test('collection reflows in the CSS viewport equivalent to 200% browser zoom', async ({browser}) => {
  const context = await browser.newContext({viewport: {width: 640, height: 450}, deviceScaleFactor: 2});
  try {
    const page = await context.newPage();
    await openDashboard(page, {collection: true});
    await expectCollection(page);
    await expect(page.locator('#collectDataSummary')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(641);
    await page.locator('#collectDataCollapseToggle').click();
    await expect(page.locator('#collectDataStatusContent')).toBeHidden();
  } finally { await context.close(); }
});

test('restoring an open chat on a phone leaves the collection page usable', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await openDashboard(page, {savedView: 'validation', savedChatOpen: true});
  await expect.poll(() => page.evaluate(() => chatHydrationPending)).toBe(false);
  await expectCollection(page);
  expect(await page.evaluate(() => dashboardShell.inert)).toBe(false);
  await expect(page.locator('.app-shell')).not.toHaveAttribute('aria-hidden', 'true');
  await page.locator('#collectDataFromTime').fill('01:30');
  await expect(page.locator('#collectDataFromTime')).toHaveValue('01:30');
  await page.locator('#collectDataSubmit').scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => scrollY)).toBeGreaterThan(0);
});

test('switching from an open desktop chat to collection remains usable after resizing', async ({page}) => {
  await openDashboard(page);
  await expect.poll(() => page.evaluate(() => chatHydrationPending)).toBe(false);
  await page.locator('#validationTab').click();
  await page.locator('#chatToggle').click();
  await expect(page.locator('#chatSidebar')).toBeVisible();
  await page.locator('#collectDataTab').click();
  await page.setViewportSize({width: 390, height: 844});
  await expectCollection(page);
  expect(await page.evaluate(() => dashboardShell.inert)).toBe(false);
  await page.locator('#collectDataFromTime').fill('02:15');
});
