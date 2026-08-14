        const helpTipButtons = Array.from(document.querySelectorAll('.help-tip'));

        function closeHelpTips(except = null) {
            helpTipButtons.forEach((button) => {
                if (button !== except) button.setAttribute('aria-expanded', 'false');
            });
        }

        helpTipButtons.forEach((button) => {
            button.addEventListener('click', (event) => {
                event.stopPropagation();
                const willOpen = button.getAttribute('aria-expanded') !== 'true';
                closeHelpTips(button);
                button.setAttribute('aria-expanded', String(willOpen));
            });
        });

        document.addEventListener('click', (event) => {
            if (!event.target.closest('.help-tip-wrap')) closeHelpTips();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key !== 'Escape') return;
            const activeHelp = event.target.closest?.('.help-tip');
            const hasOpenHelp = helpTipButtons.some(
                (button) => button.getAttribute('aria-expanded') === 'true'
            );
            if (!activeHelp && !hasOpenHelp) return;
            closeHelpTips();
            activeHelp?.blur();
            event.preventDefault();
            event.stopImmediatePropagation();
        });

        // ---- Run pipeline + progress polling ----
        const runBtn = document.getElementById('runBtn');
        const progressWrap = document.getElementById('progressWrap');
        const progressStage = document.getElementById('progressStage');
        const progressPct = document.getElementById('progressPct');
        const progressFill = document.getElementById('progressFill');
        const errorBanner = document.getElementById('errorBanner');
        const calibrationReviewPanel = document.getElementById('calibrationReviewPanel');
        const calibrationReviewToggle = document.getElementById('calibrationReviewToggle');
        const calibrationReviewContent = document.getElementById('calibrationReviewContent');
        const calibrationReviewSummary = document.getElementById('calibrationReviewSummary');
        const calibrationReviewSeasons = document.getElementById('calibrationReviewSeasons');
        const calibrationIssueList = document.getElementById('calibrationIssueList');
        const calibrationReviewActions = document.getElementById('calibrationReviewActions');
        const calibrationReviewActionNote = document.getElementById('calibrationReviewActionNote');
        const applyCalibrationReviewBtn = document.getElementById('applyCalibrationReviewBtn');
        const cancelCalibrationReviewBtn = document.getElementById('cancelCalibrationReviewBtn');
        const calibrationDecisionGate = document.getElementById('calibrationDecisionGate');
        const calibrationDecisionGateHeading = document.getElementById('calibrationDecisionGateHeading');
        const calibrationDecisionGateSummary = document.getElementById('calibrationDecisionGateSummary');
        const calibrationDecisionGateActions = document.getElementById('calibrationDecisionGateActions');
        const sourceDecisionAcknowledgementLabel = document.getElementById('sourceDecisionAcknowledgementLabel');
        const sourceDecisionAcknowledgement = document.getElementById('sourceDecisionAcknowledgement');
        const backToCalibrationDecisionsBtn = document.getElementById('backToCalibrationDecisionsBtn');
        const confirmCalibrationReviewBtn = document.getElementById('confirmCalibrationReviewBtn');
        const calibrationFactorPanel = document.getElementById('calibrationFactorPanel');
        const calibrationAuditLine = document.getElementById('calibrationAuditLine');
        const calibrationFactorRows = document.getElementById('calibrationFactorRows');
        const calibrationDriverInsights = document.getElementById('calibrationDriverInsights');
        const curtailmentEnabled = document.getElementById('curtailmentEnabled');
        const curtailmentLimitKw = document.getElementById('curtailmentLimitKw');
        const curtailmentLimitGroup = document.getElementById('curtailmentLimitGroup');
        const calibrateModel = document.getElementById('calibrateModel');
        const calibrationSeasonNote = document.getElementById('calibrationSeasonNote');
        const validationActionTitle = document.getElementById('validationActionTitle');
        const validationActionCopy = document.getElementById('validationActionCopy');
        const validationResultsHeading = document.getElementById('validationResultsHeading');
        const validationResultsDescription = document.getElementById('validationResultsDescription');
        const validationResultsNote = document.getElementById('validationResultsNote');
        const validationRunContext = document.getElementById('validationRunContext');
        const validationRunContextRange = document.getElementById('validationRunContextRange');
        const validationRunContextTimezone = document.getElementById('validationRunContextTimezone');
        const validationPreflightPanel = document.getElementById('validationPreflightPanel');
        const validationRunContextEfficiencyValues = {
            solaredge_inverter_efficiency: document.getElementById('validationRunContextSeInverter'),
            solaredge_bos_efficiency: document.getElementById('validationRunContextSeBos'),
            solaredge_total_efficiency: document.getElementById('validationRunContextSeTotal'),
            solectria_inverter_efficiency: document.getElementById('validationRunContextSolInverter'),
            solectria_bos_efficiency: document.getElementById('validationRunContextSolBos'),
            solectria_total_efficiency: document.getElementById('validationRunContextSolTotal'),
        };
        const validationEnergyChartTitle = document.getElementById('validationEnergyChartTitle');
        const validationAcChartTitle = document.getElementById('validationAcChartTitle');
        const uncalibratedChartCards = [
            document.getElementById('uncalibratedEnergyChartCard'),
            document.getElementById('uncalibratedAcChartCard'),
        ];
        const iamModelRadios = document.querySelectorAll('input[name="iamModel"]');
        const iamAr = document.getElementById('iamAr');
        const iamArGroup = document.getElementById('iamArGroup');
        const excelLink = document.getElementById('excelLink');
        const validationTab = document.getElementById('validationTab');
        const annualTab = document.getElementById('annualTab');
        const technoeconomicTab = document.getElementById('technoeconomicTab');
        const dashboardTitle = document.getElementById('dashboardTitle');
        const dashboardSubtitle = document.getElementById('dashboardSubtitle');
        const technoeconomicPanel = document.getElementById('technoeconomicPanel');
        const technoeconomicForm = document.getElementById('technoeconomicForm');
        const technoeconomicSourceSelect = document.getElementById('technoeconomicSourceSelect');
        const technoeconomicRefreshSourcesBtn = document.getElementById('technoeconomicRefreshSourcesBtn');
        const openAnnualSimulationBtn = document.getElementById('openAnnualSimulationBtn');
        const technoeconomicBasis = document.getElementById('technoeconomicBasis');
        const technoeconomicRealizations = document.getElementById('technoeconomicRealizations');
        const technoeconomicSeed = document.getElementById('technoeconomicSeed');
        const technoeconomicCostYear = document.getElementById('technoeconomicCostYear');
        const technoeconomicProjectLife = document.getElementById('technoeconomicProjectLife');
        const technoeconomicTransferEnabled = document.getElementById('technoeconomicTransferEnabled');
        const technoeconomicElements = {
            panel: technoeconomicPanel,
            form: technoeconomicForm,
            sourceSelect: technoeconomicSourceSelect,
            refreshSourcesButton: technoeconomicRefreshSourcesBtn,
            openAnnualButton: openAnnualSimulationBtn,
            sourceStatusPanel: document.getElementById('technoeconomicSourceStatusPanel'),
            sourceStatus: document.getElementById('technoeconomicSourceStatus'),
            sourceDetail: document.getElementById('technoeconomicSourceDetail'),
            sourceDetails: document.getElementById('technoeconomicSourceDetails'),
            basis: technoeconomicBasis,
            realizations: technoeconomicRealizations,
            seed: technoeconomicSeed,
            costYear: technoeconomicCostYear,
            projectLife: technoeconomicProjectLife,
            projectLifeEvidence: document.getElementById('technoeconomicProjectLifeEvidence'),
            discountRateEditor: document.getElementById('technoeconomicDiscountRateEditor'),
            degradationEditor: document.getElementById('technoeconomicDegradationEditor'),
            costLines: document.getElementById('technoeconomicCostLines'),
            costLinesEmpty: document.getElementById('technoeconomicCostLinesEmpty'),
            addCostLineButton: document.getElementById('technoeconomicAddCostLineBtn'),
            commercialDesign: document.getElementById('technoeconomicCommercialDesign'),
            commercialDesignEditor: document.getElementById('technoeconomicCommercialDesignEditor'),
            commercialTransfer: document.getElementById('technoeconomicCommercialTransfer'),
            transferEnabled: technoeconomicTransferEnabled,
            commercialTransferEditor: document.getElementById('technoeconomicCommercialTransferEditor'),
            assumptionEditors: document.getElementById('technoeconomicAssumptionEditors'),
            submitButton: document.getElementById('technoeconomicSubmitBtn'),
            formErrors: document.getElementById('technoeconomicFormErrors'),
            draftStatus: document.getElementById('technoeconomicDraftStatus'),
            confirmDialog: document.getElementById('technoeconomicConfirmDialog'),
            confirmSummary: document.getElementById('technoeconomicConfirmSummary'),
            confirmProvisional: document.getElementById('technoeconomicConfirmProvisional'),
            confirmError: document.getElementById('technoeconomicConfirmError'),
            confirmCancelButton: document.getElementById('technoeconomicConfirmCancelBtn'),
            confirmSubmitButton: document.getElementById('technoeconomicConfirmSubmitBtn'),
            jobPanel: document.getElementById('technoeconomicJobPanel'),
            jobState: document.getElementById('technoeconomicJobState'),
            progress: document.getElementById('technoeconomicProgress'),
            progressValue: document.getElementById('technoeconomicProgressValue'),
            progressStage: document.getElementById('technoeconomicProgressStage'),
            cancelButton: document.getElementById('technoeconomicCancelBtn'),
            retryButton: document.getElementById('technoeconomicRetryBtn'),
            deleteButton: document.getElementById('technoeconomicDeleteBtn'),
            jobError: document.getElementById('technoeconomicJobError'),
            liveStatus: document.getElementById('technoeconomicLiveStatus'),
            results: document.getElementById('technoeconomicResults'),
            resultSummary: document.getElementById('technoeconomicResultSummary'),
            metricSummary: document.getElementById('technoeconomicMetricSummary'),
            tradeoffs: document.getElementById('technoeconomicTradeoffs'),
            perYearTable: document.getElementById('technoeconomicPerYearTable'),
            perYearBody: document.getElementById('technoeconomicPerYearBody'),
            sensitivityTable: document.getElementById('technoeconomicSensitivityTable'),
            sensitivityBody: document.getElementById('technoeconomicSensitivityBody'),
            convergenceStatus: document.getElementById('technoeconomicConvergenceStatus'),
            convergenceTable: document.getElementById('technoeconomicConvergenceTable'),
            convergenceBody: document.getElementById('technoeconomicConvergenceBody'),
            cdfPlot: document.getElementById('technoeconomicCdfPlot'),
            cdfPlotFallback: document.getElementById('technoeconomicCdfPlotFallback'),
            sensitivityPlot: document.getElementById('technoeconomicSensitivityPlot'),
            sensitivityPlotFallback: document.getElementById('technoeconomicSensitivityPlotFallback'),
            convergencePlot: document.getElementById('technoeconomicConvergencePlot'),
            convergencePlotFallback: document.getElementById('technoeconomicConvergencePlotFallback'),
            provenance: document.getElementById('technoeconomicProvenance'),
            csvLink: document.getElementById('technoeconomicCsvLink'),
            xlsxLink: document.getElementById('technoeconomicXlsxLink'),
        };
        const annualRunBtn = document.getElementById('annualRunBtn');
        const annualProgressWrap = document.getElementById('annualProgressWrap');
        const annualProgressStage = document.getElementById('annualProgressStage');
        const annualProgressPct = document.getElementById('annualProgressPct');
        const annualProgressFill = document.getElementById('annualProgressFill');
        const annualErrorBanner = document.getElementById('annualErrorBanner');
        const annualCurtailmentEnabled = document.getElementById('annualCurtailmentEnabled');
        const annualCurtailmentLimitKw = document.getElementById('annualCurtailmentLimitKw');
        const annualCurtailmentLimitGroup = document.getElementById('annualCurtailmentLimitGroup');
        const annualIamModelRadios = document.querySelectorAll('input[name="annualIamModel"]');
        const annualIamAr = document.getElementById('annualIamAr');
        const annualIamArGroup = document.getElementById('annualIamArGroup');
        const annualExcelLink = document.getElementById('annualExcelLink');
        const annualYearElements = {
            grid: document.getElementById('annualYearGrid'),
            summary: document.getElementById('annualYearSelectionSummary'),
            selectAllButton: document.getElementById('annualSelectAllYearsBtn'),
            clearButton: document.getElementById('annualClearYearsBtn'),
            fromDate: document.getElementById('annualFromDate'),
            toDate: document.getElementById('annualToDate'),
        };
        const annualCalibrationElements = {
            strip: document.getElementById('annualCalibrationStrip'),
            mark: document.getElementById('annualCalibrationMark'),
            title: document.getElementById('annualCalibrationTitle'),
            badge: document.getElementById('annualCalibrationBadge'),
            summary: document.getElementById('annualCalibrationSummary'),
            window: document.getElementById('annualCalibrationWindow'),
            promoted: document.getElementById('annualCalibrationPromoted'),
            copy: document.getElementById('annualCalibrationCopy'),
            modifiedCount: document.getElementById('annualModifiedCount'),
            settingsStatus: document.getElementById('annualSettingsStatusText'),
            restoreButton: document.getElementById('annualRestoreSettingsBtn'),
            factorRows: document.getElementById('annualSeasonalFactorRows'),
            factorNote: document.getElementById('annualFactorNote'),
            actionTitle: document.getElementById('annualActionTitle'),
            actionCopy: document.getElementById('annualActionCopy'),
        };
        const annualFallbackElements = {
            drawer: document.getElementById('annualFallbackDrawer'),
            closeButton: document.getElementById('annualFallbackCloseBtn'),
            cancelButton: document.getElementById('annualFallbackCancelBtn'),
            confirmButton: document.getElementById('annualFallbackConfirmBtn'),
            windowCopy: document.getElementById('annualFallbackWindowCopy'),
            solarEdgeFactor: document.getElementById('annualFallbackSolarEdgeFactor'),
            solectriaFactor: document.getElementById('annualFallbackSolectriaFactor'),
            modifiedSettings: document.getElementById('annualFallbackModifiedSettings'),
        };
        const annualResultCalibrationElements = {
            panel: document.getElementById('annualResultCalibration'),
            basis: document.getElementById('annualResultBasis'),
            source: document.getElementById('annualResultSourceCalibration'),
            settings: document.getElementById('annualResultSettingsDelta'),
            seasonal: document.getElementById('annualResultSeasonalApplication'),
            factors: document.getElementById('annualResultAppliedFactors'),
            settingDetails: document.getElementById('annualResultSettingDetails'),
            note: document.getElementById('annualResultsNote'),
        };
        const annualYearResultElements = {
            panel: document.getElementById('annualYearResults'),
            summary: document.getElementById('annualYearResultsSummary'),
            rows: document.getElementById('annualYearResultRows'),
            distributionChart: document.getElementById('annualDistributionChart'),
            distributionChartWrap: document.getElementById('annualDistributionChartWrap'),
            distributionTitle: document.getElementById('annualDistributionTitle'),
            distributionDescription: document.getElementById('annualDistributionDescription'),
            distributionFallback: document.getElementById('annualDistributionFallback'),
            distributionSubtitle: document.getElementById('annualDistributionSubtitle'),
            distributionSeries: document.getElementById('annualDistributionSeries'),
            distributionRankedButton: document.getElementById('annualDistributionRankedBtn'),
            distributionExceedanceButton: document.getElementById('annualDistributionExceedanceBtn'),
            distributionViewNote: document.getElementById('annualDistributionViewNote'),
            distributionSampleValue: document.getElementById('annualDistributionSampleValue'),
            distributionSampleMeta: document.getElementById('annualDistributionSampleMeta'),
            distributionP90Value: document.getElementById('annualDistributionP90Value'),
            distributionP90Meta: document.getElementById('annualDistributionP90Meta'),
            distributionP50Value: document.getElementById('annualDistributionP50Value'),
            distributionP50Meta: document.getElementById('annualDistributionP50Meta'),
            distributionRangeValue: document.getElementById('annualDistributionRangeValue'),
            distributionRangeMeta: document.getElementById('annualDistributionRangeMeta'),
        };
        const operationsNavLink = document.getElementById('operationsNavLink');
        const pvModelNavLink = document.getElementById('pvModelNavLink');
        const STORAGE_KEY = 'sb-energy-dashboard-state-v1';
        const CHAT_HISTORY_STORAGE_KEY = 'sb-energy-solar-agent-conversations-v1';
        const MAX_SAVED_CHAT_CONVERSATIONS = 20;
        const MAX_RECENT_AGENT_RUNS = 10;
        const ANNUAL_FIRST_YEAR = 2011;
        const ANNUAL_FIRST_DATE = '2011-02-11';
        const ANNUAL_KNOWN_PARTIAL_YEAR_NOTES = Object.freeze({
            2022: 'known source gaps',
            2023: 'known source gaps',
        });
        const MAX_ANNUAL_MODEL_ROWS = 1048575;
        const SUPPORTED_ANNUAL_INTERVALS = Object.freeze({
            hours: new Set([1]),
        });
        const RECOGNIZED_LEGACY_ANNUAL_INTERVALS = Object.freeze({
            hours: new Set([1, 2, 3, 4, 6, 8, 12, 24]),
            days: new Set([1]),
        });

        function isSupportedAnnualInterval(value, unit) {
            if (unit === 'minutes') {
                return Number.isInteger(value) && value >= 1 && value <= 60 && 1440 % value === 0;
            }
            return Number.isInteger(value) && !!SUPPORTED_ANNUAL_INTERVALS[unit]?.has(value);
        }

        function isRecognizedAnnualInterval(value, unit) {
            return isSupportedAnnualInterval(value, unit) || (
                Number.isInteger(value) && !!RECOGNIZED_LEGACY_ANNUAL_INTERVALS[unit]?.has(value)
            );
        }
        const DEFAULT_ASSISTANT_MESSAGE = "Ask about performance, model accuracy, or explore a what-if scenario using the active dashboard context.";
        let latestJobId = null;
        let latestInputPlots = null;
        let latestResult = null;
        let currentRunState = null;
        let pendingCalibrationReview = null;
        let calibrationReviewCollapsed = false;
        let calibrationWorkflowRevision = 0;
        let calibrationReviewAbortController = null;
        let reviewedCalibrationAbortController = null;
        let calibrationControlDisabledState = null;
        let pollTimer = null;
        let activeView = 'validation';
        let validationPollRevision = 0;
        let activeMode = 'validation';
        let annualLatestJobId = null;
        let annualLatestResult = null;
        let annualRunState = null;
        let annualPollTimer = null;
        let annualCalibrationBaseline = null;
        let annualCalibrationBaselineJobId = null;
        let annualCalibrationProfileSha256 = null;
        let annualPendingFallback = null;
        let annualSeasonalFallbackDisplay = null;
        let annualFallbackReturnFocus = null;
        let annualRequestRevision = 0;
        let annualBaselineLoadRevision = 0;
        const ANNUAL_SETTING_ORDER = [
            'backtrack',
            'curtailment_enabled',
            'curtailment_limit_kw',
            'solaredge_inverter_efficiency',
            'solaredge_bos_efficiency',
            'solectria_inverter_efficiency',
            'solectria_bos_efficiency',
            'iam_model',
            'iam_a_r',
        ];
        const ANNUAL_SETTING_LABELS = {
            backtrack: 'Backtracking',
            curtailment_enabled: 'Curtailment enabled',
            curtailment_limit_kw: 'Curtailment limit',
            solaredge_inverter_efficiency: 'SolarEdge inverter efficiency',
            solaredge_bos_efficiency: 'SolarEdge balance of system',
            solectria_inverter_efficiency: 'Solectria inverter efficiency',
            solectria_bos_efficiency: 'Solectria balance of system',
            iam_model: 'IAM model',
            iam_a_r: 'IAM coefficient',
        };
        let annualPollRevision = 0;
        const STATUS_POLL_MAX_FAILURES = 5;
        const STATUS_POLL_MAX_DELAY_MS = 8000;
        let chatMessages = [{
            role: 'assistant',
            content: DEFAULT_ASSISTANT_MESSAGE,
            created_at: new Date().toISOString(),
        }];
        let chatConversations = [];
        let activeChatConversationId = null;
        let chatHistoryOpen = false;
        let chatHistoryPersistenceState = 'ok';
        let chatHistoryRevision = 0;
        let chatHistoryStickyIssue = 'none';
        let chatHydrationPending = true;
        const transientProtectedConversationIds = new Set();
        let serverSessionId = null;
        let agentServerState = {
            proposals: [],
            jobs: [],
            recent_job_ids: [],
            recent_activity_count: 0,
            history_limit: MAX_RECENT_AGENT_RUNS,
            promoted_baselines: { validation: null, annual: null },
        };
        const agentJobPollTimers = new Map();
        const agentJobStartedAt = new Map();
        const agentJobSnapshots = new Map();
        const agentProposalSnapshots = new Map();
        const agentExplainedJobs = new Set();
        const agentCompletionCards = new Set();
        let chatDraft = '';
        let chatIsSending = false;
        let activeChatAbortController = null;
        let chatDraftSaveTimer = null;
        let agentActivityExpanded = false;
        let agentActivityFilter = 'all';
        let agentActivitySelection = null;
        const CHAT_REQUEST_TIMEOUT_MS = 60000;
        const AGENT_POLL_MAX_FAILURES = 5;
        const TERMINAL_CHAT_ACTION_STATUSES = new Set([
            'done',
            'error',
            'cancelled',
            'interrupted',
            'deleted',
            'unavailable',
            'dismissed',
            'expired',
        ]);

