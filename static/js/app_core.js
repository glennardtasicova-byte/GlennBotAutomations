        let objectUrls = [];
        let fbPagesList = []; 
        let igPagesList = []; 
        let tiktokAccountsList = [];
        let youtubeAccountsList = [];
        let scheduledPostsList = [];
        let savedPresetsList = [];
        let commentsList = [];
        let knownCommentIds = new Set();
        let knownReplyIds = new Set();
        let pendingOptimisticReplies = {}; // keyed by comment_id -> array of optimistic reply objects
        let isInitialCommentsLoad = true;
        let selectedRecordId = null;
        let selectedCommentId = null;
        let lastRenderedThreadSignature = '';
        let livePostDetailsCache = {};
        let activeTab = 'scheduler';
        let currentModalDayKey = null;

        // --- UNIFIED INBOX & DIRECT MESSAGES STATE VARIABLES ---
        let messagesConversationsList = [];
        let messagesConnectedPagesSummary = [];
        let messagesPageLimits = {}; // { account_id: currentLimit } -> default 10 per Social Media Page, +10 on "See More"
        let selectedConversationKey = null;
        let selectedConversationId = null;
        let selectedConversationAccountId = null;
        let activeConversationObj = null;
        let activeConversationMessages = [];
        let pendingOptimisticMessages = {}; // keyed by conv_key -> array of optimistic message objects
        let knownMessageStateMap = new Map();
        let isInitialMessagesLoad = true;

        // --- SOCIAL MEDIA ANALYTICS STATE VARIABLES ---
        let analyticsDataState = {
            period: '90d',
            updated_at: '',
            connected_platforms: [],
            summary: {},
            pages: [],
            posts: []
        };
        let analyticsSelectedPlatform = 'all';
        let analyticsSelectedPageKey = 'all';
        let isAnalyticsLoading = false;

        function toggleLeftSidebar() {
            const sidebar = document.getElementById('left-nav-sidebar');
            const btn = document.getElementById('btn-toggle-sidebar');
            if (!sidebar) return;
            sidebar.classList.toggle('hidden');
            if (btn) {
                const isHidden = sidebar.classList.contains('hidden');
                btn.classList.toggle('bg-gb-cyan/20', !isHidden);
            }
        }

        let currentDraftState = {
            accounts: { facebook: '', instagram: '', tiktok: '', youtube: '' },
            titles: { youtube: '' },
            captions: { facebook: '', instagram: '', tiktok: '', youtube: '' },
            dates: { facebook: '', instagram: '', tiktok: '', youtube: '' },
            times: { facebook: '', instagram: '', tiktok: '', youtube: '' },
            mediaFiles: { facebook: null, instagram: null, tiktok: null, youtube: null },
            thumbFiles: { facebook: null, instagram: null, tiktok: null, youtube: null },
            vaultMediaItems: { facebook: null, instagram: null, tiktok: null, youtube: null },
            vaultThumbItems: { facebook: null, instagram: null, tiktok: null, youtube: null },
            lastPostType: 'reels'
        };

        const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

        function escapeHTML(str) {
            return String(str ?? '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }
        function escapeHtml(str) {
            return escapeHTML(str);
        }

        // =========================================================================
        // --- USER SETTINGS, FADE-IN/FADE-OUT MODALS & COIN.MP3 SOUND ENGINE ---
        // =========================================================================
        const DEFAULT_USER_SETTINGS = {
            theme: 'default', // 'default' | 'light' | 'dark'
            bandwidthSaverMode: true,
            instantBackgroundQueue: true,
            autoClearAfterLaunch: true,
            fadeEffects: true,
            popupNotifications: true,
            soundEffects: true,
            soundVolume: 85
        };

        let userSettings = Object.assign({}, DEFAULT_USER_SETTINGS);
        let activeSettingsAccountLabel = 'Client Account (.env)';
        let settingsCloudinarySaveTimer = null;
        let optimisticProcessingPosts = [];
        let toastHideTimer = null;
        let audioUnlocked = false;

        function getActiveSettingsStorageKey() {
            const u = window.gbCurrentAuthUser;
            if (u && u.is_admin) {
                const em = String(u.email || 'glennardtasico@gmail.com').trim().toLowerCase();
                return `glennbot_user_settings_v2_admin_${em}`;
            }
            if (u && u.user_id) {
                return `glennbot_user_settings_v2_client_${String(u.user_id).trim().toLowerCase()}`;
            }
            return 'glennbot_user_settings_v2_client_default';
        }

        function updateSettingsProfileBannerUI(accountLabel = '', syncState = 'synced') {
            if (accountLabel) {
                activeSettingsAccountLabel = accountLabel;
            } else if (window.gbCurrentAuthUser) {
                activeSettingsAccountLabel = window.gbCurrentAuthUser.is_admin
                    ? `Administrator (${window.gbCurrentAuthUser.email || 'glennardtasico@gmail.com'})`
                    : `Client (${window.gbCurrentAuthUser.user_id || '.env'})`;
            }
            const lblEl = document.getElementById('settings-active-profile-label');
            if (lblEl) {
                lblEl.textContent = activeSettingsAccountLabel;
            }
            const pillEl = document.getElementById('settings-cloudinary-sync-pill');
            if (pillEl) {
                if (syncState === 'saving') {
                    pillEl.className = 'px-2.5 py-0.5 rounded-full bg-amber-500/20 border border-amber-400/50 text-amber-300 text-[10px] font-bold shrink-0';
                    pillEl.innerHTML = '<i class="fas fa-circle-notch fa-spin mr-1"></i>Saving to Cloudinary...';
                } else {
                    pillEl.className = 'px-2.5 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-[10px] font-bold shrink-0';
                    pillEl.innerHTML = '<i class="fas fa-cloud-upload-alt mr-1"></i>Saved in Cloudinary';
                }
            }
        }

        async function loadUserSettings(preloadedServerSettings = null, preloadedProfileInfo = null) {
            try {
                const storageKey = getActiveSettingsStorageKey();
                const raw = localStorage.getItem(storageKey);
                if (raw) {
                    const parsed = JSON.parse(raw);
                    userSettings = Object.assign({}, DEFAULT_USER_SETTINGS, parsed || {});
                } else {
                    userSettings = Object.assign({}, DEFAULT_USER_SETTINGS);
                }
            } catch (e) {
                console.warn("Could not load user settings from localStorage:", e);
            }

            if (preloadedServerSettings && typeof preloadedServerSettings === 'object') {
                userSettings = Object.assign({}, DEFAULT_USER_SETTINGS, preloadedServerSettings);
                try {
                    localStorage.setItem(getActiveSettingsStorageKey(), JSON.stringify(userSettings));
                } catch (_) {}
            }
            if (preloadedProfileInfo && preloadedProfileInfo.account_label) {
                updateSettingsProfileBannerUI(preloadedProfileInfo.account_label, 'synced');
            } else {
                updateSettingsProfileBannerUI('', 'synced');
            }

            applyUserSettingsToDOM();

            // Fetch latest per-account settings from Cloudinary if not already provided
            if (!preloadedServerSettings && window.gbCurrentAuthUser) {
                try {
                    const res = await fetch('/api/user/settings');
                    const data = await res.json();
                    if (res.ok && data && data.status === 'success' && data.settings) {
                        userSettings = Object.assign({}, DEFAULT_USER_SETTINGS, data.settings);
                        try {
                            localStorage.setItem(getActiveSettingsStorageKey(), JSON.stringify(userSettings));
                        } catch (_) {}
                        updateSettingsProfileBannerUI(data.account_label || '', 'synced');
                        applyUserSettingsToDOM();
                    }
                } catch (err) {
                    console.warn("Could not fetch user settings from Cloudinary:", err);
                }
            }
        }

        function saveUserSettings(immediateCloudSync = false) {
            try {
                localStorage.setItem(getActiveSettingsStorageKey(), JSON.stringify(userSettings));
            } catch (e) {
                console.warn("Could not save user settings locally:", e);
            }
            applyUserSettingsToDOM();
            updateSettingsProfileBannerUI('', 'saving');

            if (settingsCloudinarySaveTimer) {
                clearTimeout(settingsCloudinarySaveTimer);
                settingsCloudinarySaveTimer = null;
            }
            const delayMs = immediateCloudSync ? 10 : 300;
            settingsCloudinarySaveTimer = setTimeout(async () => {
                try {
                    const res = await fetch('/api/user/settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ settings: userSettings })
                    });
                    const data = await res.json();
                    if (res.ok && data && data.status === 'success') {
                        updateSettingsProfileBannerUI(data.account_label || '', 'synced');
                    }
                } catch (err) {
                    console.warn("Cloudinary settings sync warning:", err);
                }
            }, delayMs);
        }

        function setDashboardTheme(themeName) {
            const cleanTheme = ['default', 'light', 'dark'].includes(String(themeName || '').toLowerCase())
                ? String(themeName).toLowerCase()
                : 'default';
            userSettings.theme = cleanTheme;
            saveUserSettings(true);
            const themeLabels = {
                'default': 'Default Theme (Cyber Neon)',
                'light': 'Light Mode (Crisp Daylight)',
                'dark': 'Dark Mode (Carbon Obsidian)'
            };
            const acctLabel = activeSettingsAccountLabel || 'your account';
            showToast(`🎨 Theme set to "${themeLabels[cleanTheme]}" & saved to Cloudinary for ${acctLabel}!`);
        }

        function applyUserSettingsToDOM() {
            const activeTheme = ['default', 'light', 'dark'].includes(String(userSettings.theme || '').toLowerCase())
                ? String(userSettings.theme).toLowerCase()
                : 'default';
            userSettings.theme = activeTheme;

            document.body.classList.toggle('gb-theme-light', activeTheme === 'light');
            document.body.classList.toggle('gb-theme-dark', activeTheme === 'dark');
            document.body.dataset.gbTheme = activeTheme;

            const themeBadge = document.getElementById('setting-active-theme-badge');
            const themeNamesMap = {
                'default': 'Default Theme (Cyber Neon)',
                'light': 'Light Mode (Crisp Daylight)',
                'dark': 'Dark Mode (Carbon Obsidian)'
            };
            if (themeBadge) {
                themeBadge.textContent = themeNamesMap[activeTheme] || 'Default Theme (Cyber Neon)';
            }

            ['default', 'light', 'dark'].forEach(tKey => {
                const cardEl = document.getElementById(`theme-card-${tKey}`);
                const chkEl = document.getElementById(`theme-check-${tKey}`);
                const isSelected = (tKey === activeTheme);
                if (cardEl) {
                    cardEl.className = isSelected
                        ? 'p-3 rounded-xl border-2 border-gb-cyan bg-slate-950/90 text-left transition-all flex flex-col justify-between gap-2 cursor-pointer shadow-[0_0_15px_rgba(0,240,255,0.2)]'
                        : 'p-3 rounded-xl border border-slate-700 bg-slate-950/90 hover:border-gb-cyan/60 text-left transition-all flex flex-col justify-between gap-2 cursor-pointer';
                }
                if (chkEl) {
                    chkEl.className = isSelected
                        ? 'text-[10px] font-extrabold text-gb-cyan uppercase'
                        : 'text-[10px] font-bold text-slate-400';
                    chkEl.textContent = isSelected ? '● Active' : 'Select';
                }
            });

            document.body.classList.toggle('gb-no-fade', !userSettings.fadeEffects);
            document.body.dataset.gbBandwidthSaver = userSettings.bandwidthSaverMode !== false ? 'on' : 'off';
            const toggleKeys = [
                'bandwidthSaverMode',
                'instantBackgroundQueue',
                'autoClearAfterLaunch',
                'fadeEffects',
                'popupNotifications',
                'soundEffects'
            ];
            toggleKeys.forEach(k => {
                const btn = document.getElementById(`setting-btn-${k}`);
                const knob = document.getElementById(`setting-knob-${k}`);
                const isOn = k === 'bandwidthSaverMode' ? (userSettings[k] !== false) : Boolean(userSettings[k]);
                if (btn) {
                    btn.className = `w-12 h-6 rounded-full transition-colors relative shrink-0 ${isOn ? 'bg-gb-cyan shadow-[0_0_10px_rgba(0,240,255,0.35)]' : 'bg-slate-700'}`;
                }
                if (knob) {
                    knob.className = `w-5 h-5 rounded-full bg-slate-950 shadow-md transform transition-transform absolute top-0.5 ${isOn ? 'translate-x-6' : 'translate-x-0.5'}`;
                }
            });

            const volSlider = document.getElementById('setting-sound-volume');
            const volLabel = document.getElementById('setting-sound-volume-label');
            const volVal = Math.max(10, Math.min(100, Number(userSettings.soundVolume || 85)));
            if (volSlider) volSlider.value = volVal;
            if (volLabel) volLabel.textContent = `${volVal}%`;

            const audioEl = document.getElementById('gb-notification-sound');
            if (audioEl) {
                audioEl.volume = volVal / 100;
            }
        }

        function toggleUserSetting(key) {
            if (!(key in userSettings) && key !== 'bandwidthSaverMode') return;
            userSettings[key] = !(userSettings[key] !== false && Boolean(userSettings[key]));
            saveUserSettings(true);
            if (key === 'soundEffects' && userSettings.soundEffects) {
                playNotificationSound(true);
            }
            if (key === 'bandwidthSaverMode') {
                if (typeof renderVaultFilesList === 'function') {
                    try { renderVaultFilesList(); } catch (_) {}
                }
                if (typeof renderCreatePostVaultModalList === 'function') {
                    try { renderCreatePostVaultModalList(); } catch (_) {}
                }
                showToast(
                    userSettings.bandwidthSaverMode
                        ? "🛡️ Bandwidth Saver Mode ON: Large video auto-streaming disabled (~0 MB preview mode)."
                        : "🎬 Bandwidth Saver Mode OFF: Live inline video previews enabled."
                );
            }
        }

        function updateSoundVolume(val) {
            userSettings.soundVolume = Math.max(10, Math.min(100, Number(val || 85)));
            saveUserSettings(false);
        }

        function resetUserSettingsToDefault() {
            userSettings = Object.assign({}, DEFAULT_USER_SETTINGS);
            saveUserSettings(true);
            showToast("⚙️ Settings & Theme restored to defaults (saved to Cloudinary)!");
        }

        function openSettingsModal() {
            updateSettingsProfileBannerUI('', 'synced');
            applyUserSettingsToDOM();
            openModalWithFade('settings-modal');
        }

        function closeSettingsModal() {
            closeModalWithFade('settings-modal');
        }

        // Unlock browser audio on first user gesture so background polling can play coin.mp3 freely
        function unlockBrowserAudioOnce() {
            if (audioUnlocked) return;
            audioUnlocked = true;
            const audioEl = document.getElementById('gb-notification-sound');
            if (audioEl) {
                const prevVol = audioEl.volume;
                audioEl.volume = 0.001;
                const p = audioEl.play();
                if (p && typeof p.then === 'function') {
                    p.then(() => {
                        audioEl.pause();
                        audioEl.currentTime = 0;
                        audioEl.volume = (Number(userSettings.soundVolume || 85) / 100);
                    }).catch(() => {
                        audioEl.volume = prevVol;
                    });
                }
            }
        }
        document.addEventListener('click', unlockBrowserAudioOnce, { once: true });

        function playSynthesizedCoinFallback(volumeRatio = 0.85) {
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (!AudioCtx) return;
                const ctx = new AudioCtx();
                const now = ctx.currentTime;
                const gain = ctx.createGain();
                gain.gain.setValueAtTime(0.001, now);
                gain.gain.exponentialRampToValueAtTime(Math.max(0.05, volumeRatio * 0.35), now + 0.015);
                gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.55);
                gain.connect(ctx.destination);

                // Classic dual-tone coin chime (B5 -> E6)
                const osc = ctx.createOscillator();
                osc.type = 'sine';
                osc.frequency.setValueAtTime(987.77, now);
                osc.frequency.setValueAtTime(1318.51, now + 0.085);
                osc.connect(gain);
                osc.start(now);
                osc.stop(now + 0.56);
            } catch (e) {
                console.warn("Audio fallback warning:", e);
            }
        }

        function playNotificationSound(isTest = false) {
            if (!isTest && !userSettings.soundEffects) return;
            const volRatio = Math.max(0.1, Math.min(1.0, Number(userSettings.soundVolume || 85) / 100));
            try {
                const soundClone = new Audio('/coin.mp3');
                soundClone.volume = volRatio;
                const playPromise = soundClone.play();
                if (playPromise && typeof playPromise.catch === 'function') {
                    playPromise.catch(() => {
                        // Fallback if coin.mp3 is not yet pushed to GitHub or blocked
                        playSynthesizedCoinFallback(volRatio);
                    });
                }
                if (isTest) {
                    showToast("🔊 Playing coin.mp3 notification sound!");
                }
            } catch (e) {
                playSynthesizedCoinFallback(volRatio);
            }
        }

        function openModalWithFade(modalId) {
            const modal = typeof modalId === 'string' ? document.getElementById(modalId) : modalId;
            if (!modal) return;
            if (modal._fadeOutTimer) {
                clearTimeout(modal._fadeOutTimer);
                modal._fadeOutTimer = null;
            }
            modal.classList.remove('hidden', 'gb-modal-backdrop-out');
            const innerBox = modal.firstElementChild;
            if (userSettings.fadeEffects) {
                modal.classList.add('gb-modal-backdrop-in');
                if (innerBox) {
                    innerBox.classList.remove('gb-fade-out');
                    innerBox.classList.add('gb-fade-in');
                }
            } else {
                modal.classList.remove('gb-modal-backdrop-in');
                if (innerBox) {
                    innerBox.classList.remove('gb-fade-in', 'gb-fade-out');
                }
            }
        }

        function closeModalWithFade(modalId, onAfterClose = null) {
            const modal = typeof modalId === 'string' ? document.getElementById(modalId) : modalId;
            if (!modal) return;
            const innerBox = modal.firstElementChild;
            if (!userSettings.fadeEffects) {
                modal.classList.add('hidden');
                if (typeof onAfterClose === 'function') onAfterClose();
                return;
            }
            modal.classList.remove('gb-modal-backdrop-in');
            modal.classList.add('gb-modal-backdrop-out');
            if (innerBox) {
                innerBox.classList.remove('gb-fade-in');
                innerBox.classList.add('gb-fade-out');
            }
            if (modal._fadeOutTimer) clearTimeout(modal._fadeOutTimer);
            modal._fadeOutTimer = setTimeout(() => {
                modal.classList.add('hidden');
                modal.classList.remove('gb-modal-backdrop-out');
                if (innerBox) innerBox.classList.remove('gb-fade-out');
                if (typeof onAfterClose === 'function') onAfterClose();
            }, 210);
        }

        function showToast(msg, durationMs = 3400) {
            const toast = document.getElementById('gb-toast');
            const textEl = document.getElementById('gb-toast-text');
            if (!toast || !textEl) return;
            textEl.textContent = msg;

            if (toastHideTimer) {
                clearTimeout(toastHideTimer);
                toastHideTimer = null;
            }
            if (toast._fadeOutTimer) {
                clearTimeout(toast._fadeOutTimer);
                toast._fadeOutTimer = null;
            }

            toast.classList.remove('hidden', 'gb-fade-out');
            if (userSettings.fadeEffects) {
                toast.classList.add('gb-fade-in');
            }

            toastHideTimer = setTimeout(() => {
                if (userSettings.fadeEffects) {
                    toast.classList.remove('gb-fade-in');
                    toast.classList.add('gb-fade-out');
                    toast._fadeOutTimer = setTimeout(() => {
                        toast.classList.add('hidden');
                        toast.classList.remove('gb-fade-out');
                    }, 220);
                } else {
                    toast.classList.add('hidden');
                }
            }, durationMs);
        }

        function triggerIncomingActivityAlert(info) {
            // 1. Play coin.mp3 sound effect if enabled in Settings
            if (userSettings.soundEffects) {
                playNotificationSound(false);
            }

            // 2. Show floating fade-in / fade-out pop-up notification if enabled in Settings
            if (!userSettings.popupNotifications) return;

            const stack = document.getElementById('gb-live-notification-stack');
            if (!stack) {
                showToast(info.fallbackText || "🔔 New activity received!");
                return;
            }

            const isComment = info.type === 'comment';
            const platMeta = getPlatformDisplayMeta(info.platform || 'facebook');
            const titleLabel = isComment
                ? `New ${platMeta.label} ${info.kind === 'reply' ? 'Reply' : 'Comment'}`
                : `New ${platMeta.label} Message`;
            const badgeIcon = isComment ? 'fa-comments text-gb-cyan' : 'fa-envelope text-emerald-400';

            const card = document.createElement('div');
            card.className = `pointer-events-auto glass-panel rounded-2xl p-3.5 border border-gb-cyan/60 shadow-[0_10px_30px_rgba(0,0,0,0.85),0_0_20px_rgba(0,240,255,0.28)] cursor-pointer hover:border-gb-cyan transition-all ${userSettings.fadeEffects ? 'gb-fade-in' : ''}`;
            card.innerHTML = `
                <div class="flex items-start justify-between gap-2.5">
                    <div class="flex items-start gap-2.5 min-w-0">
                        <div class="w-9 h-9 rounded-xl ${platMeta.badgeBg} flex items-center justify-center text-white shrink-0 shadow-md">
                            <i class="${platMeta.icon} text-sm"></i>
                        </div>
                        <div class="min-w-0 flex-1">
                            <div class="flex items-center gap-1.5">
                                <i class="fas ${badgeIcon} text-[11px]"></i>
                                <span class="text-xs font-bold text-white truncate">${escapeHTML(titleLabel)}</span>
                            </div>
                            <div class="text-[11px] text-gb-cyan font-semibold truncate mt-0.5">
                                ${escapeHTML(info.author || 'User')} ${info.accountName ? `<span class="text-slate-400 font-normal">• ${escapeHTML(info.accountName)}</span>` : ''}
                            </div>
                            <p class="text-xs text-slate-200 line-clamp-2 mt-1 italic">"${escapeHTML((info.text || '').slice(0, 90))}"</p>
                        </div>
                    </div>
                    <button type="button" class="text-slate-400 hover:text-white text-xs px-1" title="Dismiss">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            `;

            const dismissCard = () => {
                if (card._dismissed) return;
                card._dismissed = true;
                if (userSettings.fadeEffects) {
                    card.classList.remove('gb-fade-in');
                    card.classList.add('gb-fade-out');
                    setTimeout(() => { card.remove(); }, 220);
                } else {
                    card.remove();
                }
            };

            card.addEventListener('click', (e) => {
                if (e.target.closest('button')) {
                    e.stopPropagation();
                    dismissCard();
                    return;
                }
                if (isComment) {
                    switchTab('comments');
                    if (info.recordId && typeof openCommentNotification === 'function') {
                        openCommentNotification(info.recordId, info.commentId || '');
                    }
                } else {
                    switchTab('messages');
                    if (info.convKey && typeof openConversationThread === 'function') {
                        openConversationThread(info.convKey);
                    }
                }
                dismissCard();
            });

            stack.prepend(card);
            while (stack.children.length > 3) {
                stack.lastElementChild.remove();
            }
            setTimeout(dismissCard, 5200);
        }

        function openImageLightbox(url) {
            if (!url) return;
            const img = document.getElementById('lightbox-img');
            if (img) img.src = url;
            openModalWithFade('image-lightbox-modal');
        }

        function closeImageLightbox() {
            closeModalWithFade('image-lightbox-modal', () => {
                const img = document.getElementById('lightbox-img');
                if (img) img.src = '';
            });
        }

        // =========================================================================
        // --- MANAGE EXTERNAL API MODAL (HISTORY + BUFFER QUEUE + CLOUDINARY) ---
        // =========================================================================
        function showExternalApiErrorModal(errorMsg) {
            const textEl = document.getElementById('external-api-error-modal-text');
            if (textEl) textEl.textContent = errorMsg || "Could not retrieve or create an External API profile.";
            openModalWithFade('external-api-error-modal');
        }

        function closeExternalApiErrorModal() {
            closeModalWithFade('external-api-error-modal');
        }

        async function openManageApiModal() {
            closeExternalApiErrorModal();
            const input = document.getElementById('new-external-api-key-input');
            if (input) input.value = '';
            openModalWithFade('external-api-manager-modal');
            await loadExternalApiKeysHistory(true);
        }

        function closeManageApiModal() {
            closeModalWithFade('external-api-manager-modal');
        }

        function renderExternalApiKeysHistoryList(keysArray) {
            const container = document.getElementById('external-api-keys-list');
            const badge = document.getElementById('manage-api-total-badge');
            if (!container) return;

            const list = Array.isArray(keysArray) ? keysArray : [];
            if (badge) badge.textContent = `${list.length} Key${list.length === 1 ? '' : 's'}`;

            if (list.length === 0) {
                container.innerHTML = `
                    <div class="text-center py-8 px-4 rounded-xl bg-slate-900/60 border border-dashed border-slate-700 text-slate-400 text-xs">
                        <p>No External API keys found yet. Paste an API key above and click <strong>Add</strong>.</p>
                    </div>
                `;
                return;
            }

            container.innerHTML = list.map(item => {
                const isInUse = item.status === 'In use';
                const statusBadge = isInUse
                    ? `<span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 inline-flex items-center gap-1">
                           <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> In use
                       </span>`
                    : `<span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40 inline-flex items-center gap-1">
                           <i class="fas fa-layer-group text-[9px]"></i> Buffer
                       </span>`;

                const slotUsageBadge = item.is_full
                    ? `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-500/15 text-rose-300 border border-rose-500/30">${item.connected_count}/${item.max_limit} Accounts (Limit Reached)</span>`
                    : `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-gb-cyan/15 text-gb-cyan border border-gb-cyan/30">${item.connected_count}/${item.max_limit} Accounts Used</span>`;

                const accountsPills = (item.account_names && item.account_names.length > 0)
                    ? `<div class="flex flex-wrap gap-1.5 mt-2">
                           ${item.account_names.map(accName => `<span class="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-[10px] text-slate-300"><i class="fas fa-check-circle text-gb-cyan mr-1"></i>${escapeHTML(accName)}</span>`).join('')}
                       </div>`
                    : `<p class="text-[11px] text-slate-500 mt-1 italic">${isInUse ? 'Ready for new account connections' : 'Waiting in buffer — will auto-switch to "In use" once previous API reaches 2/2'}</p>`;

                const actionButtons = item.is_env
                    ? `<span class="px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-slate-400 text-[11px] font-semibold inline-flex items-center gap-1.5 select-none" title="Default .env API Key cannot be deleted">
                           <i class="fas fa-lock text-amber-400"></i> <span>Default (.env)</span>
                       </span>`
                    : `<div class="flex items-center gap-1.5">
                           ${!isInUse ? `
                               <button type="button" onclick="activateExternalApiKey('${item.id}')" class="px-2.5 py-1.5 rounded-lg bg-gb-cyan/15 hover:bg-gb-cyan/30 border border-gb-cyan/50 text-gb-cyan text-[11px] font-semibold transition-all" title="Mark as In Use now">
                                   Set In Use
                               </button>
                           ` : ''}
                           <button type="button" onclick="deleteExternalApiKey('${item.id}', '${escapeHTML(item.masked_key)}')" class="px-2.5 py-1.5 rounded-lg bg-rose-950/70 hover:bg-rose-600 border border-rose-500/60 text-rose-200 hover:text-white text-[11px] font-semibold inline-flex items-center gap-1 transition-all" title="Delete from Cloudinary">
                               <i class="fas fa-trash-alt text-[10px]"></i> <span>Delete</span>
                           </button>
                       </div>`;

                return `
                    <div class="p-3.5 rounded-xl border ${item.is_current_slot ? 'bg-slate-800/95 border-gb-cyan/60 shadow-[0_0_15px_rgba(0,240,255,0.12)]' : 'bg-slate-900/75 border-slate-700/80'} flex flex-col sm:flex-row sm:items-center justify-between gap-3 transition-all">
                        <div class="min-w-0 flex-1">
                            <div class="flex items-center gap-2 flex-wrap">
                                <span class="text-xs font-bold text-slate-400">#${item.order_index}</span>
                                <code class="text-xs sm:text-sm font-bold text-white bg-slate-950 px-2.5 py-0.5 rounded border border-slate-800">${escapeHTML(item.masked_key)}</code>
                                ${statusBadge}
                                ${slotUsageBadge}
                            </div>
                            ${accountsPills}
                            <div class="text-[10px] text-slate-500 mt-1.5">
                                Source: <span class="text-slate-400">${escapeHTML(item.added_at)}</span>
                            </div>
                        </div>
                        <div class="shrink-0 flex items-center justify-end">
                            ${actionButtons}
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function loadExternalApiKeysHistory(forceRefresh = true) {
            const container = document.getElementById('external-api-keys-list');
            if (container && forceRefresh) {
                container.innerHTML = `
                    <div class="text-center py-8 text-slate-400 text-xs">
                        <i class="fas fa-circle-notch fa-spin text-2xl text-gb-cyan mb-2"></i>
                        <p>Syncing API key history & usage from Cloudinary...</p>
                    </div>
                `;
            }
            try {
                const res = await fetch(`/api/external_api/keys?refresh=${forceRefresh ? 'true' : 'false'}`);
                const data = await res.json();
                if (data.status === 'success') {
                    renderExternalApiKeysHistoryList(data.keys || []);
                } else {
                    if (container) container.innerHTML = `<div class="text-center py-6 text-rose-400 text-xs">${escapeHTML(data.message || 'Failed to load API keys.')}</div>`;
                }
            } catch (e) {
                console.error("Load External API Keys error:", e);
                if (container) container.innerHTML = `<div class="text-center py-6 text-rose-400 text-xs">Network error while loading API keys.</div>`;
            }
        }

        async function addExternalApiKey() {
            const input = document.getElementById('new-external-api-key-input');
            const btn = document.getElementById('btn-add-external-api-key');
            if (!input || !btn) return;

            const apiKey = input.value.trim();
            if (!apiKey) {
                return alert("Please paste your External API Key before clicking Add.");
            }

            const origHTML = btn.innerHTML;
            btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> <span>Adding...</span>`;
            btn.disabled = true;

            try {
                const res = await fetch('/api/external_api/keys', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ api_key: apiKey })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    input.value = '';
                    renderExternalApiKeysHistoryList(data.keys || []);
                    showToast(`☁️ Added API Key (${data.masked_key}) to Cloudinary as "${data.assigned_status}"!`);
                    if (activeConnectModalTab === 'tiktok') {
                        scanTikTokAccountsToSelect(true);
                    } else if (activeConnectModalTab === 'youtube') {
                        scanYouTubeAccountsToSelect(true);
                    } else if (activeConnectModalTab === 'facebook' || activeConnectModalTab === 'instagram') {
                        scanMetaPagesToSelect(activeConnectModalTab, '');
                    }
                } else {
                    alert("❌ " + (data.message || "Failed to add External API Key."));
                }
            } catch (e) {
                console.error("Add External API Key error:", e);
                alert("❌ Network error while saving API Key to Cloudinary.");
            } finally {
                btn.innerHTML = origHTML;
                btn.disabled = false;
            }
        }

        async function activateExternalApiKey(keyId) {
            try {
                const res = await fetch(`/api/external_api/keys/${encodeURIComponent(keyId)}/activate`, { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success') {
                    renderExternalApiKeysHistoryList(data.keys || []);
                    showToast("✅ API Key is now tagged as 'In use'!");
                } else {
                    alert("❌ " + (data.message || "Could not activate API key."));
                }
            } catch (e) {
                console.error("Activate API key error:", e);
            }
        }

        async function deleteExternalApiKey(keyId, maskedKey) {
            if (!confirm(`Delete External API Key (${maskedKey}) from Cloudinary?\n\nAll social media accounts, scheduled/queued posts, comment notifications, and messages linked to this API key will also be removed automatically.`)) return;
            try {
                const res = await fetch(`/api/external_api/keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' });
                const data = await res.json();
                if (data.status === 'success') {
                    renderExternalApiKeysHistoryList(data.keys || []);
                    const removedCount = data.removed_accounts_count || 0;
                    showToast(`🗑️ Removed ${maskedKey} & ${removedCount} linked account(s)!`);

                    await fetchSocialAccounts();
                    await fetchScheduledPosts();
                    await fetchComments(false);
                    await fetchConversations(false);
                    fetchAnalyticsData(true);

                    const connModal = document.getElementById('connect-accounts-modal');
                    if (connModal && !connModal.classList.contains('hidden')) {
                        if (activeConnectModalTab === 'manage') {
                            await renderManageConnectedAccountsView();
                        } else if (activeConnectModalTab === 'facebook' || activeConnectModalTab === 'instagram') {
                            await scanMetaPagesToSelect(activeConnectModalTab, '');
                        } else if (activeConnectModalTab === 'tiktok') {
                            await scanTikTokAccountsToSelect(true);
                        } else if (activeConnectModalTab === 'youtube') {
                            await scanYouTubeAccountsToSelect(true);
                        }
                    }
                } else {
                    alert("❌ " + (data.message || "Could not delete API key."));
                }
            } catch (e) {
                console.error("Delete API key error:", e);
            }
        }

        function captureCurrentDraftState() {
            ['facebook', 'instagram', 'tiktok', 'youtube'].forEach(p => {
                const pageEl = document.getElementById(`page-${p}`);
                const titleEl = document.getElementById(`title-${p}`);
                const capEl = document.getElementById(`caption-${p}`);
                const dateEl = document.getElementById(`date-${p}`);
                const timeEl = document.getElementById(`time-${p}`);
                const mediaEl = document.getElementById(`media-${p}`);
                const thumbEl = document.getElementById(`thumb-${p}`);
                if (pageEl) currentDraftState.accounts[p] = pageEl.value;
                if (titleEl) {
                    if (!currentDraftState.titles) currentDraftState.titles = { youtube: '' };
                    currentDraftState.titles[p] = titleEl.value;
                }
                if (capEl) currentDraftState.captions[p] = capEl.value;
                if (dateEl) currentDraftState.dates[p] = dateEl.value;
                if (timeEl) currentDraftState.times[p] = timeEl.value;
                if (mediaEl && mediaEl.files && mediaEl.files.length > 0) {
                    currentDraftState.mediaFiles[p] = Array.from(mediaEl.files);
                }
                if (thumbEl && thumbEl.files && thumbEl.files.length > 0) {
                    currentDraftState.thumbFiles[p] = Array.from(thumbEl.files);
                }
            });
        }

        function onPlatformToggle() {
            captureCurrentDraftState();
            updatePreviews();
        }

        // --- DOCKED TAB BUTTONS BUILDER (Attached to the top of the first platform frame) ---
        function getDockedActionTabsHTML() {
            return `
                <div class="docked-tab-bar">
                    <button type="button" onclick="openAskAiModal()"
                        onmouseenter="showActionBubble(event, 'Ask AI (Gemini 3.5 Flash)', 'Explain your content idea and let Gemini generate titles, captions, and descriptions automatically.', 'text-purple-400')"
                        onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                        class="docked-tab-btn bg-purple-950/40 border-purple-500/50 text-purple-200 hover:text-white hover:border-purple-400">
                        <i class="fas fa-magic text-amber-300"></i> <span>Ask AI</span>
                    </button>
                    <button type="button" onclick="syncMediaToAllPlatforms()"
                        onmouseenter="showActionBubble(event, 'Use Same Media to All', 'Copy the uploaded Video, Cover, or Images to all selected platforms.')"
                        onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                        class="docked-tab-btn primary-tab">
                        <i class="fas fa-photo-video"></i> <span>Use Same Media to All Platforms</span>
                    </button>
                    <button type="button" onclick="syncCaptionAndTimeToAll()"
                        onmouseenter="showActionBubble(event, 'Sync Caption & Time', 'Sync the Caption, Date, and Time from the first card to all selected platforms.')"
                        onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                        class="docked-tab-btn">
                        <i class="fas fa-copy text-gb-cyan"></i> <span>Sync Caption & Time</span>
                    </button>
                    <button type="button" onclick="openLoadPresetModal()"
                        onmouseenter="showActionBubble(event, 'Load Custom Selection', 'Load a saved group of Social Media Pages/Accounts from Supabase.')"
                        onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                        class="docked-tab-btn">
                        <i class="fas fa-folder-open text-amber-400"></i> <span>Load Custom Selection</span>
                    </button>
                    <button type="button" onclick="saveCustomSelection()"
                        onmouseenter="showActionBubble(event, 'Save Custom Selection', 'Save the currently selected platforms and accounts as a preset for future posts.')"
                        onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                        class="docked-tab-btn">
                        <i class="fas fa-save text-emerald-400"></i> <span>Save Custom Selection</span>
                    </button>
                </div>
            `;
        }

        // --- FLOATING BUBBLE TOOLTIP FOR MEDIA ACTIONS (REPLACE / DELETE) & TOOLBAR ---
        function showActionBubble(event, titleText, descText, accentColor = 'text-gb-cyan') {
            const tooltip = document.getElementById('gb-tooltip');
            tooltip.innerHTML = `
                <div class="flex items-center gap-2 border-b border-slate-800 pb-1.5 mb-1.5">
                    <i class="fas fa-info-circle ${accentColor}"></i>
                    <span class="font-bold text-xs text-white">${titleText}</span>
                </div>
                <p class="text-[11px] text-slate-300 leading-relaxed">${descText}</p>
            `;
            tooltip.classList.remove('hidden');
            tooltip.classList.remove('opacity-0');
            movePostTooltip(event);
        }

        // --- CLEAR / DELETE MEDIA FUNCTION ---
        function clearMediaBox(inputId, containerId, type, event) {
            if (event) event.stopPropagation();
            hidePostTooltip();
            const input = document.getElementById(inputId);
            const container = document.getElementById(containerId);
            if (!input || !container) return;

            if (inputId.startsWith('thumb-')) {
                const plat = inputId.replace('thumb-', '');
                currentDraftState.thumbFiles[plat] = null;
                if (currentDraftState.vaultThumbItems) currentDraftState.vaultThumbItems[plat] = null;
            } else if (inputId.startsWith('media-')) {
                const plat = inputId.replace('media-', '');
                currentDraftState.mediaFiles[plat] = null;
                if (currentDraftState.vaultMediaItems) currentDraftState.vaultMediaItems[plat] = null;
            }

            input.value = '';
            container.innerHTML = '';
            const wrapper = input.closest('.media-box');
            if (wrapper) wrapper.classList.remove('has-media');
            showToast("🗑️ Media removed.");
        }

        function removeSingleGridImage(inputId, containerId, fileIndex, event) {
            if (event) event.stopPropagation();
            hidePostTooltip();
            const input = document.getElementById(inputId);
            if (!input) return;

            if (inputId.startsWith('media-')) {
                const plat = inputId.replace('media-', '');
                const vaultArr = currentDraftState.vaultMediaItems && currentDraftState.vaultMediaItems[plat];
                if (Array.isArray(vaultArr) && vaultArr.length > 0) {
                    const updatedVault = vaultArr.filter((_, idx) => idx !== fileIndex);
                    currentDraftState.vaultMediaItems[plat] = updatedVault.length > 0 ? updatedVault : null;
                    handleMediaPreview(input, containerId, 'grid');
                    showToast("🗑️ Vault image removed from album.");
                    return;
                }
            }

            if (!input.files) return;
            const dt = new DataTransfer();
            Array.from(input.files).forEach((file, idx) => {
                if (idx !== fileIndex) dt.items.add(file);
            });
            input.files = dt.files;
            if (inputId.startsWith('media-')) {
                const plat = inputId.replace('media-', '');
                currentDraftState.mediaFiles[plat] = dt.files.length > 0 ? Array.from(dt.files) : null;
            }
            handleMediaPreview(input, containerId, 'grid');
            showToast("🗑️ Image removed from album.");
        }

        // --- 1. USE SAME MEDIA TO ALL PLATFORMS ---
        function syncMediaToAllPlatforms() {
            hidePostTooltip();
            captureCurrentDraftState();
            const checkedBoxes = Array.from(document.querySelectorAll('input[name="platform"]:checked'));
            if (checkedBoxes.length < 2) {
                return alert("Please select at least two social media platforms on the left to use 'Use Same Media to All Platforms'.");
            }

            const postType = document.querySelector('input[name="post_type"]:checked').value;
            if (postType === 'text') {
                return alert("You are currently in Text Post format. Please select Reels, 16:9 Video, or Image format to sync media.");
            }

            let sourcePlatform = null;
            let sourceMediaFiles = null;
            let sourceVaultMedia = null;
            let sourceThumbFiles = null;
            let sourceVaultThumb = null;

            for (let box of checkedBoxes) {
                const p = box.value;
                const mediaInput = document.getElementById(`media-${p}`);
                const thumbInput = document.getElementById(`thumb-${p}`);
                const mFiles = (mediaInput && mediaInput.files && mediaInput.files.length > 0)
                    ? Array.from(mediaInput.files)
                    : (currentDraftState.mediaFiles[p] && currentDraftState.mediaFiles[p].length > 0 ? currentDraftState.mediaFiles[p] : null);
                const vMedia = (currentDraftState.vaultMediaItems && currentDraftState.vaultMediaItems[p] && currentDraftState.vaultMediaItems[p].length > 0)
                    ? currentDraftState.vaultMediaItems[p]
                    : null;
                const tFiles = (thumbInput && thumbInput.files && thumbInput.files.length > 0)
                    ? Array.from(thumbInput.files)
                    : (currentDraftState.thumbFiles[p] && currentDraftState.thumbFiles[p].length > 0 ? currentDraftState.thumbFiles[p] : null);
                const vThumb = (currentDraftState.vaultThumbItems && currentDraftState.vaultThumbItems[p] && currentDraftState.vaultThumbItems[p].length > 0)
                    ? currentDraftState.vaultThumbItems[p]
                    : null;

                if (!sourceMediaFiles && !sourceVaultMedia) {
                    if (mFiles && mFiles.length > 0) {
                        if (!sourcePlatform) sourcePlatform = p;
                        sourceMediaFiles = mFiles;
                    } else if (vMedia && vMedia.length > 0) {
                        if (!sourcePlatform) sourcePlatform = p;
                        sourceVaultMedia = vMedia;
                    }
                }
                if (!sourceThumbFiles && !sourceVaultThumb) {
                    if (tFiles && tFiles.length > 0) {
                        if (!sourcePlatform) sourcePlatform = p;
                        sourceThumbFiles = tFiles;
                    } else if (vThumb && vThumb.length > 0) {
                        if (!sourcePlatform) sourcePlatform = p;
                        sourceVaultThumb = vThumb;
                    }
                }
                if ((sourceMediaFiles || sourceVaultMedia) && (sourceThumbFiles || sourceVaultThumb)) break;
            }

            if (!sourceMediaFiles && !sourceVaultMedia && !sourceThumbFiles && !sourceVaultThumb) {
                return alert("⚠️ Please upload or select a Video, Thumbnail, or Image on at least one platform card before clicking 'Use Same Media to All Platforms'.");
            }

            checkedBoxes.forEach(box => {
                const targetPlatform = box.value;

                if (sourceMediaFiles && sourceMediaFiles.length > 0) {
                    currentDraftState.mediaFiles[targetPlatform] = Array.from(sourceMediaFiles);
                    if (currentDraftState.vaultMediaItems) currentDraftState.vaultMediaItems[targetPlatform] = null;
                    const targetMediaInput = document.getElementById(`media-${targetPlatform}`);
                    if (targetMediaInput) {
                        try {
                            const dt = new DataTransfer();
                            for (let i = 0; i < sourceMediaFiles.length; i++) {
                                dt.items.add(sourceMediaFiles[i]);
                            }
                            targetMediaInput.files = dt.files;
                        } catch (e) {
                            console.warn("DataTransfer media assignment fallback:", e);
                        }
                        if (postType === 'image') {
                            handleMediaPreview(targetMediaInput, `preview-grid-${targetPlatform}`, 'grid');
                        } else {
                            handleMediaPreview(targetMediaInput, `preview-media-${targetPlatform}`, 'video');
                        }
                    }
                } else if (sourceVaultMedia && sourceVaultMedia.length > 0) {
                    currentDraftState.mediaFiles[targetPlatform] = null;
                    if (!currentDraftState.vaultMediaItems) currentDraftState.vaultMediaItems = {};
                    currentDraftState.vaultMediaItems[targetPlatform] = sourceVaultMedia.map(item => Object.assign({}, item));
                    const targetMediaInput = document.getElementById(`media-${targetPlatform}`);
                    if (targetMediaInput) {
                        targetMediaInput.value = '';
                        if (postType === 'image') {
                            handleMediaPreview(targetMediaInput, `preview-grid-${targetPlatform}`, 'grid');
                        } else {
                            handleMediaPreview(targetMediaInput, `preview-media-${targetPlatform}`, 'video');
                        }
                    }
                }

                if (sourceThumbFiles && sourceThumbFiles.length > 0) {
                    currentDraftState.thumbFiles[targetPlatform] = [sourceThumbFiles[0]];
                    if (currentDraftState.vaultThumbItems) currentDraftState.vaultThumbItems[targetPlatform] = null;
                    const targetThumbInput = document.getElementById(`thumb-${targetPlatform}`);
                    if (targetThumbInput) {
                        try {
                            const dtThumb = new DataTransfer();
                            dtThumb.items.add(sourceThumbFiles[0]);
                            targetThumbInput.files = dtThumb.files;
                        } catch (e) {
                            console.warn("DataTransfer thumb assignment fallback:", e);
                        }
                        handleMediaPreview(targetThumbInput, `preview-thumb-${targetPlatform}`, 'image');
                    }
                } else if (sourceVaultThumb && sourceVaultThumb.length > 0) {
                    currentDraftState.thumbFiles[targetPlatform] = null;
                    if (!currentDraftState.vaultThumbItems) currentDraftState.vaultThumbItems = {};
                    currentDraftState.vaultThumbItems[targetPlatform] = [Object.assign({}, sourceVaultThumb[0])];
                    const targetThumbInput = document.getElementById(`thumb-${targetPlatform}`);
                    if (targetThumbInput) {
                        targetThumbInput.value = '';
                        handleMediaPreview(targetThumbInput, `preview-thumb-${targetPlatform}`, 'image');
                    }
                }
            });

            showToast(`✅ Media & Cover/Thumbnail synced from ${(sourcePlatform || 'card').toUpperCase()} to all selected platforms!`);
        }

        // --- SYNC CAPTION, DATE & TIME TO ALL PLATFORMS ---
        function syncCaptionAndTimeToAll() {
            hidePostTooltip();
            const checkedBoxes = Array.from(document.querySelectorAll('input[name="platform"]:checked'));
            if (checkedBoxes.length < 2) {
                return alert("Please select at least two platforms first.");
            }

            let srcCap = '', srcDate = '', srcTime = '';
            for (let box of checkedBoxes) {
                const p = box.value;
                const cap = document.getElementById(`caption-${p}`)?.value || '';
                const dt = document.getElementById(`date-${p}`)?.value || '';
                const tm = document.getElementById(`time-${p}`)?.value || '';
                if (cap || dt || tm) {
                    srcCap = cap; srcDate = dt; srcTime = tm;
                    break;
                }
            }

            checkedBoxes.forEach(box => {
                const p = box.value;
                if (srcCap && document.getElementById(`caption-${p}`)) document.getElementById(`caption-${p}`).value = srcCap;
                if (srcDate && document.getElementById(`date-${p}`)) document.getElementById(`date-${p}`).value = srcDate;
                if (srcTime && document.getElementById(`time-${p}`)) document.getElementById(`time-${p}`).value = srcTime;
            });
            captureCurrentDraftState();
            showToast("✅ Caption, Date & Time synced to all platforms!");
        }

        // --- 2. SAVE & LOAD CUSTOM SELECTION PRESETS ---
        async function saveCustomSelection() {
            hidePostTooltip();
            captureCurrentDraftState();
            const checkedBoxes = Array.from(document.querySelectorAll('input[name="platform"]:checked'));
            if (checkedBoxes.length === 0) {
                return alert("⚠️ Please select platforms and accounts from the dropdowns before saving a Custom Selection.");
            }

            const postType = document.querySelector('input[name="post_type"]:checked').value;
            const platformsData = {};

            for (let box of checkedBoxes) {
                const p = box.value;
                const selectEl = document.getElementById(`page-${p}`);
                const pageId = selectEl ? selectEl.value : '';
                const pageLabel = (selectEl && selectEl.selectedIndex >= 0) ? selectEl.options[selectEl.selectedIndex].text : '';
                platformsData[p] = {
                    pageId: pageId,
                    accountLabel: pageLabel
                };
            }

            const presetName = prompt("Enter a name for this Custom Selection preset (e.g., 'GlennBot Official Trio' or 'Client A Accounts'):");
            if (!presetName || !presetName.trim()) return;

            const selectionPayload = {
                post_type: postType,
                platforms: platformsData
            };

            try {
                let res = await fetch('/api/presets', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        preset_name: presetName.trim(),
                        selection: selectionPayload
                    })
                });
                let data = await res.json();
                if (data.status === 'success') {
                    showToast(`💾 Preset "${presetName.trim()}" saved to Supabase!`);
                } else {
                    alert("❌ Error saving preset: " + (data.message || "Unknown error"));
                }
            } catch (err) {
                console.error("Save preset error:", err);
                alert("❌ Network error while saving preset.");
            }
        }

        async function openLoadPresetModal() {
            hidePostTooltip();
            const container = document.getElementById('preset-list-container');
            openModalWithFade('preset-modal');
            container.innerHTML = `<div class="text-center py-8 text-slate-400 text-xs"><i class="fas fa-circle-notch fa-spin text-gb-cyan text-2xl mb-2"></i><p>Loading saved presets from Supabase...</p></div>`;

            try {
                let res = await fetch('/api/presets');
                let data = await res.json();
                savedPresetsList = data.presets || [];

                if (savedPresetsList.length === 0) {
                    container.innerHTML = `
                        <div class="text-center py-10 text-slate-500">
                            <i class="fas fa-folder-open text-4xl mb-2 opacity-50"></i>
                            <p class="text-sm">No saved Custom Selection presets yet.</p>
                            <p class="text-xs mt-1">Select your platforms and accounts from the dropdowns, then click "Save Custom Selection".</p>
                        </div>
                    `;
                    return;
                }

                container.innerHTML = savedPresetsList.map(preset => {
                    const platformsObj = preset.selection?.platforms || {};
                    const pKeys = Object.keys(platformsObj);
                    const badges = pKeys.map(p => {
                        const lbl = platformsObj[p]?.accountLabel || p;
                        return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-900 border border-slate-700 text-[11px] text-slate-300">${getPlatformBadge(p)} <span class="truncate max-w-[140px]">${escapeHTML(lbl)}</span></span>`;
                    }).join('');

                    return `
                        <div class="bg-slate-800/80 border border-slate-700 hover:border-gb-cyan/60 rounded-xl p-3.5 flex items-center justify-between gap-3 transition-all">
                            <div class="min-w-0 flex-1">
                                <div class="flex items-center gap-2">
                                    <span class="font-bold text-sm text-white truncate">${escapeHTML(preset.preset_name)}</span>
                                    <span class="text-[10px] uppercase px-2 py-0.5 rounded bg-gb-cyan/15 text-gb-cyan border border-gb-cyan/30">${escapeHTML(preset.selection?.post_type || 'reels')}</span>
                                </div>
                                <div class="flex flex-wrap gap-1.5 mt-2">
                                    ${badges}
                                </div>
                            </div>
                            <div class="flex items-center gap-2 shrink-0">
                                <button onclick="applyPreset('${preset.id}')" class="bg-gb-cyan text-slate-950 hover:bg-gb-cyan/90 font-bold px-3 py-1.5 rounded-lg text-xs transition-all">
                                    Apply
                                </button>
                                <button onclick="deletePreset('${preset.id}')" class="bg-rose-950/60 hover:bg-rose-900 border border-rose-700/60 text-rose-300 px-2.5 py-1.5 rounded-lg text-xs transition-all" title="Delete Preset">
                                    <i class="fas fa-trash-alt"></i>
                                </button>
                            </div>
                        </div>
                    `;
                }).join('');
            } catch (err) {
                container.innerHTML = `<div class="text-center py-8 text-rose-400 text-xs">Failed to load presets.</div>`;
            }
        }

        function closePresetModal() {
            closeModalWithFade('preset-modal');
        }

        function applyPreset(presetId) {
            const preset = savedPresetsList.find(p => p.id === presetId);
            if (!preset || !preset.selection) return;

            const sel = preset.selection;
            if (sel.post_type) {
                const radio = document.querySelector(`input[name="post_type"][value="${sel.post_type}"]`);
                if (radio) radio.checked = true;
            }

            const platformsObj = sel.platforms || {};
            document.querySelectorAll('input[name="platform"]').forEach(box => {
                const p = box.value;
                if (platformsObj[p]) {
                    box.checked = true;
                    currentDraftState.accounts[p] = platformsObj[p].pageId || '';
                } else {
                    box.checked = false;
                }
            });

            updatePreviews();
            closePresetModal();
            showToast(`⚡ Loaded preset: "${preset.preset_name}"`);
        }

        async function deletePreset(presetId) {
            if (!confirm("Are you sure you want to delete this Custom Selection preset?")) return;
            try {
                await fetch(`/api/presets/${presetId}`, { method: 'DELETE' });
                openLoadPresetModal();
            } catch (e) {
                console.error("Delete preset error:", e);
            }
        }

        // =========================================================================
        // --- ASK AI (GEMINI 3.5 FLASH) CONTENT & CAPTION ASSISTANT ENGINE ---
        // =========================================================================
        let lastGeneratedAiData = null;

        function openAskAiModal() {
            hidePostTooltip();
            const modal = document.getElementById('ask-ai-modal');
            if (!modal) return;
            openModalWithFade('ask-ai-modal');

            // If prompt is empty, try pre-filling with any caption the user already wrote
            const promptEl = document.getElementById('ask-ai-prompt');
            if (promptEl && !promptEl.value.trim()) {
                const existingCap = (
                    (document.getElementById('caption-facebook')?.value) ||
                    (document.getElementById('caption-instagram')?.value) ||
                    (document.getElementById('caption-tiktok')?.value) ||
                    (document.getElementById('caption-youtube')?.value) ||
                    ''
                ).trim();
                if (existingCap) {
                    promptEl.value = existingCap;
                }
            }
            setTimeout(() => {
                promptEl?.focus();
            }, 150);
        }

        function closeAskAiModal() {
            closeModalWithFade('ask-ai-modal');
        }

        async function triggerAskAiGenerate(isRegenerate = false) {
            const promptEl = document.getElementById('ask-ai-prompt');
            const topic = (promptEl?.value || '').trim();
            if (!topic) {
                showToast("⚠️ Paki-explain muna kung tungkol saan ang iyong content bago mag-generate!");
                promptEl?.focus();
                return;
            }

            const toneEl = document.getElementById('ask-ai-tone');
            const langEl = document.getElementById('ask-ai-lang');
            const genBtn = document.getElementById('ask-ai-generate-btn');
            const regenBtn = document.getElementById('ask-ai-regen-btn');

            const postType = (document.querySelector('input[name="post_type"]:checked')?.value) || 'reels';
            const checkedBoxes = Array.from(document.querySelectorAll('input[name="platform"]:checked'));
            const selectedPlatforms = checkedBoxes.map(b => b.value);
            const targetPlatforms = selectedPlatforms.length > 0 ? selectedPlatforms : ['facebook', 'instagram', 'tiktok', 'youtube'];

            const origGenHTML = genBtn ? genBtn.innerHTML : '';
            const origRegenHTML = regenBtn ? regenBtn.innerHTML : '';

            if (genBtn) {
                genBtn.disabled = true;
                genBtn.innerHTML = `<i class="fas fa-circle-notch fa-spin text-amber-300"></i> <span>Gemini 3.5 Flash is thinking...</span>`;
            }
            if (regenBtn) {
                regenBtn.disabled = true;
                regenBtn.innerHTML = `<i class="fas fa-circle-notch fa-spin text-gb-cyan"></i> <span>Regenerating...</span>`;
            }

            try {
                const res = await fetch('/api/ai/ask', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        topic: topic,
                        tone: toneEl ? toneEl.value : 'engaging',
                        language: langEl ? langEl.value : 'taglish',
                        post_type: postType,
                        platforms: targetPlatforms
                    })
                });

                const data = await res.json();
                if (!res.ok || data.status !== 'success' || !data.data) {
                    throw new Error(data.message || `HTTP ${res.status}: Failed to generate copy.`);
                }

                const ai = data.data;
                lastGeneratedAiData = ai;

                // Populate title & primary caption inputs
                const titleInput = document.getElementById('ask-ai-res-title');
                const captionInput = document.getElementById('ask-ai-res-caption');
                const fbInput = document.getElementById('ask-ai-res-fb');
                const igInput = document.getElementById('ask-ai-res-ig');
                const tiktokInput = document.getElementById('ask-ai-res-tiktok');
                const ytInput = document.getElementById('ask-ai-res-yt');

                if (titleInput) titleInput.value = ai.title || ai.youtube_title || '';
                if (captionInput) captionInput.value = ai.caption || '';
                if (fbInput) fbInput.value = ai.facebook_caption || ai.caption || '';
                if (igInput) igInput.value = ai.instagram_caption || ai.caption || '';
                if (tiktokInput) tiktokInput.value = ai.tiktok_caption || ai.caption || '';
                if (ytInput) ytInput.value = ai.youtube_description || ai.caption || '';

                // Reveal results section
                const resSection = document.getElementById('ask-ai-results-section');
                if (resSection) {
                    resSection.classList.remove('hidden');
                    resSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }

                playNotificationSound();
                showToast(isRegenerate ? "✨ Bagong Gemini 3.5 Flash ideas generated!" : "✨ Gemini 3.5 Flash generated content ideas!");
            } catch (err) {
                console.error("Ask AI error:", err);
                showToast(`⚠️ ${err.message || 'Error generating content with Gemini.'}`);
            } finally {
                if (genBtn) {
                    genBtn.disabled = false;
                    genBtn.innerHTML = origGenHTML;
                }
                if (regenBtn) {
                    regenBtn.disabled = false;
                    regenBtn.innerHTML = origRegenHTML;
                }
            }
        }

        function approveAndApplyAiContent() {
            const titleVal = (document.getElementById('ask-ai-res-title')?.value || '').trim();
            const primaryCap = (document.getElementById('ask-ai-res-caption')?.value || '').trim();
            const fbCap = (document.getElementById('ask-ai-res-fb')?.value || '').trim() || primaryCap;
            const igCap = (document.getElementById('ask-ai-res-ig')?.value || '').trim() || primaryCap;
            const tiktokCap = (document.getElementById('ask-ai-res-tiktok')?.value || '').trim() || primaryCap;
            const ytDesc = (document.getElementById('ask-ai-res-yt')?.value || '').trim() || primaryCap;

            if (!primaryCap && !titleVal) {
                showToast("⚠️ Walang content na na-generate o walang laman ang caption.");
                return;
            }

            // If no platform is checked yet, automatically check Facebook so the card appears!
            const checkedBoxes = Array.from(document.querySelectorAll('input[name="platform"]:checked'));
            if (checkedBoxes.length === 0) {
                const fbBox = document.querySelector('input[name="platform"][value="facebook"]');
                if (fbBox) fbBox.checked = true;
                updatePreviews();
            }

            // Apply to all current platforms and preserve in currentDraftState
            const currentPlatforms = ['facebook', 'instagram', 'tiktok', 'youtube'];
            currentPlatforms.forEach(p => {
                let assignedCap = primaryCap;
                if (p === 'facebook') assignedCap = fbCap;
                else if (p === 'instagram') assignedCap = igCap;
                else if (p === 'tiktok') assignedCap = tiktokCap;
                else if (p === 'youtube') assignedCap = ytDesc;

                currentDraftState.captions[p] = assignedCap;

                const capEl = document.getElementById(`caption-${p}`);
                if (capEl) capEl.value = assignedCap;

                if (p === 'youtube' && titleVal) {
                    if (!currentDraftState.titles) currentDraftState.titles = { youtube: '' };
                    currentDraftState.titles.youtube = titleVal;
                    const ytTitleEl = document.getElementById('title-youtube');
                    if (ytTitleEl) ytTitleEl.value = titleVal;
                }
            });

            captureCurrentDraftState();
            closeAskAiModal();
            playNotificationSound();
            showToast("🎉 Approved! Nakainput na ang captions at title. Set Date & Time then click Launch Automation!");
        }

        // --- TAB NAVIGATION ---
        function switchTab(tabName, skipAutoFetch = false) {
            activeTab = tabName;
            hidePostTooltip();
            const tabs = ['scheduler', 'calendar', 'queue', 'messages', 'comments', 'analytics', 'email', 'contacts', 'files', 'spreadsheet', 'automations'];
            tabs.forEach(t => {
                const viewEl = document.getElementById(`view-${t}`);
                const btnEl = document.getElementById(`tab-btn-${t}`);
                if (viewEl) viewEl.classList.toggle('hidden', t !== tabName);
                if (btnEl) btnEl.classList.toggle('active', t === tabName);
            });
            if (skipAutoFetch) return;
            if (tabName === 'calendar' || tabName === 'queue') {
                fetchScheduledPosts();
                if (tabName === 'calendar') {
                    fetchComposioCalendarAccounts(false);
                    fetchComposioCalendarEvents(false);
                    fetchComposioCalendarEvents(true);
                }
            } else if (tabName === 'comments') {
                fetchComments(false);
            } else if (tabName === 'messages') {
                fetchConversations(false);
            } else if (tabName === 'analytics') {
                fetchAnalyticsData(false);
            } else if (tabName === 'email') {
                initEmailTabView();
            } else if (tabName === 'contacts') {
                initContactsTabView();
            } else if (tabName === 'files') {
                fetchVaultFiles(false);
            } else if (tabName === 'spreadsheet') {
                initSpreadsheetView();
            } else if (tabName === 'automations') {
                initAutomationsCanvasView();
            }
        }

        // --- FORMAT HELPERS ---
        function formatPostTypeLabel(postType) {
            const map = {
                'reels': 'Reels/Short',
                'video169': '16:9 Video',
                'image': 'Image/Album',
                'text': 'Text Post'
            };
            return map[postType] || (postType || '').toUpperCase();
        }

        function formatPostTypeBadge(postType) {
            const iconMap = {
                'reels': 'fa-mobile-alt',
                'video169': 'fa-video',
                'image': 'fa-images',
                'text': 'fa-align-left'
            };
            const ic = iconMap[postType] || 'fa-file-alt';
            return `<span class="inline-flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1 rounded-md bg-slate-800 text-gb-cyan border border-slate-700 whitespace-nowrap"><i class="fas ${ic}"></i> ${formatPostTypeLabel(postType)}</span>`;
        }

        function getPlatformBadge(platform, withLabel = false) {
            if (platform === 'facebook') {
                return `<span class="inline-flex items-center gap-1.5"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-600 text-white text-[10px] shrink-0"><i class="fab fa-facebook-f"></i></span>${withLabel ? '<span class="text-xs font-semibold text-blue-400">Facebook</span>' : ''}</span>`;
            }
            if (platform === 'instagram') {
                return `<span class="inline-flex items-center gap-1.5"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-gradient-to-tr from-yellow-400 via-red-500 to-purple-500 text-white text-[10px] shrink-0"><i class="fab fa-instagram"></i></span>${withLabel ? '<span class="text-xs font-semibold text-pink-400">Instagram</span>' : ''}</span>`;
            }
            if (platform === 'tiktok') {
                return `<span class="inline-flex items-center gap-1.5"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-slate-950 border border-slate-600 text-white text-[10px] shrink-0"><i class="fab fa-tiktok"></i></span>${withLabel ? '<span class="text-xs font-semibold text-slate-200">TikTok</span>' : ''}</span>`;
            }
            if (platform === 'youtube') {
                return `<span class="inline-flex items-center gap-1.5"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-red-600 text-white text-[10px] shrink-0"><i class="fab fa-youtube"></i></span>${withLabel ? '<span class="text-xs font-semibold text-red-400">YouTube</span>' : ''}</span>`;
            }
            if (platform === 'whatsapp') {
                return `<span class="inline-flex items-center gap-1.5"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-[#25D366] text-slate-950 text-[11px] font-bold shrink-0"><i class="fab fa-whatsapp"></i></span>${withLabel ? '<span class="text-xs font-semibold text-[#25D366]">WhatsApp</span>' : ''}</span>`;
            }
            if (platform === 'telegram') {
                return `<span class="inline-flex items-center gap-1.5"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-[#229ED9] text-white text-[10px] shrink-0"><i class="fab fa-telegram-plane"></i></span>${withLabel ? '<span class="text-xs font-semibold text-[#229ED9]">Telegram</span>' : ''}</span>`;
            }
            if (platform === 'gmail') {
                return `<span class="inline-flex items-center gap-1.5"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-red-500 text-white text-[10px] shrink-0"><i class="fab fa-google"></i></span>${withLabel ? '<span class="text-xs font-semibold text-red-300">Gmail</span>' : ''}</span>`;
            }
            if (platform === 'google_contacts') {
                return `<span class="inline-flex items-center gap-1.5"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-600 text-white text-[10px] shrink-0" title="Imported from Google Contacts"><i class="fab fa-google"></i></span>${withLabel ? '<span class="text-xs font-semibold text-blue-300">Google Contacts</span>' : ''}</span>`;
            }
            if (platform === 'microsoft') {
                return `<span class="inline-flex items-center gap-1.5"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-sky-600 text-white text-[10px] shrink-0"><i class="fab fa-microsoft"></i></span>${withLabel ? '<span class="text-xs font-semibold text-sky-300">Microsoft</span>' : ''}</span>`;
            }
            if (platform === 'imap') {
                return `<span class="inline-flex items-center gap-1.5"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-amber-600 text-white text-[10px] shrink-0"><i class="fas fa-server"></i></span>${withLabel ? '<span class="text-xs font-semibold text-amber-300">IMAP/SMTP</span>' : ''}</span>`;
            }
            if (platform === 'sms' || platform === 'textbee') {
                return `<span class="inline-flex items-center gap-1.5"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-emerald-600 text-white text-[10px] shrink-0" title="TextBee.dev SMS (SIM 2)"><i class="fas fa-sms"></i></span>${withLabel ? '<span class="text-xs font-semibold text-emerald-300">TextBee SMS</span>' : ''}</span>`;
            }
            return '';
        }

        function getStatusIcon(status) {
            if (status === 'processing_payload') return `<i class="fas fa-satellite-dish fa-spin text-amber-400" title="Processing Payload (Uploading & Queueing in Background)"></i>`;
            if (status === 'processing') return `<i class="fas fa-cog fa-spin text-amber-400" title="Processing Payload / Publishing"></i>`;
            if (status === 'waiting') return `<i class="fas fa-circle-notch fa-spin text-gb-cyan" title="Waiting for schedule"></i>`;
            if (status === 'published') return `<i class="fas fa-check-circle text-emerald-400" title="Published!"></i>`;
            if (status === 'failed') return `<i class="fas fa-times-circle text-rose-500" title="Failed"></i>`;
            return '';
        }

        function sanitizeStatusMessageForUI(rawMessage, status = '') {
            const st = String(status || '').trim().toLowerCase();
            if (st === 'published') return '';
            let s = String(rawMessage || '').trim();
            if (!s) return '';
            const dictErrMatch = s.match(/['"]error['"]\s*:\s*['"]([^'"]+)['"]/i);
            if (dictErrMatch && s.includes('{') && s.includes('}')) {
                const prefix = /^external api failed/i.test(s) ? 'External API Failed: ' : '';
                s = prefix + dictErrMatch[1].trim();
            }
            s = s.replace(/(?:External API ID|Platform ID|Zernio ID|PostZen ID|FB Post ID|FB Video ID|FB Album ID|IG Post ID|existingPostId|accountId)\s*[:=]\s*[^\s,|)}'"]+/gi, '');
            s = s.replace(/\(\s*ID\s*:\s*[^)]+\)/gi, '');
            s = s.replace(/•\s*ID\s*:\s*[^\s,|)]+/gi, '');
            s = s.replace(/\bExternal Post\b/gi, '');
            const parts = s.split(/\s*\|\s*/).map(p => p.replace(/^[•|\-\s]+|[•|\-\s]+$/g, '')).filter(Boolean);
            const cleaned = parts.join(' • ').replace(/^[•|\-\s]+|[•|\-\s]+$/g, '');
            if (st === 'waiting' && !cleaned) return 'Waiting for schedule...';
            return cleaned;
        }

        function getStatusBadgeHTML(status, statusMessage = '', permalinkUrl = '') {
            const cleanMessage = sanitizeStatusMessageForUI(statusMessage, status);
            let badge = '';
            let progressBarHTML = '';
            if (status === 'processing_payload' || status === 'processing') {
                const iconClass = status === 'processing_payload' ? 'fa-satellite-dish' : 'fa-cog';
                const pctMatch = String(cleanMessage || '').match(/\((\d+)%\s*(?:•\s*(Part\s+\d+\/\d+))?\)/i);
                const pctVal = pctMatch ? Math.min(100, Math.max(0, parseInt(pctMatch[1], 10))) : null;
                const partLabel = (pctMatch && pctMatch[2]) ? ` • ${pctMatch[2]}` : '';
                const badgeText = pctVal !== null
                    ? `Uploading ${pctVal}%${partLabel}`
                    : 'Processing Payload';
                badge = `<span class="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-400/50 shadow-[0_0_12px_rgba(245,158,11,0.2)] inline-flex items-center gap-1.5 whitespace-nowrap"><i class="fas ${iconClass} fa-spin text-amber-400"></i> ${escapeHTML(badgeText)}</span>`;
                if (pctVal !== null) {
                    progressBarHTML = `
                        <div class="w-48 bg-slate-800 rounded-full h-1.5 overflow-hidden border border-slate-700 mt-0.5">
                            <div class="bg-gradient-to-r from-amber-400 to-gb-cyan h-full transition-all duration-300" style="width: ${pctVal}%"></div>
                        </div>
                    `;
                }
            } else if (status === 'waiting') {
                badge = `<span class="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-gb-cyan/15 text-gb-cyan border border-gb-cyan/40 inline-flex items-center gap-1.5 whitespace-nowrap"><i class="fas fa-clock"></i> Waiting</span>`;
            } else if (status === 'published') {
                badge = `<span class="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-emerald-500/15 text-emerald-300 border border-emerald-500/40 inline-flex items-center gap-1.5 whitespace-nowrap"><i class="fas fa-check-circle"></i> Published</span>`;
            } else {
                badge = `<span class="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-rose-500/15 text-rose-300 border border-rose-500/40 inline-flex items-center gap-1.5 whitespace-nowrap"><i class="fas fa-exclamation-circle"></i> Failed</span>`;
            }
            return `
                <div class="flex flex-col items-start gap-1">
                    ${badge}
                    ${progressBarHTML}
                    ${cleanMessage ? `<span class="text-[10px] text-slate-300 max-w-[240px] whitespace-normal leading-tight" title="${escapeHTML(cleanMessage)}">${escapeHTML(cleanMessage)}</span>` : ''}
                    ${permalinkUrl ? `<a href="${permalinkUrl}" target="_blank" class="text-[10px] text-gb-cyan hover:underline inline-flex items-center gap-1"><i class="fas fa-external-link-alt text-[9px]"></i> Actual Post Link</a>` : ''}
                </div>
            `;
        }

        function getCombinedScheduledPosts() {
            return [...optimisticProcessingPosts, ...scheduledPostsList];
        }

        function syncQueueBadgeCount() {
            const allPosts = getCombinedScheduledPosts();
            const activeCount = allPosts.filter(i => i.status === 'waiting' || i.status === 'processing' || i.status === 'processing_payload').length;
            const badgeEl = document.getElementById('queue-badge');
            if (badgeEl) badgeEl.textContent = activeCount;
        }

        // --- WINDOWS-STYLE FLOATING BUBBLE TOOLTIP LOGIC ---
        function showPostTooltip(event, postId) {
            const post = getCombinedScheduledPosts().find(p => p.id === postId);
            if (!post) return;

            const tooltip = document.getElementById('gb-tooltip');
            const captionPreview = post.caption ? (post.caption.length > 80 ? post.caption.substring(0, 80) + '...' : post.caption) : 'No caption provided';
            const statusLabel = (post.status === 'processing_payload' || post.status === 'processing')
                ? 'PROCESSING PAYLOAD'
                : String(post.status || '').toUpperCase();

            tooltip.innerHTML = `
                <div class="flex items-center justify-between border-b border-slate-800 pb-2 mb-2">
                    ${getPlatformBadge(post.platform, true)}
                    <span class="text-[11px] font-bold text-gb-cyan"><i class="far fa-clock mr-1"></i>${post.time_str}</span>
                </div>
                <div class="space-y-1.5">
                    <div>
                        <span class="text-[10px] uppercase tracking-wider text-slate-400 block">Social Media Page / Account</span>
                        <span class="font-semibold text-white text-xs break-words">${escapeHTML(post.account_name)}</span>
                    </div>
                    <div class="flex items-center justify-between pt-1">
                        <div>
                            <span class="text-[10px] uppercase tracking-wider text-slate-400 block">Post Format</span>
                            <span class="text-gb-cyan font-medium text-[11px]">${formatPostTypeLabel(post.post_type)}</span>
                        </div>
                        <div class="text-right">
                            <span class="text-[10px] uppercase tracking-wider text-slate-400 block">Status</span>
                            <span class="uppercase font-bold text-[10px] ${(post.status === 'processing_payload' || post.status === 'processing') ? 'text-amber-300' : 'text-slate-200'}">${escapeHTML(statusLabel)}</span>
                        </div>
                    </div>
                    <div class="pt-1 border-t border-slate-800/80">
                        <span class="text-[10px] uppercase tracking-wider text-slate-400 block">Caption</span>
                        <p class="text-[11px] text-slate-300 italic line-clamp-2">${escapeHTML(captionPreview)}</p>
                    </div>
                </div>
            `;

            tooltip.classList.remove('hidden');
            tooltip.classList.remove('opacity-0');
            movePostTooltip(event);
        }

        function movePostTooltip(event) {
            const tooltip = document.getElementById('gb-tooltip');
            if (tooltip.classList.contains('hidden')) return;

            const pad = 14;
            let x = event.clientX + pad;
            let y = event.clientY + pad;

            const rect = tooltip.getBoundingClientRect();
            if (x + rect.width > window.innerWidth - 10) {
                x = event.clientX - rect.width - pad;
            }
            if (y + rect.height > window.innerHeight - 10) {
                y = event.clientY - rect.height - pad;
            }

            tooltip.style.left = `${x}px`;
            tooltip.style.top = `${y}px`;
        }

        function hidePostTooltip() {
            const tooltip = document.getElementById('gb-tooltip');
            if (tooltip) {
                tooltip.classList.add('opacity-0');
                tooltip.classList.add('hidden');
            }
        }

        // --- REUSABLE TABULAR BUILDER ---
        function buildPostsTableHTML(postsArray, emptyMessage = "No scheduled posts found.") {
            if (!postsArray || postsArray.length === 0) {
                return `
                    <div class="flex flex-col items-center justify-center py-14 text-slate-500 opacity-70">
                        <i class="fas fa-calendar-times text-4xl mb-3"></i>
                        <p class="text-sm">${emptyMessage}</p>
                    </div>
                `;
            }

            const rowsHTML = postsArray.map((p, idx) => {
                let mediaThumb = `<span class="text-[11px] text-slate-500 italic">Text Only</span>`;
                if (p.permalink_url) {
                    mediaThumb = `<a href="${p.permalink_url}" target="_blank" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-gb-cyan/15 hover:bg-gb-cyan/25 border border-gb-cyan/50 text-gb-cyan text-xs font-semibold whitespace-nowrap"><i class="fas fa-external-link-alt"></i> View Live Post</a>`;
                } else if (p.media_preview_url) {
                    const isVideoPostType = ['reels', 'video169', 'video'].includes(String(p.post_type || '').toLowerCase());
                    const isVideoExt = /\.(mp4|mov|webm|mkv|avi)(?:$|\?)/i.test(p.media_preview_url);
                    const isVaultStream = p.media_preview_url.includes('/api/files/') || p.media_preview_url.includes('/api/gdrive-media/');
                    if ((isVideoPostType || isVideoExt || (isVaultStream && p.post_type !== 'image')) && p.post_type !== 'image') {
                        mediaThumb = `<a href="${p.media_preview_url}" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-emerald-500/50 text-emerald-300 hover:text-gb-cyan text-xs whitespace-nowrap" title="Bandwidth Saver: Click to open video stream in new tab"><i class="fas fa-play-circle text-gb-cyan"></i> View Video</a>`;
                    } else if (userSettings && userSettings.bandwidthSaverMode !== false && isVaultStream) {
                        mediaThumb = `<a href="${p.media_preview_url}" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-emerald-500/40 text-emerald-300 text-xs whitespace-nowrap" title="Bandwidth Saver: Click to view media"><i class="fas fa-image text-emerald-400"></i> View Media</a>`;
                    } else {
                        mediaThumb = `<a href="${p.media_preview_url}" target="_blank" class="block w-11 h-11 rounded-lg overflow-hidden border border-slate-600 hover:border-gb-cyan transition-all"><img src="${p.media_preview_url}" loading="lazy" class="w-full h-full object-cover" onerror="this.outerHTML='<span class=\\'text-xs text-gb-cyan p-1\\'>Media</span>'"></a>`;
                    }
                } else if (p.status === 'processing_payload' && p.post_type !== 'text') {
                    mediaThumb = `<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300 text-[11px] whitespace-nowrap"><i class="fas fa-cloud-upload-alt fa-fade"></i> Uploading...</span>`;
                }

                const isOptimistic = String(p.id || '').startsWith('temp_payload_');
                const actionBtnHTML = isOptimistic
                    ? `<span class="text-[11px] text-amber-300/80 italic px-2"><i class="fas fa-sync fa-spin mr-1"></i>Syncing...</span>`
                    : `<button onclick="deleteScheduledPost('${p.id}')" class="bg-rose-950/60 hover:bg-rose-900 border border-rose-700/60 text-rose-300 px-3 py-1.5 rounded-lg text-xs transition-all inline-flex items-center gap-1.5" title="Cancel / Delete">
                            <i class="fas fa-trash-alt"></i> <span class="hidden xl:inline">Remove</span>
                       </button>`;

                return `
                    <tr class="border-b border-slate-800/80 hover:bg-slate-800/50 transition-colors">
                        <td class="py-3 px-4 text-xs font-bold text-slate-500">#${idx + 1}</td>
                        <td class="py-3 px-4 whitespace-nowrap">
                            <div class="text-xs font-semibold text-white">${p.display_date}</div>
                            <div class="text-[11px] text-gb-cyan font-medium"><i class="far fa-clock mr-1"></i>${p.time_str}</div>
                        </td>
                        <td class="py-3 px-4 whitespace-nowrap">
                            ${getPlatformBadge(p.platform, true)}
                        </td>
                        <td class="py-3 px-4">
                            <div class="text-xs font-semibold text-slate-100 max-w-[200px] truncate" title="${escapeHTML(p.account_name)}">${escapeHTML(p.account_name)}</div>
                        </td>
                        <td class="py-3 px-4 whitespace-nowrap">
                            ${formatPostTypeBadge(p.post_type)}
                        </td>
                        <td class="py-3 px-4">
                            ${mediaThumb}
                        </td>
                        <td class="py-3 px-4 max-w-[260px]">
                            <p class="text-xs text-slate-300 line-clamp-2" title="${escapeHTML(p.caption || '')}">
                                ${p.caption ? escapeHTML(p.caption) : '<span class="italic text-slate-600">No caption</span>'}
                            </p>
                        </td>
                        <td class="py-3 px-4 whitespace-nowrap">
                            ${getStatusBadgeHTML(p.status, p.status_message, p.permalink_url)}
                        </td>
                        <td class="py-3 px-4 text-right whitespace-nowrap">
                            ${actionBtnHTML}
                        </td>
                    </tr>
                `;
            }).join('');

            return `
                <table class="w-full text-left border-collapse min-w-[750px]">
                    <thead>
                        <tr class="border-b border-slate-700 bg-slate-900/90 text-[11px] font-semibold uppercase tracking-wider text-slate-400 sticky top-0 z-10">
                            <th class="py-3 px-4">#</th>
                            <th class="py-3 px-4">Schedule</th>
                            <th class="py-3 px-4">Platform</th>
                            <th class="py-3 px-4">Social Media Page</th>
                            <th class="py-3 px-4">Post Format</th>
                            <th class="py-3 px-4">Media / Link</th>
                            <th class="py-3 px-4">Caption</th>
                            <th class="py-3 px-4">Live Status</th>
                            <th class="py-3 px-4 text-right">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rowsHTML}
                    </tbody>
                </table>
            `;
        }

        // --- EXPANDED DAY MODAL CONTROLS ---
        function openDayModal(day, monthZeroIndexed, year) {
            hidePostTooltip();
            currentModalDayKey = { day, month: monthZeroIndexed, year };
            const title = document.getElementById('modal-day-title');
            const subtitle = document.getElementById('modal-day-subtitle');
            const container = document.getElementById('modal-table-container');
            const schedBtn = document.getElementById('modal-day-schedule-btn');

            if (activeCalendarSubTab === 'composio') {
                const dayEvents = getFilteredComposioCalendarEvents().filter(ev => ev.day === day && (ev.month - 1) === monthZeroIndexed && ev.year === year);
                title.textContent = `Calendars & Meetings for ${monthNames[monthZeroIndexed]} ${day}, ${year}`;
                subtitle.textContent = `${dayEvents.length} appointment(s) / video meeting(s) synced via Composio`;
                container.innerHTML = buildCalendarEventsTableHTML(dayEvents, `No Google Calendar, MS Outlook, or Zoom appointments for ${monthNames[monthZeroIndexed]} ${day}, ${year}.`);
                if (schedBtn) {
                    schedBtn.classList.remove('hidden');
                    schedBtn.classList.add('inline-flex');
                }
            } else {
                const dayPosts = getCombinedScheduledPosts().filter(p => p.day === day && (p.month - 1) === monthZeroIndexed && p.year === year);
                title.textContent = `Scheduled Posts for ${monthNames[monthZeroIndexed]} ${day}, ${year}`;
                subtitle.textContent = `${dayPosts.length} scheduled social media automation(s) found for this date`;
                container.innerHTML = buildPostsTableHTML(dayPosts, `No scheduled posts for ${monthNames[monthZeroIndexed]} ${day}, ${year}.`);
                if (schedBtn) {
                    schedBtn.classList.add('hidden');
                    schedBtn.classList.remove('inline-flex');
                }
            }

            openModalWithFade('day-modal');
        }

        function closeDayModal() {
            currentModalDayKey = null;
            closeModalWithFade('day-modal');
        }

        // =========================================================================
        // --- OAUTH-STYLE SEPARATE EXPANDED WINDOW & FULL-WINDOW FOCUS ENGINE ---
        // --- Supports:
        // ---   1. comment_thread  (Comments Modal -> Media + Caption + Thread)
        // ---   2. spreadsheet     (Spread Sheet Modal -> Selected Workbook)
        // ---   3. email_view      (Email Reader / Expanded Email)
        // ---   4. message_thread  (Messages Modal -> Active Conversation Thread)
        // ---   5. new_sms         (Create New SMS Modal)
        // ---   6. compose_email   (Compose New Email Modal)
        // ---   7. files_vault     (Files Vault Modal)
        // =========================================================================
        window.gbActivePopoutMode = '';
        window.gbActivePopoutParams = {};
        window.gbIsInPageFocusFallback = false;

        function getUrlPopoutParams() {
            try {
                const sp = new URLSearchParams(window.location.search || '');
                const mode = String(sp.get('popout_mode') || '').trim();
                if (!mode) return null;
                const params = {};
                sp.forEach((val, key) => {
                    params[key] = val;
                });
                return { mode, params };
            } catch (_) {
                return null;
            }
        }

        function openGlennBotExpandedWindow(mode, params = {}, width = 1140, height = 840) {
            const cleanMode = String(mode || '').trim();
            if (!cleanMode) return null;

            const sp = new URLSearchParams();
            sp.set('popout_mode', cleanMode);
            Object.entries(params || {}).forEach(([k, v]) => {
                if (v !== undefined && v !== null && String(v) !== '') {
                    sp.set(k, String(v));
                }
            });
            sp.set('_ts', String(Date.now()));

            const popoutUrl = `${window.location.origin}${window.location.pathname}?${sp.toString()}`;
            const availW = window.screen?.availWidth || window.screen?.width || 1440;
            const availH = window.screen?.availHeight || window.screen?.height || 900;
            const w = Math.min(width, availW - 40);
            const h = Math.min(height, availH - 40);
            const left = Math.max(0, Math.round((availW - w) / 2));
            const top = Math.max(0, Math.round((availH - h) / 2));

            const windowName = `GlennBotExpanded_${cleanMode}_${String(params.record_id || params.workbook_id || params.message_id || params.conv_id || 'main').replace(/[^a-zA-Z0-9_-]/g, '')}`;
            const features = `width=${w},height=${h},left=${left},top=${top},menubar=no,toolbar=no,location=no,status=no,resizable=yes,scrollbars=yes`;

            let popupWin = null;
            try {
                popupWin = window.open(popoutUrl, windowName, features);
            } catch (_) {
                popupWin = null;
            }

            if (popupWin && !popupWin.closed) {
                try { popupWin.focus(); } catch (_) {}
                showToast('🗗 Opened Expanded View in a separate window!');
                return popupWin;
            }

            // Fallback if browser/iframe blocks popups: activate Full-Window Expanded Focus Mode in-place
            window.gbIsInPageFocusFallback = true;
            applyGlennBotPopoutLayout(cleanMode, params);
            showToast('🗗 Entered Full-Window Expanded Focus View!');
            return null;
        }

        // 1. Comments Modal -> Expanded View (next to Delete Thread)
        function openExpandedCommentThreadWindow(recordId, event) {
            if (event) event.stopPropagation();
            const targetRecordId = String(recordId || selectedCommentRecordId || '').trim();
            if (!targetRecordId) {
                showToast('⚠️ Select a comment thread first to open Expanded View.');
                return;
            }
            try {
                const threadItems = (typeof commentsList !== 'undefined' && Array.isArray(commentsList))
                    ? commentsList.filter(c => String(c.record_id) === targetRecordId)
                    : [];
                const draftReply = document.getElementById('comment-reply-input')?.value || '';
                localStorage.setItem('gb_popout_comment_thread_cache', JSON.stringify({
                    record_id: targetRecordId,
                    comment_id: (typeof selectedCommentId !== 'undefined' && selectedCommentId) ? selectedCommentId : '',
                    items: threadItems,
                    draft_reply: draftReply,
                    saved_at: Date.now()
                }));
            } catch (_) {}

            openGlennBotExpandedWindow('comment_thread', {
                record_id: targetRecordId,
                comment_id: (typeof selectedCommentId !== 'undefined' && selectedCommentId) ? selectedCommentId : ''
            }, 1080, 860);
        }

        // 2. Spread Sheet Modal -> Expanded View (for Selected Spreadsheet)
        function openExpandedSpreadsheetWindow(event) {
            if (event) event.stopPropagation();
            const wbId = String(currentSpreadsheetWorkbook?.workbook_id || document.getElementById('ss-saved-workbooks-select')?.value || '').trim();
            const shIdx = typeof activeSheetIndex === 'number' ? activeSheetIndex : 0;
            try {
                localStorage.setItem('gb_popout_spreadsheet_cache', JSON.stringify({
                    workbook_id: wbId,
                    active_sheet_index: shIdx,
                    workbook: currentSpreadsheetWorkbook || null,
                    saved_at: Date.now()
                }));
            } catch (_) {}

            openGlennBotExpandedWindow('spreadsheet', {
                workbook_id: wbId,
                sheet_idx: String(shIdx)
            }, 1280, 860);
        }

        // 3. Email Reader / Expanded Email -> Expanded View
        function openExpandedEmailWindow(msgId, event) {
            if (event) event.stopPropagation();
            const targetMsgId = String(msgId || (typeof selectedEmailMessageId !== 'undefined' ? selectedEmailMessageId : '') || '').trim();
            if (!targetMsgId) {
                showToast('⚠️ Select an email first to open Expanded View.');
                return;
            }
            const accId = (typeof activeEmailAccountId !== 'undefined' && activeEmailAccountId) ? activeEmailAccountId : '';
            const folder = (typeof activeEmailFolder !== 'undefined' && activeEmailFolder) ? activeEmailFolder : 'inbox';
            try {
                const msgObj = (typeof activeEmailMessages !== 'undefined' && Array.isArray(activeEmailMessages))
                    ? activeEmailMessages.find(m => String(m.id) === targetMsgId)
                    : null;
                const draftReply = document.getElementById('expanded-email-reply-input')?.value
                    || document.getElementById('email-quick-reply-input')?.value
                    || '';
                localStorage.setItem('gb_popout_email_view_cache', JSON.stringify({
                    account_id: accId,
                    message_id: targetMsgId,
                    folder: folder,
                    message: msgObj || null,
                    draft_reply: draftReply,
                    saved_at: Date.now()
                }));
            } catch (_) {}

            const popup = openGlennBotExpandedWindow('email_view', {
                account_id: accId,
                message_id: targetMsgId,
                folder: folder
            }, 1120, 860);

            if (popup && typeof closeExpandedEmailModal === 'function') {
                closeExpandedEmailModal();
            }
        }

        // 4. Messages Modal -> Expanded View (Active Conversation Thread)
        function openExpandedMessageThreadWindow(convKey, conversationId, accountId, event) {
            if (event) event.stopPropagation();
            const cKey = String(convKey || activeConversationObj?.conv_key || '').trim();
            const cId = String(conversationId || activeConversationObj?.conversation_id || '').trim();
            const aId = String(accountId || activeConversationObj?.account_id || '').trim();
            if (!cKey && !cId) {
                showToast('⚠️ Select a conversation first to open Expanded View.');
                return;
            }
            try {
                const draftMsg = document.getElementById('direct-message-input')?.value || '';
                localStorage.setItem('gb_popout_message_thread_cache', JSON.stringify({
                    conv_key: cKey,
                    conv_id: cId,
                    account_id: aId,
                    conversation: (typeof activeConversationObj !== 'undefined') ? activeConversationObj : null,
                    messages: (typeof activeConversationMessages !== 'undefined') ? activeConversationMessages : [],
                    draft_message: draftMsg,
                    saved_at: Date.now()
                }));
            } catch (_) {}

            openGlennBotExpandedWindow('message_thread', {
                conv_key: cKey,
                conv_id: cId,
                account_id: aId
            }, 1040, 840);
        }

        // 5. Create New SMS Modal -> Expanded View
        function openExpandedCreateNewSmsWindow(event) {
            if (event) event.stopPropagation();
            const phone = document.getElementById('new-sms-recipient-phone')?.value || '';
            const name = document.getElementById('new-sms-recipient-name')?.value || '';
            const sim = document.getElementById('new-sms-sim-slot')?.value || '2';
            const body = document.getElementById('new-sms-message-body')?.value || '';
            try {
                localStorage.setItem('gb_popout_new_sms_cache', JSON.stringify({
                    phone,
                    name,
                    sim,
                    body,
                    saved_at: Date.now()
                }));
            } catch (_) {}

            const popup = openGlennBotExpandedWindow('new_sms', {
                phone: phone
            }, 820, 780);

            if (popup && typeof closeCreateNewSmsModal === 'function') {
                closeCreateNewSmsModal();
            }
        }

        // 6. Compose New Email Modal -> Expanded View
        function openExpandedComposeEmailWindow(event) {
            if (event) event.stopPropagation();
            const accountId = document.getElementById('compose-email-sender-select')?.value || (typeof activeEmailAccountId !== 'undefined' ? activeEmailAccountId : '') || '';
            const to = document.getElementById('compose-email-to')?.value || '';
            const cc = document.getElementById('compose-email-cc')?.value || '';
            const subject = document.getElementById('compose-email-subject')?.value || '';
            const body = document.getElementById('compose-email-body')?.value || '';
            try {
                localStorage.setItem('gb_popout_compose_email_cache', JSON.stringify({
                    account_id: accountId,
                    to,
                    cc,
                    subject,
                    body,
                    saved_at: Date.now()
                }));
            } catch (_) {}

            const popup = openGlennBotExpandedWindow('compose_email', {
                account_id: accountId
            }, 860, 800);

            if (popup && typeof closeComposeEmailModal === 'function') {
                closeComposeEmailModal();
            }
        }

        // 7. Files Vault Modal -> Expanded View
        function openExpandedFilesVaultWindow(event) {
            if (event) event.stopPropagation();
            const searchVal = document.getElementById('vault-files-search')?.value || '';
            try {
                localStorage.setItem('gb_popout_files_vault_cache', JSON.stringify({
                    search: searchVal,
                    saved_at: Date.now()
                }));
            } catch (_) {}

            openGlennBotExpandedWindow('files_vault', {
                search: searchVal
            }, 1220, 840);
        }

        function setGlennBotPopoutBarHeader(titleText, subtitleText, iconClass = 'fa-external-link-square-alt') {
            const bar = document.getElementById('gb-popout-window-bar');
            const titleEl = document.getElementById('gb-popout-window-title');
            const subEl = document.getElementById('gb-popout-window-subtitle');
            const iconEl = document.getElementById('gb-popout-window-icon');
            const closeLbl = document.getElementById('gb-popout-close-label');

            if (bar) {
                bar.classList.remove('hidden');
                bar.classList.add('flex');
            }
            if (titleEl && titleText) titleEl.textContent = titleText;
            if (subEl && subtitleText) subEl.textContent = subtitleText;
            if (iconEl && iconClass) iconEl.className = `fas ${iconClass} text-sm`;
            if (closeLbl) {
                const isRealPopup = Boolean(window.opener && !window.opener.closed);
                closeLbl.textContent = isRealPopup ? 'Close Window' : 'Exit Expanded View';
            }
            if (titleText) {
                document.title = `${titleText} • GlennBot Automations`;
            }
        }

        async function refreshGlennBotPopoutWindow() {
            const mode = window.gbActivePopoutMode;
            const p = window.gbActivePopoutParams || {};
            if (mode === 'comment_thread') {
                await fetchComments(true);
                if (p.record_id) renderSelectedCommentDetail(p.record_id, true);
            } else if (mode === 'message_thread') {
                await fetchConversations(true);
                if (p.conv_key || p.conv_id) {
                    selectMessageConversation(p.conv_key || '', p.conv_id || '', p.account_id || '');
                }
            } else if (mode === 'spreadsheet') {
                if (typeof syncActiveSpreadsheetFromGoogleDriveNow === 'function') {
                    await syncActiveSpreadsheetFromGoogleDriveNow(true);
                }
            } else if (mode === 'email_view') {
                if (typeof refreshActiveEmailInbox === 'function') {
                    await refreshActiveEmailInbox(true, false);
                }
                if (p.message_id && typeof renderExpandedEmailModalContent === 'function') {
                    renderExpandedEmailModalContent(p.message_id);
                }
            } else if (mode === 'files_vault') {
                if (typeof fetchVaultFiles === 'function') {
                    await fetchVaultFiles(true);
                }
            } else if (mode === 'new_sms') {
                if (typeof fetchTextbeeStatusSilently === 'function') {
                    await fetchTextbeeStatusSilently(true);
                    showToast('🔄 Refreshed TextBee SIM 2 Gateway status!');
                }
            } else if (mode === 'compose_email') {
                if (typeof fetchEmailAccounts === 'function') {
                    await fetchEmailAccounts(true);
                    populateComposeEmailSenderSelect(p.account_id || '');
                    showToast('🔄 Refreshed Connected Email Accounts!');
                }
            } else if (mode === 'modal_popout') {
                const modalId = String(p.modal_id || '').trim();
                await initOrRefreshGenericModalData(modalId, true);
                showToast('🔄 Refreshed Expanded Modal View!');
            } else if (mode === 'workspace_view') {
                const tab = String(p.tab || '').trim();
                if (tab === 'scheduler') {
                    if (typeof fetchSocialAccounts === 'function') await fetchSocialAccounts();
                    if (typeof updatePreviews === 'function') updatePreviews();
                } else if (tab === 'queue' && typeof fetchScheduledPosts === 'function') {
                    await fetchScheduledPosts();
                } else if (tab === 'calendar') {
                    if (typeof fetchScheduledPosts === 'function') await fetchScheduledPosts();
                    if (typeof fetchComposioCalendarEvents === 'function') await fetchComposioCalendarEvents(true);
                } else if (tab === 'analytics' && typeof fetchAnalyticsData === 'function') {
                    await fetchAnalyticsData(true);
                } else if (tab === 'contacts' && typeof fetchCrmContacts === 'function') {
                    await fetchCrmContacts(true);
                } else if (tab === 'automations' && typeof initAutomationsCanvasView === 'function') {
                    await initAutomationsCanvasView();
                } else if (tab === 'comments' && typeof fetchComments === 'function') {
                    await fetchComments(true);
                } else if (tab === 'messages' && typeof fetchConversations === 'function') {
                    await fetchConversations(true);
                } else if (tab === 'email' && typeof refreshActiveEmailInbox === 'function') {
                    await refreshActiveEmailInbox(true, false);
                }
                showToast('🔄 Refreshed Expanded Workspace Window!');
            }
        }

        // Metadata registry for all overlay modals and workspace views
        const GB_MODAL_POPOUT_META = {
            'settings-modal': {
                title: 'Automation & Notification Settings — Expanded View',
                subtitle: 'Bandwidth Saver Mode, Sound Alerts & Background Polling Controls',
                icon: 'fa-cog',
                width: 760,
                height: 760,
                closeFn: () => { if (typeof closeSettingsModal === 'function') closeSettingsModal(); }
            },
            'connect-accounts-modal': {
                title: 'Connect & Manage Accounts — Expanded View',
                subtitle: 'Social Profiles, Email Accounts (Gmail/IMAP) & TextBee.dev SMS Gateway',
                icon: 'fa-plug',
                width: 1080,
                height: 840,
                closeFn: () => { if (typeof closeConnectAccountsModal === 'function') closeConnectAccountsModal(); }
            },
            'external-api-manager-modal': {
                title: 'Manage External API Keys — Expanded View',
                subtitle: 'Multi-Workspace Zernio & Cloudinary API Failover Configuration',
                icon: 'fa-key',
                width: 960,
                height: 820,
                closeFn: () => { if (typeof closeManageApiModal === 'function') closeManageApiModal(); }
            },
            'external-api-error-modal': {
                title: 'External API Account Limit Notice — Expanded View',
                subtitle: 'Workspace Plan & Failover API Key Diagnostic',
                icon: 'fa-exclamation-triangle',
                width: 680,
                height: 620,
                closeFn: () => { if (typeof closeExternalApiErrorModal === 'function') closeExternalApiErrorModal(); }
            },
            'internal-api-n8n-modal': {
                title: 'GlennBot Internal API & n8n Automation Hub — Expanded View',
                subtitle: 'Webhook Event Emitter, Custom Header Auth & Full REST API Reference',
                icon: 'fa-network-wired',
                width: 1180,
                height: 860,
                closeFn: () => { if (typeof closeInternalApiModal === 'function') closeInternalApiModal(); }
            },
            'ask-ai-n8n-modal': {
                title: 'AI Workflow Architect (n8n JSON Generator) — Expanded View',
                subtitle: 'Generate Ready-to-Import n8n Workflow JSON Powered by GlennBot AI',
                icon: 'fa-robot',
                width: 960,
                height: 820,
                closeFn: () => { if (typeof closeAskAiN8nModal === 'function') closeAskAiN8nModal(); }
            },
            'comment-dm-modal': {
                title: 'Send Direct Message to Commenter — Expanded View',
                subtitle: 'Private Follow-Up DM Dispatch Linked to Comment Thread',
                icon: 'fa-paper-plane',
                width: 720,
                height: 680,
                closeFn: () => { if (typeof closeCommentDmModal === 'function') closeCommentDmModal(); }
            },
            'create-post-media-source-modal': {
                title: 'Select Media Upload Source — Expanded View',
                subtitle: 'Upload from Local Device or Import from Google Drive Files Vault',
                icon: 'fa-photo-video',
                width: 920,
                height: 760,
                closeFn: () => { if (typeof closeCreatePostMediaSourceModal === 'function') closeCreatePostMediaSourceModal(); }
            },
            'ask-ai-modal': {
                title: 'Ask AI • Content & Caption Generator — Expanded View',
                subtitle: 'AI Copywriting, Hashtags & Multi-Platform Caption Studio',
                icon: 'fa-magic',
                width: 860,
                height: 800,
                closeFn: () => { if (typeof closeAskAiModal === 'function') closeAskAiModal(); }
            },
            'preset-modal': {
                title: 'Saved Account Presets — Expanded View',
                subtitle: 'Load or Manage Custom Multi-Account Publishing Presets',
                icon: 'fa-bookmark',
                width: 680,
                height: 680,
                closeFn: () => { if (typeof closePresetModal === 'function') closePresetModal(); }
            },
            'day-modal': {
                title: 'Calendar Day Breakdown — Expanded View',
                subtitle: 'Scheduled Social Posts, Video Meetings & Daily Agenda',
                icon: 'fa-calendar-day',
                width: 820,
                height: 780,
                closeFn: () => { if (typeof closeDayModal === 'function') closeDayModal(); }
            },
            'schedule-meeting-modal': {
                title: 'Schedule Calendar Appointment / Video Meeting — Expanded View',
                subtitle: 'Google Meet, Zoom & Microsoft Teams Auto-Link + Multi-Channel Invites',
                icon: 'fa-video',
                width: 900,
                height: 840,
                closeFn: () => { if (typeof closeScheduleMeetingModal === 'function') closeScheduleMeetingModal(); }
            },
            'reschedule-meeting-modal': {
                title: 'Reschedule Appointment — Expanded View',
                subtitle: 'Update Date/Time & Dispatch Automated Reschedule Notice',
                icon: 'fa-calendar-alt',
                width: 820,
                height: 800,
                closeFn: () => { if (typeof closeRescheduleMeetingModal === 'function') closeRescheduleMeetingModal(); }
            },
            'cancel-meeting-modal': {
                title: 'Cancel Appointment & Send Notice — Expanded View',
                subtitle: 'Remove Calendar Booking & Notify Attendees via Email/SMS',
                icon: 'fa-calendar-times',
                width: 720,
                height: 680,
                closeFn: () => { if (typeof closeCancelMeetingModal === 'function') closeCancelMeetingModal(); }
            },
            'email-webhook-modal': {
                title: 'Real-Time Email Webhook & Forwarding Setup — Expanded View',
                subtitle: 'Instant Inbound Email Push Endpoint for Gmail, Outlook & Custom Domains',
                icon: 'fa-satellite-dish',
                width: 880,
                height: 780,
                closeFn: () => { if (typeof closeEmailWebhookModal === 'function') closeEmailWebhookModal(); }
            },
            'crm-contact-modal': {
                title: 'CRM Contact Record — Expanded View',
                subtitle: 'Add or Edit Unified Client Profile (Phone, Email, Social & Notes)',
                icon: 'fa-address-card',
                width: 860,
                height: 800,
                closeFn: () => { if (typeof closeCrmContactModal === 'function') closeCrmContactModal(); }
            },
            'crm-open-chat-platform-modal': {
                title: 'Open Direct Chat Channel — Expanded View',
                subtitle: 'Select Social Platform or SMS Gateway for Contact Conversation',
                icon: 'fa-comments',
                width: 680,
                height: 640,
                closeFn: () => { if (typeof closeCrmOpenChatPlatformModal === 'function') closeCrmOpenChatPlatformModal(); }
            }
        };

        const GB_WORKSPACE_VIEW_META = {
            'scheduler': {
                title: 'Create & Schedule Post — Expanded View',
                subtitle: 'Multi-Platform Publisher, Media Studio & AI Caption Workspace',
                icon: 'fa-paper-plane',
                width: 1240,
                height: 860
            },
            'queue': {
                title: 'Publishing Queue & History — Expanded View',
                subtitle: 'Live Scheduled, Published & Draft Social Posts Monitor',
                icon: 'fa-stream',
                width: 1220,
                height: 840
            },
            'calendar': {
                title: 'Content & Meetings Calendar — Expanded View',
                subtitle: 'Unified Monthly Schedule for Social Media Posts & Video Appointments',
                icon: 'fa-calendar-alt',
                width: 1260,
                height: 860
            },
            'analytics': {
                title: 'Social & Automation Analytics — Expanded View',
                subtitle: 'Cross-Platform Engagement, Reach & Publishing Performance',
                icon: 'fa-chart-line',
                width: 1240,
                height: 860
            },
            'contacts': {
                title: 'CRM Contacts Database — Expanded View',
                subtitle: 'Unified Directory of Social Leads, Email Senders & SMS Contacts',
                icon: 'fa-address-book',
                width: 1260,
                height: 860
            },
            'automations': {
                title: 'GlennBot Native Automations Hub — Expanded View',
                subtitle: '24/7 Server-Side Auto-Reply Rules for Comments, DMs, SMS & Emails',
                icon: 'fa-bolt',
                width: 1260,
                height: 860
            },
            'comments': {
                title: 'Social Comments Inbox — Expanded View',
                subtitle: 'Multi-Platform Post Comments & Automated Reply Monitor',
                icon: 'fa-comment-dots',
                width: 1260,
                height: 860
            },
            'messages': {
                title: 'Unified Direct Messages & SMS Inbox — Expanded View',
                subtitle: 'Facebook, Instagram, Telegram & TextBee SIM 2 Conversations',
                icon: 'fa-comments',
                width: 1260,
                height: 860
            },
            'email': {
                title: 'Multi-Account Email Hub — Expanded View',
                subtitle: 'Live IMAP/Gmail Inbox, Sent Folder & Instant Reply Workspace',
                icon: 'fa-envelope',
                width: 1260,
                height: 860
            }
        };

        function captureElementFormControlsSnapshot(rootEl) {
            const controls = [];
            if (!rootEl) return controls;
            const fields = rootEl.querySelectorAll('input, textarea, select');
            fields.forEach((el, idx) => {
                const type = String(el.type || '').toLowerCase();
                if (type === 'file' || type === 'password') return;
                controls.push({
                    id: el.id || '',
                    name: el.name || '',
                    idx: idx,
                    type: type,
                    value: el.value,
                    checked: Boolean(el.checked)
                });
            });
            return controls;
        }

        function restoreElementFormControlsSnapshot(rootEl, controls) {
            if (!rootEl || !Array.isArray(controls) || controls.length === 0) return;
            const fields = rootEl.querySelectorAll('input, textarea, select');
            controls.forEach(item => {
                let target = null;
                if (item.id) {
                    target = rootEl.querySelector(`#${CSS.escape(item.id)}`) || document.getElementById(item.id);
                }
                if (!target && typeof item.idx === 'number' && fields[item.idx]) {
                    target = fields[item.idx];
                }
                if (!target) return;
                const type = String(target.type || '').toLowerCase();
                if (type === 'checkbox' || type === 'radio') {
                    target.checked = Boolean(item.checked);
                } else if (type !== 'file') {
                    target.value = item.value ?? '';
                }
            });
        }

        // 8. Generic Overlay Modal -> Expanded View (Triggered on Double-Click)
        function openExpandedGenericModalWindow(modalId, event) {
            if (event) event.stopPropagation();
            const cleanId = String(modalId || '').trim();
            if (!cleanId) return;

            // Route modals that already have specialized Expanded View handlers
            if (cleanId === 'compose-email-modal') return openExpandedComposeEmailWindow(event);
            if (cleanId === 'create-new-sms-modal') return openExpandedCreateNewSmsWindow(event);
            if (cleanId === 'expanded-email-modal') return openExpandedEmailWindow(null, event);

            const modalEl = document.getElementById(cleanId);
            if (!modalEl) return;

            const meta = GB_MODAL_POPOUT_META[cleanId] || {};
            const headerTitleEl = modalEl.querySelector('h2, h3');
            const headerSubEl = modalEl.querySelector('p');
            const fallbackTitle = headerTitleEl ? `${headerTitleEl.textContent.trim()} — Expanded View` : 'Modal — Expanded View';
            const fallbackSub = headerSubEl ? headerSubEl.textContent.trim() : 'Focused Standalone Modal Window';

            const extraContext = {
                connect_tab: (typeof activeConnectModalTab !== 'undefined') ? activeConnectModalTab : 'social',
                day_modal_date: (typeof selectedDayModalDate !== 'undefined') ? selectedDayModalDate : '',
                comment_dm_target: (typeof activeCommentDmTarget !== 'undefined') ? activeCommentDmTarget : null,
                crm_contact_id: document.getElementById('crm-contact-id')?.value || '',
                crm_chat_contact_id: (typeof activeCrmChatSelectorContactId !== 'undefined') ? activeCrmChatSelectorContactId : '',
                resched_event_id: document.getElementById('resched-cal-event-id')?.value || '',
                cancel_event_id: document.getElementById('cancel-cal-event-id')?.value || '',
                sched_platform: document.querySelector('input[name="sched_meeting_platform"]:checked')?.value || 'google_meet',
                internal_api_tab: !document.getElementById('internal-api-pane-endpoints')?.classList.contains('hidden') ? 'endpoints' : 'webhook'
            };

            try {
                localStorage.setItem('gb_popout_generic_modal_cache', JSON.stringify({
                    modal_id: cleanId,
                    title: meta.title || fallbackTitle,
                    subtitle: meta.subtitle || fallbackSub,
                    icon: meta.icon || 'fa-window-restore',
                    controls: captureElementFormControlsSnapshot(modalEl),
                    context: extraContext,
                    saved_at: Date.now()
                }));
            } catch (_) {}

            const popup = openGlennBotExpandedWindow(
                'modal_popout',
                { modal_id: cleanId },
                meta.width || 880,
                meta.height || 780
            );

            // If opened in a separate popup window, close the overlay modal in the parent window
            if (popup && typeof meta.closeFn === 'function') {
                meta.closeFn();
            }
        }

        // 9. Workspace Tab View -> Expanded View (Triggered on Double-Clicking Left Sidebar Navigation Buttons)
        function openExpandedWorkspaceViewWindow(tabName, event) {
            if (event) event.stopPropagation();
            const cleanTab = String(tabName || '').trim();
            if (!cleanTab) return;

            if (activeTab !== cleanTab && typeof switchTab === 'function') {
                switchTab(cleanTab);
            }

            if (cleanTab === 'spreadsheet') return openExpandedSpreadsheetWindow(event);
            if (cleanTab === 'files') return openExpandedFilesVaultWindow(event);

            const viewEl = document.getElementById(`view-${cleanTab}`);
            const meta = GB_WORKSPACE_VIEW_META[cleanTab] || {
                title: `${cleanTab.toUpperCase()} — Expanded View`,
                subtitle: 'Standalone Workspace Window',
                icon: 'fa-window-restore',
                width: 1240,
                height: 860
            };

            try {
                localStorage.setItem('gb_popout_workspace_view_cache', JSON.stringify({
                    tab: cleanTab,
                    controls: captureElementFormControlsSnapshot(viewEl),
                    saved_at: Date.now()
                }));
            } catch (_) {}

            openGlennBotExpandedWindow(
                'workspace_view',
                { tab: cleanTab },
                meta.width || 1240,
                meta.height || 860
            );
        }

        async function initOrRefreshGenericModalData(modalId, isRefresh = false, cachedContext = {}) {
            const ctx = cachedContext || {};
            try {
                if (modalId === 'settings-modal' && typeof openSettingsModal === 'function') {
                    openSettingsModal();
                } else if (modalId === 'connect-accounts-modal' && typeof openConnectAccountsModal === 'function') {
                    await openConnectAccountsModal(ctx.connect_tab || 'social');
                } else if (modalId === 'external-api-manager-modal' && typeof openManageApiModal === 'function') {
                    await openManageApiModal();
                } else if (modalId === 'internal-api-n8n-modal' && typeof openInternalApiModal === 'function') {
                    await openInternalApiModal();
                    if (ctx.internal_api_tab && typeof switchInternalApiTab === 'function') {
                        switchInternalApiTab(ctx.internal_api_tab);
                    }
                } else if (modalId === 'ask-ai-n8n-modal' && typeof openAskAiN8nModal === 'function') {
                    openAskAiN8nModal();
                } else if (modalId === 'comment-dm-modal') {
                    if (ctx.comment_dm_target && typeof openCommentDmModal === 'function') {
                        const t = ctx.comment_dm_target;
                        openCommentDmModal(t.commentId || '', t.recordId || '', t.authorName || '', t.authorHandle || '', t.platform || '', t.accountId || '', t.authorId || '');
                    }
                } else if (modalId === 'create-post-media-source-modal' && typeof openCreatePostMediaSourceModal === 'function') {
                    openCreatePostMediaSourceModal('scheduler');
                } else if (modalId === 'ask-ai-modal' && typeof openAskAiModal === 'function') {
                    openAskAiModal();
                } else if (modalId === 'preset-modal' && typeof openLoadPresetModal === 'function') {
                    openLoadPresetModal();
                } else if (modalId === 'day-modal' && typeof openDayModal === 'function') {
                    if (!isRefresh && typeof fetchCalendarEvents === 'function') await fetchCalendarEvents(false);
                    const targetDate = ctx.day_modal_date || new Date().toISOString().slice(0, 10);
                    openDayModal(targetDate);
                } else if (modalId === 'schedule-meeting-modal' && typeof openScheduleMeetingModal === 'function') {
                    openScheduleMeetingModal();
                } else if (modalId === 'reschedule-meeting-modal' && typeof openRescheduleMeetingModal === 'function') {
                    if (typeof fetchCalendarEvents === 'function') await fetchCalendarEvents(false);
                    if (ctx.resched_event_id) openRescheduleMeetingModal(ctx.resched_event_id);
                } else if (modalId === 'cancel-meeting-modal' && typeof openCancelMeetingModal === 'function') {
                    if (typeof fetchCalendarEvents === 'function') await fetchCalendarEvents(false);
                    if (ctx.cancel_event_id) openCancelMeetingModal(ctx.cancel_event_id);
                } else if (modalId === 'email-webhook-modal' && typeof openEmailWebhookModal === 'function') {
                    openEmailWebhookModal();
                } else if (modalId === 'crm-contact-modal' && typeof openCrmContactModal === 'function') {
                    if (ctx.crm_contact_id && typeof fetchCrmContacts === 'function') {
                        await fetchCrmContacts(false);
                    }
                    openCrmContactModal(ctx.crm_contact_id || null);
                } else if (modalId === 'crm-open-chat-platform-modal' && typeof openCrmChatPlatformSelector === 'function') {
                    if (typeof fetchCrmContacts === 'function') await fetchCrmContacts(false);
                    if (ctx.crm_chat_contact_id) openCrmChatPlatformSelector(ctx.crm_chat_contact_id);
                }
            } catch (err) {
                console.warn('initOrRefreshGenericModalData error:', err);
            }
        }

        function closeGlennBotPopoutWindow() {
            const isUrlPopout = Boolean(getUrlPopoutParams());
            if (isUrlPopout && window.opener && !window.opener.closed) {
                window.close();
                return;
            }
            if (isUrlPopout) {
                try { window.close(); } catch (_) {}
                window.location.href = window.location.pathname;
                return;
            }

            // Restore in-page fallback mode back to normal dashboard layout
            window.gbActivePopoutMode = '';
            window.gbActivePopoutParams = {};
            window.gbIsInPageFocusFallback = false;
            document.title = 'GlennBot Automations';

            const bar = document.getElementById('gb-popout-window-bar');
            if (bar) {
                bar.classList.add('hidden');
                bar.classList.remove('flex');
            }
            document.getElementById('main-dashboard-header')?.classList.remove('hidden');
            document.getElementById('left-nav-sidebar')?.classList.remove('hidden');
            document.getElementById('main-workspace-wrapper')?.classList.remove('hidden');
            document.querySelector('main')?.classList.remove('hidden');

            // Restore Comments split columns
            document.getElementById('comments-top-filter-bar')?.classList.remove('hidden');
            document.getElementById('comments-left-column')?.classList.remove('hidden');
            const cDetail = document.getElementById('comment-detail-panel');
            if (cDetail) {
                cDetail.classList.remove('w-full', 'lg:w-full');
                cDetail.classList.add('lg:w-7/12');
                if (cDetail.dataset.recordId && typeof renderSelectedCommentDetail === 'function') {
                    renderSelectedCommentDetail(cDetail.dataset.recordId, false);
                }
            }

            // Restore Messages split columns
            document.getElementById('messages-top-filter-bar')?.classList.remove('hidden');
            document.getElementById('messages-left-column')?.classList.remove('hidden');
            const mDetail = document.getElementById('message-detail-panel');
            if (mDetail) {
                mDetail.classList.remove('w-full', 'lg:w-full');
                mDetail.classList.add('lg:w-7/12');
                if (typeof renderActiveConversationThread === 'function') {
                    renderActiveConversationThread(false);
                }
            }

            // Restore Spread Sheet & Files Expanded View buttons
            document.getElementById('btn-ss-expanded-view')?.classList.remove('hidden');
            document.getElementById('btn-files-expanded-view')?.classList.remove('hidden');

            // Restore any generic modal that was converted to full-window mode
            document.querySelectorAll('[data-gb-orig-modal-class]').forEach(modalEl => {
                modalEl.className = modalEl.getAttribute('data-gb-orig-modal-class') || '';
                modalEl.classList.add('hidden');
                modalEl.removeAttribute('data-gb-orig-modal-class');
                const inner = modalEl.firstElementChild;
                if (inner && inner.hasAttribute('data-gb-orig-inner-class')) {
                    inner.className = inner.getAttribute('data-gb-orig-inner-class') || '';
                    inner.removeAttribute('data-gb-orig-inner-class');
                }
            });

            // Restore modals if they were converted to full-window mode
            const expEmailModal = document.getElementById('expanded-email-modal');
            if (expEmailModal) {
                expEmailModal.className = 'fixed inset-0 z-[9995] hidden bg-black/85 backdrop-blur-md flex items-center justify-center p-2 sm:p-4';
                const inner = document.getElementById('expanded-email-modal-content');
                if (inner) {
                    inner.className = 'glass-panel rounded-2xl w-full max-w-5xl h-[92vh] overflow-hidden border border-gb-cyan/60 shadow-[0_0_50px_rgba(0,240,255,0.25)] flex flex-col bg-slate-950';
                }
            }

            const smsModal = document.getElementById('create-new-sms-modal');
            if (smsModal) {
                smsModal.className = 'fixed inset-0 z-[9997] hidden bg-black/85 backdrop-blur-md flex items-center justify-center p-3 sm:p-4';
                const inner = smsModal.firstElementChild;
                if (inner) {
                    inner.className = 'glass-panel rounded-2xl w-full max-w-xl overflow-hidden border border-emerald-400/60 shadow-[0_0_50px_rgba(16,185,129,0.28)] flex flex-col max-h-[92vh] bg-slate-950';
                }
                document.getElementById('btn-new-sms-expanded-view')?.classList.remove('hidden');
                document.getElementById('btn-new-sms-close')?.classList.remove('hidden');
            }

            const compModal = document.getElementById('compose-email-modal');
            if (compModal) {
                compModal.className = 'fixed inset-0 z-[9994] hidden bg-black/80 backdrop-blur-md flex items-center justify-center p-3 sm:p-4';
                const inner = compModal.firstElementChild;
                if (inner) {
                    inner.className = 'glass-panel rounded-2xl w-full max-w-xl overflow-hidden border border-gb-cyan/60 shadow-[0_0_45px_rgba(0,240,255,0.25)] flex flex-col max-h-[92vh]';
                }
                document.getElementById('btn-compose-email-expanded-view')?.classList.remove('hidden');
                document.getElementById('btn-compose-email-close')?.classList.remove('hidden');
            }
        }

        async function applyGlennBotPopoutLayout(mode, params = {}) {
            const cleanMode = String(mode || '').trim();
            if (!cleanMode) return;

            window.gbActivePopoutMode = cleanMode;
            window.gbActivePopoutParams = params || {};

            // Hide main navigation chrome so the window looks and feels like a dedicated OAuth/App Window
            document.getElementById('main-dashboard-header')?.classList.add('hidden');
            document.getElementById('left-nav-sidebar')?.classList.add('hidden');

            // 1. COMMENT THREAD EXPANDED WINDOW
            if (cleanMode === 'comment_thread') {
                setGlennBotPopoutBarHeader(
                    'Post Thread — Expanded View',
                    'Focused on Post Media, Original Caption, Comment Thread & Direct Reply',
                    'fa-comments'
                );
                let targetRecordId = String(params.record_id || '').trim();
                let cachedDraft = '';
                try {
                    const raw = localStorage.getItem('gb_popout_comment_thread_cache');
                    if (raw) {
                        const parsed = JSON.parse(raw);
                        if (!targetRecordId && parsed.record_id) targetRecordId = String(parsed.record_id);
                        if (!params.comment_id && parsed.comment_id && typeof selectedCommentId !== 'undefined') {
                            selectedCommentId = String(parsed.comment_id);
                        }
                        if (parsed.draft_reply) cachedDraft = String(parsed.draft_reply);
                    }
                } catch (_) {}

                if (targetRecordId && typeof selectedRecordId !== 'undefined') {
                    selectedRecordId = targetRecordId;
                }
                if (params.comment_id && typeof selectedCommentId !== 'undefined') {
                    selectedCommentId = String(params.comment_id);
                }

                switchTab('comments', true);
                document.getElementById('comments-top-filter-bar')?.classList.add('hidden');
                document.getElementById('comments-left-column')?.classList.add('hidden');
                const cDetail = document.getElementById('comment-detail-panel');
                if (cDetail) {
                    cDetail.classList.remove('lg:w-7/12');
                    cDetail.classList.add('w-full', 'lg:w-full', 'flex-1');
                }

                // Fetch live Zernio-reconciled comments for this post once with selectedRecordId already set
                if (typeof fetchComments === 'function') {
                    await fetchComments(false);
                }

                if (targetRecordId && typeof renderSelectedCommentDetail === 'function') {
                    await renderSelectedCommentDetail(targetRecordId, true);
                    if (cachedDraft) {
                        const inputEl = document.getElementById('comment-reply-input');
                        if (inputEl && !inputEl.value) inputEl.value = cachedDraft;
                    }
                }
                return;
            }

            // 2. SPREADSHEET EXPANDED WINDOW (FOR SELECTED SPREADSHEET)
            if (cleanMode === 'spreadsheet') {
                switchTab('spreadsheet');
                document.getElementById('btn-ss-expanded-view')?.classList.add('hidden');

                let targetWbId = String(params.workbook_id || '').trim();
                let targetSheetIdx = parseInt(String(params.sheet_idx || '0'), 10) || 0;
                let cachedWb = null;
                try {
                    const raw = localStorage.getItem('gb_popout_spreadsheet_cache');
                    if (raw) {
                        const parsed = JSON.parse(raw);
                        if (!targetWbId && parsed.workbook_id) targetWbId = String(parsed.workbook_id);
                        if (typeof parsed.active_sheet_index === 'number') targetSheetIdx = parsed.active_sheet_index;
                        if (parsed.workbook) cachedWb = parsed.workbook;
                    }
                } catch (_) {}

                if (cachedWb && typeof loadWorkbookObjectIntoEditor === 'function') {
                    loadWorkbookObjectIntoEditor(cachedWb);
                    if (targetSheetIdx > 0 && typeof switchSpreadsheetSheetTab === 'function') {
                        switchSpreadsheetSheetTab(targetSheetIdx);
                    }
                }
                if (targetWbId && typeof onSelectSavedSpreadsheetWorkbook === 'function') {
                    await onSelectSavedSpreadsheetWorkbook(targetWbId);
                    if (targetSheetIdx > 0 && typeof switchSpreadsheetSheetTab === 'function') {
                        switchSpreadsheetSheetTab(targetSheetIdx);
                    }
                }

                const wbTitle = currentSpreadsheetWorkbook?.title || 'Untitled_Spreadsheet.xlsx';
                setGlennBotPopoutBarHeader(
                    `Spread Sheet — ${wbTitle}`,
                    'Focused Spreadsheet Window • Two-Way Live Sync with Google Drive & Files Vault',
                    'fa-file-excel'
                );
                return;
            }

            // 3. EMAIL VIEW EXPANDED WINDOW
            if (cleanMode === 'email_view') {
                switchTab('email', true);
                let targetAccId = String(params.account_id || '').trim();
                let targetMsgId = String(params.message_id || '').trim();
                let cachedMsg = null;
                let cachedDraft = '';
                try {
                    const raw = localStorage.getItem('gb_popout_email_view_cache');
                    if (raw) {
                        const parsed = JSON.parse(raw);
                        if (!targetAccId && parsed.account_id) targetAccId = String(parsed.account_id);
                        if (!targetMsgId && parsed.message_id) targetMsgId = String(parsed.message_id);
                        if (parsed.message) cachedMsg = parsed.message;
                        if (parsed.draft_reply) cachedDraft = String(parsed.draft_reply);
                    }
                } catch (_) {}

                if (targetAccId && typeof activeEmailAccountId !== 'undefined') {
                    activeEmailAccountId = targetAccId;
                }
                if (cachedMsg && typeof activeEmailMessages !== 'undefined' && Array.isArray(activeEmailMessages)) {
                    if (!activeEmailMessages.some(m => String(m.id) === String(cachedMsg.id))) {
                        activeEmailMessages.unshift(cachedMsg);
                    }
                }

                // Hide the background workspace and display #expanded-email-modal as a full-window workspace
                document.getElementById('main-workspace-wrapper')?.classList.add('hidden');
                document.querySelector('main')?.classList.add('hidden');
                const expEmailModal = document.getElementById('expanded-email-modal');
                const expEmailContent = document.getElementById('expanded-email-modal-content');
                if (expEmailModal && expEmailContent) {
                    expEmailModal.className = 'flex-1 w-full min-h-0 flex flex-col overflow-hidden';
                    expEmailContent.className = 'glass-panel rounded-2xl w-full flex-1 min-h-0 overflow-hidden border border-gb-cyan/60 shadow-[0_0_30px_rgba(0,240,255,0.18)] flex flex-col bg-slate-950';
                }

                if (targetMsgId && typeof openExpandedEmailModal === 'function') {
                    openExpandedEmailModal(targetMsgId);
                }

                if (!cachedMsg && typeof fetchEmailAccounts === 'function') {
                    await fetchEmailAccounts(false);
                    if (targetAccId) activeEmailAccountId = targetAccId;
                    if (typeof refreshActiveEmailInbox === 'function') {
                        await refreshActiveEmailInbox(false, false);
                    }
                    if (targetMsgId && typeof openExpandedEmailModal === 'function') {
                        openExpandedEmailModal(targetMsgId);
                    }
                }

                if (cachedDraft) {
                    const replyInput = document.getElementById('expanded-email-reply-input');
                    if (replyInput && !replyInput.value) replyInput.value = cachedDraft;
                }

                const activeMsg = (typeof activeEmailMessages !== 'undefined' && Array.isArray(activeEmailMessages))
                    ? activeEmailMessages.find(m => String(m.id) === targetMsgId)
                    : cachedMsg;
                setGlennBotPopoutBarHeader(
                    activeMsg?.subject ? `Email: ${activeMsg.subject}` : 'Expanded Email View',
                    activeMsg?.sender ? `From: ${activeMsg.sender}` : 'Focused Standalone Email Reader & Reply Composer',
                    'fa-envelope-open-text'
                );
                return;
            }

            // 4. MESSAGE THREAD EXPANDED WINDOW
            if (cleanMode === 'message_thread') {
                switchTab('messages', true);
                document.getElementById('messages-top-filter-bar')?.classList.add('hidden');
                document.getElementById('messages-left-column')?.classList.add('hidden');
                const mDetail = document.getElementById('message-detail-panel');
                if (mDetail) {
                    mDetail.classList.remove('lg:w-7/12');
                    mDetail.classList.add('w-full', 'lg:w-full', 'flex-1');
                }

                let cKey = String(params.conv_key || '').trim();
                let cId = String(params.conv_id || '').trim();
                let aId = String(params.account_id || '').trim();
                const targetPlat = String(params.platform || '').trim().toLowerCase();
                const targetAccName = String(params.account_name || '').trim().toLowerCase();
                const autoLatest = ['1', 'true', 'yes'].includes(String(params.auto_latest || '').trim().toLowerCase()) || Boolean((targetPlat || targetAccName) && !cId);
                const waitForNewParam = String(params.wait_for_new ?? params.fresh_session ?? '').trim().toLowerCase();
                const waitForNew = autoLatest && !['0', 'false', 'no'].includes(waitForNewParam);
                const rawSinceTs = Number(params.since_ts || params._ts || 0);
                const sessionStartTs = (rawSinceTs && !Number.isNaN(rawSinceTs) && rawSinceTs > 1000000000000)
                    ? rawSinceTs
                    : Date.now();

                if (autoLatest) {
                    if (!window._gbPopoutAutoLatestConfig || !window._gbPopoutAutoLatestConfig.enabled) {
                        window._gbPopoutAutoLatestConfig = {
                            enabled: true,
                            wait_for_new: waitForNew,
                            session_start_ts: sessionStartTs,
                            platform: targetPlat || 'facebook',
                            account_id: aId || '6af0b109818eb5c88d1e87a6',
                            account_name: targetAccName || 'glennbot automations',
                            display_account_name: String(params.account_name || 'GlennBot Automations').trim() || 'GlennBot Automations',
                            baseline_captured: false,
                            baseline_map: {},
                            locked_conv_key: '',
                            locked_conv_id: '',
                            locked_account_id: ''
                        };
                    }
                }

                let cachedDraft = '';
                if (!autoLatest) {
                    try {
                        const raw = localStorage.getItem('gb_popout_message_thread_cache');
                        if (raw) {
                            const parsed = JSON.parse(raw);
                            if (!cKey && parsed.conv_key) cKey = String(parsed.conv_key);
                            if (!cId && parsed.conv_id) cId = String(parsed.conv_id);
                            if (!aId && parsed.account_id) aId = String(parsed.account_id);
                            if (parsed.draft_message) cachedDraft = String(parsed.draft_message);
                            if (parsed.conversation && typeof activeConversationObj !== 'undefined') {
                                activeConversationObj = parsed.conversation;
                            }
                            if (Array.isArray(parsed.messages) && typeof activeConversationMessages !== 'undefined') {
                                activeConversationMessages = parsed.messages;
                            }
                        }
                    } catch (_) {}
                }

                if (autoLatest && waitForNew) {
                    const cfg = window._gbPopoutAutoLatestConfig;
                    if (!cfg.locked_conv_key) {
                        selectedConversationKey = null;
                        selectedConversationId = null;
                        selectedConversationAccountId = null;
                        activeConversationObj = null;
                        activeConversationMessages = [];
                        if (typeof renderBlankWaitingConversationStandby === 'function') {
                            renderBlankWaitingConversationStandby(cfg.display_account_name, cfg.platform);
                        }
                        setGlennBotPopoutBarHeader(
                            `Chat with ${cfg.display_account_name} — Live Messenger Session`,
                            'Blank Session Ready • Send a message on Facebook Messenger to start chatting live',
                            'fa-comments'
                        );
                    }
                    if (typeof fetchConversations === 'function') {
                        await fetchConversations(false);
                    }
                    return;
                }

                if (autoLatest && typeof fetchConversations === 'function') {
                    await fetchConversations(false);
                    if (Array.isArray(messagesConversationsList) && messagesConversationsList.length > 0) {
                        const matchingConvs = messagesConversationsList.filter(c => {
                            const cPlat = String(c.platform || '').trim().toLowerCase();
                            const cAccId = String(c.account_id || '').trim();
                            const cAccName = String(c.account_name || '').trim().toLowerCase();
                            if (targetPlat && cPlat !== targetPlat) return false;
                            if (aId && cAccId === aId) return true;
                            if (targetAccName && cAccName.includes(targetAccName)) return true;
                            return !aId && !targetAccName;
                        });
                        if (matchingConvs.length > 0) {
                            const latestConv = matchingConvs[0];
                            cKey = String(latestConv.conv_key || '');
                            cId = String(latestConv.conversation_id || '');
                            aId = String(latestConv.account_id || aId);
                        }
                    }
                }

                if (typeof activeConversationObj !== 'undefined' && activeConversationObj && typeof renderActiveConversationThread === 'function') {
                    renderActiveConversationThread(true);
                }
                if ((cKey || cId) && typeof selectMessageConversation === 'function') {
                    await selectMessageConversation(cKey, cId, aId);
                }
                if (cachedDraft) {
                    const inputEl = document.getElementById('direct-message-input');
                    if (inputEl && !inputEl.value) inputEl.value = cachedDraft;
                }

                const pName = (typeof activeConversationObj !== 'undefined' && activeConversationObj?.participant_name)
                    ? activeConversationObj.participant_name
                    : 'Direct Message Thread';
                setGlennBotPopoutBarHeader(
                    `Chat with ${pName} — Expanded View`,
                    'Focused Conversation Window • Real-Time Direct Messaging & Replies',
                    'fa-comments'
                );
                return;
            }

            // 5. CREATE NEW SMS EXPANDED WINDOW
            if (cleanMode === 'new_sms') {
                setGlennBotPopoutBarHeader(
                    'Create New SMS (TextBee.dev • SIM 2) — Expanded View',
                    'Dedicated Outbound SMS Composer Window',
                    'fa-sms'
                );
                document.getElementById('main-workspace-wrapper')?.classList.add('hidden');
                document.querySelector('main')?.classList.add('hidden');
                const smsModal = document.getElementById('create-new-sms-modal');
                if (smsModal) {
                    smsModal.className = 'flex-1 w-full min-h-0 flex flex-col overflow-hidden';
                    const inner = smsModal.firstElementChild;
                    if (inner) {
                        inner.className = 'glass-panel rounded-2xl w-full flex-1 min-h-0 overflow-y-auto border border-emerald-400/60 shadow-[0_0_35px_rgba(16,185,129,0.2)] flex flex-col bg-slate-950';
                    }
                    document.getElementById('btn-new-sms-expanded-view')?.classList.add('hidden');
                    document.getElementById('btn-new-sms-close')?.classList.add('hidden');
                }

                let cached = {};
                try {
                    cached = JSON.parse(localStorage.getItem('gb_popout_new_sms_cache') || '{}') || {};
                } catch (_) {}

                const prefillPhone = String(params.phone || cached.phone || '').trim();
                const prefillName = String(cached.name || '').trim();
                if (typeof openCreateNewSmsModal === 'function') {
                    await openCreateNewSmsModal(prefillPhone, prefillName);
                }
                if (cached.body) {
                    const msgInput = document.getElementById('new-sms-message-body');
                    if (msgInput) {
                        msgInput.value = cached.body;
                        if (typeof updateNewSmsCharCount === 'function') updateNewSmsCharCount();
                    }
                }
                return;
            }

            // 6. COMPOSE NEW EMAIL EXPANDED WINDOW
            if (cleanMode === 'compose_email') {
                setGlennBotPopoutBarHeader(
                    'Compose New Email — Expanded View',
                    'Dedicated Outbound Email Composer Window',
                    'fa-paper-plane'
                );
                document.getElementById('main-workspace-wrapper')?.classList.add('hidden');
                document.querySelector('main')?.classList.add('hidden');
                const compModal = document.getElementById('compose-email-modal');
                if (compModal) {
                    compModal.className = 'flex-1 w-full min-h-0 flex flex-col overflow-hidden';
                    const inner = compModal.firstElementChild;
                    if (inner) {
                        inner.className = 'glass-panel rounded-2xl w-full flex-1 min-h-0 overflow-y-auto border border-gb-cyan/60 shadow-[0_0_35px_rgba(0,240,255,0.2)] flex flex-col bg-slate-950';
                    }
                    document.getElementById('btn-compose-email-expanded-view')?.classList.add('hidden');
                    document.getElementById('btn-compose-email-close')?.classList.add('hidden');
                }

                let cached = {};
                try {
                    cached = JSON.parse(localStorage.getItem('gb_popout_compose_email_cache') || '{}') || {};
                } catch (_) {}

                if (typeof openComposeEmailModal === 'function') {
                    await openComposeEmailModal(cached.to || '');
                }
                const targetAcc = String(params.account_id || cached.account_id || '').trim();
                if (targetAcc && typeof populateComposeEmailSenderSelect === 'function') {
                    populateComposeEmailSenderSelect(targetAcc);
                }
                if (cached.cc) {
                    const ccEl = document.getElementById('compose-email-cc');
                    if (ccEl) ccEl.value = cached.cc;
                }
                if (cached.subject) {
                    const subEl = document.getElementById('compose-email-subject');
                    if (subEl) subEl.value = cached.subject;
                }
                if (cached.body) {
                    const bodyEl = document.getElementById('compose-email-body');
                    if (bodyEl) {
                        bodyEl.value = cached.body;
                        bodyEl.rows = 12;
                    }
                }
                return;
            }

            // 7. FILES VAULT EXPANDED WINDOW
            if (cleanMode === 'files_vault') {
                setGlennBotPopoutBarHeader(
                    'Files Vault (Google Drive API) — Expanded View',
                    'Dedicated Standalone File Manager & Python File ID Generator',
                    'fa-folder-open'
                );
                switchTab('files', true);
                document.getElementById('btn-files-expanded-view')?.classList.add('hidden');

                let searchVal = String(params.search || '').trim();
                if (!searchVal) {
                    try {
                        const cached = JSON.parse(localStorage.getItem('gb_popout_files_vault_cache') || '{}') || {};
                        if (cached.search) searchVal = String(cached.search);
                    } catch (_) {}
                }
                const searchInput = document.getElementById('vault-files-search');
                if (searchInput && searchVal) {
                    searchInput.value = searchVal;
                }
                if (typeof fetchVaultFiles === 'function') {
                    await fetchVaultFiles(false);
                }
                return;
            }

            // 8. ANY OVERLAY MODAL EXPANDED WINDOW (DOUBLE-CLICK POPOUT)
            if (cleanMode === 'modal_popout') {
                let targetModalId = String(params.modal_id || '').trim();
                let cached = {};
                try {
                    cached = JSON.parse(localStorage.getItem('gb_popout_generic_modal_cache') || '{}') || {};
                    if (!targetModalId && cached.modal_id) targetModalId = String(cached.modal_id);
                } catch (_) {}

                const modalEl = targetModalId ? document.getElementById(targetModalId) : null;
                if (!modalEl) return;

                const meta = GB_MODAL_POPOUT_META[targetModalId] || {};
                const headerTitleEl = modalEl.querySelector('h2, h3');
                const headerSubEl = modalEl.querySelector('p');
                const titleText = meta.title || cached.title || (headerTitleEl ? `${headerTitleEl.textContent.trim()} — Expanded View` : 'Expanded Modal Window');
                const subText = meta.subtitle || cached.subtitle || (headerSubEl ? headerSubEl.textContent.trim() : 'Dedicated Standalone Modal Window');
                const iconClass = meta.icon || cached.icon || 'fa-window-restore';

                setGlennBotPopoutBarHeader(titleText, subText, iconClass);

                // Hide background workspace so the modal fills the OAuth-style window cleanly
                document.getElementById('main-workspace-wrapper')?.classList.add('hidden');
                document.querySelector('main')?.classList.add('hidden');

                // Initialize the modal data/handlers first
                await initOrRefreshGenericModalData(targetModalId, false, cached.context || {});

                // Convert modal overlay & inner glass-panel into full-window standalone layout
                if (!modalEl.hasAttribute('data-gb-orig-modal-class')) {
                    modalEl.setAttribute('data-gb-orig-modal-class', modalEl.className);
                }
                modalEl.className = 'flex-1 w-full min-h-0 flex flex-col overflow-hidden';

                const inner = modalEl.firstElementChild;
                if (inner) {
                    if (!inner.hasAttribute('data-gb-orig-inner-class')) {
                        inner.setAttribute('data-gb-orig-inner-class', inner.className);
                    }
                    inner.className = 'glass-panel rounded-2xl w-full flex-1 min-h-0 overflow-y-auto border border-gb-cyan/50 shadow-[0_0_35px_rgba(0,240,255,0.18)] flex flex-col bg-slate-950 p-5 sm:p-6';
                }

                // Restore any form inputs the user was typing before double-clicking
                if (Array.isArray(cached.controls) && cached.controls.length > 0 && cached.modal_id === targetModalId) {
                    restoreElementFormControlsSnapshot(modalEl, cached.controls);
                    if (targetModalId === 'schedule-meeting-modal' && cached.context?.sched_platform && typeof onChangeScheduleMeetingPlatform === 'function') {
                        onChangeScheduleMeetingPlatform(cached.context.sched_platform);
                    }
                }
                return;
            }

            // 9. ANY MAIN WORKSPACE VIEW EXPANDED WINDOW (DOUBLE-CLICK POPOUT)
            if (cleanMode === 'workspace_view') {
                const targetTab = String(params.tab || 'scheduler').trim();
                const meta = GB_WORKSPACE_VIEW_META[targetTab] || {
                    title: `${targetTab.toUpperCase()} — Expanded View`,
                    subtitle: 'Dedicated Standalone Workspace Window',
                    icon: 'fa-window-restore'
                };
                setGlennBotPopoutBarHeader(meta.title, meta.subtitle, meta.icon);
                switchTab(targetTab);

                try {
                    const cached = JSON.parse(localStorage.getItem('gb_popout_workspace_view_cache') || '{}') || {};
                    if (cached.tab === targetTab && Array.isArray(cached.controls)) {
                        const viewEl = document.getElementById(`view-${targetTab}`);
                        restoreElementFormControlsSnapshot(viewEl, cached.controls);
                    }
                } catch (_) {}
                return;
            }
        }

        async function applyGlennBotPopoutModeIfPresent() {
            const parsed = getUrlPopoutParams();
            if (!parsed || !parsed.mode) return false;
            await applyGlennBotPopoutLayout(parsed.mode, parsed.params);
            return true;
        }

        function applyInstantPopoutChromeHideIfPresent() {
            const parsed = getUrlPopoutParams();
            if (!parsed || !parsed.mode) return;
            window.gbActivePopoutMode = String(parsed.mode || '').trim();
            window.gbActivePopoutParams = parsed.params || {};
            document.getElementById('main-dashboard-header')?.classList.add('hidden');
            document.getElementById('left-nav-sidebar')?.classList.add('hidden');
        }

        // Double-Click Expanded View Listener — ONLY on Left Sidebar Navigation Menu Buttons (#left-nav-sidebar)
        function initGlennBotDoubleClickExpandedView() {
            if (window.gbDblClickExpandedInitialized) return;
            window.gbDblClickExpandedInitialized = true;

            const sidebar = document.getElementById('left-nav-sidebar');
            if (!sidebar) return;

            sidebar.addEventListener('dblclick', (e) => {
                if (window.gbActivePopoutMode) return;
                const target = e.target;
                if (!target || typeof target.closest !== 'function') return;

                // If button already has an explicit inline ondblclick handler, let that handler run once without duplicating
                if (target.closest('[ondblclick]')) return;

                const tabBtn = target.closest('button[id^="tab-btn-"]');
                if (tabBtn) {
                    const tabName = tabBtn.id.replace(/^tab-btn-/, '');
                    if (tabName) {
                        openExpandedWorkspaceViewWindow(tabName, e);
                    }
                }
            });
        }

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                initGlennBotDoubleClickExpandedView();
                applyInstantPopoutChromeHideIfPresent();
            });
        } else {
            initGlennBotDoubleClickExpandedView();
            applyInstantPopoutChromeHideIfPresent();
        }


