        // The library discovers durable records; existing workflow renderers own evidence.
        const analysisLibrary = {
            dialog: document.getElementById('analysisLibraryDialog'),
            launcher: document.getElementById('analysisLibraryNavBtn'),
            list: document.getElementById('analysisLibraryList'),
            live: document.getElementById('analysisLibraryLive'),
            more: document.getElementById('analysisLibraryMore'),
            search: document.getElementById('analysisLibrarySearch'),
            workflow: document.getElementById('analysisLibraryWorkflow'),
            status: document.getElementById('analysisLibraryStatus'),
            revision: 0, nextOffset: null, query: null, opening: false, shown: new Set(),
        };

        function analysisLibraryTeaBusy() {
            return technoeconomicSubmissionRequestInFlight || technoeconomicLifecycleRequestInFlight
                || (technoeconomicActiveJobId && (!technoeconomicJob
                    || !technoeconomicIsTerminalState(technoeconomicJob.state)));
        }

        async function openLibraryAnalysis(item) {
            if (analysisLibrary.opening) return;
            analysisLibrary.opening = true;
            analysisLibrary.live.textContent = 'Opening ' + item.name + '…';
            try {
                if (item.workflow === 'technoeconomic') {
                    if (analysisLibraryTeaBusy()) throw new Error('Finish or cancel the active TEA request before opening another analysis.');
                    const job = technoeconomicNormalizeJob(await technoeconomicFetchJson(
                        '/api/technoeconomic/jobs/' + encodeURIComponent(item.job_id), {cache: 'no-store'}
                    ));
                    if (analysisLibraryTeaBusy()) throw new Error('A TEA request started while this result was loading. Its progress remains active.');
                    if (job.state !== 'done' || !job.result) throw new Error('Completed evidence is unavailable for this analysis.');
                    invalidateTechnoeconomicStatusPoll();
                    technoeconomicAdoptJob(job);
                    switchMode('technoeconomic', false);
                } else {
                    const loaded = await viewAgentJobResults(item.job_id, item.workflow, {preserveDraft: true});
                    if (!loaded) throw new Error('This result could not be opened. Finish any active run, or refresh history and try again.');
                    savedResultsViewedJobIds[item.workflow] = item.job_id;
                    savedResultsRestoredJobs[item.workflow] = agentJobSnapshots.get(item.job_id);
                    syncSavedResultsControls();
                }
                updateAgentContext();
                saveDashboardState();
                analysisLibrary.dialog.close();
                const heading = document.getElementById(item.workflow === 'technoeconomic'
                    ? 'technoeconomicStandaloneResults' : item.workflow === 'annual' ? 'annualResultsHeading' : 'validationResultsHeading');
                heading?.scrollIntoView({block: 'start'});
                heading?.focus({preventScroll: true});
            } catch (error) {
                analysisLibrary.live.textContent = error.message || 'The result could not be opened. Your draft was preserved.';
            } finally {
                analysisLibrary.opening = false;
            }
        }

        function analysisLibraryCard(item) {
            const card = document.createElement('article');
            card.className = 'analysis-library-card';
            const title = document.createElement('h3');
            title.textContent = item.name;
            const summary = document.createElement('p');
            const workflow = {validation: 'Calibration / model', annual: 'Annual', technoeconomic: 'TEA'}[item.workflow];
            summary.textContent = workflow + ' · ' + technoeconomicStateLabel(item.status)
                + ' · ' + formatSavedResultTimestamp(item.created_at).replace(/^Saved/, 'Created') + (item.saved ? ' · Bookmarked' : '')
                + (item.promoted_baseline ? ' · Current promoted baseline' : '');
            const identity = document.createElement('p');
            identity.textContent = 'Run ' + item.job_id + (item.source_annual_job_id ? ' · Annual source ' + item.source_annual_job_id : '');
            const open = document.createElement('button');
            open.type = 'button';
            open.textContent = item.status === 'done' ? 'Open result' : 'No completed result';
            open.disabled = item.status !== 'done';
            open.setAttribute('aria-label', 'Open result: ' + item.name + ', ' + item.job_id);
            open.addEventListener('click', () => openLibraryAnalysis(item));
            card.append(title, summary, identity, open);
            return card;
        }

        async function refreshAnalysisLibrary(append = false) {
            const revision = ++analysisLibrary.revision;
            if (!append) {
                analysisLibrary.query = {q: analysisLibrary.search.value.trim(), workflow: analysisLibrary.workflow.value, status: analysisLibrary.status.value};
                analysisLibrary.nextOffset = 0;
                analysisLibrary.list.replaceChildren();
                analysisLibrary.shown.clear();
                analysisLibrary.more.hidden = true;
            }
            const params = new URLSearchParams({...analysisLibrary.query, offset: String(analysisLibrary.nextOffset || 0), limit: '50'});
            analysisLibrary.list.setAttribute('aria-busy', 'true');
            analysisLibrary.more.disabled = true;
            analysisLibrary.live.textContent = 'Loading workspace history…';
            try {
                const response = await fetchWithDashboardTimeout('/api/analysis-library?' + params, {cache: 'no-store'});
                const body = await readAgentResponse(response, 'Could not load analysis history.');
                if (revision !== analysisLibrary.revision) return;
                if (!Array.isArray(body.items)) throw new Error('The service returned an invalid analysis list.');
                body.items.forEach(item => {
                    if (analysisLibrary.shown.has(item.id)) return;
                    analysisLibrary.shown.add(item.id);
                    analysisLibrary.list.appendChild(analysisLibraryCard(item));
                });
                analysisLibrary.nextOffset = body.next_offset;
                analysisLibrary.more.hidden = body.next_offset === null;
                const count = analysisLibrary.list.children.length;
                analysisLibrary.live.textContent = count ? count + ' analyses shown, newest first.' : 'No analyses match this search.';
            } catch (error) {
                if (revision === analysisLibrary.revision) analysisLibrary.live.textContent =
                    (error.message || 'History is unavailable.') + ' Use Search / refresh to try again.';
            } finally {
                if (revision === analysisLibrary.revision) {
                    analysisLibrary.list.setAttribute('aria-busy', 'false');
                    analysisLibrary.more.disabled = false;
                }
            }
        }

        analysisLibrary.launcher.addEventListener('click', () => {
            setSavedResultsOpen(false, {focus: false});
            setChatOpen(false, {focus: false, persist: false});
            analysisLibrary.dialog.showModal();
            analysisLibrary.search.focus();
            refreshAnalysisLibrary();
        });
        document.getElementById('analysisLibraryClose').addEventListener('click', () => analysisLibrary.dialog.close());
        document.getElementById('analysisLibrarySearchForm').addEventListener('submit', event => {
            event.preventDefault();
            refreshAnalysisLibrary();
        });
        analysisLibrary.more.addEventListener('click', () => refreshAnalysisLibrary(true));
