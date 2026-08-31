        const AUTONOMY_CASE_ID = 'case_sbe_hybrid_001';
        const AUTONOMY_CASE_REVISION = 'revision_003';
        const AUTONOMY_ANNUAL_SOURCE_ID = 'ann_2024_verified_017';
        const AUTONOMY_TEA_BASIS = 'SolarTAC site · tea-calculation-v3';
        const AUTONOMY_STAGES = Object.freeze(['ask', 'verify', 'compare', 'run', 'decide']);
        const AUTONOMY_READINESS_KEYS = Object.freeze(['calibration', 'annual', 'weather', 'evidence', 'agent']);
        const AUTONOMY_LIVE_STAGES = Object.freeze(['ask', 'verify', 'compare', 'run', 'decide']);
        const AUTONOMY_DECISION_BUILD_ACTIONS = Object.freeze(['build_comparison_bundle']);
        const AUTONOMY_DECISION_CREATE_ACTIONS = Object.freeze(['create_decision_brief']);
        const AUTONOMY_DECISION_REVERSAL_ACTIONS = Object.freeze(['test_reversal']);
        const AUTONOMY_SIGNOFF_ACTIONS = Object.freeze({
            accept: 'sign_accept',
            reject: 'sign_reject',
            defer: 'sign_defer',
        });
        const AUTONOMY_REPORT_ACTIONS = Object.freeze({
            draft: 'generate_draft_report',
            final: 'generate_final_report',
            verify: 'verify_report',
            download: 'download_report',
        });
        const AUTONOMY_TERMINAL_TEA_STATES = Object.freeze(['done', 'error', 'cancelled', 'interrupted']);
        const AUTONOMY_ACTIVE_TEA_STATES = Object.freeze(['queued', 'leased', 'running']);
        const AUTONOMY_GROUPED_TEA_ACKNOWLEDGEMENT = 'I confirm the selected scenarios, source and basis lock, evidence status, realization count, seed, and exact request hashes shown here. I understand the production action would create immutable TEA jobs for sequential worker execution.';
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
        const autonomyConfirmDescription = document.getElementById('autonomyConfirmDescription');
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
        const autonomyFixtureToolbar = document.getElementById('autonomyFixtureToolbar');
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
        const autonomyCreateBaselineBtn = document.getElementById('autonomyCreateBaselineBtn');
        const autonomyCreateAlternativeBtn = document.getElementById('autonomyCreateAlternativeBtn');
        const autonomyScenarioLocks = document.getElementById('autonomyScenarioLocks');
        const autonomyScenarioStatus = document.getElementById('autonomyScenarioStatus');
        const autonomyScenarioEmpty = document.getElementById('autonomyScenarioEmpty');
        const autonomyLiveScenarioGrid = document.getElementById('autonomyLiveScenarioGrid');
        const autonomyLiveScenarioMatrix = document.getElementById('autonomyLiveScenarioMatrix');
        const autonomyScenarioMatrixHead = document.getElementById('autonomyScenarioMatrixHead');
        const autonomyScenarioMatrixBody = document.getElementById('autonomyScenarioMatrixBody');
        const autonomyLiveScenarioMobileList = document.getElementById('autonomyLiveScenarioMobileList');
        const autonomyComparisonSummary = document.getElementById('autonomyComparisonSummary');
        const autonomyLiveAssumptions = document.getElementById('autonomyLiveAssumptions');
        const autonomyOpenLiveConfirmationBtn = document.getElementById('autonomyOpenLiveConfirmationBtn');
        const autonomyLiveRunGateHelp = document.getElementById('autonomyLiveRunGateHelp');
        const autonomyExecutionSummary = document.getElementById('autonomyExecutionSummary');
        const autonomyExecutionQueueState = document.getElementById('autonomyExecutionQueueState');
        const autonomyLiveJobList = document.getElementById('autonomyLiveJobList');
        const autonomyLivePartialResultsBanner = document.getElementById('autonomyLivePartialResultsBanner');
        const autonomyLiveResultsReadyBanner = document.getElementById('autonomyLiveResultsReadyBanner');
        const autonomyConfirmEyebrow = document.getElementById('autonomyConfirmEyebrow');
        const autonomyLiveConfirmLocks = document.getElementById('autonomyLiveConfirmLocks');
        const autonomyLiveConfirmScenarioRows = document.getElementById('autonomyLiveConfirmScenarioRows');
        const autonomyLiveConfirmWarnings = document.getElementById('autonomyLiveConfirmWarnings');
        const autonomyConfirmRationale = document.getElementById('autonomyConfirmRationale');
        const autonomyConfirmAckCopy = document.getElementById('autonomyConfirmAckCopy');
        const autonomyConfirmRevision = document.getElementById('autonomyConfirmRevision');
        const autonomyScenarioDialog = document.getElementById('autonomyScenarioDialog');
        const autonomyScenarioForm = document.getElementById('autonomyScenarioForm');
        const autonomyScenarioDialogHeading = document.getElementById('autonomyScenarioDialogHeading');
        const autonomyScenarioDialogDescription = document.getElementById('autonomyScenarioDialogDescription');
        const autonomyScenarioLabel = document.getElementById('autonomyScenarioLabel');
        const autonomyScenarioKind = document.getElementById('autonomyScenarioKind');
        const autonomyScenarioChangedFields = document.getElementById('autonomyScenarioChangedFields');
        const autonomyScenarioRequest = document.getElementById('autonomyScenarioRequest');
        const autonomyScenarioEvidenceReferences = document.getElementById('autonomyScenarioEvidenceReferences');
        const autonomyScenarioReasonField = document.getElementById('autonomyScenarioReasonField');
        const autonomyScenarioReason = document.getElementById('autonomyScenarioReason');
        const autonomyScenarioError = document.getElementById('autonomyScenarioError');
        const autonomyScenarioCancelBtn = document.getElementById('autonomyScenarioCancelBtn');
        const autonomyScenarioSubmitBtn = document.getElementById('autonomyScenarioSubmitBtn');
        const autonomyFixtureDecisionBrief = document.getElementById('autonomyFixtureDecisionBrief');
        const autonomyLiveDecisionBrief = document.getElementById('autonomyLiveDecisionBrief');
        const autonomyLiveBriefHeading = document.getElementById('autonomyLiveBriefHeading');
        const autonomyLiveBriefSummary = document.getElementById('autonomyLiveBriefSummary');
        const autonomyLiveBriefState = document.getElementById('autonomyLiveBriefState');
        const autonomyLiveBriefStateHeading = document.getElementById('autonomyLiveBriefStateHeading');
        const autonomyLiveBriefStateCopy = document.getElementById('autonomyLiveBriefStateCopy');
        const autonomyLiveBriefAgentNotice = document.getElementById('autonomyLiveBriefAgentNotice');
        const autonomyLiveBriefBlockers = document.getElementById('autonomyLiveBriefBlockers');
        const autonomyLiveBundleSelect = document.getElementById('autonomyLiveBundleSelect');
        const autonomyLiveConfirmationSelect = document.getElementById('autonomyLiveConfirmationSelect');
        const autonomyLiveBriefSelect = document.getElementById('autonomyLiveBriefSelect');
        const autonomyLiveBuildComparisonBtn = document.getElementById('autonomyLiveBuildComparisonBtn');
        const autonomyLiveCreateBriefBtn = document.getElementById('autonomyLiveCreateBriefBtn');
        const autonomyLiveReturnToCompareBtn = document.getElementById('autonomyLiveReturnToCompareBtn');
        const autonomyLiveDecideBuildBtn = document.getElementById('autonomyLiveDecideBuildBtn');
        const autonomyLiveDecideOpenBtn = document.getElementById('autonomyLiveDecideOpenBtn');
        const autonomyLiveDecideSummary = document.getElementById('autonomyLiveDecideSummary');
        const autonomyLiveRecommendation = document.getElementById('autonomyLiveRecommendation');
        const autonomyLiveRecommendationHeading = document.getElementById('autonomyLiveRecommendationHeading');
        const autonomyLiveRecommendationConfidence = document.getElementById('autonomyLiveRecommendationConfidence');
        const autonomyLiveRecommendationCopy = document.getElementById('autonomyLiveRecommendationCopy');
        const autonomyLiveAskWhyBtn = document.getElementById('autonomyLiveAskWhyBtn');
        const autonomyLiveTestReversalBtn = document.getElementById('autonomyLiveTestReversalBtn');
        const autonomyLiveWhyPanel = document.getElementById('autonomyLiveWhyPanel');
        const autonomyLiveDecisiveEvidence = document.getElementById('autonomyLiveDecisiveEvidence');
        const autonomyLiveMajorDrivers = document.getElementById('autonomyLiveMajorDrivers');
        const autonomyLiveImportantUncertainty = document.getElementById('autonomyLiveImportantUncertainty');
        const autonomyLiveModelLimits = document.getElementById('autonomyLiveModelLimits');
        const autonomyLiveBriefScenarioRows = document.getElementById('autonomyLiveBriefScenarioRows');
        const autonomyLiveRequestMatrix = document.getElementById('autonomyLiveRequestMatrix');
        const autonomyLiveMetricRows = document.getElementById('autonomyLiveMetricRows');
        const autonomyLiveJointOutcomeRows = document.getElementById('autonomyLiveJointOutcomeRows');
        const autonomyLiveSensitivityRows = document.getElementById('autonomyLiveSensitivityRows');
        const autonomyLiveQualityRows = document.getElementById('autonomyLiveQualityRows');
        const autonomyLiveEvidenceCaveats = document.getElementById('autonomyLiveEvidenceCaveats');
        const autonomyLiveReversalRows = document.getElementById('autonomyLiveReversalRows');
        const autonomyLiveBriefProvenance = document.getElementById('autonomyLiveBriefProvenance');
        const autonomyLiveBriefTimeline = document.getElementById('autonomyLiveBriefTimeline');
        const autonomyLiveSignoffPanel = document.getElementById('autonomyLiveSignoffPanel');
        const autonomyLiveSignoffHeading = document.getElementById('autonomyLiveSignoffHeading');
        const autonomyLiveSignoffSummary = document.getElementById('autonomyLiveSignoffSummary');
        const autonomyLiveSignoffStatus = document.getElementById('autonomyLiveSignoffStatus');
        const autonomyLiveSignoffBlockers = document.getElementById('autonomyLiveSignoffBlockers');
        const autonomyLiveAcceptBtn = document.getElementById('autonomyLiveAcceptBtn');
        const autonomyLiveRejectBtn = document.getElementById('autonomyLiveRejectBtn');
        const autonomyLiveDeferBtn = document.getElementById('autonomyLiveDeferBtn');
        const autonomyLiveSignoffReceipt = document.getElementById('autonomyLiveSignoffReceipt');
        const autonomyLiveSignoffReceiptDetails = document.getElementById('autonomyLiveSignoffReceiptDetails');
        const autonomyLiveSignoffHistoryRows = document.getElementById('autonomyLiveSignoffHistoryRows');
        const autonomyLiveReportPanel = document.getElementById('autonomyLiveReportPanel');
        const autonomyLiveReportSummary = document.getElementById('autonomyLiveReportSummary');
        const autonomyLiveReportStatus = document.getElementById('autonomyLiveReportStatus');
        const autonomyLiveReportBlockers = document.getElementById('autonomyLiveReportBlockers');
        const autonomyLiveDraftReportBtn = document.getElementById('autonomyLiveDraftReportBtn');
        const autonomyLiveFinalReportBtn = document.getElementById('autonomyLiveFinalReportBtn');
        const autonomyLiveReportRows = document.getElementById('autonomyLiveReportRows');
        const autonomyLiveTechnicalExports = document.getElementById('autonomyLiveTechnicalExports');
        const autonomyLiveRolloutDetails = document.getElementById('autonomyLiveRolloutDetails');
        const autonomyLiveSignoffDialog = document.getElementById('autonomyLiveSignoffDialog');
        const autonomyLiveSignoffSnapshot = document.getElementById('autonomyLiveSignoffSnapshot');
        const autonomyLiveSignoffOwner = document.getElementById('autonomyLiveSignoffOwner');
        const autonomyLiveSignoffRationale = document.getElementById('autonomyLiveSignoffRationale');
        const autonomyLiveSignoffAck = document.getElementById('autonomyLiveSignoffAck');
        const autonomyLiveSignoffAckCopy = document.getElementById('autonomyLiveSignoffAckCopy');
        const autonomyLiveWarningAcknowledgements = document.getElementById('autonomyLiveWarningAcknowledgements');
        const autonomyLiveWarningAcknowledgementList = document.getElementById('autonomyLiveWarningAcknowledgementList');
        const autonomyLiveSignoffError = document.getElementById('autonomyLiveSignoffError');
        const autonomyLiveSignoffCancelBtn = document.getElementById('autonomyLiveSignoffCancelBtn');
        const autonomyLiveSignoffSubmitBtn = document.getElementById('autonomyLiveSignoffSubmitBtn');

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
        let autonomyLiveScenarios = [];
        let autonomyLiveComparison = null;
        let autonomyLiveExecution = null;
        let autonomyLiveAllowedActions = [];
        let autonomyDecisionAllowedActions = [];
        let autonomyAuthorityAllowedActions = [];
        let autonomyDecisionBlockers = [];
        let autonomyLiveComparisonBundles = [];
        let autonomyLiveComparisonBundle = null;
        let autonomyLiveBriefs = [];
        let autonomyLiveBrief = null;
        let autonomyLiveSignoffs = [];
        let autonomyLiveReports = [];
        let autonomyLiveReleaseReadiness = null;
        let autonomyLiveSignoffBlockerRecords = [];
        let autonomyLiveReportBlockerRecords = [];
        let autonomyDecisionLoadRevision = 0;
        let autonomyDecisionAbortController = null;
        let autonomyDecisionLoadError = null;
        let autonomyDecisionBuildInFlight = false;
        let autonomyBriefCreateInFlight = false;
        let autonomyBriefCreationIdempotencyKey = null;
        let autonomyBriefCreationSignature = '';
        let autonomyLiveSignoffInFlight = false;
        let autonomyLiveSignoffIdempotencyKey = null;
        let autonomyLiveSignoffSignature = '';
        let autonomyLiveReportGenerationKind = '';
        let autonomyLiveReportIdempotencyKeys = new Map();
        let autonomyLiveReportVerificationInFlight = new Set();
        let autonomyBriefReturnContext = null;
        let autonomyLastAnnouncedDecisionState = '';
        let autonomyEligibleAnnualSources = [];
        let autonomySupportedAnalysisBases = [];
        let autonomyWorkspaceOpenPromise = null;
        let autonomyPendingTurn = null;
        let autonomyStreamAbortController = null;
        let autonomyStreamReconnectAttempts = 0;
        let autonomyLiveAgentAvailable = true;
        let autonomyScenarioLoadRevision = 0;
        let autonomyScenarioAbortController = null;
        let autonomyCaseLoadRevision = 0;
        let autonomyCaseAbortController = null;
        let autonomyDesiredCaseId = '';
        let autonomyExecutionPollRevision = 0;
        let autonomyExecutionPollTimer = null;
        let autonomyExecutionAbortController = null;
        let autonomyExecutionPollFailures = 0;
        let autonomySelectedScenarioRevisions = new Map();
        let autonomyScenarioDialogMode = 'create';
        let autonomyScenarioDialogTarget = null;
        let autonomyConfirmationIdempotencyKey = null;
        let autonomyConfirmationCaseRevision = null;
        let autonomyConfirmationSubmittedSignature = null;
        let autonomyConfirmationInFlight = false;
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
            if (autonomyContentMode === 'fixture') {
                autonomyInvalidateExecutionPoll();
                autonomyScenarioLoadRevision += 1;
                if (autonomyScenarioAbortController) autonomyScenarioAbortController.abort();
                autonomyScenarioAbortController = null;
                autonomyDecisionLoadRevision += 1;
                if (autonomyDecisionAbortController) autonomyDecisionAbortController.abort();
                autonomyDecisionAbortController = null;
            } else if (autonomyLiveStatus) {
                // Fixture announcements must never survive into a restored live case.
                autonomyLiveStatus.textContent = '';
            }
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
                error.payload = data;
                error.detail = detail;
                error.fieldErrors = Array.isArray(detail)
                    ? detail.map((item) => ({
                        path: Array.isArray(item?.loc)
                            ? '/' + item.loc.filter((part) => part !== 'body').join('/')
                            : '',
                        code: item?.type || 'invalid_field',
                        message: item?.msg || 'Invalid request field.',
                    }))
                    : ((detail && typeof detail === 'object' && Array.isArray(detail.field_errors))
                        ? detail.field_errors
                        : (Array.isArray(data.field_errors) ? data.field_errors : []));
                error.blockers = (detail && typeof detail === 'object' && Array.isArray(detail.blockers))
                    ? detail.blockers
                    : (Array.isArray(data.blockers) ? data.blockers : []);
                error.violatedRules = detail && typeof detail === 'object'
                    ? detail.violated_rules || detail.violated_contract_rules || []
                    : data.violated_rules || data.violated_contract_rules || [];
                error.closestSupportedAlternatives = detail && typeof detail === 'object'
                    ? detail.closest_supported_alternatives || detail.closest_supported_alternative || []
                    : data.closest_supported_alternatives || [];
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

        function autonomyScenarioId(value) {
            const textValue = String(value || '');
            return /^dsc_[A-Za-z0-9]+$/.test(textValue) ? textValue : '';
        }

        function autonomyScenarioRevisionId(value) {
            const textValue = String(value || '');
            return /^dscr_[A-Za-z0-9]+$/.test(textValue) ? textValue : '';
        }

        function autonomyTeaJobId(value) {
            const textValue = String(value || '');
            return /^tea_[A-Za-z0-9_-]+$/.test(textValue) && textValue.length <= 128 ? textValue : '';
        }

        function autonomyConfirmationId(value) {
            const textValue = String(value || '');
            return /^dconf_[A-Za-z0-9]+$/.test(textValue) ? textValue : '';
        }

        function autonomyComparisonBundleId(value) {
            const textValue = String(value || '');
            return /^dcmp_[A-Za-z0-9]+$/.test(textValue) ? textValue : '';
        }

        function autonomyBriefRevisionId(value) {
            const textValue = String(value || '');
            return /^dbr_[A-Za-z0-9]+$/.test(textValue) ? textValue : '';
        }

        function autonomySignoffId(value) {
            const textValue = String(value || '');
            return /^dsgn_[A-Za-z0-9]+$/.test(textValue) ? textValue : '';
        }

        function autonomyReportId(value) {
            const textValue = String(value || '');
            return /^drpt_[A-Za-z0-9]+$/.test(textValue) ? textValue : '';
        }

        function autonomyExpectedCaseRevision() {
            const revision = Number(autonomyLiveCase?.revision);
            return Number.isInteger(revision) && revision >= 1 ? revision : null;
        }

        function autonomyPlainObject(value) {
            return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
        }

        function autonomyActionEntries(value) {
            return (Array.isArray(value) ? value : []).filter((entry) => (
                typeof entry === 'string' || (entry && typeof entry === 'object')
            ));
        }

        function autonomyActionIsAllowed(actionId, record = null) {
            const scoped = autonomyActionEntries(record?.allowed_actions).filter((action) => (
                (typeof action === 'string' ? action : action.id) === actionId
            ));
            const records = scoped.length ? scoped : autonomyActionEntries(autonomyLiveAllowedActions);
            return records.some((action) => {
                const id = typeof action === 'string' ? action : action.id;
                if (id !== actionId || action?.enabled === false) return false;
                const scopedScenarioId = typeof action === 'object' ? autonomyScenarioId(action.scenario_id) : '';
                const scopedJobId = typeof action === 'object' ? autonomyTeaJobId(action.tea_job_id || action.job_id) : '';
                if (scopedScenarioId && scopedScenarioId !== autonomyScenarioId(record?.scenario_id)) return false;
                if (scopedJobId && scopedJobId !== autonomyTeaJobId(record?.tea_job_id || record?.job_id || record?.id)) return false;
                return true;
            });
        }

        function autonomyActionDisabledReason(actionId, record = null) {
            const scoped = autonomyActionEntries(record?.allowed_actions).filter((entry) => (
                (typeof entry === 'string' ? entry : entry.id) === actionId
            ));
            const actions = scoped.length ? scoped : autonomyActionEntries(autonomyLiveAllowedActions);
            const action = actions.find((entry) => (
                typeof entry === 'object' && entry.id === actionId && entry.enabled === false
            ));
            return action?.disabled_reason || action?.reason || '';
        }

        function autonomyCollectAllowedActions(...payloads) {
            let entries = [];
            payloads.forEach((payload) => {
                const next = [
                    ...autonomyActionEntries(payload?.allowed_actions),
                    ...autonomyActionEntries(payload?.allowed_case_actions),
                ];
                if (next.length) entries = next;
            });
            autonomyLiveAllowedActions = entries;
        }

        function autonomyCollectDecisionAllowedActions(...payloads) {
            const byId = new Map();
            let authoritativePayloadSeen = false;
            payloads.forEach((payload) => {
                if (!payload || !Object.prototype.hasOwnProperty.call(payload, 'decision_allowed_actions')) return;
                authoritativePayloadSeen = true;
                autonomyActionEntries(payload?.decision_allowed_actions).forEach((action) => {
                    const id = typeof action === 'string' ? action : action.id;
                    const scope = action && typeof action === 'object'
                        ? String(action.brief_revision_id || action.report_id || '')
                        : '';
                    if (id) byId.set(id + '|' + scope, action);
                });
            });
            if (authoritativePayloadSeen) autonomyDecisionAllowedActions = Array.from(byId.values());
        }

        function autonomyCollectAuthorityAllowedActions(...payloads) {
            const byId = new Map();
            let authoritativePayloadSeen = false;
            payloads.forEach((payload) => {
                ['signoff_allowed_actions', 'report_allowed_actions'].forEach((key) => {
                    if (!payload || !Object.prototype.hasOwnProperty.call(payload, key)) return;
                    authoritativePayloadSeen = true;
                    autonomyActionEntries(payload[key]).forEach((action) => {
                        const id = typeof action === 'string' ? action : action.id;
                        const scope = action && typeof action === 'object'
                            ? String(action.brief_revision_id || action.report_id || '')
                            : '';
                        if (id) byId.set(id + '|' + scope, action);
                    });
                });
            });
            if (authoritativePayloadSeen) autonomyAuthorityAllowedActions = Array.from(byId.values());
        }

        function autonomyDecisionActionIsAllowed(actionIds) {
            const expected = new Set(Array.isArray(actionIds) ? actionIds : [actionIds]);
            return autonomyActionEntries(autonomyDecisionAllowedActions).some((action) => {
                const id = typeof action === 'string' ? action : action.id;
                return expected.has(id) && action?.enabled !== false;
            });
        }

        function autonomyDecisionActionDisabledReason(actionIds) {
            const expected = new Set(Array.isArray(actionIds) ? actionIds : [actionIds]);
            const action = autonomyActionEntries(autonomyDecisionAllowedActions).find((entry) => (
                typeof entry === 'object' && expected.has(entry.id) && entry.enabled === false
            ));
            return String(action?.disabled_reason || action?.reason || '');
        }

        function autonomyDecisionEnabledAction(actionIds) {
            const expected = new Set(Array.isArray(actionIds) ? actionIds : [actionIds]);
            return autonomyActionEntries(autonomyDecisionAllowedActions).find((entry) => (
                entry && typeof entry === 'object' && expected.has(entry.id) && entry.enabled !== false
            )) || null;
        }

        function autonomyDecisionScopedAction(actionId, scope = {}, record = null) {
            const recordActions = autonomyActionEntries(record?.allowed_actions);
            const actions = recordActions.length ? recordActions : [
                ...autonomyActionEntries(autonomyAuthorityAllowedActions),
                ...autonomyActionEntries(autonomyDecisionAllowedActions),
            ];
            return actions.find((entry) => {
                const id = typeof entry === 'string' ? entry : entry?.id;
                if (id !== actionId || entry?.enabled === false) return false;
                if (!entry || typeof entry !== 'object') return false;
                return Object.entries(scope).every(([key, expectedValue]) => {
                    if (!expectedValue || !Object.prototype.hasOwnProperty.call(entry, key)) return false;
                    return String(entry[key]) === String(expectedValue);
                });
            }) || null;
        }

        function autonomyDecisionScopedActionIsAllowed(actionId, scope = {}, record = null) {
            return Boolean(autonomyDecisionScopedAction(actionId, scope, record));
        }

        function autonomyDecisionScopedDisabledReason(actionId, scope = {}, record = null) {
            const recordActions = autonomyActionEntries(record?.allowed_actions);
            const actions = recordActions.length ? recordActions : [
                ...autonomyActionEntries(autonomyAuthorityAllowedActions),
                ...autonomyActionEntries(autonomyDecisionAllowedActions),
            ];
            const action = actions.find((entry) => {
                if (!entry || typeof entry !== 'object' || entry.id !== actionId || entry.enabled !== false) return false;
                return Object.entries(scope).every(([key, expectedValue]) => (
                    !expectedValue || !Object.prototype.hasOwnProperty.call(entry, key)
                    || String(entry[key]) === String(expectedValue)
                ));
            });
            return String(action?.disabled_reason || action?.reason || '');
        }

        function autonomySelectedBundleMatchesCreateAction() {
            const action = autonomyDecisionEnabledAction(AUTONOMY_DECISION_CREATE_ACTIONS);
            const actionBundleId = autonomyComparisonBundleId(action?.comparison_bundle_id);
            const actionBundleHash = String(action?.bundle_sha256 || '');
            const selectedBundleId = autonomyDecisionBundleRecordId(autonomyLiveComparisonBundle);
            const selectedBundleHash = String(autonomyLiveComparisonBundle?.bundle_sha256 || '');
            return Boolean(
                actionBundleId
                && /^[0-9a-f]{64}$/.test(actionBundleHash)
                && selectedBundleId === actionBundleId
                && selectedBundleHash === actionBundleHash
            );
        }

        function autonomyCanOpenLiveBrief() {
            return autonomyDecisionActionIsAllowed('open_decision_brief');
        }

        function autonomyCanSelectLiveStage(stage) {
            return AUTONOMY_LIVE_STAGES.includes(stage)
                && (stage !== 'decide' || autonomyCanOpenLiveBrief());
        }

        function autonomyExecutionConfirmationId() {
            const selectedConfirmationId = autonomyConfirmationId(autonomyLiveConfirmationSelect?.value);
            if (selectedConfirmationId) return selectedConfirmationId;
            const buildAction = autonomyActionEntries(autonomyDecisionAllowedActions).find((action) => (
                typeof action === 'object' && action.id === 'build_comparison_bundle'
            ));
            const actionConfirmationIds = Array.isArray(buildAction?.confirmation_ids)
                ? buildAction.confirmation_ids.map(autonomyConfirmationId).filter(Boolean)
                : [];
            const actionConfirmation = actionConfirmationIds.length === 1
                ? actionConfirmationIds[0]
                : '';
            if (actionConfirmation) return actionConfirmation;
            const confirmation = autonomyPlainObject(
                autonomyLiveExecution?.confirmation || autonomyLiveExecution?.confirmation_receipt
            );
            return autonomyConfirmationId(
                confirmation.confirmation_id
                || confirmation.id
                || autonomyLiveExecution?.confirmation_id
            );
        }

        function autonomyResetDecisionWorkspace() {
            autonomyDecisionLoadRevision += 1;
            if (autonomyDecisionAbortController) autonomyDecisionAbortController.abort();
            autonomyDecisionAbortController = null;
            autonomyDecisionLoadError = null;
            autonomyDecisionAllowedActions = [];
            autonomyAuthorityAllowedActions = [];
            autonomyDecisionBlockers = [];
            autonomyLiveComparisonBundles = [];
            autonomyLiveComparisonBundle = null;
            autonomyLiveBriefs = [];
            autonomyLiveBrief = null;
            autonomyLiveSignoffs = [];
            autonomyLiveReports = [];
            autonomyLiveReleaseReadiness = null;
            autonomyLiveSignoffBlockerRecords = [];
            autonomyLiveReportBlockerRecords = [];
            autonomyDecisionBuildInFlight = false;
            autonomyBriefCreateInFlight = false;
            autonomyBriefCreationIdempotencyKey = null;
            autonomyBriefCreationSignature = '';
            autonomyLiveSignoffInFlight = false;
            autonomyLiveSignoffIdempotencyKey = null;
            autonomyLiveSignoffSignature = '';
            autonomyLiveReportGenerationKind = '';
            autonomyLiveReportIdempotencyKeys.clear();
            autonomyLiveReportVerificationInFlight.clear();
            autonomyBriefReturnContext = null;
            autonomyLastAnnouncedDecisionState = '';
            if (autonomyLiveWhyPanel) autonomyLiveWhyPanel.hidden = true;
            if (autonomyLiveAskWhyBtn) autonomyLiveAskWhyBtn.setAttribute('aria-expanded', 'false');
        }

        function autonomyScenarioValidation(scenario) {
            return autonomyPlainObject(scenario?.validation || scenario?.validation_result);
        }

        function autonomyScenarioIsValidated(scenario) {
            const validation = autonomyScenarioValidation(scenario);
            return scenario?.draft_status === 'validated'
                || scenario?.draft_status === 'confirmed'
                || validation.valid === true
                || validation.status === 'valid'
                || validation.status === 'validated';
        }

        function autonomyScenarioIsSelectable(scenario) {
            return autonomyActionIsAllowed('select_for_confirmation', scenario);
        }

        function autonomyScenarioRevisionKey(scenario) {
            return [
                autonomyScenarioId(scenario?.scenario_id),
                Number(scenario?.revision) || 0,
                String(scenario?.request_sha256 || ''),
            ].join(':');
        }

        function autonomyScenarioDifferences(scenario) {
            if (scenario?.kind === 'baseline') return [];
            const raw = scenario?.exact_differences || scenario?.differences || [];
            if (Array.isArray(raw) && raw.length) {
                return raw.map((item) => {
                    if (typeof item === 'string') return {
                        field: item, baselinePresent: false, baseline: null,
                        valuePresent: true, value: item, baselineKind: 'input', valueKind: 'hypothesis', display: item,
                    };
                    const value = autonomyPlainObject(item);
                    const hasBaselineValue = Object.prototype.hasOwnProperty.call(value, 'baseline_value');
                    const hasScenarioValue = Object.prototype.hasOwnProperty.call(value, 'scenario_value');
                    const baselineRecord = autonomyPlainObject(value.baseline);
                    const scenarioRecord = autonomyPlainObject(value.scenario);
                    const hasNestedBaselineValue = Object.prototype.hasOwnProperty.call(baselineRecord, 'value');
                    const hasNestedScenarioValue = Object.prototype.hasOwnProperty.call(scenarioRecord, 'value');
                    const explicitBaselinePresent = value.baseline_present ?? baselineRecord.present;
                    const explicitScenarioPresent = value.scenario_present ?? scenarioRecord.present;
                    return {
                        field: String(value.field || value.path || value.request_path || 'Input'),
                        baselinePresent: typeof explicitBaselinePresent === 'boolean'
                            ? explicitBaselinePresent
                            : (hasBaselineValue || Object.prototype.hasOwnProperty.call(value, 'baseline')),
                        baseline: hasBaselineValue ? value.baseline_value
                            : (hasNestedBaselineValue ? baselineRecord.value : value.baseline),
                        valuePresent: typeof explicitScenarioPresent === 'boolean'
                            ? explicitScenarioPresent
                            : (hasScenarioValue
                                || hasNestedScenarioValue
                                || Object.prototype.hasOwnProperty.call(value, 'value')),
                        value: hasScenarioValue ? value.scenario_value
                            : (hasNestedScenarioValue ? scenarioRecord.value
                                : (Object.prototype.hasOwnProperty.call(value, 'value') ? value.value : value.current)),
                        baselineKind: value.baseline_kind || baselineRecord.value_kind || 'input',
                        valueKind: value.value_kind || scenarioRecord.value_kind || 'hypothesis',
                        display: String(value.exact_difference || value.display || value.summary || ''),
                    };
                });
            }
            const objectDifferences = Object.entries(autonomyPlainObject(raw)).map(([field, value]) => {
                const detail = autonomyPlainObject(value);
                const hasBaselineValue = Object.prototype.hasOwnProperty.call(detail, 'baseline_value');
                const hasScenarioValue = Object.prototype.hasOwnProperty.call(detail, 'scenario_value');
                const explicitBaselinePresent = detail.baseline_present;
                const explicitScenarioPresent = detail.scenario_present;
                return {
                    field,
                    baselinePresent: typeof explicitBaselinePresent === 'boolean'
                        ? explicitBaselinePresent
                        : (hasBaselineValue || Object.prototype.hasOwnProperty.call(detail, 'baseline')),
                    baseline: hasBaselineValue ? detail.baseline_value : detail.baseline,
                    valuePresent: typeof explicitScenarioPresent === 'boolean'
                        ? explicitScenarioPresent
                        : (hasScenarioValue || Object.prototype.hasOwnProperty.call(detail, 'value')),
                    value: hasScenarioValue ? detail.scenario_value
                        : (Object.prototype.hasOwnProperty.call(detail, 'value') ? detail.value : value),
                    baselineKind: detail.baseline_kind || 'input',
                    valueKind: detail.value_kind || 'hypothesis',
                    display: String(detail.exact_difference || detail.display || detail.summary || ''),
                };
            });
            if (objectDifferences.length) return objectDifferences;
            const scenarioId = autonomyScenarioId(scenario?.scenario_id);
            const matrix = Array.isArray(autonomyLiveComparison?.difference_matrix)
                ? autonomyLiveComparison.difference_matrix : [];
            return matrix.reduce((items, row) => {
                const field = String(row?.path || row?.field || 'Input');
                const cell = (Array.isArray(row?.alternatives) ? row.alternatives : [])
                    .find((candidate) => autonomyScenarioId(candidate?.scenario_id) === scenarioId);
                if (cell?.changed) items.push({
                    field,
                    baselinePresent: typeof row?.baseline?.present === 'boolean'
                        ? row.baseline.present
                        : Object.prototype.hasOwnProperty.call(autonomyPlainObject(row?.baseline), 'value'),
                    baseline: row?.baseline?.value,
                    valuePresent: typeof cell.present === 'boolean'
                        ? cell.present
                        : Object.prototype.hasOwnProperty.call(cell, 'value'),
                    value: cell.value,
                    baselineKind: row?.baseline?.value_kind || 'input',
                    valueKind: cell.value_kind || 'hypothesis',
                    display: '',
                });
                return items;
            }, []);
        }

        function autonomyDisplayValue(value, present = true) {
            if (present === false) return 'Missing';
            if (value === null) return 'null';
            if (value === undefined) return 'Missing';
            if (value === '') return 'Empty string';
            if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
            try {
                return JSON.stringify(value);
            } catch (_) {
                return 'Structured input';
            }
        }

        function autonomyExactDifferenceText(difference) {
            if (difference?.display) return difference.display;
            const baselineKind = String(difference?.baselineKind || 'input');
            const valueKind = String(difference?.valueKind || 'hypothesis');
            return baselineKind + ': ' + autonomyDisplayValue(difference?.baseline, difference?.baselinePresent)
                + ' → ' + valueKind + ': ' + autonomyDisplayValue(difference?.value, difference?.valuePresent);
        }

        function autonomyNewIdempotencyKey(prefix = 'confirm') {
            const uuid = window.crypto?.randomUUID
                ? window.crypto.randomUUID().replace(/-/g, '')
                : Date.now().toString(36) + Math.random().toString(36).slice(2);
            return prefix + '_' + uuid;
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
            if (autonomyCanOpenLiveBrief()) return 'decide';
            const jobs = autonomyExecutionJobs({latestOnly: true});
            if (jobs.length || autonomyLiveExecution?.confirmation || autonomyLiveExecution?.confirmation_receipt) return 'run';
            if (autonomyLiveScenarios.length) return 'compare';
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
            autonomySelectedStage = autonomyCanSelectLiveStage(autonomySelectedStage)
                ? autonomySelectedStage
                : autonomyLiveDefaultStage();
            const liveStageState = autonomyNormalizeReadinessStatus(autonomyLiveReadiness?.overall_status);
            autonomyRenderStepper({
                stage: autonomyLiveDefaultStage(),
                stageState: liveStageState === 'passed' ? 'current' : liveStageState,
                signed: false,
            });
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
                    ? 'Ask, evidence review, deterministic scenario validation, and confirmed execution use the durable case state shown here.'
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
                await autonomyLoadDecisionWorkspace();
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
                await autonomyLoadDecisionWorkspace();
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
                await autonomyLoadScenarioWorkspace();
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

        function autonomyScenarioRequestScale(scenario = autonomyLiveScenarios.find((item) => !item.audit_only && item.kind === 'baseline')
            || autonomyLiveScenarios.find((item) => !item.audit_only)) {
            const request = autonomyPlainObject(scenario?.request);
            const uncertainty = autonomyPlainObject(request.uncertainty);
            const simulation = autonomyPlainObject(request.simulation);
            return {
                realizations: autonomyLiveComparison?.realization_count
                    ?? autonomyLiveComparison?.run_controls?.realization_count?.value
                    ?? request.realizations ?? request.realization_count
                    ?? request.n ?? request.n_realizations ?? uncertainty.realizations
                    ?? simulation.realizations ?? 'Not recorded',
                seed: autonomyLiveComparison?.seed
                    ?? autonomyLiveComparison?.run_controls?.seed?.value
                    ?? request.seed ?? request.random_seed ?? uncertainty.seed
                    ?? simulation.seed ?? 'Not recorded',
            };
        }

        function autonomyAppendLock(container, label, value, code = false) {
            if (!container) return;
            const item = autonomyNode('div');
            item.appendChild(autonomyNode('span', {text: label}));
            item.appendChild(autonomyNode(code ? 'code' : 'strong', {text: autonomyDisplayValue(value)}));
            container.appendChild(item);
        }

        function autonomyRenderScenarioLocks() {
            if (!autonomyScenarioLocks) return;
            autonomyScenarioLocks.replaceChildren();
            const sourceLock = autonomyCaseSourceLock() || autonomyPlainObject(autonomyLiveScenarios[0]?.source_lock);
            const scale = autonomyScenarioRequestScale();
            autonomyAppendLock(
                autonomyScenarioLocks,
                'Annual source',
                sourceLock?.annual_job_id || sourceLock?.source_annual_job_id || 'Not locked'
            );
            autonomyAppendLock(
                autonomyScenarioLocks,
                'Source snapshot SHA-256',
                sourceLock?.source_snapshot_sha256 || 'Not locked',
                true
            );
            autonomyAppendLock(autonomyScenarioLocks, 'TEA analysis basis', sourceLock?.analysis_basis || 'Not locked');
            autonomyAppendLock(autonomyScenarioLocks, 'Realizations', scale.realizations);
            autonomyAppendLock(autonomyScenarioLocks, 'Seed', scale.seed);
            autonomyAppendLock(autonomyScenarioLocks, 'Case revision', autonomyExpectedCaseRevision() || 'Not recorded');
        }

        function autonomyValidationItems(scenario) {
            const validation = autonomyScenarioValidation(scenario);
            const items = [];
            const fieldErrors = Array.isArray(validation.field_errors)
                ? validation.field_errors
                : (Array.isArray(validation.errors) ? validation.errors : []);
            fieldErrors.forEach((error) => {
                if (typeof error === 'string') items.push(error);
                else {
                    const path = error?.field || error?.path || error?.request_path || '';
                    const message = error?.message || error?.detail || error?.code || 'Invalid input.';
                    items.push([path, message].filter(Boolean).join(': '));
                }
            });
            const rules = validation.violated_contract_rules || validation.violated_rules || validation.rules || [];
            (Array.isArray(rules) ? rules : [rules]).filter(Boolean).forEach((rule) => {
                items.push('Rule: ' + (typeof rule === 'string' ? rule : rule?.rule || rule?.message || rule?.id || 'Contract rule'));
            });
            const alternatives = validation.closest_supported_alternatives || validation.closest_supported_alternative || [];
            (Array.isArray(alternatives) ? alternatives : [alternatives]).filter(Boolean).forEach((alternative) => {
                items.push('Closest supported alternative: ' + (typeof alternative === 'string'
                    ? alternative
                    : alternative?.label || alternative?.message || alternative?.action || 'Review supported inputs'));
            });
            return items;
        }

        function autonomyScenarioStatusLabel(scenario) {
            const status = String(scenario?.draft_status || autonomyScenarioValidation(scenario).status || 'draft');
            return status.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
        }

        function autonomyScenarioEvidenceState(scenario) {
            const validation = autonomyScenarioValidation(scenario);
            const references = Array.isArray(scenario?.evidence_references)
                ? scenario.evidence_references : [];
            const verifiedReceipts = Array.isArray(validation.evidence_receipts)
                ? validation.evidence_receipts : [];
            if (validation.valid === true && verifiedReceipts.length === references.length) {
                return references.length
                    ? references.length + ' accepted receipt' + (references.length === 1 ? '' : 's') + ' verified'
                    : 'Complete · no receipt reference required';
            }
            if (validation.valid === false) {
                return verifiedReceipts.length + ' of ' + references.length + ' receipt references verified · blocked';
            }
            return references.length
                ? references.length + ' receipt reference' + (references.length === 1 ? '' : 's') + ' · validation pending'
                : 'Validation pending';
        }

        function autonomyScenarioActionButton(action, label, scenario) {
            const actionRecords = autonomyActionEntries(scenario?.allowed_actions).filter((entry) => (
                (typeof entry === 'string' ? entry : entry.id) === action
            ));
            if (!actionRecords.length) return null;
            const enabled = autonomyActionIsAllowed(action, scenario);
            const button = autonomyNode('button', {className: 'autonomy-button autonomy-button-secondary', text: label, type: 'button'});
            button.dataset.autonomyLiveScenarioAction = action;
            button.dataset.scenarioId = autonomyScenarioId(scenario.scenario_id);
            button.disabled = !enabled;
            button.setAttribute('aria-disabled', String(!enabled));
            if (!enabled) button.title = autonomyActionDisabledReason(action, scenario);
            return button;
        }

        function autonomyRenderScenarioCard(scenario) {
            const scenarioId = autonomyScenarioId(scenario?.scenario_id);
            if (!scenarioId) return null;
            const article = autonomyNode('article', {className: 'autonomy-scenario-card autonomy-live-scenario-card'});
            if (scenario.audit_only) article.classList.add('is-audit-history');
            article.setAttribute('role', 'listitem');
            article.dataset.scenarioId = scenarioId;
            article.dataset.state = String(scenario.draft_status || 'draft').replace(/_/g, '-');
            article.dataset.status = autonomyScenarioIsValidated(scenario) ? 'valid'
                : (scenario.draft_status === 'expired' ? 'invalid' : 'provisional');
            const heading = autonomyNode('div');
            heading.appendChild(autonomyNode('span', {
                className: 'autonomy-scenario-label',
                text: String(scenario.kind || 'scenario').replace(/_/g, ' '),
            }));
            heading.appendChild(autonomyNode('strong', {text: autonomyScenarioStatusLabel(scenario)}));
            article.appendChild(heading);
            article.appendChild(autonomyNode('h4', {text: scenario.label || scenarioId}));
            if (scenario.audit_only) article.appendChild(autonomyNode('p', {
                className: 'autonomy-audit-only-label',
                text: 'Audit history only · no current revision',
            }));

            const selectionKey = autonomyScenarioRevisionKey(scenario);
            const selection = autonomyNode('label', {className: 'autonomy-scenario-selection'});
            const checkbox = autonomyNode('input');
            checkbox.type = 'checkbox';
            checkbox.dataset.autonomyLiveScenarioSelect = scenarioId;
            checkbox.checked = autonomySelectedScenarioRevisions.has(selectionKey);
            checkbox.disabled = !autonomyScenarioIsSelectable(scenario);
            checkbox.setAttribute('aria-label', 'Select ' + String(scenario.label || scenarioId) + ' for grouped confirmation');
            selection.append(checkbox, autonomyNode('span', {
                text: checkbox.disabled
                    ? (autonomyActionDisabledReason('select_for_confirmation', scenario) || 'Not selectable for grouped confirmation')
                    : 'Select for grouped confirmation',
            }));
            article.setAttribute('aria-selected', String(checkbox.checked));
            article.appendChild(selection);

            const metadata = autonomyNode('dl', {className: 'autonomy-scenario-meta'});
            [
                ['Stable scenario ID', scenarioId],
                ['Revision', String(scenario.revision || 'Not recorded')],
                ['Revision ID', autonomyScenarioRevisionId(scenario.scenario_revision_id) || 'Not recorded'],
                ['Comparison', scenario.comparison_classification || 'Pending validation'],
                ['Evidence state', autonomyScenarioEvidenceState(scenario)],
                ['Expires', scenario.expires_at ? autonomyFormatTimestamp(scenario.expires_at) : 'Does not expire'],
                ['Confirmed', scenario.confirmed_at ? autonomyFormatTimestamp(scenario.confirmed_at) : 'Not confirmed'],
            ].forEach(([term, description]) => {
                const item = autonomyNode('div');
                item.append(autonomyNode('dt', {text: term}), autonomyNode('dd', {text: description}));
                metadata.appendChild(item);
            });
            article.appendChild(metadata);

            const requestHash = String(scenario.request_sha256 || '');
            article.appendChild(autonomyNode('code', {
                className: 'autonomy-scenario-hash',
                text: 'Request SHA-256: ' + (/^[0-9a-f]{64}$/.test(requestHash) ? requestHash : 'Not available'),
            }));

            const differences = autonomyScenarioDifferences(scenario);
            const differenceList = autonomyNode('ul', {className: 'autonomy-scenario-differences'});
            if (!differences.length) {
                differenceList.appendChild(autonomyNode('li', {text: scenario.kind === 'baseline'
                    ? 'Baseline request · no baseline-relative changes.'
                    : 'No exact differences were returned.'}));
            } else {
                differences.forEach((difference) => differenceList.appendChild(autonomyNode('li', {
                    text: difference.field + ': ' + autonomyExactDifferenceText(difference),
                })));
            }
            article.appendChild(differenceList);

            if (scenario.comparison_classification === 'structural' || scenario.structural_warning) {
                article.appendChild(autonomyNode('p', {
                    className: 'autonomy-structural-warning',
                    text: scenario.structural_warning
                        || 'Structural comparison: baseline-relative causal attribution is limited.',
                }));
            }

            const validationItems = autonomyValidationItems(scenario);
            if (validationItems.length) {
                const errors = autonomyNode('ul', {className: 'autonomy-scenario-errors'});
                errors.setAttribute('aria-label', 'Scenario validation details');
                validationItems.forEach((message) => errors.appendChild(autonomyNode('li', {text: message})));
                article.appendChild(errors);
            }

            const history = Array.isArray(scenario.revision_history) ? scenario.revision_history : [];
            if (history.length) {
                const details = autonomyNode('details', {className: 'autonomy-revision-history'});
                details.appendChild(autonomyNode('summary', {text: 'Revision history (' + history.length + ')'}));
                const list = autonomyNode('ol');
                history.forEach((revision) => list.appendChild(autonomyNode('li', {
                    text: 'Revision ' + String(revision?.revision || '?') + ' · '
                        + String(revision?.draft_status || revision?.status || 'recorded').replace(/_/g, ' ')
                        + (revision?.updated_at ? ' · ' + autonomyFormatTimestamp(revision.updated_at) : ''),
                })));
                details.appendChild(list);
                article.appendChild(details);
            }

            const actions = autonomyNode('div', {className: 'autonomy-scenario-card-actions'});
            [
                autonomyScenarioActionButton('revise_scenario', 'Create revision', scenario),
                autonomyScenarioActionButton('validate_scenario', 'Validate', scenario),
                autonomyScenarioActionButton('expire_scenario', 'Expire draft', scenario),
            ].filter(Boolean).forEach((button) => actions.appendChild(button));
            if (actions.childElementCount) article.appendChild(actions);
            return article;
        }

        function autonomyCurrentScenarioSelections() {
            return Array.from(autonomySelectedScenarioRevisions.values()).filter((scenario) => {
                const current = autonomyLiveScenarios.find((item) => (
                    autonomyScenarioRevisionKey(item) === autonomyScenarioRevisionKey(scenario)
                ));
                return !!current && autonomyScenarioIsSelectable(current);
            });
        }

        function autonomyRenderScenarioMatrix() {
            if (!autonomyScenarioMatrixHead || !autonomyScenarioMatrixBody || !autonomyLiveScenarioMatrix) return;
            autonomyScenarioMatrixHead.replaceChildren();
            autonomyScenarioMatrixBody.replaceChildren();
            if (autonomyLiveScenarioMobileList) autonomyLiveScenarioMobileList.replaceChildren();
            const currentScenarios = autonomyLiveScenarios.filter((scenario) => !scenario.audit_only);
            const baseline = currentScenarios.find((scenario) => scenario.kind === 'baseline');
            const alternatives = currentScenarios.filter((scenario) => scenario.kind !== 'baseline');
            const ordered = [baseline, ...alternatives].filter(Boolean);
            const matrixRows = Array.isArray(autonomyLiveComparison?.difference_matrix)
                ? autonomyLiveComparison.difference_matrix : [];
            const fields = matrixRows.map((row) => String(row?.path || row?.field || 'Input'));
            ordered.forEach((scenario) => autonomyScenarioDifferences(scenario).forEach((difference) => {
                if (!fields.includes(difference.field)) fields.push(difference.field);
            }));
            if (!ordered.length || !baseline) {
                autonomyLiveScenarioMatrix.hidden = true;
                return;
            }
            const headerRow = autonomyNode('tr');
            const fieldHeader = autonomyNode('th', {text: 'Field'});
            fieldHeader.scope = 'col';
            headerRow.appendChild(fieldHeader);
            ordered.forEach((scenario) => {
                const header = autonomyNode('th', {text: scenario.label || scenario.scenario_id});
                header.scope = 'col';
                headerRow.appendChild(header);
            });
            autonomyScenarioMatrixHead.appendChild(headerRow);
            (fields.length ? fields : ['Comparison']).forEach((field) => {
                const row = autonomyNode('tr');
                const heading = autonomyNode('th', {text: field});
                heading.scope = 'row';
                row.appendChild(heading);
                ordered.forEach((scenario) => {
                    const difference = autonomyScenarioDifferences(scenario).find((item) => item.field === field);
                    const matrixRow = matrixRows.find((item) => String(item?.path || item?.field || 'Input') === field);
                    row.appendChild(autonomyNode('td', {text: scenario.kind === 'baseline'
                        ? (matrixRow
                            ? 'input: ' + autonomyDisplayValue(matrixRow.baseline?.value, matrixRow.baseline?.present)
                            : 'input: baseline request')
                        : (difference ? autonomyExactDifferenceText(difference) : 'hypothesis: no change from baseline input')}));
                });
                autonomyScenarioMatrixBody.appendChild(row);
            });
            autonomyLiveScenarioMatrix.hidden = false;

            alternatives.forEach((scenario) => {
                const article = autonomyNode('article');
                article.appendChild(autonomyNode('h4', {text: scenario.label || scenario.scenario_id}));
                const list = autonomyNode('dl');
                const differences = autonomyScenarioDifferences(scenario);
                (differences.length ? differences : [{field: 'Comparison', display: 'No change'}]).forEach((difference) => {
                    const item = autonomyNode('div');
                    item.append(autonomyNode('dt', {text: difference.field}), autonomyNode('dd', {
                        text: autonomyExactDifferenceText(difference),
                    }));
                    list.appendChild(item);
                });
                article.appendChild(list);
                autonomyLiveScenarioMobileList?.appendChild(article);
            });
        }

        function autonomyComparisonBlockers() {
            const blockers = autonomyLiveComparison?.blockers || autonomyLiveComparison?.exact_blockers || [];
            return Array.isArray(blockers) ? blockers : [];
        }

        function autonomyComparisonBlockerText(blocker) {
            if (typeof blocker === 'string') return blocker;
            const record = autonomyPlainObject(blocker);
            const parts = [record.message || record.detail || record.code];
            const alternatives = record.closest_supported_alternatives
                || record.closest_supported_alternative || [];
            (Array.isArray(alternatives) ? alternatives : [alternatives]).filter(Boolean).forEach((alternative) => {
                parts.push('Closest supported alternative: ' + (typeof alternative === 'string'
                    ? alternative
                    : alternative.label || alternative.message || alternative.action || 'Review supported inputs'));
            });
            const supportedAction = record.supported_action || record.closest_supported_action;
            if (supportedAction) parts.push('Supported action: ' + (typeof supportedAction === 'string'
                ? supportedAction.replace(/_/g, ' ')
                : supportedAction.label || supportedAction.id || 'Review available actions'));
            return parts.filter(Boolean).join(' · ');
        }

        function autonomyRenderComparisonSummary() {
            if (!autonomyComparisonSummary) return;
            autonomyComparisonSummary.replaceChildren();
            const blockers = autonomyComparisonBlockers();
            const currentScenarios = autonomyLiveScenarios.filter((scenario) => !scenario.audit_only);
            const structuralCount = currentScenarios.filter((scenario) => (
                scenario.comparison_classification === 'structural'
            )).length;
            const validCount = currentScenarios.filter(autonomyScenarioIsValidated).length;
            autonomyComparisonSummary.dataset.status = blockers.length ? 'blocked'
                : (structuralCount ? 'warning' : (validCount ? 'valid' : 'pending'));
            autonomyComparisonSummary.appendChild(autonomyNode('strong', {text: blockers.length
                ? 'Comparison has deterministic blockers'
                : 'Deterministic comparison state'}));
            const summary = autonomyLiveComparison?.summary || (
                validCount + ' validated scenario' + (validCount === 1 ? '' : 's')
                + (structuralCount ? ' · ' + structuralCount + ' structural warning' + (structuralCount === 1 ? '' : 's') : '')
            );
            autonomyComparisonSummary.appendChild(autonomyNode('p', {text: summary}));
            blockers.forEach((blocker) => autonomyComparisonSummary.appendChild(autonomyNode('p', {
                text: autonomyComparisonBlockerText(blocker),
            })));
            const templateMetadata = autonomyPlainObject(autonomyLiveComparison?.request_template_metadata);
            if (templateMetadata.message) {
                autonomyComparisonSummary.appendChild(autonomyNode('p', {text: templateMetadata.message}));
            }
            const templateAction = autonomyPlainObject(templateMetadata.supported_action);
            if (templateAction.id === 'open_expert_tea') {
                const button = autonomyNode('button', {
                    className: 'autonomy-button autonomy-button-secondary',
                    text: templateAction.label || 'Open expert TEA',
                    type: 'button',
                });
                button.dataset.autonomyOpenExpertTea = 'true';
                autonomyComparisonSummary.appendChild(button);
            }
        }

        function autonomyRenderScenarioSelectionState() {
            const selected = autonomyCurrentScenarioSelections();
            const canConfirm = selected.length > 0 && selected.length <= 4
                && autonomyConfirmationHasOneBaseline(selected)
                && autonomyActionIsAllowed('confirm_scenarios');
            if (autonomyOpenLiveConfirmationBtn) {
                autonomyOpenLiveConfirmationBtn.disabled = !canConfirm;
                autonomyOpenLiveConfirmationBtn.setAttribute('aria-disabled', String(!canConfirm));
            }
            if (autonomyLiveRunGateHelp) {
                autonomyLiveRunGateHelp.textContent = canConfirm
                    ? selected.length + ' validated scenario' + (selected.length === 1 ? '' : 's')
                        + ' selected. Review exact immutable requests before creating jobs.'
                    : (autonomyActionDisabledReason('confirm_scenarios')
                        || 'Select between one and four validated current scenario revisions, including exactly one baseline.');
            }
        }

        function autonomyRenderLiveAssumptions() {
            if (!autonomyLiveAssumptions) return;
            autonomyLiveAssumptions.replaceChildren();
            const current = autonomyLiveScenarios.filter((scenario) => !scenario.audit_only);
            if (!current.length) {
                autonomyLiveAssumptions.appendChild(autonomyNode('p', {
                    text: 'No current scenario inputs are recorded. Pre-run values are inputs or hypotheses, never outcomes.',
                }));
                return;
            }
            current.forEach((scenario) => {
                const article = autonomyNode('article');
                article.appendChild(autonomyNode('strong', {text: scenario.label || scenario.scenario_id}));
                const changed = Array.isArray(scenario.changed_fields) && scenario.changed_fields.length
                    ? scenario.changed_fields.join(', ')
                    : (scenario.kind === 'baseline' ? 'Baseline input set' : 'No declared difference');
                article.appendChild(autonomyNode('p', {
                    text: String(scenario.comparison_classification || 'pending validation')
                        + ' · ' + changed + ' · ' + autonomyScenarioEvidenceState(scenario),
                }));
                article.appendChild(autonomyNode('small', {text: 'Input / hypothesis · never an outcome'}));
                autonomyLiveAssumptions.appendChild(article);
            });
        }

        function autonomyRenderLiveScenarios() {
            if (autonomyContentMode !== 'live') return;
            autonomyRenderScenarioLocks();
            if (autonomyLiveScenarioGrid) autonomyLiveScenarioGrid.replaceChildren();
            const currentKeys = new Set(autonomyLiveScenarios.map(autonomyScenarioRevisionKey));
            Array.from(autonomySelectedScenarioRevisions.keys()).forEach((key) => {
                const current = autonomyLiveScenarios.find((scenario) => autonomyScenarioRevisionKey(scenario) === key);
                if (!currentKeys.has(key) || !autonomyScenarioIsSelectable(current)) {
                    autonomySelectedScenarioRevisions.delete(key);
                }
            });
            autonomyLiveScenarios.forEach((scenario) => {
                const card = autonomyRenderScenarioCard(scenario);
                if (card) autonomyLiveScenarioGrid?.appendChild(card);
            });
            if (autonomyScenarioEmpty) autonomyScenarioEmpty.hidden = autonomyLiveScenarios.length !== 0;
            const currentScenarios = autonomyLiveScenarios.filter((scenario) => !scenario.audit_only);
            const auditOnlyCount = autonomyLiveScenarios.length - currentScenarios.length;
            if (autonomyScenarioStatus) autonomyScenarioStatus.textContent = autonomyLiveScenarios.length
                ? currentScenarios.length + ' current durable scenario' + (currentScenarios.length === 1 ? '' : 's')
                    + (auditOnlyCount ? ' · ' + auditOnlyCount + ' expired/superseded identity in audit history.' : ' loaded.')
                : 'No durable scenario drafts are recorded for this case.';
            const baselineCount = currentScenarios.filter((scenario) => scenario.kind === 'baseline').length;
            const alternativeCount = currentScenarios.filter((scenario) => scenario.kind === 'alternative').length;
            const canCreate = autonomyActionIsAllowed('create_scenario');
            if (autonomyCreateBaselineBtn) {
                autonomyCreateBaselineBtn.disabled = !canCreate || baselineCount >= 1;
                autonomyCreateBaselineBtn.title = !canCreate ? autonomyActionDisabledReason('create_scenario') : '';
            }
            if (autonomyCreateAlternativeBtn) {
                autonomyCreateAlternativeBtn.disabled = !canCreate || baselineCount !== 1 || alternativeCount >= 3;
                autonomyCreateAlternativeBtn.title = !canCreate ? autonomyActionDisabledReason('create_scenario') : '';
            }
            autonomyRenderScenarioMatrix();
            autonomyRenderComparisonSummary();
            autonomyRenderLiveAssumptions();
            autonomyRenderScenarioSelectionState();
        }

        function autonomyExecutionJobs(options = {}) {
            const execution = autonomyPlainObject(autonomyLiveExecution);
            const candidates = options.latestOnly && Array.isArray(execution.latest_jobs)
                ? execution.latest_jobs
                : (Array.isArray(execution.jobs)
                    ? execution.jobs
                    : (Array.isArray(execution.tea_jobs) ? execution.tea_jobs : []));
            const jobs = [];
            candidates.forEach((candidate) => {
                const job = autonomyPlainObject(candidate?.job || candidate);
                const jobId = autonomyTeaJobId(job.tea_job_id || job.job_id || job.id);
                if (!jobId || jobs.some((item) => item.tea_job_id === jobId)) return;
                const scenarioId = autonomyScenarioId(candidate?.scenario_id || job.scenario_id);
                const scenario = autonomyScenarioById(scenarioId);
                jobs.push({
                    ...job,
                    tea_job_id: jobId,
                    scenario_id: scenarioId,
                    scenario_revision_id: autonomyScenarioRevisionId(
                        candidate?.scenario_revision_id || job.scenario_revision_id
                    ),
                    scenario_label: candidate?.scenario_label || job.scenario_label || job.label || scenario?.label || '',
                    attempt_number: Number(candidate?.attempt_number || job.attempt_number || 0),
                    retry_of_job_id: candidate?.retry_of_job_id || job.retry_of_job_id || null,
                    confirmation_id: candidate?.confirmation_id || job.confirmation_id || null,
                    allowed_actions: candidate?.allowed_actions || job.allowed_actions || [],
                });
            });
            if (!jobs.length) {
                autonomyLiveScenarios.forEach((scenario) => {
                    const linked = Array.isArray(scenario.tea_jobs) ? scenario.tea_jobs : [];
                    linked.forEach((job) => {
                        const jobId = autonomyTeaJobId(job?.tea_job_id || job?.job_id || job?.id);
                        if (!jobId || jobs.some((item) => item.tea_job_id === jobId)) return;
                        jobs.push({
                            ...autonomyPlainObject(job), tea_job_id: jobId,
                            scenario_id: autonomyScenarioId(scenario.scenario_id),
                            scenario_revision_id: autonomyScenarioRevisionId(scenario.scenario_revision_id),
                            scenario_label: scenario.label || '',
                        });
                    });
                });
            }
            return jobs;
        }

        function autonomyTeaStateLabel(value) {
            return {
                queued: 'Queued', leased: 'Leased', running: 'Running', done: 'Completed',
                error: 'Failed', cancelled: 'Cancelled', interrupted: 'Interrupted',
                reconnecting: 'Reconnecting',
            }[String(value || '')] || 'Unknown';
        }

        function autonomyJobActionAllowed(actionId, job) {
            const direct = autonomyActionEntries(job?.allowed_actions).some((action) => (
                (typeof action === 'string' ? action : action?.id) === actionId
                && (typeof action === 'string' || action.enabled !== false)
            ));
            if (direct) return true;
            const jobId = autonomyTeaJobId(job?.tea_job_id);
            const listName = actionId === 'cancel_execution' ? 'cancellable_job_ids' : 'retryable_job_ids';
            const allowedIds = Array.isArray(autonomyLiveExecution?.[listName])
                ? autonomyLiveExecution[listName].map(autonomyTeaJobId).filter(Boolean)
                : [];
            return allowedIds.includes(jobId) && autonomyActionIsAllowed(actionId);
        }

        function autonomyRenderExecutionSummary(jobs) {
            if (!autonomyExecutionSummary) return;
            autonomyExecutionSummary.replaceChildren();
            const execution = autonomyPlainObject(autonomyLiveExecution);
            const confirmations = Array.isArray(execution.confirmations) ? execution.confirmations : [];
            const confirmation = autonomyPlainObject(
                execution.confirmation || execution.confirmation_receipt || confirmations.at(-1)
            );
            const receipt = autonomyPlainObject(confirmation.receipt);
            autonomyAppendLock(autonomyExecutionSummary, 'Confirmation', confirmation.confirmation_id || execution.confirmation_id || 'Not confirmed');
            autonomyAppendLock(autonomyExecutionSummary, 'Confirmed by', confirmation.operator_name || 'Not confirmed');
            autonomyAppendLock(autonomyExecutionSummary, 'Confirmation receipt SHA-256', confirmation.receipt_sha256 || receipt.sha256 || 'Not recorded', true);
            autonomyAppendLock(autonomyExecutionSummary, 'Linked TEA jobs', jobs.length);
            const queueBehavior = autonomyPlainObject(execution.queue_behavior);
            autonomyAppendLock(
                autonomyExecutionSummary,
                'Queue behavior',
                queueBehavior.policy
                    ? String(queueBehavior.policy).replace(/_/g, ' ')
                    : 'Existing sequential leased worker'
            );
            autonomyAppendLock(
                autonomyExecutionSummary,
                'Confirmed case revision',
                confirmation.case_revision_after || confirmation.case_revision_before || 'Not recorded'
            );
            autonomyAppendLock(autonomyExecutionSummary, 'Current case revision', autonomyExpectedCaseRevision() || 'Not recorded');
        }

        function autonomyRenderExecutionJob(job) {
            const jobId = autonomyTeaJobId(job?.tea_job_id);
            if (!jobId) return null;
            const state = String(job.state || 'queued').toLowerCase();
            const article = autonomyNode('article', {className: 'autonomy-job-card'});
            article.setAttribute('role', 'listitem');
            article.dataset.teaJobId = jobId;
            article.dataset.state = state;
            article.dataset.status = state === 'done' ? 'complete'
                : (state === 'error' ? 'failed' : state);
            const heading = autonomyNode('div');
            heading.append(
                autonomyNode('strong', {text: job.scenario_label || job.scenario_id || 'Scenario TEA'}),
                autonomyNode('span', {text: autonomyTeaStateLabel(state)})
            );
            article.appendChild(heading);
            const progressValue = Number(job.progress);
            const progress = Number.isFinite(progressValue) ? Math.max(0, Math.min(100, progressValue)) : (state === 'done' ? 100 : 0);
            const progressNode = autonomyNode('progress');
            progressNode.max = 100;
            progressNode.value = progress;
            progressNode.textContent = Math.round(progress) + '%';
            progressNode.setAttribute('aria-label', (job.scenario_label || 'Scenario') + ' TEA progress');
            progressNode.setAttribute('aria-valuetext', autonomyTeaStateLabel(state) + (job.stage ? ' · ' + job.stage : ''));
            article.appendChild(progressNode);
            article.appendChild(autonomyNode('p', {text: job.stage || job.error || 'Durable TEA state recorded by the existing worker.'}));
            article.appendChild(autonomyNode('code', {text: jobId}));
            const attemptParts = [];
            if (job.attempt_number) attemptParts.push('Attempt ' + job.attempt_number);
            if (job.retry_of_job_id) attemptParts.push('Retry of ' + job.retry_of_job_id);
            if (job.started_at || job.updated_at || job.completed_at) {
                attemptParts.push(autonomyFormatTimestamp(job.completed_at || job.updated_at || job.started_at));
            }
            if (attemptParts.length) article.appendChild(autonomyNode('small', {text: attemptParts.join(' · ')}));
            const actions = autonomyNode('div', {className: 'autonomy-job-card-actions'});
            if (autonomyJobActionAllowed('cancel_execution', job)) {
                const cancel = autonomyNode('button', {className: 'autonomy-button autonomy-button-secondary', text: 'Cancel', type: 'button'});
                cancel.dataset.autonomyExecutionAction = 'cancel';
                cancel.dataset.teaJobId = jobId;
                actions.appendChild(cancel);
            }
            if (autonomyJobActionAllowed('retry_failed_execution', job)) {
                const retry = autonomyNode('button', {className: 'autonomy-button autonomy-button-secondary', text: 'Retry from frozen snapshot', type: 'button'});
                retry.dataset.autonomyExecutionAction = 'retry';
                retry.dataset.teaJobId = jobId;
                actions.appendChild(retry);
            }
            if (actions.childElementCount) article.appendChild(actions);
            article.dataset.structureSignature = autonomyExecutionJobStructureSignature(job);
            return article;
        }

        function autonomyExecutionJobStructureSignature(job) {
            return JSON.stringify({
                id: autonomyTeaJobId(job?.tea_job_id),
                state: String(job?.state || 'queued'),
                label: String(job?.scenario_label || job?.scenario_id || ''),
                error: String(job?.error || ''),
                attempt: Number(job?.attempt_number || 0),
                retryOf: String(job?.retry_of_job_id || ''),
                cancel: autonomyJobActionAllowed('cancel_execution', job),
                retry: autonomyJobActionAllowed('retry_failed_execution', job),
            });
        }

        function autonomyUpdateExecutionJobCard(card, job) {
            const state = String(job?.state || 'queued').toLowerCase();
            card.dataset.state = state;
            card.dataset.status = state === 'done' ? 'complete' : (state === 'error' ? 'failed' : state);
            const status = card.querySelector(':scope > div:first-child span');
            if (status) status.textContent = autonomyTeaStateLabel(state);
            const progress = card.querySelector('progress');
            if (progress) {
                const raw = Number(job?.progress);
                const value = Number.isFinite(raw) ? Math.max(0, Math.min(100, raw)) : (state === 'done' ? 100 : 0);
                progress.value = value;
                progress.textContent = Math.round(value) + '%';
                progress.setAttribute('aria-valuetext', autonomyTeaStateLabel(state) + (job?.stage ? ' · ' + job.stage : ''));
            }
            const detail = card.querySelector(':scope > p');
            if (detail) detail.textContent = job?.stage || job?.error || 'Durable TEA state recorded by the existing worker.';
        }

        function autonomyReconcileExecutionJobs(jobs) {
            if (!autonomyLiveJobList) return;
            const activeAction = document.activeElement instanceof HTMLElement
                ? document.activeElement.closest('[data-autonomy-execution-action]') : null;
            const focusToken = activeAction ? {
                jobId: autonomyTeaJobId(activeAction.dataset.teaJobId),
                action: activeAction.dataset.autonomyExecutionAction,
            } : null;
            const existing = new Map(Array.from(autonomyLiveJobList.children).map((card) => (
                [autonomyTeaJobId(card.dataset.teaJobId), card]
            )).filter(([jobId]) => jobId));
            const desired = [];
            jobs.forEach((job) => {
                const jobId = autonomyTeaJobId(job.tea_job_id);
                const signature = autonomyExecutionJobStructureSignature(job);
                let card = existing.get(jobId);
                if (!card || card.dataset.structureSignature !== signature) {
                    const replacement = autonomyRenderExecutionJob(job);
                    if (!replacement) return;
                    if (card) card.replaceWith(replacement);
                    card = replacement;
                } else {
                    autonomyUpdateExecutionJobCard(card, job);
                }
                desired.push(card);
            });
            const desiredSet = new Set(desired);
            Array.from(autonomyLiveJobList.children).forEach((card) => {
                if (!desiredSet.has(card)) card.remove();
            });
            desired.forEach((card, index) => {
                const current = autonomyLiveJobList.children[index];
                if (current !== card) autonomyLiveJobList.insertBefore(card, current || null);
            });
            if (!desired.length) {
                const empty = autonomyNode('article', {className: 'autonomy-job-card'});
                empty.setAttribute('role', 'listitem');
                empty.dataset.state = 'not-confirmed';
                empty.appendChild(autonomyNode('p', {text: 'No linked TEA jobs. Confirm selected validated scenarios to create one atomic batch.'}));
                autonomyLiveJobList.replaceChildren(empty);
            }
            if (focusToken?.jobId && focusToken.action) {
                Array.from(autonomyLiveJobList.querySelectorAll('[data-autonomy-execution-action]'))
                    .find((button) => autonomyTeaJobId(button.dataset.teaJobId) === focusToken.jobId
                        && button.dataset.autonomyExecutionAction === focusToken.action)
                    ?.focus({preventScroll: true});
            }
        }

        function autonomyRenderLiveExecution(options = {}) {
            if (autonomyContentMode !== 'live') return;
            const jobs = autonomyExecutionJobs();
            const latestJobs = autonomyExecutionJobs({latestOnly: true});
            autonomyRenderExecutionSummary(jobs);
            autonomyReconcileExecutionJobs(jobs);
            const counts = latestJobs.reduce((result, job) => {
                const state = String(job.state || 'unknown');
                result[state] = (result[state] || 0) + 1;
                return result;
            }, {});
            const completed = counts.done || 0;
            const failed = (counts.error || 0) + (counts.cancelled || 0) + (counts.interrupted || 0);
            const active = (counts.queued || 0) + (counts.leased || 0) + (counts.running || 0);
            const allComplete = autonomyLiveExecution?.all_successful === true;
            const partial = autonomyLiveExecution?.partial_results === true && !allComplete;
            if (autonomyLivePartialResultsBanner) autonomyLivePartialResultsBanner.hidden = !partial;
            if (autonomyLiveResultsReadyBanner) autonomyLiveResultsReadyBanner.hidden = !allComplete;
            if (autonomyExecutionQueueState) {
                autonomyExecutionQueueState.textContent = latestJobs.length
                    ? [completed + ' completed', active + ' active', failed + ' failed/interrupted'].join(' · ')
                    : 'Not confirmed';
            }
            autonomyRenderScenarioSelectionState();
            if (options.announce) {
                autonomyAnnounce(jobs.length
                    ? 'Scenario execution updated. ' + completed + ' completed, ' + active + ' active, and ' + failed + ' failed or interrupted.'
                    : 'No scenario TEA jobs are linked to this case.');
            }
        }

        async function autonomyFetchScenarioCollection(caseId, signal) {
            return autonomyJsonRequest(
                '/api/autonomy/cases/' + encodeURIComponent(caseId) + '/scenarios',
                {cache: 'no-store', signal}
            );
        }

        async function autonomyFetchScenarioComparison(caseId, signal) {
            try {
                return await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(caseId) + '/scenarios/compare',
                    {cache: 'no-store', signal}
                );
            } catch (error) {
                if ([404, 409, 422].includes(error.status)) {
                    return {comparison: null, blockers: error.blockers, field_errors: error.fieldErrors};
                }
                throw error;
            }
        }

        async function autonomyFetchExecution(caseId, signal) {
            try {
                return await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(caseId) + '/execution',
                    {cache: 'no-store', signal}
                );
            } catch (error) {
                if (error.status === 404) return {execution: null, allowed_actions: []};
                throw error;
            }
        }

        async function autonomyFetchComparisonBundles(caseId, signal) {
            try {
                return await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(caseId) + '/comparison-bundles',
                    {cache: 'no-store', signal}
                );
            } catch (error) {
                if (error.status === 404) return {comparison_bundles: [], decision_allowed_actions: []};
                throw error;
            }
        }

        async function autonomyFetchComparisonBundle(caseId, bundleId, signal = undefined) {
            const safeBundleId = autonomyComparisonBundleId(bundleId);
            if (!safeBundleId) throw new Error('The comparison-bundle identifier is invalid.');
            return autonomyJsonRequest(
                '/api/autonomy/cases/' + encodeURIComponent(caseId)
                    + '/comparison-bundles/' + encodeURIComponent(safeBundleId),
                {cache: 'no-store', signal}
            );
        }

        async function autonomyFetchDecisionBriefs(caseId, signal) {
            try {
                return await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(caseId) + '/decision-briefs',
                    {cache: 'no-store', signal}
                );
            } catch (error) {
                if (error.status === 404) return {decision_briefs: [], decision_allowed_actions: []};
                throw error;
            }
        }

        async function autonomyFetchDecisionBrief(caseId, briefRevisionId, signal = undefined) {
            const safeBriefRevisionId = autonomyBriefRevisionId(briefRevisionId);
            if (!safeBriefRevisionId) throw new Error('The Decision Brief revision identifier is invalid.');
            return autonomyJsonRequest(
                '/api/autonomy/cases/' + encodeURIComponent(caseId)
                    + '/decision-briefs/' + encodeURIComponent(safeBriefRevisionId),
                {cache: 'no-store', signal}
            );
        }

        async function autonomyFetchDecisionSignoffs(caseId, briefRevisionId, signal = undefined) {
            const safeBriefRevisionId = autonomyBriefRevisionId(briefRevisionId);
            if (!safeBriefRevisionId) return {signoffs: [], signoff_allowed_actions: []};
            try {
                return await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(caseId)
                        + '/decision-briefs/' + encodeURIComponent(safeBriefRevisionId) + '/signoffs',
                    {cache: 'no-store', signal}
                );
            } catch (error) {
                if (error.status === 404) return {signoffs: [], signoff_allowed_actions: []};
                throw error;
            }
        }

        async function autonomyFetchDecisionReports(caseId, signal = undefined) {
            try {
                return await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(caseId) + '/reports',
                    {cache: 'no-store', signal}
                );
            } catch (error) {
                if (error.status === 404) return {reports: [], report_allowed_actions: []};
                throw error;
            }
        }

        function autonomyDecisionRecords(payload, pluralKey, singularKey, idReader) {
            const records = Array.isArray(payload?.[pluralKey])
                ? payload[pluralKey]
                : (payload?.[singularKey] ? [payload[singularKey]] : []);
            return records.filter((record) => record && typeof record === 'object' && idReader(record));
        }

        function autonomyDecisionBundleRecordId(record) {
            return autonomyComparisonBundleId(record?.comparison_bundle_id || record?.id);
        }

        function autonomyDecisionBriefRecordId(record) {
            return autonomyBriefRevisionId(record?.brief_revision_id || record?.id);
        }

        function autonomyDecisionSignoffRecordId(record) {
            return autonomySignoffId(record?.signoff_id || record?.id);
        }

        function autonomyDecisionReportRecordId(record) {
            return autonomyReportId(record?.report_id || record?.id);
        }

        function autonomyDecisionBundleSnapshot() {
            const briefBundle = autonomyPlainObject(autonomyLiveBrief?.comparison_bundle);
            if (Object.keys(briefBundle).length) return briefBundle;
            return autonomyPlainObject(autonomyLiveComparisonBundle?.bundle || autonomyLiveComparisonBundle?.comparison_bundle);
        }

        function autonomyDecisionRecommendation() {
            const bundleRecommendation = autonomyPlainObject(autonomyDecisionBundleSnapshot().recommendation);
            const authorizedBundleRecommendation = autonomyPlainObject(
                autonomyDecisionBundleSnapshot().authorized_recommendation
                || autonomyDecisionBundleSnapshot().recommendation_v1
            );
            const briefRecommendation = autonomyPlainObject(
                autonomyLiveBrief?.recommendation
                || autonomyLiveBrief?.recommendation_snapshot
                || autonomyPlainObject(autonomyLiveBrief?.signed_snapshot).recommendation
            );
            const classification = autonomyLiveBrief?.recommendation_classification;
            const confidence = autonomyLiveBrief?.confidence_state;
            return {
                ...bundleRecommendation,
                ...authorizedBundleRecommendation,
                ...briefRecommendation,
                ...(classification && classification !== 'classification_pending_contract'
                    ? {classification: String(classification)} : {}),
                ...(confidence && confidence !== 'classification_pending_contract'
                    ? {confidence: String(confidence)} : {}),
            };
        }

        function autonomyDecisionHasOwn(record, key) {
            return record !== null && record !== undefined
                && Object.prototype.hasOwnProperty.call(Object(record), key);
        }

        function autonomyDecisionScalar(value) {
            if (value === undefined) return 'Missing — not reported';
            if (value === null) return 'Null — explicitly reported';
            if (typeof value === 'string') return value;
            if (typeof value === 'number' || typeof value === 'boolean') return String(value);
            return autonomyDecisionStructuredText(value);
        }

        function autonomyDecisionStructuredText(value) {
            if (value === undefined) return 'Missing — not reported';
            if (value === null) return 'Null — explicitly reported';
            try {
                return JSON.stringify(value, null, 2);
            } catch (_) {
                return 'Value could not be displayed safely.';
            }
        }

        function autonomyDecisionValue(record, key) {
            return autonomyDecisionHasOwn(record, key)
                ? autonomyDecisionScalar(record[key])
                : 'Missing — not reported';
        }

        function autonomyDecisionDisplayValue(record, key) {
            const displayKey = 'display_' + key;
            if (autonomyDecisionHasOwn(record, displayKey)) return autonomyDecisionScalar(record[displayKey]);
            return autonomyDecisionValue(record, key);
        }

        function autonomyDecisionAppendCell(row, value, options = {}) {
            const cell = autonomyNode(options.header ? 'th' : 'td', {text: value});
            if (options.header) cell.scope = 'row';
            if (options.code) cell.className = 'autonomy-live-code-cell';
            row.appendChild(cell);
            return cell;
        }

        function autonomyDecisionAppendExportLinks(cell, teaJobId) {
            const safeTeaJobId = autonomyTeaJobId(teaJobId);
            if (!cell || !safeTeaJobId) return;
            const links = autonomyNode('span', {className: 'autonomy-live-export-links'});
            [['csv', 'Download existing CSV data'], ['xlsx', 'Download existing XLSX data']].forEach(([format, label]) => {
                const link = autonomyNode('a', {text: label});
                link.href = '/api/technoeconomic/jobs/' + encodeURIComponent(safeTeaJobId) + '/exports/' + format;
                link.setAttribute('aria-label', label + ' for ' + safeTeaJobId);
                link.dataset.autonomyDecisionFocus = safeTeaJobId + ':' + format;
                links.appendChild(link);
            });
            cell.appendChild(links);
        }

        function autonomyDecisionAppendEmptyRow(body, columnCount, message) {
            if (!body) return;
            const row = autonomyNode('tr');
            const cell = autonomyNode('td', {text: message});
            cell.colSpan = columnCount;
            row.appendChild(cell);
            body.appendChild(row);
        }

        function autonomyDecisionListValues(value) {
            if (Array.isArray(value)) return value;
            if (value && typeof value === 'object') {
                return Object.entries(value).map(([key, item]) => ({key, value: item}));
            }
            return value === undefined || value === null ? [] : [value];
        }

        function autonomyDecisionAppendList(list, values, emptyCopy) {
            if (!list) return;
            list.replaceChildren();
            const records = autonomyDecisionListValues(values);
            if (!records.length) {
                list.appendChild(autonomyNode('li', {text: emptyCopy}));
                return;
            }
            records.forEach((record) => {
                let textValue;
                if (record && typeof record === 'object' && autonomyDecisionHasOwn(record, 'message')) {
                    textValue = (record.code ? String(record.code) + ': ' : '') + autonomyDecisionScalar(record.message);
                } else if (record && typeof record === 'object' && autonomyDecisionHasOwn(record, 'value')) {
                    textValue = (record.key ? String(record.key) + ': ' : '') + autonomyDecisionScalar(record.value);
                } else {
                    textValue = autonomyDecisionScalar(record);
                }
                list.appendChild(autonomyNode('li', {text: textValue}));
            });
        }

        function autonomyDecisionScenarioLabel(scenario) {
            return autonomyDecisionScalar(
                autonomyDecisionHasOwn(scenario, 'label') ? scenario.label : scenario.scenario_id
            );
        }

        function autonomyDecisionScenarioStatus(scenario) {
            const attempt = autonomyPlainObject(scenario?.attempt);
            return autonomyDecisionScalar(
                autonomyDecisionHasOwn(attempt, 'display_status')
                    ? attempt.display_status
                    : (autonomyDecisionHasOwn(attempt, 'durable_state') ? attempt.durable_state : 'missing')
            );
        }

        function autonomyDecisionSourceSnapshot(scenario, metric = null) {
            const source = autonomyPlainObject(scenario?.source);
            const traceability = autonomyPlainObject(metric?.traceability);
            const provenance = autonomyPlainObject(scenario?.provenance);
            if (autonomyDecisionHasOwn(traceability, 'source_snapshot_sha256')) {
                return autonomyDecisionScalar(traceability.source_snapshot_sha256);
            }
            if (autonomyDecisionHasOwn(source, 'source_snapshot_sha256')) {
                return autonomyDecisionScalar(source.source_snapshot_sha256);
            }
            if (autonomyDecisionHasOwn(provenance, 'source_snapshot_sha256')) {
                return autonomyDecisionScalar(provenance.source_snapshot_sha256);
            }
            return 'Missing — not reported';
        }

        function autonomyDecisionBundleScenarios() {
            const scenarios = autonomyDecisionBundleSnapshot().scenarios;
            return Array.isArray(scenarios) ? scenarios.filter((item) => item && typeof item === 'object') : [];
        }

        function autonomyDecisionMetricPercentile(metric, percentile) {
            const displayPercentiles = autonomyPlainObject(metric?.display_percentiles);
            if (autonomyDecisionHasOwn(displayPercentiles, percentile)) {
                return autonomyDecisionScalar(displayPercentiles[percentile]);
            }
            const percentiles = autonomyPlainObject(metric?.percentiles);
            return autonomyDecisionHasOwn(percentiles, percentile)
                ? autonomyDecisionScalar(percentiles[percentile])
                : 'Missing — not reported';
        }

        function autonomyDecisionFlattenOutcomes(outcomes) {
            const rows = [];
            Object.entries(autonomyPlainObject(outcomes)).forEach(([groupName, rawGroup]) => {
                const group = autonomyPlainObject(rawGroup);
                const probabilities = autonomyPlainObject(group.probabilities);
                const counts = autonomyPlainObject(group.counts);
                const classIds = [...Object.keys(probabilities)];
                Object.keys(counts).forEach((classId) => {
                    if (!classIds.includes(classId)) classIds.push(classId);
                });
                classIds.forEach((classId) => rows.push({
                    label: groupName + ' · ' + classId,
                    probability: autonomyDecisionHasOwn(probabilities, classId) ? probabilities[classId] : undefined,
                    count: autonomyDecisionHasOwn(counts, classId) ? counts[classId] : undefined,
                    denominator: autonomyDecisionHasOwn(group, 'denominator') ? group.denominator : undefined,
                }));
            });
            return rows;
        }

        function autonomyDecisionFlattenSensitivity(sensitivity) {
            const rows = [];
            Object.entries(autonomyPlainObject(sensitivity)).forEach(([responseId, rawModel]) => {
                const model = autonomyPlainObject(rawModel);
                const steps = Array.isArray(model.steps) ? model.steps : [];
                steps.forEach((rawStep) => {
                    const step = autonomyPlainObject(rawStep);
                    rows.push({responseId, step});
                });
            });
            return rows;
        }

        function autonomyDecisionStateName() {
            if (autonomyDecisionLoadError) return 'api-unavailable';
            const bundleRecord = autonomyLiveComparisonBundle;
            const brief = autonomyLiveBrief;
            const bundle = autonomyDecisionBundleSnapshot();
            if (!bundleRecord && !Object.keys(bundle).length) return 'empty';
            if (brief?.superseded || brief?.superseded_by_revision_id || bundleRecord?.superseded_by_bundle_id) return 'superseded';
            if (brief?.stale || brief?.stale_at || bundleRecord?.stale || bundleRecord?.stale_at) return 'stale';
            const scenarios = autonomyDecisionBundleScenarios();
            if (scenarios.some((scenario) => (
                String(scenario?.verification?.status || '') === 'failed'
                || String(scenario?.attempt?.display_status || '') === 'verification_failed'
            ))) return 'verification-failure';
            const completeness = autonomyPlainObject(bundle.completeness);
            if (completeness.status === 'partial' || bundleRecord?.is_complete === false) return 'partial-results';
            const recommendation = autonomyDecisionRecommendation();
            if (recommendation.state === 'unavailable' || recommendation.recommendation_eligible === false) {
                return 'recommendation-unavailable';
            }
            if (recommendation.state === 'classification_pending_contract' || !recommendation.classification) {
                return 'classification-pending';
            }
            if (!autonomyLiveAgentAvailable) return 'agent-unavailable';
            return brief ? 'recommendation' : 'comparison-ready';
        }

        function autonomyDecisionStatePresentation(stateName) {
            const disabledReason = autonomyDecisionActionDisabledReason('open_decision_brief');
            return {
                loading: ['Loading verified comparison', 'No displayed metric is admitted until server re-verification succeeds.'],
                empty: ['No comparison snapshot yet', disabledReason || 'The server has not authorized a deterministic comparison for this case.'],
                'partial-results': ['Partial Results · no final recommendation', 'Completed selected scenarios are shown beside every incomplete, failed, cancelled, interrupted, stale, or missing selection.'],
                'classification-pending': ['Classification pending contract', 'The verified comparison is complete, but the approved contracts do not authorize a deterministic winner or confidence threshold.'],
                stale: ['Stale Decision Brief revision', 'This immutable revision remains reviewable, but a qualifying case, result, source, scenario, or evidence change requires a new snapshot.'],
                superseded: ['Superseded comparison or Decision Brief revision', 'This immutable revision remains reviewable and points to a newer immutable snapshot.'],
                'verification-failure': ['Result verification failure', 'At least one explicitly selected attempt failed request, source, evidence, numerical provenance, terminal-state, or reporting tie-out verification.'],
                'recommendation-unavailable': ['Recommendation and sign-off unavailable', 'The versioned recommendation contract rejected this snapshot. Review every exact blocker before creating a new verified comparison.'],
                'agent-unavailable': ['Decision Agent unavailable · deterministic brief remains usable', 'This verified brief does not depend on the Decision Agent and remains fully traceable.'],
                'api-unavailable': ['Decision Brief service unavailable', autonomyDecisionLoadError?.message || 'The durable case is unchanged. Retry the read before relying on this view.'],
                'comparison-ready': ['Verified comparison ready', 'Create an immutable Decision Brief revision from this exact bundle hash when the server authorizes that action.'],
                recommendation: ['Conditional deterministic recommendation', 'Review the decisive evidence, uncertainty, caveats, reversals, and full provenance before recording any server-authorized human disposition.'],
            }[stateName] || ['Decision Brief state unavailable', 'Refresh the durable case before relying on this view.'];
        }

        function autonomyAnnounceDecisionState(stateName, presentation, prefix = '') {
            const announcementKey = autonomyCaseId() + '|' + stateName;
            if (!prefix && announcementKey === autonomyLastAnnouncedDecisionState) return;
            autonomyLastAnnouncedDecisionState = announcementKey;
            const stateCopy = presentation[0] + '. ' + presentation[1];
            autonomyAnnounce(prefix ? prefix + ' ' + stateCopy : stateCopy);
        }

        function autonomyDecisionStageLabel() {
            return {
                empty: 'Ready to build',
                'partial-results': 'Partial results',
                'classification-pending': 'Contract pending',
                stale: 'Stale revision',
                superseded: 'Superseded',
                'verification-failure': 'Verification failed',
                'recommendation-unavailable': 'Unavailable',
                'agent-unavailable': 'Agent unavailable',
                'api-unavailable': 'Reconnecting',
                'comparison-ready': 'Comparison ready',
                recommendation: 'Brief ready',
            }[autonomyDecisionStateName()] || 'Available';
        }

        function autonomyDecisionBlockerValues() {
            const bundle = autonomyDecisionBundleSnapshot();
            const recommendation = autonomyDecisionRecommendation();
            const values = [];
            [
                autonomyDecisionBlockers,
                autonomyPlainObject(bundle.completeness).blockers,
                recommendation.blockers,
            ].forEach((records) => {
                autonomyDecisionListValues(records).forEach((record) => values.push(record));
            });
            autonomyDecisionBundleScenarios().forEach((scenario) => {
                if (String(scenario?.verification?.status || '') !== 'failed') return;
                autonomyDecisionListValues(scenario?.verification?.failures).forEach((failure) => {
                    values.push(autonomyDecisionScenarioLabel(scenario) + ': ' + autonomyDecisionScalar(failure));
                });
            });
            return values;
        }

        function autonomyRenderDecisionSelectors() {
            const buildAction = autonomyActionEntries(autonomyDecisionAllowedActions).find((action) => (
                typeof action === 'object' && action.id === 'build_comparison_bundle'
            ));
            const confirmationIds = Array.isArray(buildAction?.confirmation_ids)
                ? buildAction.confirmation_ids.map(autonomyConfirmationId).filter(Boolean)
                : [];
            if (autonomyLiveConfirmationSelect) {
                const priorConfirmationId = autonomyConfirmationId(autonomyLiveConfirmationSelect.value);
                autonomyLiveConfirmationSelect.replaceChildren();
                const empty = autonomyNode('option', {text: confirmationIds.length ? 'Select an immutable confirmation receipt' : 'No confirmation available'});
                empty.value = '';
                autonomyLiveConfirmationSelect.appendChild(empty);
                confirmationIds.forEach((confirmationId) => {
                    const option = autonomyNode('option', {text: confirmationId});
                    option.value = confirmationId;
                    autonomyLiveConfirmationSelect.appendChild(option);
                });
                const executionConfirmationId = (() => {
                    const confirmation = autonomyPlainObject(
                        autonomyLiveExecution?.confirmation || autonomyLiveExecution?.confirmation_receipt
                    );
                    return autonomyConfirmationId(confirmation.confirmation_id || confirmation.id || autonomyLiveExecution?.confirmation_id);
                })();
                const preferredConfirmationId = confirmationIds.includes(priorConfirmationId)
                    ? priorConfirmationId
                    : (confirmationIds.includes(executionConfirmationId)
                        ? executionConfirmationId
                        : (confirmationIds.length === 1 ? confirmationIds[0] : ''));
                autonomyLiveConfirmationSelect.value = preferredConfirmationId;
                autonomyLiveConfirmationSelect.disabled = confirmationIds.length === 0 || autonomyDecisionBuildInFlight;
            }
            const selectedBundleId = autonomyDecisionBundleRecordId(autonomyLiveComparisonBundle);
            if (autonomyLiveBundleSelect) {
                autonomyLiveBundleSelect.replaceChildren();
                const empty = autonomyNode('option', {text: 'No verified comparison snapshot'});
                empty.value = '';
                autonomyLiveBundleSelect.appendChild(empty);
                autonomyLiveComparisonBundles.forEach((record) => {
                    const bundleId = autonomyDecisionBundleRecordId(record);
                    if (!bundleId) return;
                    const state = record.superseded_by_bundle_id ? 'superseded' : (record.stale || record.stale_at ? 'stale' : (record.is_complete ? 'complete' : 'partial'));
                    const option = autonomyNode('option', {
                        text: bundleId + ' · ' + state + ' · SHA ' + autonomyDecisionScalar(record.bundle_sha256),
                    });
                    option.value = bundleId;
                    option.selected = bundleId === selectedBundleId;
                    autonomyLiveBundleSelect.appendChild(option);
                });
                autonomyLiveBundleSelect.value = selectedBundleId;
                autonomyLiveBundleSelect.disabled = autonomyLiveComparisonBundles.length === 0 || autonomyDecisionBuildInFlight;
            }

            const selectedBriefId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
            if (autonomyLiveBriefSelect) {
                autonomyLiveBriefSelect.replaceChildren();
                const empty = autonomyNode('option', {text: 'No immutable brief revision'});
                empty.value = '';
                autonomyLiveBriefSelect.appendChild(empty);
                autonomyLiveBriefs.forEach((record) => {
                    const briefId = autonomyDecisionBriefRecordId(record);
                    if (!briefId) return;
                    const state = record.superseded || record.superseded_by_revision_id ? 'superseded' : (record.stale || record.stale_at ? 'stale' : 'current');
                    const option = autonomyNode('option', {
                        text: briefId + ' · revision ' + autonomyDecisionScalar(record.revision) + ' · ' + state,
                    });
                    option.value = briefId;
                    option.selected = briefId === selectedBriefId;
                    autonomyLiveBriefSelect.appendChild(option);
                });
                autonomyLiveBriefSelect.value = selectedBriefId;
                autonomyLiveBriefSelect.disabled = autonomyLiveBriefs.length === 0 || autonomyBriefCreateInFlight;
            }
        }

        function autonomyRenderDecisionScenarioRows() {
            if (!autonomyLiveBriefScenarioRows) return;
            autonomyLiveBriefScenarioRows.replaceChildren();
            const scenarios = autonomyDecisionBundleScenarios();
            scenarios.forEach((scenario) => {
                const attempt = autonomyPlainObject(scenario.attempt);
                const verification = autonomyPlainObject(scenario.verification);
                const row = autonomyNode('tr');
                row.dataset.status = String(attempt.display_status || attempt.durable_state || 'missing');
                autonomyDecisionAppendCell(row, autonomyDecisionScenarioLabel(scenario), {header: true});
                autonomyDecisionAppendCell(row, autonomyDecisionScenarioStatus(scenario));
                autonomyDecisionAppendCell(row, autonomyDecisionValue(scenario, 'request_sha256'), {code: true});
                const attemptCell = autonomyDecisionAppendCell(
                    row,
                    autonomyDecisionValue(attempt, 'tea_job_id') + ' / attempt '
                        + autonomyDecisionValue(attempt, 'attempt_number')
                        + ' / retry of ' + autonomyDecisionValue(attempt, 'retry_of_job_id')
                        + ' / explicit link ' + autonomyDecisionValue(attempt, 'selected_by_explicit_link'),
                    {code: true}
                );
                autonomyDecisionAppendExportLinks(attemptCell, attempt.tea_job_id);
                autonomyDecisionAppendCell(
                    row,
                    autonomyDecisionValue(verification, 'status')
                        + (verification.failures ? ' · ' + autonomyDecisionStructuredText(verification.failures) : '')
                );
                autonomyDecisionAppendCell(row, autonomyDecisionSourceSnapshot(scenario), {code: true});
                autonomyLiveBriefScenarioRows.appendChild(row);
            });
            if (!scenarios.length) autonomyDecisionAppendEmptyRow(
                autonomyLiveBriefScenarioRows, 6, 'No selected scenario records are available.'
            );
        }

        function autonomyRenderDecisionMetricRows() {
            if (!autonomyLiveMetricRows) return;
            autonomyLiveMetricRows.replaceChildren();
            let rowCount = 0;
            autonomyDecisionBundleScenarios().forEach((scenario) => {
                const metrics = autonomyPlainObject(scenario?.result?.metrics);
                Object.entries(metrics).forEach(([metricId, rawMetric]) => {
                    const metric = autonomyPlainObject(rawMetric);
                    const traceability = autonomyPlainObject(metric.traceability);
                    const attempt = autonomyPlainObject(scenario.attempt);
                    const row = autonomyNode('tr');
                    autonomyDecisionAppendCell(
                        row,
                        autonomyDecisionScenarioLabel(scenario) + ' · '
                            + autonomyDecisionScalar(metric.metric_id === undefined ? metricId : metric.metric_id),
                        {header: true}
                    );
                    const statusCell = autonomyDecisionAppendCell(
                        row,
                        autonomyDecisionValue(metric, 'status') + ' · count '
                            + autonomyDecisionValue(metric, 'count') + ' · '
                            + autonomyDecisionValue(metric, 'reason')
                    );
                    if (autonomyDecisionHasOwn(metric, 'cdf') && metric.cdf !== null) {
                        const details = autonomyNode('details', {className: 'autonomy-live-cdf-details'});
                        const summary = autonomyNode('summary', {text: 'Open exact CDF distribution'});
                        summary.dataset.autonomyDecisionFocus = autonomyDecisionScalar(scenario.scenario_revision_id)
                            + ':' + metricId + ':cdf';
                        details.appendChild(summary);
                        details.appendChild(autonomyNode('pre', {text: autonomyDecisionStructuredText(metric.cdf)}));
                        statusCell.appendChild(details);
                    }
                    autonomyDecisionAppendCell(row, autonomyDecisionValue(metric, 'unit'));
                    autonomyDecisionAppendCell(row, autonomyDecisionMetricPercentile(metric, 'p5'));
                    autonomyDecisionAppendCell(row, autonomyDecisionMetricPercentile(metric, 'p50'));
                    autonomyDecisionAppendCell(row, autonomyDecisionMetricPercentile(metric, 'p95'));
                    autonomyDecisionAppendCell(
                        row,
                        autonomyDecisionValue(metric, 'percentile_definition') + ' · '
                            + autonomyDecisionValue(metric, 'population_semantics')
                    );
                    autonomyDecisionAppendCell(
                        row,
                        autonomyDecisionValue(traceability, 'scenario_revision_id') + ' · '
                            + autonomyDecisionScalar(traceability.tea_job_id === undefined ? attempt.tea_job_id : traceability.tea_job_id)
                            + ' · attempt ' + autonomyDecisionScalar(traceability.attempt_number === undefined ? attempt.attempt_number : traceability.attempt_number)
                            + ' · source ' + autonomyDecisionSourceSnapshot(scenario, metric),
                        {code: true}
                    );
                    autonomyLiveMetricRows.appendChild(row);
                    rowCount += 1;
                });
            });
            if (!rowCount) autonomyDecisionAppendEmptyRow(
                autonomyLiveMetricRows, 8, 'No verified metric distribution is available for the selected records.'
            );
        }

        function autonomyRenderDecisionJointOutcomes() {
            if (!autonomyLiveJointOutcomeRows) return;
            autonomyLiveJointOutcomeRows.replaceChildren();
            let rowCount = 0;
            autonomyDecisionBundleScenarios().forEach((scenario) => {
                const outcomes = scenario?.result?.joint_outcomes;
                autonomyDecisionFlattenOutcomes(outcomes).forEach((outcome) => {
                    const row = autonomyNode('tr');
                    const attempt = autonomyPlainObject(scenario.attempt);
                    autonomyDecisionAppendCell(row, autonomyDecisionScenarioLabel(scenario), {header: true});
                    autonomyDecisionAppendCell(row, outcome.label);
                    autonomyDecisionAppendCell(
                        row,
                        'probability ' + autonomyDecisionScalar(outcome.probability)
                            + ' · count ' + autonomyDecisionScalar(outcome.count)
                            + ' · denominator ' + autonomyDecisionScalar(outcome.denominator)
                    );
                    autonomyDecisionAppendCell(
                        row,
                        autonomyDecisionValue(attempt, 'tea_job_id') + ' · attempt '
                            + autonomyDecisionValue(attempt, 'attempt_number'),
                        {code: true}
                    );
                    autonomyLiveJointOutcomeRows.appendChild(row);
                    rowCount += 1;
                });
            });
            if (!rowCount) autonomyDecisionAppendEmptyRow(
                autonomyLiveJointOutcomeRows, 4, 'No verified joint outcome probabilities are available.'
            );
        }

        function autonomyRenderDecisionSensitivity() {
            if (!autonomyLiveSensitivityRows) return;
            autonomyLiveSensitivityRows.replaceChildren();
            let rowCount = 0;
            autonomyDecisionBundleScenarios().forEach((scenario) => {
                autonomyDecisionFlattenSensitivity(scenario?.result?.sensitivity).forEach((driver) => {
                    const step = driver.step;
                    const row = autonomyNode('tr');
                    autonomyDecisionAppendCell(row, autonomyDecisionScenarioLabel(scenario), {header: true});
                    autonomyDecisionAppendCell(
                        row,
                        autonomyDecisionScalar(driver.responseId) + ' · '
                            + autonomyDecisionValue(step, 'predictor_id')
                    );
                    autonomyDecisionAppendCell(
                        row,
                        'entry order ' + autonomyDecisionValue(step, 'entry_order')
                            + ' · sign ' + autonomyDecisionValue(step, 'sign')
                    );
                    autonomyDecisionAppendCell(
                        row,
                        'incremental R² ' + autonomyDecisionValue(step, 'incremental_r_squared')
                            + ' · cumulative R² ' + autonomyDecisionValue(step, 'cumulative_r_squared')
                            + ' · standardized beta ' + autonomyDecisionValue(step, 'standardized_beta')
                    );
                    autonomyLiveSensitivityRows.appendChild(row);
                    rowCount += 1;
                });
            });
            if (!rowCount) autonomyDecisionAppendEmptyRow(
                autonomyLiveSensitivityRows, 4, 'No validated sensitivity drivers are available.'
            );
        }

        function autonomyDecisionQualityEntries(scenario) {
            const rows = [];
            const verification = autonomyPlainObject(scenario.verification);
            const result = autonomyPlainObject(scenario.result);
            const quality = autonomyPlainObject(result.quality);
            const attempt = autonomyPlainObject(scenario.attempt);
            const traceability = {
                scenario_revision_id: scenario.scenario_revision_id,
                tea_job_id: attempt.tea_job_id,
                attempt_number: attempt.attempt_number,
                source_snapshot_sha256: autonomyDecisionSourceSnapshot(scenario),
            };
            const tracedDetail = (value) => ({traceability, value});
            autonomyDecisionListValues(verification.checks).forEach((check, index) => {
                const record = autonomyPlainObject(check);
                rows.push({
                    check: record.check || record.name || record.id || record.key || 'Verification check ' + String(index + 1),
                    status: record.status === undefined ? verification.status : record.status,
                    detail: tracedDetail(record.detail === undefined ? check : record.detail),
                });
            });
            if (verification.failures) rows.push({
                check: 'Verification failures', status: verification.status, detail: tracedDetail(verification.failures),
            });
            if (autonomyDecisionHasOwn(result, 'convergence')) rows.push({
                check: 'Convergence', status: 'reported', detail: tracedDetail(result.convergence),
            });
            autonomyDecisionListValues(quality.reporting_checks).forEach((check, index) => {
                const record = autonomyPlainObject(check);
                rows.push({
                    check: record.check_id || record.id || record.check || record.name
                        || 'Reporting check ' + String(index + 1),
                    status: record.status === undefined ? 'reported' : record.status,
                    detail: tracedDetail(check),
                });
            });
            if (autonomyDecisionHasOwn(quality, 'reporting_tie_outs')) rows.push({
                check: 'Result reporting tie-outs',
                status: 'reported',
                detail: tracedDetail(quality.reporting_tie_outs),
            });
            if (autonomyDecisionHasOwn(quality, 'numerical_provenance')) rows.push({
                check: 'Result numerical provenance',
                status: 'reported',
                detail: tracedDetail(quality.numerical_provenance),
            });
            autonomyDecisionListValues(result.common_cost_audit).forEach((audit, index) => {
                const record = autonomyPlainObject(audit);
                rows.push({
                    check: record.check_id || record.id || record.name || record.key
                        || 'Common-cost audit ' + String(index + 1),
                    status: record.status === undefined ? 'reported' : record.status,
                    detail: tracedDetail(audit),
                });
            });
            autonomyDecisionListValues(result.per_weather_year).forEach((weatherYear, index) => {
                const record = autonomyPlainObject(weatherYear);
                const year = record.weather_year || record.year || record.label || record.key || String(index + 1);
                rows.push({
                    check: 'Weather year ' + autonomyDecisionScalar(year),
                    status: record.status === undefined ? 'reported' : record.status,
                    detail: tracedDetail(weatherYear),
                });
            });
            const provenance = autonomyPlainObject(scenario.provenance);
            if (autonomyDecisionHasOwn(provenance, 'reporting_tie_outs')) rows.push({
                check: 'Reporting tie-outs', status: 'reported', detail: tracedDetail(provenance.reporting_tie_outs),
            });
            if (autonomyDecisionHasOwn(provenance, 'kernel_numerics')) rows.push({
                check: 'Numerical provenance', status: 'reported', detail: tracedDetail(provenance.kernel_numerics),
            });
            return rows;
        }

        function autonomyRenderDecisionQuality() {
            if (!autonomyLiveQualityRows) return;
            autonomyLiveQualityRows.replaceChildren();
            let rowCount = 0;
            autonomyDecisionBundleScenarios().forEach((scenario) => {
                autonomyDecisionQualityEntries(scenario).forEach((quality) => {
                    const row = autonomyNode('tr');
                    autonomyDecisionAppendCell(row, autonomyDecisionScenarioLabel(scenario), {header: true});
                    autonomyDecisionAppendCell(row, autonomyDecisionScalar(quality.check));
                    autonomyDecisionAppendCell(row, autonomyDecisionScalar(quality.status));
                    autonomyDecisionAppendCell(row, autonomyDecisionStructuredText(quality.detail), {code: true});
                    autonomyLiveQualityRows.appendChild(row);
                    rowCount += 1;
                });
            });
            if (!rowCount) autonomyDecisionAppendEmptyRow(
                autonomyLiveQualityRows, 4, 'No convergence, verification, or reporting tie-out record is available.'
            );
        }

        function autonomyRenderDecisionEvidence() {
            if (!autonomyLiveEvidenceCaveats) return;
            const recommendation = autonomyDecisionRecommendation();
            const entries = [];
            autonomyDecisionBundleScenarios().forEach((scenario) => {
                entries.push(autonomyDecisionScenarioLabel(scenario) + ' evidence: '
                    + autonomyDecisionStructuredText(scenario.evidence));
                autonomyDecisionListValues(scenario?.result?.warnings).forEach((warning) => {
                    entries.push(autonomyDecisionScenarioLabel(scenario) + ' warning: ' + autonomyDecisionScalar(warning));
                });
            });
            autonomyDecisionListValues(autonomyLiveBrief?.caveats).forEach((item) => entries.push('Caveat: ' + autonomyDecisionScalar(item)));
            autonomyDecisionListValues(recommendation.evidence_gaps).forEach((item) => entries.push('Evidence gap: ' + autonomyDecisionScalar(item)));
            autonomyDecisionListValues(recommendation.model_limitations).forEach((item) => entries.push('Model limitation: ' + autonomyDecisionScalar(item)));
            autonomyDecisionAppendList(autonomyLiveEvidenceCaveats, entries, 'No evidence completeness or caveat record is available.');
        }

        function autonomyRenderDecisionRecommendation(stateName) {
            const recommendation = autonomyDecisionRecommendation();
            const partial = ['partial-results', 'verification-failure', 'recommendation-unavailable', 'empty', 'api-unavailable'].includes(stateName);
            if (autonomyLiveRecommendation) autonomyLiveRecommendation.hidden = partial;
            if (partial) return;
            const pending = stateName === 'classification-pending' || recommendation.state === 'classification_pending_contract';
            const classificationValue = String(recommendation.classification || '');
            const classification = pending ? 'Classification pending contract' : ({
                solaredge: 'SolarEdge',
                solectria: 'Solectria',
                no_decisive_winner: 'No decisive winner',
            }[classificationValue] || autonomyDecisionScalar(recommendation.classification));
            if (autonomyLiveRecommendationHeading) autonomyLiveRecommendationHeading.textContent = classification;
            const confidence = String(recommendation.confidence || autonomyLiveBrief?.confidence_state || '').toLowerCase();
            const authorizedConfidence = ['strong', 'mixed', 'provisional', 'not_applicable'].includes(confidence);
            if (autonomyLiveRecommendationConfidence) {
                autonomyLiveRecommendationConfidence.hidden = pending || !authorizedConfidence;
                autonomyLiveRecommendationConfidence.textContent = confidence === 'not_applicable'
                    ? 'Confidence not applicable'
                    : (authorizedConfidence ? confidence[0].toUpperCase() + confidence.slice(1) + ' confidence' : '');
            }
            if (autonomyLiveRecommendationCopy) {
                autonomyLiveRecommendationCopy.textContent = pending
                    ? 'The exact comparison is available, but no winner or confidence state is authorized until the versioned contract defines the deterministic classification rule.'
                    : autonomyDecisionScalar(
                        recommendation.conditional_statement === undefined
                            ? recommendation.summary
                            : recommendation.conditional_statement
                    );
            }
            autonomyDecisionAppendList(
                autonomyLiveDecisiveEvidence,
                autonomyDecisionListValues(recommendation.decisive_evidence).length
                    ? recommendation.decisive_evidence : recommendation.reasons,
                'No decisive evidence was classified by the server.'
            );
            autonomyDecisionAppendList(autonomyLiveMajorDrivers, recommendation.major_drivers, 'No major drivers were classified by the server.');
            autonomyDecisionAppendList(autonomyLiveImportantUncertainty, recommendation.important_uncertainty, 'No important uncertainty was classified by the server.');
            const limits = [
                ...autonomyDecisionListValues(recommendation.evidence_gaps),
                ...autonomyDecisionListValues(recommendation.model_limitations),
                ...autonomyDecisionListValues(recommendation.warnings),
            ];
            autonomyDecisionAppendList(autonomyLiveModelLimits, limits, 'No evidence gap or model limitation was classified by the server.');
        }

        function autonomyDecisionReversals() {
            if (Array.isArray(autonomyLiveBrief?.reversal_conditions)) return autonomyLiveBrief.reversal_conditions;
            const reversalConditions = autonomyDecisionRecommendation().reversal_conditions;
            return Array.isArray(reversalConditions) ? reversalConditions : [];
        }

        function autonomyRenderDecisionReversals() {
            if (!autonomyLiveReversalRows) return;
            autonomyLiveReversalRows.replaceChildren();
            const reversals = autonomyDecisionReversals();
            reversals.forEach((rawReversal, index) => {
                const reversal = autonomyPlainObject(rawReversal);
                const row = autonomyNode('tr');
                autonomyDecisionAppendCell(
                    row,
                    autonomyDecisionScalar(reversal.condition || reversal.assumption || reversal.driver || 'Condition ' + String(index + 1)),
                    {header: true}
                );
                autonomyDecisionAppendCell(row, autonomyDecisionDisplayValue(reversal, 'direction'));
                autonomyDecisionAppendCell(
                    row,
                    autonomyDecisionScalar(reversal.scenario_revision_id || reversal.calculated_in || reversal.source || 'Missing — not reported')
                );
                autonomyDecisionAppendCell(
                    row,
                    autonomyDecisionScalar(reversal.evidence_needed || reversal.evidence || 'Missing — not reported')
                );
                autonomyLiveReversalRows.appendChild(row);
            });
            if (!reversals.length) autonomyDecisionAppendEmptyRow(
                autonomyLiveReversalRows, 4, 'No calculated reversal condition is available; no break-even threshold has been invented.'
            );
        }

        function autonomyRenderDecisionProvenance() {
            if (!autonomyLiveBriefProvenance) return;
            autonomyLiveBriefProvenance.replaceChildren();
            const bundleRecord = autonomyPlainObject(autonomyLiveComparisonBundle);
            const bundle = autonomyDecisionBundleSnapshot();
            const entries = [
                ['Comparison bundle ID', autonomyDecisionBundleRecordId(bundleRecord)],
                ['Comparison bundle SHA-256', bundleRecord.bundle_sha256 || autonomyLiveBrief?.comparison_bundle_sha256 || bundle.bundle_hash],
                ['Bundle schema version', bundle.schema_version || bundleRecord.schema_version],
                ['Source confirmation', bundleRecord.source_confirmation_id || bundle?.confirmation?.confirmation_id],
                ['Expected case revision', bundleRecord.expected_case_revision || autonomyLiveBrief?.expected_case_revision],
                ['Brief revision ID', autonomyDecisionBriefRecordId(autonomyLiveBrief)],
                ['Brief revision', autonomyLiveBrief?.revision],
                ['Brief provenance SHA-256', autonomyLiveBrief?.provenance_sha256],
                ['Recommendation ID', autonomyLiveBrief?.recommendation_id],
                ['Recommendation contract version', autonomyLiveBrief?.recommendation_contract_version || autonomyDecisionRecommendation().contract_version],
                ['Recommendation contract digest', autonomyLiveBrief?.recommendation_contract_digest || autonomyDecisionRecommendation().contract_digest],
                ['Bundle canonicalization', bundle.canonicalization],
                ['Brief provenance', autonomyLiveBrief?.provenance],
            ];
            entries.forEach(([term, value]) => {
                const wrapper = autonomyNode('div');
                wrapper.appendChild(autonomyNode('dt', {text: term}));
                wrapper.appendChild(autonomyNode('dd', {text: autonomyDecisionScalar(value)}));
                autonomyLiveBriefProvenance.appendChild(wrapper);
            });
        }

        function autonomyRenderDefinitionEntries(list, entries) {
            if (!list) return;
            list.replaceChildren();
            entries.forEach(([term, value]) => {
                const wrapper = autonomyNode('div');
                wrapper.appendChild(autonomyNode('dt', {text: term}));
                wrapper.appendChild(autonomyNode('dd', {text: autonomyDecisionScalar(value)}));
                list.appendChild(wrapper);
            });
        }

        function autonomyCurrentSignoff() {
            const briefRevisionId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
            return autonomyLiveSignoffs.find((record) => (
                autonomyBriefRevisionId(record?.brief_revision_id) === briefRevisionId
            )) || null;
        }

        function autonomySignoffBlockers() {
            const records = [...autonomyDecisionListValues(autonomyLiveSignoffBlockerRecords)];
            const briefRevisionId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
            Object.entries(AUTONOMY_SIGNOFF_ACTIONS).forEach(([disposition, actionId]) => {
                const reason = autonomyDecisionScopedDisabledReason(actionId, {brief_revision_id: briefRevisionId});
                if (reason) records.push({code: actionId, message: disposition + ': ' + reason});
            });
            return records;
        }

        function autonomyRenderDecisionSignoffs() {
            const briefRevisionId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
            const currentSignoff = autonomyCurrentSignoff();
            const signed = Boolean(currentSignoff);
            const superseded = Boolean(autonomyLiveBrief?.superseded || autonomyLiveBrief?.superseded_by_revision_id);
            if (autonomyLiveSignoffPanel) autonomyLiveSignoffPanel.dataset.signoffState = superseded ? 'superseded' : (signed ? 'signed' : 'unsigned');
            if (autonomyLiveSignoffHeading) autonomyLiveSignoffHeading.textContent = superseded
                ? 'Prior signed revision retained'
                : (signed ? 'Signed Decision Brief' : 'Unsigned Decision Brief');
            if (autonomyLiveSignoffSummary) autonomyLiveSignoffSummary.textContent = signed
                ? 'The named human disposition is frozen against this exact brief, comparison bundle, provenance, and recommendation contract.'
                : 'No application sign-off is recorded for this exact immutable brief revision.';
            if (autonomyLiveSignoffStatus) {
                autonomyLiveSignoffStatus.textContent = superseded ? 'Signed · superseded' : (signed ? 'Signed · immutable' : 'Unsigned');
                autonomyLiveSignoffStatus.dataset.status = superseded ? 'superseded' : (signed ? 'signed' : 'unsigned');
            }
            autonomyDecisionAppendList(
                autonomyLiveSignoffBlockers,
                autonomySignoffBlockers(),
                signed ? 'No sign-off blocker applies to this immutable receipt.' : 'No server sign-off blocker is recorded.'
            );
            const actionButtons = {
                accept: autonomyLiveAcceptBtn,
                reject: autonomyLiveRejectBtn,
                defer: autonomyLiveDeferBtn,
            };
            Object.entries(actionButtons).forEach(([disposition, button]) => {
                if (!button) return;
                const actionId = AUTONOMY_SIGNOFF_ACTIONS[disposition];
                const acknowledgement = autonomySignoffAcknowledgementContract(disposition);
                const allowed = Boolean(briefRevisionId)
                    && autonomyDecisionScopedActionIsAllowed(actionId, {brief_revision_id: briefRevisionId})
                    && acknowledgement.complete
                    && !autonomyLiveSignoffInFlight;
                button.disabled = !allowed;
                button.setAttribute('aria-disabled', String(!allowed));
                button.title = allowed ? '' : (
                    autonomyDecisionScopedDisabledReason(actionId, {brief_revision_id: briefRevisionId})
                    || (!acknowledgement.complete
                        ? 'The server did not publish the required acknowledgement text and version.'
                        : 'The server has not authorized this disposition for the selected brief.')
                );
            });
            if (autonomyLiveSignoffReceipt) autonomyLiveSignoffReceipt.hidden = !currentSignoff;
            if (currentSignoff) autonomyRenderDefinitionEntries(autonomyLiveSignoffReceiptDetails, [
                ['Sign-off ID', autonomyDecisionSignoffRecordId(currentSignoff)],
                ['Disposition', currentSignoff.disposition],
                ['Decision owner', currentSignoff.decision_owner_name || currentSignoff.owner_name],
                ['Rationale', currentSignoff.rationale],
                ['Recorded by authenticated principal', currentSignoff.authenticated_principal || currentSignoff.created_by],
                ['Recorded at', currentSignoff.created_at || currentSignoff.signed_at],
                ['Acknowledgement version', currentSignoff.acknowledgement_version],
                ['Decision snapshot SHA-256', currentSignoff.snapshot_sha256 || currentSignoff.decision_snapshot_sha256],
                ['Recommendation contract', String(currentSignoff.recommendation_contract_version || '') + ' · ' + String(currentSignoff.recommendation_contract_digest || '')],
            ]);
            if (!autonomyLiveSignoffHistoryRows) return;
            autonomyLiveSignoffHistoryRows.replaceChildren();
            autonomyLiveSignoffs.forEach((record) => {
                const row = autonomyNode('tr');
                row.dataset.status = String(record.disposition || 'recorded');
                autonomyDecisionAppendCell(row, autonomyDecisionValue(record, 'disposition'), {header: true});
                autonomyDecisionAppendCell(row, autonomyDecisionScalar(record.decision_owner_name || record.owner_name));
                autonomyDecisionAppendCell(row, autonomyFormatTimestamp(record.created_at || record.signed_at));
                autonomyDecisionAppendCell(
                    row,
                    autonomyDecisionScalar(record.brief_revision_id) + ' · sign-off '
                        + autonomyDecisionSignoffRecordId(record) + ' · snapshot '
                        + autonomyDecisionScalar(record.snapshot_sha256 || record.decision_snapshot_sha256),
                    {code: true}
                );
                autonomyDecisionAppendCell(
                    row,
                    autonomyDecisionScalar(record.recommendation_contract_version) + ' · '
                        + autonomyDecisionScalar(record.recommendation_contract_digest),
                    {code: true}
                );
                autonomyLiveSignoffHistoryRows.appendChild(row);
            });
            if (!autonomyLiveSignoffs.length) autonomyDecisionAppendEmptyRow(
                autonomyLiveSignoffHistoryRows, 5, 'No immutable application sign-off is recorded for this brief revision.'
            );
        }

        function autonomyReportBlockers() {
            const records = [...autonomyDecisionListValues(autonomyLiveReportBlockerRecords)];
            const briefRevisionId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
            ['draft', 'final'].forEach((kind) => {
                const actionId = AUTONOMY_REPORT_ACTIONS[kind];
                const reason = autonomyDecisionScopedDisabledReason(actionId, {brief_revision_id: briefRevisionId});
                if (reason) records.push({code: actionId, message: kind + ': ' + reason});
            });
            return records;
        }

        function autonomyRenderDecisionTechnicalExports() {
            if (!autonomyLiveTechnicalExports) return;
            autonomyLiveTechnicalExports.replaceChildren();
            const seen = new Set();
            autonomyDecisionBundleScenarios().forEach((scenario) => {
                const teaJobId = autonomyTeaJobId(scenario?.attempt?.tea_job_id);
                if (!teaJobId || seen.has(teaJobId)) return;
                seen.add(teaJobId);
                const item = autonomyNode('li');
                item.appendChild(autonomyNode('strong', {text: autonomyDecisionScenarioLabel(scenario) + ' · ' + teaJobId + ': '}));
                [['csv', 'CSV bundle'], ['xlsx', 'XLSX workbook']].forEach(([format, label], index) => {
                    if (index) item.appendChild(document.createTextNode(' · '));
                    const link = autonomyNode('a', {text: label});
                    link.href = '/api/technoeconomic/jobs/' + encodeURIComponent(teaJobId) + '/exports/' + format;
                    link.setAttribute('aria-label', label + ' for ' + autonomyDecisionScenarioLabel(scenario));
                    item.appendChild(link);
                });
                autonomyLiveTechnicalExports.appendChild(item);
            });
            if (!seen.size) autonomyLiveTechnicalExports.appendChild(
                autonomyNode('li', {text: 'No verified scenario export reference is available.'})
            );
        }

        function autonomyRenderDecisionReports() {
            const briefRevisionId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
            const currentSignoff = autonomyCurrentSignoff();
            const canDraft = Boolean(briefRevisionId)
                && autonomyDecisionScopedActionIsAllowed(
                    AUTONOMY_REPORT_ACTIONS.draft, {brief_revision_id: briefRevisionId}
                ) && !autonomyLiveReportGenerationKind;
            const canFinal = Boolean(briefRevisionId && currentSignoff)
                && autonomyDecisionScopedActionIsAllowed(
                    AUTONOMY_REPORT_ACTIONS.final, {brief_revision_id: briefRevisionId}
                ) && !autonomyLiveReportGenerationKind;
            if (autonomyLiveDraftReportBtn) {
                autonomyLiveDraftReportBtn.disabled = !canDraft;
                autonomyLiveDraftReportBtn.setAttribute('aria-disabled', String(!canDraft));
                autonomyLiveDraftReportBtn.textContent = autonomyLiveReportGenerationKind === 'draft'
                    ? 'Generating watermarked draft…' : 'Generate watermarked draft PDF';
                autonomyLiveDraftReportBtn.title = canDraft ? '' : (
                    autonomyDecisionScopedDisabledReason(AUTONOMY_REPORT_ACTIONS.draft, {brief_revision_id: briefRevisionId})
                    || 'The server has not authorized a draft report for this brief.'
                );
            }
            if (autonomyLiveFinalReportBtn) {
                autonomyLiveFinalReportBtn.disabled = !canFinal;
                autonomyLiveFinalReportBtn.setAttribute('aria-disabled', String(!canFinal));
                autonomyLiveFinalReportBtn.textContent = autonomyLiveReportGenerationKind === 'final'
                    ? 'Generating immutable final…' : 'Generate immutable final PDF';
                autonomyLiveFinalReportBtn.title = canFinal ? '' : (
                    autonomyDecisionScopedDisabledReason(AUTONOMY_REPORT_ACTIONS.final, {brief_revision_id: briefRevisionId})
                    || (!currentSignoff ? 'An immutable sign-off is required for a final report.' : 'The server has not authorized a final report.')
                );
            }
            autonomyDecisionAppendList(
                autonomyLiveReportBlockers,
                autonomyReportBlockers(),
                'No server report-generation blocker is recorded.'
            );
            if (autonomyLiveReportSummary) autonomyLiveReportSummary.textContent = autonomyLiveReports.length
                ? 'Every listed PDF is tied to a stored immutable snapshot and is reverified on download.'
                : 'No report revision is recorded for this case. Drafts remain visibly watermarked; finals require sign-off.';
            if (autonomyLiveReportStatus) {
                const finalCount = autonomyLiveReports.filter((record) => record.report_kind === 'final').length;
                const draftCount = autonomyLiveReports.filter((record) => record.report_kind === 'draft').length;
                autonomyLiveReportStatus.textContent = finalCount + ' final · ' + draftCount + ' draft';
                autonomyLiveReportStatus.dataset.status = finalCount ? 'signed' : (draftCount ? 'provisional' : 'not-started');
            }
            if (autonomyLiveReportRows) {
                autonomyLiveReportRows.replaceChildren();
                autonomyLiveReports.forEach((record) => {
                    const reportId = autonomyDecisionReportRecordId(record);
                    const reportKind = record.report_kind === 'final' ? 'final' : 'draft';
                    const row = autonomyNode('tr');
                    row.dataset.reportKind = reportKind;
                    autonomyDecisionAppendCell(
                        row,
                        reportKind === 'final' ? 'Final report' : 'Draft report',
                        {header: true}
                    );
                    autonomyDecisionAppendCell(
                        row,
                        'revision ' + autonomyDecisionValue(record, 'report_revision')
                            + ' · brief ' + autonomyDecisionValue(record, 'brief_revision_id')
                            + ' · sign-off ' + autonomyDecisionValue(record, 'signoff_id')
                            + ' · snapshot ' + autonomyDecisionValue(record, 'snapshot_sha256'),
                        {code: true}
                    );
                    autonomyDecisionAppendCell(
                        row,
                        'SHA-256 ' + autonomyDecisionValue(record, 'pdf_sha256')
                            + ' · bytes ' + autonomyDecisionValue(record, 'byte_count')
                            + ' · pages ' + autonomyDecisionValue(record, 'page_count')
                            + ' · contract ' + autonomyDecisionScalar(record.generation_contract_version || record.renderer_contract_version),
                        {code: true}
                    );
                    autonomyDecisionAppendCell(
                        row,
                        autonomyFormatTimestamp(record.created_at) + ' · '
                            + autonomyDecisionScalar(record.created_by || record.authenticated_principal)
                    );
                    const actionCell = autonomyDecisionAppendCell(
                        row,
                        'Verification ' + autonomyDecisionScalar(
                            autonomyPlainObject(record.verification).status || record.verification_status
                        )
                    );
                    const controls = autonomyNode('span', {className: 'autonomy-live-report-controls'});
                    const canVerify = autonomyDecisionScopedActionIsAllowed(
                        AUTONOMY_REPORT_ACTIONS.verify, {report_id: reportId}, record
                    );
                    const verifyButton = autonomyNode('button', {className: 'autonomy-button autonomy-button-secondary', text: autonomyLiveReportVerificationInFlight.has(reportId) ? 'Verifying…' : 'Verify integrity', type: 'button'});
                    verifyButton.disabled = !reportId || !canVerify || autonomyLiveReportVerificationInFlight.has(reportId);
                    verifyButton.dataset.autonomyVerifyReport = reportId;
                    verifyButton.setAttribute('aria-label', 'Verify report integrity for ' + reportId);
                    controls.appendChild(verifyButton);
                    const canDownload = autonomyDecisionScopedActionIsAllowed(
                        AUTONOMY_REPORT_ACTIONS.download, {report_id: reportId}, record
                    );
                    if (reportId && canDownload) {
                        const link = autonomyNode('a', {text: reportKind === 'draft' ? 'Download watermarked draft PDF' : 'Download immutable final PDF'});
                        link.href = '/api/autonomy/cases/' + encodeURIComponent(autonomyCaseId())
                            + '/reports/' + encodeURIComponent(reportId) + '/download';
                        link.setAttribute('aria-label', 'Download ' + reportKind + ' report ' + reportId + ' after server verification');
                        controls.appendChild(link);
                    } else {
                        controls.appendChild(autonomyNode('span', {text: 'Download blocked by server'}));
                    }
                    actionCell.appendChild(controls);
                    autonomyLiveReportRows.appendChild(row);
                });
                if (!autonomyLiveReports.length) autonomyDecisionAppendEmptyRow(
                    autonomyLiveReportRows, 5, 'No immutable manager report revision is recorded for this case.'
                );
            }
            autonomyRenderDecisionTechnicalExports();
        }

        function autonomyRenderDecisionRolloutStatus() {
            const readiness = autonomyPlainObject(autonomyLiveReleaseReadiness);
            const automated = readiness.automated_gates || readiness.automated_checks;
            const human = readiness.human_shadow_review || readiness.manual_shadow_review;
            autonomyRenderDefinitionEntries(autonomyLiveRolloutDetails, [
                ['Decision Agent enabled', autonomyDecisionHasOwn(readiness, 'decision_agent_enabled') ? readiness.decision_agent_enabled : undefined],
                ['Shadow mode', autonomyDecisionHasOwn(readiness, 'shadow_mode') ? readiness.shadow_mode : undefined],
                ['Automated gates', automated],
                ['Human-reviewed shadow cases', human],
                ['Release ready', autonomyDecisionHasOwn(readiness, 'release_ready') ? readiness.release_ready : undefined],
            ]);
        }

        function autonomyRenderDecisionTimeline() {
            if (!autonomyLiveBriefTimeline) return;
            autonomyLiveBriefTimeline.replaceChildren();
            autonomyLiveComparisonBundles.forEach((bundle) => {
                const item = autonomyNode('li');
                item.appendChild(autonomyNode('span', {text: autonomyDecisionScalar(bundle.created_at)}));
                item.appendChild(autonomyNode('strong', {text: 'Comparison ' + autonomyDecisionBundleRecordId(bundle)}));
                item.appendChild(autonomyNode('small', {
                    text: bundle.stale || bundle.stale_at ? 'Stale immutable snapshot' : (bundle.is_complete ? 'Complete verified snapshot' : 'Partial Results snapshot'),
                }));
                autonomyLiveBriefTimeline.appendChild(item);
            });
            autonomyLiveBriefs.forEach((brief) => {
                const item = autonomyNode('li');
                item.appendChild(autonomyNode('span', {text: autonomyDecisionScalar(brief.created_at)}));
                item.appendChild(autonomyNode('strong', {text: 'Brief ' + autonomyDecisionBriefRecordId(brief)}));
                item.appendChild(autonomyNode('small', {
                    text: brief.superseded || brief.superseded_by_revision_id ? 'Superseded immutable revision' : (brief.stale || brief.stale_at ? 'Stale immutable revision' : 'Immutable brief revision'),
                }));
                autonomyLiveBriefTimeline.appendChild(item);
            });
            autonomyLiveSignoffs.forEach((signoff) => {
                const item = autonomyNode('li');
                item.appendChild(autonomyNode('span', {text: autonomyDecisionScalar(signoff.created_at || signoff.signed_at)}));
                item.appendChild(autonomyNode('strong', {
                    text: 'Sign-off ' + autonomyDecisionSignoffRecordId(signoff) + ' · ' + autonomyDecisionScalar(signoff.disposition),
                }));
                item.appendChild(autonomyNode('small', {
                    text: 'Immutable application sign-off by ' + autonomyDecisionScalar(signoff.decision_owner_name || signoff.owner_name),
                }));
                autonomyLiveBriefTimeline.appendChild(item);
            });
            autonomyLiveReports.forEach((report) => {
                const item = autonomyNode('li');
                item.appendChild(autonomyNode('span', {text: autonomyDecisionScalar(report.created_at)}));
                item.appendChild(autonomyNode('strong', {
                    text: 'Report ' + autonomyDecisionReportRecordId(report) + ' · ' + autonomyDecisionScalar(report.report_kind),
                }));
                item.appendChild(autonomyNode('small', {
                    text: report.report_kind === 'draft' ? 'Visibly watermarked draft' : 'Immutable final report',
                }));
                autonomyLiveBriefTimeline.appendChild(item);
            });
            if (!autonomyLiveBriefTimeline.children.length) {
                const item = autonomyNode('li');
                item.appendChild(autonomyNode('strong', {text: 'No comparison or brief revision recorded'}));
                autonomyLiveBriefTimeline.appendChild(item);
            }
        }

        function autonomyRenderDecisionActions(stateName) {
            const expectedCaseRevision = autonomyExpectedCaseRevision();
            const confirmationId = autonomyExecutionConfirmationId();
            const operatorName = autonomyOperator();
            const bundleId = autonomyDecisionBundleRecordId(autonomyLiveComparisonBundle);
            const bundleHash = String(autonomyLiveComparisonBundle?.bundle_sha256 || '');
            const canBuild = autonomyDecisionActionIsAllowed(AUTONOMY_DECISION_BUILD_ACTIONS)
                && Boolean(expectedCaseRevision && confirmationId && operatorName) && !autonomyDecisionBuildInFlight;
            const canCreate = autonomySelectedBundleMatchesCreateAction()
                && Boolean(expectedCaseRevision && bundleId && /^[0-9a-f]{64}$/.test(bundleHash) && operatorName)
                && !['partial-results', 'verification-failure', 'stale', 'superseded'].includes(stateName)
                && !autonomyBriefCreateInFlight;
            [autonomyLiveBuildComparisonBtn, autonomyLiveDecideBuildBtn].filter(Boolean).forEach((button) => {
                button.disabled = !canBuild;
                button.setAttribute('aria-disabled', String(!canBuild));
                button.textContent = autonomyDecisionBuildInFlight ? 'Building verified comparison…' : 'Build verified comparison';
                button.title = canBuild ? '' : (autonomyDecisionActionDisabledReason(AUTONOMY_DECISION_BUILD_ACTIONS)
                    || (!operatorName ? 'Enter the named operator.' : (!confirmationId ? 'No immutable confirmation is linked.' : 'The server has not allowed this action.')));
            });
            if (autonomyLiveCreateBriefBtn) {
                autonomyLiveCreateBriefBtn.disabled = !canCreate;
                autonomyLiveCreateBriefBtn.setAttribute('aria-disabled', String(!canCreate));
                autonomyLiveCreateBriefBtn.textContent = autonomyBriefCreateInFlight
                    ? 'Creating immutable brief…' : 'Create immutable brief revision';
                autonomyLiveCreateBriefBtn.title = canCreate ? '' : (autonomyDecisionActionDisabledReason(AUTONOMY_DECISION_CREATE_ACTIONS)
                    || 'A complete current verified comparison and named operator are required.');
            }
            const canOpen = autonomyCanOpenLiveBrief();
            if (autonomyLiveDecideOpenBtn) {
                autonomyLiveDecideOpenBtn.disabled = !canOpen;
                autonomyLiveDecideOpenBtn.setAttribute('aria-disabled', String(!canOpen));
            }
            if (autonomyLiveTestReversalBtn) {
                autonomyLiveTestReversalBtn.hidden = !autonomyDecisionActionIsAllowed(AUTONOMY_DECISION_REVERSAL_ACTIONS);
            }
        }

        function autonomyRenderLiveDecisionWorkspace() {
            if (!autonomyLiveDecisionBrief || autonomyContentMode !== 'live') return;
            const activeElement = document.activeElement instanceof HTMLElement
                && autonomyLiveDecisionBrief.contains(document.activeElement)
                ? document.activeElement
                : null;
            const activeElementId = activeElement?.id || '';
            const activeFocusKey = activeElement?.dataset.autonomyDecisionFocus || '';
            const stateName = autonomyDecisionStateName();
            const presentation = autonomyDecisionStatePresentation(stateName);
            autonomyLiveDecisionBrief.dataset.briefState = stateName;
            autonomyLiveDecisionBrief.dataset.agentState = autonomyLiveAgentAvailable ? 'available' : 'unavailable';
            autonomyLiveDecisionBrief.setAttribute('aria-busy', String(stateName === 'loading'));
            if (autonomyLiveBriefHeading) autonomyLiveBriefHeading.textContent = autonomyLiveBrief
                ? 'Decision Brief revision ' + autonomyDecisionScalar(autonomyLiveBrief.revision)
                : 'Verified scenario comparison';
            if (autonomyLiveBriefSummary) {
                autonomyLiveBriefSummary.textContent = presentation[1]
                    + (!autonomyLiveAgentAvailable && stateName !== 'agent-unavailable'
                        ? ' The Decision Agent is unavailable; deterministic comparison remains usable.' : '');
            }
            if (autonomyLiveBriefState) autonomyLiveBriefState.dataset.status = stateName;
            if (autonomyLiveBriefStateHeading) autonomyLiveBriefStateHeading.textContent = presentation[0];
            if (autonomyLiveBriefStateCopy) autonomyLiveBriefStateCopy.textContent = presentation[1];
            if (autonomyLiveBriefAgentNotice) autonomyLiveBriefAgentNotice.hidden = autonomyLiveAgentAvailable;
            autonomyDecisionAppendList(autonomyLiveBriefBlockers, autonomyDecisionBlockerValues(), 'No server blocker is recorded for this snapshot.');
            if (autonomyLiveDecideSummary) autonomyLiveDecideSummary.textContent = presentation[1];
            const bundle = autonomyDecisionBundleSnapshot();
            if (autonomyLiveRequestMatrix) {
                autonomyLiveRequestMatrix.textContent = autonomyDecisionStructuredText(
                    autonomyPlainObject(bundle.comparison).request_matrix
                );
            }
            autonomyRenderDecisionSelectors();
            autonomyRenderDecisionScenarioRows();
            autonomyRenderDecisionMetricRows();
            autonomyRenderDecisionJointOutcomes();
            autonomyRenderDecisionSensitivity();
            autonomyRenderDecisionQuality();
            autonomyRenderDecisionEvidence();
            autonomyRenderDecisionRecommendation(stateName);
            autonomyRenderDecisionReversals();
            autonomyRenderDecisionProvenance();
            autonomyRenderDecisionSignoffs();
            autonomyRenderDecisionReports();
            autonomyRenderDecisionRolloutStatus();
            autonomyRenderDecisionTimeline();
            autonomyRenderDecisionActions(stateName);
            if (autonomySelectedView === 'decision-brief' && !autonomyDecisionBrief?.hidden) {
                autonomyAnnounceDecisionState(stateName, presentation);
            }
            if (activeElement && !activeElement.isConnected) {
                window.requestAnimationFrame(() => {
                    const idTarget = activeElementId ? document.getElementById(activeElementId) : null;
                    const keyedTarget = activeFocusKey
                        ? Array.from(autonomyLiveDecisionBrief.querySelectorAll('[data-autonomy-decision-focus]'))
                            .find((element) => element.dataset.autonomyDecisionFocus === activeFocusKey)
                        : null;
                    (idTarget || keyedTarget)?.focus({preventScroll: true});
                });
            }
        }

        function autonomyDecisionPayloadCaseRevision(payload) {
            const revision = payload?.case?.revision ?? payload?.case_revision ?? payload?.expected_case_revision;
            return Number.isInteger(Number(revision)) && Number(revision) >= 1 ? Number(revision) : null;
        }

        function autonomyAdoptDecisionPayloads(bundlePayload, briefPayload, options = {}) {
            const currentBundleId = options.bundleId
                || autonomyComparisonBundleId(bundlePayload?.current_comparison_bundle_id)
                || autonomyComparisonBundleId(briefPayload?.current_comparison_bundle_id)
                || autonomyDecisionBundleRecordId(autonomyLiveComparisonBundle);
            const currentBriefId = options.briefId
                || autonomyBriefRevisionId(briefPayload?.current_decision_brief_revision_id)
                || autonomyBriefRevisionId(bundlePayload?.current_decision_brief_revision_id)
                || autonomyDecisionBriefRecordId(autonomyLiveBrief);
            const comparisonBundleRecords = autonomyDecisionRecords(
                bundlePayload, 'comparison_bundles', 'comparison_bundle', autonomyDecisionBundleRecordId
            );
            const decisionBriefRecords = autonomyDecisionRecords(
                briefPayload, 'decision_briefs', 'decision_brief', autonomyDecisionBriefRecordId
            );
            if (comparisonBundleRecords.some((record) => record.case_id !== autonomyCaseId())
                || decisionBriefRecords.some((record) => record.case_id !== autonomyCaseId())) {
                const identityError = new Error('The Decision Brief response contained a cross-case identity and was rejected.');
                identityError.code = 'cross_case_identity';
                throw identityError;
            }
            autonomyLiveComparisonBundles = comparisonBundleRecords;
            autonomyLiveBriefs = decisionBriefRecords;
            autonomyLiveComparisonBundle = autonomyLiveComparisonBundles.find((record) => (
                autonomyDecisionBundleRecordId(record) === currentBundleId
            )) || autonomyLiveComparisonBundles.find((record) => !record.stale && !record.superseded_by_bundle_id)
                || autonomyLiveComparisonBundles[0] || null;
            autonomyLiveBrief = autonomyLiveBriefs.find((record) => (
                autonomyDecisionBriefRecordId(record) === currentBriefId
            )) || autonomyLiveBriefs.find((record) => !record.stale && !record.superseded && !record.superseded_by_revision_id)
                || autonomyLiveBriefs[0] || null;
            const briefBundleId = autonomyComparisonBundleId(autonomyLiveBrief?.comparison_bundle_id);
            if (briefBundleId) {
                autonomyLiveComparisonBundle = autonomyLiveComparisonBundles.find((record) => (
                    autonomyDecisionBundleRecordId(record) === briefBundleId
                )) || autonomyLiveComparisonBundle;
            }
            autonomyCollectDecisionAllowedActions(
                autonomyLiveReadiness, autonomyLiveExecution, bundlePayload, briefPayload
            );
            autonomyDecisionBlockers = [
                ...autonomyDecisionListValues(bundlePayload?.decision_blockers),
                ...autonomyDecisionListValues(briefPayload?.decision_blockers),
            ];
        }

        function autonomyAdoptDecisionAuthorityPayloads(signoffPayload, reportPayload) {
            const caseId = autonomyCaseId();
            const briefRevisionId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
            const signoffRecords = autonomyDecisionRecords(
                signoffPayload, 'signoffs', 'signoff', autonomyDecisionSignoffRecordId
            );
            const reportRecords = autonomyDecisionRecords(
                reportPayload, 'reports', 'report', autonomyDecisionReportRecordId
            );
            const crossCase = [...signoffRecords, ...reportRecords].some((record) => (
                record.case_id !== caseId
            ));
            const crossBrief = signoffRecords.some((record) => (
                autonomyBriefRevisionId(record.brief_revision_id) !== briefRevisionId
            ));
            if (crossCase || crossBrief) {
                const identityError = new Error('The sign-off or report response contained a cross-case or cross-brief identity and was rejected.');
                identityError.code = 'cross_authority_identity';
                throw identityError;
            }
            autonomyLiveSignoffs = signoffRecords;
            autonomyLiveReports = reportRecords;
            autonomyLiveSignoffBlockerRecords = [
                ...autonomyDecisionListValues(signoffPayload?.signoff_blockers),
                ...autonomyDecisionListValues(signoffPayload?.blockers),
            ];
            autonomyLiveReportBlockerRecords = [
                ...autonomyDecisionListValues(reportPayload?.report_blockers),
                ...autonomyDecisionListValues(reportPayload?.blockers),
            ];
            autonomyLiveReleaseReadiness = signoffPayload?.release_readiness
                || reportPayload?.release_readiness
                || autonomyLiveBrief?.release_readiness
                || null;
            autonomyCollectAuthorityAllowedActions(signoffPayload, reportPayload);
        }

        async function autonomyLoadDecisionWorkspace(options = {}) {
            const caseId = autonomyCaseId();
            if (!caseId || autonomyContentMode !== 'live') return;
            const revision = ++autonomyDecisionLoadRevision;
            if (autonomyDecisionAbortController) autonomyDecisionAbortController.abort();
            const controller = new AbortController();
            autonomyDecisionAbortController = controller;
            autonomyDecisionLoadError = null;
            if (autonomyLiveDecisionBrief) {
                autonomyLiveDecisionBrief.dataset.briefState = 'loading';
                autonomyLiveDecisionBrief.setAttribute('aria-busy', 'true');
            }
            try {
                const [bundlePayload, briefPayload, reportPayload] = await Promise.all([
                    autonomyFetchComparisonBundles(caseId, controller.signal),
                    autonomyFetchDecisionBriefs(caseId, controller.signal),
                    autonomyFetchDecisionReports(caseId, controller.signal),
                ]);
                if (revision !== autonomyDecisionLoadRevision || controller.signal.aborted || caseId !== autonomyCaseId()) return;
                autonomyAdoptLiveCaseFromPayload(bundlePayload, briefPayload, reportPayload);
                autonomyAdoptDecisionPayloads(bundlePayload, briefPayload, options);
                const selectedBriefId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
                const signoffPayload = await autonomyFetchDecisionSignoffs(
                    caseId, selectedBriefId, controller.signal
                );
                if (revision !== autonomyDecisionLoadRevision || controller.signal.aborted || caseId !== autonomyCaseId()) return;
                const snapshotRevisions = [
                    autonomyDecisionPayloadCaseRevision(bundlePayload),
                    autonomyDecisionPayloadCaseRevision(briefPayload),
                    autonomyDecisionPayloadCaseRevision(reportPayload),
                    autonomyDecisionPayloadCaseRevision(signoffPayload),
                ].filter((value) => value !== null);
                if (snapshotRevisions.length && new Set(snapshotRevisions).size !== 1) {
                    const snapshotError = new Error('The case changed while Decision Brief records were loading. Refresh before relying on this view.');
                    snapshotError.code = 'mixed_case_revision';
                    throw snapshotError;
                }
                const snapshotRevision = snapshotRevisions[0];
                if (snapshotRevision && snapshotRevision < Number(autonomyLiveCase?.revision || 0)) {
                    const snapshotError = new Error('An older Decision Brief snapshot was returned. Refresh before relying on this view.');
                    snapshotError.code = 'mixed_case_revision';
                    throw snapshotError;
                }
                autonomyAdoptLiveCaseFromPayload(signoffPayload);
                autonomyCollectDecisionAllowedActions(bundlePayload, briefPayload, signoffPayload, reportPayload);
                autonomyAdoptDecisionAuthorityPayloads(signoffPayload, reportPayload);
                autonomyDecisionLoadError = null;
                autonomyRenderLiveCase();
                autonomyRenderLiveDecisionWorkspace();
                autonomyRenderStepper(autonomyCurrentFixture());
                autonomySetView(autonomySelectedView, {syncMobile: true});
                if (options.announce) {
                    const stateName = autonomyDecisionStateName();
                    autonomyAnnounceDecisionState(
                        stateName,
                        autonomyDecisionStatePresentation(stateName),
                        'Decision Brief records refreshed from one server-owned comparison snapshot.'
                    );
                }
            } catch (error) {
                if (error?.name === 'AbortError' || revision !== autonomyDecisionLoadRevision) return;
                autonomyDecisionLoadError = {
                    message: error.message || 'The Decision Brief service could not be loaded.',
                    status: error.status,
                    code: error.code,
                };
                autonomyDecisionBlockers = [autonomyDecisionLoadError.message];
                autonomyRenderLiveDecisionWorkspace();
                autonomySetConnectionStatus('Decision Brief service unavailable. Existing case and scenario data remain unchanged.', 'error');
            } finally {
                if (autonomyDecisionAbortController === controller) autonomyDecisionAbortController = null;
                if (revision === autonomyDecisionLoadRevision && autonomyLiveDecisionBrief) {
                    autonomyLiveDecisionBrief.setAttribute('aria-busy', 'false');
                }
            }
        }

        async function autonomySelectComparisonBundle(bundleId) {
            const caseId = autonomyCaseId();
            const safeBundleId = autonomyComparisonBundleId(bundleId);
            if (!caseId || !safeBundleId || autonomyContentMode !== 'live') return;
            try {
                const payload = await autonomyFetchComparisonBundle(caseId, safeBundleId);
                const record = autonomyDecisionRecords(
                    payload, 'comparison_bundles', 'comparison_bundle', autonomyDecisionBundleRecordId
                )[0];
                if (!record || record.case_id !== caseId) throw new Error('The comparison snapshot does not belong to this case.');
                autonomyLiveComparisonBundles = autonomyLiveComparisonBundles.map((item) => (
                    autonomyDecisionBundleRecordId(item) === safeBundleId ? record : item
                ));
                autonomyLiveComparisonBundle = record;
                autonomyLiveBrief = autonomyLiveBriefs.find((brief) => brief.comparison_bundle_id === safeBundleId) || null;
                autonomyCollectDecisionAllowedActions(payload);
                autonomyDecisionBlockers = autonomyDecisionListValues(payload.decision_blockers);
                const selectedBriefId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
                const [signoffPayload, reportPayload] = await Promise.all([
                    autonomyFetchDecisionSignoffs(caseId, selectedBriefId),
                    autonomyFetchDecisionReports(caseId),
                ]);
                autonomyAdoptLiveCaseFromPayload(signoffPayload, reportPayload);
                autonomyCollectDecisionAllowedActions(payload, signoffPayload, reportPayload);
                autonomyAdoptDecisionAuthorityPayloads(signoffPayload, reportPayload);
                autonomyRenderLiveDecisionWorkspace();
                const stateName = autonomyDecisionStateName();
                autonomyAnnounceDecisionState(
                    stateName,
                    autonomyDecisionStatePresentation(stateName),
                    'Opened immutable comparison snapshot ' + safeBundleId + '.'
                );
            } catch (error) {
                autonomyDecisionLoadError = {message: error.message || 'The comparison snapshot could not be opened.'};
                autonomyRenderLiveDecisionWorkspace();
            }
        }

        async function autonomySelectDecisionBrief(briefRevisionId) {
            const caseId = autonomyCaseId();
            const safeBriefRevisionId = autonomyBriefRevisionId(briefRevisionId);
            if (!caseId || !safeBriefRevisionId || autonomyContentMode !== 'live') return;
            try {
                const payload = await autonomyFetchDecisionBrief(caseId, safeBriefRevisionId);
                const record = autonomyDecisionRecords(
                    payload, 'decision_briefs', 'decision_brief', autonomyDecisionBriefRecordId
                )[0];
                if (!record || record.case_id !== caseId) throw new Error('The Decision Brief revision does not belong to this case.');
                autonomyLiveBriefs = autonomyLiveBriefs.map((item) => (
                    autonomyDecisionBriefRecordId(item) === safeBriefRevisionId ? record : item
                ));
                autonomyLiveBrief = record;
                const bundleId = autonomyComparisonBundleId(record.comparison_bundle_id);
                if (bundleId) autonomyLiveComparisonBundle = autonomyLiveComparisonBundles.find((item) => (
                    autonomyDecisionBundleRecordId(item) === bundleId
                )) || autonomyLiveComparisonBundle;
                autonomyCollectDecisionAllowedActions(payload);
                autonomyDecisionBlockers = autonomyDecisionListValues(payload.decision_blockers);
                const [signoffPayload, reportPayload] = await Promise.all([
                    autonomyFetchDecisionSignoffs(caseId, safeBriefRevisionId),
                    autonomyFetchDecisionReports(caseId),
                ]);
                autonomyAdoptLiveCaseFromPayload(signoffPayload, reportPayload);
                autonomyCollectDecisionAllowedActions(payload, signoffPayload, reportPayload);
                autonomyAdoptDecisionAuthorityPayloads(signoffPayload, reportPayload);
                autonomyRenderLiveDecisionWorkspace();
                const stateName = autonomyDecisionStateName();
                autonomyAnnounceDecisionState(
                    stateName,
                    autonomyDecisionStatePresentation(stateName),
                    'Opened immutable Decision Brief revision ' + safeBriefRevisionId + '.'
                );
            } catch (error) {
                autonomyDecisionLoadError = {message: error.message || 'The Decision Brief revision could not be opened.'};
                autonomyRenderLiveDecisionWorkspace();
            }
        }

        async function autonomyBuildComparisonBundle() {
            const caseId = autonomyCaseId();
            const expectedCaseRevision = autonomyExpectedCaseRevision();
            const confirmationId = autonomyExecutionConfirmationId();
            const operatorName = autonomyOperator();
            if (!caseId || !autonomyDecisionActionIsAllowed(AUTONOMY_DECISION_BUILD_ACTIONS)
                || !expectedCaseRevision || !confirmationId || !operatorName || autonomyDecisionBuildInFlight) return;
            autonomyDecisionBuildInFlight = true;
            autonomyDecisionLoadError = null;
            autonomyRenderLiveDecisionWorkspace();
            try {
                const payload = await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(caseId) + '/comparison-bundles',
                    {
                        method: 'POST',
                        body: {
                            expected_case_revision: expectedCaseRevision,
                            confirmation_id: confirmationId,
                            operator_name: operatorName,
                        },
                    }
                );
                const bundleId = autonomyDecisionBundleRecordId(payload.comparison_bundle);
                autonomyCollectDecisionAllowedActions(payload);
                await autonomyLoadDecisionWorkspace({bundleId, announce: true});
            } catch (error) {
                autonomyDecisionLoadError = {
                    message: error.status === 409
                        ? 'The case changed before comparison creation. Refresh the case and review the exact confirmation again.'
                        : (error.message || 'The verified comparison could not be created.'),
                    status: error.status,
                    code: error.code,
                };
                autonomyDecisionBlockers = [
                    ...autonomyDecisionListValues(error.blockers),
                    autonomyDecisionLoadError.message,
                ];
                autonomyRenderLiveDecisionWorkspace();
            } finally {
                autonomyDecisionBuildInFlight = false;
                autonomyRenderLiveDecisionWorkspace();
            }
        }

        async function autonomyCreateDecisionBrief() {
            const caseId = autonomyCaseId();
            const expectedCaseRevision = autonomyExpectedCaseRevision();
            const comparisonBundleId = autonomyDecisionBundleRecordId(autonomyLiveComparisonBundle);
            const bundleSha256 = String(autonomyLiveComparisonBundle?.bundle_sha256 || '');
            const operatorName = autonomyOperator();
            if (!caseId || !autonomySelectedBundleMatchesCreateAction()
                || !expectedCaseRevision || !comparisonBundleId || !/^[0-9a-f]{64}$/.test(bundleSha256)
                || !operatorName || autonomyBriefCreateInFlight) return;
            const signature = String(expectedCaseRevision) + '|' + comparisonBundleId + '|' + bundleSha256;
            if (signature !== autonomyBriefCreationSignature || !autonomyBriefCreationIdempotencyKey) {
                autonomyBriefCreationSignature = signature;
                autonomyBriefCreationIdempotencyKey = autonomyClientMessageId();
            }
            autonomyBriefCreateInFlight = true;
            autonomyDecisionLoadError = null;
            autonomyRenderLiveDecisionWorkspace();
            try {
                const payload = await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(caseId) + '/decision-briefs',
                    {
                        method: 'POST',
                        body: {
                            expected_case_revision: expectedCaseRevision,
                            comparison_bundle_id: comparisonBundleId,
                            bundle_sha256: bundleSha256,
                            operator_name: operatorName,
                            idempotency_key: autonomyBriefCreationIdempotencyKey,
                        },
                    }
                );
                const briefRevisionId = autonomyDecisionBriefRecordId(payload.decision_brief);
                autonomyAdoptLiveCaseFromPayload(payload);
                autonomyCollectDecisionAllowedActions(payload);
                await autonomyLoadDecisionWorkspace({briefId: briefRevisionId, bundleId: comparisonBundleId, announce: true});
            } catch (error) {
                autonomyDecisionLoadError = {
                    message: error.status === 409
                        ? 'The case or comparison snapshot changed before brief creation. Refresh without changing this immutable bundle.'
                        : (error.message || 'The immutable Decision Brief revision could not be created.'),
                    status: error.status,
                    code: error.code,
                };
                autonomyDecisionBlockers = [
                    ...autonomyDecisionListValues(error.blockers),
                    autonomyDecisionLoadError.message,
                ];
                autonomyRenderLiveDecisionWorkspace();
            } finally {
                autonomyBriefCreateInFlight = false;
                autonomyRenderLiveDecisionWorkspace();
            }
        }

        function autonomySignoffActionId(disposition) {
            return Object.prototype.hasOwnProperty.call(AUTONOMY_SIGNOFF_ACTIONS, disposition)
                ? AUTONOMY_SIGNOFF_ACTIONS[disposition] : '';
        }

        function autonomySignoffAcknowledgementContract(disposition) {
            const briefRevisionId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
            const action = autonomyDecisionScopedAction(
                autonomySignoffActionId(disposition), {brief_revision_id: briefRevisionId}
            );
            const acknowledgement = autonomyPlainObject(action?.acknowledgement);
            const text = String(action?.acknowledgement_text || acknowledgement.text || '');
            const version = String(action?.acknowledgement_version || acknowledgement.version || '');
            return {text, version, complete: Boolean(text && version)};
        }

        function autonomyWarningAcknowledgementValue(record) {
            if (typeof record === 'string') return record;
            const warning = autonomyPlainObject(record);
            const value = warning.acknowledgement_id || warning.warning_id || warning.code || warning.digest;
            return typeof value === 'string' ? value : '';
        }

        function autonomyRequiredWarningAcknowledgements(disposition) {
            const briefRevisionId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
            const action = autonomyDecisionScopedAction(
                autonomySignoffActionId(disposition), {brief_revision_id: briefRevisionId}
            );
            const actionRequirements = Array.isArray(action?.required_warning_acknowledgements)
                ? action.required_warning_acknowledgements
                : (Array.isArray(action?.required_acknowledgements) ? action.required_acknowledgements : []);
            const recommendationRequirements = autonomyDecisionListValues(
                autonomyDecisionRecommendation().required_acknowledgements
            );
            const records = actionRequirements.length ? actionRequirements : recommendationRequirements;
            const byValue = new Map();
            records.forEach((record) => {
                const value = autonomyWarningAcknowledgementValue(record);
                if (value) byValue.set(value, record);
            });
            return Array.from(byValue.entries()).map(([value, record]) => ({value, record}));
        }

        function autonomyFixtureSignoffFormIsComplete() {
            return Boolean(
                autonomyCurrentFixture().signoffAllowed
                && autonomyPanel.querySelector('[name="autonomyDisposition"]:checked')
                && autonomySignoffOwner?.value.trim()
                && autonomySignoffRationale?.value.trim()
                && autonomySignoffAck?.checked
            );
        }

        function autonomyUpdateFixtureSignoffSubmitState() {
            if (autonomySignoffSubmitBtn) {
                autonomySignoffSubmitBtn.disabled = !autonomyFixtureSignoffFormIsComplete();
            }
        }

        function autonomyLiveSignoffFormIsComplete() {
            const disposition = autonomyPanel.querySelector('[name="autonomyLiveDisposition"]:checked')?.value || '';
            const briefRevisionId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
            const actionId = autonomySignoffActionId(disposition);
            const acknowledgement = autonomySignoffAcknowledgementContract(disposition);
            const requiredWarnings = autonomyRequiredWarningAcknowledgements(disposition);
            const selectedWarnings = autonomySelectedWarningAcknowledgements();
            return Boolean(
                !autonomyLiveSignoffInFlight
                && actionId
                && briefRevisionId
                && autonomyDecisionScopedActionIsAllowed(actionId, {brief_revision_id: briefRevisionId})
                && acknowledgement.complete
                && autonomyLiveSignoffOwner?.value.trim()
                && autonomyLiveSignoffRationale?.value.trim()
                && autonomyLiveSignoffAck?.checked
                && requiredWarnings.every(({value}) => selectedWarnings.includes(value))
            );
        }

        function autonomyUpdateLiveSignoffSubmitState() {
            if (autonomyLiveSignoffSubmitBtn) {
                autonomyLiveSignoffSubmitBtn.disabled = !autonomyLiveSignoffFormIsComplete();
            }
        }

        function autonomyRenderLiveSignoffSnapshot() {
            if (!autonomyLiveSignoffSnapshot) return;
            autonomyLiveSignoffSnapshot.replaceChildren();
            const recommendation = autonomyDecisionRecommendation();
            const bundle = autonomyLiveComparisonBundle || {};
            const entries = [
                ['Case', autonomyCaseId() + ' · revision ' + autonomyDecisionScalar(autonomyExpectedCaseRevision())],
                ['Decision Brief', autonomyDecisionBriefRecordId(autonomyLiveBrief) + ' · revision ' + autonomyDecisionScalar(autonomyLiveBrief?.revision)],
                ['Recommendation', autonomyDecisionScalar(recommendation.classification) + ' · confidence ' + autonomyDecisionScalar(recommendation.confidence)],
                ['Comparison bundle', autonomyDecisionBundleRecordId(bundle) + ' · ' + autonomyDecisionScalar(bundle.bundle_sha256)],
                ['Brief provenance', autonomyDecisionScalar(autonomyLiveBrief?.provenance_sha256)],
                ['Recommendation contract', autonomyDecisionScalar(autonomyLiveBrief?.recommendation_contract_version || recommendation.contract_version) + ' · ' + autonomyDecisionScalar(autonomyLiveBrief?.recommendation_contract_digest || recommendation.contract_digest)],
            ];
            entries.forEach(([label, value]) => {
                const wrapper = autonomyNode('div');
                wrapper.appendChild(autonomyNode('span', {text: label}));
                wrapper.appendChild(autonomyNode('strong', {text: value}));
                autonomyLiveSignoffSnapshot.appendChild(wrapper);
            });
        }

        function autonomyRenderLiveWarningAcknowledgements(disposition) {
            const requirements = autonomyRequiredWarningAcknowledgements(disposition);
            if (autonomyLiveWarningAcknowledgements) autonomyLiveWarningAcknowledgements.hidden = requirements.length === 0;
            if (!autonomyLiveWarningAcknowledgementList) return;
            autonomyLiveWarningAcknowledgementList.replaceChildren();
            requirements.forEach(({value, record}, index) => {
                const input = autonomyNode('input', {type: 'checkbox'});
                input.id = 'autonomyLiveWarningAck' + String(index + 1);
                input.dataset.autonomyWarningAcknowledgement = value;
                input.addEventListener('change', autonomyUpdateLiveSignoffSubmitState);
                const label = autonomyNode('label', {className: 'autonomy-checkbox'});
                label.htmlFor = input.id;
                label.appendChild(input);
                const warning = autonomyPlainObject(record);
                label.appendChild(autonomyNode('span', {
                    text: autonomyDecisionScalar(warning.message || warning.warning || warning.label || record),
                }));
                autonomyLiveWarningAcknowledgementList.appendChild(label);
            });
        }

        function autonomyOpenLiveSignoff(disposition, trigger) {
            const actionId = autonomySignoffActionId(disposition);
            const briefRevisionId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
            const acknowledgement = autonomySignoffAcknowledgementContract(disposition);
            if (!actionId || !briefRevisionId || !autonomyDecisionScopedActionIsAllowed(
                actionId, {brief_revision_id: briefRevisionId}
            ) || !acknowledgement.complete) {
                autonomyAnnounce('The server has not authorized that disposition for this exact Decision Brief revision.');
                return;
            }
            autonomyRenderLiveSignoffSnapshot();
            autonomyPanel.querySelectorAll('[name="autonomyLiveDisposition"]').forEach((input) => {
                const inputDisposition = input.value;
                const allowed = autonomyDecisionScopedActionIsAllowed(
                    autonomySignoffActionId(inputDisposition), {brief_revision_id: briefRevisionId}
                );
                input.disabled = !allowed;
                input.checked = allowed && inputDisposition === disposition;
            });
            if (autonomyLiveSignoffOwner && !autonomyLiveSignoffOwner.value.trim()) {
                autonomyLiveSignoffOwner.value = autonomyOperator();
            }
            if (autonomyLiveSignoffAck) autonomyLiveSignoffAck.checked = false;
            if (autonomyLiveSignoffAckCopy) autonomyLiveSignoffAckCopy.textContent = acknowledgement.text;
            if (autonomyLiveSignoffError) autonomyLiveSignoffError.hidden = true;
            autonomyRenderLiveWarningAcknowledgements(disposition);
            autonomyUpdateLiveSignoffSubmitState();
            autonomyOpenDialog(autonomyLiveSignoffDialog, trigger);
            window.requestAnimationFrame(() => autonomyLiveSignoffOwner?.focus({preventScroll: true}));
        }

        function autonomySelectedWarningAcknowledgements() {
            return Array.from(
                autonomyLiveWarningAcknowledgementList?.querySelectorAll('[data-autonomy-warning-acknowledgement]:checked') || []
            ).map((input) => input.dataset.autonomyWarningAcknowledgement).filter(Boolean);
        }

        async function autonomySubmitLiveSignoff() {
            const caseId = autonomyCaseId();
            const briefRevisionId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
            const expectedCaseRevision = autonomyExpectedCaseRevision();
            const disposition = autonomyPanel.querySelector('[name="autonomyLiveDisposition"]:checked')?.value || '';
            const actionId = autonomySignoffActionId(disposition);
            const acknowledgement = autonomySignoffAcknowledgementContract(disposition);
            const owner = autonomyLiveSignoffOwner?.value.trim() || '';
            const rationale = autonomyLiveSignoffRationale?.value.trim() || '';
            const acknowledgementAccepted = Boolean(autonomyLiveSignoffAck?.checked);
            const requirements = autonomyRequiredWarningAcknowledgements(disposition);
            const selectedWarnings = autonomySelectedWarningAcknowledgements();
            const allWarningsAccepted = requirements.every(({value}) => selectedWarnings.includes(value));
            const allowed = Boolean(actionId && briefRevisionId) && autonomyDecisionScopedActionIsAllowed(
                actionId, {brief_revision_id: briefRevisionId}
            );
            if (!caseId || !expectedCaseRevision || !allowed || !acknowledgement.complete || !owner || !rationale
                || !acknowledgementAccepted || !allWarningsAccepted || autonomyLiveSignoffInFlight) {
                if (autonomyLiveSignoffError) {
                    autonomyLiveSignoffError.hidden = false;
                    autonomyLiveSignoffError.textContent = !allowed
                        ? 'The server has not authorized this disposition for the selected immutable brief.'
                        : (!allWarningsAccepted
                            ? 'Acknowledge every exact provisional evidence or convergence warning.'
                            : 'Choose an allowed disposition, type the decision owner and rationale, and acknowledge the immutable snapshot.');
                    autonomyLiveSignoffError.focus();
                }
                return;
            }
            const warningValues = requirements.map(({value}) => value);
            const signature = [
                expectedCaseRevision, briefRevisionId, disposition, owner, rationale,
                acknowledgement.text, acknowledgement.version, ...warningValues,
            ].join('|');
            if (signature !== autonomyLiveSignoffSignature || !autonomyLiveSignoffIdempotencyKey) {
                autonomyLiveSignoffSignature = signature;
                autonomyLiveSignoffIdempotencyKey = autonomyClientMessageId();
            }
            autonomyLiveSignoffInFlight = true;
            autonomyLiveSignoffDialog?.setAttribute('aria-busy', 'true');
            if (autonomyLiveSignoffSubmitBtn) {
                autonomyLiveSignoffSubmitBtn.disabled = true;
                autonomyLiveSignoffSubmitBtn.textContent = 'Recording immutable sign-off…';
            }
            try {
                const payload = await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(caseId)
                        + '/decision-briefs/' + encodeURIComponent(briefRevisionId) + '/signoffs',
                    {
                        method: 'POST',
                        headers: {'X-Autonomy-Human-Action': '1'},
                        body: {
                            expected_case_revision: expectedCaseRevision,
                            disposition,
                            decision_owner_name: owner,
                            rationale,
                            acknowledgement_text: acknowledgement.text,
                            acknowledgement_version: acknowledgement.version,
                            provisional_warning_acknowledgements: warningValues,
                            idempotency_key: autonomyLiveSignoffIdempotencyKey,
                        },
                    }
                );
                autonomyAdoptLiveCaseFromPayload(payload);
                autonomyCloseDialog(autonomyLiveSignoffDialog, {force: true});
                await autonomyLoadDecisionWorkspace({briefId: briefRevisionId, announce: true});
                autonomyAnnounce('Immutable application sign-off recorded for ' + briefRevisionId + '.');
            } catch (error) {
                if (autonomyLiveSignoffError) {
                    autonomyLiveSignoffError.hidden = false;
                    autonomyLiveSignoffError.textContent = error.status === 409
                        ? 'The case, brief, bundle, provenance, or recommendation identity changed. Refresh and review the exact snapshot again.'
                        : (error.message || 'The immutable application sign-off could not be recorded.');
                    autonomyLiveSignoffError.focus();
                }
            } finally {
                autonomyLiveSignoffInFlight = false;
                autonomyLiveSignoffDialog?.setAttribute('aria-busy', 'false');
                if (autonomyLiveSignoffSubmitBtn) {
                    autonomyLiveSignoffSubmitBtn.textContent = 'Record immutable sign-off';
                }
                autonomyUpdateLiveSignoffSubmitState();
                autonomyRenderLiveDecisionWorkspace();
            }
        }

        async function autonomyGenerateDecisionReport(reportKind) {
            const caseId = autonomyCaseId();
            const briefRevisionId = autonomyDecisionBriefRecordId(autonomyLiveBrief);
            const expectedCaseRevision = autonomyExpectedCaseRevision();
            const currentSignoff = autonomyCurrentSignoff();
            const signoffId = reportKind === 'final' ? autonomyDecisionSignoffRecordId(currentSignoff) : null;
            const actionId = AUTONOMY_REPORT_ACTIONS[reportKind];
            if (!caseId || !briefRevisionId || !expectedCaseRevision || !actionId
                || (reportKind === 'final' && !signoffId)
                || !autonomyDecisionScopedActionIsAllowed(actionId, {brief_revision_id: briefRevisionId})
                || autonomyLiveReportGenerationKind) return;
            const signature = [expectedCaseRevision, reportKind, briefRevisionId, signoffId || 'unsigned'].join('|');
            let idempotencyKey = autonomyLiveReportIdempotencyKeys.get(signature);
            if (!idempotencyKey) {
                idempotencyKey = autonomyClientMessageId();
                autonomyLiveReportIdempotencyKeys.set(signature, idempotencyKey);
            }
            autonomyLiveReportGenerationKind = reportKind;
            autonomyRenderLiveDecisionWorkspace();
            try {
                const payload = await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(caseId) + '/reports',
                    {
                        method: 'POST',
                        headers: {'X-Autonomy-Human-Action': '1'},
                        body: {
                            expected_case_revision: expectedCaseRevision,
                            report_kind: reportKind,
                            brief_revision_id: briefRevisionId,
                            signoff_id: signoffId,
                            idempotency_key: idempotencyKey,
                        },
                    }
                );
                const reportId = autonomyDecisionReportRecordId(payload.report);
                autonomyAdoptLiveCaseFromPayload(payload);
                await autonomyLoadDecisionWorkspace({briefId: briefRevisionId, announce: true});
                autonomyAnnounce((reportKind === 'draft' ? 'Watermarked draft' : 'Immutable final')
                    + ' manager report ' + reportId + ' generated and stored.');
            } catch (error) {
                autonomyLiveReportBlockerRecords = [
                    ...autonomyDecisionListValues(error.blockers),
                    {code: error.code || 'report_generation_failed', message: error.message || 'The manager report could not be generated.'},
                ];
                autonomyAnnounce(error.status === 409
                    ? 'The report snapshot changed before generation. Refresh and review the exact identities again.'
                    : (error.message || 'The manager report could not be generated.'));
            } finally {
                autonomyLiveReportGenerationKind = '';
                autonomyRenderLiveDecisionWorkspace();
            }
        }

        async function autonomyVerifyDecisionReport(reportId) {
            const safeReportId = autonomyReportId(reportId);
            const record = autonomyLiveReports.find((item) => autonomyDecisionReportRecordId(item) === safeReportId);
            if (!safeReportId || !record || !autonomyDecisionScopedActionIsAllowed(
                AUTONOMY_REPORT_ACTIONS.verify, {report_id: safeReportId}, record
            ) || autonomyLiveReportVerificationInFlight.has(safeReportId)) return;
            autonomyLiveReportVerificationInFlight.add(safeReportId);
            autonomyRenderLiveDecisionWorkspace();
            try {
                const payload = await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(autonomyCaseId())
                        + '/reports/' + encodeURIComponent(safeReportId) + '/verify',
                    {method: 'POST', headers: {'X-Autonomy-Human-Action': '1'}}
                );
                const verified = autonomyDecisionRecords(
                    payload, 'reports', 'report', autonomyDecisionReportRecordId
                )[0];
                if (verified && verified.case_id !== autonomyCaseId()) {
                    throw new Error('The report verification response contained a cross-case identity and was rejected.');
                }
                await autonomyLoadDecisionWorkspace({briefId: autonomyDecisionBriefRecordId(autonomyLiveBrief)});
                autonomyAnnounce('Report ' + safeReportId + ' passed stored snapshot and file integrity verification.');
            } catch (error) {
                autonomyLiveReportBlockerRecords = [
                    {code: error.code || 'report_verification_failed', message: error.message || 'Report verification failed.'},
                ];
                autonomyAnnounce(error.message || 'Report verification failed. Download remains blocked.');
            } finally {
                autonomyLiveReportVerificationInFlight.delete(safeReportId);
                autonomyRenderLiveDecisionWorkspace();
            }
        }

        function autonomyAdoptLiveCaseFromPayload(...payloads) {
            payloads.forEach((payload) => {
                const incomingCase = autonomyPlainObject(payload?.case);
                const incomingCaseId = autonomyCaseId(incomingCase.case_id);
                const incomingRevision = Number(incomingCase.revision || 0);
                const currentRevision = Number(autonomyLiveCase?.revision || 0);
                if (incomingCaseId && incomingCaseId === autonomyCaseId()
                    && incomingRevision >= currentRevision) {
                    autonomyLiveCase = incomingCase;
                    autonomyCases = autonomyCases.map((item) => item.case_id === incomingCaseId ? incomingCase : item);
                    if (payload?.readiness && typeof payload.readiness === 'object') {
                        autonomyLiveReadiness = payload.readiness;
                    }
                }
            });
        }

        function autonomySetScenarioWorkspaceBusy(busy) {
            [autonomyLiveScenarioGrid, autonomyLiveScenarioMatrix, autonomyLiveJobList]
                .filter(Boolean).forEach((element) => element.toggleAttribute('aria-busy', busy));
            if (!busy) return;
            [autonomyCreateBaselineBtn, autonomyCreateAlternativeBtn, autonomyOpenLiveConfirmationBtn]
                .filter(Boolean).forEach((button) => {
                    button.disabled = true;
                    button.setAttribute('aria-disabled', 'true');
                });
            autonomyLiveScenarioGrid?.querySelectorAll('button, input').forEach((control) => {
                control.disabled = true;
                control.setAttribute('aria-disabled', 'true');
            });
        }

        async function autonomyLoadScenarioWorkspace(options = {}) {
            const caseId = autonomyCaseId();
            if (!caseId || autonomyContentMode !== 'live') return;
            const revision = ++autonomyScenarioLoadRevision;
            if (autonomyScenarioAbortController) autonomyScenarioAbortController.abort();
            const controller = new AbortController();
            autonomyScenarioAbortController = controller;
            autonomySetScenarioWorkspaceBusy(true);
            if (autonomyScenarioStatus) autonomyScenarioStatus.textContent = 'Loading durable scenarios and deterministic comparison…';
            try {
                const [scenarioPayload, executionPayload] = await Promise.all([
                    autonomyFetchScenarioCollection(caseId, controller.signal),
                    autonomyFetchExecution(caseId, controller.signal),
                ]);
                if (revision !== autonomyScenarioLoadRevision || controller.signal.aborted || caseId !== autonomyCaseId()) return;
                let comparisonPayload = scenarioPayload;
                if (!scenarioPayload.comparison) {
                    comparisonPayload = await autonomyFetchScenarioComparison(caseId, controller.signal);
                }
                const payloads = [scenarioPayload, comparisonPayload, executionPayload];
                const payloadRevisions = payloads.map((payload) => Number(payload?.case?.revision))
                    .filter((value) => Number.isInteger(value) && value >= 1);
                if (payloadRevisions.length && new Set(payloadRevisions).size !== 1) {
                    const snapshotError = new Error('The case changed while scenario review data was loading. Refreshing one consistent revision.');
                    snapshotError.code = 'mixed_case_revision';
                    throw snapshotError;
                }
                const snapshotRevision = payloadRevisions[0] || 0;
                if (snapshotRevision && snapshotRevision < Number(autonomyLiveCase?.revision || 0)) {
                    const snapshotError = new Error('An older case snapshot was returned. Refreshing before showing scenario review data.');
                    snapshotError.code = 'mixed_case_revision';
                    throw snapshotError;
                }
                autonomyAdoptLiveCaseFromPayload(scenarioPayload, comparisonPayload, executionPayload);
                const historicalScenarios = Array.isArray(scenarioPayload.scenarios)
                    ? scenarioPayload.scenarios.filter((scenario) => autonomyScenarioId(scenario?.scenario_id))
                    : [];
                const currentScenarios = Array.isArray(scenarioPayload.current_scenarios)
                    ? scenarioPayload.current_scenarios
                    : historicalScenarios.filter((scenario) => !scenario?.superseded_by_revision_id);
                const currentIds = new Set(currentScenarios.map((scenario) => autonomyScenarioId(scenario?.scenario_id)).filter(Boolean));
                const withHistory = currentScenarios
                    .filter((scenario) => autonomyScenarioId(scenario?.scenario_id))
                    .map((scenario) => ({
                        ...scenario,
                        revision_history: historicalScenarios
                            .filter((revisionRecord) => revisionRecord.scenario_id === scenario.scenario_id)
                            .sort((left, right) => Number(right.revision || 0) - Number(left.revision || 0)),
                    }));
                const historicalOnly = [];
                const historicalIds = Array.from(new Set(historicalScenarios
                    .map((scenario) => autonomyScenarioId(scenario?.scenario_id)).filter(Boolean)));
                historicalIds.filter((scenarioId) => !currentIds.has(scenarioId)).forEach((scenarioId) => {
                    const history = historicalScenarios.filter((record) => record.scenario_id === scenarioId)
                        .sort((left, right) => Number(right.revision || 0) - Number(left.revision || 0));
                    if (history[0]) historicalOnly.push({...history[0], audit_only: true, revision_history: history});
                });
                autonomyLiveScenarios = [...withHistory, ...historicalOnly];
                autonomyLiveComparison = comparisonPayload.comparison || comparisonPayload;
                autonomyLiveExecution = executionPayload.execution || executionPayload.execution_status || null;
                autonomyCollectAllowedActions(
                    autonomyLiveReadiness,
                    scenarioPayload,
                    comparisonPayload,
                    executionPayload,
                    autonomyLiveExecution
                );
                autonomyCollectDecisionAllowedActions(
                    autonomyLiveReadiness,
                    scenarioPayload,
                    comparisonPayload,
                    executionPayload,
                    autonomyLiveExecution
                );
                autonomyExecutionPollFailures = 0;
                autonomyRenderLiveCase();
                autonomyRenderLiveScenarios();
                autonomyRenderLiveExecution({announce: options.announce === true});
                await autonomyLoadDecisionWorkspace();
                autonomySetScenarioWorkspaceBusy(false);
                autonomyScheduleExecutionPoll();
            } catch (error) {
                if (error?.name === 'AbortError' || revision !== autonomyScenarioLoadRevision) return;
                if (error?.code === 'mixed_case_revision' && Number(options.snapshotRetry || 0) < 2) {
                    if (autonomyScenarioStatus) autonomyScenarioStatus.textContent = error.message;
                    window.setTimeout(() => autonomyLoadScenarioWorkspace({
                        ...options,
                        snapshotRetry: Number(options.snapshotRetry || 0) + 1,
                    }), 150);
                    return;
                }
                if (autonomyScenarioStatus) {
                    autonomyScenarioStatus.textContent = error.message || 'The durable scenario workspace could not be loaded.';
                    autonomyScenarioStatus.dataset.status = 'error';
                }
                autonomySetConnectionStatus('Scenario service unavailable. The durable case remains unchanged.', 'error');
            } finally {
                if (autonomyScenarioAbortController === controller) autonomyScenarioAbortController = null;
            }
        }

        function autonomyInvalidateExecutionPoll() {
            autonomyExecutionPollRevision += 1;
            window.clearTimeout(autonomyExecutionPollTimer);
            autonomyExecutionPollTimer = null;
            if (autonomyExecutionAbortController) autonomyExecutionAbortController.abort();
            autonomyExecutionAbortController = null;
        }

        function autonomyScheduleExecutionPoll(delay = null) {
            autonomyInvalidateExecutionPoll();
            if (autonomyContentMode !== 'live' || !autonomyCaseId()) return;
            const jobs = autonomyExecutionJobs({latestOnly: true});
            if (!jobs.some((job) => AUTONOMY_ACTIVE_TEA_STATES.includes(String(job.state)))) return;
            const revision = autonomyExecutionPollRevision;
            const wait = delay === null
                ? (jobs.some((job) => job.state === 'running' || job.state === 'leased') ? 1000 : 1500)
                : delay;
            autonomyExecutionPollTimer = window.setTimeout(() => autonomyPollExecution(revision), wait);
        }

        async function autonomyPollExecution(revision) {
            const caseId = autonomyCaseId();
            if (!caseId || revision !== autonomyExecutionPollRevision || autonomyContentMode !== 'live') return;
            const controller = new AbortController();
            autonomyExecutionAbortController = controller;
            try {
                const payload = await autonomyFetchExecution(caseId, controller.signal);
                if (revision !== autonomyExecutionPollRevision || caseId !== autonomyCaseId()) return;
                const priorStates = autonomyExecutionJobs({latestOnly: true})
                    .map((job) => job.tea_job_id + ':' + job.state).join('|');
                const priorCaseRevision = autonomyExpectedCaseRevision();
                autonomyAdoptLiveCaseFromPayload(payload);
                autonomyLiveExecution = payload.execution || payload.execution_status || null;
                autonomyCollectAllowedActions(autonomyLiveReadiness, payload, autonomyLiveExecution);
                autonomyCollectDecisionAllowedActions(autonomyLiveReadiness, payload, autonomyLiveExecution);
                autonomyExecutionPollFailures = 0;
                const nextStates = autonomyExecutionJobs({latestOnly: true})
                    .map((job) => job.tea_job_id + ':' + job.state).join('|');
                autonomyRenderLiveCase();
                autonomyRenderLiveReadiness();
                autonomyRenderLiveExecution({announce: priorStates !== nextStates});
                autonomyRenderLiveDecisionWorkspace();
                if (autonomyExpectedCaseRevision() !== priorCaseRevision) {
                    autonomyLoadScenarioWorkspace().catch(() => {});
                    return;
                }
                if (priorStates !== nextStates && autonomyExecutionJobs({latestOnly: true})
                    .some((job) => AUTONOMY_TERMINAL_TEA_STATES.includes(String(job.state)))) {
                    autonomyLoadScenarioWorkspace().catch(() => {});
                    return;
                }
                autonomyScheduleExecutionPoll();
            } catch (error) {
                if (error?.name === 'AbortError' || revision !== autonomyExecutionPollRevision) return;
                autonomyExecutionPollFailures += 1;
                if (autonomyExecutionQueueState) autonomyExecutionQueueState.textContent = 'Reconnecting · durable jobs unchanged';
                autonomyAnnounce('Scenario job status connection interrupted. Retrying without changing any job.');
                const delay = Math.min(10000, 1000 * (2 ** Math.min(autonomyExecutionPollFailures, 4)));
                autonomyScheduleExecutionPoll(delay);
            } finally {
                if (autonomyExecutionAbortController === controller) autonomyExecutionAbortController = null;
            }
        }

        function autonomyScenarioById(scenarioId) {
            const safeId = autonomyScenarioId(scenarioId);
            return autonomyLiveScenarios.find((scenario) => autonomyScenarioId(scenario.scenario_id) === safeId) || null;
        }

        function autonomyScenarioTemplate(kind) {
            if (kind === 'alternative') {
                return autonomyLiveScenarios.find((scenario) => !scenario.audit_only && scenario.kind === 'baseline')?.request || {};
            }
            return autonomyLiveComparison?.request_template
                || autonomyLiveCase?.scenario_request_template
                || {};
        }

        function autonomySetScenarioDialogFieldState(expiring) {
            [
                autonomyScenarioLabel,
                autonomyScenarioKind,
                autonomyScenarioChangedFields,
                autonomyScenarioRequest,
                autonomyScenarioEvidenceReferences,
            ].forEach((field) => {
                if (!field) return;
                field.disabled = expiring;
                field.closest('label')?.toggleAttribute('hidden', expiring);
            });
            if (autonomyScenarioReasonField) autonomyScenarioReasonField.hidden = !expiring;
            if (autonomyScenarioReason) {
                autonomyScenarioReason.disabled = !expiring;
                autonomyScenarioReason.required = expiring;
            }
        }

        function autonomyOpenScenarioEditor(mode, scenario = null, kind = 'alternative', trigger = null) {
            if (autonomyContentMode !== 'live' || !autonomyCaseId()) return;
            const expiring = mode === 'expire';
            autonomyScenarioDialogMode = mode;
            autonomyScenarioDialogTarget = scenario;
            autonomySetScenarioDialogFieldState(expiring);
            if (autonomyScenarioDialogHeading) autonomyScenarioDialogHeading.textContent = expiring
                ? 'Expire unconfirmed scenario draft'
                : (mode === 'revise' ? 'Create scenario revision' : 'Create scenario draft');
            if (autonomyScenarioDialogDescription) {
                const templateMetadata = autonomyPlainObject(autonomyLiveComparison?.request_template_metadata);
                const templateKind = templateMetadata.kind === 'verified_prior_tea_request'
                    ? ' A verified prior TEA request matched to this source snapshot and basis is prefilled for operator review.'
                    : (templateMetadata.message ? ' ' + templateMetadata.message : '');
                autonomyScenarioDialogDescription.textContent = expiring
                    ? 'Expiring retains this immutable revision in case history and cannot remove confirmed records.'
                    : 'The server builds and validates the TEA request. Values shown before execution are inputs or hypotheses, never outcomes.'
                        + (mode === 'create' && kind === 'baseline' ? templateKind : '');
            }
            if (autonomyScenarioLabel) autonomyScenarioLabel.value = scenario?.label || (kind === 'baseline' ? 'Baseline' : 'Alternative');
            if (autonomyScenarioKind) {
                autonomyScenarioKind.value = scenario?.kind || kind;
                autonomyScenarioKind.disabled = expiring || mode === 'revise';
            }
            if (autonomyScenarioChangedFields) {
                autonomyScenarioChangedFields.value = Array.isArray(scenario?.changed_fields)
                    ? scenario.changed_fields.join(', ') : '';
            }
            if (autonomyScenarioRequest) {
                const request = scenario?.request || autonomyScenarioTemplate(kind);
                autonomyScenarioRequest.value = JSON.stringify(request, null, 2);
            }
            if (autonomyScenarioEvidenceReferences) {
                const references = Array.isArray(scenario?.evidence_references) ? scenario.evidence_references : [];
                autonomyScenarioEvidenceReferences.value = references.map((reference) => (
                    String(reference?.request_path || '') + '=' + String(reference?.receipt_id || '')
                )).filter((value) => !value.startsWith('=') && !value.endsWith('=')).join(', ');
            }
            if (autonomyScenarioReason) autonomyScenarioReason.value = '';
            if (autonomyScenarioError) {
                autonomyScenarioError.hidden = true;
                autonomyScenarioError.textContent = '';
            }
            if (autonomyScenarioSubmitBtn) autonomyScenarioSubmitBtn.textContent = expiring
                ? 'Expire draft revision'
                : (mode === 'revise' ? 'Create immutable revision' : 'Save draft');
            autonomyOpenDialog(autonomyScenarioDialog, trigger);
            window.requestAnimationFrame(() => (expiring ? autonomyScenarioReason : autonomyScenarioLabel)?.focus());
        }

        function autonomyParseScenarioChangedFields() {
            const values = String(autonomyScenarioChangedFields?.value || '')
                .split(',').map((value) => value.trim()).filter(Boolean);
            if (new Set(values).size !== values.length) throw new Error('Declared changed fields must be unique.');
            if (values.some((value) => !value.startsWith('/'))) {
                throw new Error('Every declared changed field must be a JSON request path beginning with /.');
            }
            return values;
        }

        function autonomyParseScenarioEvidenceReferences() {
            const raw = String(autonomyScenarioEvidenceReferences?.value || '').trim();
            if (!raw) return [];
            const references = raw.split(',').map((entry) => {
                const separator = entry.indexOf('=');
                const requestPath = separator >= 0 ? entry.slice(0, separator).trim() : '';
                const receiptId = separator >= 0 ? entry.slice(separator + 1).trim() : '';
                if (!requestPath.startsWith('/') || !/^evr_[A-Za-z0-9]+$/.test(receiptId)) {
                    throw new Error('Evidence references must use /request/path=evr_receipt format.');
                }
                return {request_path: requestPath, receipt_id: receiptId};
            });
            const keys = references.map((reference) => reference.request_path + '=' + reference.receipt_id);
            if (new Set(keys).size !== keys.length) throw new Error('Evidence references must be unique.');
            return references;
        }

        function autonomyScenarioErrorMessage(error) {
            const messages = [error?.message || 'The scenario action could not be completed.'];
            (Array.isArray(error?.fieldErrors) ? error.fieldErrors : []).forEach((fieldError) => {
                const path = Array.isArray(fieldError?.loc)
                    ? fieldError.loc.filter((part) => part !== 'body').join('.')
                    : fieldError?.field || fieldError?.path || '';
                const message = fieldError?.message || fieldError?.msg || fieldError?.detail || '';
                const combined = [path, message].filter(Boolean).join(': ');
                if (combined) messages.push(combined);
            });
            (Array.isArray(error?.blockers) ? error.blockers : []).forEach((blocker) => {
                const message = typeof blocker === 'string' ? blocker : blocker?.message || blocker?.detail || blocker?.code || '';
                if (message) messages.push('Blocker: ' + message);
            });
            (Array.isArray(error?.violatedRules) ? error.violatedRules : []).forEach((rule) => {
                const message = typeof rule === 'string' ? rule : rule?.message || rule?.detail || rule?.code || rule?.id || '';
                if (message) messages.push('Violated rule: ' + message);
            });
            const alternatives = Array.isArray(error?.closestSupportedAlternatives)
                ? error.closestSupportedAlternatives : [error?.closestSupportedAlternatives];
            alternatives.filter(Boolean).forEach((alternative) => messages.push(
                'Closest supported alternative: ' + (typeof alternative === 'string'
                    ? alternative : alternative?.label || alternative?.message || alternative?.action || 'Review supported inputs')
            ));
            return Array.from(new Set(messages)).join(' ');
        }

        async function autonomySubmitScenarioEditor(event) {
            event?.preventDefault();
            if (autonomyContentMode !== 'live' || !autonomyCaseId()) return;
            const operatorName = autonomyOperator();
            const caseRevision = autonomyExpectedCaseRevision();
            if (!operatorName || !caseRevision) {
                if (autonomyScenarioError) {
                    autonomyScenarioError.hidden = false;
                    autonomyScenarioError.textContent = !operatorName
                        ? 'Enter the named operator in the live case toolbar first.'
                        : 'Refresh the case to obtain its current revision.';
                    autonomyScenarioError.focus();
                }
                return;
            }
            const scenario = autonomyScenarioDialogTarget;
            let path = '/api/autonomy/cases/' + encodeURIComponent(autonomyCaseId()) + '/scenarios';
            let body;
            try {
                if (autonomyScenarioDialogMode === 'expire') {
                    const scenarioId = autonomyScenarioId(scenario?.scenario_id);
                    const reason = autonomyScenarioReason?.value.trim() || '';
                    if (!scenarioId || !reason) throw new Error('A reason is required to expire an unconfirmed draft revision.');
                    path += '/' + encodeURIComponent(scenarioId) + '/expire';
                    body = {
                        expected_case_revision: caseRevision,
                        expected_scenario_revision: Number(scenario.revision),
                        operator_name: operatorName,
                        reason,
                    };
                } else {
                    let request;
                    try {
                        request = JSON.parse(autonomyScenarioRequest?.value || '{}');
                    } catch (_) {
                        throw new Error('TEA request input must be valid JSON.');
                    }
                    if (!request || typeof request !== 'object' || Array.isArray(request)) {
                        throw new Error('TEA request input must be one JSON object.');
                    }
                    body = {
                        expected_case_revision: caseRevision,
                        operator_name: operatorName,
                        label: autonomyScenarioLabel?.value.trim() || '',
                        kind: autonomyScenarioKind?.value,
                        request,
                        changed_fields: autonomyParseScenarioChangedFields(),
                        evidence_references: autonomyParseScenarioEvidenceReferences(),
                    };
                    if (!body.label) throw new Error('Scenario label is required.');
                    if (autonomyScenarioDialogMode === 'revise') {
                        const scenarioId = autonomyScenarioId(scenario?.scenario_id);
                        if (!scenarioId) throw new Error('The scenario identity is invalid.');
                        path += '/' + encodeURIComponent(scenarioId) + '/revisions';
                        body.expected_scenario_revision = Number(scenario.revision);
                    }
                }
            } catch (error) {
                if (autonomyScenarioError) {
                    autonomyScenarioError.hidden = false;
                    autonomyScenarioError.textContent = error.message;
                    autonomyScenarioError.focus();
                }
                return;
            }
            if (autonomyScenarioSubmitBtn) autonomyScenarioSubmitBtn.disabled = true;
            try {
                const payload = await autonomyJsonRequest(path, {method: 'POST', body});
                autonomyAdoptLiveCaseFromPayload(payload);
                autonomyCloseDialog(autonomyScenarioDialog);
                autonomyConfirmationIdempotencyKey = null;
                await autonomyRefreshLiveCase({caseRecord: true, readiness: true, events: true});
                await autonomyLoadScenarioWorkspace({announce: true});
                autonomySelectedStage = 'compare';
                autonomySelectStage('compare', {focus: true, announce: false});
            } catch (error) {
                if (autonomyScenarioError) {
                    autonomyScenarioError.hidden = false;
                    autonomyScenarioError.textContent = autonomyScenarioErrorMessage(error);
                    autonomyScenarioError.focus();
                }
                if (error.status === 409) autonomySetConnectionStatus('Scenario action rejected because this browser has a stale case or scenario revision.', 'stale');
            } finally {
                if (autonomyScenarioSubmitBtn) autonomyScenarioSubmitBtn.disabled = false;
            }
        }

        async function autonomyValidateScenario(scenario) {
            const operatorName = autonomyOperator();
            const caseRevision = autonomyExpectedCaseRevision();
            const scenarioId = autonomyScenarioId(scenario?.scenario_id);
            const requestSha256 = String(scenario?.request_sha256 || '');
            if (!operatorName || !caseRevision || !scenarioId || !/^[0-9a-f]{64}$/.test(requestSha256)) {
                autonomySetConnectionStatus('Validation requires a named operator and the current immutable scenario identity.', 'error');
                if (!operatorName) autonomyOperatorName?.focus();
                return;
            }
            try {
                const payload = await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(autonomyCaseId())
                        + '/scenarios/' + encodeURIComponent(scenarioId) + '/validate',
                    {
                        method: 'POST',
                        body: {
                            expected_case_revision: caseRevision,
                            expected_scenario_revision: Number(scenario.revision),
                            expected_request_sha256: requestSha256,
                            operator_name: operatorName,
                        },
                    }
                );
                autonomyAdoptLiveCaseFromPayload(payload);
                await autonomyRefreshLiveCase({caseRecord: true, readiness: true, events: true});
                await autonomyLoadScenarioWorkspace({announce: true});
            } catch (error) {
                autonomySetConnectionStatus(autonomyScenarioErrorMessage(error), error.status === 409 ? 'stale' : 'error');
                autonomyAnnounce('Scenario validation returned blockers. No TEA job was created.');
            }
        }

        async function autonomyExecutionAction(action, jobId) {
            const safeAction = action === 'cancel' ? 'cancel' : (action === 'retry' ? 'retry' : '');
            const safeJobId = autonomyTeaJobId(jobId);
            const operatorName = autonomyOperator();
            const caseRevision = autonomyExpectedCaseRevision();
            if (!safeAction || !safeJobId || !operatorName || !caseRevision) {
                autonomySetConnectionStatus('The execution action requires a named operator and current case revision.', 'error');
                if (!operatorName) autonomyOperatorName?.focus();
                return;
            }
            if (safeAction === 'cancel' && !window.confirm(
                'Request cancellation of this linked TEA job? Completed results and prior attempts remain immutable.'
            )) return;
            const rationale = window.prompt(
                safeAction === 'cancel'
                    ? 'Enter the cancellation rationale.'
                    : 'Enter the retry rationale. The retry uses the same frozen request, source, and evidence snapshot.'
            );
            if (!rationale?.trim()) {
                autonomyAnnounce('Execution action cancelled because a rationale was not provided.');
                return;
            }
            try {
                const payload = await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(autonomyCaseId())
                        + '/execution/' + encodeURIComponent(safeJobId) + '/' + safeAction,
                    {
                        method: 'POST',
                        body: {
                            expected_case_revision: caseRevision,
                            operator_name: operatorName,
                            rationale: rationale.trim(),
                        },
                    }
                );
                autonomyAdoptLiveCaseFromPayload(payload);
                autonomyLiveExecution = payload.execution || autonomyLiveExecution;
                await autonomyRefreshLiveCase({caseRecord: true, readiness: true, events: true});
                await autonomyLoadScenarioWorkspace({announce: true});
            } catch (error) {
                autonomySetConnectionStatus(autonomyScenarioErrorMessage(error), error.status === 409 ? 'stale' : 'error');
            }
        }

        function autonomyConfirmationSelectionSignature(scenarios = autonomyCurrentScenarioSelections()) {
            return scenarios.map((scenario) => autonomyScenarioRevisionKey(scenario)).sort().join('|');
        }

        function autonomyConfirmationHasOneBaseline(scenarios) {
            return scenarios.filter((scenario) => scenario?.kind === 'baseline').length === 1;
        }

        function autonomyConfirmationReviewSignature(scenarios, operatorName, rationale) {
            return [
                autonomyExpectedCaseRevision(),
                autonomyConfirmationSelectionSignature(scenarios),
                String(operatorName || '').trim(),
                String(rationale || '').trim(),
                AUTONOMY_GROUPED_TEA_ACKNOWLEDGEMENT,
            ].join('|');
        }

        function autonomyResetConfirmationReview(options = {}) {
            if (autonomyConfirmAck) autonomyConfirmAck.checked = false;
            if (options.clearRationale !== false && autonomyConfirmRationale) autonomyConfirmRationale.value = '';
            autonomyConfirmationIdempotencyKey = null;
            autonomyConfirmationSubmittedSignature = null;
            if (options.clearCaseRevision !== false) autonomyConfirmationCaseRevision = null;
            if (autonomyConfirmDialog && options.clearSelection !== false) {
                autonomyConfirmDialog.dataset.selectionSignature = '';
            }
        }

        function autonomyConfirmationWarnings(scenarios) {
            const warnings = [];
            (Array.isArray(autonomyLiveComparison?.warnings) ? autonomyLiveComparison.warnings : []).forEach((warning) => {
                warnings.push({
                    status: 'warning',
                    text: typeof warning === 'string'
                        ? warning
                        : warning?.message || warning?.detail || warning?.code || 'Comparison warning',
                });
            });
            scenarios.forEach((scenario) => {
                if (scenario.comparison_classification === 'structural' || scenario.structural_warning) {
                    warnings.push({status: 'warning', text: scenario.label + ': '
                        + (scenario.structural_warning || 'Structural comparison limits causal attribution.')});
                }
                const validation = autonomyScenarioValidation(scenario);
                const evidenceState = validation.evidence_state || validation.evidence_status || '';
                if (evidenceState && !['accepted', 'complete', 'passed'].includes(String(evidenceState).toLowerCase())) {
                    warnings.push({status: 'warning', text: scenario.label + ': evidence state ' + evidenceState + '.'});
                }
            });
            autonomyComparisonBlockers().forEach((blocker) => warnings.push({
                status: 'blocked',
                text: typeof blocker === 'string' ? blocker : blocker?.message || blocker?.detail || blocker?.code || 'Comparison blocker',
            }));
            return warnings;
        }

        function autonomyPopulateLiveConfirmation() {
            const scenarios = autonomyCurrentScenarioSelections();
            if (!scenarios.length || scenarios.length > 4 || !autonomyConfirmationHasOneBaseline(scenarios)) return false;
            if (autonomyLiveConfirmLocks) autonomyLiveConfirmLocks.replaceChildren();
            const sourceLock = autonomyCaseSourceLock() || autonomyPlainObject(scenarios[0]?.source_lock);
            const scale = autonomyScenarioRequestScale(scenarios[0]);
            const receiptIds = new Set();
            scenarios.forEach((scenario) => (Array.isArray(scenario.evidence_references)
                ? scenario.evidence_references : []).forEach((reference) => {
                const receiptId = String(reference?.receipt_id || '');
                if (receiptId) receiptIds.add(receiptId);
            }));
            autonomyAppendLock(autonomyLiveConfirmLocks, 'Annual source', sourceLock?.annual_job_id || sourceLock?.source_annual_job_id || 'Not locked');
            autonomyAppendLock(autonomyLiveConfirmLocks, 'Source snapshot SHA-256', sourceLock?.source_snapshot_sha256 || 'Not locked', true);
            autonomyAppendLock(autonomyLiveConfirmLocks, 'Analysis basis', sourceLock?.analysis_basis || 'Not locked');
            autonomyAppendLock(autonomyLiveConfirmLocks, 'Realizations per scenario', scale.realizations);
            autonomyAppendLock(autonomyLiveConfirmLocks, 'Seed', scale.seed);
            autonomyAppendLock(autonomyLiveConfirmLocks, 'Unique verified accepted evidence receipts', receiptIds.size);
            autonomyAppendLock(autonomyLiveConfirmLocks, 'Queue behavior', 'Atomic creation · existing sequential leased worker');
            autonomyAppendLock(autonomyLiveConfirmLocks, 'Expected case revision', autonomyExpectedCaseRevision() || 'Not recorded');
            if (autonomyLiveConfirmScenarioRows) autonomyLiveConfirmScenarioRows.replaceChildren();
            scenarios.forEach((scenario) => {
                const row = autonomyNode('tr');
                const selectionCell = autonomyNode('td');
                const checkbox = autonomyNode('input');
                checkbox.type = 'checkbox';
                checkbox.checked = true;
                checkbox.dataset.autonomyLiveConfirmScenario = autonomyScenarioId(scenario.scenario_id);
                checkbox.setAttribute('aria-label', 'Include ' + String(scenario.label || scenario.scenario_id));
                const selectionTarget = autonomyNode('label', {className: 'autonomy-confirm-selection-target'});
                selectionTarget.appendChild(checkbox);
                selectionCell.appendChild(selectionTarget);
                row.appendChild(selectionCell);
                row.appendChild(autonomyNode('td', {text: scenario.label || scenario.scenario_id}));
                const differences = autonomyScenarioDifferences(scenario);
                row.appendChild(autonomyNode('td', {text: differences.length
                    ? differences.map((difference) => difference.field + ': ' + autonomyExactDifferenceText(difference)).join(' · ')
                    : (scenario.kind === 'baseline' ? 'No baseline-relative difference' : 'No change')}));
                row.appendChild(autonomyNode('td', {text: autonomyScenarioEvidenceState(scenario)}));
                row.appendChild(autonomyNode('td', {text: String(scenario.request_sha256 || 'Not available')}));
                autonomyLiveConfirmScenarioRows?.appendChild(row);
            });
            if (autonomyLiveConfirmWarnings) autonomyLiveConfirmWarnings.replaceChildren();
            const warnings = autonomyConfirmationWarnings(scenarios);
            warnings.forEach((warning) => {
                const item = autonomyNode('p', {text: warning.text});
                item.dataset.status = warning.status;
                autonomyLiveConfirmWarnings?.appendChild(item);
            });
            if (!warnings.length && autonomyLiveConfirmWarnings) {
                autonomyLiveConfirmWarnings.appendChild(autonomyNode('p', {
                    text: 'No additional warning was returned. Inputs remain hypotheses until the existing TEA worker completes.',
                }));
            }
            const revision = autonomyExpectedCaseRevision();
            const signature = autonomyConfirmationSelectionSignature(scenarios);
            if (!autonomyConfirmationIdempotencyKey
                || autonomyConfirmationCaseRevision !== revision
                || autonomyConfirmDialog?.dataset.selectionSignature !== signature) {
                autonomyConfirmationIdempotencyKey = autonomyNewIdempotencyKey('confirm');
            }
            autonomyConfirmationCaseRevision = revision;
            if (autonomyConfirmDialog) autonomyConfirmDialog.dataset.selectionSignature = signature;
            if (autonomyConfirmRevision) autonomyConfirmRevision.textContent = 'Expected case revision ' + String(revision)
                + ' · idempotent submission key prepared for this exact review.';
            if (autonomyConfirmOperator) autonomyConfirmOperator.value = autonomyOperator();
            if (autonomyConfirmEyebrow) autonomyConfirmEyebrow.textContent = 'Grouped TEA confirmation · live durable case';
            if (autonomyConfirmDescription) autonomyConfirmDescription.textContent = 'Confirming creates every selected TEA job atomically or creates none.';
            if (autonomyConfirmSubmitBtn) autonomyConfirmSubmitBtn.textContent = 'Confirm and create TEA jobs';
            if (autonomyConfirmAckCopy) autonomyConfirmAckCopy.textContent = AUTONOMY_GROUPED_TEA_ACKNOWLEDGEMENT;
            return true;
        }

        function autonomyOpenLiveRunConfirmation(trigger) {
            if (autonomyContentMode !== 'live' || !autonomyActionIsAllowed('confirm_scenarios')) {
                autonomyAnnounce('Grouped confirmation is not an allowed action for the current durable case state.');
                return;
            }
            autonomyResetConfirmationReview();
            if (!autonomyPopulateLiveConfirmation()) {
                autonomyAnnounce('Select between one and four validated current scenario revisions, including exactly one baseline.');
                return;
            }
            if (autonomyConfirmError) {
                autonomyConfirmError.hidden = true;
                autonomyConfirmError.textContent = '';
            }
            autonomyOpenDialog(autonomyConfirmDialog, trigger);
            window.requestAnimationFrame(() => autonomyConfirmOperator?.focus());
        }

        function autonomyLiveConfirmationSelections() {
            const selectedIds = Array.from(
                autonomyLiveConfirmScenarioRows?.querySelectorAll('[data-autonomy-live-confirm-scenario]:checked') || []
            ).map((input) => autonomyScenarioId(input.dataset.autonomyLiveConfirmScenario)).filter(Boolean);
            return selectedIds.map((scenarioId) => autonomyScenarioById(scenarioId)).filter((scenario) => (
                scenario && autonomyScenarioIsSelectable(scenario)
            ));
        }

        async function autonomySubmitLiveConfirmation() {
            const operatorName = autonomyConfirmOperator?.value.trim() || '';
            const rationale = autonomyConfirmRationale?.value.trim() || '';
            const acknowledgementAccepted = !!autonomyConfirmAck?.checked;
            const caseRevision = autonomyExpectedCaseRevision();
            const scenarios = autonomyLiveConfirmationSelections();
            const selectionSignature = autonomyConfirmationSelectionSignature(scenarios);
            const frozenSignature = autonomyConfirmDialog?.dataset.selectionSignature || '';
            let errorMessage = '';
            if (!autonomyActionIsAllowed('confirm_scenarios')) errorMessage = 'Grouped confirmation is no longer allowed for this case.';
            else if (!operatorName) errorMessage = 'Enter the named operator responsible for this execution.';
            else if (!rationale) errorMessage = 'Enter the rationale and acknowledgement for these exact requests.';
            else if (!acknowledgementAccepted) errorMessage = 'Acknowledge the exact immutable requests and queue behavior.';
            else if (!scenarios.length || scenarios.length > 4) errorMessage = 'Select between one and four validated current scenarios.';
            else if (!autonomyConfirmationHasOneBaseline(scenarios)) errorMessage = 'The grouped confirmation must include exactly one validated baseline.';
            else if (!caseRevision || caseRevision !== autonomyConfirmationCaseRevision) errorMessage = 'The case revision changed. Close and reopen confirmation to review the current case.';
            else if (selectionSignature !== frozenSignature) errorMessage = 'The scenario selection changed. Close and reopen confirmation to review the exact batch.';
            else if (scenarios.some((scenario) => !/^[0-9a-f]{64}$/.test(String(scenario.request_sha256 || '')))) {
                errorMessage = 'Every selected scenario must expose one full canonical request SHA-256.';
            }
            if (errorMessage) {
                if (autonomyConfirmError) {
                    autonomyConfirmError.hidden = false;
                    autonomyConfirmError.textContent = errorMessage;
                    autonomyConfirmError.focus();
                }
                return;
            }
            if (autonomyConfirmationInFlight) return;
            const reviewSignature = autonomyConfirmationReviewSignature(scenarios, operatorName, rationale);
            if (autonomyConfirmationSubmittedSignature && autonomyConfirmationSubmittedSignature !== reviewSignature) {
                autonomyConfirmationIdempotencyKey = null;
            }
            if (!autonomyConfirmationIdempotencyKey) {
                autonomyConfirmationIdempotencyKey = autonomyNewIdempotencyKey('confirm');
            }
            autonomyConfirmationSubmittedSignature = reviewSignature;
            autonomyConfirmationInFlight = true;
            if (autonomyConfirmSubmitBtn) {
                autonomyConfirmSubmitBtn.disabled = true;
                autonomyConfirmSubmitBtn.textContent = 'Creating atomic TEA batch…';
            }
            if (autonomyConfirmCancelBtn) autonomyConfirmCancelBtn.disabled = true;
            try {
                const payload = await autonomyJsonRequest(
                    '/api/autonomy/cases/' + encodeURIComponent(autonomyCaseId()) + '/scenarios/confirm',
                    {
                        method: 'POST',
                        body: {
                            expected_case_revision: caseRevision,
                            selections: scenarios.map((scenario) => ({
                                scenario_id: autonomyScenarioId(scenario.scenario_id),
                                revision: Number(scenario.revision),
                                request_sha256: String(scenario.request_sha256),
                            })),
                            operator_name: operatorName,
                            rationale,
                            acknowledgement_accepted: true,
                            idempotency_key: autonomyConfirmationIdempotencyKey,
                        },
                    }
                );
                autonomyAdoptLiveCaseFromPayload(payload);
                autonomyLiveExecution = payload.execution || autonomyLiveExecution;
                if (autonomyOperatorName) autonomyOperatorName.value = operatorName;
                autonomyCloseDialog(autonomyConfirmDialog, {force: true});
                autonomyConfirmationIdempotencyKey = null;
                autonomyConfirmationCaseRevision = null;
                autonomyConfirmationSubmittedSignature = null;
                if (autonomyConfirmAck) autonomyConfirmAck.checked = false;
                if (autonomyConfirmRationale) autonomyConfirmRationale.value = '';
                autonomySelectedStage = 'run';
                await autonomyRefreshLiveCase({caseRecord: true, readiness: true, events: true});
                await autonomyLoadScenarioWorkspace({announce: true});
                autonomySelectStage('run', {focus: true, announce: false});
                autonomySetConnectionStatus('Atomic scenario batch confirmed. Linked TEA jobs are durable.', 'ready');
            } catch (error) {
                if (autonomyConfirmError) {
                    autonomyConfirmError.hidden = false;
                    autonomyConfirmError.textContent = autonomyScenarioErrorMessage(error)
                        + ' The same idempotency key will be reused if you retry this unchanged review.';
                    autonomyConfirmError.focus();
                }
                if (error.status === 409) autonomySetConnectionStatus('Confirmation rejected because the case or scenario revision changed.', 'stale');
            } finally {
                autonomyConfirmationInFlight = false;
                if (autonomyConfirmSubmitBtn) {
                    autonomyConfirmSubmitBtn.disabled = false;
                    autonomyConfirmSubmitBtn.textContent = 'Confirm and create TEA jobs';
                }
                if (autonomyConfirmCancelBtn) autonomyConfirmCancelBtn.disabled = false;
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
            autonomyRenderLiveScenarios();
            autonomyRenderLiveExecution();
            autonomyRenderLiveDecisionWorkspace();
            autonomySyncMobileTabs(autonomyMobileSectionForStage(autonomySelectedStage));
        }

        async function autonomyFetchCase(caseId, signal = undefined) {
            const safeCaseId = autonomyCaseId(caseId);
            if (!safeCaseId) throw new Error('The decision-case identifier is invalid.');
            const data = await autonomyJsonRequest('/api/autonomy/cases/' + encodeURIComponent(safeCaseId), {cache: 'no-store', signal});
            return data.case || null;
        }

        async function autonomyEvaluateReadiness(caseId, signal = undefined) {
            const safeCaseId = autonomyCaseId(caseId);
            if (!safeCaseId) return null;
            return autonomyJsonRequest(
                '/api/autonomy/cases/' + encodeURIComponent(safeCaseId) + '/readiness/evaluate',
                {method: 'POST', signal}
            );
        }

        async function autonomyFetchEvents(caseId, signal = undefined) {
            const safeCaseId = autonomyCaseId(caseId);
            if (!safeCaseId) return [];
            const data = await autonomyJsonRequest(
                '/api/autonomy/cases/' + encodeURIComponent(safeCaseId) + '/events',
                {cache: 'no-store', signal}
            );
            return Array.isArray(data.events) ? data.events : [];
        }

        async function autonomyFetchMessages(caseId, signal = undefined) {
            const safeCaseId = autonomyCaseId(caseId);
            if (!safeCaseId) return [];
            const data = await autonomyJsonRequest(
                '/api/autonomy/cases/' + encodeURIComponent(safeCaseId) + '/messages',
                {cache: 'no-store', signal}
            );
            return Array.isArray(data.messages) ? data.messages : [];
        }

        async function autonomyFetchEvidence(caseId, signal = undefined) {
            const safeCaseId = autonomyCaseId(caseId);
            if (!safeCaseId) return [];
            const data = await autonomyJsonRequest(
                '/api/autonomy/cases/' + encodeURIComponent(safeCaseId) + '/evidence',
                {cache: 'no-store', signal}
            );
            return Array.isArray(data.evidence) ? data.evidence : [];
        }

        async function autonomyFetchSourceOptions(signal = undefined) {
            const data = await autonomyJsonRequest('/api/autonomy/sources', {cache: 'no-store', signal});
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
            const signal = options.signal;
            const expectedLoadRevision = options.caseLoadRevision;
            const stillCurrent = () => caseId === autonomyCaseId()
                && (!autonomyDesiredCaseId || caseId === autonomyDesiredCaseId)
                && (expectedLoadRevision === undefined || expectedLoadRevision === autonomyCaseLoadRevision);
            const requests = [];
            if (options.caseRecord) requests.push(autonomyFetchCase(caseId, signal).then((value) => {
                if (stillCurrent()) autonomyLiveCase = value;
            }));
            if (options.readiness) {
                requests.push(autonomyEvaluateReadiness(caseId, signal).then((value) => {
                    if (stillCurrent()) autonomyLiveReadiness = value;
                }));
                requests.push(autonomyFetchSourceOptions(signal).then((value) => {
                    if (!stillCurrent()) return;
                    autonomyEligibleAnnualSources = value.sources;
                    autonomySupportedAnalysisBases = value.analysisBases;
                }).catch(() => {
                    // Readiness carries the same safe source summaries, so the live case remains reviewable.
                    if (stillCurrent()) {
                        autonomyEligibleAnnualSources = [];
                        autonomySupportedAnalysisBases = [];
                    }
                }));
            }
            if (options.events) requests.push(autonomyFetchEvents(caseId, signal).then((value) => {
                if (stillCurrent()) autonomyLiveEvents = value;
            }));
            if (options.messages) requests.push(autonomyFetchMessages(caseId, signal).then((value) => {
                if (stillCurrent()) autonomyLiveMessages = value;
            }));
            if (options.evidence) requests.push(autonomyFetchEvidence(caseId, signal).then((value) => {
                if (stillCurrent()) autonomyLiveEvidence = value;
            }));
            await Promise.all(requests);
            if (!stillCurrent()) return false;
            autonomyCollectAllowedActions(autonomyLiveReadiness);
            autonomyCollectDecisionAllowedActions(autonomyLiveReadiness);
            autonomyRenderLiveWorkspace();
            return true;
        }

        async function autonomySelectLiveCase(caseId) {
            const safeCaseId = autonomyCaseId(caseId);
            if (!safeCaseId) return;
            if (autonomyConfirmationInFlight) {
                autonomyPopulateCaseOptions();
                autonomyAnnounce('Wait for the atomic grouped confirmation response before switching cases.');
                return;
            }
            const loadRevision = ++autonomyCaseLoadRevision;
            autonomyDesiredCaseId = safeCaseId;
            if (autonomyCaseAbortController) autonomyCaseAbortController.abort();
            const controller = new AbortController();
            autonomyCaseAbortController = controller;
            autonomyScenarioLoadRevision += 1;
            if (autonomyScenarioAbortController) autonomyScenarioAbortController.abort();
            autonomyInvalidateExecutionPoll();
            autonomyLiveCase = {case_id: safeCaseId, revision: 0, title: 'Loading durable case…'};
            autonomyLiveReadiness = null;
            autonomyLiveEvidence = [];
            autonomyLiveMessages = [];
            autonomyLiveEvents = [];
            autonomyLiveScenarios = [];
            autonomyLiveComparison = null;
            autonomyLiveExecution = null;
            autonomyLiveAllowedActions = [];
            autonomyResetDecisionWorkspace();
            autonomySelectedScenarioRevisions.clear();
            autonomyResetConfirmationReview();
            autonomySelectedStage = 'ask';
            autonomySelectedView = 'investigation';
            if (autonomyCaseSelect) {
                autonomyCaseSelect.disabled = true;
                autonomyCaseSelect.setAttribute('aria-busy', 'true');
            }
            autonomyRenderLiveWorkspace();
            if (autonomyCaseSelect) {
                autonomyCaseSelect.disabled = true;
                autonomyCaseSelect.setAttribute('aria-busy', 'true');
            }
            autonomySetConnectionStatus('Loading durable case and deterministic readiness…', 'loading');
            try {
                const caseRecord = await autonomyFetchCase(safeCaseId, controller.signal);
                if (controller.signal.aborted || loadRevision !== autonomyCaseLoadRevision
                    || safeCaseId !== autonomyDesiredCaseId) return;
                autonomyLiveCase = caseRecord;
                const refreshed = await autonomyRefreshLiveCase({
                    readiness: true,
                    evidence: true,
                    messages: true,
                    events: true,
                    signal: controller.signal,
                    caseLoadRevision: loadRevision,
                });
                if (!refreshed || controller.signal.aborted || loadRevision !== autonomyCaseLoadRevision) return;
                await autonomyLoadScenarioWorkspace();
                if (controller.signal.aborted || loadRevision !== autonomyCaseLoadRevision) return;
                autonomySelectedStage = autonomyLiveDefaultStage();
                autonomyRenderLiveWorkspace();
                autonomySetConnectionStatus('Durable case loaded. Readiness evaluated from current dashboard state.', 'ready');
            } catch (error) {
                if (error?.name === 'AbortError' || loadRevision !== autonomyCaseLoadRevision) return;
                autonomySetConnectionStatus(error.message || 'The durable case could not be loaded.', 'error');
            } finally {
                if (autonomyCaseAbortController === controller) autonomyCaseAbortController = null;
                if (loadRevision === autonomyCaseLoadRevision && autonomyCaseSelect) {
                    autonomyCaseSelect.disabled = autonomyCases.length === 0;
                    autonomyCaseSelect.removeAttribute('aria-busy');
                }
            }
        }

        async function autonomyLoadCases() {
            const data = await autonomyJsonRequest('/api/autonomy/cases', {cache: 'no-store'});
            autonomyCases = Array.isArray(data.cases) ? data.cases.filter((item) => autonomyCaseId(item?.case_id)) : [];
            const currentId = autonomyCaseId();
            const selected = autonomyCases.find((item) => item.case_id === currentId) || autonomyCases[0] || null;
            if (!selected) {
                autonomyDesiredCaseId = '';
                autonomyLiveCase = null;
                autonomyLiveReadiness = null;
                autonomyLiveEvidence = [];
                autonomyLiveMessages = [];
                autonomyLiveEvents = [];
                autonomyLiveScenarios = [];
                autonomyLiveComparison = null;
                autonomyLiveExecution = null;
                autonomyLiveAllowedActions = [];
                autonomyResetDecisionWorkspace();
                autonomySelectedScenarioRevisions.clear();
                autonomyInvalidateExecutionPoll();
                autonomyRenderLiveWorkspace();
                return;
            }
            await autonomySelectLiveCase(selected.case_id);
        }

        async function autonomyOpenWorkspace() {
            autonomySetContentMode('live');
            if (autonomyWorkspaceOpenPromise) return autonomyWorkspaceOpenPromise;
            autonomySetConnectionStatus('Loading durable decision cases…', 'loading');
            autonomyAnnounce('Loading the live durable case. Fixture preview data is no longer displayed.');
            autonomyWorkspaceOpenPromise = (async () => {
                try {
                    await autonomyLoadCases();
                    autonomyAnnounce(autonomyLiveCase
                        ? 'Live durable case restored. Fixture preview data is no longer displayed.'
                        : 'No live durable decision case is available. Fixture preview data is no longer displayed.');
                } catch (error) {
                    autonomyLiveAgentAvailable = false;
                    autonomySetConnectionStatus(error.message || 'The Autonomy service is unavailable.', 'unavailable');
                    autonomyAnnounce('The live Autonomy service is unavailable. Fixture preview data is no longer displayed.');
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
                await autonomyLoadScenarioWorkspace();
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
                await autonomyLoadScenarioWorkspace();
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
                const unavailable = ['agent_disabled', 'agent_credential_missing', 'agent_unavailable'].includes(failureCode);
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
            const stepperState = autonomyContentMode === 'live' ? {
                stage: autonomyLiveDefaultStage(),
                stageState: ['blocked', 'needs_attention'].includes(String(autonomyLiveCase?.status || ''))
                    ? 'needs-attention' : 'current',
                signed: false,
            } : fixture;
            const statuses = autonomyStageStatuses(stepperState);
            autonomyPanel.querySelectorAll('[data-autonomy-stage]').forEach((button) => {
                const stage = button.dataset.autonomyStage;
                const liveUnavailable = autonomyContentMode === 'live' && !autonomyCanSelectLiveStage(stage);
                button.disabled = liveUnavailable;
                button.setAttribute('aria-disabled', String(liveUnavailable));
                const index = AUTONOMY_STAGES.indexOf(stage);
                const statusValue = statuses[index] || 'not-started';
                button.dataset.status = statusValue;
                button.dataset.autonomyStageStatus = statusValue;
                button.classList.toggle('is-selected', stage === autonomySelectedStage);
                button.classList.toggle('is-current', stage === stepperState.stage);
                button.setAttribute('aria-pressed', String(stage === autonomySelectedStage));
                button.setAttribute('aria-selected', String(stage === autonomySelectedStage));
                button.tabIndex = stage === autonomySelectedStage ? 0 : -1;
                if (stage === stepperState.stage) button.setAttribute('aria-current', 'step');
                else button.removeAttribute('aria-current');
                const status = button.querySelector('small');
                if (status) {
                    status.textContent = autonomyContentMode === 'live' && stage === 'decide'
                        ? (autonomyCanOpenLiveBrief() ? autonomyDecisionStageLabel() : 'Server action required')
                        : ({
                        complete: 'Complete', current: 'Current', blocked: 'Blocked',
                        'needs-attention': 'Needs attention', 'not-started': 'Not started',
                    }[statusValue] || 'Not started');
                }
            });
            autonomyPanel.querySelectorAll('[data-autonomy-stage-panel]').forEach((panel) => {
                panel.hidden = panel.dataset.autonomyStagePanel !== autonomySelectedStage;
            });
            if (autonomyStageSelect) {
                autonomyStageSelect.value = autonomySelectedStage;
                Array.from(autonomyStageSelect.options).forEach((option) => {
                    option.disabled = autonomyContentMode === 'live' && !autonomyCanSelectLiveStage(option.value);
                });
            }
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
            return autonomyContentMode === 'live'
                ? autonomyCanOpenLiveBrief()
                : fixture.briefState !== 'unavailable';
        }

        function autonomyMobileSectionForStage(stage, fixture = autonomyCurrentFixture()) {
            if (stage === 'ask') return 'ask';
            if (stage === 'verify') return 'evidence';
            if (stage === 'decide' && autonomyCanOpenBrief(fixture)) return 'decision';
            return 'scenarios';
        }

        function autonomySyncMobileTabs(section) {
            const briefAvailable = autonomyCanOpenBrief(autonomyCurrentFixture());
            const safeSection = section === 'decision' && !briefAvailable ? 'scenarios' : section;
            autonomyMobileSection = safeSection;
            autonomyPanel.dataset.mobileSection = safeSection;
            autonomyPanel.querySelectorAll('[data-autonomy-mobile-tab]').forEach((button) => {
                const isDecision = button.dataset.autonomyMobileTab === 'decision';
                const selected = button.dataset.autonomyMobileTab === safeSection;
                button.disabled = isDecision && !briefAvailable;
                button.setAttribute('aria-disabled', String(isDecision && !briefAvailable));
                button.setAttribute('aria-selected', String(selected));
                button.classList.toggle('is-selected', selected);
                button.tabIndex = selected ? 0 : -1;
            });
        }

        function autonomySetView(view, options = {}) {
            const fixture = autonomyCurrentFixture();
            const caseExists = autonomyContentMode === 'live' ? !!autonomyCaseId() : fixture.caseExists;
            const requestedBrief = view === 'decision-brief';
            if (autonomyContentMode === 'live' && requestedBrief && autonomySelectedView !== 'decision-brief') {
                autonomyBriefReturnContext = {
                    stage: autonomySelectedStage,
                    mobileSection: autonomyMobileSection,
                    trigger: document.activeElement instanceof HTMLElement ? document.activeElement : null,
                };
            }
            autonomySelectedView = requestedBrief && autonomyCanOpenBrief(fixture) ? 'decision-brief' : 'investigation';
            const brief = autonomySelectedView === 'decision-brief';
            if (autonomyInvestigationView) autonomyInvestigationView.hidden = !caseExists || brief;
            if (autonomyDecisionBrief) autonomyDecisionBrief.hidden = !caseExists || !brief;
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
                if (brief && autonomyContentMode === 'live') {
                    const stateName = autonomyDecisionStateName();
                    autonomyAnnounceDecisionState(
                        stateName,
                        autonomyDecisionStatePresentation(stateName),
                        'Decision Brief opened for the current case.'
                    );
                } else {
                    autonomyAnnounce(brief
                        ? 'Decision Brief opened for the current case.'
                        : 'Investigation Workspace opened for the current case.');
                }
            }
        }

        function autonomyRenderBrief(fixture) {
            if (!autonomyFixtureDecisionBrief) return;
            autonomyDecisionBrief.dataset.briefState = fixture.briefState;
            if (autonomyBriefPartialWarning) autonomyBriefPartialWarning.hidden = fixture.briefState !== 'partial';
            autonomyFixtureDecisionBrief.querySelectorAll('[data-autonomy-partial-only]').forEach((element) => {
                element.hidden = fixture.briefState !== 'partial';
            });
            autonomyFixtureDecisionBrief.querySelectorAll('[data-autonomy-complete-results]').forEach((element) => {
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
            autonomyFixtureDecisionBrief.querySelectorAll('[data-autonomy-prepare-signoff]').forEach((button) => {
                button.disabled = !fixture.signoffAllowed;
                button.hidden = fixture.signed;
            });
            autonomyFixtureDecisionBrief.querySelectorAll('[data-autonomy-signoff-status]').forEach((status) => {
                status.textContent = fixture.signed
                    ? 'Signed fixture · ' + autonomySignedDecision.disposition
                    : 'Unsigned fixture';
                status.dataset.status = fixture.signed ? 'signed' : 'unsigned';
            });
            if (autonomySignedSummary) autonomySignedSummary.textContent = autonomySignedDecisionSummary();
            if (autonomySignedRationale) autonomySignedRationale.textContent = 'Recorded fixture rationale: ' + autonomySignedDecision.rationale;
            autonomyFixtureDecisionBrief.querySelectorAll('[data-autonomy-signed-only]').forEach((element) => {
                element.hidden = !fixture.signed;
            });
            autonomyFixtureDecisionBrief.querySelectorAll('[data-autonomy-superseded-only]').forEach((element) => {
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
            if (autonomyConfirmationInFlight) {
                autonomyAnnounce('Wait for the atomic grouped confirmation response before leaving the live review.');
                return;
            }
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
            if (autonomyContentMode === 'live' && !autonomyCanSelectLiveStage(stage)) {
                autonomyAnnounce('The server has not returned the open_decision_brief allowed action for this case revision.');
                return;
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
                autonomyAnnounce(autonomyContentMode === 'live'
                    ? 'The server has not returned the open_decision_brief allowed action for this case revision.'
                    : 'Decision Brief is unavailable until fixture results are ready.');
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

        function autonomyDecisionFocusTargetIsUsable(element) {
            if (!(element instanceof HTMLElement) || !element.isConnected) return false;
            if (element.closest('[hidden], [inert]')) return false;
            if (element.matches(':disabled') || element.getAttribute('aria-disabled') === 'true') return false;
            if (element.tabIndex < 0) return false;
            const style = window.getComputedStyle(element);
            return style.display !== 'none' && style.visibility !== 'hidden';
        }

        function autonomyReturnFromLiveBrief(options = {}) {
            if (autonomyContentMode !== 'live') return;
            const returnContext = autonomyBriefReturnContext;
            autonomySelectedStage = 'compare';
            autonomySelectedView = 'investigation';
            autonomySyncMobileTabs('scenarios');
            autonomyRenderStepper(autonomyCurrentFixture());
            autonomySetView('investigation', {syncMobile: false, announce: options.announce !== false});
            const contextTrigger = returnContext?.trigger;
            const restoreTarget = autonomyDecisionFocusTargetIsUsable(contextTrigger)
                && !autonomyDecisionBrief?.contains(contextTrigger)
                ? contextTrigger
                : autonomyPanel.querySelector('[data-autonomy-stage="compare"]:not(:disabled)');
            window.requestAnimationFrame(() => restoreTarget?.focus({preventScroll: true}));
            autonomyBriefReturnContext = null;
        }

        function autonomyToggleLiveWhy() {
            if (!autonomyLiveWhyPanel || !autonomyLiveAskWhyBtn || autonomyContentMode !== 'live') return;
            const expanded = autonomyLiveWhyPanel.hidden;
            autonomyLiveWhyPanel.hidden = !expanded;
            autonomyLiveAskWhyBtn.setAttribute('aria-expanded', String(expanded));
            autonomyLiveAskWhyBtn.textContent = expanded
                ? 'Hide decisive evidence and uncertainty'
                : 'Show decisive evidence and uncertainty';
            if (expanded) autonomyLiveWhyPanel.focus?.({preventScroll: true});
            autonomyAnnounce(expanded
                ? 'Deterministic decisive evidence, drivers, uncertainty, gaps, and limitations shown.'
                : 'Deterministic recommendation basis collapsed.');
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

        function autonomyCloseDialog(dialog, options = {}) {
            if (!dialog) return;
            if (dialog === autonomyConfirmDialog && autonomyConfirmationInFlight && options.force !== true) {
                autonomyAnnounce('Atomic confirmation is still being submitted. Keep this review open until the server responds.');
                return;
            }
            if (dialog === autonomyLiveSignoffDialog && autonomyLiveSignoffInFlight && options.force !== true) {
                autonomyAnnounce('Immutable sign-off is still being recorded. Keep this review open until the server responds.');
                return;
            }
            if (typeof dialog.close === 'function') dialog.close();
            else dialog.removeAttribute('open');
            if (autonomyLastDialogTrigger instanceof HTMLElement) autonomyLastDialogTrigger.focus();
            autonomyLastDialogTrigger = null;
            if (dialog === autonomyConfirmDialog && options.preserveReview !== true) {
                autonomyResetConfirmationReview();
            }
        }

        function autonomyOpenRunConfirmation(trigger) {
            if (autonomyFixtureId !== 'ready-to-confirm') {
                autonomyAnnounce('Grouped confirmation is available only when the fixture is ready to confirm.');
                return;
            }
            autonomyResetConfirmationReview();
            if (autonomyConfirmEyebrow) autonomyConfirmEyebrow.textContent = 'Grouped TEA confirmation · fixture only';
            if (autonomyConfirmDescription) autonomyConfirmDescription.textContent = 'This fixture previews the human authority boundary. No jobs will be created.';
            if (autonomyConfirmSubmitBtn) autonomyConfirmSubmitBtn.textContent = 'Preview queued state';
            if (autonomyConfirmAckCopy) autonomyConfirmAckCopy.textContent = 'I confirm the selected fixture scenarios, source and basis lock, evidence status, realization count, seed, and displayed request hashes. No server job will be created.';
            if (autonomyConfirmRevision) autonomyConfirmRevision.textContent = 'Fixture preview · no durable case revision is changed.';
            autonomyOpenDialog(autonomyConfirmDialog, trigger);
        }

        function autonomyOpenSignoff(trigger) {
            if (!autonomyCurrentFixture().signoffAllowed) {
                autonomyAnnounce('Sign-off is unavailable until the complete fixture brief is ready.');
                return;
            }
            autonomyUpdateFixtureSignoffSubmitState();
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

        function autonomyFixturePreviewRequested() {
            // The preview states are a development aid. A viewer of the deployed
            // dashboard must never be able to switch the workspace into them, so the
            // toolbar stays hidden unless it is asked for by name.
            try {
                return new URLSearchParams(window.location.search).get('fixtures') === '1';
            } catch (error) {
                return false;
            }
        }

        function autonomyInitializeWorkspace() {
            if (!autonomyPanel || autonomyInitialized) return;
            autonomyInitialized = true;
            if (autonomyFixtureToolbar && autonomyFixturePreviewRequested()) {
                autonomyFixtureToolbar.hidden = false;
            }
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
            autonomyOperatorName?.addEventListener('input', () => {
                if (autonomyContentMode === 'live') autonomyRenderLiveDecisionWorkspace();
            });
            autonomyLiveConfirmationSelect?.addEventListener('change', () => {
                if (autonomyContentMode === 'live') autonomyRenderDecisionActions(autonomyDecisionStateName());
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
            autonomyCreateBaselineBtn?.addEventListener('click', () => {
                if (autonomyContentMode === 'live' && autonomyActionIsAllowed('create_scenario')) {
                    autonomyOpenScenarioEditor('create', null, 'baseline', autonomyCreateBaselineBtn);
                }
            });
            autonomyCreateAlternativeBtn?.addEventListener('click', () => {
                if (autonomyContentMode === 'live' && autonomyActionIsAllowed('create_scenario')) {
                    autonomyOpenScenarioEditor('create', null, 'alternative', autonomyCreateAlternativeBtn);
                }
            });
            autonomyComparisonSummary?.addEventListener('click', (event) => {
                const button = event.target instanceof Element
                    ? event.target.closest('[data-autonomy-open-expert-tea]') : null;
                if (!button || autonomyContentMode !== 'live') return;
                const technoeconomicModeTab = document.getElementById('technoeconomicTab');
                technoeconomicModeTab?.click();
                technoeconomicModeTab?.focus({preventScroll: true});
            });
            autonomyLiveScenarioGrid?.addEventListener('change', (event) => {
                const checkbox = event.target instanceof Element
                    ? event.target.closest('[data-autonomy-live-scenario-select]') : null;
                if (!checkbox || autonomyContentMode !== 'live') return;
                const scenario = autonomyScenarioById(checkbox.dataset.autonomyLiveScenarioSelect);
                if (!scenario || !autonomyScenarioIsSelectable(scenario)) {
                    checkbox.checked = false;
                    return;
                }
                const key = autonomyScenarioRevisionKey(scenario);
                if (checkbox.checked && !autonomySelectedScenarioRevisions.has(key)
                    && autonomySelectedScenarioRevisions.size >= 4) {
                    checkbox.checked = false;
                    autonomyAnnounce('At most four validated scenarios may be selected for one grouped confirmation.');
                    return;
                }
                if (checkbox.checked) autonomySelectedScenarioRevisions.set(key, scenario);
                else autonomySelectedScenarioRevisions.delete(key);
                checkbox.closest('.autonomy-live-scenario-card')?.setAttribute('aria-selected', String(checkbox.checked));
                autonomyConfirmationIdempotencyKey = null;
                autonomyRenderScenarioSelectionState();
            });
            autonomyLiveScenarioGrid?.addEventListener('click', (event) => {
                const button = event.target instanceof Element
                    ? event.target.closest('[data-autonomy-live-scenario-action]') : null;
                if (!button || autonomyContentMode !== 'live') return;
                const scenario = autonomyScenarioById(button.dataset.scenarioId);
                const action = button.dataset.autonomyLiveScenarioAction;
                if (!scenario || !autonomyActionIsAllowed(action, scenario)) return;
                if (action === 'revise_scenario') autonomyOpenScenarioEditor('revise', scenario, scenario.kind, button);
                else if (action === 'validate_scenario') autonomyValidateScenario(scenario);
                else if (action === 'expire_scenario') autonomyOpenScenarioEditor('expire', scenario, scenario.kind, button);
            });
            autonomyScenarioForm?.addEventListener('submit', autonomySubmitScenarioEditor);
            autonomyScenarioCancelBtn?.addEventListener('click', () => autonomyCloseDialog(autonomyScenarioDialog));
            autonomyLiveJobList?.addEventListener('click', (event) => {
                const button = event.target instanceof Element
                    ? event.target.closest('[data-autonomy-execution-action]') : null;
                if (!button || autonomyContentMode !== 'live') return;
                const job = autonomyExecutionJobs().find((item) => item.tea_job_id === autonomyTeaJobId(button.dataset.teaJobId));
                const actionId = button.dataset.autonomyExecutionAction === 'cancel'
                    ? 'cancel_execution' : 'retry_failed_execution';
                if (!job || !autonomyJobActionAllowed(actionId, job)) return;
                autonomyExecutionAction(button.dataset.autonomyExecutionAction, job.tea_job_id);
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
            autonomyOpenLiveConfirmationBtn?.addEventListener('click', () => autonomyOpenLiveRunConfirmation(autonomyOpenLiveConfirmationBtn));
            autonomyLiveConfirmScenarioRows?.addEventListener('change', (event) => {
                const checkbox = event.target instanceof Element
                    ? event.target.closest('[data-autonomy-live-confirm-scenario]') : null;
                if (!checkbox || autonomyContentMode !== 'live') return;
                const selected = autonomyLiveConfirmationSelections();
                if (!selected.length || !autonomyConfirmationHasOneBaseline(selected)) {
                    checkbox.checked = true;
                    autonomyAnnounce('Exactly one validated baseline must remain in the grouped confirmation.');
                    return;
                }
                autonomySelectedScenarioRevisions.clear();
                selected.forEach((scenario) => autonomySelectedScenarioRevisions.set(
                    autonomyScenarioRevisionKey(scenario), scenario
                ));
                const signature = autonomyConfirmationSelectionSignature(selected);
                if (autonomyConfirmDialog) autonomyConfirmDialog.dataset.selectionSignature = signature;
                autonomyResetConfirmationReview({clearCaseRevision: false, clearSelection: false});
                if (autonomyConfirmRevision) autonomyConfirmRevision.textContent = 'Expected case revision '
                    + String(autonomyConfirmationCaseRevision) + ' · a new idempotent key will be prepared for this changed review.';
                autonomyRenderLiveScenarios();
            });
            autonomyConfirmCancelBtn?.addEventListener('click', () => autonomyCloseDialog(autonomyConfirmDialog));
            autonomyConfirmDialog?.addEventListener('cancel', (event) => {
                event.preventDefault();
                autonomyCloseDialog(autonomyConfirmDialog);
            });
            [autonomyConfirmOperator, autonomyConfirmRationale].filter(Boolean).forEach((field) => {
                field.addEventListener('input', () => {
                    if (autonomyContentMode !== 'live') return;
                    if (autonomyConfirmAck) autonomyConfirmAck.checked = false;
                    autonomyConfirmationIdempotencyKey = null;
                    autonomyConfirmationSubmittedSignature = null;
                });
            });
            autonomyConfirmSubmitBtn?.addEventListener('click', () => {
                if (autonomyContentMode === 'live') {
                    autonomySubmitLiveConfirmation();
                    return;
                }
                const operator = autonomyConfirmOperator?.value.trim() || '';
                const rationale = autonomyConfirmRationale?.value.trim() || '';
                const accepted = !!autonomyConfirmAck?.checked;
                const selectedScenarios = autonomyConfirmDialog?.querySelectorAll('[data-autonomy-confirm-scenario]:checked').length || 0;
                if (autonomyFixtureId !== 'ready-to-confirm' || !operator || !rationale || !accepted || selectedScenarios === 0) {
                    if (autonomyConfirmError) {
                        autonomyConfirmError.hidden = false;
                        autonomyConfirmError.textContent = autonomyFixtureId !== 'ready-to-confirm'
                            ? 'This fixture is not ready for grouped confirmation.'
                            : (selectedScenarios === 0
                                ? 'Select at least one fixture scenario before previewing queue state.'
                                : 'Enter the operator name and rationale, then acknowledge the exact fixture request review.');
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
            [autonomyLiveBuildComparisonBtn, autonomyLiveDecideBuildBtn].filter(Boolean).forEach((button) => {
                button.addEventListener('click', () => autonomyBuildComparisonBundle());
            });
            autonomyLiveCreateBriefBtn?.addEventListener('click', () => autonomyCreateDecisionBrief());
            autonomyLiveDecideOpenBtn?.addEventListener('click', () => {
                autonomySetView('decision-brief', {focus: true, announce: true});
            });
            autonomyLiveReturnToCompareBtn?.addEventListener('click', () => autonomyReturnFromLiveBrief());
            autonomyLiveBundleSelect?.addEventListener('change', () => {
                if (autonomyContentMode === 'live' && autonomyLiveBundleSelect.value) {
                    autonomySelectComparisonBundle(autonomyLiveBundleSelect.value);
                }
            });
            autonomyLiveBriefSelect?.addEventListener('change', () => {
                if (autonomyContentMode === 'live' && autonomyLiveBriefSelect.value) {
                    autonomySelectDecisionBrief(autonomyLiveBriefSelect.value);
                }
            });
            autonomyLiveAskWhyBtn?.addEventListener('click', () => autonomyToggleLiveWhy());
            autonomyLiveTestReversalBtn?.addEventListener('click', () => {
                if (!autonomyDecisionActionIsAllowed(AUTONOMY_DECISION_REVERSAL_ACTIONS)) return;
                autonomyReturnFromLiveBrief({announce: false});
                window.requestAnimationFrame(() => autonomyCreateAlternativeBtn?.focus({preventScroll: false}));
                autonomyAnnounce('Compare scenarios opened. No scenario was created or executed.');
            });
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
            autonomyPanel.querySelectorAll('[data-autonomy-live-disposition]').forEach((button) => {
                button.addEventListener('click', () => autonomyOpenLiveSignoff(
                    button.dataset.autonomyLiveDisposition, button
                ));
            });
            autonomyPanel.querySelectorAll('[name="autonomyLiveDisposition"]').forEach((input) => {
                input.addEventListener('change', () => {
                    if (input.checked) autonomyRenderLiveWarningAcknowledgements(input.value);
                    autonomyUpdateLiveSignoffSubmitState();
                });
            });
            autonomyLiveSignoffOwner?.addEventListener('input', autonomyUpdateLiveSignoffSubmitState);
            autonomyLiveSignoffRationale?.addEventListener('input', autonomyUpdateLiveSignoffSubmitState);
            autonomyLiveSignoffAck?.addEventListener('change', autonomyUpdateLiveSignoffSubmitState);
            autonomyLiveSignoffCancelBtn?.addEventListener('click', () => autonomyCloseDialog(autonomyLiveSignoffDialog));
            autonomyLiveSignoffSubmitBtn?.addEventListener('click', () => autonomySubmitLiveSignoff());
            autonomyLiveDraftReportBtn?.addEventListener('click', () => autonomyGenerateDecisionReport('draft'));
            autonomyLiveFinalReportBtn?.addEventListener('click', () => autonomyGenerateDecisionReport('final'));
            autonomyLiveReportRows?.addEventListener('click', (event) => {
                const button = event.target.closest('[data-autonomy-verify-report]');
                if (button) autonomyVerifyDecisionReport(button.dataset.autonomyVerifyReport);
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
            autonomyPanel.querySelectorAll('[name="autonomyDisposition"]').forEach((input) => {
                input.addEventListener('change', autonomyUpdateFixtureSignoffSubmitState);
            });
            autonomySignoffOwner?.addEventListener('input', autonomyUpdateFixtureSignoffSubmitState);
            autonomySignoffRationale?.addEventListener('input', autonomyUpdateFixtureSignoffSubmitState);
            autonomySignoffAck?.addEventListener('change', autonomyUpdateFixtureSignoffSubmitState);
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
                    const autonomyOpenModal = [autonomyConfirmDialog, autonomyScenarioDialog, autonomySignoffDialog, autonomyLiveSignoffDialog]
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
                const autonomyOpenModal = [autonomyConfirmDialog, autonomyScenarioDialog, autonomySignoffDialog]
                    .find((dialog) => dialog?.open);
                if (autonomyOpenModal) autonomyTrapFocus(event, autonomyOpenModal);
                else if (autonomyEvidenceRail?.classList.contains('is-open')) autonomyTrapFocus(event, autonomyEvidenceRail);
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
