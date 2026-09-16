import {expect, test} from '@playwright/test';
import {readFileSync, readdirSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const PROJECT_ROOT = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const FRONTEND_ROOT = join(PROJECT_ROOT, 'frontend');
const COLLECTION_ID = 'collect_0123456789abcdef01234567';
const SOURCE_ID = 'annual-browser-smoke';

function annualEnergyFixture(energies) {
  return {
    annual_energy_by_year: energies.map(([year, value]) => ({
      year,
      complete_calendar_year: true,
      source_complete: true,
      cdf_eligible: true,
      period_start: `${year}-01-01`,
      period_end: `${year}-12-31`,
      combined_predicted_kwh: value,
      se_predicted_kwh: value / 2,
      sol_predicted_kwh: 260000,
      row_count: 8760,
    })),
  };
}

function normalizedSource(path, trimFinalNewline = false) {
  const source = readFileSync(path, 'utf8').replace(/\r\n?/g, '\n');
  return trimFinalNewline ? source.replace(/\n$/, '') : source;
}

function assembledDashboard() {
  let document = normalizedSource(join(FRONTEND_ROOT, 'html', 'document.template.html'));
  for (const [slot, directory, extension] of [
    ['{{CSS}}', 'css', '.css'],
    ['{{MARKUP}}', 'html', '.html'],
    ['{{JS}}', 'js', '.js'],
  ]) {
    const sources = readdirSync(join(FRONTEND_ROOT, directory), {withFileTypes: true})
      .filter((entry) => entry.isFile() && entry.name.endsWith(extension)
        && (extension !== '.html' || /^[0-9].*\.html$/.test(entry.name)))
      .map((entry) => entry.name)
      .sort()
      .map((name) => normalizedSource(join(FRONTEND_ROOT, directory, name), true));
    const occurrences = document.split(slot).length - 1;
    if (occurrences !== 1) {
      throw new Error(`Dashboard template must contain ${slot} exactly once; found ${occurrences}`);
    }
    document = document.replace(slot, () => sources.join('\n'));
  }
  return document;
}

function browserMocks(options = {}) {
  const collectionRequest = {
    from_date: '2026-08-01', from_time: '01:15',
    to_date: '2026-08-02', to_time: '22:30',
    interval_value: 2, interval_unit: 'hours',
    data_groups: ['solaredge', 'weather'],
  };
  const collectionRecord = (state) => ({
    collection_id: 'collect_0123456789abcdef01234567',
    state,
    progress: state === 'completed' ? 100 : state === 'collecting' ? 55 : 0,
    stage: state === 'completed' ? 'Collection complete'
      : state === 'collecting' ? 'Reading Bazefield series' : 'Collection queued',
    request: collectionRequest,
    ...(state === 'completed' ? {
      result: {
        row_count: 24,
        series: ['solaredge_measured_power'],
        measured_energy_kwh: {
          solaredge_measured_power: 1250,
        },
        filename: 'browser-smoke.csv',
        sha256: 'a'.repeat(64),
        workbook: {filename: 'browser-smoke.xlsx', sha256: 'b'.repeat(64)},
        plots: {
          measured_ac_power: {sha256: 'c'.repeat(64)},
          cumulative_energy: {sha256: 'd'.repeat(64)},
        },
        quality: {
          status: 'issues_detected', issue_count: 2,
          summary: {
            usable_value_completeness_percent: 97.5,
            timestamp_coverage_percent: 99,
            non_good_quality_count: 1,
          },
        },
      },
    } : {}),
  });
  const sourceRecord = {
    source_annual_job_id: 'annual-browser-smoke',
    eligible: true,
    eligible_years: [2024, 2025],
    solectria_installed_wdc: 139181,
    solaredge_installed_wdc: 142321,
    annual_energy_by_year: [
      {year: 2024, solectria_kwh: 190000, solaredge_kwh: 205000},
      {year: 2025, solectria_kwh: 191000, solaredge_kwh: 206000},
    ],
    provenance: {
      completed_at: '2026-08-20T12:00:00Z',
      operating_limit: {curtailment_enabled: true, curtailment_limit_kw: 125},
    },
  };
  const sourceRecords = options.additionalTeaSource
    ? [sourceRecord, {...sourceRecord, source_annual_job_id: 'annual-browser-compatible'}]
    : [sourceRecord];

  window.__sbepvBrowserSmoke = {
    collectionGets: 0,
    collectionPostBody: null,
    teaSourceCalls: 0,
    teaSourceMode: 'success',
    releaseTeaSource: null,
  };
  const json = (body, status = 200) => Promise.resolve(new Response(
    JSON.stringify(body),
    {status, headers: {'Content-Type': 'application/json'}},
  ));
  window.fetch = (input, init = {}) => {
    const rawUrl = typeof input === 'string' ? input : input.url;
    const url = new URL(rawUrl, window.location.origin);
    const method = String(init.method || (typeof input === 'object' && input.method) || 'GET')
      .toUpperCase();
    if (url.pathname === '/api/data-collections' && method === 'POST') {
      window.__sbepvBrowserSmoke.collectionPostBody = JSON.parse(String(init.body || '{}'));
      const posts = Number(localStorage.getItem('sbepv-smoke-collection-posts') || 0) + 1;
      localStorage.setItem('sbepv-smoke-collection-posts', String(posts));
      return json(collectionRecord('queued'));
    }
    if (url.pathname === '/api/data-collections/collect_0123456789abcdef01234567') {
      window.__sbepvBrowserSmoke.collectionGets += 1;
      return json(collectionRecord(
        window.__sbepvBrowserSmoke.collectionGets === 1 ? 'collecting' : 'completed',
      ));
    }
    if (url.pathname === '/api/technoeconomic/sources') {
      window.__sbepvBrowserSmoke.teaSourceCalls += 1;
      if (window.__sbepvBrowserSmoke.teaSourceMode === 'hold') {
        return new Promise((resolve) => {
          window.__sbepvBrowserSmoke.releaseTeaSource = () => {
            window.__sbepvBrowserSmoke.releaseTeaSource = null;
            resolve(json({sources: sourceRecords}));
          };
        });
      }
      if (window.__sbepvBrowserSmoke.teaSourceMode === 'timeout') {
        return new Promise((_resolve, reject) => {
          const signal = init.signal;
          const abort = () => reject(new DOMException('The request was aborted.', 'AbortError'));
          if (signal?.aborted) abort();
          else signal?.addEventListener('abort', abort, {once: true});
        });
      }
      return json({sources: sourceRecords});
    }
    return json({detail: 'Not mocked by the bounded browser smoke test.'}, 404);
  };
}

test('collection recovery and TEA source retry remain operable in a browser', async ({page}) => {
  const html = assembledDashboard();
  await page.addInitScript(browserMocks);
  await page.route('http://dashboard.test/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/') {
      await route.fulfill({status: 200, contentType: 'text/html', body: html});
      return;
    }
    if (url.pathname.endsWith('/download')) {
      await route.fulfill({
        status: 200,
        contentType: 'text/csv',
        headers: {'Content-Disposition': 'attachment; filename="browser-smoke.csv"'},
        body: 'timestamp,value\n2026-08-01T00:00:00Z,1\n',
      });
      return;
    }
    if (url.pathname.endsWith('/download-xlsx')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers: {'Content-Disposition': 'attachment; filename="browser-smoke.xlsx"'},
        body: Buffer.from('browser-smoke-workbook'),
      });
      return;
    }
    if (url.pathname.includes('/plots/')) {
      await route.fulfill({status: 200, contentType: 'image/png', body: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
        'base64',
      )});
      return;
    }
    await route.fulfill({status: 404, contentType: 'application/json', body: '{}'});
  });

  await page.goto('http://dashboard.test/');
  await expect(page.locator('#technoeconomicStandaloneSourceStatus'))
    .toHaveText('Calibrated annual energy is ready');

  await page.locator('#collectDataTab').click();
  await page.locator('#collectDataFromDate').fill('2026-08-01');
  await page.locator('#collectDataFromTime').fill('01:15');
  await page.locator('#collectDataToDate').fill('2026-08-02');
  await page.locator('#collectDataToTime').fill('22:30');
  await page.locator('#collectDataIntervalValue').fill('2');
  await page.locator('#collectDataIntervalUnit').selectOption('hours');
  await page.locator('input[name="collectDataGroup"][value="solectria"]').uncheck();
  await page.locator('#collectDataSubmit').click();
  expect(await page.evaluate(() => window.__sbepvBrowserSmoke.collectionPostBody)).toEqual({
    from_date: '2026-08-01',
    from_time: '01:15',
    to_date: '2026-08-02',
    to_time: '22:30',
    interval_value: 2,
    interval_unit: 'hours',
    data_groups: ['solaredge', 'weather'],
  });
  await expect(page.locator('#collectDataStateLabel')).toHaveText('Complete');
  await expect(page.locator('#collectDataCollectionId'))
    .toHaveText(`Collection ID: ${COLLECTION_ID}`);
  await expect(page.locator('#collectDataSummary')).toBeVisible();
  await expect(page.locator('#collectDataSolarEdgeEnergy')).toHaveText('1.25 MWh');
  await expect(page.locator('#collectDataQualityNote')).toContainText('Usable completeness 97.5%');
  await expect(page.locator('#collectDataCsvDownload')).toBeVisible();
  await expect(page.locator('#collectDataXlsxDownload')).toBeVisible();
  await expect(page.locator('#collectDataAcPowerCard')).toBeVisible();
  await expect(page.locator('#collectDataEnergyCard')).toBeVisible();
  await expect.poll(() => page.locator('#collectDataAcPowerPlot').evaluate(
    (image) => image.complete && image.naturalWidth > 0,
  )).toBe(true);
  await expect.poll(() => page.locator('#collectDataEnergyPlot').evaluate(
    (image) => image.complete && image.naturalWidth > 0,
  )).toBe(true);
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#collectDataCsvDownload').click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('browser-smoke.csv');
  const workbookDownloadPromise = page.waitForEvent('download');
  await page.locator('#collectDataXlsxDownload').click();
  const workbookDownload = await workbookDownloadPromise;
  expect(workbookDownload.suggestedFilename()).toBe('browser-smoke.xlsx');
  await expect.poll(() => page.evaluate(() => localStorage.getItem(
    'sb-energy-data-collection-active-id-v1',
  ))).toBe(COLLECTION_ID);

  await page.reload();
  await page.locator('#collectDataTab').click();
  await expect(page.locator('#collectDataStateLabel')).toHaveText('Complete');
  await expect(page.locator('#collectDataCollectionId'))
    .toHaveText(`Collection ID: ${COLLECTION_ID}`);
  await expect(page.locator('#collectDataFromDate')).toHaveValue('2026-08-01');
  await expect(page.locator('#collectDataFromTime')).toHaveValue('01:15');
  await expect(page.locator('#collectDataToDate')).toHaveValue('2026-08-02');
  await expect(page.locator('#collectDataToTime')).toHaveValue('22:30');
  await expect(page.locator('#collectDataIntervalValue')).toHaveValue('2');
  await expect(page.locator('#collectDataIntervalUnit')).toHaveValue('hours');
  await expect(page.locator('input[name="collectDataGroup"][value="solaredge"]'))
    .toBeChecked();
  await expect(page.locator('input[name="collectDataGroup"][value="solectria"]'))
    .not.toBeChecked();
  await expect(page.locator('input[name="collectDataGroup"][value="weather"]'))
    .toBeChecked();
  expect(await page.evaluate(() => localStorage.getItem('sbepv-smoke-collection-posts'))).toBe('1');

  await page.locator('#technoeconomicTab').click();
  await page.locator('#technoeconomicEditAssumptionsBtn').click();
  await expect(page.locator('#technoeconomicAssumptionsDialog')).toBeVisible();
  const sourceSelect = page.locator('#technoeconomicStandaloneSourceSelect');
  const sourceStatus = page.locator('#technoeconomicStandaloneSourceStatus');
  const refresh = page.locator('#technoeconomicStandaloneRefreshSourcesBtn');
  await expect(sourceSelect).toHaveValue(SOURCE_ID);
  await expect(sourceStatus).toHaveAttribute('role', 'status');
  await expect(sourceStatus).toHaveAttribute('aria-live', 'polite');
  await expect(sourceStatus).toHaveAttribute('aria-atomic', 'true');

  const callsBeforeInvalidation = await page.evaluate(
    () => window.__sbepvBrowserSmoke.teaSourceCalls,
  );
  await page.evaluate(() => { window.__sbepvBrowserSmoke.teaSourceMode = 'hold'; });
  await refresh.click();
  await page.evaluate(() => {
    void refreshTechnoeconomicSources({invalidate: true});
    void refreshTechnoeconomicSources({invalidate: true});
  });
  await expect.poll(() => page.evaluate(() => window.__sbepvBrowserSmoke.teaSourceCalls))
    .toBe(callsBeforeInvalidation + 1);
  await page.evaluate(() => {
    window.__sbepvBrowserSmoke.teaSourceMode = 'success';
    window.__sbepvBrowserSmoke.releaseTeaSource();
  });
  await expect.poll(() => page.evaluate(() => window.__sbepvBrowserSmoke.teaSourceCalls))
    .toBe(callsBeforeInvalidation + 2);
  await expect(sourceStatus).toHaveText('Calibrated annual energy is ready');
  await expect(sourceSelect).toHaveValue(SOURCE_ID);

  await page.clock.install();
  const callsBeforeTimeout = await page.evaluate(() => window.__sbepvBrowserSmoke.teaSourceCalls);
  await page.evaluate(() => { window.__sbepvBrowserSmoke.teaSourceMode = 'timeout'; });
  await refresh.click();
  await expect.poll(() => page.evaluate(() => window.__sbepvBrowserSmoke.teaSourceCalls))
    .toBe(callsBeforeTimeout + 1);
  await page.clock.fastForward(15_100);
  await expect(sourceStatus).toHaveText('Source check timed out');
  await expect(sourceSelect).toHaveValue(SOURCE_ID);

  await page.evaluate(() => { window.__sbepvBrowserSmoke.teaSourceMode = 'success'; });
  await refresh.click();
  await expect(sourceStatus).toHaveText('Calibrated annual energy is ready');
  await expect(sourceSelect).toHaveValue(SOURCE_ID);

  await page.evaluate(() => localStorage.setItem(
    'sb-energy-data-collection-active-id-v1',
    'collect_deadbeefdeadbeefdeadbeef',
  ));
  await page.reload();
  await page.locator('#collectDataTab').click();
  await expect.poll(() => page.evaluate(() => localStorage.getItem(
    'sb-energy-data-collection-active-id-v1',
  ))).toBeNull();
  await expect(page.locator('#collectDataError')).toContainText(
    'The saved data collection has expired or is no longer available.',
  );
  await expect(page.locator('#collectDataError')).toBeVisible();
  await expect(page.locator('#collectDataSubmit')).toBeEnabled();
});

