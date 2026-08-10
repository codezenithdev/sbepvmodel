        // ---- Solar Agent chat ----
        const chatToggle = document.getElementById('chatToggle');
        const minimizeChat = document.getElementById('minimizeChat');
        const closeChat = document.getElementById('closeChat');
        const newChatBtn = document.getElementById('newChatBtn');
        const chatSidebar = document.getElementById('chatSidebar');
        const chatDragHandle = document.getElementById('chatDragHandle');
        const chatInput = document.getElementById('chatInput');
        const sendBtn = document.getElementById('sendBtn');
        const messagesContainer = document.getElementById('messages');
        const chatComposerStatus = document.getElementById('chatComposerStatus');
        const chatHistoryBtn = document.getElementById('chatHistoryBtn');
        const chatHistoryCount = document.getElementById('chatHistoryCount');
        const chatHistoryPanel = document.getElementById('chatHistory');
        const chatHistoryList = document.getElementById('chatHistoryList');
        const chatHistoryBack = document.getElementById('chatHistoryBack');
        const chatHistoryStorageStatus = document.getElementById('chatHistoryStorageStatus');
        const agentContextBadge = document.getElementById('agentContextBadge');
        const agentContextText = document.getElementById('agentContextText');
        const agentActivity = document.getElementById('agentActivity');
        const agentActivityList = document.getElementById('agentActivityList');
        const agentActivityBody = document.getElementById('agentActivityBody');
        const agentActivitySummary = document.getElementById('agentActivitySummary');
        const agentActivityBack = document.getElementById('agentActivityBack');
        const agentRefreshBtn = document.getElementById('agentRefreshBtn');
        const agentActivityToggle = document.getElementById('agentActivityToggle');
        const agentActivityToggleLabel = document.getElementById('agentActivityToggleLabel');
        const agentActivityCount = document.getElementById('agentActivityCount');
        const dashboardShell = document.querySelector('.app-shell');
        const CHAT_POSITION_KEY = 'sb-energy-chat-position-v1';
        const CHAT_WINDOW_POSITION_KEY = 'sb-energy-chat-window-position-v1';
        const CHAT_MOBILE_BREAKPOINT = 560;
        let chatDragState = null;
        let chatWindowDragState = null;
        let savedChatWindowPosition = null;
        let suppressChatClick = false;
        let lastChatTrigger = null;
        let agentActivityInteractionPointerId = null;
        let agentActivityRenderQueued = false;

        function defaultChatConversationMessages(createdAt = new Date().toISOString()) {
            return [{
                role: 'assistant',
                content: DEFAULT_ASSISTANT_MESSAGE,
                created_at: normalizeChatTimestamp(createdAt).toISOString(),
            }];
        }

        function createChatConversationId() {
            if (window.crypto?.randomUUID) return window.crypto.randomUUID();
            return 'chat-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
        }

        function normalizeStoredChatMessage(item) {
            if (!item || typeof item !== 'object' || item.content === null || item.content === undefined) return null;
            const content = String(item.content);
            if (!content) return null;
            const restored = {
                role: item.role === 'user' ? 'user' : 'assistant',
                content,
                created_at: normalizeChatTimestamp(
                    item.created_at || item.createdAt
                ).toISOString(),
                gpt_seconds: finiteElapsedSeconds(
                    item.gpt_seconds ?? item.gptSeconds
                ),
                model_run_seconds: finiteElapsedSeconds(
                    item.model_run_seconds ?? item.modelSeconds
                ),
                model_run_status: String(
                    item.model_run_status || item.modelStatus || 'not_run'
                ),
                automated: item.automated === true,
            };
            const restoredSources = collectExternalEvidence(content, item);
            if (item.web_search_enabled === true || restoredSources.length) {
                restored.web_search_enabled = true;
                restored.web_sources = restoredSources;
            }
            const actionCard = normalizeChatActionCard(item.action_card);
            if (actionCard) restored.action_card = actionCard;
            return restored;
        }

        function chatConversationTitle(messages, draft = '') {
            const firstUserMessage = (messages || []).find((message) => message?.role === 'user' && message.content);
            const source = String(firstUserMessage?.content || draft || '').replace(/\s+/g, ' ').trim();
            if (!source) return 'New conversation';
            return source.length > 58 ? source.slice(0, 57) + '...' : source;
        }

        function chatConversationPreview(conversation) {
            const messages = Array.isArray(conversation?.messages) ? conversation.messages : [];
            const lastMessage = [...messages].reverse().find((message) => (
                message?.content && message.content !== DEFAULT_ASSISTANT_MESSAGE
            ));
            const source = String(lastMessage?.content || conversation?.draft || 'No messages yet')
                .replace(/\s+/g, ' ')
                .trim();
            return source.length > 105 ? source.slice(0, 104) + '...' : source;
        }

        function chatConversationHasContent(conversation) {
            if (String(conversation?.draft || '').trim()) return true;
            return (conversation?.messages || []).some((message) => (
                message?.role === 'user' ||
                (message?.content && message.content !== DEFAULT_ASSISTANT_MESSAGE)
            ));
        }

        function chatMessageHasNonterminalAction(message) {
            const card = normalizeChatActionCard(message?.action_card);
            if (!card) return false;
            const status = String(card.status || '').toLowerCase();
            return !TERMINAL_CHAT_ACTION_STATUSES.has(status) && (
                card.job_id || card.job_ids?.length ||
                card.proposal_id || card.proposal_ids?.length ||
                card.sweep_id
            );
        }

        function trimChatMessages(messages, limit = 50) {
            const items = Array.isArray(messages) ? messages : [];
            if (items.length <= limit) return items;
            const cutoff = items.length - limit;
            const pinned = items.slice(0, cutoff).filter(chatMessageHasNonterminalAction);
            const pinnedTail = pinned.slice(-limit);
            const remaining = limit - pinnedTail.length;
            if (!remaining) return pinnedTail;
            return [
                ...pinnedTail,
                ...items.slice(-remaining),
            ];
        }

        function chatConversationHasNonterminalAction(conversation) {
            return (conversation?.messages || []).some(chatMessageHasNonterminalAction);
        }

        function chatConversationIsProtected(conversation) {
            return conversation?.id === activeChatConversationId ||
                transientProtectedConversationIds.has(conversation?.id) ||
                chatConversationHasNonterminalAction(conversation);
        }

        function compactChatConversationForStorage(conversation, level) {
            const configurations = [
                { recentMessages: 24, contentCharacters: 4000, draftCharacters: 2000 },
                { recentMessages: 12, contentCharacters: 2000, draftCharacters: 1000 },
                { recentMessages: 6, contentCharacters: 1000, draftCharacters: 500 },
                { recentMessages: 2, contentCharacters: 500, draftCharacters: 250 },
            ];
            const configuration = configurations[Math.min(
                Math.max(level - 1, 0),
                configurations.length - 1
            )];
            const messages = Array.isArray(conversation.messages) ? conversation.messages : [];
            const recentStart = Math.max(0, messages.length - configuration.recentMessages);
            const compactedMessages = messages
                .filter((message, index) => index >= recentStart || chatMessageHasNonterminalAction(message))
                .map((message) => {
                    const content = String(message.content || '');
                    const compacted = {
                        ...message,
                        content: content.length > configuration.contentCharacters
                            ? content.slice(0, configuration.contentCharacters - 3) + '...'
                            : content,
                    };
                    if (level >= 3) delete compacted.web_sources;
                    return compacted;
                });
            return {
                ...conversation,
                draft: String(conversation.draft || '').slice(0, configuration.draftCharacters),
                messages: compactedMessages,
            };
        }

        function createChatConversation(messages = null, draft = '') {
            const now = new Date().toISOString();
            const normalizedMessages = trimChatMessages(
                (Array.isArray(messages) ? messages : defaultChatConversationMessages(now))
                .map(normalizeStoredChatMessage)
                .filter(Boolean)
            );
            const safeMessages = normalizedMessages.length
                ? normalizedMessages
                : defaultChatConversationMessages(now);
            return {
                id: createChatConversationId(),
                title: chatConversationTitle(safeMessages, draft),
                created_at: safeMessages[0]?.created_at || now,
                updated_at: safeMessages.at(-1)?.created_at || now,
                draft: String(draft || '').slice(0, 4000),
                messages: safeMessages,
                unread: false,
            };
        }

        function normalizeChatConversation(item) {
            if (!item || typeof item !== 'object') return null;
            const draft = String(item.draft || '').slice(0, 4000);
            const messages = trimChatMessages(
                (Array.isArray(item.messages) ? item.messages : [])
                .map(normalizeStoredChatMessage)
                .filter(Boolean)
            );
            const safeMessages = messages.length
                ? messages
                : defaultChatConversationMessages(item.created_at);
            const createdAt = normalizeChatTimestamp(
                item.created_at || safeMessages[0]?.created_at
            ).toISOString();
            const latestMessageTime = safeMessages.reduce((latest, message) => {
                const parsed = Date.parse(message.created_at);
                return Number.isFinite(parsed) ? Math.max(latest, parsed) : latest;
            }, Date.parse(createdAt));
            const requestedUpdatedAt = Date.parse(item.updated_at || '');
            const updatedAt = new Date(Math.max(
                latestMessageTime,
                Number.isFinite(requestedUpdatedAt) ? requestedUpdatedAt : latestMessageTime
            )).toISOString();
            return {
                id: String(item.id || createChatConversationId()).slice(0, 160),
                title: chatConversationTitle(safeMessages, draft),
                created_at: createdAt,
                updated_at: updatedAt,
                draft,
                messages: safeMessages,
                unread: item.unread === true,
            };
        }

        function activeChatConversation() {
            return chatConversations.find((conversation) => conversation.id === activeChatConversationId) || null;
        }

        function syncActiveChatConversation() {
            let conversation = activeChatConversation();
            if (!conversation) {
                conversation = createChatConversation(chatMessages, chatDraft);
                chatConversations.unshift(conversation);
                activeChatConversationId = conversation.id;
            }
            const previousDraft = conversation.draft;
            const normalizedMessages = trimChatMessages(
                chatMessages
                .map(normalizeStoredChatMessage)
                .filter(Boolean)
            );
            conversation.messages = normalizedMessages.length
                ? normalizedMessages
                : defaultChatConversationMessages(conversation.created_at);
            conversation.draft = String(chatDraft || '').slice(0, 4000);
            conversation.title = chatConversationTitle(conversation.messages, conversation.draft);
            conversation.unread = false;
            const latestMessageTime = conversation.messages.reduce((latest, message) => {
                const parsed = Date.parse(message.created_at);
                return Number.isFinite(parsed) ? Math.max(latest, parsed) : latest;
            }, Date.parse(conversation.updated_at || conversation.created_at));
            conversation.updated_at = new Date(Math.max(
                latestMessageTime,
                previousDraft !== conversation.draft ? Date.now() : 0
            )).toISOString();
            chatMessages = conversation.messages;
            return conversation;
        }

        function sortedVisibleChatConversations() {
            return chatConversations
                .filter(chatConversationHasContent)
                .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at));
        }

        function readChatConversationHistory() {
            try {
                return JSON.parse(localStorage.getItem(CHAT_HISTORY_STORAGE_KEY) || 'null');
            } catch (_) {
                return null;
            }
        }

        function isChatHistoryQuotaError(error) {
            return error?.name === 'QuotaExceededError' ||
                error?.name === 'NS_ERROR_DOM_QUOTA_REACHED' ||
                error?.code === 22 || error?.code === 1014;
        }

        function saveChatConversationHistory(syncActive = true) {
            if (syncActive) syncActiveChatConversation();
            chatHistoryRevision += 1;
            const eligible = chatConversations
                .filter((conversation) => conversation.id === activeChatConversationId || chatConversationHasContent(conversation))
                .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at));
            const active = eligible.find((conversation) => conversation.id === activeChatConversationId);
            const protectedCandidates = [
                active,
                ...eligible.filter((conversation) => (
                    conversation.id !== activeChatConversationId && chatConversationIsProtected(conversation)
                )),
            ].filter(Boolean);
            const candidateIds = new Set();
            const protectedUnique = protectedCandidates
                .filter((conversation) => {
                    if (candidateIds.has(conversation.id)) return false;
                    candidateIds.add(conversation.id);
                    return true;
                });
            const recentOrdinary = eligible.filter((conversation) => !candidateIds.has(conversation.id));
            let candidates = [
                ...protectedUnique,
                ...recentOrdinary.slice(0, Math.max(
                    0,
                    MAX_SAVED_CHAT_CONVERSATIONS - protectedUnique.length
                )),
            ];
            let compactionLevel = 0;
            while (candidates.length) {
                try {
                    const persistenceState = chatHistoryStickyIssue === 'possible_loss'
                        ? 'possible_loss'
                        : (
                            chatHistoryStickyIssue === 'degraded' ||
                            compactionLevel > 0 || candidates.length < eligible.length
                        ) ? 'degraded' : 'ok';
                    localStorage.setItem(CHAT_HISTORY_STORAGE_KEY, JSON.stringify({
                        version: 1,
                        revision: chatHistoryRevision,
                        persistence_state: persistenceState,
                        active_conversation_id: activeChatConversationId,
                        conversations: compactionLevel
                            ? candidates.map((conversation) => (
                                compactChatConversationForStorage(conversation, compactionLevel)
                            ))
                            : candidates,
                    }));
                    chatHistoryPersistenceState = persistenceState;
                    return true;
                } catch (error) {
                    if (!isChatHistoryQuotaError(error)) {
                        chatHistoryPersistenceState = 'failed';
                        return false;
                    }
                    if (compactionLevel === 0) {
                        compactionLevel = 1;
                        continue;
                    }
                    const removableIndex = candidates.findLastIndex(
                        (conversation) => !chatConversationIsProtected(conversation)
                    );
                    if (removableIndex >= 0) {
                        candidates = candidates.filter((_, index) => index !== removableIndex);
                        continue;
                    }
                    if (compactionLevel < 4) {
                        compactionLevel += 1;
                        continue;
                    }
                    chatHistoryPersistenceState = 'failed';
                    return false;
                }
            }
            chatHistoryPersistenceState = 'failed';
            return false;
        }

        function restoreChatConversationHistory(
            legacyMessages = null,
            legacyDraft = '',
            legacyActiveConversationId = '',
            legacyHistoryRevision = 0,
            legacyPersistenceState = 'ok'
        ) {
            const stored = readChatConversationHistory();
            const storedRevision = Number(stored?.revision) || 0;
            const savedRevision = Number(legacyHistoryRevision) || 0;
            const legacyFailedWithoutRevision = (
                savedRevision === 0 && storedRevision === 0 && legacyPersistenceState === 'failed'
            );
            const recoverLegacyActive = savedRevision > storedRevision || legacyFailedWithoutRevision;
            chatHistoryRevision = Math.max(storedRevision, savedRevision);
            chatHistoryStickyIssue = recoverLegacyActive || stored?.persistence_state === 'possible_loss'
                ? 'possible_loss'
                : stored?.persistence_state === 'degraded' ? 'degraded' : 'none';
            chatHistoryPersistenceState = recoverLegacyActive
                ? 'possible_loss'
                : ['degraded', 'possible_loss'].includes(stored?.persistence_state)
                    ? stored.persistence_state
                    : 'ok';
            const rawConversations = Array.isArray(stored)
                ? stored
                : (Array.isArray(stored?.conversations) ? stored.conversations : []);
            const seenIds = new Set();
            chatConversations = rawConversations
                .map(normalizeChatConversation)
                .filter((conversation) => {
                    if (!conversation || seenIds.has(conversation.id)) return false;
                    seenIds.add(conversation.id);
                    return true;
                })
                .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at));
            const recoveredActiveId = String(legacyActiveConversationId || '').slice(0, 160);
            if (recoverLegacyActive && Array.isArray(legacyMessages)) {
                const recovered = createChatConversation(legacyMessages, legacyDraft);
                if (recoveredActiveId) recovered.id = recoveredActiveId;
                const existingIndex = chatConversations.findIndex(
                    (conversation) => conversation.id === recovered.id
                );
                if (existingIndex >= 0) {
                    recovered.created_at = chatConversations[existingIndex].created_at;
                    chatConversations.splice(existingIndex, 1, recovered);
                } else {
                    chatConversations.unshift(recovered);
                }
            }
            if (!chatConversations.length) {
                chatConversations = [createChatConversation(legacyMessages, legacyDraft)];
            }
            const requestedActiveId = recoverLegacyActive && recoveredActiveId
                ? recoveredActiveId
                : String(stored?.active_conversation_id || '');
            const active = chatConversations.find((conversation) => conversation.id === requestedActiveId)
                || chatConversations[0];
            const protectedConversations = chatConversations.filter((conversation) => (
                conversation.id === active.id || chatConversationHasNonterminalAction(conversation)
            ));
            const protectedIds = new Set(protectedConversations.map((conversation) => conversation.id));
            const recentConversations = chatConversations.filter(
                (conversation) => !protectedIds.has(conversation.id)
            );
            chatConversations = [
                ...protectedConversations,
                ...recentConversations.slice(0, Math.max(
                    0,
                    MAX_SAVED_CHAT_CONVERSATIONS - protectedConversations.length
                )),
            ];
            activeChatConversationId = active.id;
            active.unread = false;
            chatMessages = active.messages;
            chatDraft = active.draft;
            rebuildAgentCompletionCardIndex();
        }

        function rebuildAgentCompletionCardIndex() {
            chatConversations.forEach((conversation) => {
                conversation.messages.forEach((message) => {
                    const card = normalizeChatActionCard(message.action_card);
                    const completionStatus = String(card?.status || '').toLowerCase();
                    const isRecordedCompletion = ['done', 'error', 'cancelled', 'interrupted'].includes(
                        completionStatus
                    );
                    if (card?.kind === 'run_complete' && card.job_id && isRecordedCompletion) {
                        agentCompletionCards.add('job:' + card.job_id);
                    } else if (card?.kind === 'sweep_complete' && card.sweep_id && isRecordedCompletion) {
                        agentCompletionCards.add('sweep:' + card.sweep_id);
                    }
                });
            });
        }

        function syncChatHistoryControls() {
            const conversations = sortedVisibleChatConversations();
            const unreadCount = conversations.filter((conversation) => conversation.unread).length;
            chatHistoryCount.textContent = String(conversations.length);
            chatHistoryBtn.disabled = chatIsSending || chatHydrationPending;
            chatHistoryBtn.setAttribute('aria-expanded', String(chatHistoryOpen));
            chatHistoryBtn.setAttribute(
                'aria-label',
                unreadCount
                    ? 'View Solar Agent conversations, ' + unreadCount + ' with new updates'
                    : 'View Solar Agent conversations'
            );
            if (chatHistoryPersistenceState !== 'ok') {
                chatHistoryBtn.setAttribute(
                    'aria-label',
                    chatHistoryBtn.getAttribute('aria-label') + (
                        chatHistoryPersistenceState === 'failed'
                            ? '. Recent changes are not saved'
                            : chatHistoryPersistenceState === 'possible_loss'
                                ? '. Some recent conversation updates may be missing after storage recovery'
                                : '. Some older content is not included in the saved browser archive'
                    )
                );
            }
            chatHistoryBtn.title = chatHistoryPersistenceState === 'failed'
                ? 'Recent conversation changes could not be saved in this browser'
                : chatHistoryPersistenceState === 'possible_loss'
                    ? 'Some recent conversation updates may be missing after storage recovery'
                : chatHistoryPersistenceState === 'degraded'
                    ? 'Some older content is not included in the saved browser archive'
                    : chatHydrationPending
                        ? 'Wait while the saved dashboard context is restored'
                        : chatIsSending
                            ? 'Wait for the current response before switching conversations'
                            : 'View conversations';
            const storageMessage = chatHistoryPersistenceState === 'failed'
                ? 'Recent conversation changes could not be saved in this browser. Keep this page open and try again after freeing browser storage.'
                : chatHistoryPersistenceState === 'possible_loss'
                    ? 'Some recent conversation updates may be missing after browser-storage recovery. Future changes are saving, but verify important run updates.'
                : chatHistoryPersistenceState === 'degraded'
                    ? 'The saved browser archive keeps the newest 20 conversations and may trim older content to fit. Conversations in this open page are unchanged.'
                    : '';
            if (chatHistoryStorageStatus.textContent !== storageMessage) {
                chatHistoryStorageStatus.textContent = storageMessage;
            }
            chatHistoryStorageStatus.hidden = !storageMessage;
        }

        function renderChatHistory() {
            syncActiveChatConversation();
            syncChatHistoryControls();
            const focusedConversationId = chatHistoryList.contains(document.activeElement)
                ? document.activeElement.closest('[data-chat-conversation-id]')?.dataset.chatConversationId
                : null;
            chatHistoryList.innerHTML = '';
            const conversations = sortedVisibleChatConversations();
            if (!conversations.length) {
                const empty = document.createElement('div');
                empty.className = 'chat-history-empty';
                empty.setAttribute('role', 'listitem');
                empty.textContent = 'Your previous Solar Agent conversations will appear here after you send a message.';
                chatHistoryList.appendChild(empty);
                return;
            }
            conversations.forEach((conversation) => {
                const item = document.createElement('div');
                item.setAttribute('role', 'listitem');
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'chat-history-card';
                button.dataset.chatConversationId = conversation.id;
                button.classList.toggle('active', conversation.id === activeChatConversationId);
                button.disabled = chatIsSending || chatHydrationPending;
                button.setAttribute('aria-current', conversation.id === activeChatConversationId ? 'true' : 'false');

                const head = document.createElement('span');
                head.className = 'chat-history-card-head';
                const title = document.createElement('span');
                title.className = 'chat-history-title';
                title.textContent = conversation.title;
                head.appendChild(title);
                if (conversation.id === activeChatConversationId || conversation.unread) {
                    const state = document.createElement('span');
                    state.className = 'chat-history-state' + (conversation.unread ? ' unread' : '');
                    state.textContent = conversation.unread ? 'Updated' : 'Current';
                    head.appendChild(state);
                }

                const preview = document.createElement('span');
                preview.className = 'chat-history-preview';
                preview.textContent = chatConversationPreview(conversation);
                const meta = document.createElement('span');
                meta.className = 'chat-history-card-meta';
                const messageCount = conversation.messages.filter((message) => (
                    message.content !== DEFAULT_ASSISTANT_MESSAGE
                )).length;
                meta.textContent = messageCount + ' message' + (messageCount === 1 ? '' : 's') +
                    ' - ' + formatDashboardTimestamp(conversation.updated_at);
                button.append(head, preview, meta);
                item.appendChild(button);
                chatHistoryList.appendChild(item);
            });
            if (focusedConversationId) {
                window.requestAnimationFrame(() => {
                    const focusTarget = Array.from(chatHistoryList.querySelectorAll('[data-chat-conversation-id]'))
                        .find((element) => element.dataset.chatConversationId === focusedConversationId);
                    (focusTarget || chatHistoryBack).focus({ preventScroll: true });
                });
            }
        }

        function setChatHistoryOpen(open, persist = true) {
            if (open && chatIsSending) return;
            if (open) setAgentActivityOpen(false, false);
            chatHistoryOpen = !!open;
            chatSidebar.classList.toggle('history-view', chatHistoryOpen);
            chatHistoryPanel.classList.toggle('hidden', !chatHistoryOpen);
            renderChatHistory();
            if (persist) saveDashboardState();
        }

        function openChatConversation(conversationId) {
            if (chatIsSending || chatHydrationPending) return;
            syncActiveChatConversation();
            const conversation = chatConversations.find((item) => item.id === conversationId);
            if (!conversation) return;
            activeChatConversationId = conversation.id;
            conversation.unread = false;
            chatMessages = conversation.messages;
            chatDraft = conversation.draft;
            chatInput.value = chatDraft;
            autoResizeChatInput();
            syncChatComposerState();
            setChatHistoryOpen(false, false);
            messagesContainer.setAttribute('aria-live', 'off');
            renderChatMessages();
            saveDashboardState();
            chatInput.focus();
            window.requestAnimationFrame(() => {
                messagesContainer.setAttribute('aria-live', 'polite');
                if (activeChatConversationId === conversation.id) {
                    chatComposerStatus.textContent = 'Opened ' + conversation.title + '. New messages use the active dashboard context.';
                }
            });
        }

        function isChatMobile() {
            return window.innerWidth <= CHAT_MOBILE_BREAKPOINT;
        }

