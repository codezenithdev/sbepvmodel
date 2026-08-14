        function autoResizeChatInput() {
            chatInput.style.height = 'auto';
            const maxHeight = parseFloat(window.getComputedStyle(chatInput).maxHeight) || 126;
            const nextHeight = Math.min(chatInput.scrollHeight, maxHeight);
            chatInput.style.height = nextHeight + 'px';
            chatInput.style.overflowY = chatInput.scrollHeight > maxHeight ? 'auto' : 'hidden';
        }

        function syncChatComposerState() {
            sendBtn.disabled = chatHydrationPending || (!chatIsSending && !chatInput.value.trim());
            newChatBtn.disabled = chatIsSending || chatHydrationPending;
            syncChatHistoryControls();
            messagesContainer.setAttribute('aria-busy', String(chatIsSending || chatHydrationPending));
            sendBtn.setAttribute(
                'aria-label',
                chatHydrationPending
                    ? 'Solar Agent is restoring the saved dashboard context'
                    : chatIsSending ? 'Cancel Solar Agent response' : 'Send message'
            );
            chatComposerStatus.textContent = chatHydrationPending
                ? 'Restoring the saved dashboard context...'
                : chatIsSending
                ? 'Reviewing the active ' + (
                    activeView === 'technoeconomic'
                        ? 'technoeconomic workspace'
                        : activeMode === 'annual' ? 'annual simulation' : 'calibration run'
                ) + '... Select Cancel to stop waiting.'
                : isChatMobile()
                    ? 'Tap Send · Enter adds a new line'
                    : 'Enter to send · Shift+Enter for a new line';
        }

        function releaseChatHydration() {
            if (!chatHydrationPending) return;
            chatHydrationPending = false;
            syncChatComposerState();
            renderChatHistory();
        }

        function queueChatDraftSave() {
            chatDraft = chatInput.value;
            if (chatHydrationPending) return;
            if (chatDraftSaveTimer) clearTimeout(chatDraftSaveTimer);
            chatDraftSaveTimer = window.setTimeout(() => {
                chatDraftSaveTimer = null;
                saveDashboardState();
            }, 150);
        }

        function setAgentActivityOpen(open, persist = true) {
            if (open && chatHistoryOpen) setChatHistoryOpen(false, false);
            const hasActivity = !agentActivity.classList.contains('hidden');
            agentActivityExpanded = !!open && hasActivity;
            agentActivity.classList.toggle('collapsed', !agentActivityExpanded);
            chatSidebar.classList.toggle('activity-view', agentActivityExpanded);
            agentActivityToggle.setAttribute('aria-expanded', String(agentActivityExpanded));
            agentActivityToggle.setAttribute('aria-label', agentActivityExpanded ? 'Close scenario runs' : 'Open scenario runs');
            agentActivityToggle.title = agentActivityExpanded ? 'Return to chat-only view' : 'Open scenario runs';
            window.requestAnimationFrame(syncChatWindowPosition);
            if (persist) saveDashboardState();
        }

        function syncChatModalState(open) {
            const modal = !!open && isChatMobile();
            if (modal) chatSidebar.setAttribute('aria-modal', 'true');
            else chatSidebar.removeAttribute('aria-modal');
            document.body.classList.toggle('chat-open', modal);
            if (dashboardShell) {
                dashboardShell.toggleAttribute('inert', modal);
                dashboardShell.inert = modal;
                if (modal) dashboardShell.setAttribute('aria-hidden', 'true');
                else dashboardShell.removeAttribute('aria-hidden');
                if (!modal && window.savedResultsDrawerReady === true && document.body.classList.contains('saved-results-open')) {
                    dashboardShell.toggleAttribute('inert', true);
                    dashboardShell.inert = true;
                    dashboardShell.setAttribute('aria-hidden', 'true');
                }
            }
        }

        function startNewChat() {
            if (chatIsSending || chatHydrationPending) return;
            const currentConversation = syncActiveChatConversation();
            const shouldArchiveCurrent = chatConversationHasContent(currentConversation);
            chatMessages = [{
                role: 'assistant',
                content: DEFAULT_ASSISTANT_MESSAGE,
                created_at: new Date().toISOString(),
            }];
            chatDraft = '';
            if (shouldArchiveCurrent) {
                const conversation = createChatConversation(chatMessages, chatDraft);
                chatConversations.unshift(conversation);
                activeChatConversationId = conversation.id;
                chatMessages = conversation.messages;
            } else {
                currentConversation.messages = chatMessages;
                currentConversation.draft = '';
                currentConversation.title = 'New conversation';
                currentConversation.updated_at = chatMessages[0].created_at;
            }
            chatInput.value = '';
            autoResizeChatInput();
            syncChatComposerState();
            setChatHistoryOpen(false, false);
            renderChatMessages();
            renderChatHistory();
            saveDashboardState();
            chatInput.focus();
        }

        function prefillChatPrompt(prompt) {
            chatInput.value = String(prompt || '');
            chatDraft = chatInput.value;
            autoResizeChatInput();
            syncChatComposerState();
            saveDashboardState();
            chatInput.focus();
            chatInput.setSelectionRange(chatInput.value.length, chatInput.value.length);
        }

        function clampChatPosition(left, top) {
            const margin = 10;
            const width = chatToggle.offsetWidth || 58;
            const height = chatToggle.offsetHeight || 58;
            return {
                left: Math.min(Math.max(margin, left), Math.max(margin, window.innerWidth - width - margin)),
                top: Math.min(Math.max(margin, top), Math.max(margin, window.innerHeight - height - margin)),
            };
        }

        function setChatTogglePosition(left, top, persist = false) {
            const position = clampChatPosition(left, top);
            chatToggle.style.left = position.left + 'px';
            chatToggle.style.top = position.top + 'px';
            chatToggle.style.right = 'auto';
            chatToggle.style.bottom = 'auto';
            if (persist) {
                try {
                    localStorage.setItem(CHAT_POSITION_KEY, JSON.stringify(position));
                } catch (_) {
                    // Position persistence is optional when browser storage is unavailable.
                }
            }
        }

        function restoreChatTogglePosition() {
            try {
                const position = JSON.parse(localStorage.getItem(CHAT_POSITION_KEY) || 'null');
                if (position && Number.isFinite(position.left) && Number.isFinite(position.top)) {
                    setChatTogglePosition(position.left, position.top);
                }
            } catch (_) {
                // Keep the default lower-right position when saved state is unavailable.
            }
        }

        function clampChatWindowPosition(left, top) {
            const margin = 10;
            const width = chatSidebar.offsetWidth;
            const height = chatSidebar.offsetHeight;
            return {
                left: Math.min(Math.max(margin, left), Math.max(margin, window.innerWidth - width - margin)),
                top: Math.min(Math.max(margin, top), Math.max(margin, window.innerHeight - height - margin)),
            };
        }

        function clearChatWindowInlinePosition() {
            chatSidebar.style.left = '';
            chatSidebar.style.top = '';
            chatSidebar.style.right = '';
            chatSidebar.style.bottom = '';
        }

        function setChatWindowPosition(left, top, persist = false) {
            if (window.innerWidth <= CHAT_MOBILE_BREAKPOINT || chatSidebar.classList.contains('hidden')) return;
            const position = clampChatWindowPosition(left, top);
            chatSidebar.style.left = position.left + 'px';
            chatSidebar.style.top = position.top + 'px';
            chatSidebar.style.right = 'auto';
            chatSidebar.style.bottom = 'auto';
            if (persist) {
                savedChatWindowPosition = position;
                try {
                    localStorage.setItem(CHAT_WINDOW_POSITION_KEY, JSON.stringify(position));
                } catch (_) {
                    // Window position persistence is optional when browser storage is unavailable.
                }
            }
        }

        function restoreChatWindowPosition() {
            try {
                const position = JSON.parse(localStorage.getItem(CHAT_WINDOW_POSITION_KEY) || 'null');
                if (position && Number.isFinite(position.left) && Number.isFinite(position.top)) {
                    savedChatWindowPosition = position;
                }
            } catch (_) {
                // Keep the default lower-right position when saved state is unavailable.
            }
        }

        function syncChatWindowPosition() {
            if (window.innerWidth <= CHAT_MOBILE_BREAKPOINT) {
                clearChatWindowInlinePosition();
                return;
            }
            if (chatSidebar.classList.contains('hidden')) return;
            if (savedChatWindowPosition) {
                setChatWindowPosition(savedChatWindowPosition.left, savedChatWindowPosition.top);
            } else if (chatSidebar.style.left) {
                const rect = chatSidebar.getBoundingClientRect();
                setChatWindowPosition(rect.left, rect.top);
            }
        }

        function finishChatDrag(event, persist) {
            if (!chatDragState || event.pointerId !== chatDragState.pointerId) return;
            const moved = chatDragState.moved;
            if (moved && persist) {
                const rect = chatToggle.getBoundingClientRect();
                setChatTogglePosition(rect.left, rect.top, true);
                suppressChatClick = true;
            }
            if (chatToggle.hasPointerCapture?.(event.pointerId)) {
                chatToggle.releasePointerCapture(event.pointerId);
            }
            chatToggle.classList.remove('dragging');
            chatDragState = null;
        }

        chatToggle.addEventListener('pointerdown', (event) => {
            if (event.button !== undefined && event.button !== 0) return;
            const rect = chatToggle.getBoundingClientRect();
            chatDragState = {
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                left: rect.left,
                top: rect.top,
                moved: false,
            };
            chatToggle.setPointerCapture?.(event.pointerId);
            chatToggle.classList.add('dragging');
        });

        chatToggle.addEventListener('pointermove', (event) => {
            if (!chatDragState || event.pointerId !== chatDragState.pointerId) return;
            const dx = event.clientX - chatDragState.startX;
            const dy = event.clientY - chatDragState.startY;
            if (Math.hypot(dx, dy) > 4) chatDragState.moved = true;
            if (chatDragState.moved) {
                event.preventDefault();
                setChatTogglePosition(chatDragState.left + dx, chatDragState.top + dy);
            }
        });

        chatToggle.addEventListener('pointerup', (event) => finishChatDrag(event, true));
        chatToggle.addEventListener('pointercancel', (event) => finishChatDrag(event, false));
        chatToggle.addEventListener('click', () => {
            if (suppressChatClick) {
                suppressChatClick = false;
                return;
            }
            setChatOpen(chatSidebar.classList.contains('hidden'));
        });

        function finishChatWindowDrag(event, persist) {
            if (!chatWindowDragState || event.pointerId !== chatWindowDragState.pointerId) return;
            if (chatWindowDragState.moved && persist) {
                const rect = chatSidebar.getBoundingClientRect();
                setChatWindowPosition(rect.left, rect.top, true);
            }
            if (chatDragHandle.hasPointerCapture?.(event.pointerId)) {
                chatDragHandle.releasePointerCapture(event.pointerId);
            }
            chatSidebar.classList.remove('dragging');
            chatWindowDragState = null;
        }

        chatDragHandle.addEventListener('pointerdown', (event) => {
            if (window.innerWidth <= CHAT_MOBILE_BREAKPOINT) return;
            if (event.button !== undefined && event.button !== 0) return;
            if (event.target.closest('button')) return;
            const rect = chatSidebar.getBoundingClientRect();
            chatWindowDragState = {
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                left: rect.left,
                top: rect.top,
                moved: false,
            };
            chatDragHandle.setPointerCapture?.(event.pointerId);
            chatSidebar.classList.add('dragging');
        });

        chatDragHandle.addEventListener('pointermove', (event) => {
            if (!chatWindowDragState || event.pointerId !== chatWindowDragState.pointerId) return;
            const dx = event.clientX - chatWindowDragState.startX;
            const dy = event.clientY - chatWindowDragState.startY;
            if (Math.hypot(dx, dy) > 4) chatWindowDragState.moved = true;
            if (chatWindowDragState.moved) {
                event.preventDefault();
                setChatWindowPosition(chatWindowDragState.left + dx, chatWindowDragState.top + dy);
            }
        });

        chatDragHandle.addEventListener('pointerup', (event) => finishChatWindowDrag(event, true));
        chatDragHandle.addEventListener('pointercancel', (event) => finishChatWindowDrag(event, false));
        minimizeChat.addEventListener('click', () => setChatOpen(false));
        closeChat.addEventListener('click', () => setChatOpen(false));
        window.addEventListener('resize', () => {
            if (chatToggle.style.left) {
                const rect = chatToggle.getBoundingClientRect();
                setChatTogglePosition(rect.left, rect.top);
            }
            syncChatWindowPosition();
            syncChatModalState(!chatSidebar.classList.contains('hidden'));
            autoResizeChatInput();
        });
        restoreChatTogglePosition();
        restoreChatWindowPosition();

        sendBtn.addEventListener('click', () => {
            if (chatIsSending) cancelChatRequest();
            else sendMessage();
        });
        newChatBtn.addEventListener('click', startNewChat);
        chatHistoryBtn.addEventListener('click', () => {
            const opening = !chatHistoryOpen;
            setChatHistoryOpen(opening);
            window.setTimeout(() => {
                if (opening) (chatHistoryList.querySelector('.chat-history-card') || chatHistoryBack).focus();
                else chatInput.focus();
            }, 0);
        });
        chatHistoryBack.addEventListener('click', () => {
            setChatHistoryOpen(false);
            chatInput.focus();
        });
        chatHistoryList.addEventListener('click', (event) => {
            const conversation = event.target.closest('[data-chat-conversation-id]');
            if (!conversation) return;
            openChatConversation(conversation.dataset.chatConversationId);
        });
        agentRefreshBtn.addEventListener('click', () => refreshAgentState(true));
        agentActivityToggle.addEventListener('click', () => {
            const opening = !agentActivityExpanded;
            setAgentActivityOpen(opening);
            window.setTimeout(() => {
                if (opening) agentActivityList.querySelector('.agent-run-summary')?.focus();
                else chatInput.focus();
            }, 0);
        });
        agentActivityBack.addEventListener('click', () => {
            setAgentActivityOpen(false);
            chatInput.focus();
        });
        agentActivity.addEventListener('click', (event) => {
            const filterButton = event.target.closest('[data-agent-activity-filter]');
            if (!filterButton) return;
            setAgentActivityFilter(filterButton.dataset.agentActivityFilter);
        });
        chatSidebar.addEventListener('click', (event) => {
            const promptButton = event.target.closest('[data-chat-prompt]');
            if (!promptButton) return;
            prefillChatPrompt(promptButton.dataset.chatPrompt || promptButton.textContent);
        });
        chatInput.addEventListener('input', () => {
            autoResizeChatInput();
            syncChatComposerState();
            queueChatDraftSave();
        });
        chatInput.addEventListener('keydown', (e) => {
            if (e.isComposing) return;
            if (e.key === 'Enter' && !e.shiftKey && !isChatMobile()) {
                e.preventDefault();
                sendMessage();
            }
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && !chatSidebar.classList.contains('hidden')) {
                event.preventDefault();
                if (chatHistoryOpen) {
                    setChatHistoryOpen(false);
                    chatHistoryBtn.focus();
                    return;
                }
                if (agentActivityExpanded) {
                    if (agentActivitySelection) {
                        const selectedKey = agentActivitySelection;
                        agentActivitySelection = null;
                        renderAgentActivity();
                        saveDashboardState();
                        window.setTimeout(() => {
                            Array.from(agentActivityList.querySelectorAll('[data-agent-run-row]'))
                                .find((element) => element.dataset.agentRunRow === selectedKey)
                                ?.focus();
                        }, 0);
                        return;
                    }
                    setAgentActivityOpen(false);
                    agentActivityToggle.focus();
                    return;
                }
                setChatOpen(false);
                return;
            }
            if (event.key === 'Tab' && isChatMobile() && !chatSidebar.classList.contains('hidden')) {
                const focusable = Array.from(chatSidebar.querySelectorAll(
                    'button:not([disabled]):not(.hidden), a[href], textarea:not([disabled]), input:not([disabled]), select:not([disabled]), details > summary'
                )).filter((element) => element.getClientRects().length > 0);
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
        });