test('tabbed TEA assumptions preserve Annual source selection, edits, review, and cost basis', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.addInitScript(browserMocks, {additionalTeaSource: true});
  const html = assembledDashboard();
  // All page resources and API calls remain local fixtures; no jobs are queued.
  await page.route('**/*', async (route) => {
    if (route.request().url() === 'http://dashboard.test/') {
      await route.fulfill({status: 200, contentType: 'text/html', body: html});
    } else {
      await route.fulfill({status: 404, contentType: 'application/json', body: '{}'});
    }
  });
  await page.goto('http://dashboard.test/');
  await expect(page.locator('#technoeconomicStandaloneSourceStatus'))
    .toHaveText('Calibrated annual energy is ready');
  await page.locator('#technoeconomicTab').click();
  await page.locator('#technoeconomicEditAssumptionsBtn').click();
  const dialog = page.locator('#technoeconomicAssumptionsDialog');
  const projectTab = dialog.getByRole('tab', {name: 'Project', exact: true});
  const costsTab = dialog.getByRole('tab', {name: 'System costs', exact: true});
  const financeTab = dialog.getByRole('tab', {name: 'Finance', exact: true});
  const reviewTab = dialog.getByRole('tab', {name: 'Review', exact: true});
  const next = dialog.getByRole('button', {name: 'Next', exact: true});
  const back = dialog.getByRole('button', {name: 'Back', exact: true});
  const reviewAndCalculate = dialog.getByRole('button', {name: 'Review and calculate', exact: true});
  const reviewSummary = page.locator('#technoeconomicAssumptionsReviewSummary');
  const source = page.locator('#technoeconomicStandaloneSourceSelect');
  const year = page.locator('#technoeconomicStandaloneCostYear');
  const optimizerPrice = page.locator('#technoeconomicSharedOptimizerPrice');
  const acceptance = page.locator('#technoeconomicStandaloneAccept');
  const omLow = page.locator('#technoeconomicStandaloneSolectriaCostLines [data-tea-v4-cost-line="Om"] [data-tea-v4-param="low"]');
  const omHigh = page.locator('#technoeconomicStandaloneSolectriaCostLines [data-tea-v4-cost-line="Om"] [data-tea-v4-param="high"]');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('tab')).toHaveCount(4);
  await expect(dialog.getByRole('tabpanel', {includeHidden: true})).toHaveCount(4);
  await expect(dialog.getByRole('tabpanel')).toHaveCount(1);
  await expect(projectTab).toHaveAttribute('aria-selected', 'true');
  await expect(projectTab).toHaveAttribute('tabindex', '0');
  for (const tab of [projectTab, costsTab, financeTab, reviewTab]) {
    const panelId = await tab.getAttribute('aria-controls');
    expect(panelId).toBeTruthy();
    await expect(page.locator(`[id="${panelId}"]`)).toHaveAttribute('role', 'tabpanel');
    await expect(page.locator(`[id="${panelId}"]`))
      .toHaveAttribute('aria-labelledby', await tab.getAttribute('id'));
  }
  await expect(source).toBeVisible();
  await expect(year).toBeEditable();
  await expect(year).toHaveValue('2024');
  await expect(source).toHaveValue(SOURCE_ID);
  await expect(back).toBeHidden();
  await expect(next).toBeVisible();
  await expect(reviewAndCalculate).toBeHidden();
  await next.click();
  await expect(costsTab).toHaveAttribute('aria-selected', 'true');
  await expect(costsTab).toBeFocused();
  await expect(back).toBeVisible();
  await next.click();
  await expect(financeTab).toHaveAttribute('aria-selected', 'true');
  await next.click();
  await expect(reviewTab).toHaveAttribute('aria-selected', 'true');
  await expect(next).toBeHidden();
  await expect(reviewAndCalculate).toBeVisible();
  await expect(page.locator('#technoeconomicConfirmDialog')).not.toBeVisible();
  await back.click();
  await expect(financeTab).toHaveAttribute('aria-selected', 'true');
  await expect(financeTab).toBeFocused();
  await expect(next).toBeVisible();
  await expect(reviewAndCalculate).toBeHidden();
  await back.click();
  await expect(costsTab).toHaveAttribute('aria-selected', 'true');
  await back.click();
  await expect(projectTab).toHaveAttribute('aria-selected', 'true');
  await expect(back).toBeHidden();
  await expect(source).toHaveValue(SOURCE_ID);
  await projectTab.press('ArrowRight');
  await expect(costsTab).toBeFocused();
  await expect(costsTab).toHaveAttribute('aria-selected', 'true');
  await expect(projectTab).toHaveAttribute('aria-selected', 'false');
  await expect(projectTab).toHaveAttribute('tabindex', '-1');
  await expect(source).toBeHidden();
  await costsTab.press('End');
  await expect(reviewTab).toBeFocused();
  await expect(reviewTab).toHaveAttribute('aria-selected', 'true');
  await reviewTab.press('Home');
  await expect(projectTab).toBeFocused();
  await projectTab.press('ArrowLeft');
  await expect(reviewTab).toBeFocused();
  await reviewTab.press('Home');
  await expect(projectTab).toHaveAttribute('aria-selected', 'true');
  await financeTab.click();
  await expect(page.locator('#technoeconomicStandaloneSeed')).toHaveValue('20260916');
  await expect(page.locator('#technoeconomicStandaloneDiscountFamily')).toHaveValue('uniform');
  await expect(page.locator('#technoeconomicStandaloneDegradationFamily')).toHaveValue('triangular');
  await expect(page.locator('#technoeconomicSharedDcCapacity')).toHaveValue('134');
  await costsTab.click();
  await expect(optimizerPrice).toHaveValue('37.75');
  await expect(omLow).toHaveValue('8');
  await expect(omHigh).toHaveValue('13');
  await expect(page.locator('#technoeconomicSharedCostPreview')).toContainText('150.08 million');
  await expect(page.locator('#technoeconomicSharedCostPreview')).toContainText('154.909157 million');
  await expect(page.locator('#technoeconomicStandaloneCostPreset')).toHaveText('Default assumptions');
  await expect(page.locator('#technoeconomicAssumptionStatus')).toBeHidden();
  await expect(page.locator('#technoeconomicRestoreApprovedBtn')).toHaveText('Restore defaults');
  await dialog.screenshot({path: test.info().outputPath('tea-tabbed-costs-desktop.png')});

  await reviewTab.click();
  await acceptance.check();
  await back.click();
  await expect(financeTab).toHaveAttribute('aria-selected', 'true');
  // Footer navigation follows a directly selected tab and does not clear acceptance.
  await costsTab.click();
  await next.click();
  await expect(financeTab).toHaveAttribute('aria-selected', 'true');
  await next.click();
  await expect(reviewTab).toHaveAttribute('aria-selected', 'true');
  await expect(acceptance).toBeChecked();
  await projectTab.click();
  await year.fill('2030');
  await expect(acceptance).not.toBeChecked();
  await costsTab.click();
  await optimizerPrice.fill('40');
  await omLow.fill('9');
  await omHigh.fill('14');
  await expect(page.locator('#technoeconomicSharedCostPreview')).toContainText('155.14108 million');
  await expect(page.locator('#technoeconomicStandaloneCostPreset')).toHaveText('Modified assumptions');
  await reviewTab.click();
  await expect(reviewSummary).toContainText('2030');
  await expect(reviewSummary).toContainText('103,077');
  await expect(reviewSummary).toContainText('$40');
  await acceptance.check();
  await projectTab.click();
  await source.selectOption('annual-browser-compatible');
  await expect(acceptance).not.toBeChecked();
  await expect(year).toHaveValue('2030');
  await costsTab.click();
  await expect(optimizerPrice).toHaveValue('40');
  await expect(omLow).toHaveValue('9');
  await expect(omHigh).toHaveValue('14');
  await page.locator('#technoeconomicAssumptionsFooterCloseBtn').click();
  await expect(dialog).not.toBeVisible();
  await expect(page.locator('#technoeconomicScenarioInputs')).toContainText('USD (real 2030)');
  // Closing flushes the draft synchronously, so an immediate reload is safe.
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem(
    'sbepv.technoeconomic.paired-draft.v3',
  ) || '{}').source_annual_job_id)).toBe('annual-browser-compatible');

  await page.reload();
  await expect(page.locator('#technoeconomicStandaloneSourceStatus'))
    .toHaveText('Calibrated annual energy is ready');
  await page.locator('#technoeconomicTab').click();
  await page.locator('#technoeconomicEditAssumptionsBtn').click();
  await expect(projectTab).toHaveAttribute('aria-selected', 'true');
  await expect(source).toHaveValue('annual-browser-compatible');
  await expect(year).toHaveValue('2030');
  await costsTab.click();
  await expect(optimizerPrice).toHaveValue('40');
  await expect(omLow).toHaveValue('9');
  await expect(omHigh).toHaveValue('14');
  await reviewTab.click();
  await expect(reviewSummary).toContainText('annual-browser-compatible');
  await expect(reviewSummary).toContainText('2030');
  await expect(reviewSummary).toContainText('$40');
  await expect(acceptance).not.toBeChecked();

  // A hidden invalid cost must reveal its tab when the user reviews the run.
  await costsTab.click();
  await optimizerPrice.fill('');
  await reviewTab.click();
  await acceptance.check();
  await page.locator('#technoeconomicAssumptionsReviewBtn').click();
  await expect(dialog).toBeVisible();
  await expect(costsTab).toHaveAttribute('aria-selected', 'true');
  await expect(optimizerPrice).toBeVisible();
  await expect(page.locator('#technoeconomicStandaloneFormErrors')).toBeVisible();
  await expect(page.locator('#technoeconomicConfirmDialog')).not.toBeVisible();
  await optimizerPrice.fill('40');
  await reviewTab.click();
  await acceptance.check();
  await page.locator('#technoeconomicAssumptionsReviewBtn').click();
  const confirmation = page.locator('#technoeconomicConfirmDialog');
  await expect(confirmation).toBeVisible();
  await expect(confirmation).toContainText('2030');
  await expect(confirmation).toContainText('103,077 optimizers × $40');
  await expect(confirmation).toContainText('134,000,000 Wdc');
  await expect(confirmation).toContainText('one draw applied to both systems');
  await expect(confirmation).not.toContainText('Proposed real 2024 dollars');
  await expect(confirmation).toContainText('real 2030 USD/kWac-year');
  await page.locator('#technoeconomicConfirmCancelBtn').click();
  await page.locator('#technoeconomicEditAssumptionsBtn').click();
  await page.locator('#technoeconomicRestoreApprovedBtn').click();
  await projectTab.click();
  await expect(source).toHaveValue('annual-browser-compatible');
  await expect(year).toHaveValue('2024');
  await costsTab.click();
  await expect(optimizerPrice).toHaveValue('37.75');
  await expect(omLow).toHaveValue('8');
  await expect(omHigh).toHaveValue('13');
  await expect(acceptance).not.toBeChecked();
  await expect(page.locator('#technoeconomicStandaloneCostPreset')).toHaveText('Default assumptions');
  await page.setViewportSize({width: 390, height: 844});
  await expect(optimizerPrice).toBeVisible();
  await expect(back).toBeVisible();
  await expect(next).toBeVisible();
  await expect(page.locator('#technoeconomicAssumptionsFooterCloseBtn')).toBeHidden();
  await expect(page.locator('#technoeconomicAssumptionsCloseBtn')).toBeVisible();
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await dialog.screenshot({path: test.info().outputPath('tea-tabbed-costs-mobile.png')});
  await next.click();
  await expect(financeTab).toHaveAttribute('aria-selected', 'true');
  await next.click();
  await expect(reviewTab).toHaveAttribute('aria-selected', 'true');
  await expect(back).toBeVisible();
  await expect(next).toBeHidden();
  await expect(reviewAndCalculate).toBeVisible();
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await expect(reviewSummary).toBeVisible();
  await dialog.screenshot({path: test.info().outputPath('tea-tabbed-review-mobile.png')});
  await projectTab.click();
  await page.locator('#technoeconomicStandaloneOpenAnnualBtn').click();
  await expect(dialog).not.toBeVisible();
  await expect(page.locator('#annualTab')).toHaveAttribute('aria-pressed', 'true');
  await page.locator('#technoeconomicTab').click();
  await page.locator('#technoeconomicEditAssumptionsBtn').click();
  await expect(source).toHaveValue('annual-browser-compatible');
  expect(pageErrors).toEqual([]);
});

