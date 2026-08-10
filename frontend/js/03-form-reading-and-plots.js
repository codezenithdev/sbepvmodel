        function readEfficiency(id, label) {
            const input = document.getElementById(id);
            const value = parseFloat(input.value);
            if (!Number.isFinite(value) || value < 0 || value > 1) {
                showError(label + ' must be a decimal between 0 and 1.');
                input.focus();
                return null;
            }
            return value;
        }

        function read24HourTime(id, label) {
            const input = document.getElementById(id);
            const value = input.value.trim();
            if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value)) {
                showError(label + ' must use 24-hour HH:MM format (for example, 18:30).');
                input.focus();
                return null;
            }
            return value;
        }

        function readPositiveInteger(id, label) {
            const input = document.getElementById(id);
            const value = Number(input.value);
            if (!Number.isInteger(value) || value < 1) {
                showError(label + ' must be a whole number of at least 1.');
                input.focus();
                return null;
            }
            return value;
        }

        function readValidationWindow(fromTime, toTime) {
            const fromInput = document.getElementById('fromDate');
            const toInput = document.getElementById('toDate');
            const fromDate = fromInput.value.trim();
            const toDate = toInput.value.trim();
            const datePattern = /^\d{4}-\d{2}-\d{2}$/;
            if (!datePattern.test(fromDate)) {
                showError('Choose a valid start date.');
                fromInput.focus();
                return null;
            }
            if (!datePattern.test(toDate)) {
                showError('Choose a valid end date.');
                toInput.focus();
                return null;
            }
            if (fromDate + 'T' + fromTime >= toDate + 'T' + toTime) {
                showError('Start date/time must be before end date/time.');
                toInput.focus();
                return null;
            }
            return { fromDate, toDate };
        }

        function showImage(imgId, iconId, boxId, url, cacheBust = true) {
            const img = document.getElementById(imgId);
            img.onload = () => {
                document.getElementById(iconId).style.display = 'none';
                img.style.display = 'block';
                const box = document.getElementById(boxId);
                box.style.height = 'auto';
                box.style.background = 'white';
            };
            const separator = url.includes('?') ? '&' : '?';
            img.src = cacheBust ? url + separator + 'v=' + Date.now() : url;
        }

        function clearImage(imgId, iconId, boxId) {
            const img = document.getElementById(imgId);
            const icon = document.getElementById(iconId);
            const box = document.getElementById(boxId);
            img.removeAttribute('src');
            delete img.dataset.sourceUrl;
            img.style.display = 'none';
            icon.style.display = 'block';
            box.style.height = '360px';
            box.style.background = '';
        }

        function clearUncalibratedPlots() {
            clearImage('uncalibratedEnergyImg', 'uncalibratedEnergyIcon', 'uncalibratedEnergyChartBox');
            clearImage('uncalibratedAcImg', 'uncalibratedAcIcon', 'uncalibratedAcChartBox');
            uncalibratedChartCards.forEach((card) => {
                card.hidden = true;
            });
        }

        function renderUncalibratedPlots(result, calibrated, cacheBust = true) {
            const available = calibrated &&
                typeof result?.uncalibrated_energy_png === 'string' &&
                typeof result?.uncalibrated_ac_png === 'string';
            clearUncalibratedPlots();
            if (!available) return;
            uncalibratedChartCards.forEach((card) => {
                card.hidden = false;
            });
            showImage(
                'uncalibratedEnergyImg',
                'uncalibratedEnergyIcon',
                'uncalibratedEnergyChartBox',
                result.uncalibrated_energy_png,
                cacheBust,
            );
            showImage(
                'uncalibratedAcImg',
                'uncalibratedAcIcon',
                'uncalibratedAcChartBox',
                result.uncalibrated_ac_png,
                cacheBust,
            );
        }

        function clearRunImages() {
            clearImage('measuredPowerImg', 'measuredPowerIcon', 'measuredPowerChartBox');
            clearImage('irradianceImg', 'irradianceIcon', 'irradianceChartBox');
            clearImage('energyImg', 'energyIcon', 'energyChartBox');
            clearImage('acImg', 'acIcon', 'acChartBox');
            clearUncalibratedPlots();
        }

        function clearAnnualImages() {
            clearImage('annualIrradianceImg', 'annualIrradianceIcon', 'annualIrradianceChartBox');
            clearImage('annualAcImg', 'annualAcIcon', 'annualAcChartBox');
            clearImage('annualEnergyImg', 'annualEnergyIcon', 'annualEnergyChartBox');
            clearImage('annualMonthlyImg', 'annualMonthlyIcon', 'annualMonthlyChartBox');
        }

        function fmtPct(v) {
            if (v === null || v === undefined) return 'n/a';
            return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
        }

        function getFormState() {
            return {
                fromDate: document.getElementById('fromDate').value,
                fromTime: document.getElementById('fromTime').value,
                toDate: document.getElementById('toDate').value,
                toTime: document.getElementById('toTime').value,
                intervalValue: document.getElementById('intervalValue').value,
                intervalUnit: document.getElementById('intervalUnit').value,
                backtrack: document.getElementById('backtrack').checked,
                curtailmentEnabled: curtailmentEnabled.checked,
                curtailmentLimitKw: curtailmentLimitKw.value,
                calibrateModel: calibrateModel.checked,
                solaredgeInverterEfficiency: document.getElementById('solaredgeInverterEfficiency').value,
                solaredgeBosEfficiency: document.getElementById('solaredgeBosEfficiency').value,
                solectriaInverterEfficiency: document.getElementById('solectriaInverterEfficiency').value,
                solectriaBosEfficiency: document.getElementById('solectriaBosEfficiency').value,
                iamModel: getSelectedIamModel(iamModelRadios),
                iamAr: iamAr.value,
            };
        }

        function applyFormState(form) {
            if (!form) return;
            const setValue = (id, value) => {
                if (value !== undefined && value !== null) {
                    document.getElementById(id).value = value;
                }
            };
            setValue('fromDate', form.fromDate);
            setValue('fromTime', form.fromTime);
            setValue('toDate', form.toDate);
            setValue('toTime', form.toTime);
            setValue('intervalValue', form.intervalValue);
            setValue('intervalUnit', form.intervalUnit);
            setValue('curtailmentLimitKw', form.curtailmentLimitKw);
            setValue('solaredgeInverterEfficiency', form.solaredgeInverterEfficiency);
            setValue('solaredgeBosEfficiency', form.solaredgeBosEfficiency);
            setValue('solectriaInverterEfficiency', form.solectriaInverterEfficiency);
            setValue('solectriaBosEfficiency', form.solectriaBosEfficiency);
            setValue('iamAr', form.iamAr);
            if (form.backtrack !== undefined) document.getElementById('backtrack').checked = !!form.backtrack;
            if (form.curtailmentEnabled !== undefined) curtailmentEnabled.checked = !!form.curtailmentEnabled;
            if (form.calibrateModel !== undefined) calibrateModel.checked = !!form.calibrateModel;
            setSelectedIamModel(iamModelRadios, resolveSavedIamModel(form));
            syncCurtailmentLimit();
            syncIamAr();
            syncCalibrationMode();
        }

        function getAnnualFormState() {
            return {
                fromDate: document.getElementById('annualFromDate').value,
                toDate: document.getElementById('annualToDate').value,
                intervalValue: document.getElementById('annualIntervalValue').value,
                intervalUnit: document.getElementById('annualIntervalUnit').value,
                backtrack: document.getElementById('annualBacktrack').checked,
                curtailmentEnabled: annualCurtailmentEnabled.checked,
                curtailmentLimitKw: annualCurtailmentLimitKw.value,
                solaredgeInverterEfficiency: document.getElementById('annualSolaredgeInverterEfficiency').value,
                solaredgeBosEfficiency: document.getElementById('annualSolaredgeBosEfficiency').value,
                solectriaInverterEfficiency: document.getElementById('annualSolectriaInverterEfficiency').value,
                solectriaBosEfficiency: document.getElementById('annualSolectriaBosEfficiency').value,
                iamModel: getSelectedIamModel(annualIamModelRadios),
                iamAr: annualIamAr.value,
            };
        }

        function applyAnnualFormState(form) {
            if (!form) return;
            const setValue = (id, value) => {
                if (value !== undefined && value !== null) document.getElementById(id).value = value;
            };
            setValue('annualFromDate', form.fromDate);
            setValue('annualToDate', form.toDate);
            setValue('annualIntervalValue', form.intervalValue);
            setValue('annualIntervalUnit', form.intervalUnit);
            setValue('annualCurtailmentLimitKw', form.curtailmentLimitKw);
            setValue('annualSolaredgeInverterEfficiency', form.solaredgeInverterEfficiency);
            setValue('annualSolaredgeBosEfficiency', form.solaredgeBosEfficiency);
            setValue('annualSolectriaInverterEfficiency', form.solectriaInverterEfficiency);
            setValue('annualSolectriaBosEfficiency', form.solectriaBosEfficiency);
            setValue('annualIamAr', form.iamAr);
            if (form.backtrack !== undefined) document.getElementById('annualBacktrack').checked = !!form.backtrack;
            if (form.curtailmentEnabled !== undefined) annualCurtailmentEnabled.checked = !!form.curtailmentEnabled;
            setSelectedIamModel(annualIamModelRadios, resolveSavedIamModel(form));
            syncAnnualCurtailmentLimit();
            syncAnnualIamAr();
            updateAnnualRuntimeWarning();
        }

        function getTechnoeconomicFormState() {
            return {
                baselineAnnualizedCost: baselineAnnualizedCost.value,
                optimizedAnnualizedCost: optimizedAnnualizedCost.value,
            };
        }

        function applyTechnoeconomicFormState(form) {
            const values = form || {};
            baselineAnnualizedCost.value = values.baselineAnnualizedCost ?? '';
            optimizedAnnualizedCost.value = values.optimizedAnnualizedCost ?? '';
            renderTechnoeconomicAnalysis();
        }

        function finiteOrNull(value) {
            if (value === null || value === undefined || String(value).trim() === '') return null;
            const number = Number(value);
            return Number.isFinite(number) ? number : null;
        }

        function positiveIntegerOrNull(value) {
            const number = finiteOrNull(value);
            return Number.isInteger(number) && number >= 1 ? number : null;
        }

        function getCanonicalCurrentConfig(mode = activeMode) {
            const annual = mode === 'annual';
            const form = annual ? getAnnualFormState() : getFormState();
            const iamModel = form.iamModel === 'martin_ruiz' ? 'martin_ruiz' : 'physical';
            const config = {
                from_date: form.fromDate,
                to_date: form.toDate,
                backtrack: !!form.backtrack,
                curtailment_enabled: !!form.curtailmentEnabled,
                curtailment_limit_kw: form.curtailmentEnabled ? finiteOrNull(form.curtailmentLimitKw) : null,
                solaredge_inverter_efficiency: finiteOrNull(form.solaredgeInverterEfficiency),
                solaredge_bos_efficiency: finiteOrNull(form.solaredgeBosEfficiency),
                solectria_inverter_efficiency: finiteOrNull(form.solectriaInverterEfficiency),
                solectria_bos_efficiency: finiteOrNull(form.solectriaBosEfficiency),
                iam_model: iamModel,
                iam_a_r: iamModel === 'martin_ruiz' ? finiteOrNull(form.iamAr) : null,
                interval_value: positiveIntegerOrNull(form.intervalValue),
                interval_unit: form.intervalUnit,
            };
            if (!annual) {
                config.calibrate_model = !!form.calibrateModel;
                config.from_time = form.fromTime;
                config.to_time = form.toTime;
            }
            if (activeView === 'technoeconomic') {
                config.technoeconomic_analysis = getTechnoeconomicChatContext();
            }
            return config;
        }

        function requestValue(request, snakeName, camelName) {
            if (!request) return undefined;
            if (Object.prototype.hasOwnProperty.call(request, snakeName)) return request[snakeName];
            return request[camelName];
        }

        function applyPromotedRequest(mode, request) {
            if (!request) return;
            const iamModel = requestValue(request, 'iam_model', 'iamModel');
            const mapped = {
                fromDate: requestValue(request, 'from_date', 'fromDate'),
                toDate: requestValue(request, 'to_date', 'toDate'),
                backtrack: requestValue(request, 'backtrack', 'backtrack'),
                curtailmentEnabled: requestValue(request, 'curtailment_enabled', 'curtailmentEnabled'),
                curtailmentLimitKw: requestValue(request, 'curtailment_limit_kw', 'curtailmentLimitKw'),
                calibrateModel: requestValue(request, 'calibrate_model', 'calibrateModel'),
                solaredgeInverterEfficiency: requestValue(request, 'solaredge_inverter_efficiency', 'solaredgeInverterEfficiency'),
                solaredgeBosEfficiency: requestValue(request, 'solaredge_bos_efficiency', 'solaredgeBosEfficiency'),
                solectriaInverterEfficiency: requestValue(request, 'solectria_inverter_efficiency', 'solectriaInverterEfficiency'),
                solectriaBosEfficiency: requestValue(request, 'solectria_bos_efficiency', 'solectriaBosEfficiency'),
                iamModel,
                iamAr: requestValue(request, 'iam_a_r', 'iamAr'),
                intervalValue: requestValue(request, 'interval_value', 'intervalValue'),
                intervalUnit: requestValue(request, 'interval_unit', 'intervalUnit'),
            };
            if (mode === 'annual') {
                applyAnnualFormState(mapped);
                return;
            }
            mapped.fromTime = requestValue(request, 'from_time', 'fromTime');
            mapped.toTime = requestValue(request, 'to_time', 'toTime');
            if (mapped.calibrateModel === undefined) mapped.calibrateModel = true;
            applyFormState(mapped);
        }

        function setExcelLink(url, filename) {
            if (!url) {
                excelLink.classList.add('hidden');
                excelLink.removeAttribute('href');
                excelLink.removeAttribute('download');
                return;
            }
            excelLink.href = url;
            excelLink.download = filename || 'SB_Energy_Model_Results.xlsx';
            excelLink.classList.remove('hidden');
        }

        function setAnnualExcelLink(url, filename) {
            if (!url) {
                annualExcelLink.classList.add('hidden');
                annualExcelLink.removeAttribute('href');
                annualExcelLink.removeAttribute('download');
                return;
            }
            annualExcelLink.href = url;
            annualExcelLink.download = filename || 'SB_Energy_Annual_Simulation.xlsx';
            annualExcelLink.classList.remove('hidden');
        }

        function applyInputPlots(inputPlots, cacheBust = true) {
            if (!inputPlots) return;
            if (inputPlots.measured_power_png) {
                showImage('measuredPowerImg', 'measuredPowerIcon', 'measuredPowerChartBox', inputPlots.measured_power_png, cacheBust);
            }
            if (inputPlots.irradiance_png) {
                showImage('irradianceImg', 'irradianceIcon', 'irradianceChartBox', inputPlots.irradiance_png, cacheBust);
            }
        }

        function applyAnnualInputPlots(inputPlots, cacheBust = true) {
            if (inputPlots && inputPlots.irradiance_png) {
                const image = document.getElementById('annualIrradianceImg');
                if (image.dataset.sourceUrl === inputPlots.irradiance_png) return;
                image.dataset.sourceUrl = inputPlots.irradiance_png;
                showImage(
                    'annualIrradianceImg',
                    'annualIrradianceIcon',
                    'annualIrradianceChartBox',
                    inputPlots.irradiance_png,
                    cacheBust
                );
            }
        }

