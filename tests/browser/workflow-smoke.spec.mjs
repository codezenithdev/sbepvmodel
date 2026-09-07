import {expect, test} from '@playwright/test';
import {readFileSync, readdirSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const PROJECT_ROOT = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const FRONTEND_ROOT = join(PROJECT_ROOT, 'frontend');
const COLLECTION_ID = 'collect_0123456789abcdef01234567';
const SOURCE_ID = 'annual-browser-smoke';

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

function browserMocks() {
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
            resolve(json({sources: [sourceRecord]}));
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
      return json({sources: [sourceRecord]});
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
