        const AUTONOMY_CASE_ID = 'case_sbe_hybrid_001';
        const AUTONOMY_CASE_REVISION = 'revision_003';
        const AUTONOMY_ANNUAL_SOURCE_ID = 'ann_2024_verified_017';
        const AUTONOMY_TEA_BASIS = 'SolarTAC site · tea-calculation-v3';
        const AUTONOMY_STAGES = Object.freeze(['ask', 'verify', 'compare', 'run', 'decide']);
        const AUTONOMY_READINESS_KEYS = Object.freeze(['calibration', 'annual', 'weather', 'evidence', 'agent']);
        const AUTONOMY_LIVE_STAGES = Object.freeze(['ask', 'verify']);
        const AUTONOMY_MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
        const AUTONOMY_MAX_EVIDENCE_FILES = 10;
        const AUTONOMY_MAX_CASE_EVIDENCE_BYTES = 50 * 1024 * 1024;
        const AUTONOMY_ALLOWED_EVIDENCE_TYPES = Object.freeze([
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'text/csv',
            'image/png',
            'image/jpeg',
            'image/webp',
        ]);
        const AUTONOMY_ALLOWED_DEEP_LINKS = Object.freeze({
            calibration: {mode: 'validation', targetId: 'analysisControls'},
            '#calibration': {mode: 'validation', targetId: 'analysisControls'},
            analysisControls: {mode: 'validation', targetId: 'analysisControls'},
            annual: {mode: 'annual', targetId: 'annualControls'},
            '#annual': {mode: 'annual', targetId: 'annualControls'},
            annualControls: {mode: 'annual', targetId: 'annualControls'},
            evidence: {stage: 'verify', rail: 'evidence'},
            '#autonomy-evidence': {stage: 'verify', rail: 'evidence'},
            '#autonomy-evidence-upload': {stage: 'verify', rail: 'evidence', targetId: 'autonomyEvidenceFileInput'},
            readiness: {stage: 'verify', rail: 'readiness'},
            '#autonomy-readiness': {stage: 'verify', rail: 'readiness'},
            'source-selection': {stage: 'verify', targetId: 'autonomy-source-selection'},
            '#autonomy-source-selection': {stage: 'verify', targetId: 'autonomy-source-selection'},
            provenance: {stage: 'verify', rail: 'provenance'},
            question: {stage: 'ask', targetId: 'autonomyQuestion'},
            agent: {stage: 'ask', targetId: 'autonomyAgentComposer'},
            history: {stage: 'verify', rail: 'provenance'},
        });
        const AUTONOMY_SUPPORTED_ACTIONS = Object.freeze({
            open_calibration: 'calibration',
            open_annual_simulation: 'annual',
            open_annual: 'annual',
            inspect_source_coverage: 'readiness',
            review_source_lock: 'provenance',
            select_annual_source: '#autonomy-source-selection',
            review_evidence: 'evidence',
            continue_evidence_review: 'evidence',
            continue_manual_review: 'readiness',
            continue_without_agent: 'readiness',
            create_new_case: 'new-case',
            retry_agent: 'retry-agent',
            refresh_case: 'refresh-case',
            edit_question: 'question',
            edit_case: 'question',
            lock_case_basis: '#autonomy-source-selection',
            upload_evidence: 'evidence',
            ask_decision_agent: 'agent',
            view_history: 'history',
        });

        function autonomyFixture(config) {
            return Object.freeze({
                caseExists: true,
                caseState: 'draft',
                stage: 'ask',
                stageState: 'current',
                defaultView: 'investigation',
                briefState: 'unavailable',
                scenarioState: 'draft',
                jobState: 'none',
                signoffAllowed: false,
                signed: false,
                superseded: false,
                agentStatus: 'Ready · fixture response',
                agentAnswer: 'The current evidence supports a controlled comparison, but a named person still owns every approval boundary.',
                agentBasis: 'Agent interpretation · grounded in fixture readiness and scenario fields',
                agentLimits: 'No lifecycle result is calculated in this workspace fixture.',
                agentNextAction: 'Review the current stage and its supported next action.',
                bannerTone: 'info',
                bannerTitle: 'Decision investigation in progress',
                bannerText: 'This local fixture demonstrates the approved supervised workflow without creating records or jobs.',
                action: '',
                actionLabel: '',
                readiness: {
                    calibration: ['passed', 'Passed'],
                    annual: ['passed', 'Passed'],
                    weather: ['passed', 'Passed'],
                    evidence: ['passed', 'Passed'],
                    agent: ['passed', 'Available'],
                },
                ...config,
            });
        }

        const AUTONOMY_FIXTURE_CATALOG = Object.freeze({
            'no-case': autonomyFixture({
                label: 'Empty · no decision cases', caseExists: false, caseState: 'empty', stage: 'ask',
                bannerTitle: 'No decision cases yet',
                bannerText: 'Start a decision to frame a question and inspect readiness. Existing dashboard workflows remain available.',
                action: 'start-decision', actionLabel: 'Start a decision',
                readiness: {
                    calibration: ['not-started', 'Not checked'], annual: ['not-started', 'Not checked'],
                    weather: ['not-started', 'Not checked'], evidence: ['not-started', 'Not checked'],
                    agent: ['passed', 'Available'],
                },
            }),
            'new-case': autonomyFixture({
                label: 'New · suggested questions', stage: 'ask', caseState: 'draft', scenarioState: 'empty',
                bannerTitle: 'Frame the decision question',
                bannerText: 'Confirm the outcome that matters before reviewing evidence or scenarios.',
                action: 'focus-question', actionLabel: 'Edit decision frame',
                agentAnswer: 'Start with the decision, the comparison baseline, and the outcome that matters. Suggested questions are shown below.',
                readiness: {
                    calibration: ['passed', 'Passed'], annual: ['needs-attention', 'Needs selection'],
                    weather: ['not-started', 'Not checked'], evidence: ['needs-attention', 'Needs review'],
                    agent: ['passed', 'Available'],
                },
            }),
            'calibration-blocked': autonomyFixture({
                label: 'Blocked · calibration missing', stage: 'verify', stageState: 'blocked', caseState: 'blocked',
                bannerTone: 'danger', bannerTitle: 'Verified calibration is required',
                bannerText: 'No promoted, reviewed calibration lineage is available. This protects the Annual source and downstream TEA evidence.',
                action: 'open-calibration', actionLabel: 'Open Calibration',
                agentAnswer: 'This case cannot select a TEA-eligible Annual source until a reviewed calibration is promoted.',
                agentBasis: 'Model rule · verified promoted calibration lineage',
                agentNextAction: 'Open Calibration, complete data-quality review, and promote the reviewed result.',
                readiness: {
                    calibration: ['blocked', 'Blocked'], annual: ['blocked', 'Blocked'],
                    weather: ['not-started', 'Not checked'], evidence: ['needs-attention', 'Needs review'],
                    agent: ['passed', 'Available'],
                },
            }),
            'annual-unavailable': autonomyFixture({
                label: 'Blocked · Annual source unavailable', stage: 'verify', stageState: 'blocked', caseState: 'blocked',
                bannerTone: 'danger', bannerTitle: 'No eligible Annual Simulation source',
                bannerText: 'The case is safe, but comparison cannot proceed without a completed calibrated Annual Simulation.',
                action: 'open-annual', actionLabel: 'Open Annual Simulation',
                readiness: {
                    calibration: ['passed', 'Passed'], annual: ['blocked', 'Blocked'],
                    weather: ['not-started', 'Not checked'], evidence: ['needs-attention', 'Needs review'],
                    agent: ['passed', 'Available'],
                },
            }),
            'annual-incomplete': autonomyFixture({
                label: 'Blocked · Annual coverage incomplete', stage: 'verify', stageState: 'blocked', caseState: 'blocked',
                bannerTone: 'danger', bannerTitle: 'Annual weather coverage is incomplete',
                bannerText: 'The selected source does not meet the complete-year policy. Partial years remain visible but cannot support this comparison.',
                action: 'inspect-coverage', actionLabel: 'Inspect source coverage',
                readiness: {
                    calibration: ['passed', 'Passed'], annual: ['needs-attention', 'Needs attention'],
                    weather: ['blocked', 'Blocked'], evidence: ['needs-attention', 'Needs review'],
                    agent: ['passed', 'Available'],
                },
            }),
            'annual-stale': autonomyFixture({
                label: 'Stale · newer Annual source', stage: 'verify', stageState: 'needs-attention', caseState: 'evidence_needed',
                bannerTone: 'warning', bannerTitle: 'A newer verified Annual source is available',
                bannerText: 'The current source lock is unchanged. Review the newer source before deciding whether to create a new case.',
                action: 'review-source-lock', actionLabel: 'Review source lock',
                readiness: {
                    calibration: ['passed', 'Passed'], annual: ['stale', 'Stale'],
                    weather: ['passed', 'Passed'], evidence: ['needs-attention', 'Needs review'],
                    agent: ['passed', 'Available'],
                },
            }),
            'evidence-needed': autonomyFixture({
                label: 'Needs attention · evidence missing', stage: 'verify', stageState: 'needs-attention', caseState: 'evidence_needed',
                bannerTone: 'warning', bannerTitle: 'Two scenario inputs need evidence',
                bannerText: 'Transformer cost and recurring maintenance are still provisional. The case remains editable and no run is authorized.',
                action: 'open-evidence', actionLabel: 'Review evidence gaps',
                agentAnswer: 'Energy readiness passes. Cost evidence is the current limiting factor, so scenario outcomes would still be provisional.',
                agentBasis: 'Accepted assumption + public evidence · fixture completeness review',
                agentLimits: 'The missing project-actual values cannot be inferred from model results.',
                agentNextAction: 'Review both evidence gaps and record a rationale for any provisional value.',
                scenarioState: 'evidence-needed',
                readiness: {
                    calibration: ['passed', 'Passed'], annual: ['passed', 'Passed'],
                    weather: ['passed', 'Passed'], evidence: ['needs-attention', 'Needs attention'],
                    agent: ['passed', 'Available'],
                },
            }),
            'evidence-conflict': autonomyFixture({
                label: 'Needs attention · evidence conflict', stage: 'verify', stageState: 'needs-attention', caseState: 'evidence_needed',
                bannerTone: 'warning', bannerTitle: 'Two sources disagree',
                bannerText: 'The vendor quote and public benchmark remain side by side. A named reviewer must choose or narrow the assumption.',
                action: 'open-evidence', actionLabel: 'Compare both sources',
                scenarioState: 'evidence-conflict',
                readiness: {
                    calibration: ['passed', 'Passed'], annual: ['passed', 'Passed'],
                    weather: ['passed', 'Passed'], evidence: ['needs-attention', 'Conflicting'],
                    agent: ['passed', 'Available'],
                },
            }),
            'agent-unavailable': autonomyFixture({
                label: 'Degraded · Decision Agent unavailable', stage: 'ask', stageState: 'needs-attention', caseState: 'draft',
                bannerTone: 'warning', bannerTitle: 'Decision Agent is unavailable',
                bannerText: 'Fixture evidence, scenarios, and existing manual dashboard workflows remain safe and usable.',
                action: 'manual-review', actionLabel: 'Continue manual review',
                agentStatus: 'Unavailable · manual workspace remains usable',
                agentAnswer: 'No agent response is available. Structured readiness and scenario fixtures remain visible.',
                agentBasis: 'Deterministic fixture state',
                agentLimits: 'Questions and proposed scenario explanations are temporarily unavailable.',
                agentNextAction: 'Continue with the readiness and evidence panels.',
                readiness: {
                    calibration: ['passed', 'Passed'], annual: ['passed', 'Passed'],
                    weather: ['passed', 'Passed'], evidence: ['needs-attention', 'Needs review'],
                    agent: ['unavailable', 'Unavailable'],
                },
            }),
            'scenario-invalid': autonomyFixture({
                label: 'Blocked · invalid scenario', stage: 'compare', stageState: 'blocked', caseState: 'blocked',
                bannerTone: 'danger', bannerTitle: 'Alternative C is outside the supported contract',
                bannerText: 'Its commercial rating basis differs from the locked Annual source. The nearest supported alternative keeps the shared rating basis.',
                action: 'review-scenarios', actionLabel: 'Review supported alternative',
                scenarioState: 'invalid',
            }),
            'ready-to-confirm': autonomyFixture({
                label: 'Ready · grouped confirmation', stage: 'run', caseState: 'ready_to_run',
                bannerTone: 'success', bannerTitle: 'Three scenarios are ready for confirmation',
                bannerText: 'Review the shared source, basis, evidence, seed, realization count, and exact fixture request hashes.',
                action: 'open-confirmation', actionLabel: 'Open grouped confirmation',
                scenarioState: 'validated',
            }),
            'queued': autonomyFixture({
                label: 'Running · queued', stage: 'run', caseState: 'running', jobState: 'queued',
                bannerTitle: 'Fixture jobs are queued',
                bannerText: 'The existing worker would execute confirmed jobs sequentially. This preview does not create a queue record.',
                action: 'advance-running', actionLabel: 'Preview running state', scenarioState: 'confirmed',
            }),
            'running': autonomyFixture({
                label: 'Running · worker progress', stage: 'run', caseState: 'running', jobState: 'running',
                bannerTitle: 'Two scenarios are still running',
                bannerText: 'Baseline is complete, Alternative A is at sensitivity analysis, and Alternative B remains queued.',
                action: 'advance-partial', actionLabel: 'Preview partial results', scenarioState: 'confirmed',
            }),
            'failed': autonomyFixture({
                label: 'Recovery · one job failed', stage: 'run', stageState: 'needs-attention', caseState: 'running', jobState: 'failed',
                bannerTone: 'danger', bannerTitle: 'Alternative A failed safely',
                bannerText: 'Completed results and the case remain unchanged. A production retry would create a new immutable job.',
                action: 'preview-retry', actionLabel: 'Preview retry guidance', scenarioState: 'confirmed',
            }),
            'partial-results': autonomyFixture({
                label: 'Partial · results preview', stage: 'run', stageState: 'needs-attention', caseState: 'results_ready',
                jobState: 'partial', briefState: 'partial', bannerTone: 'warning',
                bannerTitle: 'Partial results are available',
                bannerText: 'Two scenarios completed and one failed. Preview is allowed, but no final recommendation or sign-off is available.',
                action: 'open-partial-brief', actionLabel: 'Preview partial results', scenarioState: 'confirmed',
            }),
            'results-ready': autonomyFixture({
                label: 'Completed · Decision Brief ready', stage: 'decide', caseState: 'decision_ready',
                jobState: 'completed', briefState: 'complete', bannerTone: 'success',
                bannerTitle: 'Decision Brief ready',
                bannerText: 'All selected scenario fixtures are complete. Open the brief when you are ready; this banner will not interrupt typing.',
                action: 'open-brief', actionLabel: 'Open Decision Brief', scenarioState: 'completed',
            }),
            'recommendation-provisional': autonomyFixture({
                label: 'Completed · provisional recommendation', stage: 'decide', caseState: 'decision_ready',
                defaultView: 'decision-brief', jobState: 'completed', briefState: 'provisional',
                bannerTone: 'warning', bannerTitle: 'Recommendation remains provisional',
                bannerText: 'All scenarios completed, but two accepted secondary sources still limit confidence.',
                action: 'test-reversal', actionLabel: 'Test a reversal', scenarioState: 'completed',
                readiness: {
                    calibration: ['passed', 'Passed'], annual: ['passed', 'Passed'],
                    weather: ['passed', 'Passed'], evidence: ['needs-attention', 'Provisional'],
                    agent: ['passed', 'Available'],
                },
            }),
            'decision-ready': autonomyFixture({
                label: 'Completed · ready for sign-off', stage: 'decide', caseState: 'decision_ready',
                defaultView: 'decision-brief', jobState: 'completed', briefState: 'complete',
                bannerTone: 'success', bannerTitle: 'Recommendation is ready for sign-off',
                bannerText: 'The comparison bundle, evidence summary, sensitivity, and reversal conditions are complete.',
                action: 'prepare-signoff', actionLabel: 'Prepare sign-off', scenarioState: 'completed', signoffAllowed: true,
            }),
            'signed': autonomyFixture({
                label: 'Signed · immutable revision', stage: 'decide', stageState: 'complete', caseState: 'signed',
                defaultView: 'decision-brief', jobState: 'completed', briefState: 'signed', signed: true,
                bannerTone: 'success', bannerTitle: 'Decision revision signed',
                bannerText: 'Jordan Lee accepted the recommendation. This fixture revision is immutable.',
                action: 'view-signed', actionLabel: 'View signed record', scenarioState: 'completed',
            }),
            'signed-superseded': autonomyFixture({
                label: 'Revision · signed brief superseded', stage: 'compare', stageState: 'needs-attention',
                caseState: 'draft', defaultView: 'investigation', briefState: 'superseded', superseded: true,
                bannerTone: 'warning', bannerTitle: 'A new scenario revision supersedes the current brief',
                bannerText: 'The signed revision remains immutable. Revision 4 changes transformer cost and must be validated separately.',
                action: 'review-scenarios', actionLabel: 'Review new revision', scenarioState: 'revised',
            }),
            'network-reconnecting': autonomyFixture({
                label: 'Recovery · message stream reconnecting', stage: 'ask', stageState: 'needs-attention', caseState: 'draft',
                bannerTone: 'warning', bannerTitle: 'Conversation stream interrupted',
                bannerText: 'The case, evidence, and scenario fixtures remain safe. Only the current fixture response is waiting to reconnect.',
                action: 'retry-connection', actionLabel: 'Retry fixture connection',
                agentStatus: 'Reconnecting · case state preserved',
                readiness: {
                    calibration: ['passed', 'Passed'], annual: ['passed', 'Passed'],
                    weather: ['passed', 'Passed'], evidence: ['needs-attention', 'Needs review'],
                    agent: ['needs-attention', 'Reconnecting'],
                },
            }),
            'shared-case-stale': autonomyFixture({
                label: 'Stale · shared case changed', stage: 'verify', stageState: 'needs-attention', caseState: 'evidence_needed',
                bannerTone: 'warning', bannerTitle: 'This browser has an older case snapshot',
                bannerText: 'Another authenticated user changed the shared case. Unsaved fixture typing is preserved until you refresh.',
                action: 'refresh-case', actionLabel: 'Refresh case snapshot',
            }),
        });

        const autonomyPanel = document.getElementById('autonomyPanel');
        const autonomyFixtureSelect = document.getElementById('autonomyFixtureSelect');
        const autonomyCaseEmpty = document.getElementById('autonomyCaseEmpty');
        const autonomyCaseContent = document.getElementById('autonomyCaseContent');
        const autonomyCaseTitle = document.getElementById('autonomyCaseTitle');
        const autonomyQuestion = document.getElementById('autonomyQuestion');
        const autonomyCaseStatus = document.getElementById('autonomyCaseStatus');
        const autonomyDecisionOwner = document.getElementById('autonomyDecisionOwner');
        const autonomySourceLock = document.getElementById('autonomySourceLock');
        const autonomyBasisLock = document.getElementById('autonomyBasisLock');
        const autonomyCaseRevision = document.getElementById('autonomyCaseRevision');
        const autonomyUpdatedAt = document.getElementById('autonomyUpdatedAt');
        const autonomyStageSelect = document.getElementById('autonomyStageSelect');
        const autonomyNewDecisionBtn = document.getElementById('autonomyNewDecisionBtn');
        const autonomyInvestigationViewBtn = document.getElementById('autonomyInvestigationViewBtn');
        const autonomyBriefViewBtn = document.getElementById('autonomyBriefViewBtn');
        const autonomyLiveStatus = document.getElementById('autonomyLiveStatus');
        const autonomyStateBanner = document.getElementById('autonomyStateBanner');
        const autonomyStateBannerTitle = document.getElementById('autonomyStateBannerTitle');
        const autonomyStateBannerText = document.getElementById('autonomyStateBannerText');
        const autonomyStateAction = document.getElementById('autonomyStateAction');
        const autonomyInvestigationView = document.getElementById('autonomyInvestigationView');
        const autonomyDecisionBrief = document.getElementById('autonomyDecisionBrief');
        const autonomyAgentStatus = document.getElementById('autonomyAgentStatus');
        const autonomyAgentAnswer = document.getElementById('autonomyAgentAnswer');
        const autonomyAgentBasis = document.getElementById('autonomyAgentBasis');
        const autonomyAgentLimits = document.getElementById('autonomyAgentLimits');
        const autonomyAgentNextAction = document.getElementById('autonomyAgentNextAction');
        const autonomyAgentComposer = document.getElementById('autonomyAgentComposer');
        const autonomyAgentSendBtn = document.getElementById('autonomyAgentSendBtn');
        const autonomyOpenRailBtn = document.getElementById('autonomyOpenRailBtn');
        const autonomyCloseRailBtn = document.getElementById('autonomyCloseRailBtn');
        const autonomyEvidenceRail = document.getElementById('autonomyEvidenceRail');
        const autonomyRailBackdrop = document.getElementById('autonomyRailBackdrop');
        const autonomyOpenConfirmationBtn = document.getElementById('autonomyOpenConfirmationBtn');
        const autonomyConfirmDialog = document.getElementById('autonomyConfirmDialog');
        const autonomyConfirmOperator = document.getElementById('autonomyConfirmOperator');
        const autonomyConfirmAck = document.getElementById('autonomyConfirmAck');
        const autonomyConfirmError = document.getElementById('autonomyConfirmError');
        const autonomyConfirmCancelBtn = document.getElementById('autonomyConfirmCancelBtn');
        const autonomyConfirmSubmitBtn = document.getElementById('autonomyConfirmSubmitBtn');
        const autonomyJobList = document.getElementById('autonomyJobList');
        const autonomyPartialResultsBanner = document.getElementById('autonomyPartialResultsBanner');
        const autonomyOpenPartialBriefBtn = document.getElementById('autonomyOpenPartialBriefBtn');
        const autonomyDecisionReadyBanner = document.getElementById('autonomyDecisionReadyBanner');
        const autonomyOpenBriefBtn = document.getElementById('autonomyOpenBriefBtn');
        const autonomyEvidenceRationale = document.getElementById('autonomyEvidenceRationale');
        const autonomyEvidenceReviewBtn = document.getElementById('autonomyEvidenceReviewBtn');
        const autonomyEvidenceReviewError = document.getElementById('autonomyEvidenceReviewError');
        const autonomyReturnInvestigationBtn = document.getElementById('autonomyReturnInvestigationBtn');
        const autonomyBriefPartialWarning = document.getElementById('autonomyBriefPartialWarning');
        const autonomyRecommendationTitle = document.getElementById('autonomyRecommendationTitle');
        const autonomyRecommendationConfidence = document.getElementById('autonomyRecommendationConfidence');
        const autonomyRecommendationCopy = document.getElementById('autonomyRecommendationCopy');
        const autonomyPrepareSignoffBtn = document.getElementById('autonomyPrepareSignoffBtn');
        const autonomySignoffDialog = document.getElementById('autonomySignoffDialog');
        const autonomySignoffOwner = document.getElementById('autonomySignoffOwner');
        const autonomySignoffRationale = document.getElementById('autonomySignoffRationale');
        const autonomySignoffAck = document.getElementById('autonomySignoffAck');
        const autonomySignoffError = document.getElementById('autonomySignoffError');
        const autonomySignoffCancelBtn = document.getElementById('autonomySignoffCancelBtn');
        const autonomySignoffSubmitBtn = document.getElementById('autonomySignoffSubmitBtn');
        const autonomyCreateRevisionBtn = document.getElementById('autonomyCreateRevisionBtn');
        const autonomySignedSummary = document.getElementById('autonomySignedSummary');
        const autonomySignedRationale = document.getElementById('autonomySignedRationale');
        const autonomyReturnLiveBtn = document.getElementById('autonomyReturnLiveBtn');
        const autonomyContentModeNotice = document.getElementById('autonomyContentModeNotice');
        const autonomyLiveToolbar = document.getElementById('autonomyLiveToolbar');
        const autonomyOperatorName = document.getElementById('autonomyOperatorName');
        const autonomyConnectionStatus = document.getElementById('autonomyConnectionStatus');
        const autonomyCaseSelect = document.getElementById('autonomyCaseSelect');
        const autonomyAgentThread = document.getElementById('autonomyAgentThread');
        const autonomyLiveMessageList = document.getElementById('autonomyLiveMessageList');
        const autonomyAgentComposerHelp = document.getElementById('autonomyAgentComposerHelp');
        const autonomyLiveReadinessChecklist = document.getElementById('autonomyLiveReadinessChecklist');
        const autonomyLiveReadinessDetails = document.getElementById('autonomyLiveReadinessDetails');
        const autonomyLiveEventTimeline = document.getElementById('autonomyLiveEventTimeline');
        const autonomyLiveProvenance = document.getElementById('autonomyLiveProvenance');
        const autonomyLiveEvidenceList = document.getElementById('autonomyLiveEvidenceList');
        const autonomyLiveEvidenceCandidates = document.getElementById('autonomyLiveEvidenceCandidates');
        const autonomySourceSelection = document.getElementById('autonomy-source-selection');
        const autonomySourceLockForm = document.getElementById('autonomySourceLockForm');
        const autonomyAnnualSourceSelect = document.getElementById('autonomyAnnualSourceSelect');
        const autonomyAnalysisBasisSelect = document.getElementById('autonomyAnalysisBasisSelect');
        const autonomySourceLockBtn = document.getElementById('autonomySourceLockBtn');
        const autonomySourceLockStatus = document.getElementById('autonomySourceLockStatus');
        const autonomyEvidenceUploadForm = document.getElementById('autonomyEvidenceUploadForm');
        const autonomyEvidenceClass = document.getElementById('autonomyEvidenceClass');
        const autonomyEvidenceFileInput = document.getElementById('autonomyEvidenceFileInput');
        const autonomyEvidenceUploadBtn = document.getElementById('autonomyEvidenceUploadBtn');
        const autonomyEvidenceUploadStatus = document.getElementById('autonomyEvidenceUploadStatus');

        let autonomyFixtureId = 'evidence-needed';
        let autonomySelectedStage = AUTONOMY_FIXTURE_CATALOG[autonomyFixtureId].stage;
        let autonomySelectedView = AUTONOMY_FIXTURE_CATALOG[autonomyFixtureId].defaultView;
        let autonomySelectedRailTab = 'evidence';
        let autonomyMobileSection = 'ask';
        let autonomyLastRailTrigger = null;
        let autonomyLastDialogTrigger = null;
        let autonomyInitialized = false;
        let autonomyContentMode = 'live';
        let autonomyCases = [];
        let autonomyLiveCase = null;
        let autonomyLiveReadiness = null;
        let autonomyLiveEvidence = [];
        let autonomyLiveMessages = [];
        let autonomyLiveEvents = [];
        let autonomyEligibleAnnualSources = [];
        let autonomySupportedAnalysisBases = [];
        let autonomyWorkspaceOpenPromise = null;
        let autonomyPendingTurn = null;
        let autonomyStreamAbortController = null;
        let autonomyStreamReconnectAttempts = 0;
        let autonomyLiveAgentAvailable = true;
        let autonomySignedDecision = {
            disposition: 'accept',
            owner: 'Jordan Lee',
            rationale: 'The reviewed evidence supports the conditional recommendation.',
        };

        function autonomySetConnectionStatus(message, state = 'ready') {
            if (!autonomyConnectionStatus) return;
            autonomyConnectionStatus.textContent = message;
            autonomyConnectionStatus.dataset.status = state;
        }

        function autonomySetContentMode(mode) {
            autonomyContentMode = mode === 'fixture' ? 'fixture' : 'live';
            if (autonomyPanel) autonomyPanel.dataset.contentMode = autonomyContentMode;
            if (autonomyContentModeNotice) autonomyContentModeNotice.hidden = autonomyContentMode !== 'fixture';
            if (autonomyReturnLiveBtn) autonomyReturnLiveBtn.hidden = autonomyContentMode !== 'fixture';
            if (autonomyLiveToolbar) autonomyLiveToolbar.hidden = autonomyContentMode !== 'live';
        }

        function autonomyOperator() {
            return autonomyOperatorName?.value.trim() || '';
        }

        function autonomySafeId(value, prefix) {
            const textValue = String(value || '');
            const prefixPattern = prefix ? prefix.replace(/[^a-z0-9_]/gi, '') : '';
            const pattern = prefixPattern
                ? new RegExp('^' + prefixPattern + '[A-Za-z0-9_-]+$')
                : /^[A-Za-z0-9_-]+$/;
            return pattern.test(textValue) ? textValue : '';
        }

        function autonomyCaseId(value = autonomyLiveCase?.case_id) {
            return autonomySafeId(value, 'case_');
        }

        function autonomyEvidenceId(value) {
            return autonomySafeId(value, 'evi_');
        }

        function autonomyTurnId(value) {
            return autonomySafeId(value, 'turn_') || autonomySafeId(value, 'dturn_');
        }

        function autonomyNode(tagName, options = {}) {
            const node = document.createElement(tagName);
            if (options.className) node.className = options.className;
            if (options.text !== undefined && options.text !== null) node.textContent = String(options.text);
            if (options.type) node.type = options.type;
            return node;
        }

        function autonomyFormatTimestamp(value) {
            if (!value) return 'Not recorded';
            const parsed = new Date(value);
            if (Number.isNaN(parsed.getTime())) return String(value);
            return parsed.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});
        }

        function autonomyBoundedSourcePart(value, limit = 160) {
            if (!['string', 'number', 'boolean'].includes(typeof value)) return '';
            return String(value).replace(/[\u0000-\u001f\u007f]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, limit);
        }

        function autonomyFormatSourceLocation(sourceLocation) {
            if (typeof sourceLocation === 'string') {
                return autonomyBoundedSourcePart(sourceLocation, 500) || 'Source location not reported';
            }
            if (!sourceLocation || typeof sourceLocation !== 'object' || Array.isArray(sourceLocation)) {
                return 'Source location not reported';
            }
            const kind = autonomyBoundedSourcePart(sourceLocation.kind, 48).toLowerCase();
            const part = (label, value, limit = 160) => {
                const safeValue = autonomyBoundedSourcePart(value, limit);
                return safeValue ? label + safeValue : '';
            };
            let pieces = [];
            if (kind === 'pdf_text') {
                pieces = ['PDF', part('page ', sourceLocation.page, 12), part('line ', sourceLocation.line, 12)];
            } else if (kind === 'xlsx_cell') {
                pieces = ['XLSX', part('sheet ', sourceLocation.sheet), part('cell ', sourceLocation.cell, 32)];
            } else if (kind === 'csv_cell') {
                pieces = ['CSV', part('row ', sourceLocation.row, 12), part('column ', sourceLocation.column, 12)];
            } else if (kind === 'document_metadata') {
                const format = autonomyBoundedSourcePart(sourceLocation.format, 24).toUpperCase() || 'File';
                pieces = [format];
                if (sourceLocation.page_count !== undefined) pieces.push(part('pages ', sourceLocation.page_count, 12));
                if (sourceLocation.sheet_count !== undefined) pieces.push(part('sheets ', sourceLocation.sheet_count, 12));
                if (sourceLocation.row_count !== undefined) pieces.push(part('rows ', sourceLocation.row_count, 12));
                if (sourceLocation.column_count !== undefined) pieces.push(part('columns ', sourceLocation.column_count, 12));
                if (sourceLocation.width !== undefined && sourceLocation.height !== undefined) {
                    const width = autonomyBoundedSourcePart(sourceLocation.width, 12);
                    const height = autonomyBoundedSourcePart(sourceLocation.height, 12);
                    if (width && height) pieces.push(width + ' × ' + height + ' pixels');
                }
            } else if (['file', 'file_level', 'server_managed_content'].includes(kind)) {
                pieces = ['File-level source'];
            } else if (sourceLocation.sheet !== undefined || sourceLocation.cell !== undefined) {
                pieces = [part('Sheet ', sourceLocation.sheet), part('cell ', sourceLocation.cell, 32)];
            } else if (sourceLocation.row !== undefined || sourceLocation.column !== undefined) {
                pieces = [part('Row ', sourceLocation.row, 12), part('column ', sourceLocation.column, 12)];
            } else if (sourceLocation.page !== undefined || sourceLocation.line !== undefined) {
                pieces = [part('Page ', sourceLocation.page, 12), part('line ', sourceLocation.line, 12)];
            }
            return pieces.filter(Boolean).join(' · ').slice(0, 500) || 'Source location not reported';
        }

        async function autonomyReadResponse(response, fallbackMessage) {
            let data = {};
            try {
                data = await response.json();
            } catch (_) {
                // Status-based copy is safer than exposing an upstream response body.
            }
            if (!response.ok) {
                const detail = data.detail;
                const message = Array.isArray(detail)
                    ? detail[0]?.msg
                    : (detail && typeof detail === 'object'
                        ? detail.message || detail.detail
                        : detail);
                const error = new Error(message || fallbackMessage || ('Request failed (' + response.status + ')'));
                error.status = response.status;
                error.code = data.code || (detail && typeof detail === 'object' ? detail.code : '') || '';
                throw error;
            }
            return data;
        }

        async function autonomyJsonRequest(path, options = {}) {
            const request = {...options};
            request.headers = {
                Accept: 'application/json',
                ...(options.body === undefined ? {} : {'Content-Type': 'application/json'}),
                ...(options.headers || {}),
            };
            if (options.body !== undefined && typeof options.body !== 'string') {
                request.body = JSON.stringify(options.body);
            }
            const response = await fetch(path, request);
            return autonomyReadResponse(response, 'The durable Autonomy request could not be completed.');
        }

        function autonomyClientMessageId() {
            if (window.crypto?.randomUUID) return 'client_' + window.crypto.randomUUID().replace(/-/g, '');
            const random = Math.random().toString(36).slice(2);
            return 'client_' + Date.now().toString(36) + random;
        }

        function autonomyNormalizeReadinessStatus(value) {
            const status = String(value || '').toLowerCase().replace(/\s+/g, '_').replace(/-/g, '_');
            if (status === 'passed' || status === 'available') return 'passed';
            if (status === 'needs_attention' || status === 'unavailable') return 'needs-attention';
            if (status === 'blocked') return 'blocked';
            if (status === 'stale') return 'stale';
            return 'not-started';
        }

        function autonomyReadinessStatusLabel(value) {
            return {
                passed: 'Passed',
                'needs-attention': 'Needs attention',
                blocked: 'Blocked',
                stale: 'Stale',
                'not-started': 'Not checked',
            }[value] || 'Not checked';
        }

        function autonomyAllowedAction(action) {
            const id = typeof action === 'string' ? action : action?.id;
            if (!id || action?.enabled === false || !Object.prototype.hasOwnProperty.call(AUTONOMY_SUPPORTED_ACTIONS, id)) return null;
            return {
                id,
                label: typeof action === 'object' && action?.label ? String(action.label) : id.replace(/_/g, ' '),
                deepLink: typeof action === 'object' && action?.deep_link ? String(action.deep_link) : AUTONOMY_SUPPORTED_ACTIONS[id],
            };
        }

        function autonomyPopulateCaseOptions() {
            if (!autonomyCaseSelect) return;
            autonomyCaseSelect.replaceChildren();
            autonomyCases.forEach((caseRecord) => {
                const caseId = autonomyCaseId(caseRecord?.case_id);
                if (!caseId) return;
                const option = autonomyNode('option', {
                    text: caseId + ' · ' + String(caseRecord.title || 'Untitled decision'),
                });
                option.value = caseId;
                option.selected = caseId === autonomyCaseId();
                autonomyCaseSelect.appendChild(option);
            });
            autonomyCaseSelect.disabled = autonomyCases.length === 0;
        }

        function autonomyLiveDefaultStage() {
            if (!autonomyLiveCase) return 'ask';
            const overall = autonomyNormalizeReadinessStatus(autonomyLiveReadiness?.overall_status);
            if (['blocked', 'needs-attention', 'stale'].includes(overall)) return 'verify';
            return 'ask';
        }

        function autonomyCaseSourceLock(caseRecord = autonomyLiveCase) {
            if (caseRecord?.source_lock && typeof caseRecord.source_lock === 'object') return caseRecord.source_lock;
            if (caseRecord?.basis_lock && typeof caseRecord.basis_lock === 'object') return caseRecord.basis_lock;
            return null;
        }

        function autonomyAvailableAnnualSources() {
            const readinessSources = Array.isArray(autonomyLiveReadiness?.eligible_annual_sources)
                ? autonomyLiveReadiness.eligible_annual_sources
                : [];
            const sourceRecords = autonomyEligibleAnnualSources.length ? autonomyEligibleAnnualSources : readinessSources;
            return sourceRecords.filter((source) => (
                autonomySafeId(source?.annual_job_id)
                && /^[a-f0-9]{64}$/i.test(String(source?.source_snapshot_sha256 || ''))
            ));
        }

        function autonomyAnalysisBasisLabel(value) {
            return {
                solartac_site: 'SolarTAC site basis',
                commercial_representative: 'Commercial representative basis',
            }[String(value || '')] || String(value || '').replace(/_/g, ' ');
        }

        function autonomyNormalizeAnalysisBases(records) {
            const seen = new Set();
            return (Array.isArray(records) ? records : []).reduce((items, record) => {
                const basisId = typeof record === 'string' ? record : record?.id;
                if (!['solartac_site', 'commercial_representative'].includes(basisId) || seen.has(basisId)) return items;
                seen.add(basisId);
                items.push({
                    id: basisId,
                    label: autonomyBoundedSourcePart(typeof record === 'object' ? record?.label : '', 120)
                        || autonomyAnalysisBasisLabel(basisId),
                });
                return items;
            }, []);
        }

        function autonomyUpdateSourceLockButton() {
            const sourceLock = autonomyCaseSourceLock();
            const locked = Boolean(sourceLock?.annual_job_id || sourceLock?.source_annual_job_id);
            const completeChoice = Boolean(autonomyAnnualSourceSelect?.value && autonomyAnalysisBasisSelect?.value);
            if (autonomySourceLockBtn) autonomySourceLockBtn.disabled = locked || !completeChoice;
        }

        function autonomyRenderSourceSelection() {
            if (!autonomySourceSelection || autonomyContentMode !== 'live') return;
            const sourceLock = autonomyCaseSourceLock();
            const lockedSourceId = String(sourceLock?.annual_job_id || sourceLock?.source_annual_job_id || '');
            const lockedBasis = String(sourceLock?.analysis_basis || '');
            const locked = Boolean(lockedSourceId && sourceLock?.source_snapshot_sha256 && lockedBasis);
            const priorSource = autonomyAnnualSourceSelect?.value || '';
            const priorBasis = autonomyAnalysisBasisSelect?.value || '';
            const sources = autonomyAvailableAnnualSources();
            const basisRecords = autonomySupportedAnalysisBases.length
                ? autonomySupportedAnalysisBases
                : (Array.isArray(autonomyLiveReadiness?.supported_analysis_bases)
                    ? autonomyLiveReadiness.supported_analysis_bases
                    : []);
            const bases = autonomyNormalizeAnalysisBases(basisRecords);
            autonomySourceSelection.dataset.locked = String(locked);

            if (autonomyAnnualSourceSelect) {
                autonomyAnnualSourceSelect.replaceChildren();
                const placeholder = autonomyNode('option', {text: 'Select an eligible Annual source'});
                placeholder.value = '';
                autonomyAnnualSourceSelect.appendChild(placeholder);
                sources.forEach((source) => {
                    const sourceId = autonomySafeId(source.annual_job_id);
                    if (!sourceId) return;
                    const completed = source.completed_at ? autonomyFormatTimestamp(source.completed_at) : 'completion recorded';
                    const yearCount = Array.isArray(source.eligible_years) ? source.eligible_years.length : 0;
                    const option = autonomyNode('option', {
                        text: sourceId + ' · ' + completed + (yearCount ? ' · ' + yearCount + ' eligible years' : '')
                            + ' · SHA ' + String(source.source_snapshot_sha256).slice(0, 12),
                    });
                    option.value = sourceId;
                    autonomyAnnualSourceSelect.appendChild(option);
                });
                if (lockedSourceId && !sources.some((source) => source.annual_job_id === lockedSourceId)) {
                    const lockedOption = autonomyNode('option', {text: lockedSourceId + ' · locked source'});
                    lockedOption.value = lockedSourceId;
                    autonomyAnnualSourceSelect.appendChild(lockedOption);
                }
                autonomyAnnualSourceSelect.value = lockedSourceId || (sources.some((source) => source.annual_job_id === priorSource) ? priorSource : '');
                autonomyAnnualSourceSelect.disabled = locked || sources.length === 0;
            }

            if (autonomyAnalysisBasisSelect) {
                autonomyAnalysisBasisSelect.replaceChildren();
                const placeholder = autonomyNode('option', {text: 'Select an approved analysis basis'});
                placeholder.value = '';
                autonomyAnalysisBasisSelect.appendChild(placeholder);
                bases.forEach((basis) => {
                    const basisId = basis.id;
                    const option = autonomyNode('option', {text: basis.label});
                    option.value = basisId;
                    autonomyAnalysisBasisSelect.appendChild(option);
                });
                autonomyAnalysisBasisSelect.value = lockedBasis || (bases.some((basis) => basis.id === priorBasis) ? priorBasis : '');
                autonomyAnalysisBasisSelect.disabled = locked || bases.length === 0;
            }

            if (autonomySourceLockBtn) autonomySourceLockBtn.textContent = locked
                ? 'Source and analysis basis locked'
                : 'Lock source and analysis basis';
            if (autonomySourceLockStatus) {
                autonomySourceLockStatus.textContent = locked
                    ? 'Locked by ' + String(sourceLock.locked_by || autonomyLiveCase?.updated_by || 'named operator')
                        + '. This immutable source and basis cannot be changed.'
                    : (sources.length
                        ? 'Select both values, then confirm the immutable lock using the named operator above.'
                        : 'No eligible completed Annual source is currently available. Open Annual Simulation from readiness to create one.');
            }
            autonomyUpdateSourceLockButton();
        }

        function autonomyRenderLiveCase() {
            if (!autonomyPanel || autonomyContentMode !== 'live') return;
            const caseRecord = autonomyLiveCase;
            const caseExists = !!autonomyCaseId(caseRecord?.case_id);
            autonomyPanel.dataset.autonomyCaseId = caseExists ? caseRecord.case_id : '';
            autonomyPanel.dataset.autonomyCaseRevision = caseExists ? String(caseRecord.revision ?? '') : '';
            autonomyPanel.dataset.caseState = caseExists ? String(caseRecord.status || 'draft') : 'empty';
            if (autonomyCaseEmpty) autonomyCaseEmpty.hidden = caseExists;
            if (autonomyCaseContent) autonomyCaseContent.hidden = !caseExists;
            autonomyPanel.querySelectorAll('[data-autonomy-case-workspace]').forEach((element) => {
                element.hidden = !caseExists;
            });
            autonomyPopulateCaseOptions();
            if (!caseExists) {
                autonomySetConnectionStatus('No durable decision cases yet.', 'empty');
                autonomySelectedStage = 'ask';
                autonomySelectedView = 'investigation';
                return;
            }

            const allowedActions = (Array.isArray(autonomyLiveReadiness?.allowed_case_actions)
                ? autonomyLiveReadiness.allowed_case_actions
                : [])
                .filter((action) => typeof action === 'string' || action?.enabled !== false)
                .map((action) => typeof action === 'string' ? action : action?.id)
                .filter(Boolean);
            const editable = ['update_case', 'edit_case', 'rename_case'].some((action) => allowedActions.includes(action));
            if (autonomyCaseTitle) {
                autonomyCaseTitle.value = String(caseRecord.title || '');
                autonomyCaseTitle.disabled = !editable;
            }
            if (autonomyQuestion) {
                autonomyQuestion.value = String(caseRecord.question || '');
                autonomyQuestion.disabled = !editable;
            }
            if (autonomyCaseStatus) {
                autonomyCaseStatus.textContent = String(caseRecord.status || 'draft').replace(/_/g, ' ');
                autonomyCaseStatus.dataset.status = String(caseRecord.status || 'draft');
            }
            if (autonomyDecisionOwner) autonomyDecisionOwner.textContent = String(caseRecord.owner || 'Decision owner pending');
            const sourceLock = caseRecord.source_lock && typeof caseRecord.source_lock === 'object'
                ? caseRecord.source_lock
                : (caseRecord.basis_lock && typeof caseRecord.basis_lock === 'object' ? caseRecord.basis_lock : null);
            const sourceLocked = Boolean(sourceLock?.locked || (
                (sourceLock?.annual_job_id || sourceLock?.source_annual_job_id)
                && sourceLock?.source_snapshot_sha256
                && sourceLock?.analysis_basis
            ));
            if (autonomySourceLock) {
                autonomySourceLock.textContent = sourceLocked
                    ? String(sourceLock.annual_job_id || sourceLock.source_annual_job_id || 'Annual source')
                        + ' · SHA ' + String(sourceLock.source_snapshot_sha256 || 'not recorded').slice(0, 12)
                    : 'Not locked';
            }
            if (autonomyBasisLock) autonomyBasisLock.textContent = sourceLocked && sourceLock?.analysis_basis
                ? String(sourceLock.analysis_basis)
                : 'Not locked';
            if (autonomyCaseRevision) autonomyCaseRevision.textContent = 'Revision ' + String(caseRecord.revision ?? 'not recorded');
            if (autonomyUpdatedAt) autonomyUpdatedAt.textContent = autonomyFormatTimestamp(caseRecord.updated_at);
            autonomySelectedStage = AUTONOMY_LIVE_STAGES.includes(autonomySelectedStage)
                ? autonomySelectedStage
                : autonomyLiveDefaultStage();
            const liveStageState = autonomyNormalizeReadinessStatus(autonomyLiveReadiness?.overall_status);
            autonomyRenderStepper({
                stage: autonomyLiveDefaultStage(),
                stageState: liveStageState === 'passed' ? 'current' : liveStageState,
                signed: false,
            });
            autonomySetView('investigation');
        }

        function autonomyReadinessChecks() {
            return Array.isArray(autonomyLiveReadiness?.checks) ? autonomyLiveReadiness.checks.filter(Boolean) : [];
        }

        function autonomyReadinessKey(check) {
            return {
                annual_source: 'annual',
                weather_coverage: 'weather',
            }[String(check?.key || check?.id || '')] || String(check?.key || check?.id || '');
        }

        function autonomyRenderLiveReadiness() {
            if (autonomyContentMode !== 'live') return;
            const checks = autonomyReadinessChecks();
            const byKey = new Map(checks.map((check) => [autonomyReadinessKey(check), check]));
            AUTONOMY_READINESS_KEYS.forEach((key) => {
                const item = autonomyPanel?.querySelector('[data-autonomy-readiness="' + key + '"]');
                if (!item) return;
                const check = byKey.get(key);
                const statusValue = autonomyNormalizeReadinessStatus(check?.status);
                item.dataset.status = statusValue;
                item.dataset.state = statusValue;
                const status = item.querySelector('[data-autonomy-readiness-status]');
                if (status) status.textContent = check?.status
                    ? autonomyReadinessStatusLabel(statusValue)
                    : 'Not checked';
            });

            if (autonomyLiveReadinessChecklist) autonomyLiveReadinessChecklist.replaceChildren();
            if (autonomyLiveReadinessDetails) autonomyLiveReadinessDetails.replaceChildren();
            checks.forEach((check) => {
                const statusValue = autonomyNormalizeReadinessStatus(check.status);
                const article = autonomyNode('article');
                article.setAttribute('role', 'listitem');
                article.dataset.status = statusValue;
                article.appendChild(autonomyNode('span', {text: autonomyReadinessStatusLabel(statusValue)}));
                const copy = autonomyNode('div');
                copy.appendChild(autonomyNode('h4', {text: check.label || check.key || 'Readiness check'}));
                copy.appendChild(autonomyNode('p', {text: check.summary || 'No summary was provided.'}));
                if (check.rule_id || check.exact_rule) copy.appendChild(autonomyNode('small', {
                    text: 'Exact rule: ' + [check.rule_id, check.exact_rule].filter(Boolean).join(' · '),
                }));
                const firstBlocker = check.blocker || (Array.isArray(check.blockers) ? check.blockers[0] : null);
                if (firstBlocker) {
                    const blockerText = typeof firstBlocker === 'string'
                        ? firstBlocker
                        : firstBlocker.message || firstBlocker.detail || firstBlocker.reason || firstBlocker.code || '';
                    if (blockerText) copy.appendChild(autonomyNode('small', {text: 'Blocker: ' + blockerText}));
                }
                article.appendChild(copy);
                autonomyLiveReadinessChecklist?.appendChild(article);

                const detail = autonomyNode('li');
                detail.appendChild(autonomyNode('strong', {text: check.label || check.key || 'Readiness check'}));
                const detailCopy = [autonomyReadinessStatusLabel(statusValue), check.summary, check.rule_id ? 'Rule ' + check.rule_id : '']
                    .filter(Boolean).join(' · ');
                detail.appendChild(autonomyNode('span', {text: detailCopy}));
                autonomyLiveReadinessDetails?.appendChild(detail);
            });

            const candidateActions = [];
            checks.forEach((check) => {
                const allowed = autonomyAllowedAction(check.primary_action);
                if (allowed) candidateActions.push(allowed);
                (Array.isArray(check.supported_actions) ? check.supported_actions : []).forEach((action) => {
                    const supported = autonomyAllowedAction(action);
                    if (supported) candidateActions.push(supported);
                });
                (Array.isArray(check.blockers) ? check.blockers : []).forEach((blocker) => {
                    const supported = autonomyAllowedAction(blocker?.closest_supported_action);
                    if (supported) candidateActions.push(supported);
                });
            });
            (Array.isArray(autonomyLiveReadiness?.supported_next_actions)
                ? autonomyLiveReadiness.supported_next_actions
                : []).forEach((action) => {
                const allowed = autonomyAllowedAction(action);
                if (allowed) candidateActions.push(allowed);
            });
            const primaryAction = candidateActions[0] || null;
            const firstIssue = checks.find((check) => autonomyNormalizeReadinessStatus(check.status) !== 'passed');
            const overall = autonomyNormalizeReadinessStatus(autonomyLiveReadiness?.overall_status);
            if (autonomyStateBanner) autonomyStateBanner.dataset.tone = overall === 'blocked'
                ? 'danger'
                : (['needs-attention', 'stale'].includes(overall) ? 'warning' : 'success');
            if (autonomyStateBannerTitle) autonomyStateBannerTitle.textContent = firstIssue?.label
                || (checks.length ? 'Readiness evaluated' : 'Readiness has not been evaluated');
            if (autonomyStateBannerText) autonomyStateBannerText.textContent = firstIssue?.summary
                || (checks.length
                    ? 'Ask and evidence review are available. Later-stage execution remains fixture-only.'
                    : 'Open or refresh this case to evaluate deterministic prerequisites.');
            if (autonomyStateAction) {
                autonomyStateAction.hidden = !primaryAction;
                autonomyStateAction.dataset.autonomyAction = primaryAction?.id || '';
                autonomyStateAction.dataset.autonomyDeepLink = primaryAction?.deepLink || '';
                autonomyStateAction.textContent = primaryAction?.label || '';
            }
            const agentCheck = byKey.get('agent');
            autonomyLiveAgentAvailable = autonomyNormalizeReadinessStatus(agentCheck?.status) === 'passed';
            if (autonomyAgentStatus) {
                autonomyAgentStatus.textContent = autonomyLiveAgentAvailable ? 'Available' : 'Unavailable · manual review remains usable';
                autonomyAgentStatus.dataset.status = autonomyLiveAgentAvailable ? 'available' : 'unavailable';
            }
            if (autonomyAgentComposer) autonomyAgentComposer.disabled = !autonomyLiveAgentAvailable || !autonomyLiveCase;
            if (autonomyAgentSendBtn) autonomyAgentSendBtn.disabled = !autonomyLiveAgentAvailable || !autonomyLiveCase;
        }

        function autonomyMessageContent(message) {
            const structured = message?.structured_output && typeof message.structured_output === 'object'
                ? message.structured_output
                : message?.output && typeof message.output === 'object' ? message.output : {};
            const whyNot = structured.why_not_details && typeof structured.why_not_details === 'object'
                ? structured.why_not_details
                : null;
            const nextActions = structured.next_actions || structured.next_action || message?.next_actions || message?.next_action || '';
            return {
                answer: structured.answer || message?.content || message?.message || '',
                basis: structured.basis || structured.basis_labels || message?.basis || '',
                blockers: structured.exact_blockers || whyNot?.blocking_rules || [],
                rules: structured.exact_rules || [],
                limits: structured.limits || message?.limits || '',
                missingEvidence: whyNot?.missing_evidence || [],
                protectiveReason: whyNot?.protective_reason || '',
                closestAlternative: whyNot?.closest_supported_alternative || '',
                nextAction: nextActions || whyNot?.next_action || '',
                citations: Array.isArray(structured.citations)
                    ? structured.citations
                    : (Array.isArray(message?.citations) ? message.citations : []),
                suggestion: structured.non_runnable_scenario_suggestion || structured.suggestion || message?.suggestion || null,
            };
        }

        function autonomyAppendMessageSection(container, label, value) {
            if (value === null || value === undefined || value === '') return;
            const section = autonomyNode('div');
            section.appendChild(autonomyNode('p', {className: 'autonomy-message-label', text: label}));
            let displayValue = value;
            if (Array.isArray(value)) {
                displayValue = value.map((item) => (
                    typeof item === 'string' ? item : item?.label || item?.text || item?.basis || ''
                )).filter(Boolean).join(' · ');
            } else if (typeof value === 'object') {
                displayValue = value.label || value.text || value.basis || '';
            }
            section.appendChild(autonomyNode('p', {text: displayValue}));
            container.appendChild(section);
        }

        function autonomyRenderLiveMessages() {
            if (!autonomyLiveMessageList) return;
            autonomyLiveMessageList.replaceChildren();
            if (!autonomyLiveMessages.length) {
                const empty = autonomyNode('article', {className: 'autonomy-agent-message'});
                autonomyAppendMessageSection(empty, 'Answer', 'Ask a definition, current-state, root-cause, what, why, or why-not question.');
                autonomyAppendMessageSection(empty, 'Limits', 'The Decision Agent cannot execute scenarios, queue TEA work, accept evidence, waive gates, or sign a decision.');
                autonomyLiveMessageList.appendChild(empty);
                return;
            }
            autonomyLiveMessages.forEach((message) => {
                const role = String(message?.role || 'assistant').toLowerCase();
                if (role === 'user') {
                    const article = autonomyNode('article', {className: 'autonomy-user-message'});
                    article.appendChild(autonomyNode('p', {className: 'autonomy-message-author', text: 'You'}));
                    article.appendChild(autonomyNode('p', {text: message.content || message.message || ''}));
                    if (message.created_at) article.appendChild(autonomyNode('small', {
                        className: 'autonomy-message-meta', text: autonomyFormatTimestamp(message.created_at),
                    }));
                    autonomyLiveMessageList.appendChild(article);
                    return;
                }

                const content = autonomyMessageContent(message);
                const article = autonomyNode('article', {className: 'autonomy-agent-message'});
                autonomyAppendMessageSection(article, 'Answer', content.answer);
                autonomyAppendMessageSection(article, 'Basis labels', content.basis);
                autonomyAppendMessageSection(article, 'Exact blockers', content.blockers);
                autonomyAppendMessageSection(article, 'Exact rules', content.rules);
                autonomyAppendMessageSection(article, 'Limits', content.limits);
                autonomyAppendMessageSection(article, 'Missing evidence', content.missingEvidence);
                autonomyAppendMessageSection(article, 'Protective reason', content.protectiveReason);
                autonomyAppendMessageSection(article, 'Closest supported alternative', content.closestAlternative);
                autonomyAppendMessageSection(article, 'Next actions', content.nextAction);
                if (content.citations.length) {
                    const chips = autonomyNode('div', {className: 'autonomy-source-chips'});
                    chips.setAttribute('aria-label', 'Supporting sources');
                    content.citations.forEach((citation) => {
                        const button = autonomyNode('button', {
                            type: 'button',
                            text: citation?.label || citation?.title || citation?.source_location || 'Supporting source',
                        });
                        button.dataset.autonomyLiveCitation = String(citation?.evidence_id || citation?.source_id || '');
                        chips.appendChild(button);
                    });
                    article.appendChild(chips);
                }
                if (content.suggestion && content.suggestion.runnable === false) {
                    const suggestion = autonomyNode('aside', {className: 'autonomy-agent-suggestion'});
                    suggestion.appendChild(autonomyNode('strong', {text: 'Non-runnable explanatory suggestion'}));
                    suggestion.appendChild(autonomyNode('p', {
                        text: content.suggestion.text || content.suggestion.summary || content.suggestion.rationale || '',
                    }));
                    article.appendChild(suggestion);
                }
                const meta = [message.trace_id ? 'Trace ' + message.trace_id : '', autonomyFormatTimestamp(message.created_at)]
                    .filter(Boolean).join(' · ');
                if (meta) article.appendChild(autonomyNode('small', {className: 'autonomy-message-meta', text: meta}));
                autonomyLiveMessageList.appendChild(article);
            });
        }

        function autonomyRenderLiveEvents() {
            if (autonomyLiveEventTimeline) autonomyLiveEventTimeline.replaceChildren();
            autonomyLiveEvents.forEach((eventRecord) => {
                const item = autonomyNode('li');
                const label = eventRecord.summary || eventRecord.label || eventRecord.payload?.summary
                    || eventRecord.event_type || eventRecord.type || 'Case event';
                item.appendChild(autonomyNode('strong', {text: label}));
                const actor = eventRecord.operator_name || eventRecord.actor || eventRecord.created_by || '';
                const details = [autonomyFormatTimestamp(eventRecord.occurred_at || eventRecord.created_at), actor].filter(Boolean).join(' · ');
                if (details) item.appendChild(autonomyNode('span', {text: details}));
                autonomyLiveEventTimeline?.appendChild(item);
            });
            if (autonomyLiveEventTimeline && !autonomyLiveEvents.length) {
                const empty = autonomyNode('li');
                empty.appendChild(autonomyNode('strong', {text: 'No case events recorded yet'}));
                autonomyLiveEventTimeline.appendChild(empty);
            }
        }

        function autonomyAppendProvenance(label, value) {
            if (!autonomyLiveProvenance) return;
            const row = autonomyNode('div');
            row.appendChild(autonomyNode('dt', {text: label}));
            row.appendChild(autonomyNode('dd', {text: value || 'Not recorded'}));
            autonomyLiveProvenance.appendChild(row);
        }

        function autonomyRenderLiveProvenance() {
            if (!autonomyLiveProvenance) return;
            autonomyLiveProvenance.replaceChildren();
            const caseRecord = autonomyLiveCase;
            const sourceLock = caseRecord?.source_lock || caseRecord?.basis_lock || null;
            autonomyAppendProvenance('Case ID', caseRecord?.case_id);
            autonomyAppendProvenance('Revision', caseRecord?.revision === undefined ? '' : String(caseRecord.revision));
            autonomyAppendProvenance('Created by', caseRecord?.created_by);
            autonomyAppendProvenance('Updated by', caseRecord?.updated_by);
            autonomyAppendProvenance('Annual source', sourceLock?.annual_job_id || sourceLock?.source_annual_job_id);
            autonomyAppendProvenance('Source SHA-256', sourceLock?.source_snapshot_sha256);
            autonomyAppendProvenance('Analysis basis', sourceLock?.analysis_basis);
            autonomyAppendProvenance('Readiness schema', autonomyLiveReadiness?.schema_version);
            autonomyAppendProvenance('Evaluated', autonomyFormatTimestamp(autonomyLiveReadiness?.evaluated_at));
        }

        function autonomyEvidenceStatusLabel(value) {
            return String(value || 'pending_review').replace(/_/g, ' ');
        }

        function autonomyEvidenceDownloadPath(evidenceId) {
            const caseId = autonomyCaseId();
            const safeEvidenceId = autonomyEvidenceId(evidenceId);
            if (!caseId || !safeEvidenceId) return '';
            return '/api/autonomy/cases/' + encodeURIComponent(caseId)
                + '/evidence/' + encodeURIComponent(safeEvidenceId) + '/download';
        }

        function autonomyAppendEvidenceDetail(list, label, value) {
            if (value === undefined || value === null || value === '') return;
            const row = autonomyNode('div');
            row.appendChild(autonomyNode('dt', {text: label}));
            row.appendChild(autonomyNode('dd', {text: value}));
            list.appendChild(row);
        }

        function autonomyCreateCandidateReview(evidence, candidate) {
            const evidenceId = autonomyEvidenceId(evidence?.evidence_id);
            const candidateId = autonomySafeId(candidate?.candidate_id, 'cand_')
                || autonomySafeId(candidate?.candidate_id, 'evc_');
            if (!evidenceId || !candidateId) return null;
            const section = autonomyNode('section', {className: 'autonomy-evidence-candidate'});
            section.dataset.evidenceId = evidenceId;
            section.dataset.candidateId = candidateId;
            section.appendChild(autonomyNode('p', {className: 'autonomy-eyebrow', text: 'Extracted candidate · untrusted document data'}));
            section.appendChild(autonomyNode('h4', {text: candidate.field || 'Candidate value'}));
            const value = [candidate.value, candidate.unit].filter((item) => item !== undefined && item !== null && item !== '').join(' ');
            section.appendChild(autonomyNode('p', {text: value || 'No value extracted'}));
            section.appendChild(autonomyNode('p', {
                className: 'autonomy-candidate-meta',
                text: ['Confidence ' + String(candidate.confidence ?? 'not reported'), autonomyFormatSourceLocation(candidate.source_location)]
                    .join(' · '),
            }));
            const state = autonomyEvidenceStatusLabel(candidate.review_state);
            section.appendChild(autonomyNode('p', {text: 'Review state: ' + state}));
            if (['accepted', 'rejected'].includes(String(candidate.review_state || '').toLowerCase())) return section;

            const fieldset = autonomyNode('fieldset');
            fieldset.appendChild(autonomyNode('legend', {text: 'Human review decision'}));
            const groupName = 'autonomyLiveCandidate_' + candidateId;
            ['accepted', 'rejected'].forEach((decision) => {
                const label = autonomyNode('label');
                const input = autonomyNode('input');
                input.type = 'radio';
                input.name = groupName;
                input.value = decision;
                label.append(input, document.createTextNode(decision === 'accepted' ? ' Accept candidate' : ' Reject candidate'));
                fieldset.appendChild(label);
            });
            section.appendChild(fieldset);
            const rationaleLabel = autonomyNode('label', {className: 'autonomy-field'});
            rationaleLabel.appendChild(autonomyNode('span', {text: 'Named rationale for provisional evidence'}));
            const rationale = autonomyNode('textarea');
            rationale.rows = 2;
            rationale.dataset.autonomyCandidateRationale = 'true';
            rationaleLabel.appendChild(rationale);
            section.appendChild(rationaleLabel);
            const submit = autonomyNode('button', {className: 'autonomy-button autonomy-button-primary', type: 'button', text: 'Record evidence decision'});
            submit.dataset.autonomyCandidateReview = 'true';
            section.appendChild(submit);
            const error = autonomyNode('p', {className: 'autonomy-dialog-error'});
            error.setAttribute('role', 'alert');
            error.hidden = true;
            error.dataset.autonomyCandidateError = 'true';
            section.appendChild(error);
            return section;
        }

        function autonomyRenderLiveEvidence() {
            if (autonomyLiveEvidenceList) autonomyLiveEvidenceList.replaceChildren();
            if (autonomyLiveEvidenceCandidates) autonomyLiveEvidenceCandidates.replaceChildren();
            if (!autonomyLiveEvidence.length) {
                autonomyLiveEvidenceList?.appendChild(autonomyNode('p', {text: 'No uploaded evidence is attached to this case.'}));
                autonomyLiveEvidenceCandidates?.appendChild(autonomyNode('p', {text: 'Upload evidence to review extracted candidate values.'}));
                return;
            }
            autonomyLiveEvidence.forEach((evidence) => {
                const evidenceId = autonomyEvidenceId(evidence?.evidence_id);
                if (!evidenceId) return;
                const article = autonomyNode('article', {className: 'autonomy-evidence-record'});
                const evidenceStatus = evidence.status || evidence.review_state || 'pending_review';
                article.dataset.status = String(evidenceStatus).replace(/_/g, '-');
                const heading = autonomyNode('div');
                heading.appendChild(autonomyNode('span', {text: autonomyEvidenceStatusLabel(evidence.evidence_class)}));
                heading.appendChild(autonomyNode('strong', {text: autonomyEvidenceStatusLabel(evidenceStatus)}));
                article.appendChild(heading);
                article.appendChild(autonomyNode('h4', {text: evidence.display_filename || evidence.filename || evidenceId}));
                const details = autonomyNode('dl');
                autonomyAppendEvidenceDetail(details, 'Media type', evidence.media_type);
                const byteCount = evidence.bytes ?? evidence.byte_count;
                autonomyAppendEvidenceDetail(details, 'Bytes', byteCount === undefined ? '' : Number(byteCount).toLocaleString());
                autonomyAppendEvidenceDetail(details, 'SHA-256', evidence.sha256 || evidence.content_sha256);
                autonomyAppendEvidenceDetail(details, 'Mode', evidence.preservation_mode);
                const receipt = evidence.receipt && typeof evidence.receipt === 'object' ? evidence.receipt : null;
                autonomyAppendEvidenceDetail(details, 'Receipt', receipt?.receipt_id || receipt?.sha256 || receipt?.receipt_sha256 || 'Pending');
                article.appendChild(details);
                const actions = autonomyNode('div', {className: 'autonomy-evidence-actions'});
                const downloadPath = autonomyEvidenceDownloadPath(evidenceId);
                if (downloadPath && evidence.preservation_mode === 'server_managed_content_v1') {
                    const download = autonomyNode('a', {text: 'Verified download'});
                    download.href = downloadPath;
                    download.dataset.autonomyEvidenceDownload = evidenceId;
                    actions.appendChild(download);
                }
                const remove = autonomyNode('button', {className: 'autonomy-button autonomy-button-secondary', type: 'button', text: 'Remove unreferenced evidence'});
                remove.dataset.autonomyEvidenceDelete = evidenceId;
                actions.appendChild(remove);
                article.appendChild(actions);
                autonomyLiveEvidenceList?.appendChild(article);

                (Array.isArray(evidence.candidates) ? evidence.candidates : []).forEach((candidate) => {
                    const candidateReview = autonomyCreateCandidateReview(evidence, candidate);
                    if (candidateReview) autonomyLiveEvidenceCandidates?.appendChild(candidateReview);
                });
            });
            if (autonomyLiveEvidenceCandidates && !autonomyLiveEvidenceCandidates.children.length) {
                autonomyLiveEvidenceCandidates.appendChild(autonomyNode('p', {text: 'No reviewable candidate values were extracted.'}));
            }
        }

        async function autonomyUploadEvidence(event) {
            event?.preventDefault();
            if (autonomyContentMode !== 'live' || !autonomyCaseId()) return;
            const operatorName = autonomyOperator();
            const files = Array.from(autonomyEvidenceFileInput?.files || []);
            if (!operatorName) {
                autonomyEvidenceUploadStatus.textContent = 'Enter a named operator before uploading evidence.';
                autonomyOperatorName?.focus();
                return;
            }
            if (!files.length) {
                autonomyEvidenceUploadStatus.textContent = 'Choose at least one supported file.';
                autonomyEvidenceFileInput?.focus();
                return;
            }
            const invalid = files.find((file) => file.size > AUTONOMY_MAX_UPLOAD_BYTES
                || (file.type && !AUTONOMY_ALLOWED_EVIDENCE_TYPES.includes(file.type)));
            if (invalid) {
                autonomyEvidenceUploadStatus.textContent = 'The selected file exceeds 10 MB or has an unsupported browser-reported media type.';
                return;
            }
            const existingBytes = autonomyLiveEvidence.reduce((total, evidence) => (
                total + Number(evidence.bytes ?? evidence.byte_count ?? 0)
            ), 0);
            const selectedBytes = files.reduce((total, file) => total + file.size, 0);
            if (autonomyLiveEvidence.length + files.length > AUTONOMY_MAX_EVIDENCE_FILES
                || existingBytes + selectedBytes > AUTONOMY_MAX_CASE_EVIDENCE_BYTES) {
                autonomyEvidenceUploadStatus.textContent = 'The selection would exceed the case limit of 10 files or 50 MB.';
                return;
            }
            if (autonomyEvidenceUploadBtn) autonomyEvidenceUploadBtn.disabled = true;
            try {
                for (const file of files) {
                    const formData = new FormData();
                    formData.append('file', file, file.name);
                    formData.append('evidence_class', autonomyEvidenceClass?.value || 'project_actual');
                    formData.append('operator_name', operatorName);
                    const response = await fetch(
                        '/api/autonomy/cases/' + encodeURIComponent(autonomyCaseId()) + '/evidence',
                        {method: 'POST', body: formData}
                    );
                    await autonomyReadResponse(response, 'Evidence upload failed.');
                }
                autonomyEvidenceFileInput.value = '';
                autonomyEvidenceUploadStatus.textContent = 'Evidence uploaded. Review extracted candidates before acceptance.';
                await autonomyRefreshLiveCase({readiness: true, evidence: true, events: true});
                autonomyAnnounce('Evidence uploaded and deterministic readiness refreshed.');
            } catch (error) {
                autonomyEvidenceUploadStatus.textContent = error.message || 'Evidence upload failed.';
            } finally {
                if (autonomyEvidenceUploadBtn) autonomyEvidenceUploadBtn.disabled = false;
            }
        }

        async function autonomyDeleteEvidence(evidenceId) {
            const caseId = autonomyCaseId();
            const safeEvidenceId = autonomyEvidenceId(evidenceId);
            const operatorName = autonomyOperator();
            if (!caseId || !safeEvidenceId || !operatorName) return;
            try {
                await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(caseId) + '/evidence/' + encodeURIComponent(safeEvidenceId),
                    {
                        method: 'DELETE',
                        body: {
                            operator_name: operatorName,
                            reason: 'Named operator removed an unreferenced evidence upload from the live case.',
                            expected_revision: autonomyLiveCase?.revision,
                        },
                    }
                );
                await autonomyRefreshLiveCase({readiness: true, evidence: true, events: true});
                autonomyAnnounce('Unreferenced evidence removed and readiness refreshed.');
            } catch (error) {
                autonomyEvidenceUploadStatus.textContent = error.message || 'Referenced evidence cannot be removed.';
            }
        }

        async function autonomyReviewCandidate(section) {
            const caseId = autonomyCaseId();
            const evidenceId = autonomyEvidenceId(section?.dataset.evidenceId);
            const candidateId = autonomySafeId(section?.dataset.candidateId, 'cand_')
                || autonomySafeId(section?.dataset.candidateId, 'evc_');
            if (!caseId || !evidenceId || !candidateId) return;
            const decision = section.querySelector('input[type="radio"]:checked')?.value;
            const rationale = section.querySelector('[data-autonomy-candidate-rationale]')?.value.trim() || '';
            const operatorName = autonomyOperator();
            const errorNode = section.querySelector('[data-autonomy-candidate-error]');
            const evidence = autonomyLiveEvidence.find((item) => item.evidence_id === evidenceId);
            const provisional = ['engineering_judgment', 'secondary_synthesis'].includes(evidence?.evidence_class);
            if (!['accepted', 'rejected'].includes(decision) || !operatorName || (provisional && !rationale)) {
                if (errorNode) {
                    errorNode.hidden = false;
                    errorNode.textContent = provisional
                        ? 'Choose accept or reject, enter a named operator, and provide the required provisional-evidence rationale.'
                        : 'Choose accept or reject and enter a named operator.';
                    errorNode.focus();
                }
                return;
            }
            if (errorNode) errorNode.hidden = true;
            try {
                await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(caseId)
                        + '/evidence/' + encodeURIComponent(evidenceId)
                        + '/candidates/' + encodeURIComponent(candidateId) + '/review',
                    {
                        method: 'POST',
                        body: {
                            decision,
                            operator_name: operatorName,
                            rationale: rationale || null,
                            expected_revision: autonomyLiveCase?.revision,
                        },
                    }
                );
                autonomySelectedStage = 'verify';
                await autonomyRefreshLiveCase({caseRecord: true, readiness: true, evidence: true, events: true});
                autonomySelectStage('verify', {focus: true, announce: false});
                autonomyAnnounce('Evidence decision recorded. The case remains in Verify evidence and readiness was refreshed.');
            } catch (error) {
                if (errorNode) {
                    errorNode.hidden = false;
                    errorNode.textContent = error.message || 'The evidence decision could not be recorded.';
                    errorNode.focus();
                }
            }
        }

        function autonomyRenderLiveWorkspace() {
            if (!autonomyPanel) return;
            autonomySetContentMode('live');
            autonomyRenderLiveCase();
            autonomyRenderLiveReadiness();
            autonomyRenderLiveMessages();
            autonomyRenderLiveEvidence();
            autonomyRenderLiveEvents();
            autonomyRenderLiveProvenance();
            autonomyRenderSourceSelection();
            autonomySyncMobileTabs(autonomyMobileSectionForStage(autonomySelectedStage));
        }

        async function autonomyFetchCase(caseId) {
            const safeCaseId = autonomyCaseId(caseId);
            if (!safeCaseId) throw new Error('The decision-case identifier is invalid.');
            const data = await autonomyJsonRequest('/api/autonomy/cases/' + encodeURIComponent(safeCaseId), {cache: 'no-store'});
            return data.case || null;
        }

        async function autonomyEvaluateReadiness(caseId) {
            const safeCaseId = autonomyCaseId(caseId);
            if (!safeCaseId) return null;
            return autonomyJsonRequest(
                '/api/autonomy/cases/' + encodeURIComponent(safeCaseId) + '/readiness/evaluate',
                {method: 'POST'}
            );
        }

        async function autonomyFetchEvents(caseId) {
            const safeCaseId = autonomyCaseId(caseId);
            if (!safeCaseId) return [];
            const data = await autonomyJsonRequest(
                '/api/autonomy/cases/' + encodeURIComponent(safeCaseId) + '/events',
                {cache: 'no-store'}
            );
            return Array.isArray(data.events) ? data.events : [];
        }

        async function autonomyFetchMessages(caseId) {
            const safeCaseId = autonomyCaseId(caseId);
            if (!safeCaseId) return [];
            const data = await autonomyJsonRequest(
                '/api/autonomy/cases/' + encodeURIComponent(safeCaseId) + '/messages',
                {cache: 'no-store'}
            );
            return Array.isArray(data.messages) ? data.messages : [];
        }

        async function autonomyFetchEvidence(caseId) {
            const safeCaseId = autonomyCaseId(caseId);
            if (!safeCaseId) return [];
            const data = await autonomyJsonRequest(
                '/api/autonomy/cases/' + encodeURIComponent(safeCaseId) + '/evidence',
                {cache: 'no-store'}
            );
            return Array.isArray(data.evidence) ? data.evidence : [];
        }

        async function autonomyFetchSourceOptions() {
            const data = await autonomyJsonRequest('/api/autonomy/sources', {cache: 'no-store'});
            return {
                sources: Array.isArray(data.sources) ? data.sources.filter((item) => item && typeof item === 'object') : [],
                analysisBases: autonomyNormalizeAnalysisBases(data.analysis_bases),
            };
        }

        async function autonomyRefreshLiveCase(options = {}) {
            const caseId = autonomyCaseId();
            if (!caseId) {
                autonomyRenderLiveWorkspace();
                return;
            }
            const requests = [];
            if (options.caseRecord) requests.push(autonomyFetchCase(caseId).then((value) => { autonomyLiveCase = value; }));
            if (options.readiness) {
                requests.push(autonomyEvaluateReadiness(caseId).then((value) => { autonomyLiveReadiness = value; }));
                requests.push(autonomyFetchSourceOptions().then((value) => {
                    autonomyEligibleAnnualSources = value.sources;
                    autonomySupportedAnalysisBases = value.analysisBases;
                }).catch(() => {
                    // Readiness carries the same safe source summaries, so the live case remains reviewable.
                    autonomyEligibleAnnualSources = [];
                    autonomySupportedAnalysisBases = [];
                }));
            }
            if (options.events) requests.push(autonomyFetchEvents(caseId).then((value) => { autonomyLiveEvents = value; }));
            if (options.messages) requests.push(autonomyFetchMessages(caseId).then((value) => { autonomyLiveMessages = value; }));
            if (options.evidence) requests.push(autonomyFetchEvidence(caseId).then((value) => { autonomyLiveEvidence = value; }));
            await Promise.all(requests);
            autonomyRenderLiveWorkspace();
        }

        async function autonomySelectLiveCase(caseId) {
            const safeCaseId = autonomyCaseId(caseId);
            if (!safeCaseId) return;
            autonomySetConnectionStatus('Loading durable case and deterministic readiness…', 'loading');
            autonomyLiveCase = await autonomyFetchCase(safeCaseId);
            autonomyLiveReadiness = null;
            autonomyLiveEvidence = [];
            autonomyLiveMessages = [];
            autonomyLiveEvents = [];
            autonomySelectedStage = 'ask';
            autonomySelectedView = 'investigation';
            await autonomyRefreshLiveCase({readiness: true, evidence: true, messages: true, events: true});
            autonomySelectedStage = autonomyLiveDefaultStage();
            autonomyRenderLiveWorkspace();
            autonomySetConnectionStatus('Durable case loaded. Readiness evaluated from current dashboard state.', 'ready');
        }

        async function autonomyLoadCases() {
            const data = await autonomyJsonRequest('/api/autonomy/cases', {cache: 'no-store'});
            autonomyCases = Array.isArray(data.cases) ? data.cases.filter((item) => autonomyCaseId(item?.case_id)) : [];
            const currentId = autonomyCaseId();
            const selected = autonomyCases.find((item) => item.case_id === currentId) || autonomyCases[0] || null;
            if (!selected) {
                autonomyLiveCase = null;
                autonomyLiveReadiness = null;
                autonomyLiveEvidence = [];
                autonomyLiveMessages = [];
                autonomyLiveEvents = [];
                autonomyRenderLiveWorkspace();
                return;
            }
            await autonomySelectLiveCase(selected.case_id);
        }

        async function autonomyOpenWorkspace() {
            autonomySetContentMode('live');
            if (autonomyWorkspaceOpenPromise) return autonomyWorkspaceOpenPromise;
            autonomySetConnectionStatus('Loading durable decision cases…', 'loading');
            autonomyWorkspaceOpenPromise = (async () => {
                try {
                    await autonomyLoadCases();
                } catch (error) {
                    autonomyLiveAgentAvailable = false;
                    autonomySetConnectionStatus(error.message || 'The Autonomy service is unavailable.', 'unavailable');
                    if (autonomyAgentStatus) {
                        autonomyAgentStatus.textContent = 'Unavailable · manual dashboard workflows remain usable';
                        autonomyAgentStatus.dataset.status = 'unavailable';
                    }
                    if (autonomyAgentComposer) autonomyAgentComposer.disabled = true;
                    if (autonomyAgentSendBtn) autonomyAgentSendBtn.disabled = true;
                    if (autonomyStateBanner) autonomyStateBanner.dataset.tone = 'warning';
                    if (autonomyStateBannerTitle) autonomyStateBannerTitle.textContent = 'Live Autonomy service unavailable';
                    if (autonomyStateBannerText) autonomyStateBannerText.textContent = 'Calibration, Annual Simulation, existing TEA, and fixture previews remain safe and usable.';
                    if (autonomyStateAction) {
                        autonomyStateAction.hidden = false;
                        autonomyStateAction.dataset.autonomyAction = 'retry_agent';
                        autonomyStateAction.dataset.autonomyDeepLink = 'retry-agent';
                        autonomyStateAction.textContent = 'Retry live connection';
                    }
                } finally {
                    autonomyWorkspaceOpenPromise = null;
                }
            })();
            return autonomyWorkspaceOpenPromise;
        }

        async function autonomyCreateCase() {
            const operatorName = autonomyOperator();
            if (!operatorName) {
                autonomySetConnectionStatus('Enter a named operator before creating a case.', 'error');
                autonomyOperatorName?.focus();
                return;
            }
            try {
                const data = await autonomyJsonRequest('/api/autonomy/cases', {
                    method: 'POST',
                    body: {
                        title: 'New decision',
                        question: 'What decision should this case investigate?',
                        operator_name: operatorName,
                    },
                });
                if (!data.case) throw new Error('The server did not return the created case.');
                autonomyCases = [data.case, ...autonomyCases.filter((item) => item.case_id !== data.case.case_id)];
                await autonomySelectLiveCase(data.case.case_id);
                autonomyQuestion?.focus();
                autonomyAnnounce('Durable decision case created. Frame the question before reviewing evidence.');
            } catch (error) {
                autonomySetConnectionStatus(error.message || 'The case could not be created.', 'error');
            }
        }

        async function autonomyUpdateLiveCase() {
            const caseId = autonomyCaseId();
            const operatorName = autonomyOperator();
            if (!caseId || !operatorName) return;
            const draftTitle = autonomyCaseTitle?.value.trim() || '';
            const draftQuestion = autonomyQuestion?.value.trim() || '';
            try {
                const data = await autonomyJsonRequest('/api/autonomy/cases/' + encodeURIComponent(caseId), {
                    method: 'PUT',
                    body: {
                        title: draftTitle,
                        question: draftQuestion,
                        expected_revision: autonomyLiveCase?.revision,
                        operator_name: operatorName,
                    },
                });
                autonomyLiveCase = data.case || autonomyLiveCase;
                autonomyCases = autonomyCases.map((item) => item.case_id === caseId ? autonomyLiveCase : item);
                await autonomyRefreshLiveCase({readiness: true, events: true});
                autonomySetConnectionStatus('Case revision saved.', 'ready');
            } catch (error) {
                if (error.status === 409) {
                    autonomySetConnectionStatus('Another authenticated user changed this case. Your typed text is preserved.', 'stale');
                    if (autonomyStateBanner) autonomyStateBanner.dataset.tone = 'warning';
                    if (autonomyStateBannerTitle) autonomyStateBannerTitle.textContent = 'This browser has an older case snapshot';
                    if (autonomyStateBannerText) autonomyStateBannerText.textContent = 'Refresh the durable case before saving another revision. Unsaved typing remains in the form.';
                    if (autonomyStateAction) {
                        autonomyStateAction.hidden = false;
                        autonomyStateAction.dataset.autonomyAction = 'refresh_case';
                        autonomyStateAction.dataset.autonomyDeepLink = 'refresh-case';
                        autonomyStateAction.textContent = 'Refresh case snapshot';
                    }
                } else {
                    autonomySetConnectionStatus(error.message || 'The case revision could not be saved.', 'error');
                }
            }
        }

        async function autonomyLockCaseBasis(event) {
            event?.preventDefault();
            const caseId = autonomyCaseId();
            const operatorName = autonomyOperatorName?.value.trim() || '';
            const sourceId = autonomySafeId(autonomyAnnualSourceSelect?.value);
            const analysisBasis = autonomyAnalysisBasisSelect?.value || '';
            const source = autonomyAvailableAnnualSources().find((item) => item.annual_job_id === sourceId);
            if (!caseId || !operatorName || !source || !['solartac_site', 'commercial_representative'].includes(analysisBasis)) {
                if (autonomySourceLockStatus) {
                    autonomySourceLockStatus.textContent = !operatorName
                        ? 'Enter a named operator before locking the decision basis.'
                        : 'Select one eligible Annual source and one approved analysis basis.';
                }
                if (!operatorName) autonomyOperatorName?.focus();
                else if (!source) autonomyAnnualSourceSelect?.focus();
                else autonomyAnalysisBasisSelect?.focus();
                return;
            }
            const sourceSha256 = String(source.source_snapshot_sha256 || '');
            if (!/^[a-f0-9]{64}$/i.test(sourceSha256)) {
                if (autonomySourceLockStatus) autonomySourceLockStatus.textContent = 'The selected source is missing its verified snapshot identity.';
                return;
            }
            if (autonomySourceLockBtn) autonomySourceLockBtn.disabled = true;
            if (autonomySourceLockStatus) autonomySourceLockStatus.textContent = 'Locking the immutable source and analysis basis…';
            try {
                const data = await autonomyJsonRequest('/api/autonomy/cases/' + encodeURIComponent(caseId), {
                    method: 'PUT',
                    body: {
                        source_annual_job_id: sourceId,
                        source_snapshot_sha256: sourceSha256,
                        analysis_basis: analysisBasis,
                        expected_revision: autonomyLiveCase?.revision,
                        operator_name: operatorName,
                    },
                });
                autonomyLiveCase = data.case || autonomyLiveCase;
                autonomyLiveReadiness = data.readiness || autonomyLiveReadiness;
                autonomyCases = autonomyCases.map((item) => item.case_id === caseId ? autonomyLiveCase : item);
                autonomySelectedStage = 'verify';
                await autonomyRefreshLiveCase({caseRecord: true, readiness: true, events: true});
                autonomySelectStage('verify', {focus: false, announce: false});
                window.requestAnimationFrame(() => autonomySourceSelection?.focus());
                autonomySetConnectionStatus('Annual source and analysis basis locked on the durable case.', 'ready');
                autonomyAnnounce('Immutable Annual source and analysis basis locked by the named operator.');
            } catch (error) {
                if (autonomySourceLockStatus) autonomySourceLockStatus.textContent = error.status === 409
                    ? 'The case or source changed before the lock was recorded. Refresh the case and review the source again.'
                    : (error.message || 'The source and analysis basis could not be locked.');
                autonomyUpdateSourceLockButton();
            }
        }

        function autonomyParseSseFrame(frame) {
            const parsed = {id: '', event: 'message', data: null};
            const dataLines = [];
            String(frame || '').split('\n').forEach((line) => {
                if (!line || line.startsWith(':')) return;
                const separator = line.indexOf(':');
                const field = separator >= 0 ? line.slice(0, separator) : line;
                let value = separator >= 0 ? line.slice(separator + 1) : '';
                if (value.startsWith(' ')) value = value.slice(1);
                if (field === 'id') parsed.id = value;
                else if (field === 'event') parsed.event = value || 'message';
                else if (field === 'data') dataLines.push(value);
            });
            if (!dataLines.length) return null;
            const rawData = dataLines.join('\n');
            try {
                parsed.data = JSON.parse(rawData);
            } catch (_) {
                parsed.data = {message: rawData};
            }
            return parsed;
        }

        function autonomyConsumeSseChunk(buffer, chunk) {
            const normalized = (String(buffer || '') + String(chunk || '')).replace(/\r\n?/g, '\n');
            const frames = normalized.split('\n\n');
            const remainder = frames.pop() || '';
            return {
                remainder,
                events: frames.map(autonomyParseSseFrame).filter(Boolean),
            };
        }

        function autonomySetAgentStreamState(state, message) {
            if (autonomyPanel) autonomyPanel.dataset.streamState = state;
            if (autonomyAgentStatus) {
                autonomyAgentStatus.textContent = message;
                autonomyAgentStatus.dataset.status = state === 'unavailable' ? 'unavailable' : state;
            }
            const busy = ['connecting', 'thinking', 'checking-readiness', 'reading-evidence', 'reconnecting'].includes(state);
            if (autonomyAgentComposer) autonomyAgentComposer.disabled = busy || !autonomyLiveAgentAvailable;
            if (autonomyAgentSendBtn) autonomyAgentSendBtn.disabled = busy || !autonomyLiveAgentAvailable;
            if (autonomyAgentComposerHelp) autonomyAgentComposerHelp.textContent = message;
        }

        function autonomyHandleStreamEvent(streamEvent) {
            if (!streamEvent || !autonomyPendingTurn) return;
            if (/^\d+$/.test(String(streamEvent.id || ''))) autonomyPendingTurn.lastEventId = String(streamEvent.id);
            const payload = streamEvent.data && typeof streamEvent.data === 'object' ? streamEvent.data : {};
            if (streamEvent.event === 'status') {
                const phase = String(payload.phase || 'thinking').replace(/_/g, '-');
                autonomySetAgentStreamState(phase, payload.message || ('Decision Agent: ' + phase.replace(/-/g, ' ')));
                autonomyAnnounce(payload.message || 'Decision Agent status updated.');
                return;
            }
            if (streamEvent.event === 'citation') {
                if (payload.citation) autonomyPendingTurn.citations.push(payload.citation);
                return;
            }
            if (streamEvent.event === 'final') {
                const message = payload.message && typeof payload.message === 'object'
                    ? {...payload.message}
                    : {role: 'assistant', content: payload.message || 'The Decision Agent returned no answer text.'};
                message.role = 'assistant';
                if (!Array.isArray(message.citations) || !message.citations.length) {
                    message.citations = [...autonomyPendingTurn.citations];
                }
                autonomyLiveMessages.push(message);
                autonomyRenderLiveMessages();
                autonomyPendingTurn = null;
                autonomyStreamReconnectAttempts = 0;
                autonomySetAgentStreamState('available', 'Available');
                autonomyAnnounce('Decision Agent answer received.');
                autonomyRefreshLiveCase({messages: true, events: true}).catch(() => {});
                return;
            }
            if (streamEvent.event === 'error') {
                const recoveryAction = typeof payload.recovery_action === 'object'
                    ? String(payload.recovery_action?.id || 'retry_agent')
                    : String(payload.recovery_action || 'retry_agent');
                const failureCode = String(payload.code || payload.error?.code || 'agent_unavailable');
                const failureMessage = typeof payload.message === 'string'
                    ? payload.message
                    : payload.message?.content || payload.error?.detail || 'The Decision Agent stream was interrupted.';
                if (payload.message && typeof payload.message === 'object') {
                    autonomyLiveMessages.push({...payload.message, role: 'assistant'});
                    autonomyRenderLiveMessages();
                }
                autonomyPendingTurn = null;
                autonomyStreamReconnectAttempts = 0;
                const unavailable = ['agent_disabled', 'agent_unavailable'].includes(failureCode);
                if (unavailable) autonomyLiveAgentAvailable = false;
                autonomySetAgentStreamState(unavailable ? 'unavailable' : 'available', failureMessage);
                if (autonomyStateBanner) autonomyStateBanner.dataset.tone = 'warning';
                if (autonomyStateBannerTitle) autonomyStateBannerTitle.textContent = 'Conversation stream interrupted';
                if (autonomyStateBannerText) autonomyStateBannerText.textContent = failureMessage;
                if (autonomyStateAction) {
                    autonomyStateAction.hidden = false;
                    const manualFallback = recoveryAction === 'continue_without_agent';
                    autonomyStateAction.dataset.autonomyAction = recoveryAction === 'refresh_case'
                        ? 'refresh_case'
                        : (manualFallback ? 'continue_without_agent' : 'retry_agent');
                    autonomyStateAction.dataset.autonomyDeepLink = recoveryAction === 'refresh_case'
                        ? 'refresh-case'
                        : (manualFallback ? '#autonomy-readiness' : 'retry-agent');
                    autonomyStateAction.textContent = recoveryAction === 'refresh_case'
                        ? 'Refresh case snapshot'
                        : (manualFallback ? 'Continue with deterministic readiness' : 'Retry connection');
                }
                autonomyAnnounce('Decision Agent stream error. The durable case is unchanged.');
                autonomyRefreshLiveCase({messages: true, events: true}).catch(() => {});
            }
        }

        async function autonomyConnectTurn(turnId, options = {}) {
            const safeTurnId = autonomyTurnId(turnId);
            const caseId = autonomyCaseId();
            if (!safeTurnId || !caseId || !autonomyPendingTurn) return;
            if (autonomyStreamAbortController) autonomyStreamAbortController.abort();
            const controller = new AbortController();
            autonomyStreamAbortController = controller;
            const cursor = /^\d+$/.test(String(autonomyPendingTurn.lastEventId || ''))
                ? String(autonomyPendingTurn.lastEventId)
                : '0';
            autonomySetAgentStreamState(options.reconnect ? 'reconnecting' : 'connecting', options.reconnect
                ? 'Reconnecting to the same durable agent turn…'
                : 'Connecting to the Decision Agent…');
            let completedNormally = false;
            try {
                const response = await fetch(
                    '/api/autonomy/cases/' + encodeURIComponent(caseId)
                        + '/message-stream/' + encodeURIComponent(safeTurnId)
                        + '?after_event_id=' + encodeURIComponent(cursor),
                    {headers: {Accept: 'text/event-stream'}, cache: 'no-store', signal: controller.signal}
                );
                if (!response.ok || !response.body) {
                    await autonomyReadResponse(response, 'The Decision Agent stream could not be opened.');
                    return;
                }
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                while (true) {
                    const {done, value} = await reader.read();
                    if (done) break;
                    const parsed = autonomyConsumeSseChunk(buffer, decoder.decode(value, {stream: true}));
                    buffer = parsed.remainder;
                    parsed.events.forEach(autonomyHandleStreamEvent);
                }
                const finalChunk = autonomyConsumeSseChunk(buffer, decoder.decode() + '\n\n');
                finalChunk.events.forEach(autonomyHandleStreamEvent);
                completedNormally = true;
            } catch (error) {
                if (error?.name === 'AbortError') return;
                if (error.status === 503) {
                    autonomyLiveAgentAvailable = false;
                    autonomySetAgentStreamState('unavailable', 'Unavailable · manual readiness and evidence review remain usable');
                    autonomyPendingTurn = null;
                    autonomyAnnounce('Decision Agent unavailable. Manual case review remains available.');
                    return;
                }
            } finally {
                if (autonomyStreamAbortController === controller) autonomyStreamAbortController = null;
            }
            if (autonomyPendingTurn && (completedNormally || !controller.signal.aborted)) {
                if (autonomyStreamReconnectAttempts < 2) {
                    autonomyStreamReconnectAttempts += 1;
                    autonomySetAgentStreamState('reconnecting', 'Stream interrupted. Reconnecting to the same turn…');
                    window.setTimeout(() => {
                        if (autonomyPendingTurn) autonomyConnectTurn(autonomyPendingTurn.turnId, {reconnect: true});
                    }, 400 * autonomyStreamReconnectAttempts);
                } else {
                    autonomySetAgentStreamState('reconnecting', 'Stream interrupted. The case is safe; retry the same turn.');
                    if (autonomyStateBanner) autonomyStateBanner.dataset.tone = 'warning';
                    if (autonomyStateBannerTitle) autonomyStateBannerTitle.textContent = 'Conversation stream interrupted';
                    if (autonomyStateBannerText) autonomyStateBannerText.textContent = 'The case, evidence, and durable messages remain safe. Retry resumes the same turn from the last event cursor.';
                    if (autonomyStateAction) {
                        autonomyStateAction.hidden = false;
                        autonomyStateAction.dataset.autonomyAction = 'retry_agent';
                        autonomyStateAction.dataset.autonomyDeepLink = 'retry-agent';
                        autonomyStateAction.textContent = 'Retry connection';
                    }
                }
            }
        }

        function autonomyReconnectStream() {
            if (!autonomyPendingTurn) {
                autonomyOpenWorkspace();
                return;
            }
            autonomyStreamReconnectAttempts = 0;
            autonomyConnectTurn(autonomyPendingTurn.turnId, {reconnect: true});
        }

        async function autonomySendLiveMessage() {
            if (autonomyContentMode !== 'live' || !autonomyCaseId() || !autonomyLiveAgentAvailable || autonomyPendingTurn) return;
            const message = autonomyAgentComposer?.value.trim() || '';
            const operatorName = autonomyOperator();
            if (!message) {
                autonomyAgentComposer?.focus();
                return;
            }
            if (!operatorName) {
                autonomySetConnectionStatus('Enter a named operator before sending a message.', 'error');
                autonomyOperatorName?.focus();
                return;
            }
            const clientMessageId = autonomyClientMessageId();
            autonomyAgentComposer.value = '';
            autonomyLiveMessages.push({role: 'user', content: message, created_at: new Date().toISOString()});
            autonomyRenderLiveMessages();
            autonomySetAgentStreamState('connecting', 'Saving the question and opening a durable agent turn…');
            try {
                const data = await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(autonomyCaseId()) + '/messages',
                    {
                        method: 'POST',
                        body: {message, client_message_id: clientMessageId, operator_name: operatorName},
                    }
                );
                const turn = data.turn && typeof data.turn === 'object' ? data.turn : null;
                const turnId = autonomyTurnId(turn?.turn_id);
                if (!turnId) throw new Error('The server did not return a safe durable turn identifier.');
                autonomyPendingTurn = {turnId, lastEventId: '0', citations: []};
                autonomyStreamReconnectAttempts = 0;
                try {
                    autonomyLiveMessages = await autonomyFetchMessages(autonomyCaseId());
                    autonomyRenderLiveMessages();
                } catch (_) {
                    // The optimistic user message remains visible while the durable stream connects.
                }
                await autonomyConnectTurn(turnId);
            } catch (error) {
                autonomyPendingTurn = null;
                autonomySetAgentStreamState(error.status === 503 ? 'unavailable' : 'available', error.status === 503
                    ? 'Unavailable · manual readiness and evidence review remain usable'
                    : 'Available · the message was not sent');
                if (error.status === 503) autonomyLiveAgentAvailable = false;
                autonomySetConnectionStatus(error.message || 'The Decision Agent message could not be started.', 'error');
            }
        }

        function autonomyExecuteSupportedAction(actionId, requestedDeepLink) {
            if (!Object.prototype.hasOwnProperty.call(AUTONOMY_SUPPORTED_ACTIONS, actionId)) {
                autonomyAnnounce('That action is not supported by this frontend contract.');
                return;
            }
            const mapped = AUTONOMY_SUPPORTED_ACTIONS[actionId];
            if (mapped === 'retry-agent') return autonomyReconnectStream();
            if (mapped === 'refresh-case') return autonomySelectLiveCase(autonomyCaseId());
            if (mapped === 'new-case') return autonomyCreateCase();
            const deepLinkKey = Object.prototype.hasOwnProperty.call(AUTONOMY_ALLOWED_DEEP_LINKS, requestedDeepLink)
                ? requestedDeepLink
                : mapped;
            const target = AUTONOMY_ALLOWED_DEEP_LINKS[deepLinkKey];
            if (!target) return;
            if (target.mode) {
                switchMode(target.mode);
                window.requestAnimationFrame(() => document.getElementById(target.targetId)?.focus({preventScroll: false}));
                return;
            }
            if (target.stage) autonomySelectStage(target.stage, {focus: true, announce: false});
            if (target.rail) {
                autonomyActivateRailTab(target.rail);
                autonomyOpenEvidenceRail(autonomyStateAction);
            }
            if (target.targetId) document.getElementById(target.targetId)?.focus();
        }

        function autonomyResetSignedDecision() {
            autonomySignedDecision = {
                disposition: 'accept',
                owner: 'Jordan Lee',
                rationale: 'The reviewed evidence supports the conditional recommendation.',
            };
        }

        function autonomySignedDecisionSummary() {
            const action = {
                accept: 'accepted the recommendation',
                reject: 'rejected the recommendation',
                defer: 'deferred the decision',
            }[autonomySignedDecision.disposition] || 'recorded a decision';
            return autonomySignedDecision.owner + ' ' + action + '.';
        }

        function autonomyCurrentFixture() {
            return AUTONOMY_FIXTURE_CATALOG[autonomyFixtureId] || AUTONOMY_FIXTURE_CATALOG['evidence-needed'];
        }

        function autonomyDefaultRoute(fixtureId) {
            const fixture = AUTONOMY_FIXTURE_CATALOG[fixtureId] || AUTONOMY_FIXTURE_CATALOG['evidence-needed'];
            return {stage: fixture.stage, view: fixture.defaultView};
        }

        function autonomyStageStatuses(fixture) {
            const currentIndex = Math.max(0, AUTONOMY_STAGES.indexOf(fixture.stage));
            return AUTONOMY_STAGES.map((stage, index) => {
                if (fixture.signed) return 'complete';
                if (index < currentIndex) return 'complete';
                if (index > currentIndex) return 'not-started';
                return fixture.stageState;
            });
        }

        function autonomyAnnounce(message) {
            if (!autonomyLiveStatus) return;
            autonomyLiveStatus.textContent = '';
            window.requestAnimationFrame(() => {
                autonomyLiveStatus.textContent = message;
            });
        }

        function autonomyPopulateFixtureSelect() {
            if (!autonomyFixtureSelect || autonomyFixtureSelect.options.length) return;
            Object.entries(AUTONOMY_FIXTURE_CATALOG).forEach(([id, fixture]) => {
                const option = document.createElement('option');
                option.value = id;
                option.textContent = fixture.label;
                autonomyFixtureSelect.appendChild(option);
            });
            autonomyFixtureSelect.value = autonomyFixtureId;
        }

        function autonomyRenderReadiness(fixture) {
            AUTONOMY_READINESS_KEYS.forEach((key) => {
                const item = autonomyPanel.querySelector('[data-autonomy-readiness="' + key + '"]');
                if (!item) return;
                const value = fixture.readiness[key] || ['not-started', 'Not checked'];
                item.dataset.state = value[0];
                item.dataset.status = value[0];
                const status = item.querySelector('[data-autonomy-readiness-status]');
                if (status) status.textContent = value[1];
            });
        }

        function autonomyRenderStepper(fixture) {
            const statuses = autonomyStageStatuses(fixture);
            autonomyPanel.querySelectorAll('[data-autonomy-stage]').forEach((button) => {
                const stage = button.dataset.autonomyStage;
                const index = AUTONOMY_STAGES.indexOf(stage);
                const statusValue = statuses[index] || 'not-started';
                button.dataset.status = statusValue;
                button.dataset.autonomyStageStatus = statusValue;
                button.classList.toggle('is-selected', stage === autonomySelectedStage);
                button.classList.toggle('is-current', stage === fixture.stage);
                button.setAttribute('aria-pressed', String(stage === autonomySelectedStage));
                button.setAttribute('aria-selected', String(stage === autonomySelectedStage));
                button.tabIndex = stage === autonomySelectedStage ? 0 : -1;
                if (stage === fixture.stage) button.setAttribute('aria-current', 'step');
                else button.removeAttribute('aria-current');
                const status = button.querySelector('small');
                if (status) {
                    status.textContent = {
                        complete: 'Complete', current: 'Current', blocked: 'Blocked',
                        'needs-attention': 'Needs attention', 'not-started': 'Not started',
                    }[statusValue] || 'Not started';
                }
            });
            autonomyPanel.querySelectorAll('[data-autonomy-stage-panel]').forEach((panel) => {
                panel.hidden = panel.dataset.autonomyStagePanel !== autonomySelectedStage;
            });
            if (autonomyStageSelect) autonomyStageSelect.value = autonomySelectedStage;
        }

        function autonomyRenderScenarios(fixture) {
            const states = {
                empty: ['Not started', 'Not started', 'Not started', 'Not started'],
                draft: ['Baseline', 'Draft', 'Draft', 'Draft'],
                'evidence-needed': ['Validated', 'Needs evidence', 'Needs evidence', 'Draft'],
                'evidence-conflict': ['Validated', 'Conflicting evidence', 'Needs review', 'Draft'],
                invalid: ['Validated', 'Validated', 'Validated', 'Blocked'],
                validated: ['Validated', 'Validated', 'Validated', 'Not selected'],
                confirmed: ['Confirmed', 'Confirmed', 'Confirmed', 'Not selected'],
                completed: ['Completed', 'Completed', 'Completed', 'Not selected'],
                revised: ['Signed revision 3', 'Validated', 'New revision', 'Draft'],
            }[fixture.scenarioState] || ['Baseline', 'Draft', 'Draft', 'Draft'];
            autonomyPanel.querySelectorAll('[data-autonomy-scenario]').forEach((card, index) => {
                const value = states[index] || 'Draft';
                card.dataset.state = value.toLowerCase().replace(/\s+/g, '-');
                const status = card.querySelector('[data-autonomy-scenario-status]');
                if (status) status.textContent = value;
            });
        }

        function autonomyJobPresentation(jobState) {
            const presentations = {
                queued: [
                    ['Queued', 0], ['Queued', 0], ['Queued', 0],
                ],
                running: [
                    ['Completed', 100], ['Running · sensitivity analysis', 68], ['Queued', 0],
                ],
                failed: [
                    ['Completed', 100], ['Failed safely', 46], ['Queued', 0],
                ],
                partial: [
                    ['Completed', 100], ['Completed', 100], ['Failed safely', 72],
                ],
                completed: [
                    ['Completed', 100], ['Completed', 100], ['Completed', 100],
                ],
            };
            return presentations[jobState] || [];
        }

        function autonomyRenderJobs(fixture) {
            const presentation = autonomyJobPresentation(fixture.jobState);
            if (autonomyJobList) autonomyJobList.hidden = presentation.length === 0;
            autonomyPanel.querySelectorAll('[data-autonomy-job]').forEach((card, index) => {
                const item = presentation[index] || ['Not queued', 0];
                card.dataset.state = item[0].toLowerCase().replace(/[^a-z]+/g, '-');
                const status = card.querySelector('[data-autonomy-job-status]');
                const progress = card.querySelector('[data-autonomy-job-progress]');
                if (status) status.textContent = item[0];
                if (progress) {
                    progress.value = item[1];
                    progress.setAttribute('aria-valuetext', item[0]);
                }
            });
            if (autonomyPartialResultsBanner) autonomyPartialResultsBanner.hidden = fixture.briefState !== 'partial';
            if (autonomyDecisionReadyBanner) autonomyDecisionReadyBanner.hidden = autonomyFixtureId !== 'results-ready';
        }

        function autonomyCanOpenBrief(fixture) {
            return fixture.briefState !== 'unavailable';
        }

        function autonomyMobileSectionForStage(stage, fixture = autonomyCurrentFixture()) {
            if (stage === 'ask') return 'ask';
            if (stage === 'verify') return 'evidence';
            if (stage === 'decide' && autonomyCanOpenBrief(fixture)) return 'decision';
            return 'scenarios';
        }

        function autonomySyncMobileTabs(section) {
            autonomyMobileSection = section;
            autonomyPanel.dataset.mobileSection = section;
            const briefAvailable = autonomyCanOpenBrief(autonomyCurrentFixture());
            autonomyPanel.querySelectorAll('[data-autonomy-mobile-tab]').forEach((button) => {
                const isDecision = button.dataset.autonomyMobileTab === 'decision';
                const selected = button.dataset.autonomyMobileTab === section;
                button.disabled = isDecision && !briefAvailable;
                button.setAttribute('aria-disabled', String(isDecision && !briefAvailable));
                button.setAttribute('aria-selected', String(selected));
                button.classList.toggle('is-selected', selected);
                button.tabIndex = selected ? 0 : -1;
            });
        }

        function autonomySetView(view, options = {}) {
            const fixture = autonomyCurrentFixture();
            const requestedBrief = autonomyContentMode === 'fixture' && view === 'decision-brief';
            autonomySelectedView = requestedBrief && autonomyCanOpenBrief(fixture) ? 'decision-brief' : 'investigation';
            const brief = autonomySelectedView === 'decision-brief';
            if (autonomyInvestigationView) autonomyInvestigationView.hidden = !fixture.caseExists || brief;
            if (autonomyDecisionBrief) autonomyDecisionBrief.hidden = !fixture.caseExists || !brief;
            if (autonomyInvestigationViewBtn) {
                autonomyInvestigationViewBtn.classList.toggle('is-selected', !brief);
                autonomyInvestigationViewBtn.setAttribute('aria-pressed', String(!brief));
                autonomyInvestigationViewBtn.setAttribute('aria-selected', String(!brief));
                autonomyInvestigationViewBtn.tabIndex = brief ? -1 : 0;
            }
            if (autonomyBriefViewBtn) {
                autonomyBriefViewBtn.disabled = !autonomyCanOpenBrief(fixture);
                autonomyBriefViewBtn.classList.toggle('is-selected', brief);
                autonomyBriefViewBtn.setAttribute('aria-pressed', String(brief));
                autonomyBriefViewBtn.setAttribute('aria-selected', String(brief));
                autonomyBriefViewBtn.setAttribute('aria-disabled', String(!autonomyCanOpenBrief(fixture)));
                autonomyBriefViewBtn.tabIndex = brief ? 0 : -1;
            }
            if (autonomyPanel) autonomyPanel.dataset.view = autonomySelectedView;
            if (options.syncMobile !== false) {
                autonomySyncMobileTabs(brief ? 'decision' : autonomyMobileSectionForStage(autonomySelectedStage, fixture));
            }
            if (options.focus) {
                const target = brief ? autonomyDecisionBrief : autonomyInvestigationView;
                target?.focus({preventScroll: false});
            }
            if (options.announce) {
                autonomyAnnounce(brief ? 'Decision Brief opened for the current case.' : 'Investigation Workspace opened for the current case.');
            }
        }

        function autonomyRenderBrief(fixture) {
            if (!autonomyDecisionBrief) return;
            autonomyDecisionBrief.dataset.briefState = fixture.briefState;
            if (autonomyBriefPartialWarning) autonomyBriefPartialWarning.hidden = fixture.briefState !== 'partial';
            autonomyDecisionBrief.querySelectorAll('[data-autonomy-partial-only]').forEach((element) => {
                element.hidden = fixture.briefState !== 'partial';
            });
            autonomyDecisionBrief.querySelectorAll('[data-autonomy-complete-results]').forEach((element) => {
                element.hidden = fixture.briefState === 'partial';
            });
            if (autonomyRecommendationTitle) {
                autonomyRecommendationTitle.textContent = fixture.briefState === 'partial'
                    ? 'No final recommendation from partial results'
                    : 'Conditionally prefer SolarEdge for this decision case';
            }
            if (autonomyRecommendationConfidence) {
                autonomyRecommendationConfidence.textContent = fixture.briefState === 'provisional'
                    ? 'Provisional confidence'
                    : (fixture.briefState === 'partial' ? 'Partial evidence only' : 'Mixed confidence');
            }
            if (autonomyRecommendationCopy) {
                autonomyRecommendationCopy.textContent = fixture.briefState === 'partial'
                    ? 'Two fixture scenarios are complete. Wait for or recover the remaining result before treating this preview as a decision.'
                    : 'Prefer SolarEdge only if the accepted transformer and maintenance assumptions hold; the recommendation reverses when incremental cost rises without a matching lifecycle-energy gain.';
            }
            if (autonomyPrepareSignoffBtn) {
                autonomyPrepareSignoffBtn.disabled = !fixture.signoffAllowed;
                autonomyPrepareSignoffBtn.hidden = fixture.signed;
            }
            autonomyDecisionBrief.querySelectorAll('[data-autonomy-prepare-signoff]').forEach((button) => {
                button.disabled = !fixture.signoffAllowed;
                button.hidden = fixture.signed;
            });
            autonomyDecisionBrief.querySelectorAll('[data-autonomy-signoff-status]').forEach((status) => {
                status.textContent = fixture.signed
                    ? 'Signed fixture · ' + autonomySignedDecision.disposition
                    : 'Unsigned fixture';
                status.dataset.status = fixture.signed ? 'signed' : 'unsigned';
            });
            if (autonomySignedSummary) autonomySignedSummary.textContent = autonomySignedDecisionSummary();
            if (autonomySignedRationale) autonomySignedRationale.textContent = 'Recorded fixture rationale: ' + autonomySignedDecision.rationale;
            autonomyDecisionBrief.querySelectorAll('[data-autonomy-signed-only]').forEach((element) => {
                element.hidden = !fixture.signed;
            });
            autonomyDecisionBrief.querySelectorAll('[data-autonomy-superseded-only]').forEach((element) => {
                element.hidden = !fixture.superseded;
            });
        }

        function autonomyRenderWorkspace(options = {}) {
            if (!autonomyPanel) return;
            autonomySetContentMode('fixture');
            const fixture = autonomyCurrentFixture();
            autonomyPanel.dataset.autonomyFixture = autonomyFixtureId;
            autonomyPanel.dataset.autonomyCaseId = fixture.caseExists ? AUTONOMY_CASE_ID : '';
            autonomyPanel.dataset.autonomyCaseRevision = fixture.superseded ? 'revision_004' : AUTONOMY_CASE_REVISION;
            autonomyPanel.dataset.caseState = fixture.caseState;
            if (autonomyFixtureSelect) autonomyFixtureSelect.value = autonomyFixtureId;
            if (autonomyCaseEmpty) autonomyCaseEmpty.hidden = fixture.caseExists;
            if (autonomyCaseContent) autonomyCaseContent.hidden = !fixture.caseExists;
            autonomyPanel.querySelectorAll('[data-autonomy-case-workspace]').forEach((element) => {
                element.hidden = !fixture.caseExists;
            });
            if (autonomyCaseTitle) autonomyCaseTitle.disabled = !fixture.caseExists || fixture.signed;
            if (autonomyQuestion) autonomyQuestion.disabled = !fixture.caseExists || fixture.signed;
            if (autonomyCaseStatus) {
                autonomyCaseStatus.textContent = fixture.caseState.replace(/_/g, ' ');
                autonomyCaseStatus.dataset.state = fixture.caseState;
                autonomyCaseStatus.dataset.status = fixture.caseState;
            }
            if (autonomyDecisionOwner) autonomyDecisionOwner.textContent = fixture.signed ? autonomySignedDecision.owner : 'Decision owner pending';
            if (autonomySourceLock) autonomySourceLock.textContent = AUTONOMY_ANNUAL_SOURCE_ID + ' · SHA 82d9…91c4';
            if (autonomyBasisLock) autonomyBasisLock.textContent = AUTONOMY_TEA_BASIS;
            if (autonomyCaseRevision) autonomyCaseRevision.textContent = fixture.superseded
                ? 'Revision 4 · superseding fixture revision'
                : 'Revision 3 · shared fixture identity';
            if (autonomyUpdatedAt) autonomyUpdatedAt.textContent = fixture.signed ? 'Signed Aug 27, 2026 · 10:42 MDT' : 'Fixture updated Aug 27, 2026';
            if (autonomyStateBanner) autonomyStateBanner.dataset.tone = fixture.bannerTone;
            if (autonomyStateBannerTitle) autonomyStateBannerTitle.textContent = fixture.bannerTitle;
            if (autonomyStateBannerText) autonomyStateBannerText.textContent = fixture.signed
                ? autonomySignedDecisionSummary() + ' This fixture revision is immutable.'
                : fixture.bannerText;
            if (autonomyStateAction) {
                autonomyStateAction.hidden = !fixture.action;
                autonomyStateAction.dataset.autonomyAction = fixture.action;
                autonomyStateAction.textContent = fixture.actionLabel;
            }
            if (autonomyAgentStatus) {
                autonomyAgentStatus.textContent = fixture.agentStatus;
                autonomyAgentStatus.dataset.status = fixture.readiness.agent?.[0] === 'passed'
                    ? 'available'
                    : fixture.readiness.agent?.[0] || 'unavailable';
            }
            if (autonomyAgentAnswer) autonomyAgentAnswer.textContent = fixture.agentAnswer;
            if (autonomyAgentBasis) autonomyAgentBasis.textContent = fixture.agentBasis;
            if (autonomyAgentLimits) autonomyAgentLimits.textContent = fixture.agentLimits;
            if (autonomyAgentNextAction) autonomyAgentNextAction.textContent = fixture.agentNextAction;
            if (autonomyAgentComposer) autonomyAgentComposer.disabled = autonomyFixtureId === 'agent-unavailable';
            if (autonomyAgentSendBtn) autonomyAgentSendBtn.disabled = autonomyFixtureId === 'agent-unavailable';
            autonomyPanel.querySelectorAll('[name="autonomyEvidenceDecision"]').forEach((input) => {
                input.disabled = fixture.signed;
            });
            if (autonomyEvidenceRationale) autonomyEvidenceRationale.disabled = fixture.signed;
            if (autonomyEvidenceReviewBtn) autonomyEvidenceReviewBtn.disabled = fixture.signed;
            const confirmationAllowed = autonomyFixtureId === 'ready-to-confirm';
            if (autonomyOpenConfirmationBtn) {
                autonomyOpenConfirmationBtn.disabled = !confirmationAllowed;
                autonomyOpenConfirmationBtn.setAttribute('aria-disabled', String(!confirmationAllowed));
            }
            autonomyRenderReadiness(fixture);
            autonomyRenderStepper(fixture);
            autonomyRenderScenarios(fixture);
            autonomyRenderJobs(fixture);
            autonomyRenderBrief(fixture);
            autonomySetView(autonomySelectedView);
            if (options.announce) autonomyAnnounce(fixture.label + '. ' + fixture.bannerTitle + '.');
        }

        function autonomySelectFixture(fixtureId, options = {}) {
            if (!Object.prototype.hasOwnProperty.call(AUTONOMY_FIXTURE_CATALOG, fixtureId)) return;
            autonomySetContentMode('fixture');
            autonomyFixtureId = fixtureId;
            const route = autonomyDefaultRoute(fixtureId);
            autonomySelectedStage = route.stage;
            autonomySelectedView = route.view;
            autonomyMobileSection = route.view === 'decision-brief'
                ? 'decision'
                : autonomyMobileSectionForStage(route.stage, AUTONOMY_FIXTURE_CATALOG[fixtureId]);
            autonomySyncMobileTabs(autonomyMobileSection);
            autonomyCloseEvidenceRail(false);
            autonomyRenderWorkspace({announce: options.announce !== false});
        }

        function autonomySelectStage(stage, options = {}) {
            if (!AUTONOMY_STAGES.includes(stage)) return;
            if (autonomyContentMode === 'live' && !AUTONOMY_LIVE_STAGES.includes(stage)) {
                const previewFixture = {
                    compare: 'scenario-invalid',
                    run: 'ready-to-confirm',
                    decide: 'results-ready',
                }[stage];
                if (previewFixture) {
                    autonomySelectFixture(previewFixture, {announce: options.announce !== false});
                    if (options.focus) {
                        autonomyPanel.querySelector('[data-autonomy-stage-panel="' + stage + '"]')?.focus();
                    }
                    return;
                }
            }
            autonomySelectedStage = stage;
            autonomySelectedView = 'investigation';
            autonomySyncMobileTabs(autonomyMobileSectionForStage(stage));
            autonomyRenderStepper(autonomyCurrentFixture());
            autonomySetView('investigation', {syncMobile: false});
            if (options.focus) {
                autonomyPanel.querySelector('[data-autonomy-stage-panel="' + stage + '"]')?.focus();
            }
            if (options.announce !== false) autonomyAnnounce('Opened ' + stage.replace('-', ' ') + ' stage. Case state is unchanged.');
        }

        function autonomyActivateRailTab(tabName, options = {}) {
            autonomySelectedRailTab = tabName;
            autonomyPanel.querySelectorAll('[data-autonomy-rail-tab]').forEach((button) => {
                const selected = button.dataset.autonomyRailTab === tabName;
                button.setAttribute('aria-selected', String(selected));
                button.tabIndex = selected ? 0 : -1;
                if (selected && options.focus) button.focus();
            });
            autonomyPanel.querySelectorAll('[data-autonomy-rail-panel]').forEach((panel) => {
                panel.hidden = panel.dataset.autonomyRailPanel !== tabName;
            });
        }

        function autonomySetMobileSection(section, options = {}) {
            if (!['ask', 'scenarios', 'evidence', 'decision'].includes(section)) return;
            if (section === 'decision' && !autonomyCanOpenBrief(autonomyCurrentFixture())) {
                autonomyAnnounce('Decision Brief is unavailable until fixture results are ready.');
                return;
            }
            autonomySyncMobileTabs(section);
            if (options.focus) {
                autonomyPanel.querySelector('[data-autonomy-mobile-tab="' + section + '"]')?.focus();
            }
            if (section === 'decision') autonomySetView('decision-brief', {syncMobile: false});
            else autonomySetView('investigation', {syncMobile: false});
            if (options.announce !== false) autonomyAnnounce('Opened ' + section + ' mobile workspace tab.');
        }

        function autonomyFocusable(container) {
            if (!container) return [];
            return Array.from(container.querySelectorAll(
                'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
            )).filter((element) => !element.hidden && element.getClientRects().length > 0);
        }

        function autonomyTrapFocus(event, container) {
            if (event.key === 'Tab') {
                const focusable = autonomyFocusable(container);
                if (!focusable.length) return;
                const first = focusable[0];
                const last = focusable[focusable.length - 1];
                if (event.shiftKey && document.activeElement === first) {
                    event.preventDefault();
                    last.focus();
                } else if (!event.shiftKey && document.activeElement === last) {
                    event.preventDefault();
                    first.focus();
                }
            }
        }

        function autonomyIsTabletRail() {
            return window.matchMedia('(min-width: 768px) and (max-width: 1279px)').matches;
        }

        function autonomyOpenEvidenceRail(trigger = autonomyOpenRailBtn) {
            if (!autonomyEvidenceRail) return;
            if (window.matchMedia('(max-width: 767px)').matches) {
                autonomySetMobileSection('evidence', {announce: true});
                return;
            }
            if (!autonomyIsTabletRail()) return;
            autonomyLastRailTrigger = trigger || document.activeElement;
            autonomyEvidenceRail.classList.add('is-open');
            autonomyEvidenceRail.setAttribute('role', 'dialog');
            autonomyEvidenceRail.setAttribute('aria-hidden', 'false');
            autonomyEvidenceRail.setAttribute('aria-modal', 'true');
            autonomyOpenRailBtn?.setAttribute('aria-expanded', 'true');
            if (autonomyRailBackdrop) autonomyRailBackdrop.hidden = false;
            document.body.classList.add('autonomy-rail-open');
            autonomyCloseRailBtn?.focus({preventScroll: true});
            setTimeout(() => autonomyCloseRailBtn?.focus({preventScroll: true}), 50);
            autonomyAnnounce('Evidence and readiness drawer opened.');
        }

        function autonomyCloseEvidenceRail(restoreFocus = true) {
            if (!autonomyEvidenceRail) return;
            autonomyEvidenceRail.classList.remove('is-open');
            autonomyEvidenceRail.removeAttribute('role');
            autonomyEvidenceRail.removeAttribute('aria-modal');
            if (autonomyIsTabletRail()) autonomyEvidenceRail.setAttribute('aria-hidden', 'true');
            else autonomyEvidenceRail.setAttribute('aria-hidden', 'false');
            if (autonomyRailBackdrop) autonomyRailBackdrop.hidden = true;
            autonomyOpenRailBtn?.setAttribute('aria-expanded', 'false');
            document.body.classList.remove('autonomy-rail-open');
            if (restoreFocus && autonomyLastRailTrigger instanceof HTMLElement) autonomyLastRailTrigger.focus();
            autonomyLastRailTrigger = null;
        }

        function autonomyOpenDialog(dialog, trigger) {
            if (!dialog) return;
            autonomyLastDialogTrigger = trigger || document.activeElement;
            if (typeof dialog.showModal === 'function') dialog.showModal();
            else dialog.setAttribute('open', '');
        }

        function autonomyCloseDialog(dialog) {
            if (!dialog) return;
            if (typeof dialog.close === 'function') dialog.close();
            else dialog.removeAttribute('open');
            if (autonomyLastDialogTrigger instanceof HTMLElement) autonomyLastDialogTrigger.focus();
            autonomyLastDialogTrigger = null;
        }

        function autonomyOpenRunConfirmation(trigger) {
            if (autonomyFixtureId !== 'ready-to-confirm') {
                autonomyAnnounce('Grouped confirmation is available only when the fixture is ready to confirm.');
                return;
            }
            autonomyOpenDialog(autonomyConfirmDialog, trigger);
        }

        function autonomyOpenSignoff(trigger) {
            if (!autonomyCurrentFixture().signoffAllowed) {
                autonomyAnnounce('Sign-off is unavailable until the complete fixture brief is ready.');
                return;
            }
            autonomyOpenDialog(autonomySignoffDialog, trigger);
        }

        function autonomyHandleStateAction(action) {
            if (autonomyContentMode === 'live') {
                return autonomyExecuteSupportedAction(action, autonomyStateAction?.dataset.autonomyDeepLink || '');
            }
            if (action === 'start-decision') return autonomySelectFixture('new-case');
            if (action === 'focus-question') return autonomyQuestion?.focus();
            if (action === 'open-calibration') return switchMode('validation');
            if (action === 'open-annual') return switchMode('annual');
            if (action === 'inspect-coverage' || action === 'review-source-lock') {
                autonomyActivateRailTab('readiness');
                return autonomyOpenEvidenceRail(autonomyStateAction);
            }
            if (action === 'open-evidence') {
                autonomyActivateRailTab('evidence');
                return autonomyOpenEvidenceRail(autonomyStateAction);
            }
            if (action === 'manual-review') return autonomySelectStage('verify', {focus: true});
            if (action === 'review-scenarios') return autonomySelectStage('compare', {focus: true});
            if (action === 'open-confirmation' || action === 'prepare-signoff') {
                return action === 'open-confirmation'
                    ? autonomyOpenRunConfirmation(autonomyStateAction)
                    : autonomyOpenSignoff(autonomyStateAction);
            }
            if (action === 'advance-running') {
                autonomySelectFixture('running');
                return;
            }
            if (action === 'advance-partial') return autonomySelectFixture('partial-results');
            if (action === 'preview-retry') return autonomySelectFixture('queued');
            if (action === 'open-partial-brief') return autonomySetView('decision-brief', {focus: true, announce: true});
            if (action === 'open-brief' || action === 'view-signed') return autonomySetView('decision-brief', {focus: true, announce: true});
            if (action === 'test-reversal') return autonomySelectStage('compare', {focus: true});
            if (action === 'retry-connection') return autonomySelectFixture('evidence-needed');
            if (action === 'refresh-case') return autonomySelectFixture('evidence-needed');
        }

        function autonomyBindRovingTabs(buttons, activation) {
            buttons.forEach((button) => {
                button.addEventListener('keydown', (event) => {
                    const enabledButtons = buttons.filter((candidate) => (
                        !candidate.disabled && candidate.getAttribute('aria-disabled') !== 'true'
                    ));
                    const index = enabledButtons.indexOf(button);
                    if (index < 0) return;
                    let nextIndex = null;
                    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = (index + 1) % enabledButtons.length;
                    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') nextIndex = (index - 1 + enabledButtons.length) % enabledButtons.length;
                    if (event.key === 'Home') nextIndex = 0;
                    if (event.key === 'End') nextIndex = enabledButtons.length - 1;
                    if (nextIndex !== null) {
                        event.preventDefault();
                        enabledButtons[nextIndex].focus();
                        activation(enabledButtons[nextIndex], true);
                    }
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        activation(button, true);
                    }
                });
            });
        }

        function autonomyInitializeWorkspace() {
            if (!autonomyPanel || autonomyInitialized) return;
            autonomyInitialized = true;
            autonomyPopulateFixtureSelect();
            autonomyFixtureSelect?.addEventListener('change', () => {
                if (autonomyFixtureSelect.value === 'signed') autonomyResetSignedDecision();
                autonomySelectFixture(autonomyFixtureSelect.value);
            });
            autonomyTab?.addEventListener('click', () => switchMode('autonomy'));
            autonomyReturnLiveBtn?.addEventListener('click', () => autonomyOpenWorkspace());
            autonomyNewDecisionBtn?.addEventListener('click', () => {
                if (autonomyContentMode === 'live') autonomyCreateCase();
                else autonomySelectFixture('new-case');
            });
            autonomyPanel.querySelectorAll('[data-autonomy-fixture-action="start"]').forEach((button) => {
                button.addEventListener('click', () => {
                    if (autonomyContentMode === 'live') autonomyCreateCase();
                    else autonomySelectFixture('new-case');
                });
            });
            autonomyCaseSelect?.addEventListener('change', () => {
                if (autonomyContentMode === 'live') autonomySelectLiveCase(autonomyCaseSelect.value);
            });
            autonomyCaseTitle?.addEventListener('change', () => {
                if (autonomyContentMode === 'live') autonomyUpdateLiveCase();
            });
            autonomyQuestion?.addEventListener('change', () => {
                if (autonomyContentMode === 'live') autonomyUpdateLiveCase();
            });
            autonomyInvestigationViewBtn?.addEventListener('click', () => autonomySetView('investigation', {focus: true, announce: true}));
            autonomyBriefViewBtn?.addEventListener('click', () => autonomySetView('decision-brief', {focus: true, announce: true}));
            autonomyStateAction?.addEventListener('click', () => autonomyHandleStateAction(autonomyStateAction.dataset.autonomyAction));
            autonomyPanel.querySelectorAll('[data-autonomy-stage]').forEach((button) => {
                button.addEventListener('click', () => autonomySelectStage(button.dataset.autonomyStage, {focus: true}));
            });
            autonomyStageSelect?.addEventListener('change', () => autonomySelectStage(autonomyStageSelect.value, {focus: true}));
            autonomyPanel.querySelectorAll('[data-autonomy-case-action]').forEach((button) => {
                button.addEventListener('click', () => {
                    const action = button.dataset.autonomyCaseAction;
                    button.closest('details')?.removeAttribute('open');
                    if (action === 'rename') autonomyCaseTitle?.focus();
                    else if (action === 'details') {
                        autonomyActivateRailTab('provenance');
                        autonomyOpenEvidenceRail(button);
                    } else {
                        autonomyAnnounce(autonomyContentMode === 'live'
                            ? 'That case action is not exposed in the live Agent and Evidence phase.'
                            : 'Fixture ' + action + ' preview selected. No case record was changed.');
                    }
                });
            });
            autonomyPanel.querySelectorAll('[data-autonomy-source]').forEach((button) => {
                button.addEventListener('click', () => {
                    autonomyActivateRailTab(button.dataset.autonomySource === 'annual-energy' ? 'provenance' : 'evidence');
                    autonomyOpenEvidenceRail(button);
                });
            });
            autonomyPanel.querySelectorAll('[data-autonomy-prompt]').forEach((button) => {
                button.addEventListener('click', () => {
                    if (!autonomyAgentComposer || autonomyAgentComposer.disabled) return;
                    autonomyAgentComposer.value = button.textContent.trim();
                    autonomyAgentComposer.focus();
                });
            });
            autonomyPanel.querySelectorAll('[data-autonomy-proposal-action="review"]').forEach((button) => {
                button.addEventListener('click', () => autonomySelectStage('compare', {focus: true}));
            });
            autonomyPanel.querySelectorAll('[data-autonomy-attach-evidence]').forEach((button) => {
                button.addEventListener('click', () => {
                    autonomySelectStage('verify', {focus: false});
                    autonomyActivateRailTab('evidence');
                    autonomyOpenEvidenceRail(button);
                    if (autonomyContentMode === 'live') {
                        window.requestAnimationFrame(() => autonomyEvidenceFileInput?.focus());
                    }
                });
            });
            autonomyEvidenceReviewBtn?.addEventListener('click', () => {
                if (autonomyContentMode === 'live') return;
                const decision = autonomyPanel.querySelector('[name="autonomyEvidenceDecision"]:checked');
                const rationale = autonomyEvidenceRationale?.value.trim() || '';
                if (!decision || !rationale) {
                    if (autonomyEvidenceReviewError) {
                        autonomyEvidenceReviewError.hidden = false;
                        autonomyEvidenceReviewError.textContent = 'Choose accept or reject and enter a named rationale for the fixture evidence decision.';
                        autonomyEvidenceReviewError.focus();
                    }
                    return;
                }
                if (autonomyEvidenceReviewError) autonomyEvidenceReviewError.hidden = true;
                if (decision.value === 'accept') {
                    autonomySelectFixture('ready-to-confirm', {announce: false});
                    autonomySelectStage('compare', {focus: true, announce: false});
                    autonomyAnnounce('Fixture evidence accepted with rationale. Scenarios are ready for review; no record was saved.');
                } else {
                    autonomySelectFixture('evidence-conflict');
                }
            });
            autonomyEvidenceUploadForm?.addEventListener('submit', autonomyUploadEvidence);
            autonomySourceLockForm?.addEventListener('submit', autonomyLockCaseBasis);
            autonomyAnnualSourceSelect?.addEventListener('change', autonomyUpdateSourceLockButton);
            autonomyAnalysisBasisSelect?.addEventListener('change', autonomyUpdateSourceLockButton);
            autonomyLiveEvidenceList?.addEventListener('click', (event) => {
                const button = event.target instanceof Element
                    ? event.target.closest('[data-autonomy-evidence-delete]')
                    : null;
                if (button && autonomyContentMode === 'live') {
                    const approved = window.confirm('Remove this evidence only if it is unreferenced. The server will reject removal when a durable case receipt depends on it.');
                    if (approved) autonomyDeleteEvidence(button.dataset.autonomyEvidenceDelete);
                }
            });
            autonomyLiveEvidenceCandidates?.addEventListener('click', (event) => {
                const button = event.target instanceof Element
                    ? event.target.closest('[data-autonomy-candidate-review]')
                    : null;
                if (!button || autonomyContentMode !== 'live') return;
                autonomyReviewCandidate(button.closest('[data-evidence-id][data-candidate-id]'));
            });
            autonomyAgentThread?.addEventListener('click', (event) => {
                const source = event.target instanceof Element
                    ? event.target.closest('[data-autonomy-live-citation]')
                    : null;
                if (!source || autonomyContentMode !== 'live') return;
                autonomyActivateRailTab('evidence');
                autonomyOpenEvidenceRail(source);
            });
            autonomyPanel.querySelectorAll('[data-autonomy-rail-tab]').forEach((button) => {
                button.addEventListener('click', () => autonomyActivateRailTab(button.dataset.autonomyRailTab));
            });
            autonomyPanel.querySelectorAll('[data-autonomy-mobile-tab]').forEach((button) => {
                button.addEventListener('click', () => autonomySetMobileSection(button.dataset.autonomyMobileTab));
            });
            autonomyBindRovingTabs(
                Array.from(autonomyPanel.querySelectorAll('[data-autonomy-stage]')),
                (button) => autonomySelectStage(button.dataset.autonomyStage, {focus: false})
            );
            autonomyBindRovingTabs(
                Array.from(autonomyPanel.querySelectorAll('[data-autonomy-rail-tab]')),
                (button) => autonomyActivateRailTab(button.dataset.autonomyRailTab)
            );
            autonomyBindRovingTabs(
                Array.from(autonomyPanel.querySelectorAll('[data-autonomy-mobile-tab]')),
                (button) => autonomySetMobileSection(button.dataset.autonomyMobileTab, {announce: false})
            );
            autonomyBindRovingTabs(
                [autonomyInvestigationViewBtn, autonomyBriefViewBtn].filter(Boolean),
                (button) => autonomySetView(button === autonomyBriefViewBtn ? 'decision-brief' : 'investigation', {focus: false})
            );
            autonomyPanel.querySelectorAll('[data-autonomy-readiness]').forEach((button) => {
                button.addEventListener('click', () => {
                    const key = button.dataset.autonomyReadiness;
                    autonomyActivateRailTab(key === 'evidence' ? 'evidence' : 'readiness');
                    autonomyOpenEvidenceRail(button);
                });
            });
            autonomyOpenRailBtn?.addEventListener('click', () => autonomyOpenEvidenceRail(autonomyOpenRailBtn));
            autonomyCloseRailBtn?.addEventListener('click', () => autonomyCloseEvidenceRail());
            autonomyRailBackdrop?.addEventListener('click', () => autonomyCloseEvidenceRail());
            autonomyOpenConfirmationBtn?.addEventListener('click', () => autonomyOpenRunConfirmation(autonomyOpenConfirmationBtn));
            autonomyConfirmCancelBtn?.addEventListener('click', () => autonomyCloseDialog(autonomyConfirmDialog));
            autonomyConfirmSubmitBtn?.addEventListener('click', () => {
                const operator = autonomyConfirmOperator?.value.trim() || '';
                const accepted = !!autonomyConfirmAck?.checked;
                const selectedScenarios = autonomyConfirmDialog?.querySelectorAll('[data-autonomy-confirm-scenario]:checked').length || 0;
                if (autonomyFixtureId !== 'ready-to-confirm' || !operator || !accepted || selectedScenarios === 0) {
                    if (autonomyConfirmError) {
                        autonomyConfirmError.hidden = false;
                        autonomyConfirmError.textContent = autonomyFixtureId !== 'ready-to-confirm'
                            ? 'This fixture is not ready for grouped confirmation.'
                            : (selectedScenarios === 0
                                ? 'Select at least one fixture scenario before previewing queue state.'
                                : 'Enter the operator name and acknowledge the exact fixture request review.');
                        autonomyConfirmError.focus();
                    }
                    return;
                }
                if (autonomyConfirmError) autonomyConfirmError.hidden = true;
                autonomyCloseDialog(autonomyConfirmDialog);
                autonomySelectFixture('queued');
            });
            autonomyOpenPartialBriefBtn?.addEventListener('click', () => autonomySetView('decision-brief', {focus: true, announce: true}));
            autonomyOpenBriefBtn?.addEventListener('click', () => autonomySetView('decision-brief', {focus: true, announce: true}));
            autonomyPanel.querySelectorAll('[data-autonomy-open-brief]').forEach((button) => {
                button.addEventListener('click', () => autonomySetView('decision-brief', {focus: true, announce: true}));
            });
            autonomyReturnInvestigationBtn?.addEventListener('click', () => {
                autonomySelectedStage = autonomyCurrentFixture().superseded ? 'compare' : autonomyCurrentFixture().stage;
                autonomySyncMobileTabs(autonomySelectedStage === 'ask' ? 'ask' : 'scenarios');
                autonomySetView('investigation', {focus: true, announce: true, syncMobile: false});
                autonomyRenderStepper(autonomyCurrentFixture());
            });
            autonomyPrepareSignoffBtn?.addEventListener('click', () => autonomyOpenSignoff(autonomyPrepareSignoffBtn));
            autonomyPanel.querySelectorAll('[data-autonomy-prepare-signoff]').forEach((button) => {
                button.addEventListener('click', () => autonomyOpenSignoff(button));
            });
            autonomyPanel.querySelectorAll('[data-autonomy-brief-action]').forEach((button) => {
                button.addEventListener('click', () => {
                    const action = button.dataset.autonomyBriefAction;
                    if (action === 'test-reversal') {
                        autonomySelectStage('compare', {focus: true, announce: true});
                    } else if (action === 'open-evidence') {
                        autonomySelectStage('verify', {focus: false, announce: false});
                        autonomyActivateRailTab('evidence');
                        autonomyOpenEvidenceRail(button);
                    } else {
                        autonomyAnnounce('Fixture follow-up prepared. No network request was made.');
                    }
                });
            });
            autonomySignoffCancelBtn?.addEventListener('click', () => autonomyCloseDialog(autonomySignoffDialog));
            autonomySignoffSubmitBtn?.addEventListener('click', () => {
                const disposition = autonomyPanel.querySelector('[name="autonomyDisposition"]:checked');
                const owner = autonomySignoffOwner?.value.trim() || '';
                const rationale = autonomySignoffRationale?.value.trim() || '';
                const accepted = !!autonomySignoffAck?.checked;
                if (!autonomyCurrentFixture().signoffAllowed || !disposition || !owner || !rationale || !accepted) {
                    if (autonomySignoffError) {
                        autonomySignoffError.hidden = false;
                        autonomySignoffError.textContent = !autonomyCurrentFixture().signoffAllowed
                            ? 'This fixture is not ready for sign-off.'
                            : 'Choose a disposition, enter the owner and rationale, and acknowledge the immutable fixture snapshot.';
                        autonomySignoffError.focus();
                    }
                    return;
                }
                if (autonomySignoffError) autonomySignoffError.hidden = true;
                autonomySignedDecision = {disposition: disposition.value, owner, rationale};
                autonomyCloseDialog(autonomySignoffDialog);
                autonomySelectFixture('signed');
            });
            autonomyCreateRevisionBtn?.addEventListener('click', () => autonomySelectFixture('signed-superseded'));
            autonomyAgentSendBtn?.addEventListener('click', () => {
                if (autonomyContentMode === 'live') {
                    autonomySendLiveMessage();
                    return;
                }
                const question = autonomyAgentComposer?.value.trim() || '';
                if (!question) return autonomyAgentComposer?.focus();
                autonomyAgentAnswer.textContent = 'Fixture answer: the recommendation depends most on incremental transformer cost, maintenance, and the persistence of the modeled lifecycle-energy gain.';
                autonomyAgentBasis.textContent = 'Agent interpretation · fixture comparison bundle';
                autonomyAgentLimits.textContent = 'This response does not calculate a new threshold or queue a scenario.';
                autonomyAgentNextAction.textContent = 'Open Reversal conditions or create a controlled fixture revision.';
                autonomyAgentComposer.value = '';
                autonomyAnnounce('Fixture Decision Agent response updated.');
            });
            autonomyAgentComposer?.addEventListener('keydown', (event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    autonomyAgentSendBtn?.click();
                }
            });
            document.addEventListener('keydown', (event) => {
                if (event.key === 'Escape') {
                    const autonomyOpenModal = [autonomyConfirmDialog, autonomySignoffDialog]
                        .find((dialog) => dialog?.open);
                    if (autonomyOpenModal) {
                        event.preventDefault();
                        autonomyCloseDialog(autonomyOpenModal);
                        return;
                    }
                }
                if (event.key === 'Escape' && autonomyEvidenceRail?.classList.contains('is-open')) {
                    event.preventDefault();
                    autonomyCloseEvidenceRail();
                    return;
                }
                if (autonomyEvidenceRail?.classList.contains('is-open')) autonomyTrapFocus(event, autonomyEvidenceRail);
            });
            window.addEventListener('resize', () => {
                autonomyCloseEvidenceRail(false);
            });
            autonomyActivateRailTab(autonomySelectedRailTab);
            autonomySetMobileSection(autonomyMobileSection, {announce: false});
            autonomySetContentMode('live');
            autonomyRenderLiveWorkspace();
        }

        autonomyInitializeWorkspace();
