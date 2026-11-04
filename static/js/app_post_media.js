        // --- CREATE POST MEDIA & PREVIEW LOGIC (LOCAL DEVICE OR GOOGLE DRIVE "FILES" VAULT -> ZERNIO) ---
        function clearObjectUrls() { objectUrls.forEach(url => URL.revokeObjectURL(url)); objectUrls = []; }

        let activeCreatePostMediaTarget = {
            context: 'create_post',
            inputId: '',
            containerId: '',
            type: 'video',
            platform: ''
        };
        let createPostVaultFilterMatchingOnly = true;
        let selectedCreatePostVaultGridIds = new Set();

        // Attachment state for Messages Modal (FB/IG/Telegram/WhatsApp) and Send a DM to Commenter Modal
        let activeChatAttachment = null;
        let activeCommentDmAttachment = null;

        function formatAttachmentSizeBytes(bytes) {
            const b = Number(bytes || 0);
            if (!b || b <= 0) return '';
            if (b < 1024) return `${b} B`;
            if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
            return `${(b / (1024 * 1024)).toFixed(2)} MB`;
        }

        function detectAttachmentMediaType(filename, mimeType) {
            const ct = String(mimeType || '').toLowerCase();
            const fn = String(filename || '').toLowerCase();
            if (ct.startsWith('image/') || /\.(jpg|jpeg|png|webp|gif|bmp)$/i.test(fn)) return 'image';
            if (ct.startsWith('video/') || /\.(mp4|mov|webm|mkv|avi|m4v)$/i.test(fn)) return 'video';
            return 'file';
        }

        function buildAttachmentPreviewCardHTML(att, context) {
            if (!att) return '';
            const isVault = att.source === 'vault';
            const mType = att.media_type || detectAttachmentMediaType(att.filename, att.content_type);
            const pUrl = att.preview_url || '';
            let thumbHTML = `
                <div class="w-11 h-11 rounded-lg bg-slate-900 border border-slate-700 flex items-center justify-center text-gb-cyan shrink-0">
                    <i class="fas fa-file-alt text-base"></i>
                </div>
            `;
            if (mType === 'image' && pUrl) {
                thumbHTML = `
                    <div class="w-11 h-11 rounded-lg bg-black border border-gb-cyan/40 overflow-hidden shrink-0">
                        <img src="${escapeHTML(pUrl)}" class="w-full h-full object-cover" onerror="this.style.display='none'">
                    </div>
                `;
            } else if (mType === 'video' && pUrl) {
                thumbHTML = `
                    <div class="w-11 h-11 rounded-lg bg-black border border-gb-cyan/40 overflow-hidden shrink-0 relative flex items-center justify-center">
                        <video src="${escapeHTML(pUrl)}" muted playsinline class="w-full h-full object-cover"></video>
                        <i class="fas fa-play-circle text-white/90 text-xs absolute"></i>
                    </div>
                `;
            }

            const sourceBadgeHTML = isVault
                ? `<span class="px-2 py-0.5 rounded bg-emerald-950/90 border border-emerald-500/50 text-emerald-300 font-mono text-[10px] inline-flex items-center gap-1"><i class="fab fa-google-drive text-emerald-400"></i>Files Modal • ${escapeHTML(att.file_id || '')}</span>`
                : `<span class="px-2 py-0.5 rounded bg-gb-cyan/15 border border-gb-cyan/40 text-gb-cyan font-mono text-[10px] inline-flex items-center gap-1"><i class="fas fa-laptop"></i>Local Device</span>`;

            return `
                <div class="p-2.5 rounded-xl bg-slate-950/95 border ${isVault ? 'border-emerald-500/50' : 'border-gb-cyan/50'} flex items-center justify-between gap-2.5 shadow-md">
                    <div class="flex items-center gap-2.5 min-w-0 flex-1">
                        ${thumbHTML}
                        <div class="min-w-0 flex-1">
                            <div class="flex flex-wrap items-center gap-1.5">
                                <span class="text-xs font-bold text-white truncate max-w-[200px] sm:max-w-[260px]" title="${escapeHTML(att.filename || 'Attached File')}">${escapeHTML(att.filename || 'Attached File')}</span>
                                ${sourceBadgeHTML}
                            </div>
                            <p class="text-[10px] text-slate-400 mt-0.5">
                                ${escapeHTML(att.size_formatted || '')} ${att.size_formatted ? '•' : ''} Ready to send with message
                            </p>
                        </div>
                    </div>
                    <div class="flex items-center gap-1.5 shrink-0">
                        <button type="button" onclick="openAttachmentSourceModal('${escapeHTML(context)}', event)"
                            class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-gb-cyan hover:text-slate-950 border border-slate-600 text-[10px] font-bold text-slate-200 flex items-center gap-1 transition-all"
                            title="Replace attached file">
                            <i class="fas fa-sync-alt text-[9px]"></i>
                            <span>Replace</span>
                        </button>
                        <button type="button" onclick="clearAttachmentForContext('${escapeHTML(context)}')"
                            class="w-7 h-7 rounded-lg bg-rose-950/80 hover:bg-rose-600 border border-rose-500/60 text-rose-200 hover:text-white flex items-center justify-center text-xs transition-all"
                            title="Remove attached file">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                </div>
            `;
        }

        function refreshAttachmentPreviewUI(context) {
            if (context === 'comment_dm') {
                const el = document.getElementById('comment-dm-attachment-preview');
                if (!el) return;
                if (activeCommentDmAttachment) {
                    el.innerHTML = buildAttachmentPreviewCardHTML(activeCommentDmAttachment, 'comment_dm');
                    el.classList.remove('hidden');
                } else {
                    el.innerHTML = '';
                    el.classList.add('hidden');
                }
            } else if (context === 'messages_chat') {
                const el = document.getElementById('chat-composer-attachment-preview');
                if (!el) return;
                if (activeChatAttachment) {
                    el.innerHTML = buildAttachmentPreviewCardHTML(activeChatAttachment, 'messages_chat');
                    el.classList.remove('hidden');
                } else {
                    el.innerHTML = '';
                    el.classList.add('hidden');
                }
            }
        }

        function clearAttachmentForContext(context) {
            if (context === 'comment_dm') {
                if (activeCommentDmAttachment && activeCommentDmAttachment.objectUrl) {
                    URL.revokeObjectURL(activeCommentDmAttachment.objectUrl);
                }
                activeCommentDmAttachment = null;
                const inp = document.getElementById('comment-dm-local-file-input');
                if (inp) inp.value = '';
                refreshAttachmentPreviewUI('comment_dm');
            } else if (context === 'messages_chat') {
                if (activeChatAttachment && activeChatAttachment.objectUrl) {
                    URL.revokeObjectURL(activeChatAttachment.objectUrl);
                }
                activeChatAttachment = null;
                const inp = document.getElementById('chat-composer-local-file-input');
                if (inp) inp.value = '';
                refreshAttachmentPreviewUI('messages_chat');
            }
        }

        function handleChatComposerLocalFileSelected(inputEl) {
            if (!inputEl || !inputEl.files || inputEl.files.length === 0) return;
            const file = inputEl.files[0];
            if (activeChatAttachment && activeChatAttachment.objectUrl) {
                URL.revokeObjectURL(activeChatAttachment.objectUrl);
            }
            const objUrl = URL.createObjectURL(file);
            activeChatAttachment = {
                source: 'local',
                localFile: file,
                filename: file.name,
                content_type: file.type || 'application/octet-stream',
                media_type: detectAttachmentMediaType(file.name, file.type),
                size_formatted: formatAttachmentSizeBytes(file.size),
                preview_url: objUrl,
                objectUrl: objUrl
            };
            refreshAttachmentPreviewUI('messages_chat');
            showToast(`📎 Attached "${file.name}" from Local Device!`);
        }

        function handleCommentDmLocalFileSelected(inputEl) {
            if (!inputEl || !inputEl.files || inputEl.files.length === 0) return;
            const file = inputEl.files[0];
            if (activeCommentDmAttachment && activeCommentDmAttachment.objectUrl) {
                URL.revokeObjectURL(activeCommentDmAttachment.objectUrl);
            }
            const objUrl = URL.createObjectURL(file);
            activeCommentDmAttachment = {
                source: 'local',
                localFile: file,
                filename: file.name,
                content_type: file.type || 'application/octet-stream',
                media_type: detectAttachmentMediaType(file.name, file.type),
                size_formatted: formatAttachmentSizeBytes(file.size),
                preview_url: objUrl,
                objectUrl: objUrl
            };
            refreshAttachmentPreviewUI('comment_dm');
            showToast(`📎 Attached "${file.name}" from Local Device!`);
        }

        async function uploadLocalAttachmentForDmOrChat(fileObj, platform = 'facebook', accountId = '') {
            const formData = new FormData();
            formData.append('file', fileObj);
            formData.append('platform', platform || 'facebook');
            formData.append('account_id', accountId || '');

            const res = await fetch('/api/messages/upload_attachment', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (!res.ok || data.status !== 'success' || !data.media_url) {
                throw new Error(data.message || 'Failed to upload attachment file.');
            }
            return data;
        }

        function openAttachmentSourceModal(context, event) {
            if (event) event.stopPropagation();
            hidePostTooltip();

            const isCommentDm = context === 'comment_dm';
            const inputId = isCommentDm ? 'comment-dm-local-file-input' : 'chat-composer-local-file-input';
            const plat = isCommentDm
                ? (activeCommentDmTarget?.platform || 'facebook')
                : (activeConversationObj?.platform || 'facebook');

            activeCreatePostMediaTarget = {
                context: isCommentDm ? 'comment_dm' : 'messages_chat',
                inputId: inputId,
                containerId: '',
                type: 'any',
                platform: plat
            };
            createPostVaultFilterMatchingOnly = false;
            selectedCreatePostVaultGridIds = new Set();

            const titleEl = document.getElementById('cp-media-source-modal-title');
            const badgeEl = document.getElementById('cp-media-source-target-badge');
            const iconEl = document.getElementById('cp-media-source-header-icon');
            const stepChoice = document.getElementById('cp-media-source-step-choice');
            const stepVault = document.getElementById('cp-media-source-step-vault');
            const searchInput = document.getElementById('cp-vault-search-input');

            if (titleEl) {
                titleEl.textContent = isCommentDm ? 'Attach File to Direct Message' : 'Attach File to Chat Message';
            }
            if (badgeEl) {
                badgeEl.textContent = isCommentDm
                    ? `SEND A DM • ${(plat || 'META').toUpperCase()}`
                    : `MESSAGES • ${(plat || 'CHAT').toUpperCase()}`;
            }
            if (iconEl) {
                iconEl.className = 'fas fa-paperclip text-lg';
            }
            if (searchInput) searchInput.value = '';
            if (stepChoice) stepChoice.classList.remove('hidden');
            if (stepVault) stepVault.classList.add('hidden');

            updateCreatePostVaultChoiceCountPill();
            const modal = document.getElementById('create-post-media-source-modal');
            if (modal) openModalWithFade(modal);

            if (!Array.isArray(vaultFilesList) || vaultFilesList.length === 0) {
                fetchVaultFiles(false).then(() => {
                    updateCreatePostVaultChoiceCountPill();
                }).catch(() => {});
            }
        }

        function isVaultFileMatchingCreatePostType(fileObj, targetType) {
            if (!fileObj) return false;
            if (targetType === 'any') return true;
            const ct = String(fileObj.content_type || '').toLowerCase();
            const fn = String(fileObj.filename || '').toLowerCase();
            if (targetType === 'video') {
                return ct.startsWith('video/') || /\.(mp4|mov|webm|mkv|avi|m4v)$/i.test(fn);
            }
            if (targetType === 'image' || targetType === 'grid') {
                return ct.startsWith('image/') || /\.(jpg|jpeg|png|webp|gif|bmp)$/i.test(fn);
            }
            return true;
        }

        function updateCreatePostVaultChoiceCountPill() {
            const pill = document.getElementById('cp-vault-choice-count-pill');
            if (!pill) return;
            const list = Array.isArray(vaultFilesList) ? vaultFilesList : [];
            const tType = activeCreatePostMediaTarget.type || 'video';
            if (tType === 'any') {
                pill.textContent = `${list.length} Ready File(s) • Drive → Zernio`;
                return;
            }
            const matchingCount = list.filter(f => isVaultFileMatchingCreatePostType(f, tType)).length;
            const typeWord = tType === 'video' ? 'Video(s)' : 'Image(s)';
            pill.textContent = `${matchingCount} Ready ${typeWord} • Drive → Zernio`;
        }

        function openCreatePostMediaSourceModal(inputId, containerId, type, event) {
            if (event) event.stopPropagation();
            hidePostTooltip();

            const isThumb = String(inputId || '').startsWith('thumb-');
            const plat = String(inputId || '').replace(/^(media-|thumb-)/, '');
            activeCreatePostMediaTarget = {
                context: 'create_post',
                inputId: inputId || '',
                containerId: containerId || '',
                type: type || 'video',
                platform: plat
            };
            createPostVaultFilterMatchingOnly = true;
            selectedCreatePostVaultGridIds = new Set();

            if (type === 'grid' && plat && currentDraftState.vaultMediaItems && Array.isArray(currentDraftState.vaultMediaItems[plat])) {
                currentDraftState.vaultMediaItems[plat].forEach(it => {
                    if (it && it.file_id) selectedCreatePostVaultGridIds.add(String(it.file_id));
                });
            }

            const titleEl = document.getElementById('cp-media-source-modal-title');
            const badgeEl = document.getElementById('cp-media-source-target-badge');
            const iconEl = document.getElementById('cp-media-source-header-icon');
            const stepChoice = document.getElementById('cp-media-source-step-choice');
            const stepVault = document.getElementById('cp-media-source-step-vault');
            const searchInput = document.getElementById('cp-vault-search-input');

            const labelText = isThumb
                ? 'Cover / Thumbnail Image'
                : (type === 'video' ? 'Video File' : (type === 'grid' ? 'Album Image(s)' : 'Image File'));
            if (titleEl) titleEl.textContent = `Upload ${labelText}`;
            if (badgeEl) badgeEl.textContent = `${(plat || 'POST').toUpperCase()} • ${labelText.toUpperCase()}`;
            if (iconEl) {
                iconEl.className = type === 'video'
                    ? 'fas fa-film text-lg'
                    : (type === 'grid' ? 'fas fa-images text-lg' : 'fas fa-image text-lg');
            }
            if (searchInput) searchInput.value = '';
            if (stepChoice) stepChoice.classList.remove('hidden');
            if (stepVault) stepVault.classList.add('hidden');

            updateCreatePostVaultChoiceCountPill();
            const modal = document.getElementById('create-post-media-source-modal');
            if (modal) openModalWithFade(modal);

            // Background refresh if vault list hasn't been loaded yet
            if (!Array.isArray(vaultFilesList) || vaultFilesList.length === 0) {
                fetchVaultFiles(false).then(() => {
                    updateCreatePostVaultChoiceCountPill();
                }).catch(() => {});
            }
        }

        function closeCreatePostMediaSourceModal() {
            const modal = document.getElementById('create-post-media-source-modal');
            if (modal) closeModalWithFade(modal);
        }

        function chooseCreatePostMediaFromLocalDevice() {
            const targetInputId = activeCreatePostMediaTarget.inputId;
            closeCreatePostMediaSourceModal();
            if (targetInputId) {
                const inputEl = document.getElementById(targetInputId);
                if (inputEl) inputEl.click();
            }
        }

        function backToCreatePostMediaSourceChoice() {
            const stepChoice = document.getElementById('cp-media-source-step-choice');
            const stepVault = document.getElementById('cp-media-source-step-vault');
            if (stepChoice) stepChoice.classList.remove('hidden');
            if (stepVault) stepVault.classList.add('hidden');
            updateCreatePostVaultChoiceCountPill();
        }

        async function showCreatePostVaultPickerStep() {
            const stepChoice = document.getElementById('cp-media-source-step-choice');
            const stepVault = document.getElementById('cp-media-source-step-vault');
            if (stepChoice) stepChoice.classList.add('hidden');
            if (stepVault) stepVault.classList.remove('hidden');

            updateCreatePostVaultFilterButtonUI();
            renderCreatePostVaultPickerList();

            if (!Array.isArray(vaultFilesList) || vaultFilesList.length === 0) {
                await refreshCreatePostVaultPickerFiles();
            }
        }

        function updateCreatePostVaultFilterButtonUI() {
            const labelEl = document.getElementById('cp-vault-filter-toggle-label');
            const btnEl = document.getElementById('cp-vault-filter-toggle-btn');
            const tType = activeCreatePostMediaTarget.type || 'video';
            if (labelEl) {
                if (createPostVaultFilterMatchingOnly && tType !== 'any') {
                    labelEl.textContent = tType === 'video' ? 'Showing: Videos Only' : 'Showing: Images Only';
                } else {
                    labelEl.textContent = 'Showing: All Vault Files';
                }
            }
            if (btnEl) {
                btnEl.className = (createPostVaultFilterMatchingOnly && tType !== 'any')
                    ? 'px-2.5 py-1.5 rounded-lg bg-emerald-950/80 hover:bg-emerald-900/70 border border-emerald-500/50 text-[11px] font-semibold text-emerald-300 flex items-center gap-1.5 transition-all'
                    : 'px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-600 text-[11px] font-semibold text-slate-300 flex items-center gap-1.5 transition-all';
            }
        }

        function toggleCreatePostVaultFilterMode() {
            createPostVaultFilterMatchingOnly = !createPostVaultFilterMatchingOnly;
            updateCreatePostVaultFilterButtonUI();
            renderCreatePostVaultPickerList();
        }

        async function refreshCreatePostVaultPickerFiles() {
            const icon = document.getElementById('cp-vault-refresh-icon');
            if (icon) icon.classList.add('fa-spin');
            try {
                await fetchVaultFiles(true);
                updateCreatePostVaultChoiceCountPill();
                renderCreatePostVaultPickerList();
            } finally {
                if (icon) icon.classList.remove('fa-spin');
            }
        }

        function updateConfirmGridVaultButtonUI() {
            const btn = document.getElementById('cp-vault-confirm-grid-btn');
            const lbl = document.getElementById('cp-vault-confirm-grid-label');
            if (!btn || !lbl) return;
            if (activeCreatePostMediaTarget.type === 'grid') {
                const count = selectedCreatePostVaultGridIds.size;
                btn.classList.remove('hidden');
                lbl.textContent = `Use Selected Images (${count}) → Zernio`;
                btn.disabled = count === 0;
                btn.classList.toggle('opacity-50', count === 0);
            } else {
                btn.classList.add('hidden');
            }
        }

        function renderCreatePostVaultPickerList() {
            const listContainer = document.getElementById('cp-vault-picker-list');
            if (!listContainer) return;

            updateConfirmGridVaultButtonUI();

            const query = (document.getElementById('cp-vault-search-input')?.value || '').trim().toLowerCase();
            const targetType = activeCreatePostMediaTarget.type || 'video';
            const allFiles = Array.isArray(vaultFilesList) ? vaultFilesList : [];

            const filtered = allFiles.filter(f => {
                if (createPostVaultFilterMatchingOnly && !isVaultFileMatchingCreatePostType(f, targetType)) {
                    return false;
                }
                if (!query) return true;
                const hay = `${f.file_id || ''} ${f.filename || ''} ${f.notes || ''} ${f.content_type || ''}`.toLowerCase();
                return hay.includes(query);
            });

            if (filtered.length === 0) {
                const totalCount = allFiles.length;
                listContainer.innerHTML = `
                    <div class="p-8 rounded-2xl bg-slate-950/70 border border-dashed border-slate-700 text-center space-y-3">
                        <div class="w-12 h-12 rounded-2xl bg-slate-900 border border-slate-700 flex items-center justify-center text-slate-400 mx-auto">
                            <i class="fab fa-google-drive text-xl"></i>
                        </div>
                        <div class="space-y-1">
                            <p class="text-xs sm:text-sm font-bold text-white">
                                ${totalCount === 0 ? 'No files in your Google Drive "Files" Vault yet' : `No matching ${targetType === 'video' ? 'video' : (targetType === 'any' ? 'vault' : 'image')} files found`}
                            </p>
                            <p class="text-[11px] text-slate-400 max-w-md mx-auto">
                                ${totalCount === 0
                                    ? 'Upload videos or images in the "Files" modal first so they get a reusable Google Drive Python File ID (file_...) with live preview, or upload directly from your Local Device.'
                                    : 'Try clearing your search or click "Showing: Videos/Images Only" above to view all files in your Google Drive Vault.'}
                            </p>
                        </div>
                        <div class="flex flex-wrap items-center justify-center gap-2 pt-1">
                            <button type="button" onclick="chooseCreatePostMediaFromLocalDevice()" class="px-3.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-gb-cyan/50 text-xs font-semibold text-gb-cyan flex items-center gap-1.5 transition-all">
                                <i class="fas fa-laptop"></i>
                                <span>Browse Local Device Instead</span>
                            </button>
                            <button type="button" onclick="closeCreatePostMediaSourceModal(); switchTab('files');" class="px-3.5 py-1.5 rounded-xl bg-emerald-950/90 hover:bg-emerald-900/80 border border-emerald-500/50 text-xs font-semibold text-emerald-300 flex items-center gap-1.5 transition-all">
                                <i class="fab fa-google-drive"></i>
                                <span>Go to "Files" Modal</span>
                            </button>
                        </div>
                    </div>
                `;
                return;
            }

            const isGrid = targetType === 'grid';

            listContainer.innerHTML = filtered.map(f => {
                const fid = String(f.file_id || '');
                const fname = f.filename || 'file';
                const ctype = String(f.content_type || '').toLowerCase();
                const isImg = ctype.startsWith('image/') || /\.(jpg|jpeg|png|webp|gif|bmp)$/i.test(fname);
                const isVid = ctype.startsWith('video/') || /\.(mp4|mov|webm|mkv|avi|m4v)$/i.test(fname);
                const pUrl = f.preview_url || f.download_url || (`/api/files/${encodeURIComponent(fid)}/stream`);
                const isChecked = isGrid && selectedCreatePostVaultGridIds.has(fid);

                let thumbPreviewHTML = `
                    <div class="w-16 h-16 rounded-xl bg-slate-900 border border-slate-700 flex items-center justify-center text-slate-400 shrink-0">
                        <i class="fas fa-file text-lg"></i>
                    </div>
                `;
                if (isImg && pUrl) {
                    thumbPreviewHTML = `
                        <div class="w-16 h-16 rounded-xl bg-black border border-emerald-500/40 overflow-hidden shrink-0 flex items-center justify-center relative">
                            <img src="${escapeHTML(pUrl)}" alt="${escapeHTML(fname)}" class="w-full h-full object-cover" loading="lazy" onerror="this.style.display='none'">
                        </div>
                    `;
                } else if (isVid && pUrl) {
                    thumbPreviewHTML = `
                        <div class="w-16 h-16 rounded-xl bg-black border border-gb-cyan/50 overflow-hidden shrink-0 flex items-center justify-center relative">
                            <video src="${escapeHTML(pUrl)}#t=0.5" preload="metadata" muted playsinline class="w-full h-full object-cover"></video>
                            <div class="absolute inset-0 bg-black/25 flex items-center justify-center pointer-events-none">
                                <i class="fas fa-play-circle text-white/90 text-sm drop-shadow"></i>
                            </div>
                        </div>
                    `;
                }

                return `
                    <div class="p-3 rounded-xl bg-slate-900/90 hover:bg-slate-800/90 border ${isChecked ? 'border-emerald-400 bg-emerald-950/20' : 'border-slate-700/90 hover:border-gb-cyan/50'} flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 transition-all">
                        <div class="flex items-center gap-3 min-w-0 flex-1">
                            ${isGrid ? `
                                <input type="checkbox" ${isChecked ? 'checked' : ''} onchange="toggleVaultGridFileCheckbox('${escapeHTML(fid)}', this.checked)" class="w-4 h-4 rounded accent-emerald-400 cursor-pointer shrink-0">
                            ` : ''}
                            ${thumbPreviewHTML}
                            <div class="min-w-0 flex-1">
                                <div class="flex flex-wrap items-center gap-1.5">
                                    <span class="text-xs sm:text-sm font-bold text-white truncate max-w-[260px]" title="${escapeHTML(fname)}">${escapeHTML(fname)}</span>
                                    <span class="px-2 py-0.5 rounded bg-emerald-950/90 border border-emerald-500/40 text-emerald-300 font-mono text-[10px]">${escapeHTML(fid)}</span>
                                </div>
                                <div class="flex flex-wrap items-center gap-2 text-[11px] text-slate-400 mt-1">
                                    <span><i class="fab fa-google-drive text-emerald-400 mr-1"></i>${escapeHTML(f.size_formatted || '0 B')}</span>
                                    <span>•</span>
                                    <span>${escapeHTML(f.content_type || 'media')}</span>
                                    ${f.uploaded_at_display ? `<span>•</span><span>${escapeHTML(f.uploaded_at_display)}</span>` : ''}
                                </div>
                                ${f.notes ? `<p class="text-[10px] text-slate-400 italic mt-0.5 truncate"><i class="fas fa-sticky-note text-amber-400 mr-1"></i>${escapeHTML(f.notes)}</p>` : ''}
                            </div>
                        </div>
                        <div class="flex items-center gap-2 self-end sm:self-center shrink-0">
                            <button type="button" onclick="selectSingleVaultFileForCreatePost('${escapeHTML(fid)}')" class="px-3.5 py-2 rounded-xl bg-gradient-to-r from-emerald-400 to-gb-cyan text-slate-950 font-bold text-xs shadow-[0_0_15px_rgba(0,240,255,0.25)] hover:shadow-[0_0_20px_rgba(16,185,129,0.5)] flex items-center gap-1.5 transition-all">
                                <i class="fas fa-cloud-upload-alt"></i>
                                <span>${isGrid ? 'Use This Image' : (activeCreatePostMediaTarget.context !== 'create_post' ? 'Attach This File' : 'Use File → Zernio')}</span>
                            </button>
                        </div>
                    </div>
                `;
            }).join('');
        }

        function toggleVaultGridFileCheckbox(fileId, checked) {
            if (!fileId) return;
            if (checked) {
                selectedCreatePostVaultGridIds.add(String(fileId));
            } else {
                selectedCreatePostVaultGridIds.delete(String(fileId));
            }
            renderCreatePostVaultPickerList();
        }

        function selectSingleVaultFileForCreatePost(fileId) {
            const list = Array.isArray(vaultFilesList) ? vaultFilesList : [];
            const found = list.find(f => String(f.file_id) === String(fileId));
            if (!found) {
                showToast('⚠️ Vault file not found. Try clicking Refresh.');
                return;
            }

            const { context, inputId, containerId, type, platform } = activeCreatePostMediaTarget;
            if (context === 'messages_chat' || context === 'comment_dm') {
                const fid = String(found.file_id || '');
                const pUrl = found.preview_url || found.download_url || (`/api/files/${encodeURIComponent(fid)}/stream`);
                const attObj = {
                    source: 'vault',
                    file_id: fid,
                    filename: found.filename || fid,
                    content_type: found.content_type || 'application/octet-stream',
                    media_type: detectAttachmentMediaType(found.filename, found.content_type),
                    size_formatted: found.size_formatted || '',
                    preview_url: pUrl
                };
                if (context === 'comment_dm') {
                    if (activeCommentDmAttachment && activeCommentDmAttachment.objectUrl) {
                        URL.revokeObjectURL(activeCommentDmAttachment.objectUrl);
                    }
                    activeCommentDmAttachment = attObj;
                    refreshAttachmentPreviewUI('comment_dm');
                } else {
                    if (activeChatAttachment && activeChatAttachment.objectUrl) {
                        URL.revokeObjectURL(activeChatAttachment.objectUrl);
                    }
                    activeChatAttachment = attObj;
                    refreshAttachmentPreviewUI('messages_chat');
                }
                closeCreatePostMediaSourceModal();
                showToast(`✅ Attached "${found.filename}" (${found.file_id}) from Files Modal!`);
                return;
            }

            const inputEl = document.getElementById(inputId);
            if (inputEl) inputEl.value = '';

            if (!currentDraftState.vaultMediaItems) currentDraftState.vaultMediaItems = {};
            if (!currentDraftState.vaultThumbItems) currentDraftState.vaultThumbItems = {};

            if (String(inputId).startsWith('thumb-')) {
                currentDraftState.thumbFiles[platform] = null;
                currentDraftState.vaultThumbItems[platform] = [Object.assign({}, found)];
            } else {
                currentDraftState.mediaFiles[platform] = null;
                currentDraftState.vaultMediaItems[platform] = [Object.assign({}, found)];
            }

            if (inputEl) {
                handleMediaPreview(inputEl, containerId, type);
            }
            closeCreatePostMediaSourceModal();
            showToast(`✅ Selected "${found.filename}" (${found.file_id}) from Google Drive Vault → ready to transfer to Zernio!`);
        }

        function confirmSelectedVaultGridFilesForCreatePost() {
            if (selectedCreatePostVaultGridIds.size === 0) {
                showToast('⚠️ Please check at least one image from the Vault list.');
                return;
            }
            const list = Array.isArray(vaultFilesList) ? vaultFilesList : [];
            const chosen = list.filter(f => selectedCreatePostVaultGridIds.has(String(f.file_id))).map(f => Object.assign({}, f));
            if (chosen.length === 0) {
                showToast('⚠️ Selected Vault files could not be resolved.');
                return;
            }

            const { inputId, containerId, type, platform } = activeCreatePostMediaTarget;
            const inputEl = document.getElementById(inputId);
            if (inputEl) inputEl.value = '';

            if (!currentDraftState.vaultMediaItems) currentDraftState.vaultMediaItems = {};
            currentDraftState.mediaFiles[platform] = null;
            currentDraftState.vaultMediaItems[platform] = chosen;

            if (inputEl) {
                handleMediaPreview(inputEl, containerId, type);
            }
            closeCreatePostMediaSourceModal();
            showToast(`✅ Selected ${chosen.length} Vault image(s) from Google Drive → ready to transfer to Zernio!`);
        }

        function buildMediaActionButtonsHTML(inputId, containerId, type) {
            const labelType = type === 'video' ? 'Video' : 'Image/Thumbnail';
            return `
                <div class="absolute top-2 right-2 z-30 flex items-center gap-1.5">
                    <button type="button"
                        onclick="openCreatePostMediaSourceModal('${inputId}', '${containerId}', '${type}', event)"
                        onmouseenter="showActionBubble(event, 'Replace ${labelType}', 'Choose a new ${labelType.toLowerCase()} from your Local Device or Google Drive Files Vault.', 'text-gb-cyan')"
                        onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                        class="bg-slate-900/90 hover:bg-gb-cyan hover:text-slate-950 border border-gb-cyan/60 px-2.5 py-1 rounded-lg text-[11px] font-semibold text-white flex items-center gap-1 transition-all shadow-lg">
                        <i class="fas fa-sync-alt text-[10px]"></i> <span>Replace</span>
                    </button>
                    <button type="button"
                        onclick="clearMediaBox('${inputId}', '${containerId}', '${type}', event)"
                        onmouseenter="showActionBubble(event, 'Delete ${labelType}', 'Remove and clear this ${labelType.toLowerCase()} file from the box.', 'text-rose-400')"
                        onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                        class="bg-rose-950/90 hover:bg-rose-600 border border-rose-500/70 px-2.5 py-1 rounded-lg text-[11px] font-semibold text-rose-200 hover:text-white flex items-center gap-1 transition-all shadow-lg">
                        <i class="fas fa-trash-alt text-[10px]"></i> <span>Delete</span>
                    </button>
                </div>
            `;
        }

        function buildVaultSourceBadgeHTML(vaultItem) {
            if (!vaultItem || !vaultItem.file_id) return '';
            return `
                <div class="absolute bottom-2 left-2 right-2 z-30 pointer-events-none flex items-center justify-between gap-1.5 px-2.5 py-1 rounded-lg bg-slate-950/90 border border-emerald-400/60 text-[10px] text-emerald-300 shadow-lg backdrop-blur-sm">
                    <span class="truncate font-semibold"><i class="fab fa-google-drive mr-1 text-emerald-400"></i>Google Drive → Zernio: <span class="text-white">${escapeHTML(vaultItem.filename || '')}</span></span>
                    <code class="px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-300 font-mono shrink-0">${escapeHTML(vaultItem.file_id)}</code>
                </div>
            `;
        }

        function handleMediaPreview(input, containerId, type) {
            if (!input) return;
            const container = document.getElementById(containerId);
            if (!container) return;
            const wrapper = input.closest('.media-box');
            container.innerHTML = '';

            let activeFiles = (input.files && input.files.length > 0) ? Array.from(input.files) : null;
            let activeVaultItems = null;

            if (activeFiles && activeFiles.length > 0) {
                if (input.id && input.id.startsWith('thumb-')) {
                    const plat = input.id.replace('thumb-', '');
                    currentDraftState.thumbFiles[plat] = activeFiles;
                    if (currentDraftState.vaultThumbItems) currentDraftState.vaultThumbItems[plat] = null;
                } else if (input.id && input.id.startsWith('media-')) {
                    const plat = input.id.replace('media-', '');
                    currentDraftState.mediaFiles[plat] = activeFiles;
                    if (currentDraftState.vaultMediaItems) currentDraftState.vaultMediaItems[plat] = null;
                }
            } else {
                if (input.id && input.id.startsWith('thumb-')) {
                    const plat = input.id.replace('thumb-', '');
                    if (currentDraftState.thumbFiles[plat] && currentDraftState.thumbFiles[plat].length > 0) {
                        activeFiles = currentDraftState.thumbFiles[plat];
                    } else if (currentDraftState.vaultThumbItems && currentDraftState.vaultThumbItems[plat] && currentDraftState.vaultThumbItems[plat].length > 0) {
                        activeVaultItems = currentDraftState.vaultThumbItems[plat];
                    }
                } else if (input.id && input.id.startsWith('media-')) {
                    const plat = input.id.replace('media-', '');
                    if (currentDraftState.mediaFiles[plat] && currentDraftState.mediaFiles[plat].length > 0) {
                        activeFiles = currentDraftState.mediaFiles[plat];
                    } else if (currentDraftState.vaultMediaItems && currentDraftState.vaultMediaItems[plat] && currentDraftState.vaultMediaItems[plat].length > 0) {
                        activeVaultItems = currentDraftState.vaultMediaItems[plat];
                    }
                }
            }

            if (activeFiles && activeFiles.length > 0) {
                if (wrapper) wrapper.classList.add('has-media');
                if (type === 'video') {
                    const url = URL.createObjectURL(activeFiles[0]);
                    objectUrls.push(url);
                    container.innerHTML = `
                        <video src="${url}" controls class="w-full h-full object-contain rounded-lg relative z-20" onclick="event.stopPropagation()"></video>
                        ${buildMediaActionButtonsHTML(input.id, containerId, 'video')}
                    `;
                } else if (type === 'image') {
                    const url = URL.createObjectURL(activeFiles[0]);
                    objectUrls.push(url);
                    container.innerHTML = `
                        <img src="${url}" class="w-full h-full object-cover rounded-lg relative z-20" onclick="event.stopPropagation()">
                        ${buildMediaActionButtonsHTML(input.id, containerId, 'image')}
                    `;
                } else if (type === 'grid') {
                    if (wrapper) wrapper.classList.remove('has-media');
                    const toolbarHTML = `
                        <div class="flex flex-wrap items-center justify-end gap-2 mb-3" onclick="event.stopPropagation()">
                            <button type="button"
                                onclick="openCreatePostMediaSourceModal('${input.id}', '${containerId}', 'grid', event)"
                                onmouseenter="showActionBubble(event, 'Replace Album Images', 'Choose a new set of images from Local Device or Google Drive Files Vault.', 'text-gb-cyan')"
                                onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                                class="bg-slate-900/90 hover:bg-gb-cyan hover:text-slate-950 border border-gb-cyan/60 px-2.5 py-1 rounded-lg text-xs font-semibold text-white flex items-center gap-1.5 transition-all">
                                <i class="fas fa-sync-alt text-[10px]"></i> <span>Replace All</span>
                            </button>
                            <button type="button"
                                onclick="clearMediaBox('${input.id}', '${containerId}', 'grid', event)"
                                onmouseenter="showActionBubble(event, 'Delete All Images', 'Remove all selected images from this album.', 'text-rose-400')"
                                onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                                class="bg-rose-950/90 hover:bg-rose-600 border border-rose-500/70 px-2.5 py-1 rounded-lg text-xs font-semibold text-rose-200 hover:text-white flex items-center gap-1.5 transition-all">
                                <i class="fas fa-trash-alt text-[10px]"></i> <span>Delete All</span>
                            </button>
                        </div>
                    `;
                    const gridItemsHTML = activeFiles.map((file, idx) => {
                        const url = URL.createObjectURL(file);
                        objectUrls.push(url);
                        return `
                            <div class="relative group rounded-lg overflow-hidden border border-gb-cyan/40 aspect-square bg-black" onclick="event.stopPropagation()">
                                <img src="${url}" class="w-full h-full object-cover">
                                <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/95 via-black/70 to-transparent p-1.5 flex items-center justify-center gap-1">
                                    <button type="button"
                                        onclick="openCreatePostMediaSourceModal('${input.id}', '${containerId}', 'grid', event)"
                                        onmouseenter="showActionBubble(event, 'Replace Image', 'Replace the images in this album (${escapeHTML(file.name)}).', 'text-gb-cyan')"
                                        onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                                        class="bg-slate-900/90 hover:bg-gb-cyan hover:text-slate-950 border border-slate-600 px-1.5 py-0.5 rounded text-[10px] font-semibold text-white flex items-center gap-1">
                                        <i class="fas fa-sync-alt text-[9px]"></i> Replace
                                    </button>
                                    <button type="button"
                                        onclick="removeSingleGridImage('${input.id}', '${containerId}', ${idx}, event)"
                                        onmouseenter="showActionBubble(event, 'Delete Image', 'Remove this image (${escapeHTML(file.name)}) from the album.', 'text-rose-400')"
                                        onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                                        class="bg-rose-950/90 hover:bg-rose-600 border border-rose-500/60 px-1.5 py-0.5 rounded text-[10px] font-semibold text-rose-200 hover:text-white flex items-center gap-1">
                                        <i class="fas fa-trash-alt text-[9px]"></i> Delete
                                    </button>
                                </div>
                            </div>
                        `;
                    }).join('');
                    container.innerHTML = `${toolbarHTML}<div class="image-grid w-full">${gridItemsHTML}</div>`;
                }
            } else if (activeVaultItems && activeVaultItems.length > 0) {
                if (wrapper) wrapper.classList.add('has-media');
                const firstItem = activeVaultItems[0];
                const fid = String(firstItem.file_id || '');
                const vaultUrl = firstItem.preview_url || firstItem.download_url || (`/api/files/${encodeURIComponent(fid)}/stream`);
                if (type === 'video') {
                    container.innerHTML = `
                        <video src="${escapeHTML(vaultUrl)}" preload="metadata" controls playsinline class="w-full h-full object-contain rounded-lg relative z-20" onclick="event.stopPropagation()"></video>
                        ${buildMediaActionButtonsHTML(input.id, containerId, 'video')}
                        ${buildVaultSourceBadgeHTML(firstItem)}
                    `;
                } else if (type === 'image') {
                    container.innerHTML = `
                        <img src="${escapeHTML(vaultUrl)}" class="w-full h-full object-cover rounded-lg relative z-20" onclick="event.stopPropagation()" onerror="this.style.display='none'">
                        ${buildMediaActionButtonsHTML(input.id, containerId, 'image')}
                        ${buildVaultSourceBadgeHTML(firstItem)}
                    `;
                } else if (type === 'grid') {
                    if (wrapper) wrapper.classList.remove('has-media');
                    const toolbarHTML = `
                        <div class="flex flex-wrap items-center justify-between gap-2 mb-3" onclick="event.stopPropagation()">
                            <span class="px-2.5 py-1 rounded-lg bg-emerald-950/90 border border-emerald-500/50 text-[11px] font-semibold text-emerald-300 flex items-center gap-1.5">
                                <i class="fab fa-google-drive text-emerald-400"></i>
                                <span>Google Drive Vault → Zernio (${activeVaultItems.length} file${activeVaultItems.length > 1 ? 's' : ''})</span>
                            </span>
                            <div class="flex items-center gap-2">
                                <button type="button"
                                    onclick="openCreatePostMediaSourceModal('${input.id}', '${containerId}', 'grid', event)"
                                    onmouseenter="showActionBubble(event, 'Replace Album Images', 'Choose a new set of images from Local Device or Google Drive Files Vault.', 'text-gb-cyan')"
                                    onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                                    class="bg-slate-900/90 hover:bg-gb-cyan hover:text-slate-950 border border-gb-cyan/60 px-2.5 py-1 rounded-lg text-xs font-semibold text-white flex items-center gap-1.5 transition-all">
                                    <i class="fas fa-sync-alt text-[10px]"></i> <span>Replace All</span>
                                </button>
                                <button type="button"
                                    onclick="clearMediaBox('${input.id}', '${containerId}', 'grid', event)"
                                    onmouseenter="showActionBubble(event, 'Delete All Images', 'Remove all selected images from this album.', 'text-rose-400')"
                                    onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                                    class="bg-rose-950/90 hover:bg-rose-600 border border-rose-500/70 px-2.5 py-1 rounded-lg text-xs font-semibold text-rose-200 hover:text-white flex items-center gap-1.5 transition-all">
                                    <i class="fas fa-trash-alt text-[10px]"></i> <span>Delete All</span>
                                </button>
                            </div>
                        </div>
                    `;
                    const gridItemsHTML = activeVaultItems.map((vItem, idx) => {
                        const vFid = String(vItem.file_id || '');
                        const vUrl = vItem.preview_url || vItem.download_url || (`/api/files/${encodeURIComponent(vFid)}/stream`);
                        const vName = vItem.filename || vItem.file_id || 'Vault Image';
                        return `
                            <div class="relative group rounded-lg overflow-hidden border border-emerald-400/60 aspect-square bg-black" onclick="event.stopPropagation()">
                                <img src="${escapeHTML(vUrl)}" class="w-full h-full object-cover">
                                <div class="absolute top-1.5 left-1.5 px-1.5 py-0.5 rounded bg-slate-950/90 border border-emerald-500/50 text-[9px] font-mono text-emerald-300">
                                    ${escapeHTML(vItem.file_id || '')}
                                </div>
                                <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/95 via-black/70 to-transparent p-1.5 flex items-center justify-center gap-1">
                                    <button type="button"
                                        onclick="openCreatePostMediaSourceModal('${input.id}', '${containerId}', 'grid', event)"
                                        onmouseenter="showActionBubble(event, 'Replace Image', 'Replace the images in this album (${escapeHTML(vName)}).', 'text-gb-cyan')"
                                        onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                                        class="bg-slate-900/90 hover:bg-gb-cyan hover:text-slate-950 border border-slate-600 px-1.5 py-0.5 rounded text-[10px] font-semibold text-white flex items-center gap-1">
                                        <i class="fas fa-sync-alt text-[9px]"></i> Replace
                                    </button>
                                    <button type="button"
                                        onclick="removeSingleGridImage('${input.id}', '${containerId}', ${idx}, event)"
                                        onmouseenter="showActionBubble(event, 'Delete Image', 'Remove this image (${escapeHTML(vName)}) from the album.', 'text-rose-400')"
                                        onmousemove="movePostTooltip(event)" onmouseleave="hidePostTooltip()"
                                        class="bg-rose-950/90 hover:bg-rose-600 border border-rose-500/60 px-1.5 py-0.5 rounded text-[10px] font-semibold text-rose-200 hover:text-white flex items-center gap-1">
                                        <i class="fas fa-trash-alt text-[9px]"></i> Delete
                                    </button>
                                </div>
                            </div>
                        `;
                    }).join('');
                    container.innerHTML = `${toolbarHTML}<div class="image-grid w-full">${gridItemsHTML}</div>`;
                }
            } else {
                if (wrapper) wrapper.classList.remove('has-media');
            }
        }

        let activeConnectModalTab = 'manage';
        let connectedAccountsMasterList = [];
        let discoveredCandidatesList = [];

        function updateConnectedAccountCounters() {
            const total = fbPagesList.length + igPagesList.length + tiktokAccountsList.length + youtubeAccountsList.length;
            const navBadge = document.getElementById('nav-connected-badge');
            const headerBadge = document.getElementById('header-connected-badge');
            const sideBadge = document.getElementById('sidebar-connected-count');
            const modalBadge = document.getElementById('conn-modal-count-badge');
            const fbCount = document.getElementById('platform-count-facebook');
            const igCount = document.getElementById('platform-count-instagram');
            const tkCount = document.getElementById('platform-count-tiktok');
            const ytCount = document.getElementById('platform-count-youtube');

            if (navBadge) navBadge.textContent = total;
            if (headerBadge) headerBadge.textContent = total;
            if (sideBadge) sideBadge.textContent = total;
            if (modalBadge) modalBadge.textContent = total;
            if (fbCount) fbCount.textContent = `${fbPagesList.length} page${fbPagesList.length === 1 ? '' : 's'}`;
            if (igCount) igCount.textContent = `${igPagesList.length} acct${igPagesList.length === 1 ? '' : 's'}`;
            if (tkCount) tkCount.textContent = `${tiktokAccountsList.length} acct${tiktokAccountsList.length === 1 ? '' : 's'}`;
            if (ytCount) ytCount.textContent = `${youtubeAccountsList.length} chnl${youtubeAccountsList.length === 1 ? '' : 's'}`;
        }

        async function fetchSocialAccounts() {
            try {
                let response = await fetch('/api/social/accounts');
                let data = await response.json();
                fbPagesList = data.facebook || [];
                igPagesList = data.instagram || [];
                tiktokAccountsList = data.tiktok || [];
                youtubeAccountsList = data.youtube || [];
                updateConnectedAccountCounters();
            } catch (e) { 
                console.error("Error fetching accounts:", e); 
            } finally {
                updatePreviews();
            }
        }

