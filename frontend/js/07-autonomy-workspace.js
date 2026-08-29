        const AUTONOMY_CASE_ID = 'case_sbe_hybrid_001';
        const AUTONOMY_CASE_REVISION = 'revision_003';
        const AUTONOMY_ANNUAL_SOURCE_ID = 'ann_2024_verified_017';
        const AUTONOMY_TEA_BASIS = 'SolarTAC site · tea-calculation-v3';
        const AUTONOMY_STAGES = Object.freeze(['ask', 'verify', 'compare', 'run', 'decide']);
        const AUTONOMY_READINESS_KEYS = Object.freeze(['calibration', 'annual', 'weather', 'evidence', 'agent']);

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

        let autonomyFixtureId = 'evidence-needed';
        let autonomySelectedStage = AUTONOMY_FIXTURE_CATALOG[autonomyFixtureId].stage;
        let autonomySelectedView = AUTONOMY_FIXTURE_CATALOG[autonomyFixtureId].defaultView;
        let autonomySelectedRailTab = 'evidence';
        let autonomyMobileSection = 'ask';
        let autonomyLastRailTrigger = null;
        let autonomyLastDialogTrigger = null;
        let autonomyInitialized = false;
        let autonomySignedDecision = {
            disposition: 'accept',
            owner: 'Jordan Lee',
            rationale: 'The reviewed evidence supports the conditional recommendation.',
        };

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
            const requestedBrief = view === 'decision-brief';
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
            autonomyNewDecisionBtn?.addEventListener('click', () => autonomySelectFixture('new-case'));
            autonomyPanel.querySelectorAll('[data-autonomy-fixture-action="start"]').forEach((button) => {
                button.addEventListener('click', () => autonomySelectFixture('new-case'));
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
                        autonomyAnnounce('Fixture ' + action + ' preview selected. No case record was changed.');
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
                });
            });
            autonomyEvidenceReviewBtn?.addEventListener('click', () => {
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
            autonomyRenderWorkspace();
        }

        autonomyInitializeWorkspace();
