        // =========================================================================
        // --- CONNECT & MANAGE SOCIAL ACCOUNTS HUB (EXTERNAL API) ---
        // =========================================================================
        function openConnectAccountsModal(tab = 'manage') {
            hidePostTooltip();
            openModalWithFade('connect-accounts-modal');
            switchConnectModalTab(tab);
        }

        function closeConnectAccountsModal() {
            closeModalWithFade('connect-accounts-modal');
        }

        async function switchConnectModalTab(tab) {
            activeConnectModalTab = tab;
            ['manage', 'facebook', 'instagram', 'tiktok', 'youtube', 'whatsapp', 'telegram', 'textbee', 'gmail', 'microsoft', 'imap'].forEach(t => {
                const btn = document.getElementById(`conn-tab-${t}`);
                if (!btn) return;
                if (t === tab) {
                    btn.className = "px-3 py-2 rounded-t-lg text-xs font-semibold border border-b-0 border-gb-cyan bg-gb-cyan/15 text-gb-cyan flex items-center gap-1.5 transition-all";
                } else {
                    btn.className = "px-3 py-2 rounded-t-lg text-xs font-semibold border border-b-0 border-slate-700 bg-slate-800/70 text-slate-300 hover:text-white flex items-center gap-1.5 transition-all";
                }
            });

            if (tab === 'manage') {
                await renderManageConnectedAccountsView();
            } else if (tab === 'facebook' || tab === 'instagram') {
                await renderMetaConnectView(tab);
            } else if (tab === 'tiktok') {
                await renderTikTokConnectView();
            } else if (tab === 'youtube') {
                await renderYouTubeConnectView();
            } else if (tab === 'whatsapp') {
                await renderWhatsAppConnectView();
            } else if (tab === 'telegram') {
                await renderTelegramConnectView();
            } else if (tab === 'textbee') {
                await renderTextbeeConnectView();
            } else if (tab === 'gmail' || tab === 'microsoft') {
                await renderEmailOAuthConnectView(tab);
            } else if (tab === 'imap') {
                await renderImapConnectView();
            }
        }

        async function renderManageConnectedAccountsView() {
            const body = document.getElementById('connect-modal-body');
            if (!body) return;
            body.innerHTML = `
                <div class="text-center py-10 text-slate-400 text-xs">
                    <i class="fas fa-circle-notch fa-spin text-2xl text-gb-cyan mb-2"></i>
                    <p>Loading connected social media accounts from Supabase...</p>
                </div>
            `;

            try {
                const res = await fetch('/api/connected_accounts');
                const data = await res.json();
                connectedAccountsMasterList = data.accounts || [];
                await fetchSocialAccounts();

                if (connectedAccountsMasterList.length === 0) {
                    body.innerHTML = `
                        <div class="text-center py-10 px-4 bg-slate-900/60 border border-dashed border-slate-700 rounded-2xl space-y-4">
                            <div class="w-16 h-16 mx-auto rounded-2xl bg-gb-cyan/10 border border-gb-cyan/30 flex items-center justify-center text-gb-cyan">
                                <i class="fas fa-plug text-2xl"></i>
                            </div>
                            <div>
                                <h4 class="text-sm sm:text-base font-bold text-white">No Social Media Accounts Connected Yet</h4>
                                <p class="text-xs text-slate-400 max-w-md mx-auto mt-1">
                                    Click any button below to log in via External API and select which Facebook, Instagram, TikTok, YouTube, WhatsApp, or Telegram accounts you want to manage:
                                </p>
                            </div>
                            <div class="flex flex-wrap items-center justify-center gap-2.5 pt-2">
                                <button type="button" onclick="switchConnectModalTab('facebook')" class="px-4 py-2.5 rounded-xl bg-[#1877F2] hover:bg-[#1877F2]/90 text-white text-xs font-bold flex items-center gap-2 shadow-lg transition-all">
                                    <i class="fab fa-facebook text-sm"></i> Connect with Facebook
                                </button>
                                <button type="button" onclick="switchConnectModalTab('instagram')" class="px-4 py-2.5 rounded-xl bg-gradient-to-r from-pink-600 to-purple-600 hover:opacity-90 text-white text-xs font-bold flex items-center gap-2 shadow-lg transition-all">
                                    <i class="fab fa-instagram text-sm"></i> Connect with Instagram
                                </button>
                                <button type="button" onclick="switchConnectModalTab('whatsapp')" class="px-4 py-2.5 rounded-xl bg-[#25D366] hover:bg-[#25D366]/90 text-slate-950 text-xs font-extrabold flex items-center gap-2 shadow-lg transition-all">
                                    <i class="fab fa-whatsapp text-sm"></i> Connect with WhatsApp
                                </button>
                                <button type="button" onclick="switchConnectModalTab('telegram')" class="px-4 py-2.5 rounded-xl bg-[#229ED9] hover:bg-[#229ED9]/90 text-white text-xs font-bold flex items-center gap-2 shadow-lg transition-all">
                                    <i class="fab fa-telegram-plane text-sm"></i> Connect with Telegram
                                </button>
                                <button type="button" onclick="switchConnectModalTab('tiktok')" class="px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-gb-cyan/50 text-white text-xs font-bold flex items-center gap-2 shadow-lg transition-all">
                                    <i class="fab fa-tiktok text-gb-cyan text-sm"></i> Connect with TikTok
                                </button>
                                <button type="button" onclick="switchConnectModalTab('youtube')" class="px-4 py-2.5 rounded-xl bg-red-600 hover:bg-red-500 text-white text-xs font-bold flex items-center gap-2 shadow-lg transition-all">
                                    <i class="fab fa-youtube text-white text-sm"></i> Connect with YouTube
                                </button>
                            </div>
                        </div>
                    `;
                    return;
                }

                const cardsHTML = connectedAccountsMasterList.map(acc => {
                    const avatar = acc.avatar_url
                        ? `<img src="${acc.avatar_url}" class="w-10 h-10 rounded-full object-cover border border-slate-600 shrink-0" onerror="this.outerHTML='<div class=\\'w-10 h-10 rounded-full bg-slate-800 border border-slate-600 flex items-center justify-center text-gb-cyan font-bold text-xs shrink-0\\'><i class=\\'fas fa-user\\'></i></div>'">`
                        : `<div class="w-10 h-10 rounded-full bg-slate-800 border border-slate-600 flex items-center justify-center text-gb-cyan font-bold text-xs shrink-0"><i class="fas fa-user"></i></div>`;

                    const subLabel = acc.platform === 'instagram'
                        ? `@${escapeHTML(acc.username)}`
                        : (acc.platform === 'tiktok' ? `@${escapeHTML(acc.username)}` : (acc.platform === 'youtube' ? `@${escapeHTML(acc.username || acc.account_name)}` : (acc.platform === 'telegram' ? `@${escapeHTML(acc.username || acc.account_name)}` : (acc.platform === 'whatsapp' ? escapeHTML(acc.username || acc.account_name) : (acc.platform === 'sms' ? escapeHTML(acc.username || 'TextBee.dev SMS Gateway (SIM 2)') : escapeHTML(acc.username || 'Facebook Page'))))));

                    const apiSourceBadge = acc.platform === 'sms' ? 'TextBee.dev API' : 'External API';
                    const actionBtnHTML = acc.platform === 'sms'
                        ? `<button type="button" onclick="switchConnectModalTab('textbee')" class="px-3 py-1.5 rounded-lg bg-emerald-950/70 hover:bg-emerald-600 border border-emerald-500/60 text-emerald-200 hover:text-white text-xs font-semibold flex items-center gap-1.5 shrink-0 transition-all"><i class="fas fa-cog text-[11px]"></i> <span>Configure SMS</span></button>`
                        : `<button type="button" onclick="disconnectSocialAccount('${acc.id}', '${escapeHTML(acc.account_name)}')"
                                class="px-3 py-1.5 rounded-lg bg-rose-950/70 hover:bg-rose-600 border border-rose-500/60 text-rose-200 hover:text-white text-xs font-semibold flex items-center gap-1.5 shrink-0 transition-all"
                                title="Remove this page/account from GlennBot">
                                <i class="fas fa-unlink text-[11px]"></i> <span>Disconnect</span>
                            </button>`;

                    return `
                        <div class="p-3.5 rounded-xl bg-slate-800/80 border border-slate-700 hover:border-gb-cyan/50 flex items-center justify-between gap-3 transition-all">
                            <div class="flex items-center gap-3 min-w-0">
                                <div class="relative shrink-0">
                                    ${avatar}
                                    <span class="absolute -bottom-1 -right-1">${getPlatformBadge(acc.platform)}</span>
                                </div>
                                <div class="min-w-0">
                                    <div class="flex items-center gap-2 flex-wrap">
                                        <span class="font-bold text-xs sm:text-sm text-white truncate">${escapeHTML(acc.account_name)}</span>
                                        <span class="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-semibold">Connected</span>
                                    </div>
                                    <div class="text-[11px] text-slate-400 truncate mt-0.5">
                                        ${subLabel} • <span class="${acc.platform === 'sms' ? 'text-emerald-300' : 'text-purple-300'}">${apiSourceBadge}</span>
                                    </div>
                                </div>
                            </div>
                            ${actionBtnHTML}
                        </div>
                    `;
                }).join('');

                body.innerHTML = `
                    <div class="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-800">
                        <div>
                            <h4 class="text-xs sm:text-sm font-bold text-white">Active Pages & Accounts in GlennBot (${connectedAccountsMasterList.length})</h4>
                            <p class="text-[11px] text-slate-400">Connected accounts appear in Scheduler, Messages, and Contacts CRM.</p>
                        </div>
                        <div class="flex flex-wrap gap-1.5">
                            <button type="button" onclick="switchConnectModalTab('textbee')" class="px-2.5 py-1.5 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/35 border border-emerald-400/50 text-emerald-300 text-[11px] font-semibold flex items-center gap-1.5">
                                <i class="fas fa-sms"></i> TextBee SMS (SIM 2)
                            </button>
                            <button type="button" onclick="switchConnectModalTab('facebook')" class="px-2.5 py-1.5 rounded-lg bg-[#1877F2]/25 hover:bg-[#1877F2]/40 border border-[#1877F2]/60 text-white text-[11px] font-semibold flex items-center gap-1.5">
                                <i class="fab fa-facebook text-blue-400"></i> + Facebook
                            </button>
                            <button type="button" onclick="switchConnectModalTab('instagram')" class="px-2.5 py-1.5 rounded-lg bg-pink-600/25 hover:bg-pink-600/40 border border-pink-500/60 text-white text-[11px] font-semibold flex items-center gap-1.5">
                                <i class="fab fa-instagram text-pink-400"></i> + Instagram
                            </button>
                            <button type="button" onclick="switchConnectModalTab('whatsapp')" class="px-2.5 py-1.5 rounded-lg bg-[#25D366]/20 hover:bg-[#25D366]/35 border border-[#25D366]/50 text-[#25D366] text-[11px] font-semibold flex items-center gap-1.5">
                                <i class="fab fa-whatsapp"></i> + WhatsApp
                            </button>
                            <button type="button" onclick="switchConnectModalTab('telegram')" class="px-2.5 py-1.5 rounded-lg bg-[#229ED9]/20 hover:bg-[#229ED9]/35 border border-[#229ED9]/50 text-[#229ED9] text-[11px] font-semibold flex items-center gap-1.5">
                                <i class="fab fa-telegram-plane"></i> + Telegram
                            </button>
                            <button type="button" onclick="switchConnectModalTab('tiktok')" class="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-600 text-white text-[11px] font-semibold flex items-center gap-1.5">
                                <i class="fab fa-tiktok text-gb-cyan"></i> + TikTok
                            </button>
                            <button type="button" onclick="switchConnectModalTab('youtube')" class="px-2.5 py-1.5 rounded-lg bg-red-600/20 hover:bg-red-600/35 border border-red-500/50 text-red-200 text-[11px] font-semibold flex items-center gap-1.5">
                                <i class="fab fa-youtube text-red-400"></i> + YouTube
                            </button>
                        </div>
                    </div>
                    <div class="space-y-2.5">
                        ${cardsHTML}
                    </div>
                `;
            } catch (e) {
                body.innerHTML = `<div class="text-center py-8 text-rose-400 text-xs">Failed to load connected accounts.</div>`;
            }
        }

        async function disconnectSocialAccount(itemId, accountName) {
            if (!confirm(`Disconnect "${accountName}" from GlennBot? Its posts, comments, and messages will also be hidden until reconnected.`)) return;
            try {
                const res = await fetch(`/api/connected_accounts/${encodeURIComponent(itemId)}`, { method: 'DELETE' });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast(`🔌 Disconnected "${accountName}" from GlennBot.`);
                    await fetchSocialAccounts();
                    await renderManageConnectedAccountsView();
                    fetchScheduledPosts();
                    fetchComments(true);
                    fetchConversations(false);
                    fetchAnalyticsData(true);
                } else {
                    alert("Error disconnecting account: " + (data.message || "Unknown error"));
                }
            } catch (e) {
                console.error("Disconnect error:", e);
            }
        }

        async function renderMetaConnectView(platform) {
            const body = document.getElementById('connect-modal-body');
            if (!body) return;
            const isFB = (platform === 'facebook');
            const label = isFB ? 'Facebook Pages' : 'Instagram Business Accounts';
            const btnColor = isFB ? 'bg-[#1877F2] hover:bg-[#1877F2]/90' : 'bg-gradient-to-r from-pink-600 to-purple-600 hover:opacity-90';
            const iconClass = isFB ? 'fab fa-facebook' : 'fab fa-instagram';

            body.innerHTML = `
                <div class="p-4 rounded-xl bg-slate-900/90 border border-slate-700 space-y-3">
                    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div>
                            <h4 class="text-xs sm:text-sm font-bold text-white flex items-center gap-2">
                                <i class="${iconClass} text-gb-cyan"></i>
                                <span>Step 1: Log in with ${isFB ? 'Facebook' : 'Instagram'} (External API)</span>
                            </h4>
                            <p class="text-[11px] text-slate-400 mt-0.5">
                                Click the button on the right to authorize ${label} via your External API pool.
                            </p>
                        </div>
                        <button type="button" onclick="launchMetaOAuthPopup('${platform}')" class="${btnColor} text-white font-bold px-4 py-2.5 rounded-xl text-xs flex items-center justify-center gap-2 shrink-0 shadow-lg transition-all">
                            <i class="${iconClass} text-base"></i>
                            <span>Log in with ${isFB ? 'Facebook' : 'Instagram'} Popup</span>
                        </button>
                    </div>
                </div>

                <!-- Step 2: Interactive Page / Account Checklist -->
                <div id="meta-discovered-container" class="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
                    <div class="text-center py-6 text-slate-400 text-xs">
                        <i class="fas fa-circle-notch fa-spin text-2xl text-gb-cyan mb-2"></i>
                        <p>Scanning available ${label} from External API...</p>
                    </div>
                </div>
            `;

            await scanMetaPagesToSelect(platform, '');
        }

        async function launchMetaOAuthPopup(platform) {
            try {
                showToast(`🔗 Opening ${platform === 'facebook' ? 'Facebook' : 'Instagram'} login popup...`);
                const res = await fetch(`/api/oauth/connect_popup/${encodeURIComponent(platform)}`, { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success' && data.auth_url) {
                    const width = 620, height = 720;
                    const left = Math.max(0, (window.screen.width - width) / 2);
                    const top = Math.max(0, (window.screen.height - height) / 2);
                    const popup = window.open(
                        data.auth_url,
                        'GlennBotExternalMetaOAuth',
                        `width=${width},height=${height},left=${left},top=${top},scrollbars=yes,resizable=yes`
                    );
                    const timer = setInterval(() => {
                        if (popup && popup.closed) {
                            clearInterval(timer);
                            showToast(`🔄 Refreshing available ${platform === 'facebook' ? 'Facebook Pages' : 'Instagram Accounts'}...`);
                            scanMetaPagesToSelect(platform, '');
                        }
                    }, 1500);
                } else {
                    showExternalApiErrorModal(`Could not open ${platform.toUpperCase()} OAuth link: ` + (data.message || "Could not retrieve or create an External API profile."));
                }
            } catch (e) {
                console.error("Meta OAuth popup error:", e);
            }
        }

        async function scanMetaPagesToSelect(platform, accessToken = '', code = '', redirectUri = '') {
            const container = document.getElementById('meta-discovered-container');
            if (!container) return;

            container.innerHTML = `
                <div class="text-center py-8 text-slate-400 text-xs">
                    <i class="fas fa-circle-notch fa-spin text-2xl text-gb-cyan mb-2"></i>
                    <p>Fetching ${platform === 'facebook' ? 'Facebook Pages' : 'Instagram Business Accounts'} from External API...</p>
                </div>
            `;

            try {
                const res = await fetch('/api/oauth/meta/discover', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        access_token: accessToken,
                        code: code,
                        redirect_uri: redirectUri,
                        use_env_fallback: false
                    })
                });
                const data = await res.json();
                if (data.status !== 'success') {
                    container.innerHTML = `
                        <div class="text-center py-6 text-amber-300 text-xs space-y-2">
                            <i class="fas fa-info-circle text-xl"></i>
                            <p>${escapeHTML(data.message || 'Could not load pages.')}</p>
                        </div>
                    `;
                    return;
                }

                discoveredCandidatesList = (platform === 'facebook')
                    ? (data.facebook_pages || [])
                    : (data.instagram_accounts || []);

                if (discoveredCandidatesList.length === 0) {
                    container.innerHTML = `
                        <div class="text-center py-8 text-slate-400 text-xs">
                            <p>No ${platform === 'facebook' ? 'Facebook Pages' : 'Instagram Business Accounts'} authorized in External API yet. Click "Log in Popup" above to connect.</p>
                        </div>
                    `;
                    return;
                }

                renderDiscoveredChecklistHTML(
                    container,
                    discoveredCandidatesList,
                    `Step 2: Select Which ${platform === 'facebook' ? 'Facebook Pages' : 'Instagram Accounts'} to Manage in GlennBot`
                );
            } catch (e) {
                console.error("Scan Meta pages error:", e);
                container.innerHTML = `<div class="text-center py-6 text-rose-400 text-xs">Network error while scanning pages.</div>`;
            }
        }

        async function renderTikTokConnectView() {
            const body = document.getElementById('connect-modal-body');
            if (!body) return;

            body.innerHTML = `
                <div class="p-4 sm:p-5 rounded-2xl bg-slate-900/95 border border-slate-700/90 space-y-4">
                    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div class="space-y-1">
                            <h4 class="text-sm sm:text-base font-bold text-white flex items-center gap-2">
                                <span class="w-7 h-7 rounded-lg bg-gb-cyan/15 border border-gb-cyan/40 flex items-center justify-center text-gb-cyan shrink-0">
                                    <i class="fab fa-tiktok text-xs"></i>
                                </span>
                                <span>Step 1: Connect TikTok via External API (Auto-Post + Comments & DMs)</span>
                            </h4>
                            <p class="text-xs text-slate-400 leading-relaxed">
                                One-step authorization powered by <strong>External API</strong> — manages your TikTok Video Auto-Posting, Direct Comment Replies, and Messages inside GlennBot.
                            </p>
                        </div>
                        <div class="flex items-center gap-2 shrink-0">
                            <button type="button" onclick="launchTikTokOAuthPopup()"
                                class="bg-gradient-to-r from-gb-blue to-gb-cyan text-slate-950 font-bold px-4 py-2.5 rounded-xl text-xs flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(0,240,255,0.25)] hover:shadow-[0_0_20px_rgba(0,240,255,0.5)] transition-all">
                                <i class="fab fa-tiktok text-sm"></i>
                                <span>Log in with TikTok Popup</span>
                            </button>
                            <button type="button" onclick="scanTikTokAccountsToSelect(true)"
                                class="bg-slate-800 hover:bg-slate-700 border border-slate-600 hover:border-gb-cyan/50 text-slate-200 hover:text-gb-cyan px-3 py-2.5 rounded-xl text-xs font-semibold inline-flex items-center gap-1.5 transition-all"
                                title="Refresh Authorized TikTok Accounts">
                                <i class="fas fa-sync-alt"></i>
                                <span class="hidden sm:inline">Refresh</span>
                            </button>
                        </div>
                    </div>
                </div>

                <div id="tiktok-discovered-container" class="p-4 rounded-2xl bg-slate-900/60 border border-slate-800">
                    <div class="text-center py-6 text-slate-400 text-xs">
                        <i class="fas fa-circle-notch fa-spin text-2xl text-gb-cyan mb-2"></i>
                        <p>Scanning authorized TikTok accounts from External API...</p>
                    </div>
                </div>
            `;

            await scanTikTokAccountsToSelect(true);
        }

        async function launchTikTokOAuthPopup() {
            try {
                showToast("🎵 Opening TikTok login popup...");
                const res = await fetch('/api/oauth/tiktok/start?provider=external_api', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success' && data.auth_url) {
                    const width = 620, height = 740;
                    const left = Math.max(0, (window.screen.width - width) / 2);
                    const top = Math.max(0, (window.screen.height - height) / 2);

                    const popup = window.open(
                        data.auth_url,
                        'GlennBotTikTokExternalOAuth',
                        `width=${width},height=${height},left=${left},top=${top},scrollbars=yes,resizable=yes`
                    );
                    const timer = setInterval(() => {
                        if (popup && popup.closed) {
                            clearInterval(timer);
                            showToast("✅ TikTok authorization finished! Refreshing list...");
                            scanTikTokAccountsToSelect(true);
                        }
                    }, 1500);
                } else {
                    showExternalApiErrorModal("Could not generate TikTok OAuth link: " + (data.message || "Could not retrieve or create an External API profile."));
                }
            } catch (e) {
                console.error("TikTok OAuth error:", e);
            }
        }

        async function scanTikTokAccountsToSelect(forceRefresh = true) {
            const container = document.getElementById('tiktok-discovered-container');
            if (!container) return;

            container.innerHTML = `
                <div class="text-center py-6 text-slate-400 text-xs">
                    <i class="fas fa-circle-notch fa-spin text-2xl text-gb-cyan mb-2"></i>
                    <p>Loading authorized TikTok accounts from External API...</p>
                </div>
            `;

            try {
                const res = await fetch(`/api/oauth/tiktok/discover?refresh=${forceRefresh ? 'true' : 'false'}`);
                const data = await res.json();
                discoveredCandidatesList = data.tiktok_accounts || [];

                if (discoveredCandidatesList.length === 0) {
                    container.innerHTML = `
                        <div class="text-center py-8 text-slate-400 text-xs">
                            <p>No TikTok accounts authorized yet. Click "Log in with TikTok Popup" above to connect.</p>
                        </div>
                    `;
                    return;
                }

                renderDiscoveredChecklistHTML(
                    container,
                    discoveredCandidatesList,
                    "Step 2: Select Which TikTok Accounts to Manage in GlennBot"
                );
            } catch (e) {
                container.innerHTML = `<div class="text-center py-6 text-rose-400 text-xs">Failed to load TikTok accounts.</div>`;
            }
        }


        async function renderYouTubeConnectView() {
            const body = document.getElementById('connect-modal-body');
            if (!body) return;

            body.innerHTML = `
                <div class="p-4 sm:p-5 rounded-2xl bg-slate-900/95 border border-slate-700/90 space-y-4">
                    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div class="space-y-1">
                            <h4 class="text-sm sm:text-base font-bold text-white flex items-center gap-2">
                                <span class="w-7 h-7 rounded-lg bg-red-600/20 border border-red-500/50 flex items-center justify-center text-red-500 shrink-0">
                                    <i class="fab fa-youtube text-xs"></i>
                                </span>
                                <span>Step 1: Connect YouTube via External API (Shorts, 16:9 Videos & Comments)</span>
                            </h4>
                            <p class="text-xs text-slate-400 leading-relaxed">
                                One-step authorization powered by <strong>External API</strong> — manages your YouTube Shorts & 16:9 Video Auto-Posting and Direct Comment Replies inside GlennBot.
                            </p>
                        </div>
                        <div class="flex items-center gap-2 shrink-0">
                            <button type="button" onclick="launchYouTubeOAuthPopup()"
                                class="bg-red-600 hover:bg-red-500 text-white font-bold px-4 py-2.5 rounded-xl text-xs flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(220,38,38,0.35)] hover:shadow-[0_0_20px_rgba(220,38,38,0.6)] transition-all">
                                <i class="fab fa-youtube text-sm"></i>
                                <span>Log in with YouTube Popup</span>
                            </button>
                            <button type="button" onclick="scanYouTubeAccountsToSelect(true)"
                                class="bg-slate-800 hover:bg-slate-700 border border-slate-600 hover:border-gb-cyan/50 text-slate-200 hover:text-gb-cyan px-3 py-2.5 rounded-xl text-xs font-semibold inline-flex items-center gap-1.5 transition-all"
                                title="Refresh Authorized YouTube Channels">
                                <i class="fas fa-sync-alt"></i>
                                <span class="hidden sm:inline">Refresh</span>
                            </button>
                        </div>
                    </div>
                </div>

                <div id="youtube-discovered-container" class="p-4 rounded-2xl bg-slate-900/60 border border-slate-800">
                    <div class="text-center py-6 text-slate-400 text-xs">
                        <i class="fas fa-circle-notch fa-spin text-2xl text-gb-cyan mb-2"></i>
                        <p>Scanning authorized YouTube channels from External API...</p>
                    </div>
                </div>
            `;

            await scanYouTubeAccountsToSelect(true);
        }

        async function launchYouTubeOAuthPopup() {
            try {
                showToast("▶️ Opening YouTube login popup...");
                const res = await fetch('/api/oauth/youtube/start?provider=external_api', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success' && data.auth_url) {
                    const width = 620, height = 740;
                    const left = Math.max(0, (window.screen.width - width) / 2);
                    const top = Math.max(0, (window.screen.height - height) / 2);

                    const popup = window.open(
                        data.auth_url,
                        'GlennBotYouTubeExternalOAuth',
                        `width=${width},height=${height},left=${left},top=${top},scrollbars=yes,resizable=yes`
                    );
                    const timer = setInterval(() => {
                        if (popup && popup.closed) {
                            clearInterval(timer);
                            showToast("✅ YouTube authorization finished! Refreshing channels...");
                            scanYouTubeAccountsToSelect(true);
                        }
                    }, 1500);
                } else {
                    showExternalApiErrorModal("Could not generate YouTube OAuth link: " + (data.message || "Could not retrieve or create an External API profile."));
                }
            } catch (e) {
                console.error("YouTube OAuth error:", e);
            }
        }

        async function scanYouTubeAccountsToSelect(forceRefresh = true) {
            const container = document.getElementById('youtube-discovered-container');
            if (!container) return;

            container.innerHTML = `
                <div class="text-center py-6 text-slate-400 text-xs">
                    <i class="fas fa-circle-notch fa-spin text-2xl text-gb-cyan mb-2"></i>
                    <p>Loading authorized YouTube channels from External API...</p>
                </div>
            `;

            try {
                const res = await fetch(`/api/oauth/youtube/discover?refresh=${forceRefresh ? 'true' : 'false'}`);
                const data = await res.json();
                discoveredCandidatesList = data.youtube_accounts || [];

                if (discoveredCandidatesList.length === 0) {
                    container.innerHTML = `
                        <div class="text-center py-8 text-slate-400 text-xs">
                            <p>No YouTube channels authorized yet. Click "Log in with YouTube Popup" above to connect.</p>
                        </div>
                    `;
                    return;
                }

                renderDiscoveredChecklistHTML(
                    container,
                    discoveredCandidatesList,
                    "Step 2: Select Which YouTube Channels to Manage in GlennBot"
                );
            } catch (e) {
                container.innerHTML = `<div class="text-center py-6 text-rose-400 text-xs">Failed to load YouTube channels.</div>`;
            }
        }

        async function renderWhatsAppConnectView() {
            const body = document.getElementById('connect-modal-body');
            if (!body) return;

            body.innerHTML = `
                <div class="p-4 sm:p-5 rounded-2xl bg-slate-900/95 border border-[#25D366]/40 space-y-4">
                    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div class="space-y-1">
                            <h4 class="text-sm sm:text-base font-bold text-white flex items-center gap-2">
                                <span class="w-7 h-7 rounded-lg bg-[#25D366]/20 border border-[#25D366]/50 flex items-center justify-center text-[#25D366] shrink-0">
                                    <i class="fab fa-whatsapp text-sm"></i>
                                </span>
                                <span>Step 1: Connect WhatsApp via External API (Zernio)</span>
                            </h4>
                            <p class="text-xs text-slate-400 leading-relaxed">
                                Link your <strong>WhatsApp Business</strong> account using your Zernio API key — automatically syncs all your WhatsApp chats into the <strong>Messages</strong> tab and imports your contacts into the <strong>Contacts CRM</strong> tab!
                            </p>
                        </div>
                        <div class="flex items-center gap-2 shrink-0">
                            <button type="button" onclick="launchWhatsAppOAuthPopup()"
                                class="bg-[#25D366] hover:bg-[#25D366]/90 text-slate-950 font-extrabold px-4 py-2.5 rounded-xl text-xs flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(37,211,102,0.3)] transition-all">
                                <i class="fab fa-whatsapp text-sm"></i>
                                <span>Connect WhatsApp Popup</span>
                            </button>
                            <button type="button" onclick="scanWhatsAppAccountsToSelect(true)"
                                class="bg-slate-800 hover:bg-slate-700 border border-slate-600 hover:border-gb-cyan/50 text-slate-200 hover:text-gb-cyan px-3 py-2.5 rounded-xl text-xs font-semibold inline-flex items-center gap-1.5 transition-all">
                                <i class="fas fa-sync-alt"></i>
                                <span class="hidden sm:inline">Refresh</span>
                            </button>
                        </div>
                    </div>
                </div>

                <div id="whatsapp-discovered-container" class="p-4 rounded-2xl bg-slate-900/60 border border-slate-800">
                    <div class="text-center py-6 text-slate-400 text-xs">
                        <i class="fas fa-circle-notch fa-spin text-2xl text-[#25D366] mb-2"></i>
                        <p>Scanning authorized WhatsApp accounts from External API...</p>
                    </div>
                </div>
            `;

            await scanWhatsAppAccountsToSelect(true);
        }

        async function launchWhatsAppOAuthPopup() {
            try {
                showToast("💬 Opening WhatsApp connection popup...");
                const res = await fetch('/api/oauth/whatsapp/start?provider=external_api', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success' && data.auth_url) {
                    const width = 620, height = 740;
                    const left = Math.max(0, (window.screen.width - width) / 2);
                    const top = Math.max(0, (window.screen.height - height) / 2);
                    const popup = window.open(
                        data.auth_url,
                        'GlennBotWhatsAppExternalOAuth',
                        `width=${width},height=${height},left=${left},top=${top},scrollbars=yes,resizable=yes`
                    );
                    const timer = setInterval(() => {
                        if (popup && popup.closed) {
                            clearInterval(timer);
                            showToast("✅ WhatsApp authorization finished! Refreshing accounts & contacts...");
                            scanWhatsAppAccountsToSelect(true);
                            fetchConversations(true);
                            syncAllCrmContactsWithDeduplication();
                        }
                    }, 1500);
                } else {
                    showExternalApiErrorModal("Could not generate WhatsApp connection link: " + (data.message || "Make sure your Zernio API key is active in Manage API."));
                }
            } catch (e) {
                console.error("WhatsApp OAuth error:", e);
            }
        }

        async function scanWhatsAppAccountsToSelect(forceRefresh = true) {
            const container = document.getElementById('whatsapp-discovered-container');
            if (!container) return;
            container.innerHTML = `
                <div class="text-center py-6 text-slate-400 text-xs">
                    <i class="fas fa-circle-notch fa-spin text-2xl text-[#25D366] mb-2"></i>
                    <p>Loading authorized WhatsApp accounts from External API...</p>
                </div>
            `;
            try {
                const res = await fetch(`/api/oauth/whatsapp/discover?refresh=${forceRefresh ? 'true' : 'false'}`);
                const data = await res.json();
                discoveredCandidatesList = data.whatsapp_accounts || [];
                if (discoveredCandidatesList.length === 0) {
                    container.innerHTML = `
                        <div class="text-center py-8 text-slate-400 text-xs">
                            <p>No WhatsApp accounts linked on your Zernio API key yet. Click "Connect WhatsApp Popup" above to link your WhatsApp account.</p>
                        </div>
                    `;
                    return;
                }
                renderDiscoveredChecklistHTML(
                    container,
                    discoveredCandidatesList,
                    "Step 2: Select Which WhatsApp Accounts to Manage in GlennBot (Messages & Contacts)"
                );
            } catch (e) {
                container.innerHTML = `<div class="text-center py-6 text-rose-400 text-xs">Failed to load WhatsApp accounts.</div>`;
            }
        }

        let telegramAutoPollInterval = null;
        let lastTelegramVerificationData = null;

        function stopTelegramAutoPoll() {
            if (telegramAutoPollInterval) {
                clearInterval(telegramAutoPollInterval);
                telegramAutoPollInterval = null;
            }
        }

        async function copyTelegramPairingText(textToCopy, label = 'Verification Code') {
            try {
                await navigator.clipboard.writeText(textToCopy);
                showToast(`✅ Copied ${label}: ${textToCopy}`);
            } catch (err) {
                const ta = document.createElement('textarea');
                ta.value = textToCopy;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                showToast(`✅ Copied ${label}: ${textToCopy}`);
            }
        }

        function copyTelegramChannelCommand(code) {
            const input = document.getElementById('telegram-channel-username-input');
            let rawChan = (input ? input.value : '').trim();
            if (!rawChan) {
                showToast("⚠️ Please enter the @username of your Telegram Channel or Group first (e.g. @mychannel).");
                if (input) input.focus();
                return;
            }
            if (!rawChan.startsWith('@')) {
                rawChan = '@' + rawChan;
            }
            const fullCmd = `${code} ${rawChan}`;
            copyTelegramPairingText(fullCmd, 'Telegram Bot Command');
        }

        function openTelegramBotWindow(botUrl) {
            const targetUrl = botUrl || 'https://t.me/LateScheduleBot';
            const width = 640, height = 760;
            const left = Math.max(0, (window.screen.width - width) / 2);
            const top = Math.max(0, (window.screen.height - height) / 2);
            window.open(
                targetUrl,
                'GlennBotTelegramBotWindow',
                `width=${width},height=${height},left=${left},top=${top},scrollbars=yes,resizable=yes`
            );
        }

        function renderTelegramBotVerificationBox(data) {
            const box = document.getElementById('telegram-bot-verification-container');
            if (!box || !data) return;
            const code = data.verification_code || '';
            const botUsername = (data.bot_username || 'LateScheduleBot').replace(/^@/, '');
            const botUrl = data.bot_url || `https://t.me/${botUsername}`;

            box.classList.remove('hidden');
            box.innerHTML = `
                <div class="p-4 sm:p-5 rounded-2xl bg-slate-950/95 border-2 border-[#229ED9]/60 shadow-[0_0_25px_rgba(34,158,217,0.2)] space-y-4">
                    <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
                        <div class="flex items-center gap-2">
                            <span class="px-2.5 py-1 rounded-lg bg-[#229ED9]/20 border border-[#229ED9]/50 text-[#229ED9] text-[11px] font-extrabold uppercase tracking-wider">
                                <i class="fas fa-robot mr-1"></i>Telegram Bot Pairing Active
                            </span>
                            <span class="text-[11px] text-slate-400">Valid for 15 minutes • Auto-scanning every 5s</span>
                        </div>
                        <button type="button" onclick="openTelegramBotWindow('${escapeHTML(botUrl)}')"
                            class="px-3.5 py-1.5 rounded-xl bg-[#229ED9] hover:bg-[#229ED9]/90 text-white text-xs font-bold flex items-center gap-1.5 shadow-[0_0_12px_rgba(34,158,217,0.4)] transition-all">
                            <i class="fab fa-telegram-plane"></i>
                            <span>Open @${escapeHTML(botUsername)} in Telegram</span>
                        </button>
                    </div>

                    <div class="p-3 rounded-xl bg-amber-500/10 border border-amber-400/30 text-xs text-amber-200 leading-relaxed">
                        <i class="fas fa-info-circle text-amber-400 mr-1"></i>
                        <strong>How Telegram Pairing Works:</strong> Telegram connects using a secure <strong>Verification Code (${escapeHTML(code)})</strong> sent to the official bot <strong>@${escapeHTML(botUsername)}</strong>.
                    </div>

                    <!-- Big Verification Code + Quick Command Builder -->
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div class="p-3.5 rounded-xl bg-slate-900 border border-slate-700 flex flex-col justify-between gap-2">
                            <span class="text-[10px] font-bold uppercase tracking-wider text-slate-400">Your Telegram Verification Code:</span>
                            <div class="flex items-center justify-between gap-2">
                                <code class="text-lg sm:text-xl font-black tracking-wider text-gb-cyan select-all">${escapeHTML(code)}</code>
                                <button type="button" onclick="copyTelegramPairingText('${escapeHTML(code)}', 'Verification Code')"
                                    class="px-3 py-1.5 rounded-lg bg-gb-cyan/20 hover:bg-gb-cyan/30 border border-gb-cyan/50 text-gb-cyan text-xs font-bold flex items-center gap-1.5 shrink-0 transition-all">
                                    <i class="fas fa-copy"></i>
                                    <span>Copy Code</span>
                                </button>
                            </div>
                        </div>

                        <div class="p-3.5 rounded-xl bg-slate-900 border border-slate-700 flex flex-col justify-between gap-2">
                            <span class="text-[10px] font-bold uppercase tracking-wider text-slate-400">Public Channel/Group Command Builder:</span>
                            <div class="flex items-center gap-1.5">
                                <input type="text" id="telegram-channel-username-input" placeholder="@yourchannel"
                                    class="flex-1 min-w-0 bg-slate-950 border border-slate-700 focus:border-[#229ED9] rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none">
                                <button type="button" onclick="copyTelegramChannelCommand('${escapeHTML(code)}')"
                                    class="px-3 py-1.5 rounded-lg bg-[#229ED9]/20 hover:bg-[#229ED9]/35 border border-[#229ED9]/50 text-[#229ED9] text-xs font-bold flex items-center gap-1 shrink-0 transition-all">
                                    <i class="fas fa-copy"></i>
                                    <span>Copy Command</span>
                                </button>
                            </div>
                        </div>
                    </div>

                    <!-- Step-by-Step Instructions -->
                    <div class="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2 text-xs text-slate-300">
                        <div class="font-bold text-white text-xs uppercase tracking-wider text-[#229ED9]">Step-by-Step Setup:</div>
                        <ol class="list-decimal list-inside space-y-1.5 text-xs text-slate-300 leading-relaxed">
                            <li>Add <strong class="text-white select-all">@${escapeHTML(botUsername)}</strong> as an <strong>Administrator</strong> in your Telegram Channel or Group.</li>
                            <li>Click the <strong class="text-[#229ED9]">Open @${escapeHTML(botUsername)} in Telegram</strong> button above to start a private chat with the bot.</li>
                            <li>For a <strong>Public Channel/Group</strong> (with a username), send this command to the bot: <code class="px-1.5 py-0.5 rounded bg-slate-950 text-gb-cyan font-bold select-all">${escapeHTML(code)} @yourchannel</code></li>
                            <li>For a <strong>Private Channel/Group</strong> (without a public username), forward any message from your channel/group to <strong>@${escapeHTML(botUsername)}</strong> along with the code: <code class="px-1.5 py-0.5 rounded bg-slate-950 text-gb-cyan font-bold select-all">${escapeHTML(code)}</code></li>
                            <li>Once confirmed by the bot, your Telegram account will automatically appear in <strong>Step 2</strong> below (or click the button below)!</li>
                        </ol>
                    </div>

                    <div class="flex flex-wrap items-center justify-between gap-2 pt-1">
                        <span class="text-[11px] text-emerald-400 flex items-center gap-1.5">
                            <i class="fas fa-satellite-dish animate-pulse"></i>
                            <span>Waiting for @${escapeHTML(botUsername)} confirmation...</span>
                        </span>
                        <button type="button" onclick="scanTelegramAccountsToSelect(true)"
                            class="px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-extrabold text-xs flex items-center gap-1.5 shadow-[0_0_15px_rgba(16,185,129,0.3)] transition-all">
                            <i class="fas fa-check-circle"></i>
                            <span>Code Sent — Scan &amp; Connect Now</span>
                        </button>
                    </div>
                </div>
            `;
        }

        async function renderTelegramConnectView() {
            const body = document.getElementById('connect-modal-body');
            if (!body) return;
            stopTelegramAutoPoll();

            body.innerHTML = `
                <div class="p-4 sm:p-5 rounded-2xl bg-slate-900/95 border border-[#229ED9]/40 space-y-4">
                    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div class="space-y-1">
                            <h4 class="text-sm sm:text-base font-bold text-white flex items-center gap-2">
                                <span class="w-7 h-7 rounded-lg bg-[#229ED9]/20 border border-[#229ED9]/50 flex items-center justify-center text-[#229ED9] shrink-0">
                                    <i class="fab fa-telegram-plane text-sm"></i>
                                </span>
                                <span>Step 1: Connect Telegram via Zernio Bot Verification</span>
                            </h4>
                            <p class="text-xs text-slate-400 leading-relaxed">
                                Generate a <strong>Telegram Verification Code</strong> for <strong>@LateScheduleBot</strong> using your Zernio API key — once verified, your Telegram chats and contacts sync into <strong>Messages</strong> & <strong>Contacts CRM</strong>!
                            </p>
                        </div>
                        <div class="flex items-center gap-2 shrink-0">
                            <button type="button" onclick="launchTelegramOAuthPopup()"
                                class="bg-[#229ED9] hover:bg-[#229ED9]/90 text-white font-bold px-4 py-2.5 rounded-xl text-xs flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(34,158,217,0.35)] transition-all">
                                <i class="fab fa-telegram-plane text-sm"></i>
                                <span>Generate Telegram Code</span>
                            </button>
                            <button type="button" onclick="scanTelegramAccountsToSelect(true)"
                                class="bg-slate-800 hover:bg-slate-700 border border-slate-600 hover:border-gb-cyan/50 text-slate-200 hover:text-gb-cyan px-3 py-2.5 rounded-xl text-xs font-semibold inline-flex items-center gap-1.5 transition-all">
                                <i class="fas fa-sync-alt"></i>
                                <span class="hidden sm:inline">Refresh</span>
                            </button>
                        </div>
                    </div>
                </div>

                <div id="telegram-bot-verification-container" class="hidden"></div>

                <div id="telegram-discovered-container" class="p-4 rounded-2xl bg-slate-900/60 border border-slate-800">
                    <div class="text-center py-6 text-slate-400 text-xs">
                        <i class="fas fa-circle-notch fa-spin text-2xl text-[#229ED9] mb-2"></i>
                        <p>Scanning authorized Telegram accounts from External API...</p>
                    </div>
                </div>
            `;

            if (lastTelegramVerificationData && lastTelegramVerificationData.verification_code) {
                renderTelegramBotVerificationBox(lastTelegramVerificationData);
            }

            await scanTelegramAccountsToSelect(true);
        }

        async function launchTelegramOAuthPopup() {
            try {
                showToast("✈️ Generating Telegram verification code from Zernio...");
                const res = await fetch('/api/oauth/telegram/start?provider=external_api', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success' && (data.connection_type === 'telegram_bot_code' || data.verification_code)) {
                    lastTelegramVerificationData = data;
                    renderTelegramBotVerificationBox(data);
                    showToast(`✅ Telegram Code Generated: ${data.verification_code}! Send it to @${data.bot_username || 'LateScheduleBot'}.`);
                    stopTelegramAutoPoll();
                    telegramAutoPollInterval = setInterval(async () => {
                        const modal = document.getElementById('connect-accounts-modal');
                        const container = document.getElementById('telegram-discovered-container');
                        if (!modal || modal.classList.contains('hidden') || !container) {
                            stopTelegramAutoPoll();
                            return;
                        }
                        try {
                            const r = await fetch('/api/oauth/telegram/discover?refresh=true');
                            const d = await r.json();
                            const found = d.telegram_accounts || [];
                            if (found.length > 0) {
                                stopTelegramAutoPoll();
                                discoveredCandidatesList = found;
                                renderDiscoveredChecklistHTML(
                                    container,
                                    discoveredCandidatesList,
                                    "Step 2: Select Which Telegram Accounts to Manage in GlennBot (Messages & Contacts)"
                                );
                                showToast("🎉 Telegram account detected! Check it below and click Save Selected Accounts.");
                                fetchConversations(true);
                                syncAllCrmContactsWithDeduplication();
                            }
                        } catch (_) {}
                    }, 5000);
                } else if (data.status === 'success' && data.auth_url) {
                    const width = 620, height = 740;
                    const left = Math.max(0, (window.screen.width - width) / 2);
                    const top = Math.max(0, (window.screen.height - height) / 2);
                    const popup = window.open(
                        data.auth_url,
                        'GlennBotTelegramExternalOAuth',
                        `width=${width},height=${height},left=${left},top=${top},scrollbars=yes,resizable=yes`
                    );
                    const timer = setInterval(() => {
                        if (popup && popup.closed) {
                            clearInterval(timer);
                            showToast("✅ Telegram authorization finished! Refreshing accounts & contacts...");
                            scanTelegramAccountsToSelect(true);
                            fetchConversations(true);
                            syncAllCrmContactsWithDeduplication();
                        }
                    }, 1500);
                } else if (data.api_limit_reached) {
                    showExternalApiErrorModal("Could not generate Telegram connection: " + (data.message || "Maximum 2 connected accounts reached on active API key."));
                } else {
                    showToast("⚠️ " + (data.message || "Could not generate Telegram connection."));
                }
            } catch (e) {
                console.error("Telegram OAuth error:", e);
            }
        }

        async function scanTelegramAccountsToSelect(forceRefresh = true) {
            const container = document.getElementById('telegram-discovered-container');
            if (!container) return;
            container.innerHTML = `
                <div class="text-center py-6 text-slate-400 text-xs">
                    <i class="fas fa-circle-notch fa-spin text-2xl text-[#229ED9] mb-2"></i>
                    <p>Loading authorized Telegram accounts from External API...</p>
                </div>
            `;
            try {
                const res = await fetch(`/api/oauth/telegram/discover?refresh=${forceRefresh ? 'true' : 'false'}`);
                const data = await res.json();
                discoveredCandidatesList = data.telegram_accounts || [];
                if (discoveredCandidatesList.length === 0) {
                    container.innerHTML = `
                        <div class="text-center py-8 text-slate-400 text-xs">
                            <p>No Telegram accounts linked on your Zernio API key yet. Click <strong>"Generate Telegram Code"</strong> above and send the code to <strong>@LateScheduleBot</strong>.</p>
                        </div>
                    `;
                    return;
                }
                renderDiscoveredChecklistHTML(
                    container,
                    discoveredCandidatesList,
                    "Step 2: Select Which Telegram Accounts to Manage in GlennBot (Messages & Contacts)"
                );
            } catch (e) {
                container.innerHTML = `<div class="text-center py-6 text-rose-400 text-xs">Failed to load Telegram accounts.</div>`;
            }
        }

        function toggleAllDiscoveredCheckboxes(checked) {
            document.querySelectorAll('.discovered-acc-checkbox').forEach(cb => {
                cb.checked = checked;
            });
        }

        function renderDiscoveredChecklistHTML(container, items, titleText) {
            const rowsHTML = items.map((item, idx) => {
                const avatar = item.avatar_url
                    ? `<img src="${item.avatar_url}" class="w-9 h-9 rounded-full object-cover border border-slate-600 shrink-0" onerror="this.outerHTML='<div class=\\'w-9 h-9 rounded-full bg-slate-800 border border-slate-600 flex items-center justify-center text-gb-cyan text-xs font-bold shrink-0\\'><i class=\\'fas fa-user\\'></i></div>'">`
                    : `<div class="w-9 h-9 rounded-full bg-slate-800 border border-slate-600 flex items-center justify-center text-gb-cyan text-xs font-bold shrink-0"><i class="fas fa-user"></i></div>`;

                const subtitle = item.platform === 'instagram'
                    ? `@${escapeHTML(item.username)} • External API Connected`
                    : (item.platform === 'tiktok' ? `@${escapeHTML(item.username)}` : `${escapeHTML(item.username || 'Page')} • External API Connected`);

                const providerBadgeHTML = `<span class="text-[10px] px-2 py-0.5 rounded-full font-semibold border bg-purple-500/15 text-purple-300 border-purple-500/40">
                       <i class="fas fa-bolt mr-1"></i>External API
                   </span>`;

                return `
                    <label class="flex items-center justify-between gap-3 p-3 rounded-xl border border-slate-700 bg-slate-800/60 hover:border-gb-cyan/60 cursor-pointer transition-all">
                        <div class="flex items-center gap-3 min-w-0">
                            <input type="checkbox" class="discovered-acc-checkbox w-4 h-4 accent-cyan-400 rounded cursor-pointer shrink-0" value="${idx}" ${item.already_connected ? 'checked' : ''}>
                            ${avatar}
                            <div class="min-w-0">
                                <div class="flex items-center gap-2 flex-wrap">
                                    <span class="font-bold text-xs sm:text-sm text-white truncate">${escapeHTML(item.account_name)}</span>
                                    ${item.already_connected
                                        ? `<span class="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-semibold">Already Connected</span>`
                                        : `<span class="text-[10px] px-2 py-0.5 rounded-full bg-gb-cyan/15 text-gb-cyan border border-gb-cyan/30 font-semibold">Available</span>`
                                    }
                                    ${providerBadgeHTML}
                                </div>
                                <p class="text-[11px] text-slate-400 truncate">${subtitle}</p>
                            </div>
                        </div>
                    </label>
                `;
            }).join('');

            container.innerHTML = `
                <div class="space-y-3">
                    <div class="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-800">
                        <span class="text-xs font-bold text-gb-cyan">${titleText}</span>
                        <div class="flex items-center gap-2 text-[11px]">
                            <button type="button" onclick="toggleAllDiscoveredCheckboxes(true)" class="text-gb-cyan hover:underline">Select All</button>
                            <span class="text-slate-600">•</span>
                            <button type="button" onclick="toggleAllDiscoveredCheckboxes(false)" class="text-slate-400 hover:text-white">Clear All</button>
                        </div>
                    </div>
                    <div class="space-y-2 max-h-[280px] overflow-y-auto pr-1">
                        ${rowsHTML}
                    </div>
                    <div class="pt-2 flex justify-end">
                        <button type="button" onclick="saveSelectedDiscoveredAccounts()" class="bg-gradient-to-r from-gb-blue to-gb-cyan text-slate-950 font-bold px-5 py-2.5 rounded-xl text-xs sm:text-sm shadow-[0_0_15px_rgba(0,240,255,0.3)] hover:shadow-[0_0_20px_rgba(0,240,255,0.6)] flex items-center gap-2 transition-all">
                            <i class="fas fa-check-circle"></i>
                            <span>Add Selected Accounts to GlennBot</span>
                        </button>
                    </div>
                </div>
            `;
        }

        async function saveSelectedDiscoveredAccounts() {
            const checked = Array.from(document.querySelectorAll('.discovered-acc-checkbox:checked'));
            if (checked.length === 0) {
                return alert("Please check at least one Page or Account to add to GlennBot.");
            }

            const selectedItems = checked.map(cb => discoveredCandidatesList[parseInt(cb.value)]).filter(Boolean);

            try {
                const res = await fetch('/api/connected_accounts/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ accounts: selectedItems })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast(`✅ Connected ${data.saved_count} social media account(s) to GlennBot!`);
                    await fetchSocialAccounts();
                    await switchConnectModalTab('manage');
                    fetchScheduledPosts();
                    fetchComments(true);
                    fetchConversations(true);
                    fetchAnalyticsData(true);
                } else {
                    alert("Error saving accounts: " + (data.message || "Unknown error"));
                }
            } catch (e) {
                console.error("Save selected accounts error:", e);
                alert("Network error while saving selected accounts.");
            }
        }

        function updatePreviews() {
            const container = document.getElementById('preview-container');
            const checkedBoxes = document.querySelectorAll('input[name="platform"]:checked');
            const postType = document.querySelector('input[name="post_type"]:checked').value;
            const prevPostType = currentDraftState.lastPostType || postType;
            if ((prevPostType === 'image') !== (postType === 'image')) {
                ['facebook', 'instagram', 'tiktok', 'youtube'].forEach(p => {
                    currentDraftState.mediaFiles[p] = null;
                    if (currentDraftState.vaultMediaItems) currentDraftState.vaultMediaItems[p] = null;
                });
            }
            currentDraftState.lastPostType = postType;
            
            clearObjectUrls(); container.innerHTML = ''; 
            
            if (checkedBoxes.length === 0) {
                container.innerHTML = `
                    <div class="flex flex-col flex-1">
                        ${getDockedActionTabsHTML()}
                        <div class="flex-1 flex flex-col items-center justify-center py-12 bg-slate-800/40 border border-slate-600 rounded-xl rounded-tl-none text-slate-500">
                            <i class="fas fa-satellite-dish text-4xl sm:text-5xl mb-3 opacity-60"></i>
                            <p class="text-sm sm:text-base text-center opacity-75">Select a platform on the left or click <span class="text-amber-400 font-semibold">Load Custom Selection</span> above.</p>
                        </div>
                    </div>
                `;
                return;
            }

            checkedBoxes.forEach((box, index) => {
                const platform = box.value;
                let icon = ''; let iconBg = '';
                
                if(platform === 'facebook') { icon = 'fab fa-facebook-f text-white'; iconBg = 'bg-blue-600'; }
                if(platform === 'instagram') { icon = 'fab fa-instagram text-white'; iconBg = 'bg-gradient-to-tr from-yellow-400 via-red-500 to-purple-500'; }
                if(platform === 'tiktok') { icon = 'fab fa-tiktok text-white'; iconBg = 'bg-slate-900 border border-slate-700'; }
                if(platform === 'youtube') { icon = 'fab fa-youtube text-white'; iconBg = 'bg-red-600'; }

                let mediaSectionHTML = '';

                if (platform === 'instagram' && postType === 'text') {
                    mediaSectionHTML = `<div class="mt-4 p-3 bg-red-900/30 border border-red-500 rounded text-red-400 text-xs sm:text-sm text-center"><i class="fas fa-exclamation-triangle mr-2"></i>Instagram requires an Image or Video. Please select a different format above.</div>`;
                }
                else if (platform === 'tiktok' && (postType === 'text' || postType === 'image')) {
                    mediaSectionHTML = `<div class="mt-4 p-3 bg-red-900/30 border border-red-500 rounded text-red-400 text-xs sm:text-sm text-center"><i class="fas fa-exclamation-triangle mr-2"></i>TikTok requires a Video (Reels or 16:9). Please select a video format above.</div>`;
                }
                else if (platform === 'youtube' && (postType === 'text' || postType === 'image')) {
                    mediaSectionHTML = `<div class="mt-4 p-3 bg-red-900/30 border border-red-500 rounded text-red-400 text-xs sm:text-sm text-center"><i class="fas fa-exclamation-triangle mr-2"></i>YouTube requires a Video (Reels/Short or 16:9 Video). Please select a video format above.</div>`;
                }
                else if (postType === 'reels') {
                    mediaSectionHTML = `<div class="flex flex-row flex-wrap gap-3 sm:gap-4 mt-4 justify-center sm:justify-start"><div class="media-box relative h-52 sm:h-64 aspect-[3/4] border border-dashed border-slate-500 rounded-xl cursor-pointer hover:border-gb-cyan transition-colors overflow-hidden group bg-slate-950/50" onclick="openCreatePostMediaSourceModal('thumb-${platform}', 'preview-thumb-${platform}', 'image', event)"><div class="overlay absolute inset-0 flex flex-col items-center justify-center z-10 text-slate-400 group-hover:text-gb-cyan"><i class="fas fa-image text-2xl mb-2"></i><span class="text-xs font-medium">Cover/Thumb</span><span class="text-[9px] text-slate-500 group-hover:text-emerald-300 mt-0.5">Local or Files Vault</span></div><div id="preview-thumb-${platform}" class="absolute inset-0 z-0 flex items-center justify-center bg-black"></div><input type="file" id="thumb-${platform}" accept="image/*" class="hidden" onclick="event.stopPropagation()" onchange="handleMediaPreview(this, 'preview-thumb-${platform}', 'image')"></div><div class="media-box relative h-52 sm:h-64 aspect-[9/16] border border-dashed border-slate-500 rounded-xl cursor-pointer hover:border-gb-cyan transition-colors overflow-hidden group bg-slate-950/50" onclick="openCreatePostMediaSourceModal('media-${platform}', 'preview-media-${platform}', 'video', event)"><div class="overlay absolute inset-0 flex flex-col items-center justify-center z-10 text-slate-400 group-hover:text-gb-cyan"><i class="fas fa-video text-3xl mb-2"></i><span class="text-xs font-medium text-center px-2">Add 9:16 Video</span><span class="text-[9px] text-slate-500 group-hover:text-emerald-300 mt-0.5">Local or Files Vault</span></div><div id="preview-media-${platform}" class="absolute inset-0 z-0 flex items-center justify-center bg-black"></div><input type="file" id="media-${platform}" accept="video/*" class="hidden" onclick="event.stopPropagation()" onchange="handleMediaPreview(this, 'preview-media-${platform}', 'video')"></div></div>`;
                } else if (postType === 'video169') {
                    mediaSectionHTML = `<div class="flex flex-row flex-wrap gap-3 sm:gap-4 mt-4 justify-center sm:justify-start"><div class="media-box relative h-40 sm:h-48 aspect-video border border-dashed border-slate-500 rounded-xl cursor-pointer hover:border-gb-cyan transition-colors overflow-hidden group bg-slate-950/50" onclick="openCreatePostMediaSourceModal('media-${platform}', 'preview-media-${platform}', 'video', event)"><div class="overlay absolute inset-0 flex flex-col items-center justify-center z-10 text-slate-400 group-hover:text-gb-cyan"><i class="fas fa-film text-2xl sm:text-3xl mb-2"></i><span class="text-xs font-medium">Add 16:9 Video</span><span class="text-[9px] text-slate-500 group-hover:text-emerald-300 mt-0.5">Local or Files Vault</span></div><div id="preview-media-${platform}" class="absolute inset-0 z-0 flex items-center justify-center bg-black"></div><input type="file" id="media-${platform}" accept="video/*" class="hidden" onclick="event.stopPropagation()" onchange="handleMediaPreview(this, 'preview-media-${platform}', 'video')"></div><div class="media-box relative h-40 sm:h-48 aspect-video border border-dashed border-slate-500 rounded-xl cursor-pointer hover:border-gb-cyan transition-colors overflow-hidden group bg-slate-950/50" onclick="openCreatePostMediaSourceModal('thumb-${platform}', 'preview-thumb-${platform}', 'image', event)"><div class="overlay absolute inset-0 flex flex-col items-center justify-center z-10 text-slate-400 group-hover:text-gb-cyan"><i class="fas fa-image text-2xl mb-2"></i><span class="text-xs font-medium">Add Thumbnail</span><span class="text-[9px] text-slate-500 group-hover:text-emerald-300 mt-0.5">Local or Files Vault</span></div><div id="preview-thumb-${platform}" class="absolute inset-0 z-0 flex items-center justify-center bg-black"></div><input type="file" id="thumb-${platform}" accept="image/*" class="hidden" onclick="event.stopPropagation()" onchange="handleMediaPreview(this, 'preview-thumb-${platform}', 'image')"></div></div>`;
                } else if (postType === 'image') {
                    mediaSectionHTML = `<div class="mt-4"><div class="media-box w-full border border-dashed border-slate-500 rounded-xl p-4 cursor-pointer hover:border-gb-cyan transition-colors bg-slate-950/50 text-center" onclick="openCreatePostMediaSourceModal('media-${platform}', 'preview-grid-${platform}', 'grid', event)"><div class="overlay"><i class="fas fa-images text-3xl mb-2 text-slate-400"></i><p class="text-xs font-medium text-slate-400 mb-1">Click to upload images (Multiple allowed)</p><p class="text-[10px] text-emerald-400/90 font-semibold mb-1">Choose From Local Device or "Files" Modal (Google Drive → Zernio)</p></div><input type="file" id="media-${platform}" accept="image/*" multiple class="hidden" onclick="event.stopPropagation()" onchange="handleMediaPreview(this, 'preview-grid-${platform}', 'grid')"><div id="preview-grid-${platform}" class="w-full"></div></div></div>`;
                }

                const savedPageId = currentDraftState.accounts[platform] || '';
                let pageSelector = '';
                
                if (platform === 'facebook') {
                    let options = `<option value="">${fbPagesList.length > 0 ? 'Select FB Page...' : 'No FB Page connected yet (Click + Connect)'}</option>`;
                    fbPagesList.forEach(page => {
                        const sel = (String(page.id) === String(savedPageId)) ? 'selected' : '';
                        options += `<option value="${page.id}" ${sel}>${escapeHTML(page.name)}</option>`;
                    });
                    pageSelector = `<select id="page-${platform}" onchange="captureCurrentDraftState()" class="bg-slate-800 border border-slate-600 text-white text-xs sm:text-sm rounded-lg focus:ring-gb-cyan focus:border-gb-cyan block w-full p-2 cursor-pointer">${options}</select>`;
                } else if (platform === 'instagram') {
                    let options = `<option value="">${igPagesList.length > 0 ? 'Select IG Account...' : 'No IG Account connected yet (Click + Connect)'}</option>`;
                    igPagesList.forEach(acc => {
                        const sel = (String(acc.id) === String(savedPageId)) ? 'selected' : '';
                        options += `<option value="${acc.id}" ${sel}>@${escapeHTML(acc.username)} (${escapeHTML(acc.name)})</option>`;
                    });
                    pageSelector = `<select id="page-${platform}" onchange="captureCurrentDraftState()" class="bg-slate-800 border border-slate-600 text-white text-xs sm:text-sm rounded-lg focus:ring-gb-cyan focus:border-gb-cyan block w-full p-2 cursor-pointer">${options}</select>`;
                } else if (platform === 'tiktok') {
                    let options = `<option value="">${tiktokAccountsList.length > 0 ? 'Select TikTok Account...' : 'No TikTok Account connected yet (Click + Connect)'}</option>`;
                    tiktokAccountsList.forEach(acc => {
                        const sel = (String(acc.id) === String(savedPageId)) ? 'selected' : '';
                        options += `<option value="${acc.id}" ${sel}>@${escapeHTML(acc.username)}</option>`;
                    });
                    pageSelector = `<select id="page-${platform}" onchange="captureCurrentDraftState()" class="bg-slate-800 border border-slate-600 text-white text-xs sm:text-sm rounded-lg focus:ring-gb-cyan focus:border-gb-cyan block w-full p-2 cursor-pointer">${options}</select>`;
                } else if (platform === 'youtube') {
                    let options = `<option value="">${youtubeAccountsList.length > 0 ? 'Select YouTube Channel...' : 'No YouTube Channel connected yet (Click + Connect)'}</option>`;
                    youtubeAccountsList.forEach(acc => {
                        const sel = (String(acc.id) === String(savedPageId)) ? 'selected' : '';
                        options += `<option value="${acc.id}" ${sel}>${escapeHTML(acc.name || acc.username)}</option>`;
                    });
                    pageSelector = `<select id="page-${platform}" onchange="captureCurrentDraftState()" class="bg-slate-800 border border-slate-600 text-white text-xs sm:text-sm rounded-lg focus:ring-gb-cyan focus:border-gb-cyan block w-full p-2 cursor-pointer">${options}</select>`;
                }

                const savedTitle = (currentDraftState.titles && currentDraftState.titles[platform]) || '';
                const savedCap = currentDraftState.captions[platform] || '';
                const savedDate = currentDraftState.dates[platform] || '';
                const savedTime = currentDraftState.times[platform] || '';

                const attachedTabsHTML = (index === 0) ? getDockedActionTabsHTML() : '';
                const topCornerClass = (index === 0) ? 'rounded-tl-none' : '';

                const cardHTML = `
                    <div class="shrink-0">
                        ${attachedTabsHTML}
                        <div class="bg-slate-800/60 border border-slate-600 rounded-xl ${topCornerClass} p-3.5 sm:p-4 shadow-lg">
                            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 mb-3">
                                <div class="flex items-center gap-2.5 w-full sm:w-auto flex-1">
                                    <div class="w-10 h-10 rounded-full ${iconBg} flex items-center justify-center shadow-md shrink-0"><i class="${icon} text-lg"></i></div>
                                    <div class="flex items-center gap-2 w-full sm:max-w-[360px]">
                                        <div class="flex-1 min-w-0">${pageSelector}</div>
                                        <button type="button" onclick="openConnectAccountsModal('${platform}')" class="px-2.5 py-2 rounded-lg bg-slate-900 hover:bg-gb-cyan/20 border border-gb-cyan/50 text-gb-cyan text-xs font-semibold shrink-0 flex items-center gap-1 transition-all" title="Connect or Remove ${platform.toUpperCase()} Pages/Accounts">
                                            <i class="fas fa-plug text-[10px]"></i> <span>Connect</span>
                                        </button>
                                    </div>
                                </div>
                                
                                <div class="grid grid-cols-2 sm:flex gap-2 w-full sm:w-auto">
                                    <div class="relative bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 flex items-center"><i class="fas fa-calendar-alt text-gb-cyan mr-2 text-xs"></i><input type="date" id="date-${platform}" value="${savedDate}" onchange="captureCurrentDraftState()" class="bg-transparent border-none text-xs text-white focus:outline-none w-full [color-scheme:dark]"></div>
                                    <div class="relative bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 flex items-center"><i class="fas fa-clock text-gb-cyan mr-2 text-xs"></i><input type="time" id="time-${platform}" value="${savedTime}" onchange="captureCurrentDraftState()" class="bg-transparent border-none text-xs text-white focus:outline-none w-full [color-scheme:dark]"></div>
                                </div>
                            </div>
                            ${platform === 'youtube' ? `
                            <div class="mb-2.5">
                                <label class="block text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1"><i class="fas fa-heading text-red-500 mr-1"></i> Video Title</label>
                                <input type="text" id="title-${platform}" value="${escapeHTML(savedTitle)}" oninput="captureCurrentDraftState()" maxlength="100" placeholder="Enter YouTube video title (max 100 chars)..." class="w-full bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-xs sm:text-sm text-white focus:ring-1 focus:ring-gb-cyan focus:border-gb-cyan transition-all placeholder-slate-500">
                            </div>
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1"><i class="fas fa-align-left text-red-500 mr-1"></i> Description</label>
                                <textarea id="caption-${platform}" oninput="captureCurrentDraftState()" rows="2" placeholder="Write your YouTube video description..." class="w-full bg-slate-900/80 border border-slate-700 rounded-lg p-3 text-xs sm:text-sm text-white focus:ring-1 focus:ring-gb-cyan focus:border-gb-cyan transition-all resize-y placeholder-slate-500">${escapeHTML(savedCap)}</textarea>
                            </div>
                            ` : `
                            <textarea id="caption-${platform}" oninput="captureCurrentDraftState()" rows="2" placeholder="Write an engaging caption..." class="w-full bg-slate-900/80 border border-slate-700 rounded-lg p-3 text-xs sm:text-sm text-white focus:ring-1 focus:ring-gb-cyan focus:border-gb-cyan transition-all resize-y placeholder-slate-500">${escapeHTML(savedCap)}</textarea>
                            `}
                            ${mediaSectionHTML}
                        </div>
                    </div>
                `;
                container.insertAdjacentHTML('beforeend', cardHTML);

                // Restore saved mediaFiles, thumbFiles, vaultMediaItems, and vaultThumbItems into the newly rendered DOM inputs and preview boxes
                const savedThumbFiles = currentDraftState.thumbFiles[platform];
                const savedVaultThumbs = currentDraftState.vaultThumbItems && currentDraftState.vaultThumbItems[platform];
                if ((savedThumbFiles && savedThumbFiles.length > 0) || (savedVaultThumbs && savedVaultThumbs.length > 0)) {
                    const thumbInput = document.getElementById(`thumb-${platform}`);
                    if (thumbInput) {
                        if (savedThumbFiles && savedThumbFiles.length > 0) {
                            try {
                                const dtThumb = new DataTransfer();
                                dtThumb.items.add(savedThumbFiles[0]);
                                thumbInput.files = dtThumb.files;
                            } catch (e) {
                                console.warn("Restore thumb DataTransfer warning:", e);
                            }
                        }
                        handleMediaPreview(thumbInput, `preview-thumb-${platform}`, 'image');
                    }
                }

                const savedMediaFiles = currentDraftState.mediaFiles[platform];
                const savedVaultMedia = currentDraftState.vaultMediaItems && currentDraftState.vaultMediaItems[platform];
                if ((savedMediaFiles && savedMediaFiles.length > 0) || (savedVaultMedia && savedVaultMedia.length > 0)) {
                    const mediaInput = document.getElementById(`media-${platform}`);
                    if (mediaInput) {
                        if (savedMediaFiles && savedMediaFiles.length > 0) {
                            try {
                                const dtMedia = new DataTransfer();
                                savedMediaFiles.forEach(f => dtMedia.items.add(f));
                                mediaInput.files = dtMedia.files;
                            } catch (e) {
                                console.warn("Restore media DataTransfer warning:", e);
                            }
                        }
                        if (postType === 'image') {
                            handleMediaPreview(mediaInput, `preview-grid-${platform}`, 'grid');
                        } else if (postType === 'reels' || postType === 'video169') {
                            handleMediaPreview(mediaInput, `preview-media-${platform}`, 'video');
                        }
                    }
                }
            });
        }

        function clearCurrentBatchInputsAfterLaunch(platformsArray) {
            (platformsArray || []).forEach(platform => {
                currentDraftState.captions[platform] = '';
                if (currentDraftState.titles && platform in currentDraftState.titles) {
                    currentDraftState.titles[platform] = '';
                }
                currentDraftState.mediaFiles[platform] = null;
                currentDraftState.thumbFiles[platform] = null;
                if (currentDraftState.vaultMediaItems) currentDraftState.vaultMediaItems[platform] = null;
                if (currentDraftState.vaultThumbItems) currentDraftState.vaultThumbItems[platform] = null;
            });
            updatePreviews();
        }

        function buildOptimisticPayloadItem(job) {
            const now = new Date();
            let schedDate = now;
            if (job.dateVal && job.timeVal) {
                const parsed = new Date(`${job.dateVal}T${job.timeVal}:00`);
                if (!isNaN(parsed.getTime())) schedDate = parsed;
            }
            const monthShort = monthNames[schedDate.getMonth()].slice(0, 3);
            const dayNum = schedDate.getDate();
            const yearNum = schedDate.getFullYear();
            const hours24 = schedDate.getHours();
            const mins = String(schedDate.getMinutes()).padStart(2, '0');
            const ampm = hours24 >= 12 ? 'PM' : 'AM';
            const hours12 = String(hours24 % 12 || 12).padStart(2, '0');

            return {
                id: job.tempId,
                platform: job.platform,
                page_id: job.pageId,
                account_name: job.accountName || job.platform.toUpperCase(),
                post_type: job.postType,
                caption: job.title ? `${job.title}\n${job.caption}`.trim() : (job.caption || ''),
                media_preview_url: (job.vaultMediaList && job.vaultMediaList[0] && job.vaultMediaList[0].download_url) ? job.vaultMediaList[0].download_url : '',
                external_post_id: '',
                permalink_url: '',
                scheduled_iso: schedDate.toISOString(),
                date_str: `${yearNum}-${String(schedDate.getMonth() + 1).padStart(2, '0')}-${String(dayNum).padStart(2, '0')}`,
                display_date: `${monthShort} ${String(dayNum).padStart(2, '0')}, ${yearNum}`,
                time_str: `${hours12}:${mins} ${ampm}`,
                display_datetime: `${monthShort} ${String(dayNum).padStart(2, '0')}, ${yearNum} • ${hours12}:${mins} ${ampm}`,
                day: dayNum,
                month: schedDate.getMonth() + 1,
                year: yearNum,
                status: 'processing_payload',
                status_message: (job.vaultMediaList && job.vaultMediaList.length > 0)
                    ? `Processing Payload • Transferring ${job.vaultMediaList[0].filename || job.vaultMediaList[0].file_id} from Google Drive Vault to Zernio Cloud...`
                    : 'Processing Payload • Uploading media & queueing in background...'
            };
        }

        async function submitPost() {
            captureCurrentDraftState();
            const checkedBoxes = Array.from(document.querySelectorAll('input[name="platform"]:checked'));
            const postType = document.querySelector('input[name="post_type"]:checked').value;
            
            if (checkedBoxes.length === 0) {
                return showToast("⚠️ Please select at least one social media platform.");
            }

            for (let box of checkedBoxes) {
                const platform = box.value;
                const pageId = document.getElementById(`page-${platform}`)?.value;
                
                if (!pageId) {
                    return showToast(`❌ Please select a ${platform.toUpperCase()} account from the dropdown first!`);
                }
                if (platform === 'instagram' && postType === 'text') {
                    return showToast("❌ Instagram requires an Image or Video format.");
                }
                if (platform === 'tiktok' && (postType === 'text' || postType === 'image')) {
                    return showToast("❌ TikTok requires a Video format (Reels or 16:9).");
                }
                if (platform === 'youtube' && (postType === 'text' || postType === 'image')) {
                    return showToast("❌ YouTube requires a Video format (Reels/Short or 16:9 Video).");
                }
            }

            // Build the batch of payloads right now before clearing/freeing the form
            const batchJobs = [];
            for (let box of checkedBoxes) {
                const platform = box.value;
                const selectEl = document.getElementById(`page-${platform}`);
                const pageId = selectEl?.value || '';
                const accountName = selectEl?.options[selectEl.selectedIndex]?.text || platform;
                const dateVal = document.getElementById(`date-${platform}`)?.value || '';
                const timeVal = document.getElementById(`time-${platform}`)?.value || '';
                const titleInputEl = document.getElementById(`title-${platform}`);
                const titleVal = titleInputEl ? titleInputEl.value : '';
                const captionVal = document.getElementById(`caption-${platform}`)?.value || '';

                const formData = new FormData();
                formData.append('platform', platform);
                formData.append('post_type', postType);
                formData.append('base_url', window.location.origin);
                if (pageId) formData.append('pageId', pageId);
                formData.append('accountName', accountName);
                formData.append('date', dateVal);
                formData.append('time', timeVal);
                if (titleInputEl) formData.append('title', titleVal);
                formData.append('caption', captionVal);

                let thumbFile = null;
                let videoFile = null;
                let vaultThumbFileId = '';
                let vaultMediaList = [];

                if (postType !== 'text') {
                    const thumbInput = document.getElementById(`thumb-${platform}`);
                    thumbFile = (thumbInput && thumbInput.files && thumbInput.files[0])
                        ? thumbInput.files[0]
                        : ((currentDraftState.thumbFiles[platform] && currentDraftState.thumbFiles[platform][0]) ? currentDraftState.thumbFiles[platform][0] : null);
                    const vaultThumbArr = currentDraftState.vaultThumbItems && currentDraftState.vaultThumbItems[platform];
                    if (thumbFile) {
                        formData.append('thumbnail', thumbFile);
                    } else if (Array.isArray(vaultThumbArr) && vaultThumbArr[0] && vaultThumbArr[0].file_id) {
                        vaultThumbFileId = String(vaultThumbArr[0].file_id);
                        formData.append('vault_thumb_file_id', vaultThumbFileId);
                    }
                    
                    const mediaInput = document.getElementById(`media-${platform}`);
                    const mediaFilesList = (mediaInput && mediaInput.files && mediaInput.files.length > 0)
                        ? Array.from(mediaInput.files)
                        : ((currentDraftState.mediaFiles[platform] && currentDraftState.mediaFiles[platform].length > 0) ? currentDraftState.mediaFiles[platform] : []);
                    const vaultMediaArr = (currentDraftState.vaultMediaItems && Array.isArray(currentDraftState.vaultMediaItems[platform]))
                        ? currentDraftState.vaultMediaItems[platform]
                        : [];

                    if (mediaFilesList.length > 0) {
                        if (postType === 'image') {
                            for (let i = 0; i < mediaFilesList.length; i++) formData.append('media_files', mediaFilesList[i]);
                        } else {
                            videoFile = mediaFilesList[0];
                            formData.append('media', mediaFilesList[0]);
                        }
                    } else if (vaultMediaArr.length > 0) {
                        vaultMediaList = vaultMediaArr.map(item => Object.assign({}, item));
                        if (postType === 'image') {
                            const ids = vaultMediaList.map(item => String(item.file_id || '').trim()).filter(Boolean);
                            formData.append('vault_media_file_ids', JSON.stringify(ids));
                            if (ids[0]) formData.append('vault_media_file_id', ids[0]);
                        } else if (vaultMediaList[0] && vaultMediaList[0].file_id) {
                            formData.append('vault_media_file_id', String(vaultMediaList[0].file_id));
                        }
                    }
                }

                batchJobs.push({
                    tempId: `temp_payload_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
                    platform,
                    postType,
                    pageId,
                    accountName,
                    dateVal,
                    timeVal,
                    title: titleVal,
                    caption: captionVal,
                    thumbFile,
                    videoFile,
                    vaultThumbFileId,
                    vaultMediaList,
                    formData
                });
            }

            // Helper: Safely parse JSON even if a proxy/gateway returns an HTML 502/503 error page
            async function safeParseServerJson(res, stepLabel) {
                const rawText = await res.text();
                try {
                    return JSON.parse(rawText);
                } catch (_) {
                    const cleanSnippet = rawText.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120);
                    return {
                        status: 'error',
                        message: `${stepLabel} returned HTTP ${res.status}${cleanSnippet ? ': ' + cleanSnippet : ''}`
                    };
                }
            }

            // Helper: Compute SHA-1 hex in browser for chunked upload verification
            async function computeBlobSha1Hex(blob) {
                const buffer = await blob.arrayBuffer();
                if (window.crypto && window.crypto.subtle) {
                    const hashBuffer = await window.crypto.subtle.digest('SHA-1', buffer);
                    const hashArray = Array.from(new Uint8Array(hashBuffer));
                    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
                }
                // Pure-JS SHA-1 fallback if WebCrypto is unavailable on non-HTTPS LAN origins
                const bytes = new Uint8Array(buffer);
                function rol(n, s) { return (n << s) | (n >>> (32 - s)); }
                const l = bytes.length;
                const words = [];
                for (let i = 0; i < l; i++) {
                    words[i >>> 2] |= bytes[i] << (24 - (i % 4) * 8);
                }
                words[l >>> 2] |= 0x80 << (24 - (l % 4) * 8);
                words[(((l + 8) >>> 6) << 4) + 15] = l * 8;
                let h0 = 0x67452301, h1 = 0xefcdab89, h2 = 0x98badcfe, h3 = 0x10325476, h4 = 0xc3d2e1f0;
                const w = new Array(80);
                for (let i = 0; i < words.length; i += 16) {
                    let a = h0, b = h1, c = h2, d = h3, e = h4;
                    for (let j = 0; j < 80; j++) {
                        if (j < 16) w[j] = words[i + j] | 0;
                        else w[j] = rol(w[j - 3] ^ w[j - 8] ^ w[j - 14] ^ w[j - 16], 1);
                        const f = j < 20 ? ((b & c) | ((~b) & d)) + 0x5a827999
                                : j < 40 ? (b ^ c ^ d) + 0x6ed9eba1
                                : j < 60 ? ((b & c) | (b & d) | (c & d)) - 0x70e44324
                                : (b ^ c ^ d) - 0x359d3e2a;
                        const t = (rol(a, 5) + f + e + w[j]) | 0;
                        e = d; d = c; c = rol(b, 30); b = a; a = t;
                    }
                    h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c) | 0; h3 = (h3 + d) | 0; h4 = (h4 + e) | 0;
                }
                return [h0, h1, h2, h3, h4].map(v => (v >>> 0).toString(16).padStart(8, '0')).join('');
            }

            // Expose helpers globally so the Files Vault modal can also use resilient JSON parsing & SHA-1
            window.glennbotSafeParseServerJson = safeParseServerJson;
            window.glennbotComputeBlobSha1Hex = computeBlobSha1Hex;

            // Helper: Transmits a scheduled post using Direct Browser-to-Zernio Media Cloud or Google Drive Chunked Upload
            async function transmitScheduledJobResilient(job) {
                const isVideoPost = (job.postType === 'reels' || job.postType === 'video169') && job.videoFile;
                if (!isVideoPost) {
                    try {
                        const response = await fetch('/api/schedule', { method: 'POST', body: job.formData });
                        const result = await safeParseServerJson(response, 'Schedule API');
                        if (!response.ok || result.status === 'error') {
                            throw new Error(result.message || `Server returned ${response.status}`);
                        }
                        optimisticProcessingPosts = optimisticProcessingPosts.filter(item => item.id !== job.tempId);
                        await fetchScheduledPosts();
                    } catch (err) {
                        console.error("Schedule Transmission Error:", err);
                        const optItem = optimisticProcessingPosts.find(item => item.id === job.tempId);
                        if (optItem) {
                            optItem.status = 'failed';
                            optItem.status_message = `Upload Failed: ${err.message || err}`;
                            renderCalendar();
                            renderQueue();
                        }
                        showToast(`⚠️ Failed to schedule ${job.platform.toUpperCase()}: ${err.message || err}`);
                    }
                    return;
                }

                // Direct Browser-to-Zernio / Google Drive Chunked Upload Pipeline (15 MB parts)
                const CHUNK_SIZE = 15 * 1024 * 1024; // 15 MB per part
                const MULTIPART_THRESHOLD = 20 * 1024 * 1024; // Files > 20 MB always have >= 2 parts
                const file = job.videoFile;
                const totalSize = file.size || 0;
                const totalParts = totalSize > MULTIPART_THRESHOLD ? Math.ceil(totalSize / CHUNK_SIZE) : 1;

                let dbRecordId = '';
                try {
                    const initForm = new FormData();
                    initForm.append('platform', job.platform);
                    initForm.append('post_type', job.postType);
                    if (job.pageId) initForm.append('pageId', job.pageId);
                    initForm.append('accountName', job.accountName || job.platform);
                    initForm.append('date', job.dateVal || '');
                    initForm.append('time', job.timeVal || '');
                    initForm.append('title', job.title || '');
                    initForm.append('caption', job.caption || '');
                    initForm.append('media_filename', file.name || 'video.mp4');
                    initForm.append('media_total_size', String(totalSize));
                    initForm.append('total_parts', String(totalParts));
                    if (job.thumbFile) {
                        initForm.append('thumbnail', job.thumbFile);
                    } else if (job.vaultThumbFileId) {
                        initForm.append('vault_thumb_file_id', job.vaultThumbFileId);
                    }

                    const initRes = await fetch('/api/schedule/chunked/init', { method: 'POST', body: initForm });
                    const initData = await safeParseServerJson(initRes, 'Upload Init');
                    if (!initRes.ok || initData.status !== 'success' || !initData.id) {
                        throw new Error(initData.message || `Failed to initialize upload (${initRes.status})`);
                    }

                    dbRecordId = initData.id;
                    let zernioUploadUrl = initData.zernio_upload_url || '';
                    let zernioPublicUrl = initData.zernio_public_url || '';
                    let mediaContentType = initData.content_type || 'video/mp4';
                    let uploadedDirectlyToZernio = false;
                    let cancelledDuringDirectZernio = false;
                    const collectedPartSha1s = [];

                    // Remove temporary local item ONLY AFTER real database row is saved, so it NEVER vanishes!
                    optimisticProcessingPosts = optimisticProcessingPosts.filter(item => item.id !== job.tempId);
                    await fetchScheduledPosts();

                    // TIER 1 (FASTEST & ZERO RENDER TRAFFIC): Direct Browser-to-Zernio Media Cloud PUT (supports up to 5GB / 4GB FB)
                    // Retries up to 3 times with a fresh presigned URL so a 1.4GB video never gets stuck at 11% or falls back to Render!
                    if (zernioUploadUrl && zernioPublicUrl) {
                        for (let zAttempt = 1; zAttempt <= 3; zAttempt++) {
                            try {
                                if (zAttempt > 1) {
                                    const pForm = new FormData();
                                    pForm.append('record_id', dbRecordId);
                                    pForm.append('platform', job.platform || '');
                                    pForm.append('pageId', job.pageId || '');
                                    pForm.append('media_filename', file.name || 'video.mp4');
                                    pForm.append('media_total_size', String(totalSize));
                                    pForm.append('content_type', mediaContentType);
                                    const pRes = await fetch('/api/schedule/chunked/zernio-presign', { method: 'POST', body: pForm });
                                    const pData = await safeParseServerJson(pRes, 'Refresh Zernio Presign');
                                    if (pRes.ok && pData.zernio_upload_url && pData.zernio_public_url) {
                                        zernioUploadUrl = pData.zernio_upload_url;
                                        zernioPublicUrl = pData.zernio_public_url;
                                        if (pData.content_type) mediaContentType = pData.content_type;
                                    }
                                }

                                await new Promise((resolveZernio, rejectZernio) => {
                                    const xhr = new XMLHttpRequest();
                                    xhr.open('PUT', zernioUploadUrl, true);
                                    xhr.setRequestHeader('Content-Type', mediaContentType);

                                    let lastReportedPct = 0;
                                    let lastReportTs = 0;
                                    let pingInFlight = false;
                                    let stallTimer = null;

                                    const resetStallTimer = () => {
                                        if (stallTimer) clearTimeout(stallTimer);
                                        stallTimer = setTimeout(() => {
                                            try { xhr.abort(); } catch (_) {}
                                            rejectZernio(new Error('Direct Cloud PUT stalled for 90s'));
                                        }, 90000);
                                    };
                                    resetStallTimer();

                                    xhr.upload.onprogress = (evt) => {
                                        resetStallTimer();
                                        if (!evt.lengthComputable || evt.total <= 0) return;
                                        const pct = Math.min(99, Math.max(1, Math.round((evt.loaded / evt.total) * 100)));
                                        const nowTs = Date.now();
                                        const gbLabel = totalSize >= 1073741824
                                            ? `${(totalSize / 1073741824).toFixed(2)} GB`
                                            : `${(totalSize / 1048576).toFixed(1)} MB`;
                                        const retryTag = zAttempt > 1 ? ` • Retry ${zAttempt}/3` : '';
                                        const liveMsg = `Processing Payload • Direct-Uploading ${gbLabel} to External API Media Cloud (${pct}%${retryTag})...`;

                                        window.activeBrowserUploadProgress[dbRecordId] = {
                                            pct,
                                            status_message: liveMsg,
                                            ts: nowTs
                                        };

                                        const tracked = scheduledPostsList.find(p => p.id === dbRecordId);
                                        if (tracked) {
                                            tracked.status_message = liveMsg;
                                            renderQueue();
                                        }

                                        // Throttle backend heartbeat pings to every 5% or 6 seconds so Render.com stays completely idle
                                        if (!pingInFlight && (pct - lastReportedPct >= 5 || nowTs - lastReportTs >= 6000)) {
                                            lastReportedPct = pct;
                                            lastReportTs = nowTs;
                                            pingInFlight = true;
                                            const confForm = new FormData();
                                            confForm.append('record_id', dbRecordId);
                                            confForm.append('part_number', String(pct));
                                            confForm.append('total_parts', '100');
                                            confForm.append('media_total_size', String(totalSize));
                                            confForm.append('storage_target', 'zernio');
                                            fetch('/api/schedule/chunked/part-confirm', { method: 'POST', body: confForm })
                                                .then(r => safeParseServerJson(r, 'Zernio Progress'))
                                                .then(d => {
                                                    if (d && d.status === 'cancelled') {
                                                        cancelledDuringDirectZernio = true;
                                                        try { xhr.abort(); } catch (_) {}
                                                    }
                                                })
                                                .catch(() => {})
                                                .finally(() => { pingInFlight = false; });
                                        }
                                    };

                                    xhr.onload = () => {
                                        if (stallTimer) clearTimeout(stallTimer);
                                        if (xhr.status >= 200 && xhr.status < 300) {
                                            uploadedDirectlyToZernio = true;
                                            resolveZernio(true);
                                        } else {
                                            rejectZernio(new Error(`Direct Cloud PUT HTTP ${xhr.status}`));
                                        }
                                    };
                                    xhr.onerror = () => {
                                        if (stallTimer) clearTimeout(stallTimer);
                                        rejectZernio(new Error('Direct Cloud PUT network interruption'));
                                    };
                                    xhr.onabort = () => {
                                        if (stallTimer) clearTimeout(stallTimer);
                                        if (cancelledDuringDirectZernio) {
                                            resolveZernio(false);
                                        } else {
                                            rejectZernio(new Error('Direct Cloud PUT aborted'));
                                        }
                                    };
                                    xhr.send(file);
                                });

                                if (uploadedDirectlyToZernio || cancelledDuringDirectZernio) {
                                    break;
                                }
                            } catch (zernioDirectErr) {
                                console.warn(`Direct Browser-to-Zernio PUT attempt ${zAttempt}/3 warning:`, zernioDirectErr);
                                uploadedDirectlyToZernio = false;
                                if (cancelledDuringDirectZernio) break;
                                if (zAttempt < 3) {
                                    await new Promise(r => setTimeout(r, 2500 * zAttempt));
                                } else if (totalSize > 100 * 1024 * 1024) {
                                    // Never route >100MB (e.g. 1.4GB) video bytes through Render.com's 512MB instance!
                                    throw new Error(`Direct upload of ${(totalSize / 1073741824).toFixed(2)} GB video to External API Media Cloud was interrupted after 3 attempts (${zernioDirectErr.message || zernioDirectErr}). Please check your internet connection and try again.`);
                                }
                            }
                        }
                    }

                    if (cancelledDuringDirectZernio) {
                        delete window.activeBrowserUploadProgress[dbRecordId];
                        await fetchScheduledPosts();
                        return;
                    }

                    if (!uploadedDirectlyToZernio) {
                        for (let partNum = 1; partNum <= totalParts; partNum++) {
                            const startByte = (partNum - 1) * CHUNK_SIZE;
                            const endByte = partNum === totalParts ? totalSize : Math.min(totalSize, startByte + CHUNK_SIZE);
                            const chunkBlob = file.slice(startByte, endByte);

                            let partSuccess = false;
                            let lastPartErr = '';

                            // AUTOMATIC FALLBACK (Only for videos <= 100 MB): 15 MB Chunk Stream Pipe via Python to Google Drive / Zernio
                            if (!partSuccess) {
                                for (let attempt = 1; attempt <= 3; attempt++) {
                                    try {
                                        const partForm = new FormData();
                                        partForm.append('record_id', dbRecordId);
                                        partForm.append('part_number', String(partNum));
                                        partForm.append('total_parts', String(totalParts));
                                        partForm.append('chunk', chunkBlob, file.name || `part_${partNum}.bin`);

                                        const partRes = await fetch('/api/schedule/chunked/part', { method: 'POST', body: partForm });
                                        const partData = await safeParseServerJson(partRes, `Upload Part ${partNum}`);
                                        if (partData && partData.status === 'cancelled') {
                                            delete window.activeBrowserUploadProgress[dbRecordId];
                                            await fetchScheduledPosts();
                                            return;
                                        }
                                        if (partRes.ok && partData.status === 'success') {
                                            partSuccess = true;
                                            const tracked = scheduledPostsList.find(p => p.id === dbRecordId);
                                            if (tracked && partData.status_message) {
                                                tracked.status_message = partData.status_message;
                                                renderQueue();
                                            }
                                            break;
                                        }
                                        lastPartErr = partData.message || `HTTP ${partRes.status}`;
                                    } catch (chunkErr) {
                                        lastPartErr = chunkErr.message || String(chunkErr);
                                    }
                                    if (attempt < 3) {
                                        await new Promise(r => setTimeout(r, 2000 * attempt));
                                    }
                                }
                            }

                            if (!partSuccess) {
                                throw new Error(`Part ${partNum}/${totalParts} failed after retries: ${lastPartErr}`);
                            }
                        }
                    }

                    delete window.activeBrowserUploadProgress[dbRecordId];

                    const compForm = new FormData();
                    compForm.append('record_id', dbRecordId);
                    if (uploadedDirectlyToZernio && zernioPublicUrl) {
                        compForm.append('zernio_public_url', zernioPublicUrl);
                    }
                    if (collectedPartSha1s.length > 0) {
                        compForm.append('part_sha1_json', JSON.stringify(collectedPartSha1s));
                    }

                    const compRes = await fetch('/api/schedule/chunked/complete', { method: 'POST', body: compForm });
                    const compData = await safeParseServerJson(compRes, 'Finalize Upload');
                    if (!compRes.ok || (compData.status !== 'success' && compData.status !== 'cancelled')) {
                        throw new Error(compData.message || `Failed to finalize upload (${compRes.status})`);
                    }

                    await fetchScheduledPosts();
                } catch (err) {
                    console.error("Direct Video Upload Error:", err);
                    if (dbRecordId) {
                        delete window.activeBrowserUploadProgress[dbRecordId];
                        try {
                            const failForm = new FormData();
                            failForm.append('record_id', dbRecordId);
                            failForm.append('error_message', err.message || String(err));
                            await fetch('/api/schedule/chunked/fail', { method: 'POST', body: failForm });
                        } catch (_) {}
                        await fetchScheduledPosts();
                    } else {
                        const optItem = optimisticProcessingPosts.find(item => item.id === job.tempId);
                        if (optItem) {
                            optItem.status = 'failed';
                            optItem.status_message = `Upload Failed: ${err.message || err}`;
                            renderCalendar();
                            renderQueue();
                        }
                    }
                    showToast(`⚠️ Video Upload Error (${job.platform.toUpperCase()}): ${err.message || err}`);
                }
            }

            // NON-BLOCKING INSTANT BACKGROUND QUEUE MODE (Default ON in Settings)
            if (userSettings.instantBackgroundQueue) {
                const optimisticItems = batchJobs.map(j => buildOptimisticPayloadItem(j));
                optimisticProcessingPosts.unshift(...optimisticItems);
                syncQueueBadgeCount();
                renderCalendar();
                renderQueue();
                ensurePayloadProcessingPoll();

                if (userSettings.autoClearAfterLaunch) {
                    clearCurrentBatchInputsAfterLaunch(batchJobs.map(j => j.platform));
                }

                showToast(`🚀 ${batchJobs.length} post(s) sent to Queue & Calendar ("Processing Payload")! Direct-Uploading to External API Media Cloud.`);

                // Transmit each payload in the background without locking the Create Post button
                (async () => {
                    for (const job of batchJobs) {
                        await transmitScheduledJobResilient(job);
                    }
                })();
                return;
            }

            // Classic Synchronous Fallback (if user turned OFF Instant Background Queue in Settings)
            const submitBtn = document.getElementById('submit-btn');
            const originalText = submitBtn.innerHTML;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Launching...';
            submitBtn.disabled = true;

            for (const job of batchJobs) {
                await transmitScheduledJobResilient(job);
            }

            await fetchScheduledPosts();
            submitBtn.innerHTML = originalText;
            submitBtn.disabled = false;
            showToast("✅ Payload transmitted to Queue & Calendar!");
            switchTab('queue');
        }

        // =========================================================================
        // --- SOCIAL MEDIA ANALYTICS & PER-PAGE INSIGHTS ENGINE (ZERNIO API) ---
        // =========================================================================
        function formatCompactNumber(num) {
            const n = Number(num || 0);
            if (!Number.isFinite(n) || n <= 0) return '0';
            if (n >= 1000000) return (n / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
            if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'K';
            return n.toLocaleString();
        }

        function getPlatformDisplayMeta(platform) {
            const p = (platform || '').toLowerCase();
            if (p === 'facebook') {
                return {
                    label: 'Facebook',
                    icon: 'fab fa-facebook-f',
                    iconColor: 'text-blue-400',
                    badgeBg: 'bg-blue-600',
                    pillActive: 'bg-blue-600/25 border-blue-400 text-white shadow-[0_0_12px_rgba(37,99,235,0.3)]',
                    accentBorder: 'hover:border-blue-500/60',
                    barColor: 'bg-blue-500'
                };
            }
            if (p === 'instagram') {
                return {
                    label: 'Instagram',
                    icon: 'fab fa-instagram',
                    iconColor: 'text-pink-400',
                    badgeBg: 'bg-gradient-to-tr from-yellow-400 via-red-500 to-purple-500',
                    pillActive: 'bg-pink-600/25 border-pink-400 text-white shadow-[0_0_12px_rgba(236,72,153,0.3)]',
                    accentBorder: 'hover:border-pink-500/60',
                    barColor: 'bg-pink-500'
                };
            }
            if (p === 'tiktok') {
                return {
                    label: 'TikTok',
                    icon: 'fab fa-tiktok',
                    iconColor: 'text-gb-cyan',
                    badgeBg: 'bg-slate-900 border border-slate-600',
                    pillActive: 'bg-gb-cyan/20 border-gb-cyan text-gb-cyan shadow-[0_0_12px_rgba(0,240,255,0.25)]',
                    accentBorder: 'hover:border-gb-cyan/60',
                    barColor: 'bg-gb-cyan'
                };
            }
            if (p === 'youtube') {
                return {
                    label: 'YouTube',
                    icon: 'fab fa-youtube',
                    iconColor: 'text-red-500',
                    badgeBg: 'bg-red-600',
                    pillActive: 'bg-red-600/25 border-red-400 text-white shadow-[0_0_12px_rgba(220,38,38,0.3)]',
                    accentBorder: 'hover:border-red-500/60',
                    barColor: 'bg-red-500'
                };
            }
            return {
                label: (platform || 'Social').toUpperCase(),
                icon: 'fas fa-share-alt',
                iconColor: 'text-gb-cyan',
                badgeBg: 'bg-slate-800',
                pillActive: 'bg-gb-cyan/20 border-gb-cyan text-gb-cyan',
                accentBorder: 'hover:border-gb-cyan/60',
                barColor: 'bg-gb-cyan'
            };
        }

        let analyticsFollowupTimer = null;

        async function fetchAnalyticsData(forceRefresh = false) {
            const syncIcon = document.getElementById('sync-analytics-icon');
            if (syncIcon && forceRefresh) syncIcon.classList.add('fa-spin');

            const periodEl = document.getElementById('analytics-filter-period');
            const periodVal = periodEl ? periodEl.value : (analyticsDataState.period || '90d');

            if (isAnalyticsLoading && !forceRefresh) return;
            isAnalyticsLoading = true;

            const pagesGrid = document.getElementById('analytics-pages-grid');
            if (pagesGrid && (!analyticsDataState.pages || analyticsDataState.pages.length === 0)) {
                pagesGrid.innerHTML = `
                    <div class="col-span-full flex flex-col items-center justify-center py-10 text-slate-400">
                        <i class="fas fa-circle-notch fa-spin text-2xl text-gb-cyan mb-2"></i>
                        <p class="text-xs">Loading analytics snapshot...</p>
                    </div>
                `;
            }

            try {
                const res = await fetch(`/api/analytics?period=${encodeURIComponent(periodVal)}&force=${forceRefresh ? 'true' : 'false'}`);
                const data = await res.json();
                if (data.status === 'success') {
                    analyticsDataState = {
                        period: data.period || periodVal,
                        updated_at: data.updated_at || '',
                        syncing_external: Boolean(data.syncing_external),
                        connected_platforms: data.connected_platforms || [],
                        summary: data.summary || {},
                        pages: data.pages || [],
                        posts: data.posts || []
                    };

                    const navBadge = document.getElementById('analytics-pages-badge');
                    if (navBadge) navBadge.textContent = analyticsDataState.pages.length;

                    const updatedEl = document.getElementById('analytics-last-updated');
                    if (updatedEl) {
                        if (analyticsDataState.syncing_external) {
                            updatedEl.innerHTML = `<span class="text-gb-cyan font-semibold"><i class="fas fa-sync-alt fa-spin mr-1"></i>Syncing live External API metrics...</span>`;
                        } else if (analyticsDataState.updated_at) {
                            updatedEl.textContent = `• Updated ${analyticsDataState.updated_at}`;
                        }
                    }

                    // Validate current platform & page filters against connected pages
                    if (analyticsSelectedPlatform !== 'all' && !analyticsDataState.connected_platforms.includes(analyticsSelectedPlatform)) {
                        analyticsSelectedPlatform = 'all';
                    }
                    if (analyticsSelectedPageKey !== 'all') {
                        const pageExists = analyticsDataState.pages.some(p => p.page_key === analyticsSelectedPageKey);
                        if (!pageExists) analyticsSelectedPageKey = 'all';
                    }

                    renderAnalyticsView();
                    if (forceRefresh) {
                        showToast(`📊 Synced Analytics across ${analyticsDataState.pages.length} connected page(s)!`);
                    }

                    if (analyticsFollowupTimer) {
                        clearTimeout(analyticsFollowupTimer);
                        analyticsFollowupTimer = null;
                    }
                    if (analyticsDataState.syncing_external) {
                        analyticsFollowupTimer = setTimeout(() => {
                            fetchAnalyticsData(false);
                        }, 2500);
                    }
                }
            } catch (e) {
                console.error("Error fetching analytics:", e);
            } finally {
                isAnalyticsLoading = false;
                if (syncIcon) syncIcon.classList.remove('fa-spin');
            }
        }

        function onAnalyticsPeriodChange() {
            fetchAnalyticsData(false);
        }

        function setAnalyticsPlatformFilter(platform) {
            analyticsSelectedPlatform = platform || 'all';
            if (analyticsSelectedPageKey !== 'all') {
                const pg = (analyticsDataState.pages || []).find(p => p.page_key === analyticsSelectedPageKey);
                if (!pg || (analyticsSelectedPlatform !== 'all' && pg.platform !== analyticsSelectedPlatform)) {
                    analyticsSelectedPageKey = 'all';
                }
            }
            renderAnalyticsView();
        }

        function onAnalyticsPageFilterChange() {
            const sel = document.getElementById('analytics-filter-page');
            if (!sel) return;
            analyticsSelectedPageKey = sel.value || 'all';
            if (analyticsSelectedPageKey !== 'all') {
                const pg = (analyticsDataState.pages || []).find(p => p.page_key === analyticsSelectedPageKey);
                if (pg && analyticsSelectedPlatform !== 'all' && pg.platform !== analyticsSelectedPlatform) {
                    analyticsSelectedPlatform = pg.platform;
                }
            }
            renderAnalyticsView();
        }

        function selectAnalyticsPageCard(pageKey) {
            if (analyticsSelectedPageKey === pageKey) {
                analyticsSelectedPageKey = 'all';
            } else {
                analyticsSelectedPageKey = pageKey;
            }
            renderAnalyticsView();
        }

        function resetAnalyticsFilters() {
            analyticsSelectedPlatform = 'all';
            analyticsSelectedPageKey = 'all';
            const searchEl = document.getElementById('analytics-post-search');
            if (searchEl) searchEl.value = '';
            renderAnalyticsView();
        }

        function populateAnalyticsFilterControls() {
            const allPages = analyticsDataState.pages || [];
            const pillContainer = document.getElementById('analytics-platform-buttons-container');
            const filterIndicator = document.getElementById('analytics-active-filter-indicator');
            const pageSelect = document.getElementById('analytics-filter-page');

            if (pillContainer) {
                const platformsOrder = ['facebook', 'instagram', 'tiktok', 'youtube'];
                const countsByPlat = { facebook: 0, instagram: 0, tiktok: 0, youtube: 0 };
                allPages.forEach(p => {
                    if (countsByPlat[p.platform] !== undefined) countsByPlat[p.platform]++;
                });

                const isAllActive = analyticsSelectedPlatform === 'all';
                let pillsHTML = `
                    <button type="button" onclick="setAnalyticsPlatformFilter('all')"
                        class="px-3 py-1.5 rounded-xl text-xs font-semibold border transition-all inline-flex items-center gap-2 ${isAllActive ? 'bg-gb-cyan/20 border-gb-cyan text-gb-cyan shadow-[0_0_12px_rgba(0,240,255,0.2)]' : 'bg-slate-900/80 border-slate-700 text-slate-300 hover:text-white hover:border-slate-500'}">
                        <i class="fas fa-globe"></i>
                        <span>All Connected</span>
                        <span class="px-1.5 py-0.2 rounded-full text-[10px] font-bold ${isAllActive ? 'bg-gb-cyan text-slate-950' : 'bg-slate-800 text-slate-300'}">${allPages.length}</span>
                    </button>
                `;

                platformsOrder.forEach(plat => {
                    const count = countsByPlat[plat] || 0;
                    const meta = getPlatformDisplayMeta(plat);
                    const isActive = analyticsSelectedPlatform === plat;
                    const isConnected = count > 0;

                    pillsHTML += `
                        <button type="button" onclick="setAnalyticsPlatformFilter('${plat}')"
                            class="px-3 py-1.5 rounded-xl text-xs font-semibold border transition-all inline-flex items-center gap-2 ${isActive ? meta.pillActive : (isConnected ? 'bg-slate-900/80 border-slate-700 text-slate-300 hover:text-white hover:border-slate-500' : 'bg-slate-900/40 border-slate-800 text-slate-500 hover:text-slate-300')}">
                            <i class="${meta.icon} ${isActive ? 'text-white' : meta.iconColor}"></i>
                            <span>${meta.label}</span>
                            <span class="px-1.5 py-0.2 rounded-full text-[10px] font-bold ${isActive ? 'bg-white/20 text-white' : 'bg-slate-800 text-slate-400'}">${count}</span>
                        </button>
                    `;
                });

                pillContainer.innerHTML = pillsHTML;
            }

            if (pageSelect) {
                const candidatePages = analyticsSelectedPlatform === 'all'
                    ? allPages
                    : allPages.filter(p => p.platform === analyticsSelectedPlatform);

                let optsHTML = `<option value="all">${analyticsSelectedPlatform === 'all' ? `All Connected Social Media Pages (${allPages.length})` : `All ${getPlatformDisplayMeta(analyticsSelectedPlatform).label} Pages (${candidatePages.length})`}</option>`;
                candidatePages.forEach(p => {
                    const meta = getPlatformDisplayMeta(p.platform);
                    const selAttr = (p.page_key === analyticsSelectedPageKey) ? 'selected' : '';
                    optsHTML += `<option value="${escapeHTML(p.page_key)}" ${selAttr}>[${meta.label}] ${escapeHTML(p.account_name)}</option>`;
                });
                pageSelect.innerHTML = optsHTML;
            }

            if (filterIndicator) {
                if (analyticsSelectedPlatform !== 'all' || analyticsSelectedPageKey !== 'all') {
                    const activePage = allPages.find(p => p.page_key === analyticsSelectedPageKey);
                    const labelParts = [];
                    if (analyticsSelectedPlatform !== 'all') {
                        labelParts.push(getPlatformDisplayMeta(analyticsSelectedPlatform).label);
                    }
                    if (activePage) {
                        labelParts.push(activePage.account_name);
                    }
                    filterIndicator.innerHTML = `
                        <span class="text-slate-300 font-medium">Filtering: <strong class="text-gb-cyan">${escapeHTML(labelParts.join(' • '))}</strong></span>
                        <button type="button" onclick="resetAnalyticsFilters()" class="px-2 py-0.5 rounded-md bg-slate-800 hover:bg-rose-950/80 border border-slate-600 hover:border-rose-500/50 text-slate-300 hover:text-rose-200 text-[10px] font-semibold transition-all">
                            <i class="fas fa-times mr-1"></i>Reset Filter
                        </button>
                    `;
                } else {
                    filterIndicator.innerHTML = `<span class="text-slate-400">Showing all connected accounts across ${analyticsDataState.connected_platforms.length} platform(s)</span>`;
                }
            }
        }

        function renderAnalyticsView() {
            populateAnalyticsFilterControls();

            const allPages = analyticsDataState.pages || [];
            const filteredPages = allPages.filter(p => {
                if (analyticsSelectedPlatform !== 'all' && p.platform !== analyticsSelectedPlatform) return false;
                if (analyticsSelectedPageKey !== 'all' && p.page_key !== analyticsSelectedPageKey) return false;
                return true;
            });

            // Compute dynamic KPI totals for the currently filtered pages
            const totals = filteredPages.reduce((acc, p) => {
                acc.views += Number(p.views || 0);
                acc.impressions += Number(p.impressions || 0);
                acc.reach += Number(p.reach || 0);
                acc.likes += Number(p.likes || 0);
                acc.comments += Number(p.comments || 0);
                acc.unread_comments += Number(p.unread_comments_count || 0);
                acc.shares += Number(p.shares || 0);
                acc.saves += Number(p.saves || 0);
                acc.clicks += Number(p.clicks || 0);
                acc.engagement += Number(p.total_engagement || 0);
                acc.published += Number(p.published_posts_count || 0);
                acc.waiting += Number(p.scheduled_waiting_count || 0);
                acc.followers += Number(p.followers || 0);
                acc.messages += Number(p.messages_count || 0);
                return acc;
            }, {
                views: 0, impressions: 0, reach: 0, likes: 0, comments: 0, unread_comments: 0,
                shares: 0, saves: 0, clicks: 0, engagement: 0, published: 0, waiting: 0,
                followers: 0, messages: 0
            });

            const denom = Math.max(totals.impressions, totals.views);
            const engRate = (denom > 0 && totals.engagement > 0)
                ? ((totals.engagement / denom) * 100).toFixed(2)
                : '0.00';

            // 1. Render KPI Cards
            const kpiGrid = document.getElementById('analytics-kpi-grid');
            if (kpiGrid) {
                kpiGrid.innerHTML = `
                    <div class="p-3.5 rounded-xl bg-slate-900/80 border border-slate-700/80 flex flex-col justify-between">
                        <div class="flex items-center justify-between text-xs text-slate-400 mb-1">
                            <span class="font-semibold uppercase tracking-wider text-[10px]">Views & Reach</span>
                            <span class="w-7 h-7 rounded-lg bg-gb-cyan/15 border border-gb-cyan/30 flex items-center justify-center text-gb-cyan">
                                <i class="fas fa-eye text-xs"></i>
                            </span>
                        </div>
                        <div class="text-xl sm:text-2xl font-bold text-white tracking-tight">${formatCompactNumber(totals.views)}</div>
                        <div class="mt-1.5 flex items-center justify-between text-[11px] text-slate-400">
                            <span>Impressions: <strong class="text-slate-200">${formatCompactNumber(totals.impressions)}</strong></span>
                            ${totals.followers > 0 ? `<span class="text-gb-cyan font-semibold" title="Total Followers / Subscribers"><i class="fas fa-users mr-1"></i>${formatCompactNumber(totals.followers)}</span>` : ''}
                        </div>
                    </div>

                    <div class="p-3.5 rounded-xl bg-slate-900/80 border border-slate-700/80 flex flex-col justify-between">
                        <div class="flex items-center justify-between text-xs text-slate-400 mb-1">
                            <span class="font-semibold uppercase tracking-wider text-[10px]">Total Engagement</span>
                            <span class="w-7 h-7 rounded-lg bg-purple-500/15 border border-purple-500/30 flex items-center justify-center text-purple-300">
                                <i class="fas fa-bolt text-xs"></i>
                            </span>
                        </div>
                        <div class="flex items-baseline gap-2">
                            <span class="text-xl sm:text-2xl font-bold text-white tracking-tight">${formatCompactNumber(totals.engagement)}</span>
                            <span class="text-[11px] font-bold px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">${engRate}% ER</span>
                        </div>
                        <div class="mt-1.5 text-[11px] text-slate-400 truncate">
                            Shares: <strong class="text-slate-200">${formatCompactNumber(totals.shares)}</strong> • Saves: <strong class="text-slate-200">${formatCompactNumber(totals.saves)}</strong>
                        </div>
                    </div>

                    <div class="p-3.5 rounded-xl bg-slate-900/80 border border-slate-700/80 flex flex-col justify-between">
                        <div class="flex items-center justify-between text-xs text-slate-400 mb-1">
                            <span class="font-semibold uppercase tracking-wider text-[10px]">Likes & Reactions</span>
                            <span class="w-7 h-7 rounded-lg bg-rose-500/15 border border-rose-500/30 flex items-center justify-center text-rose-400">
                                <i class="fas fa-heart text-xs"></i>
                            </span>
                        </div>
                        <div class="text-xl sm:text-2xl font-bold text-white tracking-tight">${formatCompactNumber(totals.likes)}</div>
                        <div class="mt-1.5 text-[11px] text-slate-400">
                            Avg <strong class="text-slate-200">${totals.published > 0 ? Math.round(totals.likes / totals.published).toLocaleString() : 0}</strong> likes / post
                        </div>
                    </div>

                    <div class="p-3.5 rounded-xl bg-slate-900/80 border border-slate-700/80 flex flex-col justify-between">
                        <div class="flex items-center justify-between text-xs text-slate-400 mb-1">
                            <span class="font-semibold uppercase tracking-wider text-[10px]">Comments & Replies</span>
                            <span class="w-7 h-7 rounded-lg bg-amber-500/15 border border-amber-500/30 flex items-center justify-center text-amber-400">
                                <i class="fas fa-comments text-xs"></i>
                            </span>
                        </div>
                        <div class="flex items-baseline gap-2">
                            <span class="text-xl sm:text-2xl font-bold text-white tracking-tight">${formatCompactNumber(totals.comments)}</span>
                            ${totals.unread_comments > 0 ? `<span class="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-rose-500 text-white">${totals.unread_comments} new</span>` : ''}
                        </div>
                        <div class="mt-1.5 text-[11px] text-slate-400">
                            Active DMs: <strong class="text-gb-cyan">${totals.messages}</strong> chat(s)
                        </div>
                    </div>

                    <div class="p-3.5 rounded-xl bg-slate-900/80 border border-slate-700/80 flex flex-col justify-between col-span-2 sm:col-span-1">
                        <div class="flex items-center justify-between text-xs text-slate-400 mb-1">
                            <span class="font-semibold uppercase tracking-wider text-[10px]">Published Posts</span>
                            <span class="w-7 h-7 rounded-lg bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                                <i class="fas fa-check-double text-xs"></i>
                            </span>
                        </div>
                        <div class="flex items-baseline gap-2">
                            <span class="text-xl sm:text-2xl font-bold text-white tracking-tight">${totals.published}</span>
                            <span class="text-xs text-slate-400">across <strong class="text-gb-cyan">${filteredPages.length}</strong> page(s)</span>
                        </div>
                        <div class="mt-1.5 text-[11px] text-slate-400">
                            In Queue: <strong class="text-amber-300">${totals.waiting}</strong> scheduled
                        </div>
                    </div>
                `;
            }

            // 2. Render Per-Social Media Page Cards
            const pagesSectionCount = document.getElementById('analytics-pages-section-count');
            if (pagesSectionCount) {
                pagesSectionCount.textContent = `${filteredPages.length} Page${filteredPages.length === 1 ? '' : 's'}`;
            }

            const pagesGrid = document.getElementById('analytics-pages-grid');
            if (pagesGrid) {
                if (allPages.length === 0) {
                    pagesGrid.innerHTML = `
                        <div class="col-span-full p-8 rounded-2xl bg-slate-900/60 border border-dashed border-slate-700 text-center space-y-3">
                            <div class="w-12 h-12 rounded-2xl bg-gb-cyan/10 border border-gb-cyan/30 flex items-center justify-center text-gb-cyan mx-auto">
                                <i class="fas fa-plug text-xl"></i>
                            </div>
                            <div>
                                <h4 class="text-sm font-bold text-white">No Connected Social Media Pages Found</h4>
                                <p class="text-xs text-slate-400 mt-1 max-w-md mx-auto">Connect your Facebook, Instagram, TikTok, or YouTube accounts to view real-time External API analytics per page.</p>
                            </div>
                            <button type="button" onclick="openConnectAccountsModal('manage')" class="px-4 py-2 rounded-xl bg-gb-cyan/15 hover:bg-gb-cyan/25 border border-gb-cyan/50 text-gb-cyan text-xs font-bold inline-flex items-center gap-2 transition-all">
                                <i class="fas fa-plus-circle"></i> <span>Connect Social Media Accounts</span>
                            </button>
                        </div>
                    `;
                } else if (filteredPages.length === 0) {
                    pagesGrid.innerHTML = `
                        <div class="col-span-full p-6 rounded-xl bg-slate-900/60 border border-slate-800 text-center text-slate-400 text-xs">
                            No connected pages match the selected platform filter.
                            <button type="button" onclick="resetAnalyticsFilters()" class="text-gb-cyan underline ml-1 font-semibold">Show All Pages</button>
                        </div>
                    `;
                } else {
                    const maxEngagementAcrossPages = Math.max(1, ...filteredPages.map(p => (p.total_engagement || 0) + (p.views || 0)));

                    pagesGrid.innerHTML = filteredPages.map(p => {
                        const meta = getPlatformDisplayMeta(p.platform);
                        const isSelectedPage = (analyticsSelectedPageKey === p.page_key);
                        const avatarHTML = p.avatar_url
                            ? `<img src="${p.avatar_url}" class="w-11 h-11 rounded-xl object-cover border border-slate-600 shrink-0" onerror="this.outerHTML='<div class=\\'w-11 h-11 rounded-xl bg-slate-800 border border-slate-600 flex items-center justify-center text-sm font-bold text-gb-cyan shrink-0\\'><i class=\\'${meta.icon}\\'></i></div>'">`
                            : `<div class="w-11 h-11 rounded-xl bg-slate-800 border border-slate-600 flex items-center justify-center text-sm font-bold text-gb-cyan shrink-0"><i class="${meta.icon}"></i></div>`;

                        const handleText = (p.username && p.username.toLowerCase() !== p.account_name.toLowerCase())
                            ? `@${p.username.replace(/^@/, '')}`
                            : meta.label;

                        const activityScore = (p.total_engagement || 0) + (p.views || 0);
                        const barWidthPct = Math.min(100, Math.max(6, Math.round((activityScore / maxEngagementAcrossPages) * 100)));

                        const followersPill = p.followers > 0
                            ? `<span class="px-2 py-0.5 rounded-md bg-slate-950 border border-slate-800 text-[10px] font-semibold text-gb-cyan" title="Followers / Subscribers">
                                   <i class="fas fa-users mr-1"></i>${formatCompactNumber(p.followers)}
                                   ${p.follower_growth > 0 ? `<span class="text-emerald-400 ml-0.5">+${p.follower_growth}</span>` : ''}
                               </span>`
                            : '';

                        return `
                            <div onclick="selectAnalyticsPageCard('${escapeHTML(p.page_key)}')"
                                 class="p-4 rounded-2xl border transition-all cursor-pointer flex flex-col justify-between gap-3.5 ${isSelectedPage ? 'bg-slate-800/95 border-gb-cyan shadow-[0_0_20px_rgba(0,240,255,0.2)]' : `bg-slate-900/80 border-slate-700/80 hover:bg-slate-800/75 ${meta.accentBorder}`}">
                                <!-- Card Header: Avatar + Page Name + Platform Badge -->
                                <div class="flex items-start justify-between gap-2.5">
                                    <div class="flex items-center gap-3 min-w-0">
                                        <div class="relative shrink-0">
                                            ${avatarHTML}
                                            <span class="absolute -bottom-1 -right-1 w-5 h-5 rounded-full ${meta.badgeBg} text-white text-[10px] flex items-center justify-center shadow">
                                                <i class="${meta.icon}"></i>
                                            </span>
                                        </div>
                                        <div class="min-w-0">
                                            <div class="flex items-center gap-1.5">
                                                <h4 class="text-xs sm:text-sm font-bold text-white truncate" title="${escapeHTML(p.account_name)}">${escapeHTML(p.account_name)}</h4>
                                                ${isSelectedPage ? `<span class="px-1.5 py-0.2 rounded bg-gb-cyan text-slate-950 text-[9px] font-extrabold uppercase shrink-0">Selected</span>` : ''}
                                            </div>
                                            <div class="flex items-center gap-1.5 flex-wrap mt-0.5">
                                                <span class="text-[11px] text-slate-400 truncate">${escapeHTML(handleText)}</span>
                                                <span class="text-slate-600">•</span>
                                                <span class="text-[10px] text-purple-300 font-medium">${escapeHTML(p.masked_key)}</span>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="flex flex-col items-end gap-1 shrink-0">
                                        ${followersPill}
                                        <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                                            ${Number(p.engagement_rate || 0).toFixed(1)}% ER
                                        </span>
                                    </div>
                                </div>

                                <!-- 4-Column Core Metrics Grid -->
                                <div class="grid grid-cols-4 gap-2 p-2.5 rounded-xl bg-slate-950/80 border border-slate-800/90 text-center">
                                    <div>
                                        <div class="text-[10px] text-slate-400 font-medium">Views</div>
                                        <div class="text-xs sm:text-sm font-bold text-gb-cyan mt-0.5">${formatCompactNumber(p.views)}</div>
                                    </div>
                                    <div class="border-l border-slate-800">
                                        <div class="text-[10px] text-slate-400 font-medium">Likes</div>
                                        <div class="text-xs sm:text-sm font-bold text-rose-400 mt-0.5">${formatCompactNumber(p.likes)}</div>
                                    </div>
                                    <div class="border-l border-slate-800">
                                        <div class="text-[10px] text-slate-400 font-medium">Comments</div>
                                        <div class="text-xs sm:text-sm font-bold text-amber-400 mt-0.5">${formatCompactNumber(p.comments)}</div>
                                    </div>
                                    <div class="border-l border-slate-800">
                                        <div class="text-[10px] text-slate-400 font-medium">Shares</div>
                                        <div class="text-xs sm:text-sm font-bold text-emerald-400 mt-0.5">${formatCompactNumber((p.shares || 0) + (p.saves || 0))}</div>
                                    </div>
                                </div>

                                <!-- Activity Bar & Secondary Stats -->
                                <div class="space-y-1.5">
                                    <div class="w-full h-1.5 rounded-full bg-slate-950 overflow-hidden border border-slate-800/80">
                                        <div class="h-full rounded-full ${meta.barColor} transition-all duration-300" style="width: ${barWidthPct}%"></div>
                                    </div>
                                    <div class="flex items-center justify-between text-[11px] text-slate-400">
                                        <div class="flex items-center gap-2.5">
                                            <span><i class="fas fa-check-circle text-emerald-400 mr-1"></i><strong class="text-slate-200">${p.published_posts_count}</strong> Published</span>
                                            ${p.scheduled_waiting_count > 0 ? `<span><i class="fas fa-clock text-amber-400 mr-1"></i><strong class="text-amber-300">${p.scheduled_waiting_count}</strong> Queued</span>` : ''}
                                            ${(p.platform === 'facebook' || p.platform === 'instagram') ? `<span><i class="fas fa-envelope text-gb-cyan mr-1"></i><strong class="text-slate-200">${p.messages_count || 0}</strong> DMs</span>` : ''}
                                        </div>
                                        <span class="text-[11px] font-semibold ${isSelectedPage ? 'text-gb-cyan' : 'text-slate-400'}">
                                            ${isSelectedPage ? '<i class="fas fa-filter mr-1"></i>Filtered' : 'Filter Posts <i class="fas fa-chevron-right text-[9px] ml-0.5"></i>'}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        `;
                    }).join('');
                }
            }

            // 3. Render Posts Breakdown Table
            renderAnalyticsPostsTable();
        }

        function renderAnalyticsPostsTable() {
            const container = document.getElementById('analytics-posts-container');
            const countBadge = document.getElementById('analytics-posts-section-count');
            if (!container) return;

            const searchVal = (document.getElementById('analytics-post-search')?.value || '').trim().toLowerCase();
            const sortVal = document.getElementById('analytics-post-sort')?.value || 'engagement';

            let posts = (analyticsDataState.posts || []).filter(post => {
                if (analyticsSelectedPlatform !== 'all' && post.platform !== analyticsSelectedPlatform) return false;
                if (analyticsSelectedPageKey !== 'all' && post.page_key !== analyticsSelectedPageKey) return false;
                if (searchVal) {
                    const hay = `${post.caption || ''} ${post.account_name || ''} ${post.platform || ''}`.toLowerCase();
                    if (!hay.includes(searchVal)) return false;
                }
                return true;
            });

            posts.sort((a, b) => {
                if (sortVal === 'views') return (b.views || 0) - (a.views || 0) || (b.total_engagement || 0) - (a.total_engagement || 0);
                if (sortVal === 'likes') return (b.likes || 0) - (a.likes || 0) || (b.views || 0) - (a.views || 0);
                if (sortVal === 'comments') return (b.comments || 0) - (a.comments || 0) || (b.views || 0) - (a.views || 0);
                if (sortVal === 'newest') return (b.published_iso || '').localeCompare(a.published_iso || '');
                return (b.total_engagement || 0) - (a.total_engagement || 0) || (b.views || 0) - (a.views || 0);
            });

            if (countBadge) {
                countBadge.textContent = `${posts.length} Post${posts.length === 1 ? '' : 's'}`;
            }

            if (posts.length === 0) {
                container.innerHTML = `
                    <div class="flex flex-col items-center justify-center py-12 px-4 text-center text-slate-400">
                        <i class="fas fa-chart-bar text-3xl text-slate-600 mb-2"></i>
                        <p class="text-xs sm:text-sm font-semibold text-slate-300">No published posts found for this filter.</p>
                        <p class="text-[11px] text-slate-500 mt-1">Publish a post or change the platform/page filter above to inspect post-level analytics.</p>
                    </div>
                `;
                return;
            }

            const rowsHTML = posts.map((p, idx) => {
                const captionText = p.caption ? escapeHTML(p.caption) : '<span class="italic text-slate-500">Media post (no caption)</span>';
                const openLinkHTML = p.permalink_url
                    ? `<a href="${p.permalink_url}" target="_blank" class="px-2.5 py-1 rounded-lg bg-gb-cyan/15 hover:bg-gb-cyan/30 border border-gb-cyan/40 text-gb-cyan text-[11px] font-semibold inline-flex items-center gap-1.5 whitespace-nowrap transition-all">
                           <i class="fas fa-external-link-alt text-[10px]"></i> <span>View Post</span>
                       </a>`
                    : `<span class="text-[11px] text-slate-500">Synced</span>`;

                return `
                    <tr class="border-b border-slate-800/80 hover:bg-slate-800/60 transition-colors">
                        <td class="py-3 px-3.5 text-xs font-bold text-slate-500">#${idx + 1}</td>
                        <td class="py-3 px-3.5 whitespace-nowrap">
                            <div class="flex items-center gap-2">
                                ${getPlatformBadge(p.platform)}
                                <div>
                                    <div class="text-xs font-bold text-white max-w-[170px] truncate" title="${escapeHTML(p.account_name)}">${escapeHTML(p.account_name)}</div>
                                    <div class="text-[10px] text-slate-400">${escapeHTML(p.display_date)}</div>
                                </div>
                            </div>
                        </td>
                        <td class="py-3 px-3.5 max-w-[280px]">
                            <p class="text-xs text-slate-200 line-clamp-2" title="${escapeHTML(p.caption || '')}">${captionText}</p>
                        </td>
                        <td class="py-3 px-3.5 text-right whitespace-nowrap">
                            <span class="text-xs font-bold text-gb-cyan">${formatCompactNumber(p.views)}</span>
                            ${p.impressions > p.views ? `<div class="text-[10px] text-slate-500">${formatCompactNumber(p.impressions)} imp</div>` : ''}
                        </td>
                        <td class="py-3 px-3.5 text-right whitespace-nowrap">
                            <span class="text-xs font-bold text-rose-400"><i class="fas fa-heart text-[10px] mr-1 opacity-75"></i>${formatCompactNumber(p.likes)}</span>
                        </td>
                        <td class="py-3 px-3.5 text-right whitespace-nowrap">
                            <span class="text-xs font-bold text-amber-400"><i class="fas fa-comment text-[10px] mr-1 opacity-75"></i>${formatCompactNumber(p.comments)}</span>
                        </td>
                        <td class="py-3 px-3.5 text-right whitespace-nowrap">
                            <span class="text-xs font-bold text-emerald-400">${formatCompactNumber((p.shares || 0) + (p.saves || 0))}</span>
                        </td>
                        <td class="py-3 px-3.5 text-right whitespace-nowrap">
                            <span class="px-2 py-0.5 rounded-full text-[11px] font-bold bg-purple-500/15 text-purple-300 border border-purple-500/30">
                                ${formatCompactNumber(p.total_engagement)} (${Number(p.engagement_rate || 0).toFixed(1)}%)
                            </span>
                        </td>
                        <td class="py-3 px-3.5 text-right whitespace-nowrap">
                            ${openLinkHTML}
                        </td>
                    </tr>
                `;
            }).join('');

            container.innerHTML = `
                <table class="w-full text-left border-collapse min-w-[780px]">
                    <thead>
                        <tr class="border-b border-slate-700 bg-slate-950/90 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                            <th class="py-2.5 px-3.5">#</th>
                            <th class="py-2.5 px-3.5">Social Media Page</th>
                            <th class="py-2.5 px-3.5">Post Caption / Title</th>
                            <th class="py-2.5 px-3.5 text-right">Views / Reach</th>
                            <th class="py-2.5 px-3.5 text-right">Likes</th>
                            <th class="py-2.5 px-3.5 text-right">Comments</th>
                            <th class="py-2.5 px-3.5 text-right">Shares/Saves</th>
                            <th class="py-2.5 px-3.5 text-right">Engagement</th>
                            <th class="py-2.5 px-3.5 text-right">Link</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rowsHTML}
                    </tbody>
                </table>
            `;
        }