test('annual CDF interpolation follows selected series and additional complete years', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.addInitScript(browserMocks);
  const html = assembledDashboard();
  await page.route('http://dashboard.test/**', async (route) => {
    const isDocument = new URL(route.request().url()).pathname === '/';
    await route.fulfill({
      status: isDocument ? 200 : 404,
      contentType: isDocument ? 'text/html' : 'application/json',
      body: isDocument ? html : '{}',
    });
  });
  await page.goto('http://dashboard.test/');
  await page.locator('#annualTab').click();
  const fixture = annualEnergyFixture([
    [2025, 525800], [2017, 527400], [2021, 527500],
    [2019, 543900], [2020, 564200], [2024, 570800],
  ]);
  fixture.annual_energy_by_year.push({
    ...fixture.annual_energy_by_year[0],
    year: 2022,
    source_complete: false,
    cdf_eligible: false,
    combined_predicted_kwh: 1,
  });
  await page.evaluate((result) => renderAnnualYearResults(result), fixture);

  const interpolation = page.locator('#annualDistributionFitChart');
  const equation = page.locator('#annualDistributionFitEquation');
  await expect(page.locator('#annualDistributionCdfChart')).toHaveCount(0);
  await expect(page.locator('#annualDistributionCdfChartWrap')).toHaveCount(0);
  await expect(page.locator('#annualDistributionChart')).toBeVisible();
  await expect(interpolation).toBeVisible();
  await expect(interpolation.locator('.annual-distribution-point')).toHaveCount(6);
  await expect(interpolation.locator('.annual-cdf-point-label')).toHaveCount(6);
  await expect(interpolation.locator('.annual-cdf-point-label').filter({hasText: '525.8 MWh (2025)'}))
    .toHaveCount(1);
  await expect(interpolation.locator('.annual-cdf-point-label').filter({hasText: '(2022)'}))
    .toHaveCount(0);
  await expect(interpolation.locator('.annual-distribution-axis-label').filter({hasText: /^0%$/}))
    .toHaveCount(1);
  await expect(interpolation.locator('.annual-distribution-axis-label').filter({hasText: /^100%$/}))
    .toHaveCount(1);
  await expect(equation).toContainText('n = 6');
  await expect(equation).not.toContainText('R2');
  await expect(equation).not.toContainText('NORM.DIST');
  await expect(page.locator('#annualDistributionP50Value')).toHaveText('535.7 MWh');
  await equation.locator('summary').click();
  await expect(equation.locator('table')).toBeVisible();
  await expect(equation.locator('tbody tr')).toHaveCount(5);
  await expect(equation.locator('tbody tr').first()).toContainText('525.80 <= x <= 527.40');
  await expect(equation.locator('tbody tr').first()).toContainText('F(x) ≈ 0.50/6');
  const combinedEquation = await equation.textContent();
  await page.locator('.annual-distribution-subchart').last().screenshot({
    path: test.info().outputPath('annual-six-year-interpolation.png'),
  });

  // Check the actual drawn path begins/ends at observed point coordinates.
  // Axis padding must not become an extrapolated probability tail.
  const geometry = await interpolation.evaluate((chart) => {
    const coordinates = chart.querySelector('path').getAttribute('d')
      .match(/[-+]?(?:\d*\.)?\d+(?:e[-+]?\d+)?/gi).map(Number);
    const points = Array.from(chart.querySelectorAll('circle')).map((point) => [
      Number(point.getAttribute('cx')), Number(point.getAttribute('cy')),
    ]).sort((a, b) => a[0] - b[0]);
    return {start: coordinates.slice(0, 2), end: coordinates.slice(-2), points};
  });
  expect(geometry.start).toEqual(geometry.points[0]);
  expect(geometry.end).toEqual(geometry.points.at(-1));

  // Open the current SVG with its own styling, year labels, and equation.
  const newChartPage = page.context().waitForEvent('page');
  await interpolation.click({position: {x: 100, y: 100}});
  const chartPage = await newChartPage;
  await expect(chartPage.locator('h1')).toHaveText('Combined interpolated annual-energy CDF');
  await expect(chartPage.locator('svg .annual-cdf-point-label')).toHaveCount(6);
  await expect(chartPage.locator('tbody tr')).toHaveCount(5);
  await expect(chartPage.locator('tbody tr').first()).toContainText('525.80 <= x <= 527.40');
  expect(await chartPage.evaluate(() => window.opener)).toBeNull();
  expect(page.url()).toBe('http://dashboard.test/');
  await chartPage.screenshot({path: test.info().outputPath('annual-chart-new-tab.png'), fullPage: true});
  await chartPage.close();

  await page.locator('#annualDistributionSeries').selectOption('solarEdge');
  await expect(page.locator('#annualDistributionFitTitle')).toContainText('SolarEdge');
  await expect(equation).toContainText('n = 6');
  await expect(equation.locator('tbody tr')).toHaveCount(5);
  expect(await equation.textContent()).not.toEqual(combinedEquation);
  await expect(equation).toContainText('262.9');
  await expect(equation).not.toContainText('525.8');
  await expect(interpolation.locator('.annual-cdf-point-label').filter({hasText: '262.9 MWh (2025)'}))
    .toHaveCount(1);

  // All-equal observations have a midpoint rank but no invertible energy interval.
  await page.locator('#annualDistributionSeries').selectOption('solectria');
  await expect(interpolation).toBeHidden();
  await expect(page.locator('#annualDistributionFitNote')).toContainText(
    'Every complete weather year returned the same annual energy.',
  );
  await expect(interpolation.locator('.annual-distribution-point')).toHaveCount(0);
  await expect(equation.locator('tbody tr')).toHaveCount(0);
  await expect(equation).not.toContainText('525.8');

  const twelve = annualEnergyFixture(Array.from({length: 12}, (_, index) => [
    2010 + index, 300000 + (index * index + index) * 1000,
  ]));
  await page.evaluate((result) => renderAnnualYearResults(result), twelve);
  await expect(page.locator('#annualDistributionSeries')).toHaveValue('combined');
  await expect(interpolation).toBeVisible();
  await expect(interpolation.locator('.annual-cdf-point-label')).toHaveCount(12);
  await expect(equation).toContainText('n = 12');
  await expect(equation.locator('tbody tr')).toHaveCount(11);
  await expect(equation).not.toContainText('525.8');
  const keyboardChartPage = page.context().waitForEvent('page');
  await interpolation.focus();
  await interpolation.press('Enter');
  const twelveChartPage = await keyboardChartPage;
  await expect(twelveChartPage.locator('svg .annual-cdf-point-label')).toHaveCount(12);
  await expect(twelveChartPage.locator('tbody tr')).toHaveCount(11);
  await twelveChartPage.close();
  await page.setViewportSize({width: 390, height: 844});
  await equation.locator('summary').click();
  await expect(equation.locator('table')).toBeVisible();
  const mobileBounds = await page.locator('.annual-distribution-subchart').last().evaluate((section) => {
    const right = section.getBoundingClientRect().right;
    return {
      sectionRight: right,
      chartRight: section.querySelector('svg').getBoundingClientRect().right,
      equationRight: section.querySelector('.annual-distribution-equation').getBoundingClientRect().right,
    };
  });
  expect(mobileBounds.chartRight).toBeLessThanOrEqual(mobileBounds.sectionRight + 1);
  expect(mobileBounds.equationRight).toBeLessThanOrEqual(mobileBounds.sectionRight + 1);
  await page.locator('.annual-distribution-subchart').last().screenshot({
    path: test.info().outputPath('annual-twelve-year-interpolation-mobile.png'),
  });

  await page.evaluate(() => clearAnnualYearResults());
  await expect(interpolation).toBeHidden();
  await expect(equation.locator('tbody tr')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test('TEA v5 interpretation stays below the chart and loaded image charts open in new tabs', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.addInitScript(browserMocks);
  const html = assembledDashboard();
  const plotPath = '/api/technoeconomic/jobs/tea_browser_fixture/artifacts/cdf_plot';
  const plotUrl = `http://dashboard.test${plotPath}`;
  const pdfPath = '/api/technoeconomic/jobs/tea_browser_fixture/exports/pdf';
  const docxPath = '/api/technoeconomic/jobs/tea_browser_fixture/exports/docx';
  const validationUrl = 'http://dashboard.test/outputs/browser-validation.png';
  // Only local mock responses: no calculation or saved model result is changed.
  await page.context().route('http://dashboard.test/**', async (route) => {
    const url = route.request().url();
    if (url === `http://dashboard.test${pdfPath}`) {
      await route.fulfill({status: 200, contentType: 'application/pdf',
        headers: {'Content-Disposition': 'attachment; filename="LCOE_comparsion.pdf"'},
        body: Buffer.from('%PDF-1.4\n% synthetic download fixture\n%%EOF\n')});
    } else if (url === `http://dashboard.test${docxPath}`) {
      await route.fulfill({status: 200,
        contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers: {'Content-Disposition': 'attachment; filename="PV_Comparison_fixture_v2.0_tea_browser_fixture.docx"'},
        body: Buffer.from('PK synthetic Word download fixture')});
    } else if (url === plotUrl || url === validationUrl) {
      await route.fulfill({status: 200, contentType: 'image/png', body: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
        'base64',
      )});
    } else {
      await route.fulfill({status: 200, contentType: 'text/html', body: html});
    }
  });
  await page.goto('http://dashboard.test/');
  await expect(page.locator('#technoeconomicStandaloneSourceStatus'))
    .toHaveText('Calibrated annual energy is ready');
  await page.locator('#technoeconomicTab').click();
  const figure = page.locator('.tea-standalone-cdf-figure');
  const interpretation = page.locator('.tea-standalone-interpretation');
  const figureBounds = await figure.boundingBox();
  const interpretationBounds = await interpretation.boundingBox();
  expect(interpretationBounds.y).toBeGreaterThanOrEqual(figureBounds.y + figureBounds.height - 1);
  expect(interpretationBounds.width).toBeGreaterThanOrEqual(figureBounds.width - 1);
  for (const name of ['Solectria', 'SolarEdge']) {
    const header = page.locator('#technoeconomicLcoePercentileTable th').filter({hasText: name});
    expect((await header.boundingBox()).width).toBeGreaterThan(90);
  }
  // Empty placeholders are never advertised as links.
  await expect(page.locator('#technoeconomicStandaloneCdfPlot')).not.toHaveAttribute('data-chart-openable');
  await expect(page.locator('#technoeconomicStandalonePdfLink')).toBeHidden();
  await expect(page.locator('#technoeconomicStandaloneDocxLink')).toBeHidden();
  await page.locator('.tea-standalone-cdf-card').screenshot({path: test.info().outputPath('tea-v5-interpretation-below.png')});
  // Exercise completed-job adoption, contract dispatch, and verified artifact URL
  // selection together, including the separate Chart action in the result header.
  await page.evaluate(({sourceId, plotPath}) => technoeconomicAdoptJob({
    job_id: 'tea_browser_fixture', workflow: 'technoeconomic', state: 'done',
    progress: 100, stage: 'Completed browser fixture', source_annual_job_id: sourceId,
    request: {
      calculation_contract_version: 'tea-calculation-v5', n: 1000,
      source_annual_job_id: sourceId,
      finance: {
        constant_dollar_cost_year: 2022, project_life_years: 30,
        real_discount_rate: {distribution: {family: 'fixed', value: 0.04}},
      },
      paired_commercial: {
        target_capacity: 100, target_capacity_unit: 'mw',
        target_rating_basis: 'ac_operating_limit',
        shared_initial_capex: {
          report_context: {preset_id: 'thursday-2026-09-17-v1'},
        },
      },
    },
    result: {
      calculation_contract_version: 'tea-calculation-v5', realization_count: 1000,
      source_snapshot_sha256: 'f'.repeat(64),
      paired_commercial: {
        target_capacity_w: 100000000, target_rating_basis: 'ac_operating_limit',
        systems: {
          solectria: {percentiles: {p10: 0.04, p50: 0.05, p90: 0.06}},
          solaredge: {percentiles: {p10: 0.045, p50: 0.055, p90: 0.065}},
        },
        lcoe_delta_se_minus_sol: {percentiles: {p10: 0.004, p50: 0.005, p90: 0.006}},
      },
    },
    artifacts: {exports: {artifacts: {cdf_plot: {url: plotPath}}}},
  }), {sourceId: SOURCE_ID, plotPath});
  await expect(page.locator('#technoeconomicStandaloneResults')).toHaveAttribute('data-state', 'done');
  await expect(page.locator('#technoeconomicStandaloneCostPreset'))
    .toContainText('Thursday comparison assumptions (proposed 2024 USD');
  const pdfLink = page.locator('#technoeconomicStandalonePdfLink');
  await expect(pdfLink).toBeVisible();
  await expect(pdfLink).toHaveAttribute('href', pdfPath);
  const downloadPromise = page.waitForEvent('download');
  await pdfLink.click();
  const pdfDownload = await downloadPromise;
  expect(pdfDownload.suggestedFilename()).toBe('LCOE_comparsion.pdf');
  await expect(page.getByRole('link', { name: /CSV bundle/i })).toHaveCount(0);
  expect(await pdfDownload.failure()).toBeNull();
  const wordLink = page.locator('#technoeconomicStandaloneDocxLink');
  await expect(wordLink).toBeVisible();
  await expect(wordLink).toHaveAttribute('href', docxPath);
  const wordDownloadPromise = page.waitForEvent('download');
  await wordLink.click();
  const wordDownload = await wordDownloadPromise;
  expect(wordDownload.suggestedFilename()).toBe('PV_Comparison_fixture_v2.0_tea_browser_fixture.docx');
  expect(await wordDownload.failure()).toBeNull();
  await expect(page.locator('#technoeconomicLcoePercentileBody tr')).toHaveCount(3);
  await expect(page.locator('#technoeconomicStandaloneInterpretation'))
    .toContainText('Solectria 50 USD/MWh');
  const chart = page.locator('#technoeconomicStandaloneCdfPlot');
  const chartLink = page.locator('a#technoeconomicStandaloneCdfPlotLink');
  const chartAction = page.locator('a#technoeconomicStandaloneCdfLink');
  await expect(chart).toHaveAttribute('data-chart-openable', '');
  await expect(chartLink.locator('img')).toHaveCount(1);
  await page.locator('.tea-standalone-cdf-card').screenshot({path: test.info().outputPath('tea-v5-completed-results.png')});
  for (const link of [chartLink, chartAction]) {
    await expect(link).toHaveAttribute('href', new RegExp(`${plotPath}$`));
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', /noopener/);
    await expect(link).toHaveAttribute('rel', /noreferrer/);
  }
  for (const target of [chart, chartAction]) {
    const openedPage = page.context().waitForEvent('page');
    await target.click();
    const imagePage = await openedPage;
    await expect(imagePage).toHaveURL(plotUrl);
    expect(await imagePage.evaluate(() => window.opener)).toBeNull();
    await expect(page).toHaveURL('http://dashboard.test/');
    await expect(page.locator('#technoeconomicStandaloneResults')).toHaveAttribute('data-state', 'done');
    await imagePage.close();
  }
  await page.evaluate(() => invalidateTechnoeconomicWorkspace());
  await expect(page.locator('#technoeconomicStandaloneCostPreset'))
    .toHaveText('Default assumptions');
  await expect(pdfLink).toBeHidden();
  await expect(wordLink).toBeHidden();
  await expect(chart).not.toHaveAttribute('data-chart-openable');
  for (const link of [chartLink, chartAction]) {
    await expect(link).toBeHidden();
    await expect(link).not.toHaveAttribute('href');
  }

  // Regular validation images share the click/keyboard behavior.
  await page.locator('#validationTab').click();
  await page.evaluate((url) => showImage('acImg', 'acIcon', 'acChartBox', url, false), validationUrl);
  const validationChart = page.locator('#acImg');
  await expect(validationChart).toHaveAttribute('data-chart-openable', '');
  const validationOpened = page.context().waitForEvent('page');
  await validationChart.focus();
  await validationChart.press('Enter');
  const validationPage = await validationOpened;
  await expect(validationPage).toHaveURL(validationUrl);
  await validationPage.close();
  expect(pageErrors).toEqual([]);
});
