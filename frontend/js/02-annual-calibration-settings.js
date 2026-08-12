        function baselineSettingValue(settings, snakeName, camelName) {
            if (!settings || typeof settings !== 'object') return undefined;
            if (Object.prototype.hasOwnProperty.call(settings, snakeName)) return settings[snakeName];
            if (camelName && Object.prototype.hasOwnProperty.call(settings, camelName)) return settings[camelName];
            return undefined;
        }

        function normalizeAnnualCalibrationSettings(settings) {
            const raw = settings && typeof settings === 'object' ? settings : {};
            const numberOrNull = (value) => {
                if (value === null || value === undefined || value === '') return null;
                const number = Number(value);
                return Number.isFinite(number) ? number : null;
            };
            const iamModel = baselineSettingValue(raw, 'iam_model', 'iamModel');
            const curtailmentEnabled = baselineSettingValue(raw, 'curtailment_enabled', 'curtailmentEnabled') === true;
            return {
                backtrack: baselineSettingValue(raw, 'backtrack', 'backtrack') === true,
                curtailment_enabled: curtailmentEnabled,
                curtailment_limit_kw: curtailmentEnabled
                    ? numberOrNull(baselineSettingValue(raw, 'curtailment_limit_kw', 'curtailmentLimitKw'))
                    : null,
                solaredge_inverter_efficiency: numberOrNull(baselineSettingValue(raw, 'solaredge_inverter_efficiency', 'solaredgeInverterEfficiency')),
                solaredge_bos_efficiency: numberOrNull(baselineSettingValue(raw, 'solaredge_bos_efficiency', 'solaredgeBosEfficiency')),
                solectria_inverter_efficiency: numberOrNull(baselineSettingValue(raw, 'solectria_inverter_efficiency', 'solectriaInverterEfficiency')),
                solectria_bos_efficiency: numberOrNull(baselineSettingValue(raw, 'solectria_bos_efficiency', 'solectriaBosEfficiency')),
                iam_model: iamModel === 'martin_ruiz' ? 'martin_ruiz' : 'physical',
                iam_a_r: iamModel === 'martin_ruiz'
                    ? numberOrNull(baselineSettingValue(raw, 'iam_a_r', 'iamAr'))
                    : null,
            };
        }

        function readAnnualInheritedSettings() {
            const iamModel = getSelectedIamModel(annualIamModelRadios);
            return {
                backtrack: document.getElementById('annualBacktrack').checked,
                curtailment_enabled: annualCurtailmentEnabled.checked,
                curtailment_limit_kw: annualCurtailmentEnabled.checked
                    ? finiteOrNull(annualCurtailmentLimitKw.value)
                    : null,
                solaredge_inverter_efficiency: finiteOrNull(document.getElementById('annualSolaredgeInverterEfficiency').value),
                solaredge_bos_efficiency: finiteOrNull(document.getElementById('annualSolaredgeBosEfficiency').value),
                solectria_inverter_efficiency: finiteOrNull(document.getElementById('annualSolectriaInverterEfficiency').value),
                solectria_bos_efficiency: finiteOrNull(document.getElementById('annualSolectriaBosEfficiency').value),
                iam_model: iamModel,
                iam_a_r: iamModel === 'martin_ruiz' ? finiteOrNull(annualIamAr.value) : null,
            };
        }

        function applyAnnualCalibrationSettings(settings) {
            const normalized = normalizeAnnualCalibrationSettings(settings);
            document.getElementById('annualBacktrack').checked = normalized.backtrack;
            annualCurtailmentEnabled.checked = normalized.curtailment_enabled;
            if (normalized.curtailment_limit_kw !== null) {
                annualCurtailmentLimitKw.value = String(normalized.curtailment_limit_kw);
            }
            const setNumber = (id, value) => {
                if (value !== null) document.getElementById(id).value = String(value);
            };
            setNumber('annualSolaredgeInverterEfficiency', normalized.solaredge_inverter_efficiency);
            setNumber('annualSolaredgeBosEfficiency', normalized.solaredge_bos_efficiency);
            setNumber('annualSolectriaInverterEfficiency', normalized.solectria_inverter_efficiency);
            setNumber('annualSolectriaBosEfficiency', normalized.solectria_bos_efficiency);
            setSelectedIamModel(annualIamModelRadios, normalized.iam_model);
            if (normalized.iam_a_r !== null) annualIamAr.value = String(normalized.iam_a_r);
            syncAnnualCurtailmentLimit();
            syncAnnualIamAr();
        }

        function annualSettingValuesMatch(left, right) {
            if (left === null || left === undefined || right === null || right === undefined) {
                return left === right;
            }
            if (typeof left === 'number' || typeof right === 'number') {
                const a = Number(left);
                const b = Number(right);
                return Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) <= 1e-12;
            }
            return left === right;
        }

        function formatAnnualSettingValue(key, value) {
            if (value === null || value === undefined) return 'not applied';
            if (key === 'backtrack' || key === 'curtailment_enabled') return value ? 'On' : 'Off';
            if (key === 'iam_model') return value === 'martin_ruiz' ? 'Martin–Ruiz' : 'Physical';
            if (typeof value === 'number') return String(value);
            return String(value);
        }

        function annualModifiedSettings() {
            if (!annualCalibrationBaseline?.settings) return [];
            const baseline = normalizeAnnualCalibrationSettings(annualCalibrationBaseline.settings);
            const current = readAnnualInheritedSettings();
            return ANNUAL_SETTING_ORDER.filter((key) => !annualSettingValuesMatch(current[key], baseline[key])).map((key) => ({
                key,
                label: ANNUAL_SETTING_LABELS[key],
                baseline: baseline[key],
                current: current[key],
            }));
        }

        function renderAnnualSettingDiffs() {
            const hasBaseline = !!annualCalibrationBaseline?.settings;
            const modified = hasBaseline ? annualModifiedSettings() : [];
            const modifiedKeys = new Set(modified.map((item) => item.key));
            const baseline = hasBaseline
                ? normalizeAnnualCalibrationSettings(annualCalibrationBaseline.settings)
                : {};
            ANNUAL_SETTING_ORDER.forEach((key) => {
                document.querySelectorAll('[data-annual-setting-field="' + key + '"]').forEach((field) => {
                    field.classList.toggle('is-modified', modifiedKeys.has(key));
                });
                document.querySelectorAll('[data-annual-setting-origin="' + key + '"]').forEach((origin) => {
                    origin.hidden = !hasBaseline;
                    origin.classList.toggle('modified', modifiedKeys.has(key));
                    origin.textContent = modifiedKeys.has(key)
                        ? 'Modified · was ' + formatAnnualSettingValue(key, baseline[key])
                        : 'From calibration';
                });
            });
            const count = modified.length;
            annualCalibrationElements.modifiedCount.textContent = count + ' setting' + (count === 1 ? '' : 's') + ' changed';
            annualCalibrationElements.modifiedCount.classList.toggle('has-changes', count > 0);
            annualCalibrationElements.restoreButton.disabled = !hasBaseline || count === 0;
            annualCalibrationElements.settingsStatus.textContent = hasBaseline
                ? (count ? 'Overrides apply only to this annual run.' : 'All nine shared settings match calibration.')
                : 'Annual settings are using physics-model defaults.';
            return modified;
        }

        function restoreAnnualCalibrationSettings() {
            if (!annualCalibrationBaseline?.settings) return;
            annualRequestRevision += 1;
            clearAnnualFallbackConfirmation();
            clearAnnualSeasonalFallbackDisplay();
            applyAnnualCalibrationSettings(annualCalibrationBaseline.settings);
            renderAnnualSettingDiffs();
            saveDashboardState();
            annualCalibrationElements.restoreButton.focus();
        }

        function annualFactorRecord(baseline, season) {
            const factors = baseline?.seasonal_factors;
            if (!factors || typeof factors !== 'object') return null;
            const record = factors[season];
            return record && typeof record === 'object' ? record : null;
        }

        function normalizeAnnualFallbackFactors(factors) {
            if (!factors || typeof factors !== 'object') return null;
            const readFactor = (system) => {
                const systemValue = factors[system] ?? factors.systems?.[system];
                const rawValue = systemValue && typeof systemValue === 'object'
                    ? systemValue.factor
                    : systemValue;
                const value = Number(rawValue);
                return Number.isFinite(value) ? value : null;
            };
            const solaredge = readFactor('solaredge');
            const solectria = readFactor('solectria');
            return solaredge !== null && solectria !== null
                ? { solaredge, solectria }
                : null;
        }

        function normalizeAnnualSeasonalFallbackDisplay(value) {
            if (!value || typeof value !== 'object') return null;
            const mapping = value.mapping && typeof value.mapping === 'object' ? value.mapping : {};
            const sourceSeason = String(
                value.source_season || value.from_season || mapping.source_season || mapping.from_season || ''
            ).toLowerCase();
            const targetSeason = String(
                value.target_season || value.to_season || mapping.target_season || mapping.to_season || ''
            ).toLowerCase();
            const factors = normalizeAnnualFallbackFactors(
                value.factors || value.spring_factors || value.seasonal_factors?.fall
            );
            if (sourceSeason !== 'spring' || targetSeason !== 'fall' || !factors) return null;
            return {
                source_season: 'spring',
                target_season: 'fall',
                factors,
                baseline_job_id: value.baseline_job_id ? String(value.baseline_job_id) : null,
                profile_sha256: value.profile_sha256 || value.origin_profile_sha256
                    ? String(value.profile_sha256 || value.origin_profile_sha256)
                    : null,
                confirmation_context_sha256: value.confirmation_context_sha256
                    ? String(value.confirmation_context_sha256)
                    : null,
            };
        }

        function activeAnnualSeasonalFallback(baseline) {
            const fallback = annualSeasonalFallbackDisplay;
            if (!fallback || !baseline) return null;
            const baselineJobId = baseline.job_id ? String(baseline.job_id) : null;
            const profileSha256 = baseline.profile_sha256 ? String(baseline.profile_sha256) : null;
            if (fallback.baseline_job_id && baselineJobId && fallback.baseline_job_id !== baselineJobId) return null;
            if (fallback.profile_sha256 && profileSha256 && fallback.profile_sha256 !== profileSha256) return null;
            return fallback;
        }

        function setAnnualSeasonalFallbackDisplay(value, { render = true } = {}) {
            annualSeasonalFallbackDisplay = normalizeAnnualSeasonalFallbackDisplay(value);
            if (render) renderAnnualSeasonalFactors(annualCalibrationBaseline);
            return annualSeasonalFallbackDisplay;
        }

        function clearAnnualSeasonalFallbackDisplay({ render = true } = {}) {
            const changed = annualSeasonalFallbackDisplay !== null;
            annualSeasonalFallbackDisplay = null;
            if (changed && render) renderAnnualSeasonalFactors(annualCalibrationBaseline);
        }

        function annualFactorValue(baseline, season, system) {
            const fallback = activeAnnualSeasonalFallback(baseline);
            if (fallback?.target_season === season) return fallback.factors[system] ?? null;
            const record = annualFactorRecord(baseline, season);
            if (!record) return null;
            const systemValue = record[system] ?? record.systems?.[system];
            const rawValue = systemValue && typeof systemValue === 'object'
                ? systemValue.factor
                : systemValue;
            const value = Number(rawValue);
            return Number.isFinite(value) ? value : null;
        }

        function annualSeasonCovered(baseline, season) {
            const fallback = activeAnnualSeasonalFallback(baseline);
            if (fallback?.target_season === season) return true;
            const coverage = baseline?.factor_coverage;
            if (Array.isArray(coverage)) {
                const match = coverage.find((item) => (typeof item === 'string' ? item : item?.season) === season);
                if (typeof match === 'string') return true;
                if (match && typeof match === 'object') return match.available !== false && match.covered !== false;
            }
            if (coverage && typeof coverage === 'object' && Object.prototype.hasOwnProperty.call(coverage, season)) {
                const value = coverage[season];
                if (typeof value === 'boolean') return value;
                if (value && typeof value === 'object') return value.available !== false && value.covered !== false;
            }
            return annualFactorValue(baseline, season, 'solaredge') !== null &&
                annualFactorValue(baseline, season, 'solectria') !== null;
        }

        function formatAnnualFactor(value) {
            return value === null ? '—' : Number(value).toFixed(4);
        }

        function formatAnnualFactorCompact(value) {
            if (value === null) return '—';
            return Number(value).toFixed(4);
        }

        function renderAnnualSeasonalFactors(baseline, loading = false) {
            const fallback = !loading ? activeAnnualSeasonalFallback(baseline) : null;
            const seasons = [
                ['winter', 'Winter', 'Dec–Feb'],
                ['spring', 'Spring', 'Mar–May'],
                ['summer', 'Summer', 'Jun–Aug'],
                ['fall', 'Fall', 'Sep–Nov'],
            ];
            seasons.forEach(([key]) => {
                const state = document.querySelector('[data-annual-season="' + key + '"]');
                const covered = !loading && !!baseline && annualSeasonCovered(baseline, key);
                const substituted = fallback?.target_season === key;
                state.classList.toggle('loading', loading);
                state.classList.toggle('missing', !loading && !covered);
                state.classList.toggle('substituted', substituted);
                state.querySelector('span').textContent = loading
                    ? 'Checking'
                    : (substituted ? 'Spring copied' : (covered ? 'Ready' : 'Missing'));
            });
            annualCalibrationElements.factorRows.replaceChildren();
            seasons.forEach(([key, label, months]) => {
                const row = document.createElement('tr');
                const seasonCell = document.createElement('td');
                const substituted = fallback?.target_season === key;
                seasonCell.textContent = label + ' (' + months + ')' + (substituted ? ' · Spring copy' : '');
                row.appendChild(seasonCell);
                ['solaredge', 'solectria'].forEach((system) => {
                    const cell = document.createElement('td');
                    const value = loading ? null : annualFactorValue(baseline, key, system);
                    cell.textContent = loading ? '--' : formatAnnualFactorCompact(value);
                    if (!loading && value !== null) cell.title = 'Exact factor: ' + formatAnnualFactor(value);
                    cell.classList.toggle('annual-factor-missing', !loading && value === null);
                    row.appendChild(cell);
                });
                annualCalibrationElements.factorRows.appendChild(row);
            });
            annualCalibrationElements.factorNote.classList.remove('warning');
            if (loading) {
                annualCalibrationElements.factorNote.textContent = 'Season coverage will appear after the current calibration is verified.';
            } else if (!baseline) {
                annualCalibrationElements.factorNote.textContent = 'No promoted calibration is available. This annual run will remain physics-only.';
                annualCalibrationElements.factorNote.classList.add('warning');
            } else if (fallback) {
                annualCalibrationElements.factorNote.textContent = 'Fall now uses the exact Spring factors shown above for this annual run.';
            } else if (!annualSeasonCovered(baseline, 'fall') && annualSeasonCovered(baseline, 'spring')) {
                annualCalibrationElements.factorNote.textContent = 'Fall is missing. If the selected MIDC years require Fall, you will be asked to approve an exact Spring → Fall substitution before any job starts.';
                annualCalibrationElements.factorNote.classList.add('warning');
            } else {
                annualCalibrationElements.factorNote.textContent = 'Available factors are frozen from the reviewed calibration and will not be refit against annual MIDC data.';
            }
        }

        function formatAnnualCalibrationDate(value) {
            if (!value) return '--';
            const text = String(value);
            if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
                const date = new Date(text + 'T00:00:00Z');
                return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' });
            }
            return formatDashboardTimestamp(text);
        }

        function renderAnnualCalibrationBaseline(baseline, { state = 'verified', message = '' } = {}) {
            const elements = annualCalibrationElements;
            elements.strip.classList.remove('loading', 'unavailable', 'conflict');
            if (!baseline) {
                elements.strip.classList.add(state === 'loading' ? 'loading' : 'unavailable');
                elements.mark.textContent = state === 'loading' ? '…' : '!';
                elements.title.textContent = state === 'loading' ? 'Loading current calibration' : 'No promoted calibration available';
                elements.badge.textContent = state === 'loading' ? 'Checking' : 'Physics only';
                elements.summary.hidden = true;
                elements.copy.hidden = false;
                elements.copy.textContent = message || (state === 'loading'
                    ? 'Checking for the current promoted, reviewed calibration…'
                    : 'Annual Simulation remains available with physics-only predictions until a reviewed calibration is promoted.');
                renderAnnualSeasonalFactors(null, state === 'loading');
                renderAnnualSettingDiffs();
                elements.actionTitle.textContent = 'Run physics-only annual simulation';
                elements.actionCopy.textContent = 'No calibration baseline will be attached to this request.';
                resetAnnualRunBtn();
                return;
            }
            if (state === 'conflict') elements.strip.classList.add('conflict');
            elements.mark.textContent = state === 'conflict' ? '!' : '✓';
            elements.title.textContent = state === 'conflict' ? 'Promoted calibration changed' : 'Inherited calibrated model';
            elements.badge.textContent = state === 'conflict' ? 'Review required' : 'Verified';
            const windowData = baseline.calibration_window || {};
            const windowStart = windowData.from_date ?? windowData.from ?? windowData.start;
            const windowEnd = windowData.to_date ?? windowData.to ?? windowData.end;
            elements.window.textContent = windowStart || windowEnd
                ? formatAnnualCalibrationDate(windowStart) + ' – ' + formatAnnualCalibrationDate(windowEnd)
                : '--';
            elements.promoted.textContent = formatAnnualCalibrationDate(baseline.promoted_at);
            elements.summary.hidden = false;
            const baselineMessage = message || (state === 'conflict'
                ? 'The baseline changed before the run was queued. Its nine shared settings were refreshed; review them before running again.'
                : '');
            elements.copy.textContent = baselineMessage;
            elements.copy.hidden = !baselineMessage;
            renderAnnualSeasonalFactors(baseline);
            renderAnnualSettingDiffs();
            elements.actionTitle.textContent = 'Review & run';
            elements.actionCopy.textContent = 'The baseline, setting differences, and exact seasonal factors will be recorded with the annual result.';
            resetAnnualRunBtn();
        }

        async function loadCurrentCalibration({ forceSettings = false, conflictMessage = '' } = {}) {
            const loadRevision = ++annualBaselineLoadRevision;
            if (!annualCalibrationBaseline) renderAnnualCalibrationBaseline(null, { state: 'loading' });
            try {
                const response = await fetch('/api/current-calibration', { cache: 'no-store' });
                if (!response.ok) throw new Error('Current calibration request failed (' + response.status + ')');
                const baseline = await response.json();
                if (loadRevision !== annualBaselineLoadRevision) return null;
                if (!baseline?.available) {
                    const hadBaseline = !!annualCalibrationBaselineJobId;
                    clearAnnualSeasonalFallbackDisplay({ render: false });
                    annualCalibrationBaseline = null;
                    annualCalibrationBaselineJobId = null;
                    annualCalibrationProfileSha256 = null;
                    if (hadBaseline) clearAnnualFallbackConfirmation();
                    renderAnnualCalibrationBaseline(null, {
                        state: 'unavailable',
                        message: hadBaseline
                            ? 'The previously inherited calibration is no longer promoted. Review this physics-only annual run before continuing.'
                            : '',
                    });
                    saveDashboardState();
                    return null;
                }
                const nextJobId = String(baseline.job_id || '');
                const nextProfile = String(baseline.profile_sha256 || '');
                const previousJobId = annualCalibrationBaselineJobId;
                const previousProfile = annualCalibrationProfileSha256;
                const changed = !!previousJobId && (previousJobId !== nextJobId || (!!previousProfile && previousProfile !== nextProfile));
                const shouldApplySettings = forceSettings || !previousJobId || changed;
                if (changed) {
                    annualRequestRevision += 1;
                    clearAnnualFallbackConfirmation();
                    clearAnnualSeasonalFallbackDisplay({ render: false });
                }
                annualCalibrationBaseline = baseline;
                annualCalibrationBaselineJobId = nextJobId;
                annualCalibrationProfileSha256 = nextProfile;
                if (shouldApplySettings) applyAnnualCalibrationSettings(baseline.settings);
                renderAnnualCalibrationBaseline(baseline, {
                    state: changed || conflictMessage ? 'conflict' : 'verified',
                    message: conflictMessage,
                });
                saveDashboardState();
                return baseline;
            } catch (error) {
                if (loadRevision !== annualBaselineLoadRevision) return null;
                annualCalibrationBaseline = null;
                renderAnnualCalibrationBaseline(null, {
                    state: 'unavailable',
                    message: 'The current calibration could not be verified. Annual Simulation is temporarily physics-only; refresh before relying on inherited settings.',
                });
                return null;
            }
        }

        function setAnnualFallbackVisible(visible, { focus = true } = {}) {
            const drawer = annualFallbackElements.drawer;
            drawer.classList.toggle('visible', visible);
            drawer.hidden = !visible;
            drawer.setAttribute('aria-hidden', String(!visible));
            if (visible && focus) {
                setTimeout(() => {
                    drawer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                    annualFallbackElements.confirmButton.focus();
                }, 0);
            }
        }

        function clearAnnualFallbackConfirmation({ restoreFocus = false } = {}) {
            const returnFocus = annualFallbackReturnFocus;
            annualPendingFallback = null;
            annualFallbackReturnFocus = null;
            annualFallbackElements.confirmButton.disabled = false;
            annualFallbackElements.confirmButton.textContent = 'Use Spring for Fall';
            setAnnualFallbackVisible(false, { focus: false });
            if (restoreFocus && returnFocus && document.contains(returnFocus)) returnFocus.focus();
        }

        function localModifiedSettingsSummary() {
            const modified = annualModifiedSettings();
            if (!modified.length) return 'No inherited settings were modified.';
            return 'Modified settings: ' + modified.map((item) =>
                item.label + ' (' + formatAnnualSettingValue(item.key, item.baseline) + ' → ' + formatAnnualSettingValue(item.key, item.current) + ')'
            ).join('; ') + '.';
        }

        function openAnnualFallbackConfirmation(body, detail, requestRevision) {
            clearAnnualSeasonalFallbackDisplay();
            const mapping = detail?.mapping || {};
            const sourceSeason = String(mapping.source_season || '').toLowerCase();
            const targetSeason = String(mapping.target_season || '').toLowerCase();
            const contextHash = String(detail?.confirmation_context_sha256 || '');
            const springFactors = detail?.spring_factors || {};
            const solarEdge = Number(springFactors.solaredge);
            const solectria = Number(springFactors.solectria);
            if (sourceSeason !== 'spring' || targetSeason !== 'fall' || !contextHash || !Number.isFinite(solarEdge) || !Number.isFinite(solectria)) {
                showAnnualError('The server returned an invalid seasonal-fallback confirmation. No annual job was started.');
                annualProgressWrap.classList.remove('visible');
                annualRunState = null;
                resetAnnualRunBtn();
                return;
            }
            annualPendingFallback = {
                body: JSON.parse(JSON.stringify(body)),
                requestRevision,
                confirmation_context_sha256: contextHash,
                source_season: 'spring',
                target_season: 'fall',
                factors: { solaredge: solarEdge, solectria },
                baseline_job_id: detail.baseline_job_id || annualCalibrationBaseline?.job_id || null,
                profile_sha256: detail.profile_sha256 || annualCalibrationBaseline?.profile_sha256 || null,
            };
            const activeElement = document.activeElement;
            annualFallbackReturnFocus = activeElement
                && activeElement !== document.body
                && activeElement !== document.documentElement
                ? activeElement
                : annualRunBtn;
            const calibrationWindow = annualCalibrationBaseline?.calibration_window || {};
            const start = calibrationWindow.from_date ?? calibrationWindow.from ?? calibrationWindow.start;
            const end = calibrationWindow.to_date ?? calibrationWindow.to ?? calibrationWindow.end;
            annualFallbackElements.windowCopy.textContent = 'Fall (Sep–Nov) factors are not available in the inherited calibration window' +
                (start || end ? ' (' + formatAnnualCalibrationDate(start) + ' – ' + formatAnnualCalibrationDate(end) + ')' : '') + '.';
            annualFallbackElements.solarEdgeFactor.textContent = formatAnnualFactor(solarEdge);
            annualFallbackElements.solectriaFactor.textContent = formatAnnualFactor(solectria);
            annualFallbackElements.modifiedSettings.textContent = Array.isArray(detail.modified_settings)
                ? annualSettingsDeltaDescription(detail.modified_settings)
                : localModifiedSettingsSummary();
            annualProgressWrap.classList.remove('visible');
            annualRunState = { state: 'confirmation_required', progress: 0, stage: 'Seasonal confirmation required' };
            resetAnnualRunBtn();
            setAnnualFallbackVisible(true);
            saveDashboardState();
        }

        function cancelAnnualFallbackConfirmation() {
            annualRequestRevision += 1;
            clearAnnualFallbackConfirmation({ restoreFocus: true });
            annualProgressWrap.classList.remove('visible');
            annualRunState = null;
            resetAnnualRunBtn();
            saveDashboardState();
        }

        function handleAnnualFallbackKeydown(event) {
            if (!annualFallbackElements.drawer.classList.contains('visible')) return;
            if (event.key === 'Escape') {
                event.preventDefault();
                cancelAnnualFallbackConfirmation();
            }
        }

        function estimateAnnualModelRows(years, intervalValue, intervalUnit) {
            const secondsByUnit = { minutes: 60, hours: 3600, days: 86400 };
            const intervalSeconds = intervalValue * (secondsByUnit[intervalUnit] || 0);
            const selectedDays = years
                .map(annualYearDateRange)
                .filter(Boolean)
                .reduce((total, range) => {
                    const start = Date.parse(range.periodStart + 'T00:00:00Z');
                    const end = Date.parse(range.periodEnd + 'T00:00:00Z');
                    return total + Math.floor((end - start) / 86400000) + 1;
                }, 0);
            return intervalSeconds > 0
                ? Math.ceil(selectedDays * 86400 / intervalSeconds)
                : 0;
        }

        function updateAnnualRuntimeWarning() {
            const warning = document.getElementById('annualRuntimeWarning');
            const years = readAnnualSelectedYears();
            const intervalValue = Number(document.getElementById('annualIntervalValue').value);
            const intervalUnit = document.getElementById('annualIntervalUnit').value;
            const intervalSeconds = intervalValue * ({ minutes: 60, hours: 3600, days: 86400 }[intervalUnit] || 0);
            const estimatedRows = estimateAnnualModelRows(years, intervalValue, intervalUnit);
            const subHour = intervalSeconds > 0 && intervalSeconds < 3600;
            const messages = [];
            if (subHour) {
                messages.push(
                    intervalValue + '-minute resolution will produce approximately ' +
                    estimatedRows.toLocaleString() + ' model rows for the selected years.'
                );
            }
            if (estimatedRows > MAX_ANNUAL_MODEL_ROWS) {
                messages.push(
                    'This exceeds the ' + MAX_ANNUAL_MODEL_ROWS.toLocaleString() +
                    '-row Excel export limit; select fewer years or a longer interval.'
                );
            }
            if (years.length > 1) {
                messages.push(years.length + ' years are selected; download and model time will increase.');
            }
            warning.textContent = messages.join(' ');
            warning.classList.toggle('visible', messages.length > 0);
        }

