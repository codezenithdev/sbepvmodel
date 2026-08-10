        function escapeHtml(text) {
            const map = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            };
            return text.replace(/[&<>"']/g, m => map[m]);
        }

        function renderSafeMarkdown(text) {
            const lines = String(text || '').replace(/\r\n/g, '\n').split('\n');
            const html = [];
            let listOpen = false;

            function inlineMarkdown(value) {
                let out = escapeHtml(value.trim());
                out = out.replace(
                    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
                    (_, label, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`
                );
                out = out.replace(
                    /(^|[\s(>])(https?:\/\/[^\s<"]+)/g,
                    (_, prefix, url) => `${prefix}<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`
                );
                out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
                return out;
            }

            function closeList() {
                if (listOpen) {
                    html.push('</ul>');
                    listOpen = false;
                }
            }

            lines.forEach((line) => {
                const trimmed = line.trim();
                if (!trimmed) {
                    closeList();
                    return;
                }

                const bullet = trimmed.match(/^[-*]\s+(.+)$/);
                if (bullet) {
                    if (!listOpen) {
                        html.push('<ul>');
                        listOpen = true;
                    }
                    html.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
                    return;
                }

                closeList();
                const section = trimmed.match(/^\*\*([^*]+)\*\*:?\s*$/);
                if (section) {
                    html.push(`<span class="chat-section-title">${escapeHtml(section[1])}</span>`);
                    return;
                }
                html.push(`<p>${inlineMarkdown(trimmed)}</p>`);
            });

            closeList();
            return html.join('');
        }

        function isInitialChatState() {
            return chatMessages.length === 1
                && chatMessages[0].role === 'assistant'
                && chatMessages[0].content === DEFAULT_ASSISTANT_MESSAGE;
        }

        function createChatPromptButton(label, prompt) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'chat-prompt-btn';
            button.dataset.chatPrompt = prompt;
            button.textContent = label;
            return button;
        }

        function activeChatPrompts() {
            if (activeView === 'technoeconomic') {
                return [
                    ['Explain LCOO and LCOE', 'Explain the LCOO and LCOE shown in the active technoeconomic analysis'],
                    ['Review cost assumptions', 'Review the visible annualized cost assumptions and identify any consistency checks'],
                    ['Compare system economics', 'Compare the baseline Solectria and optimized SolarEdge economics'],
                    ['Summarize the energy basis', 'Summarize the Annual Simulation energy values used by the technoeconomic analysis'],
                ];
            }
            if (activeMode === 'annual') {
                return [
                    ['Summarize annual energy', 'Summarize annual energy by system'],
                    ['Explain the main yield drivers', 'Which assumptions influence annual yield most?'],
                    ['Compare both systems', 'Compare SolarEdge and Solectria annual performance'],
                    ['Explore an efficiency scenario', 'Prepare a 2% efficiency improvement scenario'],
                    ['Sweep IAM a_r', 'Run annual IAM a_r from 0.1 to 0.5 by 0.1 and compare the results'],
                ];
            }
            return [
                ['Summarize this view', 'Summarize this calibration window'],
                ['Explain modeled vs measured', 'Why do measured and modeled values differ?'],
                ['Compare both systems', 'Compare SolarEdge and Solectria'],
                ['Test backtracking off', 'Test what changes with backtracking off'],
                ['Sweep inverter efficiency', 'Run SolarEdge inverter efficiency from 0.96 to 1.00 by 0.01 and compare the results'],
            ];
        }

        function renderChatWelcome() {
            messagesContainer.innerHTML = '';
            const welcome = document.createElement('div');
            welcome.className = 'chat-welcome';
            const mark = document.createElement('div');
            mark.className = 'chat-welcome-mark';
            mark.setAttribute('aria-hidden', 'true');
            const copy = document.createElement('div');
            copy.className = 'chat-welcome-copy';
            const title = document.createElement('div');
            title.className = 'chat-welcome-title';
            title.textContent = 'Turn solar data into clear decisions';
            const description = document.createElement('p');
            description.className = 'chat-welcome-description';
            description.textContent = DEFAULT_ASSISTANT_MESSAGE;
            copy.append(title, description);
            const prompts = document.createElement('div');
            prompts.className = 'chat-prompt-grid';
            prompts.setAttribute('aria-label', 'Suggested Solar Agent questions');
            activeChatPrompts().forEach(([label, prompt]) => prompts.appendChild(createChatPromptButton(label, prompt)));
            const note = document.createElement('div');
            note.className = 'chat-welcome-note';
            note.textContent = 'Agent scenarios cannot replace the active baseline without your action.';
            welcome.append(mark, copy, prompts, note);
            messagesContainer.appendChild(welcome);
        }

        function renderChatFollowups() {
            messagesContainer.querySelector('.chat-followups')?.remove();
            if (isInitialChatState() || chatIsSending || chatMessages.at(-1)?.role !== 'assistant') return;
            const followups = document.createElement('div');
            followups.className = 'chat-followups';
            followups.setAttribute('aria-label', 'Suggested follow-up questions');
            const prompts = activeView === 'technoeconomic'
                ? [
                    ['Explain the cost delta', 'Explain the marginal annualized cost used in LCOO'],
                    ['Check assumptions', 'Check whether the visible technoeconomic assumptions are internally consistent'],
                ]
                : activeMode === 'annual'
                ? [
                    ['Explain yield drivers', 'Explain the most important annual yield drivers'],
                    ['Explore efficiency', 'Prepare an annual efficiency improvement scenario'],
                ]
                : [
                    ['Show the largest gaps', 'Show the largest measured versus modeled gaps'],
                    ['Explore backtracking', 'Prepare a backtracking-off comparison scenario'],
                ];
            prompts.forEach(([label, prompt]) => followups.appendChild(createChatPromptButton(label, prompt)));
            messagesContainer.appendChild(followups);
        }

        function shouldStickChatToBottom() {
            return messagesContainer.scrollHeight - messagesContainer.scrollTop - messagesContainer.clientHeight < 90;
        }

        function scrollChatToBottom(force = false) {
            if (!force && !shouldStickChatToBottom()) return;
            window.requestAnimationFrame(() => {
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            });
        }

        function normalizeChatTimestamp(value) {
            const parsed = new Date(value || Date.now());
            return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
        }

        function formatDashboardTimestamp(value) {
            const parts = new Intl.DateTimeFormat('en-US', {
                timeZone: 'America/Denver',
                month: '2-digit',
                day: '2-digit',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
                hourCycle: 'h23',
            }).formatToParts(normalizeChatTimestamp(value));
            const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
            return `${values.month}-${values.day}-${values.year} ${values.hour}:${values.minute}`;
        }

        function finiteElapsedSeconds(value) {
            if (value === null || value === undefined || value === '') return null;
            const numeric = Number(value);
            return Number.isFinite(numeric) && numeric >= 0 ? numeric : null;
        }

        function formatElapsedSeconds(value) {
            const seconds = finiteElapsedSeconds(value);
            return seconds === null ? null : `${seconds.toFixed(1)}s`;
        }

        function modelTimingText(status, seconds) {
            const formatted = formatElapsedSeconds(seconds);
            if (formatted !== null) return `Model run ${formatted}`;
            if (status === 'queued') return 'Model run queued';
            if (status === 'running') return 'Model run in progress';
            if (status === 'done' || status === 'completed') return 'Model run completed';
            if (status === 'failed') return 'Model run failed';
            if (status === 'canceled' || status === 'cancelled') return 'Model run canceled';
            return 'Model run not used';
        }

        function assistantMessageFromResponse(content, data = {}) {
            const timing = data.timing || {};
            const message = {
                role: 'assistant',
                content,
                created_at: normalizeChatTimestamp(
                    timing.response_timestamp
                ).toISOString(),
                gpt_seconds: finiteElapsedSeconds(timing.gpt_seconds),
                model_run_seconds: finiteElapsedSeconds(timing.model_run_seconds),
                model_run_status: timing.model_run_status || 'not_run',
                automated: data.automated === true,
            };
            const webSources = collectExternalEvidence(content, data);
            if (data.web_search_enabled === true || webSources.length) {
                message.web_search_enabled = true;
                message.web_sources = webSources;
            }
            const actionCard = normalizeChatActionCard(data.action_card);
            if (actionCard) message.action_card = actionCard;
            return message;
        }

        function applyMessageMeta(message, role, options = {}) {
            message.querySelector('.message-meta')?.remove();
            if (!['user', 'assistant'].includes(role) || options.loading) return;

            const createdAt = normalizeChatTimestamp(
                options.created_at || options.createdAt
            ).toISOString();
            const meta = document.createElement('div');
            meta.className = 'message-meta';

            const timestamp = document.createElement('time');
            timestamp.dateTime = createdAt;
            timestamp.textContent = formatDashboardTimestamp(createdAt);
            meta.appendChild(timestamp);

            if (role === 'assistant') {
                if (options.automated !== true) {
                    const gpt = document.createElement('span');
                    gpt.className = 'message-timing';
                    const gptSeconds = formatElapsedSeconds(
                        options.gpt_seconds ?? options.gptSeconds
                    );
                    gpt.textContent = gptSeconds === null
                        ? 'GPT time unavailable'
                        : `GPT ${gptSeconds}`;
                    meta.appendChild(gpt);
                } else {
                    const update = document.createElement('span');
                    update.className = 'message-timing';
                    update.textContent = 'Live model update';
                    meta.appendChild(update);
                }

                const model = document.createElement('span');
                model.className = 'message-timing';
                model.textContent = modelTimingText(
                    options.model_run_status || options.modelStatus,
                    options.model_run_seconds ?? options.modelSeconds
                );
                meta.appendChild(model);
            }
            message.appendChild(meta);
        }

        function renderMessageBubbleContent(bubble, content, options = {}) {
            bubble.innerHTML = renderSafeMarkdown(content);
            const actionCard = renderChatActionCard(options.action_card);
            if (actionCard) bubble.appendChild(actionCard);
        }

        function appendMessage(role, content, options = {}) {
            const shouldStick = role === 'user' || shouldStickChatToBottom();
            messagesContainer.querySelector('.chat-welcome')?.remove();
            messagesContainer.querySelector('.chat-followups')?.remove();
            const msg = document.createElement('div');
            msg.className = 'message ' + role;
            if (options.clarification) msg.classList.add('clarification');
            if (options.error) msg.classList.add('error');
            const bubble = document.createElement('div');
            bubble.className = 'message-content';
            if (options.loading) {
                msg.classList.add('is-loading');
                msg.setAttribute('role', 'status');
                bubble.innerHTML = '<span class="chat-loading-label">Reviewing dashboard</span><span class="chat-typing-dots" aria-hidden="true"><span></span><span></span><span></span></span>';
            } else {
                renderMessageBubbleContent(bubble, content, options);
            }
            msg.appendChild(bubble);
            applyMessageMeta(msg, role, options);
            messagesContainer.appendChild(msg);
            if (role === 'assistant' && !options.loading) {
                renderExternalEvidence(content, options);
            }
            if (shouldStick) scrollChatToBottom(true);
            return bubble;
        }

        function appendSystemNotice(content, kind = 'info') {
            const bubble = appendMessage('system', content, { error: kind === 'error' });
            bubble.parentElement.setAttribute('role', kind === 'error' ? 'alert' : 'status');
            return bubble;
        }

        function isClarificationReply(reply, data) {
            if (data && (data.clarification === true || data.action?.type === 'clarification')) return true;
            const text = String(reply || '');
            return /\?/.test(text) && /\b(iam|a_r|coefficient|interval|unit|clarif|do you mean|which)\b/i.test(text);
        }

        function collectExternalEvidence(reply, data) {
            if (!data || (!data.web_search_enabled && !Array.isArray(data.web_sources) && !Array.isArray(data.citations))) {
                return [];
            }
            const candidates = [];
            [data.web_sources, data.citations].forEach((supplied) => {
                if (!Array.isArray(supplied)) return;
                supplied.forEach((item) => {
                    if (typeof item === 'string') candidates.push({ label: item, url: item });
                    else if (item && item.url) candidates.push({ label: item.title || item.label || item.url, url: item.url });
                });
            });
            const markdownLink = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
            let match;
            while ((match = markdownLink.exec(String(reply || ''))) !== null) {
                candidates.push({ label: match[1], url: match[2] });
            }
            const unique = [];
            const seen = new Set();
            candidates.forEach((item) => {
                const url = String(item.url || '').slice(0, 2048);
                if (!/^https?:\/\//i.test(url) || seen.has(url)) return;
                seen.add(url);
                unique.push({
                    label: String(item.label || item.url).slice(0, 240),
                    url,
                });
            });
            return unique.slice(0, 12);
        }

        function renderExternalEvidence(reply, data) {
            const unique = collectExternalEvidence(reply, data);
            if (!unique.length) return null;
            const evidence = document.createElement('div');
            evidence.className = 'message-evidence';
            const title = document.createElement('strong');
            title.textContent = 'External research';
            evidence.appendChild(title);
            unique.forEach((item, index) => {
                if (index) evidence.appendChild(document.createTextNode(' · '));
                const link = document.createElement('a');
                link.href = item.url;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.textContent = item.label;
                evidence.appendChild(link);
            });
            messagesContainer.appendChild(evidence);
            return evidence;
        }

