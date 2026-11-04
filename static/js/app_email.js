        // =========================================================================
        // --- DEDICATED SINGLE-ACCOUNT EMAIL HUB (GMAIL, MICROSOFT, IMAP/SMTP) ---
        // =========================================================================
        let emailAccountsList = [];
        let activeEmailPlatform = 'all'; // 'all' | 'gmail' | 'microsoft' | 'imap'
        let activeEmailAccountId = '';
        let activeEmailFolder = 'inbox'; // 'inbox' | 'sent' | 'drafts' | 'trash'
        let activeEmailMessages = [];
        let selectedEmailMessageId = '';
        let emailOAuthPollTimer = null;

        function showToastNotification(msg, type = 'info') {
            showToast(msg);
        }

        // Listen for postMessage from the OAuth Popup window
        window.addEventListener('message', async (event) => {
            const d = event.data || {};
            if (d && d.type === 'GLENNBOT_EMAIL_OAUTH_DONE') {
                if (emailOAuthPollTimer) {
                    clearInterval(emailOAuthPollTimer);
                    emailOAuthPollTimer = null;
                }
                showToast(`✅ Connected ${String(d.provider || 'Email').toUpperCase()} account! Syncing inbox...`);
                await fetchEmailAccounts(true);
                if (d.provider) {
                    focusEmailPlatform(d.provider);
                }
                if (!document.getElementById('connect-accounts-modal')?.classList.contains('hidden')) {
                    closeConnectAccountsModal();
                }
                if (activeTab !== 'email') {
                    switchTab('email');
                }
            } else if (d && d.type === 'GLENNBOT_CALENDAR_OAUTH_DONE') {
                if (calendarOAuthPollTimer) {
                    clearInterval(calendarOAuthPollTimer);
                    calendarOAuthPollTimer = null;
                }
                showToast(`✅ Connected ${String(d.provider || 'Calendar').replace('_', ' ').toUpperCase()} via Composio! Syncing events...`);
                await fetchComposioCalendarAccounts(true);
                await fetchComposioCalendarEvents(true);
                if (activeTab !== 'calendar') {
                    switchTab('calendar');
                }
                switchCalendarSubTab('composio');
            }
        });

        async function fetchEmailAccounts(discover = false) {
            try {
                const url = discover ? '/api/email/discover' : '/api/email/accounts';
                const res = await fetch(url);
                const data = await res.json();
                if (data.status === 'success') {
                    emailAccountsList = data.accounts || [];
                    updateEmailBadgesAndSelectors();
                    renderEmailPlatformColumnCards();

                    // Auto-select first available account if none selected yet and warm up inbox across ALL tabs
                    if (!activeEmailAccountId && emailAccountsList.length > 0) {
                        const firstAcc = emailAccountsList[0];
                        activeEmailAccountId = firstAcc.id;
                        activeEmailPlatform = firstAcc.provider || 'gmail';
                        applyEmailPlatformIsolationUI();
                        updateEmailBadgesAndSelectors();
                        await refreshActiveEmailInbox(false, activeTab !== 'email');
                    } else if (activeEmailAccountId && !emailAccountsList.some(a => a.id === activeEmailAccountId)) {
                        activeEmailAccountId = emailAccountsList[0]?.id || '';
                        activeEmailPlatform = emailAccountsList[0]?.provider || 'all';
                        applyEmailPlatformIsolationUI();
                        updateEmailBadgesAndSelectors();
                        if (activeEmailAccountId) {
                            await refreshActiveEmailInbox(false, activeTab !== 'email');
                        }
                    }
                }
            } catch (e) {
                console.error('Error fetching email accounts:', e);
            }
        }

        function initEmailTabView() {
            fetchEmailAccounts(false).then(() => {
                if (activeEmailAccountId) {
                    applyEmailPlatformIsolationUI();
                    refreshActiveEmailInbox(false);
                } else {
                    renderEmailPlatformColumnCards();
                }
            });
        }

        function updateEmailBadgesAndSelectors() {
            const totalBadge = document.getElementById('email-accounts-badge');
            if (totalBadge) totalBadge.textContent = String(emailAccountsList.length);

            const gmCount = emailAccountsList.filter(a => a.provider === 'gmail').length;
            const msCount = emailAccountsList.filter(a => a.provider === 'microsoft').length;
            const imCount = emailAccountsList.filter(a => a.provider === 'imap').length;

            const gmBadge = document.getElementById('email-count-badge-gmail');
            const msBadge = document.getElementById('email-count-badge-microsoft');
            const imBadge = document.getElementById('email-count-badge-imap');
            if (gmBadge) gmBadge.textContent = String(gmCount);
            if (msBadge) msBadge.textContent = String(msCount);
            if (imBadge) imBadge.textContent = String(imCount);

            // Populate Top Active Email Account Dropdown (filtered by activeEmailPlatform if not 'all')
            const sel = document.getElementById('email-active-account-select');
            if (sel) {
                const visibleAccounts = activeEmailPlatform === 'all'
                    ? emailAccountsList
                    : emailAccountsList.filter(a => a.provider === activeEmailPlatform);

                if (visibleAccounts.length === 0) {
                    sel.innerHTML = `<option value="" class="bg-slate-900 text-slate-400">-- No Connected Email --</option>`;
                } else {
                    sel.innerHTML = visibleAccounts.map(acc => {
                        const pTag = (acc.provider || 'gmail').toUpperCase();
                        const selectedAttr = acc.id === activeEmailAccountId ? 'selected' : '';
                        return `<option value="${escapeHTML(acc.id)}" ${selectedAttr} class="bg-slate-900 text-white">[${pTag}] ${escapeHTML(acc.email_address)}</option>`;
                    }).join('');
                }
            }

            // Update active account banner text
            const activeAcc = emailAccountsList.find(a => a.id === activeEmailAccountId);
            const bannerLabel = document.getElementById('email-active-account-label');
            if (bannerLabel) {
                if (activeAcc) {
                    const pName = activeAcc.provider === 'gmail' ? 'Gmail' : (activeAcc.provider === 'microsoft' ? 'Microsoft Outlook' : 'IMAP/SMTP');
                    bannerLabel.innerHTML = `<span class="text-gb-cyan">${escapeHTML(activeAcc.email_address)}</span> <span class="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 border border-slate-700 text-slate-300 ml-1">${pName}</span>`;
                } else {
                    bannerLabel.textContent = 'No email account selected yet';
                }
            }
        }

        function applyEmailPlatformIsolationUI() {
            // CRITICAL REQUIREMENT:
            // When a specific platform (e.g. 'gmail') is chosen, automatically hide the other platform cards
            // ('microsoft', 'imap') in the left column so the user is strictly focused on that single platform/account!
            const platforms = ['gmail', 'microsoft', 'imap'];
            const isIsolated = platforms.includes(activeEmailPlatform);

            platforms.forEach(p => {
                const card = document.getElementById(`email-plat-card-${p}`);
                if (!card) return;
                if (isIsolated && p !== activeEmailPlatform) {
                    card.classList.add('hidden');
                } else {
                    card.classList.remove('hidden');
                }
            });

            const switchBtn = document.getElementById('btn-show-all-email-platforms');
            if (switchBtn) {
                switchBtn.classList.toggle('hidden', !isIsolated);
            }

            const topFilter = document.getElementById('email-top-platform-filter');
            if (topFilter && topFilter.value !== activeEmailPlatform) {
                topFilter.value = activeEmailPlatform;
            }
        }

        function showAllEmailPlatformsColumn() {
            activeEmailPlatform = 'all';
            applyEmailPlatformIsolationUI();
            updateEmailBadgesAndSelectors();
            renderEmailPlatformColumnCards();
        }

        function handleTopEmailPlatformFilter(platformValue) {
            activeEmailPlatform = platformValue || 'all';
            applyEmailPlatformIsolationUI();

            // If switching to a specific platform, automatically select its first connected email account
            if (activeEmailPlatform !== 'all') {
                const matching = emailAccountsList.filter(a => a.provider === activeEmailPlatform);
                if (matching.length > 0 && (!activeEmailAccountId || !matching.some(m => m.id === activeEmailAccountId))) {
                    activeEmailAccountId = matching[0].id;
                    updateEmailBadgesAndSelectors();
                    renderEmailPlatformColumnCards();
                    refreshActiveEmailInbox(false);
                    return;
                } else if (matching.length === 0) {
                    activeEmailAccountId = '';
                    activeEmailMessages = [];
                    renderEmailMessagesList();
                    renderEmptyEmailReader();
                }
            }
            updateEmailBadgesAndSelectors();
            renderEmailPlatformColumnCards();
        }

        function focusEmailPlatform(provider) {
            activeEmailPlatform = provider;
            applyEmailPlatformIsolationUI();
            const matching = emailAccountsList.filter(a => a.provider === provider);
            if (matching.length > 0) {
                if (!matching.some(m => m.id === activeEmailAccountId)) {
                    activeEmailAccountId = matching[0].id;
                }
                updateEmailBadgesAndSelectors();
                renderEmailPlatformColumnCards();
                refreshActiveEmailInbox(false);
            } else {
                activeEmailAccountId = '';
                activeEmailMessages = [];
                updateEmailBadgesAndSelectors();
                renderEmailPlatformColumnCards();
                renderEmailMessagesList();
                renderEmptyEmailReader();
            }
        }

        function selectSingleEmailAccount(accountId) {
            if (!accountId) return;
            const found = emailAccountsList.find(a => a.id === accountId);
            if (!found) return;
            if (activeEmailAccountId !== found.id) {
                activeEmailMessages = [];
                selectedEmailMessageId = '';
                lastRenderedEmailReaderMsgId = '';
            }
            activeEmailAccountId = found.id;
            activeEmailPlatform = found.provider || 'gmail';
            // Auto-hide other platforms when an email account is selected
            applyEmailPlatformIsolationUI();
            updateEmailBadgesAndSelectors();
            renderEmailPlatformColumnCards();
            refreshActiveEmailInbox(false, false);
        }

        function renderEmailPlatformColumnCards() {
            ['gmail', 'microsoft', 'imap'].forEach(provider => {
                const container = document.getElementById(`email-plat-accounts-${provider}`);
                if (!container) return;
                const list = emailAccountsList.filter(a => a.provider === provider);
                if (list.length === 0) {
                    container.innerHTML = `
                        <div class="text-[11px] text-slate-500 py-1.5 italic">
                            No ${provider === 'imap' ? 'IMAP/SMTP' : provider.charAt(0).toUpperCase() + provider.slice(1)} email connected yet.
                        </div>
                    `;
                    return;
                }

                container.innerHTML = list.map(acc => {
                    const isSelected = acc.id === activeEmailAccountId;
                    const activeClasses = isSelected
                        ? 'bg-gb-cyan/15 border-gb-cyan text-white shadow-[0_0_12px_rgba(0,240,255,0.2)]'
                        : 'bg-slate-950/70 border-slate-800 text-slate-300 hover:border-slate-600 hover:text-white';
                    return `
                        <div class="p-2 rounded-xl border ${activeClasses} flex items-center justify-between gap-2 transition-all">
                            <button type="button" onclick="selectSingleEmailAccount('${escapeHTML(acc.id)}')" class="flex-1 min-w-0 flex items-center gap-2 text-left">
                                <span class="w-2 h-2 rounded-full ${isSelected ? 'bg-gb-cyan shadow-[0_0_8px_#00f0ff]' : 'bg-emerald-400'} shrink-0"></span>
                                <div class="min-w-0 flex-1">
                                    <div class="text-xs font-bold truncate">${escapeHTML(acc.email_address)}</div>
                                    <div class="text-[10px] text-slate-400 truncate">${isSelected ? 'Active Single Inbox' : 'Click to open solely'}</div>
                                </div>
                            </button>
                            <button type="button" onclick="disconnectEmailAccount('${escapeHTML(acc.id)}', '${escapeHTML(acc.email_address)}')" class="w-6 h-6 rounded-lg bg-slate-900 hover:bg-rose-900/70 text-slate-400 hover:text-rose-200 flex items-center justify-center shrink-0 transition-all" title="Disconnect this email account">
                                <i class="fas fa-trash-alt text-[10px]"></i>
                            </button>
                        </div>
                    `;
                }).join('');
            });
        }

        let emailReaderViewMode = 'rich'; // 'rich' or 'plain'
        let composeEmailAttachments = [];
        let replyEmailAttachments = [];
        let lastRenderedEmailReaderMsgId = '';
        let activeEmailNextPageToken = '';
        let activeEmailTotalEstimate = 0;
        let isLoadingMoreEmails = false;
        let normalReplyMode = 'reply'; // 'reply' | 'reply_all' | 'forward'
        let expandedReplyMode = 'reply'; // 'reply' | 'reply_all' | 'forward'

        function extractEmailAddressesList(rawStr) {
            if (!rawStr) return [];
            const str = String(rawStr);
            const matches = str.match(/[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/g) || [];
            const seen = new Set();
            const out = [];
            for (const m of matches) {
                const clean = m.trim();
                const low = clean.toLowerCase();
                if (clean && !seen.has(low)) {
                    seen.add(low);
                    out.push(clean);
                }
            }
            if (out.length === 0 && str.trim()) {
                str.split(/[,;]+/).forEach(part => {
                    const p = part.trim();
                    if (p && !seen.has(p.toLowerCase())) {
                        seen.add(p.toLowerCase());
                        out.push(p);
                    }
                });
            }
            return out;
        }

        function computeReplyActionFields(msg, mode = 'reply') {
            if (!msg) return { to: '', cc: '', bodyPrefix: '' };
            const activeAcc = emailAccountsList.find(a => a.id === activeEmailAccountId);
            const selfEmail = (activeAcc?.email_address || '').trim().toLowerCase();

            const senderEmails = extractEmailAddressesList(msg.sender_email || msg.sender || '');
            const primarySender = senderEmails[0] || (msg.sender_email || msg.sender || '').trim();

            if (mode === 'forward') {
                const cleanBody = cleanEmailTextClientSide(msg.body || msg.snippet || '');
                const fwdBlock = `\n\n---------- Forwarded message ---------\nFrom: ${msg.sender || msg.sender_name || ''}\nDate: ${msg.date || ''}\nSubject: ${msg.subject || '(No Subject)'}\nTo: ${msg.to || ''}${msg.cc ? `\nCc: ${msg.cc}` : ''}\n\n${cleanBody}`;
                return {
                    to: '',
                    cc: '',
                    bodyPrefix: fwdBlock
                };
            }

            if (mode === 'reply_all') {
                const toSet = new Set();
                const toArr = [];
                const addUniqueTo = (em) => {
                    const c = String(em || '').trim();
                    const low = c.toLowerCase();
                    if (c && !toSet.has(low)) {
                        toSet.add(low);
                        toArr.push(c);
                    }
                };
                if (primarySender) addUniqueTo(primarySender);
                extractEmailAddressesList(msg.to || '').forEach(em => {
                    if (em.toLowerCase() !== selfEmail) addUniqueTo(em);
                });

                const ccArr = [];
                extractEmailAddressesList(msg.cc || '').forEach(em => {
                    const low = em.toLowerCase();
                    if (low !== selfEmail && !toSet.has(low)) {
                        toSet.add(low);
                        ccArr.push(em);
                    }
                });
                return {
                    to: toArr.join(', '),
                    cc: ccArr.join(', '),
                    bodyPrefix: ''
                };
            }

            // Default 'reply'
            return {
                to: primarySender,
                cc: '',
                bodyPrefix: ''
            };
        }

        function toggleEmailReplyCcRow(targetPane = 'normal', forceShow = null) {
            const rowId = targetPane === 'expanded' ? 'expanded-email-reply-cc-row' : 'email-quick-reply-cc-row';
            const inputId = targetPane === 'expanded' ? 'expanded-email-reply-cc' : 'email-quick-reply-cc';
            const rowEl = document.getElementById(rowId);
            if (!rowEl) return;
            const shouldShow = forceShow !== null ? forceShow : rowEl.classList.contains('hidden');
            rowEl.classList.toggle('hidden', !shouldShow);
            if (shouldShow && forceShow === null) {
                document.getElementById(inputId)?.focus();
            }
        }

        function setEmailReplyActionMode(mode = 'reply', targetPane = 'normal') {
            const msg = activeEmailMessages.find(m => m.id === selectedEmailMessageId);
            if (!msg) return;

            if (targetPane === 'expanded') {
                expandedReplyMode = mode;
            } else {
                normalReplyMode = mode;
            }

            const isExp = (targetPane === 'expanded');
            const toInput = document.getElementById(isExp ? 'expanded-email-reply-to' : 'email-quick-reply-to');
            const ccInput = document.getElementById(isExp ? 'expanded-email-reply-cc' : 'email-quick-reply-cc');
            const bodyInput = document.getElementById(isExp ? 'expanded-email-reply-input' : 'email-quick-reply-input');
            const sendBtn = document.getElementById(isExp ? 'btn-send-expanded-email-reply' : 'btn-send-email-reply');
            const modeBadge = document.getElementById(isExp ? 'expanded-email-reply-mode-label' : 'email-quick-reply-mode-label');

            const computed = computeReplyActionFields(msg, mode);
            if (toInput) {
                toInput.value = computed.to;
                if (mode === 'forward') {
                    toInput.placeholder = 'Enter recipient email(s) to forward to (comma-separated)...';
                    toInput.focus();
                } else {
                    toInput.placeholder = 'recipient@example.com, another@example.com';
                }
            }
            if (ccInput) {
                ccInput.value = computed.cc;
            }
            if (mode === 'reply_all' || computed.cc) {
                toggleEmailReplyCcRow(targetPane, true);
            }

            if (bodyInput) {
                if (mode === 'forward') {
                    if (!bodyInput.value.includes('---------- Forwarded message ---------')) {
                        bodyInput.value = (bodyInput.value ? bodyInput.value + '\n' : '') + computed.bodyPrefix.trimStart();
                    }
                    bodyInput.placeholder = 'Add a message above the forwarded email...';
                } else {
                    if (bodyInput.value.includes('---------- Forwarded message ---------')) {
                        bodyInput.value = bodyInput.value.split('---------- Forwarded message ---------')[0].trim();
                    }
                    bodyInput.placeholder = mode === 'reply_all' ? 'Write your Reply All message here...' : 'Write your reply here...';
                }
            }

            // Update mode button styles
            ['reply', 'reply_all', 'forward'].forEach(m => {
                const btnEl = document.getElementById(`${isExp ? 'exp' : 'norm'}-mode-btn-${m}`);
                if (!btnEl) return;
                if (m === mode) {
                    btnEl.className = 'px-2.5 py-1 rounded-lg bg-gb-cyan text-slate-950 font-bold text-[11px] flex items-center gap-1 shadow-[0_0_10px_rgba(0,240,255,0.3)] transition-all';
                } else {
                    btnEl.className = 'px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white font-semibold text-[11px] flex items-center gap-1 border border-slate-700 transition-all';
                }
            });

            if (modeBadge) {
                if (mode === 'forward') {
                    modeBadge.innerHTML = `<i class="fas fa-share text-amber-400 mr-1"></i>Forwarding email`;
                } else if (mode === 'reply_all') {
                    modeBadge.innerHTML = `<i class="fas fa-reply-all text-gb-cyan mr-1"></i>Replying All`;
                } else {
                    modeBadge.innerHTML = `<i class="fas fa-reply text-gb-cyan mr-1"></i>Replying`;
                }
            }

            if (sendBtn) {
                const btnLabel = mode === 'forward' ? 'Forward Email' : (mode === 'reply_all' ? 'Send Reply All' : (isExp ? 'Send Reply' : 'Reply'));
                const btnIcon = mode === 'forward' ? 'fa-share' : (mode === 'reply_all' ? 'fa-reply-all' : 'fa-paper-plane');
                sendBtn.innerHTML = `<i class="fas ${btnIcon}"></i> <span>${btnLabel}</span>`;
            }
        }

        function looksLikeEmailHtml(rawStr) {
            if (!rawStr || typeof rawStr !== 'string') return false;
            const sample = rawStr.slice(0, 2500).toLowerCase();
            return (
                sample.includes('<!doctype html') ||
                sample.includes('<html') ||
                sample.includes('<head') ||
                sample.includes('<body') ||
                sample.includes('<table') ||
                sample.includes('<div') ||
                sample.includes('<style') ||
                sample.includes('<p>') ||
                sample.includes('<p ') ||
                sample.includes('<br') ||
                sample.includes('<a href=') ||
                sample.includes('<img ')
            );
        }

        function cleanEmailTextClientSide(rawStr) {
            if (!rawStr) return '';
            let txt = String(rawStr);
            txt = txt.replace(/<head[\s\S]*?<\/head>/gi, ' ')
                     .replace(/<style[\s\S]*?<\/style>/gi, ' ')
                     .replace(/<script[\s\S]*?<\/script>/gi, ' ')
                     .replace(/<!--[\s\S]*?-->/g, ' ')
                     .replace(/<!doctype[^>]*>/gi, ' ')
                     .replace(/<br\s*\/?>/gi, '\n')
                     .replace(/<\/(p|div|tr|li|h[1-6]|blockquote|section|article|header|footer)>/gi, '\n')
                     .replace(/<[^>]+>/g, ' ');
            try {
                const dec = document.createElement('textarea');
                dec.innerHTML = txt;
                txt = dec.value;
            } catch (e) {}
            txt = txt.replace(/[\u034f\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad\u2060]+/g, '')
                     .replace(/%%[a-zA-Z0-9_]+%%/g, '')
                     .replace(/https?:\/\/___MirrorURLMultiMid___\S*/g, '')
                     .replace(/\[https?:\/\/[^\]]{45,}\]/g, '');
            return txt
                .split(/\r?\n/)
                .map(l => l.replace(/[ \t\f\v\u00a0]+/g, ' ').trim())
                .join('\n')
                .replace(/\n{3,}/g, '\n\n')
                .trim();
        }

        function formatAttachmentSize(bytes) {
            const n = Number(bytes || 0);
            if (n < 1024) return `${n} B`;
            if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
            return `${(n / (1024 * 1024)).toFixed(2)} MB`;
        }

        function readFilesAsAttachmentObjects(fileList) {
            const files = Array.from(fileList || []);
            return Promise.all(files.map(file => new Promise((resolve) => {
                const reader = new FileReader();
                reader.onload = () => {
                    const resStr = String(reader.result || '');
                    const b64 = resStr.includes(',') ? resStr.split(',')[1] : resStr;
                    resolve({
                        filename: file.name || 'attachment',
                        content_type: file.type || 'application/octet-stream',
                        content_base64: b64,
                        size: file.size || 0
                    });
                };
                reader.onerror = () => resolve(null);
                reader.readAsDataURL(file);
            }))).then(items => items.filter(Boolean));
        }

        async function handleComposeEmailFileSelect(event) {
            const input = event?.target;
            if (!input || !input.files || input.files.length === 0) return;
            const added = await readFilesAsAttachmentObjects(input.files);
            composeEmailAttachments = [...composeEmailAttachments, ...added];
            input.value = '';
            renderComposeEmailAttachmentsUI();
        }

        function removeComposeEmailAttachment(index) {
            composeEmailAttachments.splice(index, 1);
            renderComposeEmailAttachmentsUI();
        }

        function clearComposeEmailAttachments() {
            composeEmailAttachments = [];
            const fileInput = document.getElementById('compose-email-file-input');
            if (fileInput) fileInput.value = '';
            renderComposeEmailAttachmentsUI();
        }

        function renderComposeEmailAttachmentsUI() {
            const listEl = document.getElementById('compose-email-attachments-list');
            const countEl = document.getElementById('compose-email-attachments-count');
            const clearBtn = document.getElementById('btn-clear-compose-attachments');
            if (countEl) {
                if (composeEmailAttachments.length === 0) {
                    countEl.textContent = 'No files attached';
                } else {
                    const totalBytes = composeEmailAttachments.reduce((acc, f) => acc + (f.size || 0), 0);
                    countEl.textContent = `${composeEmailAttachments.length} file${composeEmailAttachments.length === 1 ? '' : 's'} (${formatAttachmentSize(totalBytes)})`;
                }
            }
            if (clearBtn) {
                clearBtn.classList.toggle('hidden', composeEmailAttachments.length === 0);
            }
            if (!listEl) return;
            if (composeEmailAttachments.length === 0) {
                listEl.innerHTML = '';
                return;
            }
            listEl.innerHTML = composeEmailAttachments.map((att, idx) => `
                <div class="px-2.5 py-1 rounded-lg bg-slate-900 border border-gb-cyan/40 text-xs text-slate-200 flex items-center gap-2 max-w-full">
                    <i class="fas fa-file-alt text-gb-cyan text-[11px] shrink-0"></i>
                    <span class="truncate max-w-[180px] font-medium">${escapeHTML(att.filename)}</span>
                    <span class="text-[10px] text-slate-400 shrink-0">(${formatAttachmentSize(att.size)})</span>
                    <button type="button" onclick="removeComposeEmailAttachment(${idx})" class="text-slate-400 hover:text-rose-400 ml-0.5 shrink-0" title="Remove file">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            `).join('');
        }

        async function handleReplyEmailFileSelect(event) {
            const input = event?.target;
            if (!input || !input.files || input.files.length === 0) return;
            const added = await readFilesAsAttachmentObjects(input.files);
            replyEmailAttachments = [...replyEmailAttachments, ...added];
            input.value = '';
            renderReplyEmailAttachmentsUI();
        }

        function removeReplyEmailAttachment(index) {
            replyEmailAttachments.splice(index, 1);
            renderReplyEmailAttachmentsUI();
        }

        function renderReplyEmailAttachmentsUI() {
            const listEl = document.getElementById('reply-email-attachments-list');
            if (!listEl) return;
            if (replyEmailAttachments.length === 0) {
                listEl.innerHTML = '';
                return;
            }
            listEl.innerHTML = replyEmailAttachments.map((att, idx) => `
                <div class="px-2 py-1 rounded-lg bg-slate-950 border border-gb-cyan/40 text-[11px] text-slate-200 flex items-center gap-1.5">
                    <i class="fas fa-paperclip text-gb-cyan text-[10px]"></i>
                    <span class="truncate max-w-[160px]">${escapeHTML(att.filename)}</span>
                    <span class="text-[10px] text-slate-400">(${formatAttachmentSize(att.size)})</span>
                    <button type="button" onclick="removeReplyEmailAttachment(${idx})" class="text-slate-400 hover:text-rose-400 ml-0.5">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            `).join('');
        }

        function switchEmailFolder(folderName) {
            activeEmailFolder = folderName;
            selectedEmailMessageId = '';
            lastRenderedEmailReaderMsgId = '';
            activeEmailMessages = [];
            activeEmailNextPageToken = '';
            activeEmailTotalEstimate = 0;
            ['inbox', 'sent', 'drafts', 'spam', 'trash'].forEach(f => {
                const btn = document.getElementById(`email-folder-btn-${f}`);
                if (!btn) return;
                if (f === folderName) {
                    btn.className = "px-3 py-1.5 rounded-lg text-xs font-bold bg-gb-cyan/20 text-gb-cyan border border-gb-cyan/50 flex items-center gap-1.5 transition-all";
                } else {
                    btn.className = "px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800/80 text-slate-300 hover:text-white border border-slate-700 flex items-center gap-1.5 transition-all";
                }
            });
            refreshActiveEmailInbox(false, false);
        }

        function getEmailTimestampMs(msg) {
            if (!msg) return 0;
            if (typeof msg.timestamp === 'number' && msg.timestamp > 0) {
                return msg.timestamp > 1e11 ? msg.timestamp : msg.timestamp * 1000;
            }
            const raw = String(msg.raw_date || msg.date || '').trim();
            if (!raw) return 0;
            const parsed = Date.parse(raw);
            if (!Number.isNaN(parsed)) return parsed;
            return 0;
        }

        function sortEmailMessagesNewestFirst(list) {
            if (!Array.isArray(list)) return [];
            return [...list].sort((a, b) => getEmailTimestampMs(b) - getEmailTimestampMs(a));
        }

        let isSilentEmailSyncInFlight = false;

        async function refreshActiveEmailInbox(force = false, silent = false) {
            if (silent && isSilentEmailSyncInFlight) return;
            if (silent) isSilentEmailSyncInFlight = true;

            const listPane = document.getElementById('email-messages-list-pane');
            const countEl = document.getElementById('email-active-folder-count');
            const syncIcon = document.getElementById('email-sync-icon');

            if (!activeEmailAccountId) {
                if (silent) isSilentEmailSyncInFlight = false;
                activeEmailNextPageToken = '';
                activeEmailTotalEstimate = 0;
                if (listPane) {
                    listPane.innerHTML = `
                        <div class="p-8 text-center space-y-3">
                            <div class="w-12 h-12 rounded-2xl bg-gb-cyan/10 border border-gb-cyan/30 flex items-center justify-center text-gb-cyan mx-auto">
                                <i class="fas fa-at text-xl"></i>
                            </div>
                            <div class="text-xs font-bold text-white">No Active Email Selected</div>
                            <p class="text-[11px] text-slate-400 max-w-xs mx-auto">
                                Connect your Gmail, Microsoft, or IMAP/SMTP email on the left column to view its dedicated inbox here.
                            </p>
                            <div class="flex flex-wrap justify-center gap-2 pt-1">
                                <button type="button" onclick="startEmailOAuthPopup('gmail')" class="px-3 py-1.5 rounded-xl bg-red-500/20 hover:bg-red-500/30 border border-red-400/50 text-red-200 text-xs font-bold flex items-center gap-1.5">
                                    <i class="fab fa-google"></i> Connect Gmail Popup
                                </button>
                                <button type="button" onclick="startEmailOAuthPopup('microsoft')" class="px-3 py-1.5 rounded-xl bg-sky-500/20 hover:bg-sky-500/30 border border-sky-400/50 text-sky-200 text-xs font-bold flex items-center gap-1.5">
                                    <i class="fab fa-microsoft"></i> Connect Microsoft
                                </button>
                            </div>
                        </div>
                    `;
                }
                if (countEl) countEl.textContent = '0 emails';
                renderEmptyEmailReader();
                return;
            }

            const hasExistingList = Array.isArray(activeEmailMessages) && activeEmailMessages.length > 0;
            if (syncIcon && !silent) syncIcon.classList.add('fa-spin');

            // Only show full loading spinner if list is currently empty (never wipe out list while user is browsing!)
            if (listPane && !hasExistingList && !silent) {
                listPane.innerHTML = `
                    <div class="p-8 text-center text-slate-400 text-xs">
                        <i class="fas fa-circle-notch fa-spin text-2xl text-gb-cyan mb-2"></i>
                        <p>Loading ${activeEmailFolder.toUpperCase()} for selected email account...</p>
                    </div>
                `;
            }

            const qVal = (document.getElementById('email-search-input')?.value || '').trim();
            try {
                const url = `/api/email/messages?account_id=${encodeURIComponent(activeEmailAccountId)}&folder=${encodeURIComponent(activeEmailFolder)}&q=${encodeURIComponent(qVal)}&force=${force ? 'true' : 'false'}`;
                const res = await fetch(url);
                const data = await res.json();
                if (data.status === 'success') {
                    const incomingMessages = sortEmailMessagesNewestFirst(data.messages || []);

                    // If Gmail API returned a temporary 429 rate-limit cooldown and incomingMessages is empty,
                    // NEVER wipe out existing emails already displayed on screen!
                    if (data.rate_limited && incomingMessages.length === 0) {
                        if (hasExistingList && activeEmailMessages.length > 0) {
                            return;
                        }
                        if (listPane) {
                            const resumeStr = data.retry_after_manila
                                ? `Resumes automatically around ${escapeHTML(data.retry_after_manila)} (Manila Time)`
                                : 'Resumes automatically in a few minutes';
                            listPane.innerHTML = `
                                <div class="p-6 text-center text-amber-300 text-xs space-y-2">
                                    <i class="fas fa-hourglass-half text-2xl text-amber-400"></i>
                                    <p class="font-bold text-amber-200">Gmail API Temporary Quota Cooldown</p>
                                    <p class="text-[11px] text-slate-300 leading-relaxed">Google temporarily paused requests for this inbox due to frequent syncs. ${resumeStr}.</p>
                                    <p class="text-[10px] text-slate-400">Auto-protection is now active so the cooldown finishes cleanly without resetting.</p>
                                </div>
                            `;
                        }
                        return;
                    }

                    const oldTopSlice = (activeEmailMessages || []).slice(0, incomingMessages.length);
                    const oldSig = oldTopSlice.map(m => `${m.id}:${m.is_unread ? 1 : 0}`).join('|');
                    const newSig = incomingMessages.map(m => `${m.id}:${m.is_unread ? 1 : 0}`).join('|');

                    if (silent && hasExistingList && activeEmailMessages.length > incomingMessages.length) {
                        // Preserve already-paginated ("Load More") emails during silent background checks!
                        const incomingIds = new Set(incomingMessages.map(m => m.id));
                        const olderLoaded = activeEmailMessages.filter(m => !incomingIds.has(m.id));
                        activeEmailMessages = sortEmailMessagesNewestFirst([...incomingMessages, ...olderLoaded]);
                    } else {
                        activeEmailMessages = incomingMessages;
                        activeEmailNextPageToken = data.next_page_token || '';
                        activeEmailTotalEstimate = Number(data.result_size_estimate || activeEmailMessages.length);
                    }

                    const unreadCount = activeEmailMessages.filter(m => m.is_unread).length;
                    const unreadBadge = document.getElementById('email-unread-badge');
                    if (unreadBadge) {
                        unreadBadge.textContent = String(unreadCount);
                        unreadBadge.classList.toggle('hidden', unreadCount === 0);
                    }
                    const navUnreadBadge = document.getElementById('nav-email-unread-badge');
                    if (navUnreadBadge && activeEmailFolder === 'inbox') {
                        navUnreadBadge.textContent = String(unreadCount);
                        navUnreadBadge.classList.toggle('hidden', unreadCount === 0);
                    }
                    if (countEl) {
                        const moreHint = activeEmailNextPageToken ? '+' : '';
                        countEl.textContent = `${activeEmailMessages.length}${moreHint} email${activeEmailMessages.length === 1 ? '' : 's'} in ${activeEmailFolder.toUpperCase()}`;
                    }

                    // If silent background check and nothing changed, do NOT touch the DOM or scroll position at all!
                    if (silent && hasExistingList && oldSig === newSig) {
                        return;
                    }

                    if (silent && oldSig !== newSig) {
                        pollRealtimeEmailWebhookEvents();
                    }

                    renderEmailMessagesList();

                    if (activeEmailMessages.length > 0) {
                        const stillExists = activeEmailMessages.find(m => m.id === selectedEmailMessageId);
                        if (!stillExists) {
                            selectEmailMessageToRead(activeEmailMessages[0].id);
                        } else if (lastRenderedEmailReaderMsgId !== stillExists.id) {
                            selectEmailMessageToRead(stillExists.id);
                        }
                    } else {
                        lastRenderedEmailReaderMsgId = '';
                        renderEmptyEmailReader();
                    }
                } else if (!silent && !hasExistingList) {
                    if (listPane) {
                        listPane.innerHTML = `<div class="p-6 text-center text-rose-400 text-xs">${escapeHTML(data.message || 'Could not load emails.')}</div>`;
                    }
                }
            } catch (err) {
                if (!silent && !hasExistingList && listPane) {
                    listPane.innerHTML = `<div class="p-6 text-center text-rose-400 text-xs">Network error loading emails.</div>`;
                }
            } finally {
                if (silent) isSilentEmailSyncInFlight = false;
                if (syncIcon) syncIcon.classList.remove('fa-spin');
            }
        }

        async function loadMoreActiveEmailInbox() {
            if (!activeEmailAccountId || !activeEmailNextPageToken || isLoadingMoreEmails) return;
            isLoadingMoreEmails = true;
            const loadBtn = document.getElementById('btn-load-more-emails');
            if (loadBtn) {
                loadBtn.disabled = true;
                loadBtn.innerHTML = `<i class="fas fa-circle-notch fa-spin text-gb-cyan"></i> <span>Loading More Emails...</span>`;
            }

            const qVal = (document.getElementById('email-search-input')?.value || '').trim();
            try {
                const url = `/api/email/messages?account_id=${encodeURIComponent(activeEmailAccountId)}&folder=${encodeURIComponent(activeEmailFolder)}&q=${encodeURIComponent(qVal)}&page_token=${encodeURIComponent(activeEmailNextPageToken)}`;
                const res = await fetch(url);
                const data = await res.json();
                if (data.status === 'success') {
                    const nextBatch = data.messages || [];
                    const existingIds = new Set(activeEmailMessages.map(m => m.id));
                    const uniqueAdded = nextBatch.filter(m => !existingIds.has(m.id));
                    activeEmailMessages = sortEmailMessagesNewestFirst([...activeEmailMessages, ...uniqueAdded]);
                    activeEmailNextPageToken = data.next_page_token || '';
                    if (data.result_size_estimate) {
                        activeEmailTotalEstimate = Number(data.result_size_estimate);
                    }

                    const countEl = document.getElementById('email-active-folder-count');
                    if (countEl) {
                        const moreHint = activeEmailNextPageToken ? '+' : '';
                        countEl.textContent = `${activeEmailMessages.length}${moreHint} email${activeEmailMessages.length === 1 ? '' : 's'} in ${activeEmailFolder.toUpperCase()}`;
                    }
                    renderEmailMessagesList();
                    showToastNotification(`Loaded ${uniqueAdded.length} more email(s) (${activeEmailMessages.length} total shown).`, 'success');
                } else {
                    showToastNotification(data.message || 'Could not load more emails.', 'error');
                }
            } catch (err) {
                showToastNotification('Network error while loading more emails.', 'error');
            } finally {
                isLoadingMoreEmails = false;
                const updatedBtn = document.getElementById('btn-load-more-emails');
                if (updatedBtn) {
                    updatedBtn.disabled = false;
                    updatedBtn.innerHTML = `<i class="fas fa-chevron-circle-down text-gb-cyan"></i> <span>Load More Emails (${activeEmailMessages.length} loaded)</span>`;
                }
            }
        }

        function renderEmailMessagesList() {
            const listPane = document.getElementById('email-messages-list-pane');
            if (!listPane) return;
            const prevScrollTop = listPane.scrollTop;

            if (!activeEmailMessages || activeEmailMessages.length === 0) {
                listPane.innerHTML = `
                    <div class="p-8 text-center text-slate-400 text-xs space-y-2">
                        <i class="fas fa-inbox text-2xl text-slate-600"></i>
                        <p class="font-semibold text-slate-300">No emails found in ${escapeHTML(activeEmailFolder.toUpperCase())}</p>
                        <p class="text-[11px] text-slate-500">Try switching folders or clicking Refresh.</p>
                    </div>
                `;
                return;
            }

            const rowsHTML = activeEmailMessages.map(msg => {
                const isSelected = msg.id === selectedEmailMessageId;
                const rowBg = isSelected
                    ? 'bg-gb-cyan/15 border-l-4 border-l-gb-cyan'
                    : (msg.is_unread ? 'bg-slate-900/90 hover:bg-slate-800/80' : 'bg-transparent hover:bg-slate-900/60');
                let cleanPreview = cleanEmailTextClientSide(msg.snippet || '');
                if (!cleanPreview || cleanPreview.length < 5 || looksLikeEmailHtml(cleanPreview)) {
                    cleanPreview = cleanEmailTextClientSide(msg.body || '').replace(/\s+/g, ' ').slice(0, 150);
                }
                cleanPreview = cleanPreview.replace(/^[\.\s•·\-_]+/, '').replace(/\s+/g, ' ').trim();
                const hasAtt = Array.isArray(msg.attachments) && msg.attachments.length > 0;
                const displayDate = String(msg.date || '').slice(0, 19);
                return `
                    <button type="button" onclick="selectEmailMessageToRead('${escapeHTML(msg.id)}')" ondblclick="openExpandedEmailModal('${escapeHTML(msg.id)}')" title="Click to preview • Double-click for Expanded Full View" class="group w-full text-left p-3.5 transition-all flex flex-col gap-1 ${rowBg}">
                        <div class="flex items-center justify-between gap-2">
                            <div class="flex items-center gap-2 min-w-0">
                                ${msg.is_unread ? '<span class="w-2 h-2 rounded-full bg-gb-cyan shrink-0"></span>' : ''}
                                <span class="text-xs font-bold text-white truncate">${escapeHTML(msg.sender_name || msg.sender || 'Unknown')}</span>
                            </div>
                            <div class="flex items-center gap-1.5 shrink-0">
                                ${hasAtt ? '<i class="fas fa-paperclip text-[10px] text-gb-cyan" title="Has downloadable attachment"></i>' : ''}
                                <span class="text-[10px] text-slate-400">${escapeHTML(displayDate)}</span>
                                <i class="fas fa-expand-alt text-[10px] text-gb-cyan opacity-0 group-hover:opacity-100 transition-opacity ml-0.5" title="Double-click to expand"></i>
                            </div>
                        </div>
                        <div class="text-xs font-semibold text-gb-cyan truncate">${escapeHTML(msg.subject || '(No Subject)')}</div>
                        <div class="text-[11px] text-slate-400 line-clamp-2 leading-snug">${escapeHTML(cleanPreview || '(No preview)')}</div>
                    </button>
                `;
            }).join('');

            const loadMoreFooterHTML = activeEmailNextPageToken
                ? `<div class="p-3.5 bg-slate-900/90 border-t border-slate-800 flex flex-col items-center gap-1.5">
                        <button type="button" id="btn-load-more-emails" onclick="loadMoreActiveEmailInbox()" class="w-full py-2.5 px-4 rounded-xl bg-slate-950 hover:bg-gb-cyan/15 border border-gb-cyan/50 hover:border-gb-cyan text-gb-cyan font-bold text-xs flex items-center justify-center gap-2 transition-all shadow-[0_0_12px_rgba(0,240,255,0.12)]">
                            <i class="fas fa-chevron-circle-down"></i>
                            <span>Load More Emails (${activeEmailMessages.length} loaded)</span>
                        </button>
                   </div>`
                : (activeEmailMessages.length >= 25
                    ? `<div class="p-3 text-center text-[11px] text-slate-500 bg-slate-950/60">All ${activeEmailMessages.length} emails in this folder loaded</div>`
                    : '');

            listPane.innerHTML = rowsHTML + loadMoreFooterHTML;
            listPane.scrollTop = prevScrollTop;
        }

        function renderEmptyEmailReader() {
            const reader = document.getElementById('email-reader-pane');
            if (!reader) return;
            reader.innerHTML = `
                <div class="flex-1 flex flex-col items-center justify-center p-8 text-center text-slate-500 text-xs">
                    <i class="fas fa-envelope-open text-3xl text-slate-700 mb-3"></i>
                    <p class="font-semibold text-slate-300">No Email Selected</p>
                    <p class="text-[11px] text-slate-500 mt-1 max-w-sm">Click any email on the left to read it here, or <strong>double-click</strong> any email to pop up the full Expanded View.</p>
                </div>
            `;
        }

        function buildEmailAttachmentsBarHTML(msg) {
            if (!msg || !Array.isArray(msg.attachments) || msg.attachments.length === 0) {
                return '';
            }
            return `
                <div class="px-4 py-2.5 bg-slate-900/95 border-b border-slate-800 flex flex-wrap items-center gap-2 text-xs shrink-0">
                    <span class="text-slate-300 font-bold flex items-center gap-1.5">
                        <i class="fas fa-paperclip text-gb-cyan"></i>
                        <span>Attachments (${msg.attachments.length}):</span>
                    </span>
                    ${msg.attachments.map((att, attIdx) => {
                        const sizeStr = att.size ? ` (${formatAttachmentSize(att.size)})` : '';
                        return `
                            <button type="button" onclick="downloadEmailAttachmentByIndex('${escapeHTML(msg.id)}', ${attIdx}, this)" class="px-3 py-1.5 rounded-xl bg-slate-950 hover:bg-gb-cyan/15 border border-gb-cyan/40 hover:border-gb-cyan text-slate-100 flex items-center gap-2 text-[11px] font-semibold transition-all shadow-sm" title="Click to download ${escapeHTML(att.filename || 'file')}">
                                <i class="fas fa-download text-gb-cyan"></i>
                                <span class="truncate max-w-[220px]">${escapeHTML(att.filename || 'attachment')}${escapeHTML(sizeStr)}</span>
                                <span class="px-1.5 py-0.5 rounded bg-gb-cyan/20 text-gb-cyan text-[9px] font-bold uppercase">Download</span>
                            </button>
                        `;
                    }).join('')}
                </div>
            `;
        }

        async function downloadEmailAttachmentByIndex(msgId, attIdx, btnEl) {
            const msg = activeEmailMessages.find(m => m.id === msgId);
            if (!msg || !Array.isArray(msg.attachments) || !msg.attachments[attIdx]) {
                showToastNotification('Attachment metadata not found.', 'error');
                return;
            }
            const att = msg.attachments[attIdx];
            const filename = att.filename || 'attachment.bin';
            const origHTML = btnEl ? btnEl.innerHTML : '';
            if (btnEl) {
                btnEl.disabled = true;
                btnEl.innerHTML = `<i class="fas fa-circle-notch fa-spin text-gb-cyan"></i> <span>Downloading ${escapeHTML(filename)}...</span>`;
            }
            showToastNotification(`⬇️ Downloading "${filename}"...`, 'info');
            try {
                const res = await fetch('/api/email/attachment/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_id: activeEmailAccountId,
                        message_id: msg.id,
                        attachment_id: att.attachmentId || '',
                        filename: filename,
                        mime_type: att.mimeType || 'application/octet-stream',
                        folder: activeEmailFolder
                    })
                });
                if (!res.ok) {
                    let errMsg = `Download failed (HTTP ${res.status})`;
                    try {
                        const errJson = await res.json();
                        if (errJson && errJson.message) errMsg = errJson.message;
                    } catch (e) {}
                    showToastNotification(errMsg, 'error');
                    return;
                }
                const blob = await res.blob();
                const blobUrl = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = blobUrl;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                setTimeout(() => {
                    document.body.removeChild(a);
                    URL.revokeObjectURL(blobUrl);
                }, 1500);
                showToastNotification(`✅ Downloaded "${filename}"!`, 'success');
            } catch (err) {
                showToastNotification('Network error while downloading attachment.', 'error');
            } finally {
                if (btnEl) {
                    btnEl.disabled = false;
                    btnEl.innerHTML = origHTML;
                }
            }
        }

        function parseCssRgbColor(colorStr) {
            if (!colorStr) return null;
            const s = String(colorStr).trim().toLowerCase();
            if (!s || s === 'transparent' || s === 'inherit' || s === 'initial' || s === 'unset') return null;
            const rgbaMatch = s.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*[,/]\s*([0-9.]+))?\s*\)/);
            if (rgbaMatch) {
                const a = rgbaMatch[4] !== undefined ? parseFloat(rgbaMatch[4]) : 1;
                if (a < 0.15) return null;
                return { r: parseInt(rgbaMatch[1], 10), g: parseInt(rgbaMatch[2], 10), b: parseInt(rgbaMatch[3], 10), a };
            }
            const hexMatch = s.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
            if (hexMatch) {
                let h = hexMatch[1];
                if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
                return {
                    r: parseInt(h.slice(0, 2), 16),
                    g: parseInt(h.slice(2, 4), 16),
                    b: parseInt(h.slice(4, 6), 16),
                    a: 1
                };
            }
            return null;
        }

        function computeRelativeLuminance(rgb) {
            if (!rgb) return 1;
            const toLinear = (c) => {
                const v = c / 255;
                return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
            };
            return 0.2126 * toLinear(rgb.r) + 0.7152 * toLinear(rgb.g) + 0.0722 * toLinear(rgb.b);
        }

        function applySmartEmailIframeContrastGuard(iframeEl) {
            try {
                const doc = iframeEl?.contentDocument || iframeEl?.contentWindow?.document;
                if (!doc || !doc.body) return;
                const win = iframeEl.contentWindow || window;

                const getEffectiveBgInfo = (startEl) => {
                    let cur = startEl;
                    let hasBgImage = false;
                    while (cur && cur.nodeType === 1) {
                        const cs = win.getComputedStyle(cur);
                        if (cs && cs.backgroundImage && cs.backgroundImage !== 'none') {
                            hasBgImage = true;
                        }
                        const parsed = parseCssRgbColor(cs ? cs.backgroundColor : '');
                        if (parsed) {
                            return { rgb: parsed, hasBgImage };
                        }
                        const bgAttr = cur.getAttribute && cur.getAttribute('bgcolor');
                        const parsedAttr = parseCssRgbColor(bgAttr);
                        if (parsedAttr) {
                            return { rgb: parsedAttr, hasBgImage };
                        }
                        if (cur === doc.body || cur === doc.documentElement) break;
                        cur = cur.parentElement;
                    }
                    return { rgb: { r: 255, g: 255, b: 255, a: 1 }, hasBgImage };
                };

                const allEls = doc.body.querySelectorAll('*');
                allEls.forEach((el) => {
                    const tag = (el.tagName || '').toUpperCase();
                    if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'META' || tag === 'LINK' || tag === 'IMG' || tag === 'BR' || tag === 'HR') {
                        return;
                    }
                    let hasDirectText = false;
                    for (let i = 0; i < el.childNodes.length; i++) {
                        const n = el.childNodes[i];
                        if (n.nodeType === 3 && n.nodeValue && n.nodeValue.trim().length > 0) {
                            hasDirectText = true;
                            break;
                        }
                    }
                    if (!hasDirectText) return;

                    const cs = win.getComputedStyle(el);
                    const fgRgb = parseCssRgbColor(cs ? cs.color : '');
                    if (!fgRgb) return;

                    const { rgb: bgRgb, hasBgImage } = getEffectiveBgInfo(el);
                    const fgLum = computeRelativeLuminance(fgRgb);
                    const bgLum = computeRelativeLuminance(bgRgb);

                    // Case 1: Dark text on a dark background (e.g., black hero banner where text became dark) -> make text white
                    if (bgLum < 0.24 && fgLum < 0.35) {
                        el.style.setProperty('color', '#ffffff', 'important');
                    }
                    // Case 2: White/near-white text on a white/light background (without a background image/gradient) -> make text dark slate
                    else if (!hasBgImage && bgLum > 0.78 && fgLum > 0.85) {
                        el.style.setProperty('color', '#0f172a', 'important');
                    }
                });
            } catch (e) {
                // Ignore cross-origin or transient DOM errors
            }
        }

        function populateEmailHtmlIframe(iframeEl, rawHtmlBody) {
            if (!iframeEl) return;
            iframeEl.style.colorScheme = 'light';
            // Neutralize @media (prefers-color-scheme: dark) so emails render in their standard Gmail light-mode palette
            // while preserving intentional dark hero banners / white text inside the email design.
            const sanitizedBody = String(rawHtmlBody || '')
                .replace(/<meta[^>]*name=["']?(?:supported-)?color-schemes?["']?[^>]*>/gi, '')
                .replace(/prefers-color-scheme\s*:\s*dark/gi, 'prefers-color-scheme: never-match-dark');

            const safeHtmlDoc = `<!DOCTYPE html>
<html style="color-scheme: light only; background-color: #ffffff; color: #0f172a;">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light only">
<meta name="supported-color-schemes" content="light only">
<base target="_blank">
<style>
    :root, html, body {
        color-scheme: light only;
        margin: 0;
        padding: 14px 18px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        font-size: 14px;
        line-height: 1.6;
        color: #0f172a;
        background-color: #ffffff;
        word-wrap: break-word;
        overflow-x: auto;
    }
    img { max-width: 100%; height: auto; }
    pre, code { white-space: pre-wrap; word-break: break-word; }
</style>
</head>
<body>${sanitizedBody}</body>
</html>`;
            iframeEl.onload = () => {
                applySmartEmailIframeContrastGuard(iframeEl);
                setTimeout(() => applySmartEmailIframeContrastGuard(iframeEl), 120);
            };
            iframeEl.srcdoc = safeHtmlDoc;
        }

        function toggleEmailReaderViewMode(mode) {
            emailReaderViewMode = mode === 'plain' ? 'plain' : 'rich';
            if (selectedEmailMessageId) {
                selectEmailMessageToRead(selectedEmailMessageId, true);
            }
            const expModal = document.getElementById('expanded-email-modal');
            if (expModal && !expModal.classList.contains('hidden') && selectedEmailMessageId) {
                renderExpandedEmailModalContent(selectedEmailMessageId);
            }
        }

        function selectEmailMessageToRead(msgId, forceReRender = false) {
            const isSameMsg = (selectedEmailMessageId === msgId && lastRenderedEmailReaderMsgId === msgId);
            selectedEmailMessageId = msgId;
            renderEmailMessagesList();

            if (isSameMsg && !forceReRender) {
                return;
            }

            const msg = activeEmailMessages.find(m => m.id === msgId);
            const reader = document.getElementById('email-reader-pane');
            if (!reader || !msg) {
                lastRenderedEmailReaderMsgId = '';
                renderEmptyEmailReader();
                return;
            }

            lastRenderedEmailReaderMsgId = msgId;
            replyEmailAttachments = [];
            normalReplyMode = 'reply';

            const activeAcc = emailAccountsList.find(a => a.id === activeEmailAccountId);
            const fromAccountEmail = activeAcc ? activeAcc.email_address : '';
            const initialReplyFields = computeReplyActionFields(msg, 'reply');

            const rawHtmlBody = msg.body_html || (looksLikeEmailHtml(msg.body) ? msg.body : '');
            const hasHtmlVersion = Boolean(rawHtmlBody && rawHtmlBody.trim().length > 0);
            const cleanPlainBody = cleanEmailTextClientSide(msg.body || msg.snippet || '(No content)');
            const showRichHtml = hasHtmlVersion && emailReaderViewMode !== 'plain';

            const attachmentsBarHTML = buildEmailAttachmentsBarHTML(msg);

            const viewToggleHTML = hasHtmlVersion
                ? `<div class="inline-flex rounded-lg bg-slate-950 p-0.5 border border-slate-700">
                    <button type="button" onclick="toggleEmailReaderViewMode('rich')" class="px-2 py-1 rounded-md text-[10px] font-bold transition-all ${showRichHtml ? 'bg-gb-cyan text-slate-950' : 'text-slate-400 hover:text-white'}">
                        <i class="fas fa-eye mr-1"></i>Rich View
                    </button>
                    <button type="button" onclick="toggleEmailReaderViewMode('plain')" class="px-2 py-1 rounded-md text-[10px] font-bold transition-all ${!showRichHtml ? 'bg-gb-cyan text-slate-950' : 'text-slate-400 hover:text-white'}">
                        <i class="fas fa-align-left mr-1"></i>Plain Text
                    </button>
                   </div>`
                : '';

            reader.innerHTML = `
                <div class="p-3.5 sm:p-4 border-b border-slate-800 bg-slate-900/80 flex flex-col gap-2.5 shrink-0">
                    <!-- Top Action Toolbar Row -->
                    <div class="w-full flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-800/80">
                        <div class="text-[11px] text-slate-400 font-medium flex items-center gap-1.5">
                            <i class="far fa-clock text-gb-cyan text-[10px]"></i>
                            <span>${escapeHTML(msg.date || '')}</span>
                        </div>
                        <div class="flex flex-wrap items-center justify-end gap-1.5">
                            ${viewToggleHTML}
                            <button type="button" onclick="openAddToContactsFromEmail('${escapeHTML(msg.id)}')" class="px-2.5 py-1 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/30 border border-emerald-400/50 text-emerald-300 text-[11px] font-bold flex items-center gap-1 transition-all" title="Add Email Sender to CRM Contacts">
                                <i class="fas fa-user-plus text-[10px]"></i> <span>+ Contact</span>
                            </button>
                            <button type="button" onclick="openExpandedEmailModal('${escapeHTML(msg.id)}')" class="px-2.5 py-1 rounded-lg bg-gb-cyan/15 hover:bg-gb-cyan/30 border border-gb-cyan/50 text-gb-cyan text-[11px] font-bold flex items-center gap-1 transition-all" title="Open Full Expanded Email View">
                                <i class="fas fa-expand-alt text-[10px]"></i> <span>Expand</span>
                            </button>
                            <button type="button" onclick="trashSelectedEmailMessage('${escapeHTML(msg.id)}')" class="px-2.5 py-1 rounded-lg bg-rose-950/60 hover:bg-rose-600 border border-rose-500/40 text-rose-200 hover:text-white text-[11px] font-semibold flex items-center gap-1 transition-all" title="Move to Trash">
                                <i class="fas fa-trash-alt text-[10px]"></i> <span>Trash</span>
                            </button>
                        </div>
                    </div>
                    <!-- Full-Width Subject & Sender Details -->
                    <div class="w-full space-y-1">
                        <h3 class="w-full text-sm sm:text-base font-bold text-white leading-snug break-words">${escapeHTML(msg.subject || '(No Subject)')}</h3>
                        <div class="w-full text-xs text-slate-300 flex flex-wrap items-center gap-x-3 gap-y-1">
                            <span class="break-all sm:break-normal"><strong class="text-slate-400">From:</strong> ${escapeHTML(msg.sender || msg.sender_name)}</span>
                            ${msg.to ? `<span class="break-all sm:break-normal"><strong class="text-slate-400">To:</strong> ${escapeHTML(msg.to)}</span>` : ''}
                            ${msg.cc ? `<span class="break-all sm:break-normal"><strong class="text-slate-400">Cc:</strong> ${escapeHTML(msg.cc)}</span>` : ''}
                        </div>
                    </div>
                </div>

                ${attachmentsBarHTML}

                <!-- Email Full Body (Rich HTML Sandboxed Frame OR Clean Plain Text) -->
                ${showRichHtml
                    ? `<div class="flex-1 bg-white overflow-hidden flex flex-col">
                           <iframe id="email-html-reader-frame" class="w-full flex-1 border-0 bg-white" sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"></iframe>
                       </div>`
                    : `<div class="flex-1 overflow-y-auto p-4 text-xs sm:text-sm text-slate-200 whitespace-pre-wrap leading-relaxed font-sans select-text bg-slate-950/50">${escapeHTML(cleanPlainBody || '(No content)')}</div>`
                }

                <!-- Quick Reply / Reply All / Forward Box (Editable To & CC + Supports File Attachments) -->
                <div class="p-3.5 border-t border-slate-800 bg-slate-900/95 space-y-2 shrink-0">
                    <!-- Action Mode Bar: Reply | Reply All | Forward | +CC | Attach File -->
                    <div class="flex flex-wrap items-center justify-between gap-2">
                        <div class="flex flex-wrap items-center gap-1.5">
                            <button type="button" id="norm-mode-btn-reply" onclick="setEmailReplyActionMode('reply', 'normal')" class="px-2.5 py-1 rounded-lg bg-gb-cyan text-slate-950 font-bold text-[11px] flex items-center gap-1 shadow-[0_0_10px_rgba(0,240,255,0.3)] transition-all">
                                <i class="fas fa-reply"></i> <span>Reply</span>
                            </button>
                            <button type="button" id="norm-mode-btn-reply_all" onclick="setEmailReplyActionMode('reply_all', 'normal')" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white font-semibold text-[11px] flex items-center gap-1 border border-slate-700 transition-all">
                                <i class="fas fa-reply-all"></i> <span>Reply All</span>
                            </button>
                            <button type="button" id="norm-mode-btn-forward" onclick="setEmailReplyActionMode('forward', 'normal')" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white font-semibold text-[11px] flex items-center gap-1 border border-slate-700 transition-all">
                                <i class="fas fa-share"></i> <span>Forward</span>
                            </button>
                            <button type="button" onclick="toggleEmailReplyCcRow('normal')" class="px-2 py-1 rounded-lg bg-slate-950 hover:bg-slate-800 text-gb-cyan font-bold text-[10px] border border-gb-cyan/30 transition-all" title="Show/Hide CC Recipients">
                                + CC
                            </button>
                        </div>
                        <div class="flex items-center gap-2 text-[11px] text-slate-400">
                            <span class="hidden sm:inline"><span id="email-quick-reply-mode-label"><i class="fas fa-reply text-gb-cyan mr-1"></i>Replying</span> as <strong class="text-gb-cyan">${escapeHTML(fromAccountEmail)}</strong></span>
                            <input type="file" id="reply-email-file-input" multiple class="hidden" onchange="handleReplyEmailFileSelect(event)">
                            <button type="button" onclick="document.getElementById('reply-email-file-input')?.click()" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 border border-gb-cyan/40 text-gb-cyan text-[11px] font-semibold flex items-center gap-1 transition-all" title="Attach files">
                                <i class="fas fa-paperclip"></i>
                                <span>Attach File</span>
                            </button>
                        </div>
                    </div>

                    <!-- Editable To & CC Recipient Fields -->
                    <div class="space-y-1.5">
                        <div class="flex items-center gap-2 bg-slate-950 border border-slate-700/90 focus-within:border-gb-cyan rounded-xl px-3 py-1.5">
                            <span class="text-[11px] font-bold uppercase tracking-wider text-gb-cyan shrink-0">To:</span>
                            <input type="text" id="email-quick-reply-to" value="${escapeHTML(initialReplyFields.to)}" placeholder="recipient@example.com, another@example.com (comma-separated)" class="w-full bg-transparent text-xs text-white focus:outline-none">
                        </div>
                        <div id="email-quick-reply-cc-row" class="hidden flex items-center gap-2 bg-slate-950 border border-slate-700/90 focus-within:border-gb-cyan rounded-xl px-3 py-1.5">
                            <span class="text-[11px] font-bold uppercase tracking-wider text-slate-400 shrink-0">CC:</span>
                            <input type="text" id="email-quick-reply-cc" value="" placeholder="cc1@example.com, cc2@example.com (optional)" class="w-full bg-transparent text-xs text-white focus:outline-none">
                        </div>
                    </div>

                    <div id="reply-email-attachments-list" class="flex flex-wrap gap-1.5 empty:hidden"></div>
                    <div class="flex gap-2">
                        <textarea id="email-quick-reply-input" rows="2" placeholder="Write your reply here..." class="flex-1 bg-slate-950 border border-slate-700 focus:border-gb-cyan rounded-xl p-2.5 text-xs text-white focus:outline-none resize-none"></textarea>
                        <button type="button" id="btn-send-email-reply" onclick="sendReplyToSelectedEmail()" class="px-4 py-2 rounded-xl bg-gradient-to-r from-gb-blue to-gb-cyan text-slate-950 font-bold text-xs flex items-center justify-center gap-1.5 shrink-0 shadow-[0_0_12px_rgba(0,240,255,0.3)]">
                            <i class="fas fa-paper-plane"></i>
                            <span>Reply</span>
                        </button>
                    </div>
                </div>
            `;

            if (showRichHtml) {
                populateEmailHtmlIframe(document.getElementById('email-html-reader-frame'), rawHtmlBody);
            }
        }

        // --- EXPANDED EMAIL POPUP MODAL FUNCTIONS ---
        let expandedReplyEmailAttachments = [];

        async function handleExpandedReplyFileSelect(event) {
            const input = event?.target;
            if (!input || !input.files || input.files.length === 0) return;
            const added = await readFilesAsAttachmentObjects(input.files);
            expandedReplyEmailAttachments = [...expandedReplyEmailAttachments, ...added];
            input.value = '';
            renderExpandedReplyAttachmentsUI();
        }

        function removeExpandedReplyAttachment(index) {
            expandedReplyEmailAttachments.splice(index, 1);
            renderExpandedReplyAttachmentsUI();
        }

        function renderExpandedReplyAttachmentsUI() {
            const listEl = document.getElementById('expanded-reply-email-attachments-list');
            if (!listEl) return;
            if (expandedReplyEmailAttachments.length === 0) {
                listEl.innerHTML = '';
                return;
            }
            listEl.innerHTML = expandedReplyEmailAttachments.map((att, idx) => `
                <div class="px-2.5 py-1 rounded-lg bg-slate-950 border border-gb-cyan/40 text-xs text-slate-200 flex items-center gap-1.5">
                    <i class="fas fa-paperclip text-gb-cyan text-[10px]"></i>
                    <span class="truncate max-w-[200px]">${escapeHTML(att.filename)}</span>
                    <span class="text-[10px] text-slate-400">(${formatAttachmentSize(att.size)})</span>
                    <button type="button" onclick="removeExpandedReplyAttachment(${idx})" class="text-slate-400 hover:text-rose-400 ml-0.5">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            `).join('');
        }

        function openExpandedEmailModal(msgId) {
            const targetId = msgId || selectedEmailMessageId;
            if (!targetId) return;
            if (selectedEmailMessageId !== targetId) {
                selectEmailMessageToRead(targetId, true);
            }
            expandedReplyEmailAttachments = [];
            expandedReplyMode = 'reply';
            renderExpandedEmailModalContent(targetId);
            openModalWithFade('expanded-email-modal');
        }

        function closeExpandedEmailModal() {
            closeModalWithFade('expanded-email-modal');
        }

        function renderExpandedEmailModalContent(msgId) {
            const container = document.getElementById('expanded-email-modal-content');
            const msg = activeEmailMessages.find(m => m.id === msgId);
            if (!container || !msg) return;

            const activeAcc = emailAccountsList.find(a => a.id === activeEmailAccountId);
            const fromAccountEmail = activeAcc ? activeAcc.email_address : '';
            const initialReplyFields = computeReplyActionFields(msg, expandedReplyMode || 'reply');

            const rawHtmlBody = msg.body_html || (looksLikeEmailHtml(msg.body) ? msg.body : '');
            const hasHtmlVersion = Boolean(rawHtmlBody && rawHtmlBody.trim().length > 0);
            const cleanPlainBody = cleanEmailTextClientSide(msg.body || msg.snippet || '(No content)');
            const showRichHtml = hasHtmlVersion && emailReaderViewMode !== 'plain';

            const attachmentsBarHTML = buildEmailAttachmentsBarHTML(msg);

            const viewToggleHTML = hasHtmlVersion
                ? `<div class="inline-flex rounded-xl bg-slate-950 p-1 border border-slate-700">
                    <button type="button" onclick="toggleEmailReaderViewMode('rich')" class="px-3 py-1 rounded-lg text-xs font-bold transition-all ${showRichHtml ? 'bg-gb-cyan text-slate-950' : 'text-slate-400 hover:text-white'}">
                        <i class="fas fa-eye mr-1"></i>Rich View
                    </button>
                    <button type="button" onclick="toggleEmailReaderViewMode('plain')" class="px-3 py-1 rounded-lg text-xs font-bold transition-all ${!showRichHtml ? 'bg-gb-cyan text-slate-950' : 'text-slate-400 hover:text-white'}">
                        <i class="fas fa-align-left mr-1"></i>Plain Text
                    </button>
                   </div>`
                : '';

            container.innerHTML = `
                <!-- Expanded Modal Header -->
                <div class="px-5 py-4 border-b border-slate-800 bg-slate-900/95 flex flex-col gap-3 shrink-0">
                    <div class="w-full flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-slate-800/80">
                        <div class="flex items-center gap-2">
                            <span class="px-2 py-0.5 rounded-md bg-gb-cyan/15 border border-gb-cyan/40 text-gb-cyan text-[10px] font-bold uppercase tracking-wider">Expanded Email View</span>
                            <span class="text-xs text-slate-400">${escapeHTML(msg.date || '')}</span>
                        </div>
                        <div class="flex flex-wrap items-center gap-2">
                            ${viewToggleHTML}
                            <button type="button" onclick="openAddToContactsFromEmail('${escapeHTML(msg.id)}')" class="px-3 py-1.5 rounded-xl bg-emerald-500/15 hover:bg-emerald-500/30 border border-emerald-400/50 text-emerald-300 text-xs font-bold flex items-center gap-1.5 transition-all" title="Add Email Sender to CRM Contacts">
                                <i class="fas fa-user-plus"></i>
                                <span>Add to Contacts</span>
                            </button>
                            <button type="button" onclick="trashSelectedEmailMessage('${escapeHTML(msg.id)}', true)" class="px-3 py-1.5 rounded-xl bg-rose-950/70 hover:bg-rose-600 border border-rose-500/50 text-rose-200 hover:text-white text-xs font-bold flex items-center gap-1.5 transition-all" title="Move to Trash">
                                <i class="fas fa-trash-alt"></i>
                                <span>Trash</span>
                            </button>
                            <button type="button" onclick="closeExpandedEmailModal()" class="w-9 h-9 rounded-xl bg-slate-800 hover:bg-rose-900/70 border border-slate-600 text-slate-200 hover:text-white flex items-center justify-center transition-all" title="Close Expanded View">
                                <i class="fas fa-times text-sm"></i>
                            </button>
                        </div>
                    </div>
                    <div class="w-full space-y-1">
                        <h2 class="w-full text-base sm:text-lg font-extrabold text-white leading-snug break-words">${escapeHTML(msg.subject || '(No Subject)')}</h2>
                        <div class="w-full text-xs text-slate-300 flex flex-wrap items-center gap-x-4 gap-y-1">
                            <span class="break-all sm:break-normal"><strong class="text-slate-400">From:</strong> ${escapeHTML(msg.sender || msg.sender_name)}</span>
                            ${msg.to ? `<span class="break-all sm:break-normal"><strong class="text-slate-400">To:</strong> ${escapeHTML(msg.to)}</span>` : ''}
                            ${msg.cc ? `<span class="break-all sm:break-normal"><strong class="text-slate-400">Cc:</strong> ${escapeHTML(msg.cc)}</span>` : ''}
                        </div>
                    </div>
                </div>

                ${attachmentsBarHTML}

                <!-- Expanded Email Body -->
                ${showRichHtml
                    ? `<div class="flex-1 bg-white overflow-hidden flex flex-col">
                           <iframe id="expanded-email-html-frame" class="w-full flex-1 border-0 bg-white" sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"></iframe>
                       </div>`
                    : `<div class="flex-1 overflow-y-auto p-6 text-sm sm:text-base text-slate-100 whitespace-pre-wrap leading-relaxed font-sans select-text bg-slate-950">${escapeHTML(cleanPlainBody || '(No content)')}</div>`
                }

                <!-- Expanded Quick Reply / Reply All / Forward Box -->
                <div class="p-4 border-t border-slate-800 bg-slate-900/95 space-y-2.5 shrink-0">
                    <!-- Action Mode Bar -->
                    <div class="flex flex-wrap items-center justify-between gap-2">
                        <div class="flex flex-wrap items-center gap-1.5">
                            <button type="button" id="exp-mode-btn-reply" onclick="setEmailReplyActionMode('reply', 'expanded')" class="px-2.5 py-1 rounded-lg bg-gb-cyan text-slate-950 font-bold text-[11px] flex items-center gap-1 shadow-[0_0_10px_rgba(0,240,255,0.3)] transition-all">
                                <i class="fas fa-reply"></i> <span>Reply</span>
                            </button>
                            <button type="button" id="exp-mode-btn-reply_all" onclick="setEmailReplyActionMode('reply_all', 'expanded')" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white font-semibold text-[11px] flex items-center gap-1 border border-slate-700 transition-all">
                                <i class="fas fa-reply-all"></i> <span>Reply All</span>
                            </button>
                            <button type="button" id="exp-mode-btn-forward" onclick="setEmailReplyActionMode('forward', 'expanded')" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white font-semibold text-[11px] flex items-center gap-1 border border-slate-700 transition-all">
                                <i class="fas fa-share"></i> <span>Forward</span>
                            </button>
                            <button type="button" onclick="toggleEmailReplyCcRow('expanded')" class="px-2 py-1 rounded-lg bg-slate-950 hover:bg-slate-800 text-gb-cyan font-bold text-[10px] border border-gb-cyan/30 transition-all" title="Show/Hide CC Recipients">
                                + CC
                            </button>
                        </div>
                        <div class="flex items-center gap-2 text-xs text-slate-300">
                            <span><span id="expanded-email-reply-mode-label"><i class="fas fa-reply text-gb-cyan mr-1"></i>Replying</span> as <strong class="text-gb-cyan">${escapeHTML(fromAccountEmail)}</strong></span>
                            <input type="file" id="expanded-reply-email-file-input" multiple class="hidden" onchange="handleExpandedReplyFileSelect(event)">
                            <button type="button" onclick="document.getElementById('expanded-reply-email-file-input')?.click()" class="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-gb-cyan/40 text-gb-cyan text-xs font-bold flex items-center gap-1.5 transition-all">
                                <i class="fas fa-paperclip"></i>
                                <span>Attach File</span>
                            </button>
                        </div>
                    </div>

                    <!-- Editable To & CC Recipient Fields -->
                    <div class="grid grid-cols-1 sm:grid-cols-12 gap-2">
                        <div class="sm:col-span-12 flex items-center gap-2 bg-slate-950 border border-slate-700/90 focus-within:border-gb-cyan rounded-xl px-3 py-1.5">
                            <span class="text-xs font-bold uppercase tracking-wider text-gb-cyan shrink-0">To:</span>
                            <input type="text" id="expanded-email-reply-to" value="${escapeHTML(initialReplyFields.to)}" placeholder="recipient@example.com, another@example.com (comma-separated)" class="w-full bg-transparent text-xs sm:text-sm text-white focus:outline-none">
                        </div>
                        <div id="expanded-email-reply-cc-row" class="hidden sm:col-span-12 flex items-center gap-2 bg-slate-950 border border-slate-700/90 focus-within:border-gb-cyan rounded-xl px-3 py-1.5">
                            <span class="text-xs font-bold uppercase tracking-wider text-slate-400 shrink-0">CC:</span>
                            <input type="text" id="expanded-email-reply-cc" value="" placeholder="cc1@example.com, cc2@example.com (optional)" class="w-full bg-transparent text-xs sm:text-sm text-white focus:outline-none">
                        </div>
                    </div>

                    <div id="expanded-reply-email-attachments-list" class="flex flex-wrap gap-1.5 empty:hidden"></div>
                    <div class="flex gap-2.5">
                        <textarea id="expanded-email-reply-input" rows="3" placeholder="Write your reply here..." class="flex-1 bg-slate-950 border border-slate-700 focus:border-gb-cyan rounded-xl p-3 text-xs sm:text-sm text-white focus:outline-none resize-none"></textarea>
                        <button type="button" id="btn-send-expanded-email-reply" onclick="sendReplyFromExpandedModal()" class="px-5 py-2.5 rounded-xl bg-gradient-to-r from-gb-blue to-gb-cyan text-slate-950 font-bold text-xs sm:text-sm flex items-center justify-center gap-2 shrink-0 shadow-[0_0_15px_rgba(0,240,255,0.35)]">
                            <i class="fas fa-paper-plane"></i>
                            <span>Send Reply</span>
                        </button>
                    </div>
                </div>
            `;

            if (showRichHtml) {
                populateEmailHtmlIframe(document.getElementById('expanded-email-html-frame'), rawHtmlBody);
            }
            renderExpandedReplyAttachmentsUI();
        }

        async function sendReplyFromExpandedModal() {
            const msg = activeEmailMessages.find(m => m.id === selectedEmailMessageId);
            if (!msg || !activeEmailAccountId) return;
            const toInput = document.getElementById('expanded-email-reply-to');
            const ccInput = document.getElementById('expanded-email-reply-cc');
            const input = document.getElementById('expanded-email-reply-input');
            const btn = document.getElementById('btn-send-expanded-email-reply');

            const recipientTo = (toInput?.value || '').trim();
            const recipientCc = (ccInput?.value || '').trim();
            const bodyText = (input?.value || '').trim();

            if (!recipientTo) {
                showToastNotification('Please enter at least one recipient email in the "To:" field.', 'error');
                toInput?.focus();
                return;
            }
            if (!bodyText && expandedReplyEmailAttachments.length === 0) {
                showToastNotification('Please write a message or attach a file.', 'error');
                return;
            }
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Sending...`;
            }
            try {
                const res = await fetch('/api/email/reply', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_id: activeEmailAccountId,
                        thread_id: msg.thread_id || msg.id,
                        message_id: msg.id,
                        to: recipientTo,
                        recipient_email: recipientTo,
                        cc: recipientCc,
                        mode: expandedReplyMode || 'reply',
                        subject: msg.subject || '',
                        body: bodyText || '(Please see attached file)',
                        attachments: expandedReplyEmailAttachments
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    if (input) input.value = '';
                    expandedReplyEmailAttachments = [];
                    renderExpandedReplyAttachmentsUI();
                    showToastNotification(data.message || 'Email sent!', 'success');
                } else {
                    showToastNotification(data.message || 'Send failed.', 'error');
                }
            } catch (e) {
                showToastNotification('Network error while sending email.', 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    setEmailReplyActionMode(expandedReplyMode || 'reply', 'expanded');
                }
            }
        }

        async function sendReplyToSelectedEmail() {
            const msg = activeEmailMessages.find(m => m.id === selectedEmailMessageId);
            if (!msg || !activeEmailAccountId) return;
            const toInput = document.getElementById('email-quick-reply-to');
            const ccInput = document.getElementById('email-quick-reply-cc');
            const input = document.getElementById('email-quick-reply-input');
            const btn = document.getElementById('btn-send-email-reply');

            const recipientTo = (toInput?.value || '').trim();
            const recipientCc = (ccInput?.value || '').trim();
            const bodyText = (input?.value || '').trim();

            if (!recipientTo) {
                showToastNotification('Please enter at least one recipient email in the "To:" field.', 'error');
                toInput?.focus();
                return;
            }
            if (!bodyText && replyEmailAttachments.length === 0) {
                showToastNotification('Please write a message or attach a file.', 'error');
                return;
            }
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Sending...`;
            }
            try {
                const res = await fetch('/api/email/reply', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_id: activeEmailAccountId,
                        thread_id: msg.thread_id || msg.id,
                        message_id: msg.id,
                        to: recipientTo,
                        recipient_email: recipientTo,
                        cc: recipientCc,
                        mode: normalReplyMode || 'reply',
                        subject: msg.subject || '',
                        body: bodyText || '(Please see attached file)',
                        attachments: replyEmailAttachments
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    if (input) input.value = '';
                    replyEmailAttachments = [];
                    renderReplyEmailAttachmentsUI();
                    showToastNotification(data.message || 'Email sent!', 'success');
                } else {
                    showToastNotification(data.message || 'Send failed.', 'error');
                }
            } catch (e) {
                showToastNotification('Network error while sending email.', 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    setEmailReplyActionMode(normalReplyMode || 'reply', 'normal');
                }
            }
        }

        async function trashSelectedEmailMessage(msgId, closeExpanded = false) {
            if (!activeEmailAccountId || !msgId) return;
            try {
                const res = await fetch('/api/email/trash', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_id: activeEmailAccountId, message_id: msgId })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    if (closeExpanded) {
                        closeExpandedEmailModal();
                    }
                    showToastNotification('Moved email to Trash.', 'success');
                    activeEmailMessages = activeEmailMessages.filter(m => m.id !== msgId);
                    selectedEmailMessageId = activeEmailMessages[0]?.id || '';
                    lastRenderedEmailReaderMsgId = '';
                    renderEmailMessagesList();
                    if (selectedEmailMessageId) {
                        selectEmailMessageToRead(selectedEmailMessageId, true);
                    } else {
                        renderEmptyEmailReader();
                    }
                }
            } catch (e) {
                showToastNotification('Could not move email to Trash.', 'error');
            }
        }

        function populateComposeEmailSenderSelect(preferredAccountId = '') {
            const sel = document.getElementById('compose-email-sender-select');
            const fromLbl = document.getElementById('compose-email-from-label');
            const accounts = Array.isArray(emailAccountsList) ? emailAccountsList : [];
            if (accounts.length === 0) {
                if (sel) {
                    sel.innerHTML = `<option value="">-- No Connected Email Account (Click + Connect Email) --</option>`;
                }
                if (fromLbl) {
                    fromLbl.textContent = `From: No connected email account selected`;
                }
                return '';
            }
            let chosenId = String(preferredAccountId || activeEmailAccountId || '').trim();
            if (!chosenId || !accounts.some(a => String(a.id) === chosenId)) {
                chosenId = String(accounts[0].id || '');
            }
            activeEmailAccountId = chosenId;
            if (sel) {
                sel.innerHTML = accounts.map(acc => {
                    const isSel = String(acc.id) === chosenId ? 'selected' : '';
                    const prov = String(acc.provider || 'email').toUpperCase();
                    return `<option value="${escapeHTML(String(acc.id))}" ${isSel}>${escapeHTML(acc.email_address)} (${escapeHTML(prov)})</option>`;
                }).join('');
            }
            const activeAcc = accounts.find(a => String(a.id) === chosenId);
            if (fromLbl && activeAcc) {
                fromLbl.textContent = `From: ${activeAcc.email_address} (${String(activeAcc.provider || 'email').toUpperCase()})`;
            }
            return chosenId;
        }

        function onComposeEmailSenderAccountChange(accountId) {
            const cleanId = String(accountId || '').trim();
            if (!cleanId) return;
            activeEmailAccountId = cleanId;
            const activeAcc = (emailAccountsList || []).find(a => String(a.id) === cleanId);
            const fromLbl = document.getElementById('compose-email-from-label');
            if (fromLbl && activeAcc) {
                fromLbl.textContent = `From: ${activeAcc.email_address} (${String(activeAcc.provider || 'email').toUpperCase()})`;
            }
            const topSel = document.getElementById('email-active-account-select');
            if (topSel && topSel.value !== cleanId) {
                topSel.value = cleanId;
            }
        }

        async function openComposeEmailModal(prefillTo = '') {
            if (!Array.isArray(emailAccountsList) || emailAccountsList.length === 0) {
                try {
                    await fetchEmailAccounts(false);
                } catch (_) {}
            }
            populateComposeEmailSenderSelect(activeEmailAccountId);
            if (prefillTo) {
                const toEl = document.getElementById('compose-email-to');
                if (toEl) toEl.value = String(prefillTo).trim();
            }
            renderComposeEmailAttachmentsUI();
            openModalWithFade('compose-email-modal');
        }

        function closeComposeEmailModal() {
            closeModalWithFade('compose-email-modal');
        }

        async function sendComposedEmail() {
            const senderSelectEl = document.getElementById('compose-email-sender-select');
            const selectedSenderId = String(senderSelectEl?.value || activeEmailAccountId || '').trim();
            if (!selectedSenderId) {
                showToastNotification('Please select or connect a Sender Email account first.', 'error');
                openConnectAccountsModal('gmail');
                return;
            }
            activeEmailAccountId = selectedSenderId;
            const toVal = (document.getElementById('compose-email-to')?.value || '').trim();
            const ccVal = (document.getElementById('compose-email-cc')?.value || '').trim();
            const subjVal = (document.getElementById('compose-email-subject')?.value || '').trim();
            const bodyVal = (document.getElementById('compose-email-body')?.value || '').trim();
            const btn = document.getElementById('btn-send-composed-email');

            if (!toVal || (!bodyVal && composeEmailAttachments.length === 0)) {
                showToastNotification('Please enter Recipient Email and a Message Body (or attach a file).', 'error');
                return;
            }

            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Sending...`;
            }
            try {
                const res = await fetch('/api/email/send', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_id: selectedSenderId,
                        to: toVal,
                        cc: ccVal,
                        subject: subjVal || '(No Subject)',
                        body: bodyVal || '(Please see attached file)',
                        attachments: composeEmailAttachments
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToastNotification(data.message || 'Email sent!', 'success');
                    document.getElementById('compose-email-to').value = '';
                    const ccEl = document.getElementById('compose-email-cc');
                    if (ccEl) ccEl.value = '';
                    document.getElementById('compose-email-subject').value = '';
                    document.getElementById('compose-email-body').value = '';
                    clearComposeEmailAttachments();
                    closeComposeEmailModal();
                    if (activeEmailFolder === 'sent') {
                        refreshActiveEmailInbox(true, false);
                    }
                } else {
                    showToastNotification(data.message || 'Failed to send email.', 'error');
                }
            } catch (e) {
                showToastNotification('Network error while sending email.', 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<i class="fas fa-paper-plane"></i> <span>Send Email Now</span>`;
                }
            }
        }

        async function startEmailOAuthPopup(provider = 'gmail') {
            const cleanProvider = String(provider || 'gmail').toLowerCase();
            const label = cleanProvider === 'microsoft' ? 'Microsoft Outlook' : 'Gmail';

            // 1. Open popup SYNCHRONOUSLY on click BEFORE any await so browser popup blockers never block it!
            const width = 560;
            const height = 680;
            const left = Math.max(0, Math.round((window.screen.width - width) / 2));
            const top = Math.max(0, Math.round((window.screen.height - height) / 2));
            const popup = window.open(
                'about:blank',
                `glennbot_${cleanProvider}_oauth`,
                `width=${width},height=${height},left=${left},top=${top},resizable=yes,scrollbars=yes`
            );

            if (popup) {
                try {
                    popup.document.open();
                    popup.document.write(`<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Connecting ${label}...</title></head>
<body style="background:#050b14;color:#e2e8f0;font-family:'Segoe UI',system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;">
    <div style="background:rgba(15,23,42,0.95);border:1px solid rgba(0,240,255,0.45);border-radius:16px;padding:32px 28px;max-width:390px;box-shadow:0 0 35px rgba(0,240,255,0.2);">
        <div style="width:36px;height:36px;border:3px solid rgba(0,240,255,0.2);border-top-color:#00f0ff;border-radius:50%;margin:0 auto 14px auto;animation:spin 0.8s linear infinite;"></div>
        <style>@keyframes spin { to { transform: rotate(360deg); } }</style>
        <div style="color:#00f0ff;font-size:17px;font-weight:700;margin-bottom:8px;">Connecting to ${label}...</div>
        <p style="color:#94a3b8;font-size:13px;line-height:1.5;margin:0;">Generating secure OAuth2 session. Redirecting to login...</p>
    </div>
</body>
</html>`);
                    popup.document.close();
                } catch (e) {}
            }

            showToast(`🔗 Opening ${label} OAuth Popup...`);

            try {
                const res = await fetch('/api/oauth/email/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ provider: cleanProvider })
                });
                const data = await res.json();
                if (data.status === 'success' && data.auth_url) {
                    if (popup && !popup.closed) {
                        popup.location.href = data.auth_url;
                        popup.focus();
                    } else {
                        window.open(data.auth_url, '_blank');
                    }

                    // Show direct fallback link inside Connect Modal just in case browser blocked popups
                    const fallbackBox = document.getElementById('email-oauth-fallback-link-box');
                    if (fallbackBox) {
                        fallbackBox.classList.remove('hidden');
                        fallbackBox.innerHTML = `
                            <div class="p-3 rounded-xl bg-gb-cyan/10 border border-gb-cyan/40 flex flex-wrap items-center justify-between gap-2 text-xs">
                                <span class="text-slate-200"><i class="fas fa-external-link-alt text-gb-cyan mr-1.5"></i>Popup didn't appear? Click the direct login link:</span>
                                <a href="${escapeHTML(data.auth_url)}" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 rounded-lg bg-gb-cyan text-slate-950 font-bold hover:opacity-90 transition-all">
                                    Open ${label} Login Page
                                </a>
                            </div>
                        `;
                    }

                    // Poll /api/email/discover every 4s while popup is open
                    if (emailOAuthPollTimer) clearInterval(emailOAuthPollTimer);
                    let attempts = 0;
                    const beforeCount = emailAccountsList.length;
                    emailOAuthPollTimer = setInterval(async () => {
                        attempts++;
                        if (attempts > 35 || (popup && popup.closed)) {
                            clearInterval(emailOAuthPollTimer);
                            emailOAuthPollTimer = null;
                            await fetchEmailAccounts(true);
                            if (activeConnectModalTab === 'gmail' || activeConnectModalTab === 'microsoft') {
                                renderEmailOAuthConnectView(activeConnectModalTab);
                            }
                            return;
                        }
                        await fetchEmailAccounts(true);
                        if (emailAccountsList.length > beforeCount) {
                            clearInterval(emailOAuthPollTimer);
                            emailOAuthPollTimer = null;
                            showToast(`✅ ${label} account connected!`);
                            if (activeConnectModalTab === 'gmail' || activeConnectModalTab === 'microsoft') {
                                renderEmailOAuthConnectView(activeConnectModalTab);
                            }
                        }
                    }, 4000);
                } else {
                    if (popup && !popup.closed) popup.close();
                    showToast('❌ ' + (data.message || `Could not start ${label} OAuth.`));
                }
            } catch (err) {
                if (popup && !popup.closed) popup.close();
                showToast(`❌ Failed to launch ${label} OAuth popup.`);
            }
        }

        async function disconnectEmailAccount(accountId, emailLabel) {
            if (!confirm(`Disconnect email account "${emailLabel}" from GlennBot?`)) return;
            try {
                const res = await fetch(`/api/email/accounts/${encodeURIComponent(accountId)}`, { method: 'DELETE' });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast(`🔌 Disconnected ${emailLabel}`);
                    if (activeEmailAccountId === accountId) {
                        activeEmailAccountId = '';
                        activeEmailMessages = [];
                    }
                    await fetchEmailAccounts(false);
                    if (activeTab === 'email') {
                        refreshActiveEmailInbox(false);
                    }
                }
            } catch (e) {
                showToast('❌ Failed to disconnect email account.');
            }
        }

        async function renderEmailOAuthConnectView(provider = 'gmail') {
            const body = document.getElementById('connect-modal-body');
            if (!body) return;
            const isGmail = provider === 'gmail';
            const title = isGmail ? 'Connect with Gmail (Google Workspace / Personal Gmail)' : 'Connect with Microsoft (Outlook / Office 365)';
            const iconClass = isGmail ? 'fab fa-google text-red-400' : 'fab fa-microsoft text-sky-400';
            const btnBg = isGmail ? 'bg-red-600 hover:bg-red-500' : 'bg-sky-600 hover:bg-sky-500';
            const connectedForProvider = emailAccountsList.filter(a => a.provider === provider);

            const connectedListHTML = connectedForProvider.length === 0
                ? `<div class="text-xs text-slate-400 italic py-2">No ${isGmail ? 'Gmail' : 'Microsoft'} accounts connected yet.</div>`
                : connectedForProvider.map(acc => `
                    <div class="p-3 rounded-xl bg-slate-900 border border-slate-700 flex items-center justify-between gap-3">
                        <div class="flex items-center gap-2.5 min-w-0">
                            ${getPlatformBadge(provider)}
                            <div class="min-w-0">
                                <div class="text-xs font-bold text-white truncate">${escapeHTML(acc.email_address)}</div>
                                <div class="text-[10px] text-emerald-400">Active via OAuth2 • Single-Account Isolated</div>
                            </div>
                        </div>
                        <button type="button" onclick="disconnectEmailAccount('${escapeHTML(acc.id)}', '${escapeHTML(acc.email_address)}')" class="px-2.5 py-1 rounded-lg bg-rose-950/70 hover:bg-rose-600 border border-rose-500/50 text-rose-200 hover:text-white text-xs font-semibold">
                            Disconnect
                        </button>
                    </div>
                `).join('');

            body.innerHTML = `
                <div class="p-5 rounded-2xl bg-slate-900/70 border border-slate-700 space-y-4">
                    <div class="flex items-start gap-3.5">
                        <div class="w-12 h-12 rounded-2xl bg-slate-800 border border-slate-600 flex items-center justify-center shrink-0">
                            <i class="${iconClass} text-2xl"></i>
                        </div>
                        <div class="space-y-1">
                            <h4 class="text-sm sm:text-base font-bold text-white">${title}</h4>
                            <p class="text-xs text-slate-300 leading-relaxed">
                                Powered by <strong>Managed OAuth2 Authentication</strong> — click the button below to open the secure login popup and authorize your email inbox.
                            </p>
                        </div>
                    </div>

                    <div class="flex flex-wrap items-center gap-2.5 pt-1">
                        <button type="button" onclick="startEmailOAuthPopup('${provider}')" class="px-5 py-2.5 rounded-xl ${btnBg} text-white text-xs sm:text-sm font-bold flex items-center gap-2 shadow-lg transition-all">
                            <i class="${iconClass} text-white"></i>
                            <span>Launch ${isGmail ? 'Gmail' : 'Microsoft'} OAuth Popup</span>
                        </button>
                        <button type="button" onclick="fetchEmailAccounts(true).then(() => renderEmailOAuthConnectView('${provider}'))" class="px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-gb-cyan/50 text-gb-cyan text-xs font-bold flex items-center gap-1.5 transition-all">
                            <i class="fas fa-sync-alt"></i>
                            <span>Discover Connected ${isGmail ? 'Gmail' : 'Microsoft'} Accounts</span>
                        </button>
                    </div>

                    <div id="email-oauth-fallback-link-box" class="hidden"></div>

                    <div class="pt-3 border-t border-slate-800 space-y-2">
                        <div class="text-xs font-bold uppercase tracking-wider text-slate-400">Connected ${isGmail ? 'Gmail' : 'Microsoft'} Accounts (${connectedForProvider.length})</div>
                        <div class="space-y-2">${connectedListHTML}</div>
                    </div>
                </div>
            `;
        }

        async function renderImapConnectView() {
            const body = document.getElementById('connect-modal-body');
            if (!body) return;
            const connectedImap = emailAccountsList.filter(a => a.provider === 'imap');
            const connectedHTML = connectedImap.length === 0
                ? `<div class="text-xs text-slate-400 italic py-1">No IMAP/SMTP accounts connected yet.</div>`
                : connectedImap.map(acc => `
                    <div class="p-3 rounded-xl bg-slate-900 border border-slate-700 flex items-center justify-between gap-3">
                        <div class="flex items-center gap-2.5 min-w-0">
                            ${getPlatformBadge('imap')}
                            <div class="min-w-0">
                                <div class="text-xs font-bold text-white truncate">${escapeHTML(acc.email_address)}</div>
                                <div class="text-[10px] text-amber-300">${escapeHTML(acc.imap_host)}:${acc.imap_port} • Single-Account Isolated</div>
                            </div>
                        </div>
                        <button type="button" onclick="disconnectEmailAccount('${escapeHTML(acc.id)}', '${escapeHTML(acc.email_address)}')" class="px-2.5 py-1 rounded-lg bg-rose-950/70 hover:bg-rose-600 border border-rose-500/50 text-rose-200 hover:text-white text-xs font-semibold">
                            Disconnect
                        </button>
                    </div>
                `).join('');

            body.innerHTML = `
                <div class="p-5 rounded-2xl bg-slate-900/70 border border-slate-700 space-y-4">
                    <div class="flex items-center gap-3">
                        <div class="w-11 h-11 rounded-2xl bg-amber-500/15 border border-amber-500/40 flex items-center justify-center text-amber-400 shrink-0">
                            <i class="fas fa-server text-xl"></i>
                        </div>
                        <div>
                            <h4 class="text-sm sm:text-base font-bold text-white">Connect Custom IMAP / SMTP Email</h4>
                            <p class="text-xs text-slate-400">Connect Hostinger, cPanel Webmail, Zoho, Namecheap, Yahoo, or Gmail App Passwords.</p>
                        </div>
                    </div>

                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label class="block text-[11px] font-bold text-slate-300 mb-1">Email Address</label>
                            <input type="email" id="imap-connect-email" placeholder="support@yourdomain.com" class="w-full bg-slate-950 border border-slate-700 focus:border-gb-cyan rounded-xl px-3 py-2 text-xs text-white focus:outline-none">
                        </div>
                        <div>
                            <label class="block text-[11px] font-bold text-slate-300 mb-1">Password / App Password</label>
                            <input type="password" id="imap-connect-password" placeholder="••••••••••••" class="w-full bg-slate-950 border border-slate-700 focus:border-gb-cyan rounded-xl px-3 py-2 text-xs text-white focus:outline-none">
                        </div>
                        <div>
                            <label class="block text-[11px] font-bold text-slate-300 mb-1">IMAP Host (Incoming)</label>
                            <input type="text" id="imap-connect-host" value="imap.gmail.com" placeholder="imap.hostinger.com" class="w-full bg-slate-950 border border-slate-700 focus:border-gb-cyan rounded-xl px-3 py-2 text-xs text-white focus:outline-none">
                        </div>
                        <div>
                            <label class="block text-[11px] font-bold text-slate-300 mb-1">IMAP SSL Port</label>
                            <input type="number" id="imap-connect-port" value="993" class="w-full bg-slate-950 border border-slate-700 focus:border-gb-cyan rounded-xl px-3 py-2 text-xs text-white focus:outline-none">
                        </div>
                        <div>
                            <label class="block text-[11px] font-bold text-slate-300 mb-1">SMTP Host (Outgoing)</label>
                            <input type="text" id="smtp-connect-host" value="smtp.gmail.com" placeholder="smtp.hostinger.com" class="w-full bg-slate-950 border border-slate-700 focus:border-gb-cyan rounded-xl px-3 py-2 text-xs text-white focus:outline-none">
                        </div>
                        <div>
                            <label class="block text-[11px] font-bold text-slate-300 mb-1">SMTP Port (465 SSL / 587 TLS)</label>
                            <input type="number" id="smtp-connect-port" value="465" class="w-full bg-slate-950 border border-slate-700 focus:border-gb-cyan rounded-xl px-3 py-2 text-xs text-white focus:outline-none">
                        </div>
                    </div>

                    <button type="button" id="btn-save-imap-account" onclick="submitImapAccountConnection()" class="px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 text-slate-950 font-bold text-xs sm:text-sm flex items-center gap-2 shadow-lg">
                        <i class="fas fa-plug"></i>
                        <span>Verify &amp; Connect IMAP/SMTP Account</span>
                    </button>

                    <div class="pt-3 border-t border-slate-800 space-y-2">
                        <div class="text-xs font-bold uppercase tracking-wider text-slate-400">Connected IMAP/SMTP Accounts (${connectedImap.length})</div>
                        <div class="space-y-2">${connectedHTML}</div>
                    </div>
                </div>
            `;
        }

        async function submitImapAccountConnection() {
            const email_address = (document.getElementById('imap-connect-email')?.value || '').trim();
            const password = (document.getElementById('imap-connect-password')?.value || '').trim();
            const imap_host = (document.getElementById('imap-connect-host')?.value || '').trim();
            const imap_port = Number(document.getElementById('imap-connect-port')?.value || 993);
            const smtp_host = (document.getElementById('smtp-connect-host')?.value || '').trim();
            const smtp_port = Number(document.getElementById('smtp-connect-port')?.value || 465);
            const btn = document.getElementById('btn-save-imap-account');

            if (!email_address || !password || !imap_host || !smtp_host) {
                showToastNotification('Please fill in all IMAP/SMTP fields.', 'error');
                return;
            }
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Testing IMAP Connection...`;
            }
            try {
                const res = await fetch('/api/email/imap/connect', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email_address, password, imap_host, imap_port, smtp_host, smtp_port })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToastNotification(data.message || 'IMAP/SMTP account connected!', 'success');
                    await fetchEmailAccounts(false);
                    await renderImapConnectView();
                } else {
                    showToastNotification(data.message || 'IMAP login failed.', 'error');
                }
            } catch (e) {
                showToastNotification('Network error while testing IMAP connection.', 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<i class="fas fa-plug"></i> <span>Verify & Connect IMAP/SMTP Account</span>`;
                }
            }
        }

