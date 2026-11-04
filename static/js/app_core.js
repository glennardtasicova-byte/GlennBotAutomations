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
            const toggleKeys = [
                'instantBackgroundQueue',
                'autoClearAfterLaunch',
                'fadeEffects',
                'popupNotifications',
                'soundEffects'
            ];
            toggleKeys.forEach(k => {
                const btn = document.getElementById(`setting-btn-${k}`);
                const knob = document.getElementById(`setting-knob-${k}`);
                const isOn = Boolean(userSettings[k]);
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
            if (!(key in userSettings)) return;
            userSettings[key] = !userSettings[key];
            saveUserSettings(true);
            if (key === 'soundEffects' && userSettings.soundEffects) {
                playNotificationSound(true);
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
        function switchTab(tabName) {
            activeTab = tabName;
            hidePostTooltip();
            const tabs = ['scheduler', 'calendar', 'queue', 'messages', 'comments', 'analytics', 'email', 'contacts', 'files', 'spreadsheet', 'automations'];
            tabs.forEach(t => {
                const viewEl = document.getElementById(`view-${t}`);
                const btnEl = document.getElementById(`tab-btn-${t}`);
                if (viewEl) viewEl.classList.toggle('hidden', t !== tabName);
                if (btnEl) btnEl.classList.toggle('active', t === tabName);
            });
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
                    if (p.media_preview_url.match(/\.(mp4|mov|webm|mkv|avi)(?:$|\?)/i) && p.post_type !== 'image') {
                        mediaThumb = `<a href="${p.media_preview_url}" target="_blank" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-600 text-gb-cyan text-xs whitespace-nowrap"><i class="fas fa-play-circle"></i> View Video</a>`;
                    } else {
                        mediaThumb = `<a href="${p.media_preview_url}" target="_blank" class="block w-11 h-11 rounded-lg overflow-hidden border border-slate-600 hover:border-gb-cyan transition-all"><img src="${p.media_preview_url}" class="w-full h-full object-cover" onerror="this.outerHTML='<span class=\\'text-xs text-gb-cyan p-1\\'>Media</span>'"></a>`;
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

