        const collectDataElements = Object.freeze({
            panel: document.getElementById('collectDataPanel'),
            form: document.getElementById('collectDataForm'),
            fromDate: document.getElementById('collectDataFromDate'),
            fromTime: document.getElementById('collectDataFromTime'),
            toDate: document.getElementById('collectDataToDate'),
            toTime: document.getElementById('collectDataToTime'),
            intervalValue: document.getElementById('collectDataIntervalValue'),
            intervalUnit: document.getElementById('collectDataIntervalUnit'),
            submit: document.getElementById('collectDataSubmit'),
            error: document.getElementById('collectDataError'),
            status: document.getElementById('collectDataStatus'),
            stateLabel: document.getElementById('collectDataStateLabel'),
            stage: document.getElementById('collectDataStage'),
            progress: document.getElementById('collectDataProgress'),
            progressFill: document.getElementById('collectDataProgressFill'),
            progressText: document.getElementById('collectDataProgressText'),
            collapseToggle: document.getElementById('collectDataCollapseToggle'),
            statusContent: document.getElementById('collectDataStatusContent'),
            summary: document.getElementById('collectDataSummary'),
            rowCount: document.getElementById('collectDataRowCount'),
            seriesCount: document.getElementById('collectDataSeriesCount'),
            solarEdgeStatus: document.getElementById('collectDataSolarEdgeStatus'),
            solectriaStatus: document.getElementById('collectDataSolectriaStatus'),
            plots: document.getElementById('collectDataPlots'),
            acPowerCard: document.getElementById('collectDataAcPowerCard'),
            acPowerPlot: document.getElementById('collectDataAcPowerPlot'),
            energyCard: document.getElementById('collectDataEnergyCard'),
            energyPlot: document.getElementById('collectDataEnergyPlot'),
            plotNote: document.getElementById('collectDataPlotNote'),
            downloads: document.getElementById('collectDataDownloads'),
            csvDownload: document.getElementById('collectDataCsvDownload'),
            xlsxDownload: document.getElementById('collectDataXlsxDownload'),
        });
        let collectDataPollTimer = null;
        let collectDataRevision = 0;
        let collectDataActiveId = null;
        let collectDataPollFailures = 0;
        let collectDataBusy = false;

        function openCollectDataView() {
            document.body.classList.remove(
                'dashboard-mode-validation',
                'dashboard-mode-annual',
                'dashboard-mode-technoeconomic',
                'dashboard-mode-autonomy'
            );
            document.body.classList.add('dashboard-mode-collect-data');
            dashboardTitle.textContent = 'Collect Bazefield Data';
            dashboardSubtitle.textContent = 'Retrieve measured SolarEdge and Solectria power, review the charts, and download CSV or XLSX without starting a model workflow.';
            [validationTab, annualTab, technoeconomicTab, autonomyTab].forEach((tab) => {
                tab.classList.remove('active');
                tab.setAttribute('aria-pressed', 'false');
            });
            collectDataTab.classList.add('active');
            collectDataTab.setAttribute('aria-pressed', 'true');
            setActiveNav(operationsNavLink);
        }

        function collectDataRestoreWorkflowView() {
            if (!document.body.classList.contains('dashboard-mode-collect-data')) return;
            switchMode(activeView, false);
        }

        function collectDataSetError(message, focus = false) {
            collectDataElements.error.textContent = String(message || 'The data collection could not be completed.');
            collectDataElements.error.hidden = false;
            if (focus) collectDataElements.error.focus();
        }

        function collectDataClearError() {
            collectDataElements.error.textContent = '';
            collectDataElements.error.hidden = true;
        }

        function collectDataSetBusy(busy) {
            collectDataBusy = busy;
            collectDataElements.submit.disabled = busy;
            collectDataElements.submit.textContent = busy ? 'Collecting…' : 'Collect data';
            collectDataElements.status.setAttribute('aria-busy', String(busy));
            collectDataElements.form.querySelectorAll('input, select').forEach((control) => {
                control.disabled = busy;
            });
        }

        function collectDataSetCollapsed(collapsed) {
            const shouldCollapse = !!collapsed;
            if (shouldCollapse && collectDataElements.statusContent.contains(document.activeElement)) {
                collectDataElements.collapseToggle.focus({ preventScroll: true });
            }
            collectDataElements.statusContent.hidden = shouldCollapse;
            collectDataElements.status.classList.toggle('collapsed', shouldCollapse);
            collectDataElements.collapseToggle.setAttribute('aria-expanded', String(!shouldCollapse));
            const action = shouldCollapse ? 'Expand' : 'Collapse';
            const label = action + ' collection details';
            collectDataElements.collapseToggle.setAttribute('aria-label', label);
            collectDataElements.collapseToggle.title = label;
        }

        function collectDataResetDownload() {
            collectDataElements.downloads.hidden = true;
            [collectDataElements.csvDownload, collectDataElements.xlsxDownload].forEach((link) => {
                link.hidden = false;
                link.removeAttribute('href');
                link.removeAttribute('download');
            });
        }

        function collectDataResetPlots() {
            collectDataElements.plots.hidden = true;
            collectDataElements.acPowerCard.hidden = true;
            collectDataElements.energyCard.hidden = true;
            collectDataElements.plotNote.hidden = true;
            collectDataElements.plotNote.textContent = '';
            collectDataElements.acPowerPlot.removeAttribute('src');
            delete collectDataElements.acPowerPlot.dataset.collectionId;
            collectDataElements.energyPlot.removeAttribute('src');
            delete collectDataElements.energyPlot.dataset.collectionId;
        }

        function collectDataClearResult() {
            collectDataResetDownload();
            collectDataResetPlots();
            collectDataSetCollapsed(false);
            collectDataElements.collapseToggle.hidden = true;
            collectDataElements.status.hidden = true;
            collectDataElements.summary.hidden = true;
        }

        function collectDataInvalidateResult() {
            if (collectDataBusy) return;
            collectDataRevision += 1;
            collectDataActiveId = null;
            collectDataPollFailures = 0;
            window.clearTimeout(collectDataPollTimer);
            collectDataClearError();
            collectDataClearResult();
        }

        function collectDataSetProgress(progress) {
            const bounded = Math.min(100, Math.max(0, Number(progress) || 0));
            const rounded = Math.round(bounded);
            collectDataElements.progress.setAttribute('aria-valuenow', String(rounded));
            collectDataElements.progressFill.style.width = rounded + '%';
            collectDataElements.progressText.textContent = rounded + '%';
        }

        function collectDataStateText(state) {
            if (state === 'completed') return 'Complete';
            if (state === 'failed') return 'Needs attention';
            if (state === 'collecting') return 'Collecting';
            return 'Queued';
        }

        function collectDataRenderPlots(record, result) {
            collectDataResetPlots();
            collectDataElements.plots.hidden = false;
            const collectionId = String(record?.collection_id || '');
            const safeId = /^collect_[a-f0-9]{24}$/.test(collectionId) ? collectionId : null;
            const plots = result?.plots && typeof result.plots === 'object' ? result.plots : {};
            const definitions = [
                {
                    key: 'measured_ac_power',
                    route: 'measured-ac-power',
                    card: collectDataElements.acPowerCard,
                    image: collectDataElements.acPowerPlot,
                },
                {
                    key: 'cumulative_energy',
                    route: 'cumulative-energy',
                    card: collectDataElements.energyCard,
                    image: collectDataElements.energyPlot,
                },
            ];
            let rendered = 0;
            if (safeId) {
                definitions.forEach((definition) => {
                    const metadata = plots[definition.key];
                    const digest = String(metadata?.sha256 || '');
                    if (!/^[a-f0-9]{64}$/.test(digest)) return;
                    definition.image.dataset.collectionId = safeId;
                    definition.image.src = '/api/data-collections/' + encodeURIComponent(safeId)
                        + '/plots/' + definition.route + '?v=' + encodeURIComponent(digest.slice(0, 16));
                    definition.card.hidden = false;
                    rendered += 1;
                });
            }
            if (rendered) return;
            collectDataElements.plotNote.hidden = false;
            collectDataElements.plotNote.textContent = result?.plot_status === 'not_applicable'
                ? 'Select SolarEdge or Solectria power to generate measured power and energy plots.'
                : 'Measured plots were unavailable for this collection. The collected downloads are still available.';
        }

        function collectDataRender(record) {
            collectDataElements.status.hidden = false;
            collectDataElements.stateLabel.textContent = collectDataStateText(record?.state);
            collectDataElements.stage.textContent = String(record?.stage || 'Checking collection status');
            collectDataSetProgress(record?.progress);
            const result = record?.result;
            if (record?.state === 'completed' && result) {
                const seriesNames = new Set(
                    (Array.isArray(result.series) ? result.series : [])
                        .map((series) => String(series?.name || ''))
                );
                collectDataElements.summary.hidden = false;
                collectDataElements.rowCount.textContent = Number(result.row_count || 0).toLocaleString();
                collectDataElements.seriesCount.textContent = Number((result.series || []).length).toLocaleString();
                collectDataElements.solarEdgeStatus.textContent = seriesNames.has('solaredge_measured_power') ? 'Included' : 'Not selected';
                collectDataElements.solectriaStatus.textContent = seriesNames.has('solectria_measured_power') ? 'Included' : 'Not selected';
                collectDataRenderPlots(record, result);
                collectDataElements.collapseToggle.hidden = false;
                const safeId = /^collect_[a-f0-9]{24}$/.test(String(record.collection_id || ''))
                    ? record.collection_id
                    : null;
                if (safeId) {
                    const encodedId = encodeURIComponent(safeId);
                    collectDataElements.csvDownload.href = '/api/data-collections/' + encodedId + '/download';
                    const csvFilename = String(result.filename || 'sbe-collected-data.csv').replace(/[^A-Za-z0-9._-]/g, '_');
                    collectDataElements.csvDownload.setAttribute('download', csvFilename);
                    const workbook = result.workbook && typeof result.workbook === 'object' ? result.workbook : {};
                    if (/^[a-f0-9]{64}$/.test(String(workbook.sha256 || ''))) {
                        collectDataElements.xlsxDownload.href = '/api/data-collections/' + encodedId + '/download-xlsx';
                        const xlsxFilename = String(workbook.filename || 'sbe-collected-data.xlsx').replace(/[^A-Za-z0-9._-]/g, '_');
                        collectDataElements.xlsxDownload.setAttribute('download', xlsxFilename);
                    } else {
                        collectDataElements.xlsxDownload.hidden = true;
                    }
                    collectDataElements.downloads.hidden = false;
                }
            }
            if (record?.state === 'failed') {
                collectDataSetError(record?.error?.message || 'The data collection failed.', true);
            }
        }

        async function collectDataReadPayload(response) {
            try {
                return await response.json();
            } catch (_) {
                return {};
            }
        }

        function collectDataErrorDetail(payload, fallback) {
            if (typeof payload?.detail === 'string') return payload.detail;
            if (Array.isArray(payload?.detail)) {
                const messages = payload.detail.map((item) => item?.msg).filter(Boolean);
                if (messages.length) return messages.join('; ');
            }
            return fallback;
        }

        function collectDataSchedulePoll(collectionId, revision, delay = 750) {
            window.clearTimeout(collectDataPollTimer);
            collectDataPollTimer = window.setTimeout(
                () => void collectDataPoll(collectionId, revision),
                delay
            );
        }

        async function collectDataPoll(collectionId, revision) {
            if (revision !== collectDataRevision || collectionId !== collectDataActiveId) return;
            try {
                const response = await fetchWithDashboardTimeout(
                    '/api/data-collections/' + encodeURIComponent(collectionId),
                    { cache: 'no-store' },
                    10000
                );
                const payload = await collectDataReadPayload(response);
                if (!response.ok) {
                    throw new Error(collectDataErrorDetail(payload, 'Collection status is unavailable.'));
                }
                if (revision !== collectDataRevision) return;
                collectDataPollFailures = 0;
                collectDataRender(payload);
                if (payload.state === 'queued' || payload.state === 'collecting') {
                    collectDataSchedulePoll(collectionId, revision, 900);
                    return;
                }
                collectDataSetBusy(false);
            } catch (error) {
                if (revision !== collectDataRevision) return;
                collectDataPollFailures += 1;
                if (collectDataPollFailures < 4) {
                    collectDataElements.stage.textContent = 'Reconnecting to collection status';
                    collectDataSchedulePoll(collectionId, revision, 1200 * collectDataPollFailures);
                    return;
                }
                collectDataSetBusy(false);
                collectDataSetError(error?.message || 'Collection status is unavailable.', true);
            }
        }

        function collectDataReadRequest() {
            collectDataClearError();
            const datePattern = /^\d{4}-\d{2}-\d{2}$/;
            const timePattern = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
            const fromDate = collectDataElements.fromDate.value.trim();
            const toDate = collectDataElements.toDate.value.trim();
            const fromTime = collectDataElements.fromTime.value.trim();
            const toTime = collectDataElements.toTime.value.trim();
            if (!datePattern.test(fromDate)) {
                collectDataElements.fromDate.focus();
                throw new Error('Choose a valid collection start date.');
            }
            if (!timePattern.test(fromTime)) {
                collectDataElements.fromTime.focus();
                throw new Error('Start time must use 24-hour HH:MM format.');
            }
            if (!datePattern.test(toDate)) {
                collectDataElements.toDate.focus();
                throw new Error('Choose a valid collection end date.');
            }
            if (!timePattern.test(toTime)) {
                collectDataElements.toTime.focus();
                throw new Error('End time must use 24-hour HH:MM format.');
            }
            if (fromDate + 'T' + fromTime >= toDate + 'T' + toTime) {
                collectDataElements.toDate.focus();
                throw new Error('Collection start date/time must be before the end date/time.');
            }
            const intervalValue = Number(collectDataElements.intervalValue.value);
            if (!Number.isInteger(intervalValue) || intervalValue < 1) {
                collectDataElements.intervalValue.focus();
                throw new Error('Aggregation interval must be a whole number of at least 1.');
            }
            const dataGroups = Array.from(
                collectDataElements.form.querySelectorAll('input[name="collectDataGroup"]:checked')
            ).map((input) => input.value);
            if (!dataGroups.length) {
                collectDataElements.form.querySelector('input[name="collectDataGroup"]')?.focus();
                throw new Error('Select at least one system-data group.');
            }
            return {
                from_date: fromDate,
                from_time: fromTime,
                to_date: toDate,
                to_time: toTime,
                interval_value: intervalValue,
                interval_unit: collectDataElements.intervalUnit.value,
                data_groups: dataGroups,
            };
        }

        async function collectDataSubmit(event) {
            event.preventDefault();
            let request;
            try {
                request = collectDataReadRequest();
            } catch (error) {
                collectDataSetError(error?.message, true);
                return;
            }
            collectDataRevision += 1;
            const revision = collectDataRevision;
            collectDataActiveId = null;
            collectDataPollFailures = 0;
            window.clearTimeout(collectDataPollTimer);
            collectDataClearResult();
            collectDataElements.status.hidden = false;
            collectDataElements.stateLabel.textContent = 'Queued';
            collectDataElements.stage.textContent = 'Submitting collection request';
            collectDataSetProgress(0);
            collectDataSetBusy(true);
            try {
                const response = await fetchWithDashboardTimeout(
                    '/api/data-collections',
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(request),
                    },
                    10000
                );
                const payload = await collectDataReadPayload(response);
                if (!response.ok) {
                    throw new Error(collectDataErrorDetail(payload, 'The collection request was rejected.'));
                }
                if (revision !== collectDataRevision) return;
                const collectionId = String(payload.collection_id || '');
                if (!/^collect_[a-f0-9]{24}$/.test(collectionId)) {
                    throw new Error('The collection service returned an invalid identifier.');
                }
                collectDataActiveId = collectionId;
                collectDataRender(payload);
                collectDataSchedulePoll(collectionId, revision, 250);
            } catch (error) {
                if (revision !== collectDataRevision) return;
                collectDataSetBusy(false);
                collectDataSetError(error?.message || 'The collection request failed.', true);
            }
        }

        function collectDataApplyDefaults() {
            const today = dateIsoInTimeZone();
            collectDataElements.fromDate.value = '2025-12-12';
            collectDataElements.toDate.value = today;
            collectDataElements.fromDate.max = today;
            collectDataElements.toDate.max = today;
        }

        function collectDataHandlePlotError(image, card) {
            image.addEventListener('error', () => {
                if (image.dataset.collectionId !== collectDataActiveId) return;
                card.hidden = true;
                collectDataElements.plotNote.hidden = false;
                collectDataElements.plotNote.textContent = 'One or more measured plots could not be loaded. The collected downloads are still available.';
            });
        }

        collectDataTab.addEventListener('click', openCollectDataView);
        [operationsNavLink, pvModelNavLink].forEach((link) => {
            link.addEventListener('click', collectDataRestoreWorkflowView, true);
        });
        collectDataElements.collapseToggle.addEventListener('click', () => {
            const expanded = collectDataElements.collapseToggle.getAttribute('aria-expanded') === 'true';
            collectDataSetCollapsed(expanded);
        });
        collectDataHandlePlotError(collectDataElements.acPowerPlot, collectDataElements.acPowerCard);
        collectDataHandlePlotError(collectDataElements.energyPlot, collectDataElements.energyCard);
        collectDataElements.form.addEventListener('submit', collectDataSubmit);
        collectDataElements.form.addEventListener('input', collectDataInvalidateResult);
        collectDataElements.form.addEventListener('change', collectDataInvalidateResult);
        collectDataApplyDefaults();
