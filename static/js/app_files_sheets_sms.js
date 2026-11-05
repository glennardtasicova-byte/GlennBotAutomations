        // =========================================================================
        // --- "FILES" MODAL / VIEW: GOOGLE DRIVE API VAULT + PYTHON FILE ID ENGINE ---
        // =========================================================================
        let vaultFilesList = [];
        let pendingVaultFilesSelection = [];
        let gdriveAuthState = {
            configured: true,
            authorized: false,
            connected_email: '',
            folder_name: 'GlennBot_Media_Vault',
            folder_id: ''
        };

        // Listen for postMessage from Google Drive OAuth callback popup (when authorized on localhost)
        window.addEventListener('message', (event) => {
            if (event && event.data && event.data.type === 'GDRIVE_AUTH_SUCCESS') {
                const emailStr = event.data.email ? ` (${event.data.email})` : '';
                showToast(`✅ Google Drive API Connected${emailStr}! Folder: ${event.data.folder_name || 'GlennBot_Media_Vault'}`);
                fetchVaultFiles(true);
            }
        });

        function updateGoogleDriveAuthBannerUI(data) {
            if (data && typeof data === 'object') {
                if ('gdrive_authorized' in data) gdriveAuthState.authorized = Boolean(data.gdrive_authorized);
                if ('authorized' in data) gdriveAuthState.authorized = Boolean(data.authorized);
                if (data.gdrive_connected_email || data.connected_email) {
                    gdriveAuthState.connected_email = data.gdrive_connected_email || data.connected_email || '';
                }
                if (data.gdrive_folder_name || data.folder_name) {
                    gdriveAuthState.folder_name = data.gdrive_folder_name || data.folder_name || 'GlennBot_Media_Vault';
                }
                if (data.gdrive_folder_id || data.folder_id) {
                    gdriveAuthState.folder_id = data.gdrive_folder_id || data.folder_id || '';
                }
            }

            const pill = document.getElementById('files-b2-status-pill');
            if (pill) {
                const folderName = gdriveAuthState.folder_name || 'GlennBot_Media_Vault';
                if (gdriveAuthState.authorized) {
                    pill.className = 'text-[10px] px-2.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/40 font-semibold flex items-center gap-1';
                    pill.innerHTML = `<i class="fab fa-google-drive text-[9px]"></i> Google Drive Connected (<code class="text-white">${escapeHTML(folderName)}</code>)`;
                } else {
                    pill.className = 'text-[10px] px-2.5 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/40 font-semibold flex items-center gap-1';
                    pill.innerHTML = `<i class="fab fa-google-drive text-[9px]"></i> Google Drive (<code class="text-white">${escapeHTML(folderName)}</code> • Click Connect)`;
                }
            }

            const banner = document.getElementById('gdrive-auth-banner');
            const badge = document.getElementById('gdrive-auth-status-badge');
            const titleEl = document.getElementById('gdrive-auth-status-title');
            const descEl = document.getElementById('gdrive-auth-status-desc');
            const btnLabel = document.getElementById('btn-connect-gdrive-label');
            const pasteBox = document.getElementById('gdrive-code-paste-box');

            if (gdriveAuthState.authorized) {
                if (banner) banner.className = 'p-3 rounded-xl bg-emerald-950/25 border border-emerald-500/40 mb-3 shrink-0 flex flex-col gap-2.5';
                if (titleEl) titleEl.textContent = 'Google Drive API v3 Active & Authorized';
                if (badge) {
                    badge.className = 'text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-400/50';
                    badge.innerHTML = `<i class="fas fa-check-circle mr-1"></i>Connected${gdriveAuthState.connected_email ? ': ' + escapeHTML(gdriveAuthState.connected_email) : ''}`;
                }
                if (descEl) {
                    descEl.innerHTML = `Target Drive Folder: <code class="text-emerald-300 font-mono">${escapeHTML(gdriveAuthState.folder_name || 'GlennBot_Media_Vault')}</code> • Live Video &amp; Image Previews Enabled in Create Post!`;
                }
                if (btnLabel) btnLabel.textContent = 'Reconnect Google Drive';
                if (pasteBox) pasteBox.classList.add('hidden');
            } else {
                if (banner) banner.className = 'p-3 rounded-xl bg-amber-950/25 border border-amber-500/50 mb-3 shrink-0 flex flex-col gap-2.5';
                if (titleEl) titleEl.textContent = 'One-Time Setup: Authorize Your Google Drive Account';
                if (badge) {
                    badge.className = 'text-[10px] font-mono px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-400/50';
                    badge.innerHTML = `<i class="fas fa-exclamation-circle mr-1"></i>Authorization Required Once`;
                }
                if (descEl) {
                    descEl.innerHTML = `Click <strong>"Connect Google Drive"</strong> on the right to sign in with Google and link your <code class="text-emerald-300">GlennBot_Media_Vault</code> folder.`;
                }
                if (btnLabel) btnLabel.textContent = 'Connect Google Drive';
            }
        }

        function toggleGoogleDriveCodePasteBox() {
            const box = document.getElementById('gdrive-code-paste-box');
            if (!box) return;
            box.classList.toggle('hidden');
            if (!box.classList.contains('hidden')) {
                const inp = document.getElementById('gdrive-code-paste-input');
                if (inp) inp.focus();
            }
        }

        async function connectGoogleDriveOAuth() {
            try {
                const res = await fetch(`/api/gdrive/auth-url?origin=${encodeURIComponent(window.location.origin)}`);
                const data = await res.json();
                if (data.status !== 'success' || !data.auth_url) {
                    showToast('⚠️ ' + (data.message || 'Could not generate Google Drive OAuth URL.'));
                    return;
                }
                const width = 560, height = 680;
                const left = Math.max(0, (window.screen.width - width) / 2);
                const top = Math.max(0, (window.screen.height - height) / 2);
                window.open(
                    data.auth_url,
                    'GlennBotGoogleDriveOAuth',
                    `width=${width},height=${height},left=${left},top=${top},scrollbars=yes,resizable=yes`
                );
                // If user is on Render.com (not localhost), automatically show the paste box so they can paste the http://localhost/?code=... URL
                const host = String(window.location.hostname || '').toLowerCase();
                if (host !== 'localhost' && host !== '127.0.0.1') {
                    const box = document.getElementById('gdrive-code-paste-box');
                    if (box) box.classList.remove('hidden');
                    showToast('🔐 Sign in with Google in the popup, then paste the redirected http://localhost/?code=... URL into the box!');
                } else {
                    showToast('🔐 Complete Google Drive sign-in in the popup window...');
                }
            } catch (e) {
                showToast('⚠️ Failed to open Google Drive OAuth popup: ' + (e.message || e));
            }
        }

        async function submitGoogleDriveAuthCode() {
            const inp = document.getElementById('gdrive-code-paste-input');
            const btn = document.getElementById('btn-submit-gdrive-code');
            const rawVal = (inp?.value || '').trim();
            if (!rawVal) {
                showToast('⚠️ Please paste the redirected http://localhost/?code=... URL or authorization code first.');
                if (inp) inp.focus();
                return;
            }
            const origHTML = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> <span>Verifying...</span>`;
            }
            try {
                const form = new FormData();
                form.append('code_or_url', rawVal);
                form.append('redirect_uri', 'http://localhost');
                const res = await fetch('/api/gdrive/exchange-code', { method: 'POST', body: form });
                const data = await res.json();
                if (res.ok && data.status === 'success') {
                    if (inp) inp.value = '';
                    updateGoogleDriveAuthBannerUI(data);
                    showToast(`✅ ${data.message || 'Google Drive connected permanently!'}`);
                    await fetchVaultFiles(true);
                } else {
                    showToast('⚠️ ' + (data.message || 'Failed to exchange code.'));
                }
            } catch (e) {
                showToast('⚠️ Error verifying Google Drive code: ' + (e.message || e));
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = origHTML || `<i class="fas fa-check-circle"></i> <span>Verify &amp; Save Token</span>`;
                }
            }
        }

        function onVaultFilesInputSelected(inputEl) {
            const files = Array.from(inputEl?.files || []);
            pendingVaultFilesSelection = files;
            const labelEl = document.getElementById('vault-selected-files-label');
            if (!labelEl) return;
            if (files.length === 0) {
                labelEl.textContent = 'No file selected yet — click "Select File(s)" to upload to Google Drive';
            } else if (files.length === 1) {
                const kb = Math.max(1, Math.round(files[0].size / 1024));
                labelEl.textContent = `Selected: ${files[0].name} (${kb} KB) — ready to upload to Google Drive`;
            } else {
                labelEl.textContent = `Selected ${files.length} files (${files.map(f => f.name).slice(0, 3).join(', ')}) — ready to upload to Google Drive`;
            }
        }

        function updateVaultFilesBadges() {
            const count = Array.isArray(vaultFilesList) ? vaultFilesList.length : 0;
            const navBadge = document.getElementById('files-total-badge');
            if (navBadge) navBadge.textContent = String(count);
            const sumEl = document.getElementById('vault-files-summary-count');
            if (sumEl) sumEl.textContent = `${count} file(s) stored in Google Drive (${gdriveAuthState.folder_name || 'GlennBot_Media_Vault'}) with Python File IDs`;
        }

        async function fetchVaultFiles(force = false) {
            const syncIcon = document.getElementById('vault-files-sync-icon');
            if (syncIcon && force) syncIcon.classList.add('fa-spin');
            try {
                const res = await fetch(`/api/files?force=${force ? 'true' : 'false'}`);
                const data = await res.json();
                if (data.status === 'success') {
                    vaultFilesList = Array.isArray(data.files) ? data.files : [];
                    updateGoogleDriveAuthBannerUI(data);
                    updateVaultFilesBadges();
                    renderVaultFilesList();
                }
            } catch (e) {
                console.warn('Could not fetch Google Drive vault files:', e);
                renderVaultFilesList();
            } finally {
                if (syncIcon) syncIcon.classList.remove('fa-spin');
            }
        }

        async function uploadSelectedVaultFilesToGoogleDrive() {
            const inputEl = document.getElementById('vault-files-input');
            const noteEl = document.getElementById('vault-files-note-input');
            const btn = document.getElementById('btn-upload-vault-files');
            const filesToUpload = pendingVaultFilesSelection.length > 0
                ? pendingVaultFilesSelection
                : Array.from(inputEl?.files || []);

            if (filesToUpload.length === 0) {
                showToast('⚠️ Please select a file using "Select File(s)" before uploading to Google Drive!');
                if (inputEl) inputEl.click();
                return;
            }

            if (!gdriveAuthState.authorized) {
                showToast('🔐 Please click "Connect Google Drive" first so GlennBot can upload to your Google Drive folder!');
                connectGoogleDriveOAuth();
                return;
            }

            const notesVal = (noteEl?.value || '').trim();
            const CHUNK_SIZE = 15 * 1024 * 1024;
            const MULTIPART_THRESHOLD = 20 * 1024 * 1024;

            const safeParse = window.glennbotSafeParseServerJson || (async (res) => {
                const t = await res.text();
                try { return JSON.parse(t); } catch (_) { return { status: 'error', message: `HTTP ${res.status}` }; }
            });

            const origHTML = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin shrink-0"></i> <span class="truncate">Uploading to Google Drive...</span>`;
            }

            try {
                let lastGeneratedId = '';
                for (const file of filesToUpload) {
                    const totalSize = file.size || 0;
                    const totalParts = totalSize > MULTIPART_THRESHOLD ? Math.ceil(totalSize / CHUNK_SIZE) : 1;

                    const cleanUploadName = String(file.name || 'file.bin').replace(/^file_[a-fA-F0-9]{8,16}_+/, '') || 'file.bin';
                    const initForm = new FormData();
                    initForm.append('filename', cleanUploadName);
                    initForm.append('content_type', file.type || 'application/octet-stream');
                    initForm.append('total_size', String(totalSize));
                    initForm.append('total_parts', String(totalParts));
                    initForm.append('notes', notesVal);

                    const initRes = await fetch('/api/files/chunked/init', { method: 'POST', body: initForm });
                    const initData = await safeParse(initRes, 'Files Init');
                    if (!initRes.ok || initData.status !== 'success' || !initData.file_id) {
                        if (initData.needs_oauth) {
                            gdriveAuthState.authorized = false;
                            updateGoogleDriveAuthBannerUI(initData);
                            connectGoogleDriveOAuth();
                        }
                        throw new Error(initData.message || `Failed to start Google Drive upload for ${file.name}`);
                    }

                    const fileId = initData.file_id;
                    lastGeneratedId = fileId;

                    for (let partNum = 1; partNum <= totalParts; partNum++) {
                        const startByte = (partNum - 1) * CHUNK_SIZE;
                        const endByte = partNum === totalParts ? totalSize : Math.min(totalSize, startByte + CHUNK_SIZE);
                        const chunkBlob = file.slice(startByte, endByte);
                        const pct = Math.min(99, Math.round((partNum / totalParts) * 100));
                        if (btn) {
                            btn.innerHTML = `<i class="fas fa-circle-notch fa-spin shrink-0"></i> <span class="truncate">Uploading (${pct}% • Part ${partNum}/${totalParts})...</span>`;
                        }

                        let partOk = false;
                        let partErr = '';
                        for (let attempt = 1; attempt <= 3; attempt++) {
                            try {
                                const pForm = new FormData();
                                pForm.append('file_id', fileId);
                                pForm.append('part_number', String(partNum));
                                pForm.append('total_parts', String(totalParts));
                                pForm.append('chunk', chunkBlob, file.name);
                                const pRes = await fetch('/api/files/chunked/part', { method: 'POST', body: pForm });
                                const pData = await safeParse(pRes, 'Vault Part Upload');
                                if (pRes.ok && pData.status === 'success') {
                                    partOk = true;
                                    break;
                                }
                                partErr = pData.message || `HTTP ${pRes.status}`;
                            } catch (ex) {
                                partErr = ex.message || String(ex);
                            }
                            if (attempt < 3) await new Promise(r => setTimeout(r, 2000 * attempt));
                        }

                        if (!partOk) {
                            throw new Error(`Part ${partNum}/${totalParts} failed: ${partErr}`);
                        }
                    }

                    const compForm = new FormData();
                    compForm.append('file_id', fileId);
                    compForm.append('filename', cleanUploadName);
                    compForm.append('content_type', file.type || 'application/octet-stream');
                    compForm.append('total_size', String(totalSize));
                    compForm.append('notes', notesVal);

                    const compRes = await fetch('/api/files/chunked/complete', { method: 'POST', body: compForm });
                    const compData = await safeParse(compRes, 'Finalize Google Drive Upload');
                    if (!compRes.ok || compData.status !== 'success') {
                        throw new Error(compData.message || 'Failed to finalize Google Drive upload.');
                    }
                    if (Array.isArray(compData.files)) {
                        vaultFilesList = compData.files;
                    }
                }

                showToast(`✅ Uploaded to Google Drive! Generated File ID: ${lastGeneratedId}`);
                pendingVaultFilesSelection = [];
                if (inputEl) inputEl.value = '';
                if (noteEl) noteEl.value = '';
                const labelEl = document.getElementById('vault-selected-files-label');
                if (labelEl) labelEl.textContent = 'No file selected yet — click "Select File(s)" to upload to Google Drive';
                updateVaultFilesBadges();
                renderVaultFilesList();
                if (typeof fetchSavedSpreadsheets === 'function') {
                    fetchSavedSpreadsheets(true);
                }
            } catch (e) {
                showToast('⚠️ ' + (e.message || 'Network error while uploading file to Google Drive.'));
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = origHTML || `<i class="fab fa-google-drive shrink-0"></i> <span class="truncate">Upload to Google Drive &amp; Generate File ID</span>`;
                }
            }
        }

        async function copyVaultFileId(fileId) {
            if (!fileId) return;
            try {
                await navigator.clipboard.writeText(fileId);
                showToast(`📋 Copied File ID: ${fileId}`);
            } catch (_) {
                showToast(`📋 File ID: ${fileId}`);
            }
        }

        async function deleteVaultFile(fileId) {
            if (!fileId) return;
            try {
                const res = await fetch(`/api/files/${encodeURIComponent(fileId)}`, {
                    method: 'DELETE'
                });
                const data = await res.json();
                if (data.status === 'success') {
                    vaultFilesList = Array.isArray(data.files) ? data.files : vaultFilesList.filter(f => f.file_id !== fileId);
                    updateVaultFilesBadges();
                    renderVaultFilesList();
                    if (typeof currentSpreadsheetWorkbook !== 'undefined' && currentSpreadsheetWorkbook && currentSpreadsheetWorkbook.file_id === fileId) {
                        if (typeof createNewSpreadsheetWorkbook === 'function') {
                            createNewSpreadsheetWorkbook(true);
                        }
                    }
                    if (typeof fetchSavedSpreadsheets === 'function') {
                        fetchSavedSpreadsheets(true);
                    }
                    showToast(`🗑️ ${data.message || 'Deleted file from Google Drive!'}`);
                } else {
                    showToast('⚠️ ' + (data.message || 'Could not delete file.'));
                }
            } catch (_) {
                showToast('⚠️ Network error while deleting file from Google Drive.');
            }
        }

        function getVaultFileTypeIcon(mime, filename) {
            const m = String(mime || '').toLowerCase();
            const n = String(filename || '').toLowerCase();
            if (m.startsWith('video/') || /\.(mp4|mov|webm|mkv|avi)$/.test(n)) return 'fa-file-video text-purple-400';
            if (m.startsWith('image/') || /\.(png|jpg|jpeg|gif|webp|svg)$/.test(n)) return 'fa-file-image text-pink-400';
            if (m.includes('pdf') || n.endsWith('.pdf')) return 'fa-file-pdf text-rose-400';
            if (/\.(xlsx|xls|csv)$/.test(n)) return 'fa-file-excel text-emerald-400';
            if (/\.(zip|rar|7z|tar|gz)$/.test(n)) return 'fa-file-archive text-amber-400';
            if (/\.(json|py|js|ts|html)$/.test(n)) return 'fa-file-code text-gb-cyan';
            return 'fa-file-alt text-sky-400';
        }

        function renderVaultFilesList() {
            const container = document.getElementById('vault-files-table-container');
            if (!container) return;

            const q = (document.getElementById('vault-files-search')?.value || '').trim().toLowerCase();
            const filtered = (vaultFilesList || []).filter(item => {
                if (!q) return true;
                return (
                    String(item.file_id || '').toLowerCase().includes(q) ||
                    String(item.filename || '').toLowerCase().includes(q) ||
                    String(item.notes || '').toLowerCase().includes(q) ||
                    String(item.content_type || '').toLowerCase().includes(q)
                );
            });

            if (filtered.length === 0) {
                container.innerHTML = `
                    <div class="flex flex-col items-center justify-center py-16 px-4 text-center text-slate-400">
                        <div class="w-14 h-14 rounded-2xl bg-emerald-500/10 border border-emerald-400/30 flex items-center justify-center text-emerald-400 mb-3">
                            <i class="fab fa-google-drive text-2xl"></i>
                        </div>
                        <p class="text-sm font-bold text-white">No Uploaded Google Drive Vault Files Yet</p>
                        <p class="text-xs text-slate-400 max-w-md mt-1">
                            All files uploaded from this <strong>Files</strong> modal are stored in your <strong>Google Drive</strong> (<code class="text-emerald-300">GlennBot_Media_Vault</code>) and listed here with their Python-generated <strong>File ID</strong> (<code class="text-gb-cyan">file_...</code>) and live preview.
                        </p>
                    </div>
                `;
                return;
            }

            const rowsHTML = filtered.map((item, idx) => {
                const fid = String(item.file_id || '');
                const fname = String(item.filename || 'file').replace(/^file_[a-fA-F0-9]{8,16}_+/, '') || 'file';
                const fsize = String(item.size_formatted || '0 KB');
                const ftype = String(item.content_type || 'application/octet-stream');
                const note = String(item.notes || '');
                const uploadedAt = String(item.uploaded_at || '');
                const streamUrl = String(item.preview_url || item.download_url || `/api/files/${encodeURIComponent(fid)}/stream`);
                const driveViewLink = String(item.web_view_link || '');
                const iconCls = getVaultFileTypeIcon(ftype, fname);
                const isImg = ftype.toLowerCase().startsWith('image/') || /\.(png|jpg|jpeg|gif|webp|bmp)$/i.test(fname);
                const isVid = ftype.toLowerCase().startsWith('video/') || /\.(mp4|mov|webm|mkv|avi)$/i.test(fname);

                let miniPreviewHTML = `<i class="fas ${iconCls} text-base shrink-0"></i>`;
                if (isImg) {
                    miniPreviewHTML = `<img src="${escapeHTML(streamUrl)}" class="w-10 h-10 rounded-lg object-cover border border-emerald-500/40 shrink-0 bg-black" loading="lazy" onerror="this.style.display='none'">`;
                } else if (isVid) {
                    miniPreviewHTML = `<video src="${escapeHTML(streamUrl)}#t=0.5" preload="metadata" muted playsinline class="w-10 h-10 rounded-lg object-cover border border-gb-cyan/50 shrink-0 bg-black"></video>`;
                }

                return `
                    <tr class="border-b border-slate-800/80 hover:bg-slate-900/80 transition-colors">
                        <td class="py-3 px-4 text-xs font-bold text-slate-500">#${idx + 1}</td>
                        <td class="py-3 px-4 whitespace-nowrap">
                            <div class="inline-flex items-center gap-2 bg-slate-900 border border-gb-cyan/50 rounded-xl px-3 py-1.5 shadow-[0_0_10px_rgba(0,240,255,0.12)]">
                                <code class="text-xs font-mono font-extrabold text-gb-cyan">${escapeHTML(fid)}</code>
                                <button type="button" onclick="copyVaultFileId('${escapeHTML(fid)}')" class="px-2 py-0.5 rounded-lg bg-gb-cyan/15 hover:bg-gb-cyan/30 text-gb-cyan text-[10px] font-bold flex items-center gap-1 transition-all" title="Copy File ID for Automation">
                                    <i class="fas fa-copy"></i>
                                    <span>Copy ID</span>
                                </button>
                            </div>
                        </td>
                        <td class="py-3 px-4">
                            <div class="flex items-center gap-2.5">
                                ${miniPreviewHTML}
                                <div class="min-w-0">
                                    <div class="text-xs font-bold text-white truncate max-w-[260px]" title="${escapeHTML(fname)}">${escapeHTML(fname)}</div>
                                    <div class="text-[10px] text-slate-400 font-mono truncate">${escapeHTML(ftype)}</div>
                                </div>
                            </div>
                        </td>
                        <td class="py-3 px-4 whitespace-nowrap text-xs font-semibold text-emerald-300">${escapeHTML(fsize)}</td>
                        <td class="py-3 px-4 whitespace-nowrap">
                            <span class="px-2.5 py-1 rounded-full text-[10px] font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/40 inline-flex items-center gap-1.5">
                                <i class="fab fa-google-drive text-[9px]"></i> Google Drive
                            </span>
                        </td>
                        <td class="py-3 px-4">
                            <span class="text-xs text-slate-300">${note ? escapeHTML(note) : '<span class="text-slate-600 italic">—</span>'}</span>
                        </td>
                        <td class="py-3 px-4 whitespace-nowrap text-[11px] text-slate-400">${escapeHTML(uploadedAt)}</td>
                        <td class="py-3 px-4 text-right whitespace-nowrap">
                            <div class="inline-flex items-center gap-1.5">
                                <a href="${escapeHTML(streamUrl)}" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-gb-cyan/50 text-gb-cyan text-xs font-semibold inline-flex items-center gap-1 transition-all" title="Preview / Stream Media">
                                    <i class="fas fa-play text-[10px]"></i>
                                    <span>Preview</span>
                                </a>
                                ${driveViewLink ? `
                                <a href="${escapeHTML(driveViewLink)}" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1.5 rounded-lg bg-emerald-950/70 hover:bg-emerald-900 border border-emerald-500/50 text-emerald-300 text-xs font-semibold inline-flex items-center gap-1 transition-all" title="View in Google Drive">
                                    <i class="fab fa-google-drive text-[10px]"></i>
                                    <span>Drive</span>
                                </a>
                                ` : ''}
                                <button type="button" onclick="deleteVaultFile('${escapeHTML(fid)}')" class="px-2.5 py-1.5 rounded-lg bg-rose-950/60 hover:bg-rose-900 border border-rose-500/50 text-rose-300 text-xs font-semibold inline-flex items-center gap-1 transition-all" title="Delete from Google Drive">
                                    <i class="fas fa-trash-alt text-[10px]"></i>
                                    <span>Delete</span>
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');

            container.innerHTML = `
                <table class="w-full text-left border-collapse min-w-[820px]">
                    <thead>
                        <tr class="border-b border-slate-800 bg-slate-900/95 text-[11px] font-bold uppercase tracking-wider text-slate-400 sticky top-0 z-10">
                            <th class="py-3 px-4">#</th>
                            <th class="py-3 px-4">Python File ID (For Automation)</th>
                            <th class="py-3 px-4">File Name &amp; Preview</th>
                            <th class="py-3 px-4">Size</th>
                            <th class="py-3 px-4">Storage</th>
                            <th class="py-3 px-4">Automation Note</th>
                            <th class="py-3 px-4">Uploaded (PH Time)</th>
                            <th class="py-3 px-4 text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rowsHTML}
                    </tbody>
                </table>
            `;
        }

        // =========================================================================
        // --- "SPREAD SHEET" MODAL / VIEW: CUSTOM A,B,C,D x 1,2,3,4 SPREADSHEET ---
        // --- STARTS BLANK + GOOGLE DRIVE SAVE (WITH FILE_ID) + TWO-WAY AUTO-SYNC ---
        // =========================================================================
        function createBlankSpreadsheetWorkbookState() {
            return {
                workbook_id: '',
                file_id: '',
                gdrive_file_id: '',
                title: 'Untitled_Spreadsheet.xlsx',
                sheets: [
                    {
                        id: 'sheet_1',
                        name: 'Sheet1',
                        row_count: 25,
                        col_count: 10,
                        cells: {},
                        wrap_cells: {},
                        col_widths: {},
                        row_heights: {}
                    }
                ]
            };
        }

        let savedSpreadsheetsList = [];
        let currentSpreadsheetWorkbook = createBlankSpreadsheetWorkbookState();
        let activeSheetIndex = 0;
        let activeCellCoord = 'A1';
        let ssSelectionAnchorCoord = 'A1';
        let ssSelectedCells = new Set(['A1']);
        let ssSelectedCols = new Set();
        let ssSelectedRows = new Set();
        let ssEditingCellCoord = null;
        let ssIsMouseDraggingSelection = false;
        let ssDragSelectMode = null; // 'cells' | 'cols' | 'rows'
        let ssDragStartCoord = null;
        let ssDragStartColIdx = null;
        let ssDragStartRowNum = null;
        let ssDragBaseSelectedCells = null;
        let ssDragBaseSelectedCols = null;
        let ssDragBaseSelectedRows = null;
        let ssDragMouseUpAttached = false;
        let ssLayoutSaveTimer = null;
        let spreadsheetInitialized = false;
        let ssAutoSyncPushTimer = null;
        let ssAutoSyncPullInterval = null;
        let ssIsSavingInFlight = false;
        let ssHasPendingSaveWhileInFlight = false;
        let ssLocalEditVersion = 0;
        let ssIsPullSyncInFlight = false;
        let ssFocusListenersAttached = false;
        let lastSyncedSpreadsheetSignature = '';

        function ssGetWorkbookLayoutStorageKeys(sheetName) {
            const shKey = String(sheetName || 'Sheet1').trim();
            const keys = [];
            const wbId = String(currentSpreadsheetWorkbook?.workbook_id || '').trim();
            const fId = String(currentSpreadsheetWorkbook?.file_id || '').trim();
            const title = String(currentSpreadsheetWorkbook?.title || 'Untitled_Spreadsheet.xlsx').trim();
            if (wbId) keys.push(`gb_ss_layout_v2::${wbId}::${shKey}`);
            if (fId) keys.push(`gb_ss_layout_v2::${fId}::${shKey}`);
            if (title) keys.push(`gb_ss_layout_v2::${title}::${shKey}`);
            keys.push(`gb_ss_layout_v2::blank_wb::${shKey}`);
            return Array.from(new Set(keys));
        }

        function ssSaveSheetLayoutToLocalCache(sheet) {
            if (!sheet) return;
            try {
                const payload = JSON.stringify({
                    wrap_cells: sheet.wrap_cells || {},
                    col_widths: sheet.col_widths || {},
                    row_heights: sheet.row_heights || {}
                });
                ssGetWorkbookLayoutStorageKeys(sheet.name).forEach(k => {
                    localStorage.setItem(k, payload);
                });
            } catch (_) {}
            // Also persist layout asynchronously to Python backend store
            if (ssLayoutSaveTimer) clearTimeout(ssLayoutSaveTimer);
            ssLayoutSaveTimer = setTimeout(async () => {
                ssLayoutSaveTimer = null;
                try {
                    await fetch('/api/spreadsheets/save-layout', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            workbook_id: currentSpreadsheetWorkbook?.workbook_id || '',
                            file_id: currentSpreadsheetWorkbook?.file_id || '',
                            title: currentSpreadsheetWorkbook?.title || '',
                            sheets: currentSpreadsheetWorkbook?.sheets || []
                        })
                    });
                } catch (_) {}
            }, 350);
        }

        function ssRestoreSheetLayoutFromLocalCache(sheet) {
            if (!sheet) return;
            sheet.wrap_cells = (sheet.wrap_cells && typeof sheet.wrap_cells === 'object') ? sheet.wrap_cells : {};
            sheet.col_widths = (sheet.col_widths && typeof sheet.col_widths === 'object') ? sheet.col_widths : {};
            sheet.row_heights = (sheet.row_heights && typeof sheet.row_heights === 'object') ? sheet.row_heights : {};
            try {
                const keys = ssGetWorkbookLayoutStorageKeys(sheet.name);
                for (let i = 0; i < keys.length; i++) {
                    const raw = localStorage.getItem(keys[i]);
                    if (!raw) continue;
                    const parsed = JSON.parse(raw);
                    if (parsed && typeof parsed === 'object') {
                        if (Object.keys(sheet.wrap_cells).length === 0 && parsed.wrap_cells && typeof parsed.wrap_cells === 'object') {
                            sheet.wrap_cells = { ...parsed.wrap_cells };
                        }
                        if (Object.keys(sheet.col_widths).length === 0 && parsed.col_widths && typeof parsed.col_widths === 'object') {
                            sheet.col_widths = { ...parsed.col_widths };
                        }
                        if (Object.keys(sheet.row_heights).length === 0 && parsed.row_heights && typeof parsed.row_heights === 'object') {
                            sheet.row_heights = { ...parsed.row_heights };
                        }
                        break;
                    }
                }
            } catch (_) {}
        }

        function ssSyncWrapMirror(inputEl) {
            if (!inputEl) return;
            const mirror = inputEl.previousElementSibling;
            if (mirror && mirror.classList.contains('ss-wrap-cell-mirror')) {
                mirror.textContent = String(inputEl.value || '') + ' ';
            }
        }

        function ssGetEffectiveSelectedCoords() {
            if (ssSelectedCells && ssSelectedCells.size > 0) {
                return Array.from(ssSelectedCells);
            }
            return [activeCellCoord || 'A1'];
        }

        function updateSpreadsheetWrapTextButtonUI() {
            const btn = document.getElementById('btn-ss-wrap-text');
            const lbl = document.getElementById('btn-ss-wrap-text-label');
            if (!btn) return;
            const sheet = ssGetActiveSheet();
            const wrapMap = sheet.wrap_cells || {};
            const coords = ssGetEffectiveSelectedCoords();
            let wrappedCount = 0;
            for (let i = 0; i < coords.length; i++) {
                if (wrapMap[coords[i]]) wrappedCount++;
            }
            const allWrapped = coords.length > 0 && wrappedCount === coords.length;
            const someWrapped = wrappedCount > 0 && wrappedCount < coords.length;

            if (allWrapped) {
                btn.className = 'px-2.5 py-1 rounded-lg bg-gb-cyan/20 hover:bg-gb-cyan/30 border border-gb-cyan/60 text-gb-cyan text-[11px] font-bold flex items-center gap-1.5 shrink-0 transition-all shadow-[0_0_10px_rgba(0,240,255,0.18)]';
                if (lbl) lbl.textContent = coords.length > 1 ? `Wrap Text: ON (${coords.length})` : 'Wrap Text: ON';
            } else if (someWrapped) {
                btn.className = 'px-2.5 py-1 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 border border-amber-400/60 text-amber-300 text-[11px] font-bold flex items-center gap-1.5 shrink-0 transition-all';
                if (lbl) lbl.textContent = `Wrap Text: Mixed (${wrappedCount}/${coords.length})`;
            } else {
                btn.className = 'px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 hover:text-white text-[11px] font-semibold flex items-center gap-1.5 shrink-0 transition-all';
                if (lbl) lbl.textContent = 'Wrap Text';
            }
        }

        function toggleSpreadsheetWrapText() {
            ssExitCellEditMode();
            const sheet = ssGetActiveSheet();
            sheet.wrap_cells = sheet.wrap_cells || {};
            const coords = ssGetEffectiveSelectedCoords();
            if (coords.length === 0) return;

            const allCurrentlyWrapped = coords.every(c => Boolean(sheet.wrap_cells[c]));
            const nextWrapState = !allCurrentlyWrapped;

            coords.forEach(coord => {
                if (nextWrapState) {
                    sheet.wrap_cells[coord] = true;
                } else {
                    delete sheet.wrap_cells[coord];
                }
            });

            ssSaveSheetLayoutToLocalCache(sheet);
            renderSpreadsheetGrid();
            updateSpreadsheetWrapTextButtonUI();
            scheduleSpreadsheetAutoSyncToGoogleDrive(true);

            const targetDesc = coords.length === 1 ? `Cell ${coords[0]}` : `${coords.length} selected cells`;
            showToast(nextWrapState
                ? `📝 Wrap Text enabled on ${targetDesc}!`
                : `📏 Wrap Text disabled on ${targetDesc}.`
            );
        }

        function ssNormalizeCellValue(rawVal) {
            if (rawVal === null || rawVal === undefined) return '';
            // Replace raw newlines with a clean visual separator so single-line <input type="text"> cells never glue multi-turn replies together
            const rawStr = String(rawVal).replace(/\r?\n+/g, '  |  ');
            const s = rawStr.trim();
            if (!s || s.startsWith('=')) return rawStr;
            // Preserve leading-zero strings like '09175497760'
            if (s.length > 1 && s[0] === '0' && /^\d$/.test(s[1])) return rawStr;
            // Convert scientific notation (e.g. 1.3453184631841E+12, 1.554878515441E12) into exact plain number without '.' or 'E'
            const sciMatch = /^([+-]?)(\d+)(?:\.(\d+))?[eE]([+-]?\d+)$/.exec(s);
            if (sciMatch) {
                const sign = sciMatch[1] === '-' ? '-' : '';
                const intPart = sciMatch[2] || '0';
                const fracPart = sciMatch[3] || '';
                const exp = parseInt(sciMatch[4], 10);
                if (Number.isFinite(exp) && Math.abs(exp) <= 30) {
                    const digits = intPart + fracPart;
                    const shift = exp - fracPart.length;
                    if (shift >= 0) {
                        return sign + (digits + '0'.repeat(shift)).replace(/^0+(?=\d)/, '');
                    } else {
                        const splitPos = digits.length + shift;
                        if (splitPos > 0) {
                            const left = digits.slice(0, splitPos);
                            const right = digits.slice(splitPos).replace(/0+$/, '');
                            return sign + (right ? `${left}.${right}` : left);
                        } else {
                            const right = ('0'.repeat(-splitPos) + digits).replace(/0+$/, '');
                            return sign + (right ? `0.${right}` : '0');
                        }
                    }
                }
            }
            // Strip redundant trailing .0 on whole integers (e.g. "1345318463184.0" -> "1345318463184")
            if (/^[+-]?\d+\.0+$/.test(s)) {
                return s.replace(/\.0+$/, '');
            }
            return rawStr;
        }

        function ssSanitizeWorkbookCells(wb) {
            if (!wb || !Array.isArray(wb.sheets)) return wb;
            wb.sheets.forEach(sh => {
                if (!sh || typeof sh !== 'object') return;
                sh.cells = (sh.cells && typeof sh.cells === 'object') ? sh.cells : {};
                sh.wrap_cells = (sh.wrap_cells && typeof sh.wrap_cells === 'object') ? sh.wrap_cells : {};
                sh.col_widths = (sh.col_widths && typeof sh.col_widths === 'object') ? sh.col_widths : {};
                sh.row_heights = (sh.row_heights && typeof sh.row_heights === 'object') ? sh.row_heights : {};
                Object.keys(sh.cells).forEach(k => {
                    sh.cells[k] = ssNormalizeCellValue(sh.cells[k]);
                });
            });
            return wb;
        }

        function ssComputeWorkbookSignature(wb) {
            if (!wb || !Array.isArray(wb.sheets)) return '';
            try {
                return JSON.stringify(wb.sheets.map(s => {
                    const rawCells = s.cells || {};
                    const sortedKeys = Object.keys(rawCells).sort();
                    const normCells = {};
                    sortedKeys.forEach(k => {
                        const v = ssNormalizeCellValue(rawCells[k]);
                        if (v.trim() !== '') normCells[k.toUpperCase()] = v;
                    });
                    return {
                        name: s.name || 'Sheet1',
                        cells: normCells,
                        wrap_cells: s.wrap_cells || {},
                        col_widths: s.col_widths || {},
                        row_heights: s.row_heights || {}
                    };
                }));
            } catch (_) {
                return '';
            }
        }

        function ssUpdateSyncBadgeStatus(text, tone = 'neutral') {
            const badge = document.getElementById('ss-gdrive-sync-badge');
            if (!badge) return;
            badge.className = 'text-[10px] px-2 py-0.5 rounded-full font-mono transition-all ';
            if (tone === 'synced') {
                badge.className += 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/40';
            } else if (tone === 'syncing') {
                badge.className += 'bg-gb-cyan/15 text-gb-cyan border border-gb-cyan/40';
            } else if (tone === 'warn') {
                badge.className += 'bg-amber-500/15 text-amber-300 border border-amber-500/40';
            } else {
                badge.className += 'bg-slate-800 text-slate-300 border border-slate-600';
            }
            badge.textContent = text;
        }

        function ssColIdxToLetter(index) {
            let n = Math.max(0, Number(index || 0)) + 1;
            let letters = '';
            while (n > 0) {
                const rem = (n - 1) % 26;
                letters = String.fromCharCode(65 + rem) + letters;
                n = Math.floor((n - 1) / 26);
            }
            return letters || 'A';
        }

        function ssLetterToColIdx(colStr) {
            const clean = String(colStr || '').trim().toUpperCase().replace(/[^A-Z]/g, '');
            if (!clean) return 0;
            let res = 0;
            for (let i = 0; i < clean.length; i++) {
                res = res * 26 + (clean.charCodeAt(i) - 64);
            }
            return Math.max(0, res - 1);
        }

        function ssParseCoord(coord) {
            const m = /^([A-Za-z]+)(\d+)$/.exec(String(coord || '').trim());
            if (!m) return null;
            const colLetter = m[1].toUpperCase();
            const rowNum = parseInt(m[2], 10);
            if (rowNum < 1) return null;
            return { colLetter, colIndex: ssLetterToColIdx(colLetter), rowNum };
        }

        function ssGetActiveSheet() {
            const sheets = currentSpreadsheetWorkbook.sheets || [];
            if (sheets.length === 0) {
                currentSpreadsheetWorkbook.sheets = [{
                    id: 'sheet_1',
                    name: 'Sheet1',
                    row_count: 25,
                    col_count: 10,
                    cells: {},
                    wrap_cells: {},
                    col_widths: {},
                    row_heights: {}
                }];
            }
            if (activeSheetIndex < 0 || activeSheetIndex >= currentSpreadsheetWorkbook.sheets.length) {
                activeSheetIndex = 0;
            }
            const sheet = currentSpreadsheetWorkbook.sheets[activeSheetIndex];
            sheet.cells = sheet.cells || {};
            sheet.wrap_cells = sheet.wrap_cells || {};
            sheet.col_widths = sheet.col_widths || {};
            sheet.row_heights = sheet.row_heights || {};
            sheet.row_count = Math.max(15, Number(sheet.row_count || 25));
            sheet.col_count = Math.max(6, Number(sheet.col_count || 10));
            return sheet;
        }

        const SS_BLOCKED_IMAGE_FORMULAS = new Set([
            'IMAGE', 'SPARKLINE', 'IMPORTIMAGE', 'EMBEDIMAGE', 'WEBIMAGE', 'PICTURE'
        ]);

        function ssIsBlockedImageFormula(rawStr) {
            const s = String(rawStr || '').trim();
            if (!s.startsWith('=')) return false;
            const expr = s.slice(1).trim();
            const re = /\b([A-Za-z_][A-Za-z0-9_.]*)\s*\(/g;
            let m;
            while ((m = re.exec(expr)) !== null) {
                const fn = m[1].toUpperCase();
                if (SS_BLOCKED_IMAGE_FORMULAS.has(fn) || fn.includes('IMAGE')) {
                    return true;
                }
            }
            return false;
        }

        function ssSplitFormulaArgs(argsStr) {
            const args = [];
            let cur = '';
            let depth = 0;
            let inQuotes = false;
            for (let i = 0; i < argsStr.length; i++) {
                const ch = argsStr[i];
                if (ch === '"') {
                    if (inQuotes && i + 1 < argsStr.length && argsStr[i + 1] === '"') {
                        cur += '"';
                        i++;
                        continue;
                    }
                    inQuotes = !inQuotes;
                    cur += ch;
                } else if (!inQuotes) {
                    if (ch === '(') {
                        depth++;
                        cur += ch;
                    } else if (ch === ')') {
                        depth = Math.max(0, depth - 1);
                        cur += ch;
                    } else if ((ch === ',' || ch === ';') && depth === 0) {
                        args.push(cur.trim());
                        cur = '';
                    } else {
                        cur += ch;
                    }
                } else {
                    cur += ch;
                }
            }
            if (cur.trim() !== '' || /[,;]\s*$/.test(argsStr)) {
                args.push(cur.trim());
            }
            return args;
        }

        function ssFormatFormulaNumber(val) {
            if (!Number.isFinite(val)) return '#NUM!';
            if (Math.abs(val - Math.round(val)) < 1e-9) return String(Math.round(val));
            return String(Number(val.toFixed(6)));
        }

        function ssMatchesExcelCriteria(cellVal, criteriaRaw) {
            let critStr = String(criteriaRaw ?? '').trim();
            if (critStr.length >= 2 && critStr.startsWith('"') && critStr.endsWith('"')) {
                critStr = critStr.slice(1, -1);
            }
            const cStr = String(cellVal ?? '').trim();
            let op = '=';
            let rhs = critStr;
            for (const p of ['<>', '>=', '<=', '>', '<', '=']) {
                if (critStr.startsWith(p)) {
                    op = p;
                    rhs = critStr.slice(p.length).trim();
                    break;
                }
            }
            const lhsNum = cStr !== '' ? Number(cStr.replace(/,/g, '')) : NaN;
            const rhsNum = rhs !== '' ? Number(rhs.replace(/,/g, '')) : NaN;
            if (Number.isFinite(lhsNum) && Number.isFinite(rhsNum)) {
                if (op === '=') return Math.abs(lhsNum - rhsNum) < 1e-9;
                if (op === '<>') return Math.abs(lhsNum - rhsNum) >= 1e-9;
                if (op === '>') return lhsNum > rhsNum;
                if (op === '<') return lhsNum < rhsNum;
                if (op === '>=') return lhsNum >= rhsNum;
                if (op === '<=') return lhsNum <= rhsNum;
            }
            const lhsL = cStr.toLowerCase();
            const rhsL = rhs.toLowerCase();
            if ((op === '=' || op === '<>') && (rhsL.includes('*') || rhsL.includes('?'))) {
                const escaped = rhsL.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.');
                const matched = new RegExp(`^${escaped}$`, 'i').test(lhsL);
                return op === '=' ? matched : !matched;
            }
            if (op === '=') return lhsL === rhsL;
            if (op === '<>') return lhsL !== rhsL;
            if (op === '>') return lhsL > rhsL;
            if (op === '<') return lhsL < rhsL;
            if (op === '>=') return lhsL >= rhsL;
            if (op === '<=') return lhsL <= rhsL;
            return false;
        }

        function ssEvaluateCellDisplay(rawVal, cellsMap, depth = 0) {
            const str = ssNormalizeCellValue(rawVal ?? '');
            if (!str.startsWith('=')) return str;
            if (depth > 8) return '#REF!';
            const expr = str.slice(1).trim();
            if (!expr) return '';

            if (ssIsBlockedImageFormula(str)) {
                return '#IMAGE_FORMULA_NOT_ALLOWED!';
            }

            const getCellEval = (coordStr) => {
                const clean = String(coordStr || '').replace(/\$/g, '').trim().toUpperCase();
                return ssEvaluateCellDisplay(cellsMap[clean] || '', cellsMap, depth + 1);
            };

            const toFloat = (v, fallback = 0) => {
                if (typeof v === 'number') return Number.isFinite(v) ? v : fallback;
                const sv = String(v ?? '').trim();
                if (sv.toUpperCase() === 'TRUE') return 1;
                if (sv.toUpperCase() === 'FALSE') return 0;
                if (!sv) return fallback;
                const clean = sv.replace(/[$₱€£¥,\s]/g, '');
                if (clean.endsWith('%')) {
                    const p = Number(clean.slice(0, -1));
                    return Number.isFinite(p) ? p / 100 : fallback;
                }
                const n = Number(clean);
                return Number.isFinite(n) ? n : fallback;
            };

            const toBool = (v) => {
                if (typeof v === 'boolean') return v;
                const sv = String(v ?? '').trim().toUpperCase();
                if (sv === 'TRUE' || sv === '1' || sv === 'YES') return true;
                if (sv === 'FALSE' || sv === '0' || sv === '' || sv === 'NO') return false;
                const n = toFloat(sv, null);
                return n !== null ? Boolean(n) : true;
            };

            const expandRangeCoords = (rangeStr) => {
                const clean = String(rangeStr || '').replace(/\$/g, '').trim();
                const parts = clean.split(':');
                if (parts.length !== 2) return [];
                const s = ssParseCoord(parts[0]);
                const e = ssParseCoord(parts[1]);
                if (!s || !e) return [];
                const cMin = Math.min(s.colIndex, e.colIndex);
                const cMax = Math.max(s.colIndex, e.colIndex);
                const rMin = Math.min(s.rowNum, e.rowNum);
                const rMax = Math.max(s.rowNum, e.rowNum);
                const matrix = [];
                for (let r = rMin; r <= rMax; r++) {
                    const row = [];
                    for (let c = cMin; c <= cMax; c++) {
                        row.push(`${ssColIdxToLetter(c)}${r}`);
                    }
                    matrix.push(row);
                }
                return matrix;
            };

            const expandArgValues = (argExpr) => {
                const aClean = String(argExpr || '').trim();
                if (/^\$?[A-Za-z]+\$?\d+:\$?[A-Za-z]+\$?\d+$/.test(aClean)) {
                    const mat = expandRangeCoords(aClean);
                    const out = [];
                    mat.forEach(row => row.forEach(c => out.push(getCellEval(c))));
                    return out;
                }
                return [String(evalExpr(aClean))];
            };

            const expandArgNumbers = (argExpr) => {
                const aClean = String(argExpr || '').trim();
                if (/^\$?[A-Za-z]+\$?\d+:\$?[A-Za-z]+\$?\d+$/.test(aClean)) {
                    const mat = expandRangeCoords(aClean);
                    const nums = [];
                    mat.forEach(row => row.forEach(c => {
                        const rawCell = String(cellsMap[c] ?? '').trim();
                        if (!rawCell) return;
                        const fv = toFloat(getCellEval(c), null);
                        if (fv !== null) nums.push(fv);
                    }));
                    return nums;
                }
                if (/^\$?[A-Za-z]+\$?\d+$/.test(aClean)) {
                    const fv = toFloat(getCellEval(aClean), null);
                    return fv !== null ? [fv] : [];
                }
                const fv = toFloat(evalExpr(aClean), null);
                return fv !== null ? [fv] : [];
            };

            const evalFunction = (fnName, rawArgs) => {
                const fn = String(fnName || '').toUpperCase().replace(/^_XLFN\./, '');
                if (SS_BLOCKED_IMAGE_FORMULAS.has(fn) || fn.includes('IMAGE')) {
                    return '#IMAGE_FORMULA_NOT_ALLOWED!';
                }

                // --- LOGICAL ---
                if (fn === 'TRUE') return 'TRUE';
                if (fn === 'FALSE') return 'FALSE';
                if (fn === 'IF') {
                    if (!rawArgs.length) return '#VALUE!';
                    const cond = toBool(evalExpr(rawArgs[0]));
                    if (cond) return rawArgs.length > 1 ? evalExpr(rawArgs[1]) : 'TRUE';
                    return rawArgs.length > 2 ? evalExpr(rawArgs[2]) : 'FALSE';
                }
                if (fn === 'IFS') {
                    for (let i = 0; i + 1 < rawArgs.length; i += 2) {
                        if (toBool(evalExpr(rawArgs[i]))) return evalExpr(rawArgs[i + 1]);
                    }
                    return '#N/A';
                }
                if (fn === 'IFERROR') {
                    if (!rawArgs.length) return '';
                    const v = String(evalExpr(rawArgs[0]));
                    return v.startsWith('#') ? (rawArgs.length > 1 ? evalExpr(rawArgs[1]) : '') : v;
                }
                if (fn === 'IFNA') {
                    if (!rawArgs.length) return '';
                    const v = String(evalExpr(rawArgs[0]));
                    return v === '#N/A' ? (rawArgs.length > 1 ? evalExpr(rawArgs[1]) : '') : v;
                }
                if (fn === 'AND') {
                    const vals = rawArgs.flatMap(a => expandArgValues(a)).filter(v => String(v).trim() !== '');
                    return vals.length && vals.every(v => toBool(v)) ? 'TRUE' : 'FALSE';
                }
                if (fn === 'OR') {
                    const vals = rawArgs.flatMap(a => expandArgValues(a)).filter(v => String(v).trim() !== '');
                    return vals.some(v => toBool(v)) ? 'TRUE' : 'FALSE';
                }
                if (fn === 'XOR') {
                    const vals = rawArgs.flatMap(a => expandArgValues(a)).filter(v => String(v).trim() !== '');
                    const trues = vals.filter(v => toBool(v)).length;
                    return trues % 2 === 1 ? 'TRUE' : 'FALSE';
                }
                if (fn === 'NOT') {
                    return rawArgs.length && toBool(evalExpr(rawArgs[0])) ? 'FALSE' : 'TRUE';
                }
                if (fn === 'SWITCH') {
                    if (rawArgs.length < 3) return '#VALUE!';
                    const target = String(evalExpr(rawArgs[0])).trim().toLowerCase();
                    for (let i = 1; i + 1 < rawArgs.length; i += 2) {
                        if (String(evalExpr(rawArgs[i])).trim().toLowerCase() === target) {
                            return evalExpr(rawArgs[i + 1]);
                        }
                    }
                    return rawArgs.length % 2 === 0 ? evalExpr(rawArgs[rawArgs.length - 1]) : '#N/A';
                }

                // --- AGGREGATE & STATISTICAL ---
                if (['SUM', 'AVERAGE', 'AVG', 'MIN', 'MAX', 'COUNT', 'COUNTA', 'COUNTBLANK', 'MEDIAN', 'MODE', 'STDEV', 'STDEV.S', 'STDEVP', 'STDEV.P', 'VAR', 'VAR.S', 'VARP', 'VAR.P', 'PRODUCT'].includes(fn)) {
                    if (fn === 'COUNTA') {
                        return String(rawArgs.flatMap(a => expandArgValues(a)).filter(v => String(v).trim() !== '').length);
                    }
                    if (fn === 'COUNTBLANK') {
                        return String(rawArgs.flatMap(a => expandArgValues(a)).filter(v => String(v).trim() === '').length);
                    }
                    const nums = rawArgs.flatMap(a => expandArgNumbers(a));
                    if (fn === 'COUNT') return String(nums.length);
                    if (fn === 'SUM') return ssFormatFormulaNumber(nums.reduce((a, b) => a + b, 0));
                    if (fn === 'PRODUCT') return nums.length ? ssFormatFormulaNumber(nums.reduce((a, b) => a * b, 1)) : '0';
                    if (!nums.length) return (fn === 'AVERAGE' || fn === 'AVG') ? '#DIV/0!' : '0';
                    if (fn === 'AVERAGE' || fn === 'AVG') return ssFormatFormulaNumber(nums.reduce((a, b) => a + b, 0) / nums.length);
                    if (fn === 'MIN') return ssFormatFormulaNumber(Math.min(...nums));
                    if (fn === 'MAX') return ssFormatFormulaNumber(Math.max(...nums));
                    if (fn === 'MEDIAN') {
                        const s = [...nums].sort((a, b) => a - b);
                        const mid = Math.floor(s.length / 2);
                        return ssFormatFormulaNumber(s.length % 2 === 1 ? s[mid] : (s[mid - 1] + s[mid]) / 2);
                    }
                    if (fn === 'MODE') {
                        const counts = new Map();
                        let best = nums[0];
                        let bestCnt = 0;
                        nums.forEach(n => {
                            const c = (counts.get(n) || 0) + 1;
                            counts.set(n, c);
                            if (c > bestCnt) { bestCnt = c; best = n; }
                        });
                        return ssFormatFormulaNumber(best);
                    }
                    if (fn === 'VAR' || fn === 'VAR.S' || fn === 'STDEV' || fn === 'STDEV.S') {
                        if (nums.length < 2) return '#DIV/0!';
                        const mean = nums.reduce((a, b) => a + b, 0) / nums.length;
                        const v = nums.reduce((a, x) => a + Math.pow(x - mean, 2), 0) / (nums.length - 1);
                        return ssFormatFormulaNumber(fn.includes('STDEV') ? Math.sqrt(v) : v);
                    }
                    if (fn === 'VARP' || fn === 'VAR.P' || fn === 'STDEVP' || fn === 'STDEV.P') {
                        const mean = nums.reduce((a, b) => a + b, 0) / nums.length;
                        const v = nums.reduce((a, x) => a + Math.pow(x - mean, 2), 0) / nums.length;
                        return ssFormatFormulaNumber(fn.includes('STDEV') ? Math.sqrt(v) : v);
                    }
                }
                if (fn === 'LARGE' || fn === 'SMALL') {
                    if (rawArgs.length < 2) return '#VALUE!';
                    const nums = expandArgNumbers(rawArgs[0]).sort((a, b) => fn === 'LARGE' ? b - a : a - b);
                    const k = Math.trunc(toFloat(evalExpr(rawArgs[1]), 1));
                    if (k < 1 || k > nums.length) return '#NUM!';
                    return ssFormatFormulaNumber(nums[k - 1]);
                }
                if (fn === 'SUMPRODUCT') {
                    if (!rawArgs.length) return '0';
                    const arrays = rawArgs.map(a => expandArgValues(a).map(v => toFloat(v, 0)));
                    const minLen = Math.min(...arrays.map(arr => arr.length));
                    let total = 0;
                    for (let i = 0; i < minLen; i++) {
                        let p = 1;
                        arrays.forEach(arr => { p *= arr[i]; });
                        total += p;
                    }
                    return ssFormatFormulaNumber(total);
                }

                // --- CONDITIONAL AGGREGATES ---
                if (fn === 'COUNTIF' || fn === 'SUMIF' || fn === 'AVERAGEIF') {
                    if (rawArgs.length < 2) return '#VALUE!';
                    const critCoords = expandRangeCoords(rawArgs[0]).flat();
                    const critVal = evalExpr(rawArgs[1]);
                    const valCoords = rawArgs.length > 2 ? expandRangeCoords(rawArgs[2]).flat() : critCoords;
                    const matchedNums = [];
                    let matchedCount = 0;
                    critCoords.forEach((cCoord, idx) => {
                        if (ssMatchesExcelCriteria(getCellEval(cCoord), critVal)) {
                            matchedCount++;
                            if (idx < valCoords.length) {
                                const fv = toFloat(getCellEval(valCoords[idx]), null);
                                if (fv !== null) matchedNums.push(fv);
                            }
                        }
                    });
                    if (fn === 'COUNTIF') return String(matchedCount);
                    if (fn === 'SUMIF') return ssFormatFormulaNumber(matchedNums.reduce((a, b) => a + b, 0));
                    return matchedNums.length ? ssFormatFormulaNumber(matchedNums.reduce((a, b) => a + b, 0) / matchedNums.length) : '#DIV/0!';
                }
                if (['COUNTIFS', 'SUMIFS', 'AVERAGEIFS', 'MINIFS', 'MAXIFS'].includes(fn)) {
                    if (fn === 'COUNTIFS') {
                        if (rawArgs.length < 2 || rawArgs.length % 2 !== 0) return '#VALUE!';
                        const firstCoords = expandRangeCoords(rawArgs[0]).flat();
                        const pairs = [];
                        for (let i = 0; i < rawArgs.length; i += 2) {
                            pairs.push([expandRangeCoords(rawArgs[i]).flat(), evalExpr(rawArgs[i + 1])]);
                        }
                        let cnt = 0;
                        for (let i = 0; i < firstCoords.length; i++) {
                            if (pairs.every(([rc, cv]) => i < rc.length && ssMatchesExcelCriteria(getCellEval(rc[i]), cv))) cnt++;
                        }
                        return String(cnt);
                    } else {
                        if (rawArgs.length < 3 || rawArgs.length % 2 === 0) return '#VALUE!';
                        const targetCoords = expandRangeCoords(rawArgs[0]).flat();
                        const pairs = [];
                        for (let i = 1; i < rawArgs.length; i += 2) {
                            pairs.push([expandRangeCoords(rawArgs[i]).flat(), evalExpr(rawArgs[i + 1])]);
                        }
                        const matched = [];
                        targetCoords.forEach((tc, i) => {
                            if (pairs.every(([rc, cv]) => i < rc.length && ssMatchesExcelCriteria(getCellEval(rc[i]), cv))) {
                                const fv = toFloat(getCellEval(tc), null);
                                if (fv !== null) matched.push(fv);
                            }
                        });
                        if (fn === 'SUMIFS') return ssFormatFormulaNumber(matched.reduce((a, b) => a + b, 0));
                        if (fn === 'AVERAGEIFS') return matched.length ? ssFormatFormulaNumber(matched.reduce((a, b) => a + b, 0) / matched.length) : '#DIV/0!';
                        if (fn === 'MINIFS') return matched.length ? ssFormatFormulaNumber(Math.min(...matched)) : '0';
                        if (fn === 'MAXIFS') return matched.length ? ssFormatFormulaNumber(Math.max(...matched)) : '0';
                    }
                }

                // --- MATH & TRIG ---
                if (fn === 'ABS') return rawArgs.length ? ssFormatFormulaNumber(Math.abs(toFloat(evalExpr(rawArgs[0]), 0))) : '0';
                if (fn === 'ROUND') {
                    const n = toFloat(evalExpr(rawArgs[0]), 0);
                    const d = rawArgs.length > 1 ? Math.trunc(toFloat(evalExpr(rawArgs[1]), 0)) : 0;
                    const f = Math.pow(10, d);
                    return ssFormatFormulaNumber(Math.round(n * f) / f);
                }
                if (fn === 'ROUNDUP') {
                    const n = toFloat(evalExpr(rawArgs[0]), 0);
                    const d = rawArgs.length > 1 ? Math.trunc(toFloat(evalExpr(rawArgs[1]), 0)) : 0;
                    const f = Math.pow(10, d);
                    return ssFormatFormulaNumber((n >= 0 ? Math.ceil(n * f) : Math.floor(n * f)) / f);
                }
                if (fn === 'ROUNDDOWN' || fn === 'TRUNC') {
                    const n = toFloat(evalExpr(rawArgs[0]), 0);
                    const d = rawArgs.length > 1 ? Math.trunc(toFloat(evalExpr(rawArgs[1]), 0)) : 0;
                    const f = Math.pow(10, d);
                    return ssFormatFormulaNumber(Math.trunc(n * f) / f);
                }
                if (fn === 'INT') return ssFormatFormulaNumber(Math.floor(toFloat(evalExpr(rawArgs[0]), 0)));
                if (fn === 'MOD') {
                    if (rawArgs.length < 2) return '#VALUE!';
                    const a = toFloat(evalExpr(rawArgs[0]), 0);
                    const b = toFloat(evalExpr(rawArgs[1]), 0);
                    if (b === 0) return '#DIV/0!';
                    return ssFormatFormulaNumber(((a % b) + b) % b);
                }
                if (fn === 'POWER' || fn === 'POW') {
                    if (rawArgs.length < 2) return '#VALUE!';
                    return ssFormatFormulaNumber(Math.pow(toFloat(evalExpr(rawArgs[0]), 0), toFloat(evalExpr(rawArgs[1]), 0)));
                }
                if (fn === 'SQRT') {
                    const n = toFloat(evalExpr(rawArgs[0]), 0);
                    return n >= 0 ? ssFormatFormulaNumber(Math.sqrt(n)) : '#NUM!';
                }
                if (fn === 'EXP') return ssFormatFormulaNumber(Math.exp(toFloat(evalExpr(rawArgs[0]), 0)));
                if (fn === 'LN') {
                    const n = toFloat(evalExpr(rawArgs[0]), 0);
                    return n > 0 ? ssFormatFormulaNumber(Math.log(n)) : '#NUM!';
                }
                if (fn === 'LOG10') {
                    const n = toFloat(evalExpr(rawArgs[0]), 0);
                    return n > 0 ? ssFormatFormulaNumber(Math.log10(n)) : '#NUM!';
                }
                if (fn === 'LOG') {
                    const n = toFloat(evalExpr(rawArgs[0]), 0);
                    const base = rawArgs.length > 1 ? toFloat(evalExpr(rawArgs[1]), 10) : 10;
                    return (n > 0 && base > 0) ? ssFormatFormulaNumber(Math.log(n) / Math.log(base)) : '#NUM!';
                }
                if (fn === 'PI') return ssFormatFormulaNumber(Math.PI);
                if (fn === 'SIGN') {
                    const n = toFloat(evalExpr(rawArgs[0]), 0);
                    return n > 0 ? '1' : (n < 0 ? '-1' : '0');
                }
                if (fn === 'SIN') return ssFormatFormulaNumber(Math.sin(toFloat(evalExpr(rawArgs[0]), 0)));
                if (fn === 'COS') return ssFormatFormulaNumber(Math.cos(toFloat(evalExpr(rawArgs[0]), 0)));
                if (fn === 'TAN') return ssFormatFormulaNumber(Math.tan(toFloat(evalExpr(rawArgs[0]), 0)));
                if (fn === 'RADIANS') return ssFormatFormulaNumber(toFloat(evalExpr(rawArgs[0]), 0) * (Math.PI / 180));
                if (fn === 'DEGREES') return ssFormatFormulaNumber(toFloat(evalExpr(rawArgs[0]), 0) * (180 / Math.PI));
                if (fn === 'CEILING' || fn === 'CEIL') {
                    const n = toFloat(evalExpr(rawArgs[0]), 0);
                    const sig = rawArgs.length > 1 ? toFloat(evalExpr(rawArgs[1]), 1) : 1;
                    return sig ? ssFormatFormulaNumber(Math.ceil(n / sig) * sig) : '0';
                }
                if (fn === 'FLOOR') {
                    const n = toFloat(evalExpr(rawArgs[0]), 0);
                    const sig = rawArgs.length > 1 ? toFloat(evalExpr(rawArgs[1]), 1) : 1;
                    return sig ? ssFormatFormulaNumber(Math.floor(n / sig) * sig) : '0';
                }

                // --- LOOKUP & REFERENCE ---
                if (fn === 'VLOOKUP') {
                    if (rawArgs.length < 3) return '#VALUE!';
                    const lookupVal = String(evalExpr(rawArgs[0])).trim();
                    const mat = expandRangeCoords(rawArgs[1]);
                    const colIdx = Math.trunc(toFloat(evalExpr(rawArgs[2]), 1));
                    if (!mat.length || colIdx < 1 || colIdx > mat[0].length) return '#REF!';
                    for (const row of mat) {
                        if (ssMatchesExcelCriteria(getCellEval(row[0]).trim(), lookupVal)) {
                            return getCellEval(row[colIdx - 1]);
                        }
                    }
                    return '#N/A';
                }
                if (fn === 'HLOOKUP') {
                    if (rawArgs.length < 3) return '#VALUE!';
                    const lookupVal = String(evalExpr(rawArgs[0])).trim();
                    const mat = expandRangeCoords(rawArgs[1]);
                    const rowIdx = Math.trunc(toFloat(evalExpr(rawArgs[2]), 1));
                    if (!mat.length || rowIdx < 1 || rowIdx > mat.length) return '#REF!';
                    for (let c = 0; c < mat[0].length; c++) {
                        if (ssMatchesExcelCriteria(getCellEval(mat[0][c]).trim(), lookupVal)) {
                            return getCellEval(mat[rowIdx - 1][c]);
                        }
                    }
                    return '#N/A';
                }
                if (fn === 'XLOOKUP') {
                    if (rawArgs.length < 3) return '#VALUE!';
                    const lookupVal = String(evalExpr(rawArgs[0])).trim();
                    const lCoords = expandRangeCoords(rawArgs[1]).flat();
                    const rCoords = expandRangeCoords(rawArgs[2]).flat();
                    const notFound = rawArgs.length > 3 ? evalExpr(rawArgs[3]) : '#N/A';
                    for (let i = 0; i < lCoords.length; i++) {
                        if (ssMatchesExcelCriteria(getCellEval(lCoords[i]).trim(), lookupVal)) {
                            return i < rCoords.length ? getCellEval(rCoords[i]) : '#REF!';
                        }
                    }
                    return notFound;
                }
                if (fn === 'INDEX') {
                    if (rawArgs.length < 2) return '#VALUE!';
                    const mat = expandRangeCoords(rawArgs[0]);
                    if (!mat.length) return '#REF!';
                    let rNum = Math.trunc(toFloat(evalExpr(rawArgs[1]), 1));
                    let cNum = rawArgs.length > 2 ? Math.trunc(toFloat(evalExpr(rawArgs[2]), 1)) : 1;
                    if (mat.length === 1 && rNum > 1 && cNum === 1) {
                        cNum = rNum;
                        rNum = 1;
                    }
                    if (rNum < 1 || rNum > mat.length || cNum < 1 || cNum > mat[0].length) return '#REF!';
                    return getCellEval(mat[rNum - 1][cNum - 1]);
                }
                if (fn === 'MATCH') {
                    if (rawArgs.length < 2) return '#VALUE!';
                    const lookupVal = String(evalExpr(rawArgs[0])).trim();
                    const lCoords = expandRangeCoords(rawArgs[1]).flat();
                    for (let i = 0; i < lCoords.length; i++) {
                        if (ssMatchesExcelCriteria(getCellEval(lCoords[i]).trim(), lookupVal)) return String(i + 1);
                    }
                    return '#N/A';
                }
                if (fn === 'CHOOSE') {
                    if (rawArgs.length < 2) return '#VALUE!';
                    const idx = Math.trunc(toFloat(evalExpr(rawArgs[0]), 0));
                    if (idx < 1 || idx >= rawArgs.length) return '#VALUE!';
                    return evalExpr(rawArgs[idx]);
                }
                if (fn === 'ROW') {
                    if (!rawArgs.length) return String((ssParseCoord(activeCellCoord) || { rowNum: 1 }).rowNum);
                    const p = ssParseCoord(String(rawArgs[0]).replace(/\$/g, '').split(':')[0]);
                    return p ? String(p.rowNum) : '#REF!';
                }
                if (fn === 'COLUMN') {
                    if (!rawArgs.length) return String(((ssParseCoord(activeCellCoord) || { colIndex: 0 }).colIndex) + 1);
                    const p = ssParseCoord(String(rawArgs[0]).replace(/\$/g, '').split(':')[0]);
                    return p ? String(p.colIndex + 1) : '#REF!';
                }
                if (fn === 'ROWS') {
                    const mat = rawArgs.length ? expandRangeCoords(rawArgs[0]) : [];
                    return String(mat.length || 1);
                }
                if (fn === 'COLUMNS') {
                    const mat = rawArgs.length ? expandRangeCoords(rawArgs[0]) : [];
                    return String((mat[0] && mat[0].length) || 1);
                }

                // --- TEXT / STRING ---
                if (fn === 'CONCAT' || fn === 'CONCATENATE') {
                    return rawArgs.flatMap(a => expandArgValues(a)).join('');
                }
                if (fn === 'TEXTJOIN') {
                    if (rawArgs.length < 3) return '#VALUE!';
                    const delim = String(evalExpr(rawArgs[0]));
                    const ignoreEmpty = toBool(evalExpr(rawArgs[1]));
                    let vals = rawArgs.slice(2).flatMap(a => expandArgValues(a));
                    if (ignoreEmpty) vals = vals.filter(v => v !== '');
                    return vals.join(delim);
                }
                if (fn === 'LEN') return rawArgs.length ? String(String(evalExpr(rawArgs[0])).length) : '0';
                if (fn === 'LOWER') return rawArgs.length ? String(evalExpr(rawArgs[0])).toLowerCase() : '';
                if (fn === 'UPPER') return rawArgs.length ? String(evalExpr(rawArgs[0])).toUpperCase() : '';
                if (fn === 'PROPER') {
                    return rawArgs.length ? String(evalExpr(rawArgs[0])).toLowerCase().replace(/\b\w/g, c => c.toUpperCase()) : '';
                }
                if (fn === 'TRIM') return rawArgs.length ? String(evalExpr(rawArgs[0])).trim().replace(/\s+/g, ' ') : '';
                if (fn === 'LEFT') {
                    const txt = rawArgs.length ? String(evalExpr(rawArgs[0])) : '';
                    const n = rawArgs.length > 1 ? Math.max(0, Math.trunc(toFloat(evalExpr(rawArgs[1]), 1))) : 1;
                    return txt.slice(0, n);
                }
                if (fn === 'RIGHT') {
                    const txt = rawArgs.length ? String(evalExpr(rawArgs[0])) : '';
                    const n = rawArgs.length > 1 ? Math.max(0, Math.trunc(toFloat(evalExpr(rawArgs[1]), 1))) : 1;
                    return n > 0 ? txt.slice(-n) : '';
                }
                if (fn === 'MID') {
                    if (rawArgs.length < 3) return '#VALUE!';
                    const txt = String(evalExpr(rawArgs[0]));
                    const start = Math.max(1, Math.trunc(toFloat(evalExpr(rawArgs[1]), 1)));
                    const len = Math.max(0, Math.trunc(toFloat(evalExpr(rawArgs[2]), 0)));
                    return txt.slice(start - 1, start - 1 + len);
                }
                if (fn === 'SUBSTITUTE') {
                    if (rawArgs.length < 3) return '#VALUE!';
                    const srcTxt = String(evalExpr(rawArgs[0]));
                    const oldTxt = String(evalExpr(rawArgs[1]));
                    const newTxt = String(evalExpr(rawArgs[2]));
                    if (!oldTxt) return srcTxt;
                    if (rawArgs.length >= 4) {
                        const instNum = Math.trunc(toFloat(evalExpr(rawArgs[3]), 0));
                        if (instNum < 1) return '#VALUE!';
                        let occ = 0;
                        let pos = 0;
                        while (pos <= srcTxt.length) {
                            const found = srcTxt.indexOf(oldTxt, pos);
                            if (found === -1) break;
                            occ++;
                            if (occ === instNum) {
                                return srcTxt.slice(0, found) + newTxt + srcTxt.slice(found + oldTxt.length);
                            }
                            pos = found + oldTxt.length;
                        }
                        return srcTxt;
                    }
                    return srcTxt.split(oldTxt).join(newTxt);
                }
                if (fn === 'REPLACE') {
                    if (rawArgs.length < 4) return '#VALUE!';
                    const txt = String(evalExpr(rawArgs[0]));
                    const start = Math.max(1, Math.trunc(toFloat(evalExpr(rawArgs[1]), 1)));
                    const numChars = Math.max(0, Math.trunc(toFloat(evalExpr(rawArgs[2]), 0)));
                    const newS = String(evalExpr(rawArgs[3]));
                    return txt.slice(0, start - 1) + newS + txt.slice(start - 1 + numChars);
                }
                if (fn === 'FIND' || fn === 'SEARCH') {
                    if (rawArgs.length < 2) return '#VALUE!';
                    const needle = String(evalExpr(rawArgs[0]));
                    const haystack = String(evalExpr(rawArgs[1]));
                    const start = rawArgs.length > 2 ? Math.max(1, Math.trunc(toFloat(evalExpr(rawArgs[2]), 1))) : 1;
                    const idx = fn === 'SEARCH'
                        ? haystack.toLowerCase().indexOf(needle.toLowerCase(), start - 1)
                        : haystack.indexOf(needle, start - 1);
                    return idx >= 0 ? String(idx + 1) : '#VALUE!';
                }
                if (fn === 'REPT') {
                    if (rawArgs.length < 2) return '#VALUE!';
                    const txt = String(evalExpr(rawArgs[0]));
                    const cnt = Math.max(0, Math.min(1000, Math.trunc(toFloat(evalExpr(rawArgs[1]), 0))));
                    return txt.repeat(cnt);
                }
                if (fn === 'EXACT') {
                    return rawArgs.length >= 2 && String(evalExpr(rawArgs[0])) === String(evalExpr(rawArgs[1])) ? 'TRUE' : 'FALSE';
                }
                if (fn === 'VALUE') {
                    const fv = toFloat(rawArgs.length ? evalExpr(rawArgs[0]) : '', null);
                    return fv !== null ? ssFormatFormulaNumber(fv) : '#VALUE!';
                }

                // --- DATE & TIME ---
                if (fn === 'TODAY') return new Date().toISOString().slice(0, 10);
                if (fn === 'NOW') {
                    const d = new Date();
                    return `${d.toISOString().slice(0, 10)} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
                }
                if (fn === 'DATE') {
                    if (rawArgs.length < 3) return '#VALUE!';
                    const y = Math.trunc(toFloat(evalExpr(rawArgs[0]), 2026));
                    const m = Math.trunc(toFloat(evalExpr(rawArgs[1]), 1));
                    const d = Math.trunc(toFloat(evalExpr(rawArgs[2]), 1));
                    const dt = new Date(Date.UTC(y, m - 1, d));
                    return Number.isNaN(dt.getTime()) ? '#VALUE!' : dt.toISOString().slice(0, 10);
                }
                if (fn === 'YEAR' || fn === 'MONTH' || fn === 'DAY') {
                    const rawD = rawArgs.length ? String(evalExpr(rawArgs[0])).trim() : '';
                    const isoM = /^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/.exec(rawD);
                    if (isoM) {
                        if (fn === 'YEAR') return String(parseInt(isoM[1], 10));
                        if (fn === 'MONTH') return String(parseInt(isoM[2], 10));
                        return String(parseInt(isoM[3], 10));
                    }
                    const dt = new Date(rawD);
                    if (Number.isNaN(dt.getTime())) return '#VALUE!';
                    if (fn === 'YEAR') return String(dt.getFullYear());
                    if (fn === 'MONTH') return String(dt.getMonth() + 1);
                    return String(dt.getDate());
                }
                if (fn === 'DAYS') {
                    if (rawArgs.length < 2) return '#VALUE!';
                    const d1 = new Date(String(evalExpr(rawArgs[0])));
                    const d2 = new Date(String(evalExpr(rawArgs[1])));
                    if (Number.isNaN(d1.getTime()) || Number.isNaN(d2.getTime())) return '#VALUE!';
                    return String(Math.round((d1.getTime() - d2.getTime()) / 86400000));
                }

                // --- FINANCIAL ---
                if (fn === 'PMT') {
                    if (rawArgs.length < 3) return '#VALUE!';
                    const rate = toFloat(evalExpr(rawArgs[0]), 0);
                    const nper = toFloat(evalExpr(rawArgs[1]), 0);
                    const pv = toFloat(evalExpr(rawArgs[2]), 0);
                    const fv = rawArgs.length > 3 ? toFloat(evalExpr(rawArgs[3]), 0) : 0;
                    const type = rawArgs.length > 4 && toFloat(evalExpr(rawArgs[4]), 0) ? 1 : 0;
                    if (nper === 0) return '#DIV/0!';
                    if (rate === 0) return ssFormatFormulaNumber(-(pv + fv) / nper);
                    const factor = Math.pow(1 + rate, nper);
                    const pmt = -(rate * (pv * factor + fv)) / ((1 + rate * type) * (factor - 1));
                    return ssFormatFormulaNumber(pmt);
                }
                if (fn === 'FV') {
                    if (rawArgs.length < 3) return '#VALUE!';
                    const rate = toFloat(evalExpr(rawArgs[0]), 0);
                    const nper = toFloat(evalExpr(rawArgs[1]), 0);
                    const pmt = toFloat(evalExpr(rawArgs[2]), 0);
                    const pv = rawArgs.length > 3 ? toFloat(evalExpr(rawArgs[3]), 0) : 0;
                    const type = rawArgs.length > 4 && toFloat(evalExpr(rawArgs[4]), 0) ? 1 : 0;
                    if (rate === 0) return ssFormatFormulaNumber(-(pv + pmt * nper));
                    const factor = Math.pow(1 + rate, nper);
                    return ssFormatFormulaNumber(-(pv * factor + pmt * (1 + rate * type) * (factor - 1) / rate));
                }
                if (fn === 'PV') {
                    if (rawArgs.length < 3) return '#VALUE!';
                    const rate = toFloat(evalExpr(rawArgs[0]), 0);
                    const nper = toFloat(evalExpr(rawArgs[1]), 0);
                    const pmt = toFloat(evalExpr(rawArgs[2]), 0);
                    const fv = rawArgs.length > 3 ? toFloat(evalExpr(rawArgs[3]), 0) : 0;
                    const type = rawArgs.length > 4 && toFloat(evalExpr(rawArgs[4]), 0) ? 1 : 0;
                    if (rate === 0) return ssFormatFormulaNumber(-(fv + pmt * nper));
                    const factor = Math.pow(1 + rate, nper);
                    return ssFormatFormulaNumber(-(fv + pmt * (1 + rate * type) * (factor - 1) / rate) / factor);
                }
                if (fn === 'NPV') {
                    if (rawArgs.length < 2) return '#VALUE!';
                    const rate = toFloat(evalExpr(rawArgs[0]), 0);
                    const cfs = rawArgs.slice(1).flatMap(a => expandArgNumbers(a));
                    const npv = cfs.reduce((acc, cf, idx) => acc + cf / Math.pow(1 + rate, idx + 1), 0);
                    return ssFormatFormulaNumber(npv);
                }

                // --- INFORMATION ---
                if (fn === 'ISBLANK') {
                    if (!rawArgs.length) return 'TRUE';
                    const ac = rawArgs[0].trim();
                    if (/^\$?[A-Za-z]+\$?\d+$/.test(ac)) {
                        return String(cellsMap[ac.replace(/\$/g, '').toUpperCase()] ?? '').trim() === '' ? 'TRUE' : 'FALSE';
                    }
                    return String(evalExpr(ac)).trim() === '' ? 'TRUE' : 'FALSE';
                }
                if (fn === 'ISNUMBER') {
                    return rawArgs.length && toFloat(evalExpr(rawArgs[0]), null) !== null ? 'TRUE' : 'FALSE';
                }
                if (fn === 'ISTEXT') {
                    if (!rawArgs.length) return 'FALSE';
                    const v = String(evalExpr(rawArgs[0])).trim();
                    return (v !== '' && toFloat(v, null) === null && !v.startsWith('#')) ? 'TRUE' : 'FALSE';
                }
                if (fn === 'ISERROR') {
                    return rawArgs.length && String(evalExpr(rawArgs[0])).startsWith('#') ? 'TRUE' : 'FALSE';
                }
                if (fn === 'ISNA') {
                    return rawArgs.length && String(evalExpr(rawArgs[0])) === '#N/A' ? 'TRUE' : 'FALSE';
                }
                if (fn === 'ISEVEN') {
                    const n = toFloat(rawArgs.length ? evalExpr(rawArgs[0]) : '', null);
                    return n !== null && Math.trunc(n) % 2 === 0 ? 'TRUE' : 'FALSE';
                }
                if (fn === 'ISODD') {
                    const n = toFloat(rawArgs.length ? evalExpr(rawArgs[0]) : '', null);
                    return n !== null && Math.trunc(n) % 2 !== 0 ? 'TRUE' : 'FALSE';
                }

                // --- EXTENDED EXCEL FORMULA ENGINE (ALL 10 CATEGORIES) ---
                if (typeof window.ssEvaluateExtendedFormula === 'function') {
                    const extResult = window.ssEvaluateExtendedFormula(fn, rawArgs, {
                        cellsMap,
                        getCellEval,
                        toFloat,
                        toBool,
                        expandRangeCoords,
                        expandArgValues,
                        expandArgNumbers,
                        evalExpr,
                        formatNum: ssFormatFormulaNumber,
                        matchesCriteria: ssMatchesExcelCriteria,
                        splitArgs: ssSplitFormulaArgs
                    });
                    if (extResult !== null && extResult !== undefined) {
                        return extResult;
                    }
                }

                return '#NAME?';
            };

            const evalExpr = (subExpr) => {
                let t = String(subExpr ?? '').trim();
                if (!t) return '';

                // Strip redundant outer parentheses if balanced
                while (t.startsWith('(') && t.endsWith(')')) {
                    let depthP = 0;
                    let inQ = false;
                    let balancedOuter = true;
                    for (let i = 0; i < t.length; i++) {
                        const ch = t[i];
                        if (ch === '"') inQ = !inQ;
                        else if (!inQ) {
                            if (ch === '(') depthP++;
                            else if (ch === ')') {
                                depthP--;
                                if (depthP === 0 && i < t.length - 1) {
                                    balancedOuter = false;
                                    break;
                                }
                            }
                        }
                    }
                    if (balancedOuter && depthP === 0) t = t.slice(1, -1).trim();
                    else break;
                }

                // String literal
                if (t.length >= 2 && t.startsWith('"') && t.endsWith('"')) {
                    const inner = t.slice(1, -1);
                    if (!inner.replace(/""/g, '').includes('"')) {
                        return inner.replace(/""/g, '"');
                    }
                }

                // Top-level comparison operators: <>, >=, <=, =, >, <
                let inQ = false;
                let depthP = 0;
                for (let i = 0; i < t.length; i++) {
                    const ch = t[i];
                    if (ch === '"') inQ = !inQ;
                    else if (!inQ) {
                        if (ch === '(') depthP++;
                        else if (ch === ')') depthP = Math.max(0, depthP - 1);
                        else if (depthP === 0) {
                            for (const opStr of ['<>', '>=', '<=', '=', '>', '<']) {
                                if (t.slice(i).startsWith(opStr)) {
                                    const lhs = evalExpr(t.slice(0, i));
                                    const rhs = evalExpr(t.slice(i + opStr.length));
                                    return ssMatchesExcelCriteria(lhs, `${opStr}${rhs}`) ? 'TRUE' : 'FALSE';
                                }
                            }
                        }
                    }
                }

                // Top-level string concatenation (&)
                inQ = false;
                depthP = 0;
                for (let i = 0; i < t.length; i++) {
                    const ch = t[i];
                    if (ch === '"') inQ = !inQ;
                    else if (!inQ) {
                        if (ch === '(') depthP++;
                        else if (ch === ')') depthP = Math.max(0, depthP - 1);
                        else if (ch === '&' && depthP === 0) {
                            return `${evalExpr(t.slice(0, i))}${evalExpr(t.slice(i + 1))}`;
                        }
                    }
                }

                // Top-level addition / subtraction (+ / -) scanning right-to-left
                inQ = false;
                depthP = 0;
                for (let i = t.length - 1; i >= 0; i--) {
                    const ch = t[i];
                    if (ch === '"') inQ = !inQ;
                    else if (!inQ) {
                        if (ch === ')') depthP++;
                        else if (ch === '(') depthP = Math.max(0, depthP - 1);
                        else if (depthP === 0 && (ch === '+' || ch === '-') && i > 0) {
                            const prev = t.slice(0, i).trimEnd();
                            if (prev && !['+', '-', '*', '/', '^', '(', ',', ';', '=', '<', '>'].includes(prev[prev.length - 1])) {
                                const lhsV = evalExpr(t.slice(0, i));
                                const rhsV = evalExpr(t.slice(i + 1));
                                if (String(lhsV).startsWith('#')) return lhsV;
                                if (String(rhsV).startsWith('#')) return rhsV;
                                const ln = toFloat(lhsV, null);
                                const rn = toFloat(rhsV, null);
                                if (ln === null || rn === null) return '#VALUE!';
                                return ssFormatFormulaNumber(ch === '+' ? ln + rn : ln - rn);
                            }
                        }
                    }
                }

                // Top-level multiplication / division (* / /) scanning right-to-left
                inQ = false;
                depthP = 0;
                for (let i = t.length - 1; i >= 0; i--) {
                    const ch = t[i];
                    if (ch === '"') inQ = !inQ;
                    else if (!inQ) {
                        if (ch === ')') depthP++;
                        else if (ch === '(') depthP = Math.max(0, depthP - 1);
                        else if (depthP === 0 && (ch === '*' || ch === '/') && i > 0) {
                            const lhsV = evalExpr(t.slice(0, i));
                            const rhsV = evalExpr(t.slice(i + 1));
                            if (String(lhsV).startsWith('#')) return lhsV;
                            if (String(rhsV).startsWith('#')) return rhsV;
                            const ln = toFloat(lhsV, null);
                            const rn = toFloat(rhsV, null);
                            if (ln === null || rn === null) return '#VALUE!';
                            if (ch === '/') return rn === 0 ? '#DIV/0!' : ssFormatFormulaNumber(ln / rn);
                            return ssFormatFormulaNumber(ln * rn);
                        }
                    }
                }

                // Top-level exponentiation (^)
                inQ = false;
                depthP = 0;
                for (let i = t.length - 1; i >= 0; i--) {
                    const ch = t[i];
                    if (ch === '"') inQ = !inQ;
                    else if (!inQ) {
                        if (ch === ')') depthP++;
                        else if (ch === '(') depthP = Math.max(0, depthP - 1);
                        else if (depthP === 0 && ch === '^' && i > 0) {
                            const ln = toFloat(evalExpr(t.slice(0, i)), null);
                            const rn = toFloat(evalExpr(t.slice(i + 1)), null);
                            if (ln === null || rn === null) return '#VALUE!';
                            return ssFormatFormulaNumber(Math.pow(ln, rn));
                        }
                    }
                }

                // Unary - or +
                if (t.startsWith('-')) {
                    const uv = toFloat(evalExpr(t.slice(1)), null);
                    return uv !== null ? ssFormatFormulaNumber(-uv) : '#VALUE!';
                }
                if (t.startsWith('+')) {
                    const uv = toFloat(evalExpr(t.slice(1)), null);
                    return uv !== null ? ssFormatFormulaNumber(uv) : '#VALUE!';
                }

                // Percentage literal
                if (/^-?\d+(\.\d+)?%$/.test(t)) {
                    return ssFormatFormulaNumber(Number(t.slice(0, -1)) / 100);
                }

                // Function call: FUNC(args)
                const fnCall = /^([A-Za-z_][A-Za-z0-9_.]*)\s*\(([\s\S]*)\)$/.exec(t);
                if (fnCall) {
                    const fnName = fnCall[1];
                    const argsBody = fnCall[2].trim();
                    const parsedArgs = argsBody ? ssSplitFormulaArgs(argsBody) : [];
                    return evalFunction(fnName, parsedArgs);
                }

                // Single Cell Reference
                if (/^\$?[A-Za-z]+\$?\d+$/.test(t)) {
                    return getCellEval(t);
                }

                if (t.toUpperCase() === 'TRUE' || t.toUpperCase() === 'FALSE') {
                    return t.toUpperCase();
                }
                const numVal = Number(t);
                if (Number.isFinite(numVal) && t !== '') {
                    return ssFormatFormulaNumber(numVal);
                }
                return t;
            };

            try {
                const res = evalExpr(expr);
                return String(res ?? '');
            } catch (_) {
                return '#ERROR!';
            }
        }

        function updateSpreadsheetBadgesAndSelector() {
            const validWorkbooks = (Array.isArray(savedSpreadsheetsList) ? savedSpreadsheetsList : []).filter(wb => {
                if (!wb || !wb.workbook_id) return false;
                const t = String(wb.title || '').toLowerCase();
                return t.endsWith('.xlsx') || t.endsWith('.xls') || Boolean(wb.file_id) || Boolean(wb.gdrive_file_id);
            });
            const count = validWorkbooks.length;
            const badge = document.getElementById('spreadsheet-total-badge');
            if (badge) badge.textContent = String(count);

            const sel = document.getElementById('ss-saved-workbooks-select');
            if (sel) {
                const activeWbId = String(currentSpreadsheetWorkbook.workbook_id || '');
                const placeholderSelected = !activeWbId ? 'selected' : '';
                let optionsHTML = `<option value="" ${placeholderSelected}>-- Select Spreadsheet (.xlsx / .xls) --</option>`;
                optionsHTML += validWorkbooks.map(wb => {
                    const wbId = String(wb.workbook_id || '');
                    const selected = activeWbId && wbId === activeWbId ? 'selected' : '';
                    const fidLabel = wb.file_id ? ` [${wb.file_id}]` : '';
                    return `<option value="${escapeHTML(wbId)}" ${selected}>${escapeHTML((wb.title || 'Spreadsheet.xlsx') + fidLabel)}</option>`;
                }).join('');
                sel.innerHTML = optionsHTML;
            }

            if (currentSpreadsheetWorkbook && currentSpreadsheetWorkbook.workbook_id) {
                const fidTxt = currentSpreadsheetWorkbook.file_id ? `File ID: ${currentSpreadsheetWorkbook.file_id} • ` : '';
                ssUpdateSyncBadgeStatus(`${fidTxt}Live 2-Way Sync Active (2.5s)`, 'synced');
            } else {
                ssUpdateSyncBadgeStatus('Blank Worksheet • Select a file or click Save to Google Drive', 'neutral');
            }
        }

        async function fetchSavedSpreadsheets(force = false) {
            try {
                const res = await fetch(`/api/spreadsheets?force=${force ? 'true' : 'false'}&sync_gdrive=true&_ts=${Date.now()}`, {
                    cache: 'no-store'
                });
                const data = await res.json();
                if (data.status === 'success' && Array.isArray(data.workbooks)) {
                    savedSpreadsheetsList = data.workbooks.map(w => ssSanitizeWorkbookCells(w));
                    spreadsheetInitialized = true;
                    // IMPORTANT: Keep worksheet blank by default unless the user has already selected a workbook!
                    if (currentSpreadsheetWorkbook && currentSpreadsheetWorkbook.workbook_id) {
                        const updatedMatch = savedSpreadsheetsList.find(
                            w => String(w.workbook_id) === String(currentSpreadsheetWorkbook.workbook_id)
                        );
                        if (updatedMatch) {
                            applyLiveSyncedWorkbookUpdate(updatedMatch, false);
                        }
                    }
                    updateSpreadsheetBadgesAndSelector();
                }
            } catch (e) {
                console.warn('Could not fetch saved spreadsheets:', e);
            }
        }

        function loadWorkbookObjectIntoEditor(wb) {
            if (!wb) return;
            currentSpreadsheetWorkbook = ssSanitizeWorkbookCells(JSON.parse(JSON.stringify(wb)));
            (currentSpreadsheetWorkbook.sheets || []).forEach(sh => ssRestoreSheetLayoutFromLocalCache(sh));
            lastSyncedSpreadsheetSignature = ssComputeWorkbookSignature(currentSpreadsheetWorkbook);
            activeSheetIndex = 0;
            activeCellCoord = 'A1';
            ssSelectedCells = new Set(['A1']);
            ssSelectedCols.clear();
            ssSelectedRows.clear();
            ssEditingCellCoord = null;
            const titleInput = document.getElementById('ss-workbook-title');
            if (titleInput) titleInput.value = currentSpreadsheetWorkbook.title || 'Untitled_Spreadsheet.xlsx';
            renderSpreadsheetGrid();
            renderSpreadsheetSheetTabs();
            syncFormulaBarWithActiveCell();
            updateSpreadsheetBadgesAndSelector();
        }

        function applyLiveSyncedWorkbookUpdate(remoteWb, showNotification = false) {
            if (!remoteWb || !remoteWb.workbook_id) return;
            ssSanitizeWorkbookCells(remoteWb);
            const newSig = ssComputeWorkbookSignature(remoteWb);
            if (!newSig || newSig === lastSyncedSpreadsheetSignature) return;

            const prevSheet = ssGetActiveSheet();
            const prevRowCount = prevSheet.row_count || 25;
            const prevColCount = prevSheet.col_count || 10;
            const oldSheetsByName = {};
            (currentSpreadsheetWorkbook.sheets || []).forEach(sh => {
                if (sh && sh.name) oldSheetsByName[sh.name] = sh;
            });

            lastSyncedSpreadsheetSignature = newSig;
            currentSpreadsheetWorkbook.file_id = remoteWb.file_id || currentSpreadsheetWorkbook.file_id || '';
            currentSpreadsheetWorkbook.gdrive_file_id = remoteWb.gdrive_file_id || currentSpreadsheetWorkbook.gdrive_file_id || '';
            currentSpreadsheetWorkbook.gdrive_modified_time = remoteWb.gdrive_modified_time || '';
            currentSpreadsheetWorkbook.title = remoteWb.title || currentSpreadsheetWorkbook.title;
            currentSpreadsheetWorkbook.sheets = JSON.parse(JSON.stringify(remoteWb.sheets || []));
            (currentSpreadsheetWorkbook.sheets || []).forEach(sh => {
                const prevSh = oldSheetsByName[sh.name];
                if (prevSh) {
                    sh.wrap_cells = { ...(prevSh.wrap_cells || {}), ...(sh.wrap_cells || {}) };
                    sh.col_widths = { ...(prevSh.col_widths || {}), ...(sh.col_widths || {}) };
                    sh.row_heights = { ...(prevSh.row_heights || {}), ...(sh.row_heights || {}) };
                }
                ssRestoreSheetLayoutFromLocalCache(sh);
            });

            if (activeSheetIndex >= currentSpreadsheetWorkbook.sheets.length) {
                activeSheetIndex = 0;
            }

            const activeEditingCoord = ssEditingCellCoord;
            const sheet = ssGetActiveSheet();
            const cells = sheet.cells || {};
            const colCount = sheet.col_count || 10;
            const rowCount = sheet.row_count || 25;

            const table = document.getElementById('ss-grid-table');
            const domRowsCount = table ? table.querySelectorAll('tbody tr').length : 0;

            if (table && table.querySelector('tbody') && domRowsCount === rowCount && colCount === prevColCount) {
                for (let r = 1; r <= rowCount; r++) {
                    for (let c = 0; c < colCount; c++) {
                        const coord = `${ssColIdxToLetter(c)}${r}`;
                        if (coord === activeEditingCoord) continue;
                        const inputEl = document.getElementById(`ss-cell-${coord}`);
                        if (inputEl) {
                            const rawVal = cells[coord] ?? '';
                            const dispVal = ssEvaluateCellDisplay(rawVal, cells);
                            if (inputEl.value !== dispVal) {
                                inputEl.value = dispVal;
                                ssSyncWrapMirror(inputEl);
                            }
                        }
                    }
                }
            } else {
                renderSpreadsheetGrid();
            }
            renderSpreadsheetSheetTabs();
            if (!activeEditingCoord) {
                syncFormulaBarWithActiveCell();
            }
            updateSpreadsheetBadgesAndSelector();
            if (showNotification) {
                showToast(`🔄 Auto-synced latest changes from Google Sheets / Drive for "${currentSpreadsheetWorkbook.title}"!`);
            }
        }

        async function syncActiveSpreadsheetFromGoogleDriveNow(manualNotify = false) {
            if (!currentSpreadsheetWorkbook || !currentSpreadsheetWorkbook.workbook_id) {
                if (manualNotify) {
                    await fetchSavedSpreadsheets(true);
                    showToast('🔄 Refreshed spreadsheet files list from Google Drive!');
                }
                return;
            }
            if (ssIsSavingInFlight || ssAutoSyncPushTimer || ssHasPendingSaveWhileInFlight || ssIsPullSyncInFlight) return;

            const editVerBeforePull = ssLocalEditVersion;
            ssIsPullSyncInFlight = true;
            const syncIcon = document.getElementById('icon-ss-sync-now');
            if (syncIcon) syncIcon.classList.add('fa-spin');
            if (manualNotify) {
                ssUpdateSyncBadgeStatus('Syncing live cells from Google Sheets / Drive...', 'syncing');
            }
            try {
                const wbId = currentSpreadsheetWorkbook.workbook_id;
                const res = await fetch(`/api/spreadsheets/${encodeURIComponent(wbId)}/sync?force=true&_ts=${Date.now()}`, {
                    cache: 'no-store'
                });
                if (res.ok) {
                    const data = await res.json();
                    // Never overwrite if the user edited locally while this pull request was in flight!
                    if (ssLocalEditVersion !== editVerBeforePull || ssIsSavingInFlight || ssAutoSyncPushTimer || ssHasPendingSaveWhileInFlight) {
                        return;
                    }
                    if (data.status === 'success' && data.workbook) {
                        if (Array.isArray(data.workbooks)) {
                            savedSpreadsheetsList = data.workbooks.map(w => ssSanitizeWorkbookCells(w));
                        }
                        const sigBefore = lastSyncedSpreadsheetSignature;
                        applyLiveSyncedWorkbookUpdate(data.workbook, Boolean(data.changed) || manualNotify);
                        if (manualNotify && sigBefore === lastSyncedSpreadsheetSignature) {
                            updateSpreadsheetBadgesAndSelector();
                            showToast(`✅ "${currentSpreadsheetWorkbook.title}" is already up to date with Google Sheets!`);
                        }
                    }
                }
            } catch (_) {
            } finally {
                ssIsPullSyncInFlight = false;
                if (syncIcon) syncIcon.classList.remove('fa-spin');
            }
        }

        function startSpreadsheetLiveAutoSyncPoller() {
            if (!ssFocusListenersAttached) {
                ssFocusListenersAttached = true;
                window.addEventListener('focus', () => {
                    if (currentSpreadsheetWorkbook && currentSpreadsheetWorkbook.workbook_id) {
                        syncActiveSpreadsheetFromGoogleDriveNow(false);
                    }
                });
                document.addEventListener('visibilitychange', () => {
                    if (document.visibilityState === 'visible' && currentSpreadsheetWorkbook && currentSpreadsheetWorkbook.workbook_id) {
                        syncActiveSpreadsheetFromGoogleDriveNow(false);
                    }
                });
            }
            if (ssAutoSyncPullInterval) return;
            ssAutoSyncPullInterval = setInterval(() => {
                if (!currentSpreadsheetWorkbook || !currentSpreadsheetWorkbook.workbook_id) return;
                syncActiveSpreadsheetFromGoogleDriveNow(false);
            }, 2000);
        }

        function scheduleSpreadsheetAutoSyncToGoogleDrive(immediate = false) {
            ssLocalEditVersion++;
            const sheet = ssGetActiveSheet();
            ssSaveSheetLayoutToLocalCache(sheet);
            if (!currentSpreadsheetWorkbook || !currentSpreadsheetWorkbook.workbook_id || !currentSpreadsheetWorkbook.gdrive_file_id) {
                return;
            }
            ssUpdateSyncBadgeStatus('Syncing changes to Google Sheets / Drive...', 'syncing');
            if (ssAutoSyncPushTimer) clearTimeout(ssAutoSyncPushTimer);
            const delayMs = immediate ? 25 : 300;
            ssAutoSyncPushTimer = setTimeout(async () => {
                ssAutoSyncPushTimer = null;
                await saveCurrentSpreadsheetToCloudinary(true);
            }, delayMs);
        }

        function initSpreadsheetView() {
            startSpreadsheetLiveAutoSyncPoller();
            if (!spreadsheetInitialized) {
                currentSpreadsheetWorkbook = createBlankSpreadsheetWorkbookState();
                renderSpreadsheetGrid();
                renderSpreadsheetSheetTabs();
                syncFormulaBarWithActiveCell();
                fetchSavedSpreadsheets(true);
            } else {
                renderSpreadsheetGrid();
                renderSpreadsheetSheetTabs();
                syncFormulaBarWithActiveCell();
                if (currentSpreadsheetWorkbook && currentSpreadsheetWorkbook.workbook_id) {
                    syncActiveSpreadsheetFromGoogleDriveNow(false);
                } else {
                    fetchSavedSpreadsheets(true);
                }
            }
        }

        function ssGetColumnWidthPx(sheet, colIdx) {
            const colLetter = ssColIdxToLetter(colIdx);
            const customW = Number(sheet?.col_widths?.[colLetter] || 0);
            if (customW >= 50) return Math.round(customW);
            return 145;
        }

        function ssGetRowHeightPx(sheet, rowNum) {
            const customH = Number(sheet?.row_heights?.[rowNum] || 0);
            if (customH >= 22) return Math.round(customH);
            return 0; // 0 means automatic standard row height (28px min, or auto-expanding if a cell in the row has wrap_cells enabled)
        }

        function renderSpreadsheetGrid() {
            const table = document.getElementById('ss-grid-table');
            if (!table) return;
            const sheet = ssGetActiveSheet();
            ssRestoreSheetLayoutFromLocalCache(sheet);
            const colCount = sheet.col_count || 10;
            const rowCount = sheet.row_count || 25;
            const cells = sheet.cells || {};
            const wrapMap = sheet.wrap_cells || {};

            if (!ssSelectedCells || ssSelectedCells.size === 0) {
                ssSelectedCells = new Set([activeCellCoord || 'A1']);
            }

            // Build <colgroup> for exact, draggable column widths
            let colGroupHTML = `<col id="ss-col-def-rowhdr" style="width:46px; min-width:46px; max-width:46px;">`;
            const colWidthsPx = [];
            for (let c = 0; c < colCount; c++) {
                const colLetter = ssColIdxToLetter(c);
                const wPx = ssGetColumnWidthPx(sheet, c);
                colWidthsPx.push(wPx);
                colGroupHTML += `<col id="ss-col-def-${colLetter}" style="width:${wPx}px; min-width:${wPx}px;">`;
            }

            // Header Row: Top-left Select-All (#) + Column Letters (A, B, C, D...) with Drag Resizers
            let theadCols = `
                <th
                    onclick="onSpreadsheetSelectAllClick(event)"
                    title="Click to select all cells in this sheet"
                    class="sticky top-0 left-0 z-30 bg-slate-900 hover:bg-slate-800 border border-slate-700 w-[46px] min-w-[46px] max-w-[46px] py-1.5 text-center text-[11px] font-extrabold text-slate-400 hover:text-gb-cyan cursor-pointer select-none"
                >#</th>
            `;
            for (let c = 0; c < colCount; c++) {
                const colLetter = ssColIdxToLetter(c);
                const wPx = colWidthsPx[c];
                theadCols += `
                    <th
                        id="ss-col-hdr-${colLetter}"
                        data-col="${colLetter}"
                        onmousedown="onSpreadsheetColHeaderMouseDown(event, '${colLetter}')"
                        onmouseenter="onSpreadsheetColHeaderMouseEnter(event, '${colLetter}')"
                        style="width:${wPx}px; min-width:${wPx}px; max-width:${wPx}px;"
                        title="Click or Drag to select Column ${colLetter} (Ctrl+Click for multiple columns) • Drag right border to resize column width"
                        class="sticky top-0 z-20 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 px-2 py-1.5 text-center font-mono font-extrabold text-xs cursor-pointer select-none relative"
                    >
                        <span>${colLetter}</span>
                        <div
                            class="ss-col-resizer"
                            onmousedown="ssStartColResize(event, '${colLetter}')"
                            ondblclick="ssAutoFitColumn('${colLetter}'); event.stopPropagation();"
                            onclick="event.stopPropagation()"
                            title="Drag to resize Column ${colLetter} • Double-click to auto-fit"
                        ></div>
                    </th>
                `;
            }

            let tbodyRows = '';
            for (let r = 1; r <= rowCount; r++) {
                const customRowH = ssGetRowHeightPx(sheet, r);
                const trStyle = customRowH > 0 ? `height:${customRowH}px;` : '';
                const rowHdrStyle = customRowH > 0 ? `height:${customRowH}px;` : 'height:28px;';
                let rowCells = `
                    <td
                        id="ss-row-hdr-${r}"
                        data-row="${r}"
                        onmousedown="onSpreadsheetRowHeaderMouseDown(event, ${r})"
                        onmouseenter="onSpreadsheetRowHeaderMouseEnter(event, ${r})"
                        style="${rowHdrStyle}"
                        title="Click or Drag to select Row ${r} (Ctrl+Click for multiple rows) • Drag bottom border to resize row height"
                        class="sticky left-0 z-10 bg-slate-900 hover:bg-slate-800 text-slate-400 border border-slate-700 px-1.5 py-1 text-center font-mono font-bold text-[11px] cursor-pointer select-none align-middle relative"
                    >
                        <span>${r}</span>
                        <div
                            class="ss-row-resizer"
                            onmousedown="ssStartRowResize(event, ${r})"
                            onclick="event.stopPropagation()"
                            title="Drag to resize Row ${r}"
                        ></div>
                    </td>
                `;

                for (let c = 0; c < colCount; c++) {
                    const colLetter = ssColIdxToLetter(c);
                    const coord = `${colLetter}${r}`;
                    const rawVal = cells[coord] ?? '';
                    const isEditingThis = ssEditingCellCoord === coord;
                    const displayVal = isEditingThis ? ssNormalizeCellValue(rawVal) : ssEvaluateCellDisplay(rawVal, cells);
                    const isWrapped = Boolean(wrapMap[coord]);
                    const wPx = colWidthsPx[c];
                    const tdHeightStyle = customRowH > 0 ? `height:${customRowH}px;` : '';
                    const inputStateCls = isEditingThis ? 'ss-cell-input-editing' : 'ss-cell-input-locked';
                    const readOnlyAttr = isEditingThis ? '' : 'readonly';

                    if (isWrapped) {
                        rowCells += `
                            <td
                                id="ss-td-${coord}"
                                data-coord="${coord}"
                                data-col="${colLetter}"
                                data-row="${r}"
                                onmousedown="onSpreadsheetCellMouseDown(event, '${coord}')"
                                onmouseenter="onSpreadsheetCellMouseEnter(event, '${coord}')"
                                ondblclick="onSpreadsheetCellDblClick(event, '${coord}')"
                                style="width:${wPx}px; min-width:${wPx}px; max-width:${wPx}px; ${tdHeightStyle}"
                                class="ss-data-cell border border-slate-800 p-0 align-top hover:bg-slate-900/60"
                            >
                                <div class="ss-wrap-cell-grid" style="${customRowH > 0 ? `min-height:${customRowH}px;` : ''}">
                                    <div class="ss-wrap-cell-mirror" aria-hidden="true">${escapeHTML(displayVal)} </div>
                                    <textarea
                                        rows="1"
                                        id="ss-cell-${coord}"
                                        data-coord="${coord}"
                                        ${readOnlyAttr}
                                        oninput="onSpreadsheetCellInput('${coord}', this.value); ssSyncWrapMirror(this)"
                                        onblur="onSpreadsheetCellBlur('${coord}', this)"
                                        onkeydown="onSpreadsheetCellKeyDown(event, ${c}, ${r})"
                                        class="ss-wrap-cell-textarea text-white ${inputStateCls}"
                                    >${escapeHTML(displayVal)}</textarea>
                                </div>
                            </td>
                        `;
                    } else {
                        rowCells += `
                            <td
                                id="ss-td-${coord}"
                                data-coord="${coord}"
                                data-col="${colLetter}"
                                data-row="${r}"
                                onmousedown="onSpreadsheetCellMouseDown(event, '${coord}')"
                                onmouseenter="onSpreadsheetCellMouseEnter(event, '${coord}')"
                                ondblclick="onSpreadsheetCellDblClick(event, '${coord}')"
                                style="width:${wPx}px; min-width:${wPx}px; max-width:${wPx}px; ${tdHeightStyle}"
                                class="ss-data-cell border border-slate-800 p-0 align-middle overflow-hidden hover:bg-slate-900/60"
                            >
                                <input
                                    type="text"
                                    id="ss-cell-${coord}"
                                    data-coord="${coord}"
                                    value="${escapeHTML(displayVal)}"
                                    ${readOnlyAttr}
                                    oninput="onSpreadsheetCellInput('${coord}', this.value)"
                                    onblur="onSpreadsheetCellBlur('${coord}', this)"
                                    onkeydown="onSpreadsheetCellKeyDown(event, ${c}, ${r})"
                                    style="${customRowH > 0 ? `height:${customRowH}px;` : ''}"
                                    class="ss-unwrap-cell-input text-white ${inputStateCls}"
                                >
                            </td>
                        `;
                    }
                }
                tbodyRows += `<tr id="ss-row-tr-${r}" style="${trStyle}">${rowCells}</tr>`;
            }

            table.innerHTML = `<colgroup>${colGroupHTML}</colgroup><thead><tr>${theadCols}</tr></thead><tbody>${tbodyRows}</tbody>`;
            ssRefreshSelectionHighlights();
            updateSpreadsheetWrapTextButtonUI();
        }

        function ssRefreshSelectionHighlights() {
            const sheet = ssGetActiveSheet();
            const activeParsed = ssParseCoord(activeCellCoord || 'A1') || { colLetter: 'A', rowNum: 1 };

            // 1. Update cell selection & active classes
            document.querySelectorAll('#ss-grid-table td.ss-data-cell').forEach(td => {
                const coord = td.getAttribute('data-coord') || '';
                const isSel = ssSelectedCells.has(coord);
                const isAct = coord === activeCellCoord;
                const isEdit = coord === ssEditingCellCoord;
                td.classList.toggle('ss-cell-selected', isSel && !isAct && !isEdit);
                td.classList.toggle('ss-cell-active', isAct && !isEdit);
                td.classList.toggle('ss-cell-editing-td', isEdit);
            });

            // 2. Highlight Column Headers (active column or full-selected columns)
            const activeColsSet = new Set([activeParsed.colLetter]);
            ssSelectedCells.forEach(coord => {
                const colL = String(coord).replace(/\d+/g, '');
                if (colL) activeColsSet.add(colL);
            });
            document.querySelectorAll('#ss-grid-table thead th[data-col]').forEach(th => {
                const colL = th.getAttribute('data-col') || '';
                const isFullColSel = ssSelectedCols.has(colL);
                const isHighlighted = isFullColSel || activeColsSet.has(colL);
                if (isFullColSel) {
                    th.className = 'sticky top-0 z-20 bg-gb-cyan text-slate-950 border border-gb-cyan px-2 py-1.5 text-center font-mono font-extrabold text-xs cursor-pointer select-none relative shadow-[0_0_10px_rgba(0,240,255,0.3)]';
                } else if (isHighlighted) {
                    th.className = 'sticky top-0 z-20 bg-gb-cyan/20 text-gb-cyan border border-gb-cyan/60 px-2 py-1.5 text-center font-mono font-extrabold text-xs cursor-pointer select-none relative';
                } else {
                    th.className = 'sticky top-0 z-20 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 px-2 py-1.5 text-center font-mono font-extrabold text-xs cursor-pointer select-none relative';
                }
            });

            // 3. Highlight Row Headers (active row or full-selected rows)
            const activeRowsSet = new Set([activeParsed.rowNum]);
            ssSelectedCells.forEach(coord => {
                const rN = parseInt(String(coord).replace(/[A-Za-z]+/g, ''), 10);
                if (Number.isFinite(rN)) activeRowsSet.add(rN);
            });
            document.querySelectorAll('#ss-grid-table tbody td[data-row]:not(.ss-data-cell)').forEach(td => {
                const rN = parseInt(td.getAttribute('data-row') || '0', 10);
                const isFullRowSel = ssSelectedRows.has(rN);
                const isHighlighted = isFullRowSel || activeRowsSet.has(rN);
                if (isFullRowSel) {
                    td.className = 'sticky left-0 z-10 bg-gb-cyan text-slate-950 border border-gb-cyan px-1.5 py-1 text-center font-mono font-extrabold text-[11px] cursor-pointer select-none align-middle relative shadow-[0_0_10px_rgba(0,240,255,0.3)]';
                } else if (isHighlighted) {
                    td.className = 'sticky left-0 z-10 bg-gb-cyan/20 text-gb-cyan border border-gb-cyan/60 px-1.5 py-1 text-center font-mono font-bold text-[11px] cursor-pointer select-none align-middle relative';
                } else {
                    td.className = 'sticky left-0 z-10 bg-slate-900 hover:bg-slate-800 text-slate-400 border border-slate-700 px-1.5 py-1 text-center font-mono font-bold text-[11px] cursor-pointer select-none align-middle relative';
                }
            });

            // 4. Update Coordinate Badge & Status Pill
            const badge = document.getElementById('ss-active-cell-badge');
            const statusPill = document.getElementById('ss-selection-status-pill');
            const selCount = ssSelectedCells.size;
            if (badge) {
                if (ssSelectedCols.size > 0 && ssSelectedRows.size === 0) {
                    badge.textContent = `Col ${Array.from(ssSelectedCols).join(',')}`;
                } else if (ssSelectedRows.size > 0 && ssSelectedCols.size === 0) {
                    badge.textContent = `Row ${Array.from(ssSelectedRows).join(',')}`;
                } else if (selCount > 1) {
                    badge.textContent = `${activeCellCoord} (${selCount})`;
                } else {
                    badge.textContent = activeCellCoord;
                }
            }
            if (statusPill) {
                const isWrapped = Boolean(sheet.wrap_cells?.[activeCellCoord]);
                const wrapTag = isWrapped ? ' • Wrap: ON' : '';
                if (ssEditingCellCoord) {
                    statusPill.textContent = `Editing ${ssEditingCellCoord}${wrapTag}`;
                } else if (ssSelectedCols.size > 0) {
                    statusPill.textContent = `Column ${Array.from(ssSelectedCols).join(', ')} selected (${selCount} cells)${wrapTag}`;
                } else if (ssSelectedRows.size > 0) {
                    statusPill.textContent = `Row ${Array.from(ssSelectedRows).join(', ')} selected (${selCount} cells)${wrapTag}`;
                } else if (selCount > 1) {
                    statusPill.textContent = `${selCount} cells selected (Active: ${activeCellCoord})${wrapTag}`;
                } else {
                    statusPill.textContent = `1 cell selected (${activeCellCoord})${wrapTag}`;
                }
            }
        }

        function syncFormulaBarWithActiveCell() {
            const fInput = document.getElementById('ss-formula-bar-input');
            const sheet = ssGetActiveSheet();
            if (fInput && document.activeElement !== fInput) {
                fInput.value = ssNormalizeCellValue(sheet.cells[activeCellCoord] ?? '');
            }
            const renameInput = document.getElementById('ss-rename-sheet-input');
            if (renameInput && document.activeElement !== renameInput) {
                renameInput.value = sheet.name || 'Sheet1';
            }
            ssRefreshSelectionHighlights();
            updateSpreadsheetWrapTextButtonUI();
        }

        function ssExitCellEditMode() {
            if (typeof window.ssResetFormulaPointToken === 'function') {
                window.ssResetFormulaPointToken();
            }
            if (typeof window.ssHighlightFormulaReferencedCells === 'function') {
                window.ssHighlightFormulaReferencedCells('');
            }
            if (!ssEditingCellCoord) return;
            const prevCoord = ssEditingCellCoord;
            ssEditingCellCoord = null;
            const inputEl = document.getElementById(`ss-cell-${prevCoord}`);
            const sheet = ssGetActiveSheet();
            if (inputEl) {
                inputEl.readOnly = true;
                inputEl.classList.remove('ss-cell-input-editing');
                inputEl.classList.add('ss-cell-input-locked');
                const rawVal = sheet.cells[prevCoord] ?? '';
                inputEl.value = ssEvaluateCellDisplay(rawVal, sheet.cells);
                ssSyncWrapMirror(inputEl);
                inputEl.blur();
            }
            const tdEl = document.getElementById(`ss-td-${prevCoord}`);
            if (tdEl) {
                tdEl.classList.remove('ss-cell-editing-td');
            }
            ssRefreshSelectionHighlights();
        }

        function ssEnterCellEditMode(coord, initialChar = null) {
            if (!coord) return;
            if (ssEditingCellCoord && ssEditingCellCoord !== coord) {
                ssExitCellEditMode();
            }
            if (typeof window.ssResetFormulaPointToken === 'function') {
                window.ssResetFormulaPointToken();
            }
            activeCellCoord = coord;
            ssSelectedCells = new Set([coord]);
            ssSelectedCols.clear();
            ssSelectedRows.clear();
            ssEditingCellCoord = coord;

            const sheet = ssGetActiveSheet();
            const inputEl = document.getElementById(`ss-cell-${coord}`);
            if (!inputEl) return;

            inputEl.readOnly = false;
            inputEl.classList.remove('ss-cell-input-locked');
            inputEl.classList.add('ss-cell-input-editing');

            const rawVal = ssNormalizeCellValue(sheet.cells[coord] ?? '');
            if (initialChar !== null) {
                inputEl.value = initialChar;
                onSpreadsheetCellInput(coord, initialChar);
            } else {
                inputEl.value = rawVal;
            }
            if (typeof window.ssHighlightFormulaReferencedCells === 'function') {
                window.ssHighlightFormulaReferencedCells(inputEl.value);
            }
            ssSyncWrapMirror(inputEl);
            ssRefreshSelectionHighlights();
            updateSpreadsheetWrapTextButtonUI();

            setTimeout(() => {
                inputEl.focus();
                try {
                    const len = inputEl.value.length;
                    inputEl.setSelectionRange(len, len);
                } catch (_) {}
            }, 0);
        }

        function ssEnsureGlobalDragMouseUpListener() {
            if (ssDragMouseUpAttached) return;
            ssDragMouseUpAttached = true;
            window.addEventListener('mouseup', () => {
                if (ssIsMouseDraggingSelection) {
                    ssIsMouseDraggingSelection = false;
                    ssDragSelectMode = null;
                    ssDragStartCoord = null;
                    ssDragStartColIdx = null;
                    ssDragStartRowNum = null;
                    ssDragBaseSelectedCells = null;
                    ssDragBaseSelectedCols = null;
                    ssDragBaseSelectedRows = null;
                }
            });
        }

        function ssAddRectRangeToSet(targetSet, coordA, coordB) {
            const pA = ssParseCoord(coordA);
            const pB = ssParseCoord(coordB);
            if (!pA || !pB) return;
            const cMin = Math.min(pA.colIndex, pB.colIndex);
            const cMax = Math.max(pA.colIndex, pB.colIndex);
            const rMin = Math.min(pA.rowNum, pB.rowNum);
            const rMax = Math.max(pA.rowNum, pB.rowNum);
            for (let r = rMin; r <= rMax; r++) {
                for (let c = cMin; c <= cMax; c++) {
                    targetSet.add(`${ssColIdxToLetter(c)}${r}`);
                }
            }
        }

        function onSpreadsheetCellMouseDown(event, coord) {
            if (!coord) return;
            if (event && event.button !== undefined && event.button !== 0) return;
            // If user clicked inside the cell that is already in inline edit mode, allow normal text cursor positioning
            if (ssEditingCellCoord === coord) {
                return;
            }
            // Formula Point Mode: Click / Drag / Ctrl+Click / Shift+Click inserts cell/range reference into active formula!
            if (typeof window.ssShouldInterceptGridForFormulaPointing === 'function' && window.ssShouldInterceptGridForFormulaPointing()) {
                if (window.ssHandleFormulaPointCellMouseDown(event, coord)) {
                    return;
                }
            }
            if (event) event.preventDefault();
            if (ssEditingCellCoord) {
                ssExitCellEditMode();
            }
            ssEnsureGlobalDragMouseUpListener();

            const isMultiModifier = Boolean(event && (event.ctrlKey || event.metaKey));
            const isShiftModifier = Boolean(event && event.shiftKey);

            ssIsMouseDraggingSelection = true;
            ssDragSelectMode = 'cells';
            ssDragStartCoord = coord;

            if (isShiftModifier && ssSelectionAnchorCoord) {
                ssSelectedCols.clear();
                ssSelectedRows.clear();
                ssSelectedCells.clear();
                ssAddRectRangeToSet(ssSelectedCells, ssSelectionAnchorCoord, coord);
                activeCellCoord = ssSelectionAnchorCoord;
                ssDragStartCoord = ssSelectionAnchorCoord;
                ssDragBaseSelectedCells = new Set();
            } else if (isMultiModifier) {
                ssSelectedCols.clear();
                ssSelectedRows.clear();
                ssDragBaseSelectedCells = new Set(ssSelectedCells);
                if (ssSelectedCells.has(coord) && ssSelectedCells.size > 1) {
                    ssSelectedCells.delete(coord);
                    ssDragBaseSelectedCells.delete(coord);
                    const remaining = Array.from(ssSelectedCells);
                    activeCellCoord = remaining[remaining.length - 1] || 'A1';
                } else {
                    ssSelectedCells.add(coord);
                    activeCellCoord = coord;
                    ssSelectionAnchorCoord = coord;
                }
            } else {
                ssSelectedCols.clear();
                ssSelectedRows.clear();
                ssSelectedCells = new Set([coord]);
                ssDragBaseSelectedCells = new Set();
                activeCellCoord = coord;
                ssSelectionAnchorCoord = coord;
            }

            syncFormulaBarWithActiveCell();
            const wrapper = document.getElementById('ss-grid-scroll-wrapper');
            if (wrapper && document.activeElement !== wrapper) {
                wrapper.focus({ preventScroll: true });
            }
        }

        function onSpreadsheetCellMouseEnter(event, coord) {
            if (typeof window.ssHandleFormulaPointCellMouseEnter === 'function' && window.ssHandleFormulaPointCellMouseEnter(event, coord)) {
                return;
            }
            if (!ssIsMouseDraggingSelection || ssDragSelectMode !== 'cells' || !ssDragStartCoord || !coord) return;
            if (event && event.buttons !== undefined && (event.buttons & 1) === 0) {
                ssIsMouseDraggingSelection = false;
                ssDragSelectMode = null;
                return;
            }
            ssSelectedCols.clear();
            ssSelectedRows.clear();
            const nextSet = new Set(ssDragBaseSelectedCells || []);
            ssAddRectRangeToSet(nextSet, ssDragStartCoord, coord);
            ssSelectedCells = nextSet;
            activeCellCoord = ssDragStartCoord;
            ssRefreshSelectionHighlights();
            updateSpreadsheetWrapTextButtonUI();
        }

        function onSpreadsheetCellDblClick(event, coord) {
            if (event) {
                event.preventDefault();
                event.stopPropagation();
            }
            ssIsMouseDraggingSelection = false;
            ssDragSelectMode = null;
            ssEnterCellEditMode(coord);
        }

        function onSpreadsheetColHeaderMouseDown(event, colLetter) {
            if (!colLetter) return;
            if (event && event.target && event.target.classList && event.target.classList.contains('ss-col-resizer')) return;
            if (typeof window.ssShouldInterceptGridForFormulaPointing === 'function' && window.ssShouldInterceptGridForFormulaPointing()) {
                const sheetForRef = ssGetActiveSheet();
                const maxR = sheetForRef.row_count || 25;
                if (window.ssHandleFormulaPointCellMouseDown(event, `${colLetter}1`, `${colLetter}${maxR}`)) {
                    return;
                }
            }
            if (event) event.preventDefault();
            ssExitCellEditMode();
            ssEnsureGlobalDragMouseUpListener();

            const sheet = ssGetActiveSheet();
            const rowCount = sheet.row_count || 25;
            const colIdx = ssLetterToColIdx(colLetter);
            const isMulti = Boolean(event && (event.ctrlKey || event.metaKey));

            ssIsMouseDraggingSelection = true;
            ssDragSelectMode = 'cols';
            ssDragStartColIdx = colIdx;

            if (!isMulti) {
                ssSelectedCells.clear();
                ssSelectedCols.clear();
                ssSelectedRows.clear();
                ssDragBaseSelectedCells = new Set();
                ssDragBaseSelectedCols = new Set();
            } else {
                ssDragBaseSelectedCells = new Set(ssSelectedCells);
                ssDragBaseSelectedCols = new Set(ssSelectedCols);
            }

            if (isMulti && ssSelectedCols.has(colLetter) && ssSelectedCols.size > 1) {
                ssSelectedCols.delete(colLetter);
                ssDragBaseSelectedCols.delete(colLetter);
                for (let r = 1; r <= rowCount; r++) {
                    ssSelectedCells.delete(`${colLetter}${r}`);
                    ssDragBaseSelectedCells.delete(`${colLetter}${r}`);
                }
            } else {
                ssSelectedCols.add(colLetter);
                for (let r = 1; r <= rowCount; r++) {
                    ssSelectedCells.add(`${colLetter}${r}`);
                }
                activeCellCoord = `${colLetter}1`;
                ssSelectionAnchorCoord = activeCellCoord;
            }

            if (ssSelectedCells.size === 0) {
                ssSelectedCells.add('A1');
                activeCellCoord = 'A1';
            }
            syncFormulaBarWithActiveCell();
            const wrapper = document.getElementById('ss-grid-scroll-wrapper');
            if (wrapper) wrapper.focus({ preventScroll: true });
        }

        function onSpreadsheetColHeaderMouseEnter(event, colLetter) {
            if (!ssIsMouseDraggingSelection || ssDragSelectMode !== 'cols' || ssDragStartColIdx === null || !colLetter) return;
            if (event && event.buttons !== undefined && (event.buttons & 1) === 0) {
                ssIsMouseDraggingSelection = false;
                ssDragSelectMode = null;
                return;
            }
            const sheet = ssGetActiveSheet();
            const rowCount = sheet.row_count || 25;
            const curColIdx = ssLetterToColIdx(colLetter);
            const cMin = Math.min(ssDragStartColIdx, curColIdx);
            const cMax = Math.max(ssDragStartColIdx, curColIdx);

            ssSelectedRows.clear();
            ssSelectedCols = new Set(ssDragBaseSelectedCols || []);
            ssSelectedCells = new Set(ssDragBaseSelectedCells || []);
            for (let c = cMin; c <= cMax; c++) {
                const cL = ssColIdxToLetter(c);
                ssSelectedCols.add(cL);
                for (let r = 1; r <= rowCount; r++) {
                    ssSelectedCells.add(`${cL}${r}`);
                }
            }
            activeCellCoord = `${ssColIdxToLetter(ssDragStartColIdx)}1`;
            ssRefreshSelectionHighlights();
            updateSpreadsheetWrapTextButtonUI();
        }

        function onSpreadsheetColHeaderClick(event, colLetter) {
            onSpreadsheetColHeaderMouseDown(event, colLetter);
        }

        function onSpreadsheetRowHeaderMouseDown(event, rowNum) {
            const r = Number(rowNum || 0);
            if (r < 1) return;
            if (event && event.target && event.target.classList && event.target.classList.contains('ss-row-resizer')) return;
            if (typeof window.ssShouldInterceptGridForFormulaPointing === 'function' && window.ssShouldInterceptGridForFormulaPointing()) {
                const sheetForRef = ssGetActiveSheet();
                const maxColL = ssColIdxToLetter((sheetForRef.col_count || 10) - 1);
                if (window.ssHandleFormulaPointCellMouseDown(event, `A${r}`, `${maxColL}${r}`)) {
                    return;
                }
            }
            if (event) event.preventDefault();
            ssExitCellEditMode();
            ssEnsureGlobalDragMouseUpListener();

            const sheet = ssGetActiveSheet();
            const colCount = sheet.col_count || 10;
            const isMulti = Boolean(event && (event.ctrlKey || event.metaKey));

            ssIsMouseDraggingSelection = true;
            ssDragSelectMode = 'rows';
            ssDragStartRowNum = r;

            if (!isMulti) {
                ssSelectedCells.clear();
                ssSelectedCols.clear();
                ssSelectedRows.clear();
                ssDragBaseSelectedCells = new Set();
                ssDragBaseSelectedRows = new Set();
            } else {
                ssDragBaseSelectedCells = new Set(ssSelectedCells);
                ssDragBaseSelectedRows = new Set(ssSelectedRows);
            }

            if (isMulti && ssSelectedRows.has(r) && ssSelectedRows.size > 1) {
                ssSelectedRows.delete(r);
                ssDragBaseSelectedRows.delete(r);
                for (let c = 0; c < colCount; c++) {
                    ssSelectedCells.delete(`${ssColIdxToLetter(c)}${r}`);
                    ssDragBaseSelectedCells.delete(`${ssColIdxToLetter(c)}${r}`);
                }
            } else {
                ssSelectedRows.add(r);
                for (let c = 0; c < colCount; c++) {
                    ssSelectedCells.add(`${ssColIdxToLetter(c)}${r}`);
                }
                activeCellCoord = `A${r}`;
                ssSelectionAnchorCoord = activeCellCoord;
            }

            if (ssSelectedCells.size === 0) {
                ssSelectedCells.add('A1');
                activeCellCoord = 'A1';
            }
            syncFormulaBarWithActiveCell();
            const wrapper = document.getElementById('ss-grid-scroll-wrapper');
            if (wrapper) wrapper.focus({ preventScroll: true });
        }

        function onSpreadsheetRowHeaderMouseEnter(event, rowNum) {
            const curRow = Number(rowNum || 0);
            if (!ssIsMouseDraggingSelection || ssDragSelectMode !== 'rows' || ssDragStartRowNum === null || curRow < 1) return;
            if (event && event.buttons !== undefined && (event.buttons & 1) === 0) {
                ssIsMouseDraggingSelection = false;
                ssDragSelectMode = null;
                return;
            }
            const sheet = ssGetActiveSheet();
            const colCount = sheet.col_count || 10;
            const rMin = Math.min(ssDragStartRowNum, curRow);
            const rMax = Math.max(ssDragStartRowNum, curRow);

            ssSelectedCols.clear();
            ssSelectedRows = new Set(ssDragBaseSelectedRows || []);
            ssSelectedCells = new Set(ssDragBaseSelectedCells || []);
            for (let r = rMin; r <= rMax; r++) {
                ssSelectedRows.add(r);
                for (let c = 0; c < colCount; c++) {
                    ssSelectedCells.add(`${ssColIdxToLetter(c)}${r}`);
                }
            }
            activeCellCoord = `A${ssDragStartRowNum}`;
            ssRefreshSelectionHighlights();
            updateSpreadsheetWrapTextButtonUI();
        }

        function onSpreadsheetRowHeaderClick(event, rowNum) {
            onSpreadsheetRowHeaderMouseDown(event, rowNum);
        }

        function onSpreadsheetSelectAllClick(event) {
            if (event) event.preventDefault();
            ssExitCellEditMode();
            const sheet = ssGetActiveSheet();
            const colCount = sheet.col_count || 10;
            const rowCount = sheet.row_count || 25;
            ssSelectedCells.clear();
            ssSelectedCols.clear();
            ssSelectedRows.clear();
            for (let c = 0; c < colCount; c++) {
                const colL = ssColIdxToLetter(c);
                ssSelectedCols.add(colL);
                for (let r = 1; r <= rowCount; r++) {
                    ssSelectedCells.add(`${colL}${r}`);
                }
            }
            for (let r = 1; r <= rowCount; r++) {
                ssSelectedRows.add(r);
            }
            activeCellCoord = 'A1';
            syncFormulaBarWithActiveCell();
            showToast(`✅ Selected all ${ssSelectedCells.size} cells in "${sheet.name}"!`);
        }

        function ssStartColResize(event, colLetter) {
            if (!colLetter) return;
            event.preventDefault();
            event.stopPropagation();
            ssExitCellEditMode();

            const thEl = document.getElementById(`ss-col-hdr-${colLetter}`);
            const colDefEl = document.getElementById(`ss-col-def-${colLetter}`);
            const resizerEl = event.currentTarget;
            if (!thEl) return;

            const startX = event.clientX;
            const startWidth = thEl.getBoundingClientRect().width || 145;
            const sheet = ssGetActiveSheet();
            sheet.col_widths = sheet.col_widths || {};

            document.body.classList.add('ss-is-resizing-col');
            if (resizerEl) resizerEl.classList.add('ss-resizing-active');

            const onMouseMove = (moveEv) => {
                const deltaX = moveEv.clientX - startX;
                const newWidth = Math.max(55, Math.min(1400, Math.round(startWidth + deltaX)));
                sheet.col_widths[colLetter] = newWidth;
                if (colDefEl) {
                    colDefEl.style.width = `${newWidth}px`;
                    colDefEl.style.minWidth = `${newWidth}px`;
                }
                thEl.style.width = `${newWidth}px`;
                thEl.style.minWidth = `${newWidth}px`;
                thEl.style.maxWidth = `${newWidth}px`;
                document.querySelectorAll(`#ss-grid-table td.ss-data-cell[data-col="${colLetter}"]`).forEach(td => {
                    td.style.width = `${newWidth}px`;
                    td.style.minWidth = `${newWidth}px`;
                    td.style.maxWidth = `${newWidth}px`;
                });
            };

            const onMouseUp = () => {
                window.removeEventListener('mousemove', onMouseMove);
                window.removeEventListener('mouseup', onMouseUp);
                document.body.classList.remove('ss-is-resizing-col');
                if (resizerEl) resizerEl.classList.remove('ss-resizing-active');
                ssSaveSheetLayoutToLocalCache(sheet);
                scheduleSpreadsheetAutoSyncToGoogleDrive();
            };

            window.addEventListener('mousemove', onMouseMove);
            window.addEventListener('mouseup', onMouseUp);
        }

        function ssAutoFitColumn(colLetter) {
            if (!colLetter) return;
            const sheet = ssGetActiveSheet();
            const rowCount = sheet.row_count || 25;
            const cells = sheet.cells || {};
            let maxChars = 10;
            for (let r = 1; r <= rowCount; r++) {
                const val = ssEvaluateCellDisplay(cells[`${colLetter}${r}`] ?? '', cells);
                if (val.length > maxChars) maxChars = val.length;
            }
            const autoWidth = Math.max(90, Math.min(720, Math.round(maxChars * 7.2 + 28)));
            sheet.col_widths = sheet.col_widths || {};
            sheet.col_widths[colLetter] = autoWidth;
            ssSaveSheetLayoutToLocalCache(sheet);
            renderSpreadsheetGrid();
            scheduleSpreadsheetAutoSyncToGoogleDrive();
            showToast(`↔️ Auto-fitted Column ${colLetter} (${autoWidth}px)`);
        }

        function ssStartRowResize(event, rowNum) {
            const r = Number(rowNum || 0);
            if (r < 1) return;
            event.preventDefault();
            event.stopPropagation();
            ssExitCellEditMode();

            const rowHdrEl = document.getElementById(`ss-row-hdr-${r}`);
            const trEl = document.getElementById(`ss-row-tr-${r}`);
            const resizerEl = event.currentTarget;
            if (!rowHdrEl || !trEl) return;

            const startY = event.clientY;
            const startHeight = trEl.getBoundingClientRect().height || 28;
            const sheet = ssGetActiveSheet();
            sheet.row_heights = sheet.row_heights || {};

            document.body.classList.add('ss-is-resizing-row');
            if (resizerEl) resizerEl.classList.add('ss-resizing-active');

            const onMouseMove = (moveEv) => {
                const deltaY = moveEv.clientY - startY;
                const newHeight = Math.max(24, Math.min(900, Math.round(startHeight + deltaY)));
                sheet.row_heights[r] = newHeight;
                trEl.style.height = `${newHeight}px`;
                rowHdrEl.style.height = `${newHeight}px`;
                trEl.querySelectorAll('td.ss-data-cell').forEach(td => {
                    td.style.height = `${newHeight}px`;
                    const innerGrid = td.querySelector('.ss-wrap-cell-grid');
                    if (innerGrid) innerGrid.style.minHeight = `${newHeight}px`;
                    const innerInput = td.querySelector('input.ss-unwrap-cell-input');
                    if (innerInput) innerInput.style.height = `${newHeight}px`;
                });
            };

            const onMouseUp = () => {
                window.removeEventListener('mousemove', onMouseMove);
                window.removeEventListener('mouseup', onMouseUp);
                document.body.classList.remove('ss-is-resizing-row');
                if (resizerEl) resizerEl.classList.remove('ss-resizing-active');
                ssSaveSheetLayoutToLocalCache(sheet);
                scheduleSpreadsheetAutoSyncToGoogleDrive();
            };

            window.addEventListener('mousemove', onMouseMove);
            window.addEventListener('mouseup', onMouseUp);
        }

        function onSpreadsheetCellInput(coord, val) {
            if (typeof window.ssResetFormulaPointToken === 'function') {
                window.ssResetFormulaPointToken();
            }
            if (window.ssFormulaPointState) {
                if (String(val || '').trimStart().startsWith('=')) {
                    window.ssFormulaPointState.activeInputId = `ss-cell-${coord}`;
                    window.ssFormulaPointState.formulaCellCoord = coord;
                } else {
                    window.ssFormulaPointState.activeInputId = null;
                    window.ssFormulaPointState.formulaCellCoord = null;
                }
            }
            if (typeof window.ssHighlightFormulaReferencedCells === 'function') {
                window.ssHighlightFormulaReferencedCells(val);
            }
            const sheet = ssGetActiveSheet();
            if (String(val ?? '') === '') {
                delete sheet.cells[coord];
            } else {
                sheet.cells[coord] = String(val);
            }
            const fInput = document.getElementById('ss-formula-bar-input');
            if (fInput && activeCellCoord === coord && document.activeElement !== fInput) {
                fInput.value = String(val ?? '');
            }
            scheduleSpreadsheetAutoSyncToGoogleDrive();
        }

        function onSpreadsheetCellBlur(coord, inputEl) {
            if (window.ssFormulaPointState && window.ssFormulaPointState.isDraggingRef) {
                return;
            }
            const sheet = ssGetActiveSheet();
            const rawVal = sheet.cells[coord] ?? '';
            if (ssEditingCellCoord === coord) {
                ssEditingCellCoord = null;
            }
            if (typeof window.ssResetFormulaPointToken === 'function') {
                window.ssResetFormulaPointToken();
            }
            if (window.ssFormulaPointState) {
                window.ssFormulaPointState.activeInputId = null;
                window.ssFormulaPointState.formulaCellCoord = null;
            }
            if (typeof window.ssHighlightFormulaReferencedCells === 'function') {
                window.ssHighlightFormulaReferencedCells('');
            }
            if (inputEl) {
                inputEl.readOnly = true;
                inputEl.classList.remove('ss-cell-input-editing');
                inputEl.classList.add('ss-cell-input-locked');
                inputEl.value = ssEvaluateCellDisplay(rawVal, sheet.cells);
                ssSyncWrapMirror(inputEl);
            }
            const tdEl = document.getElementById(`ss-td-${coord}`);
            if (tdEl) {
                tdEl.classList.remove('ss-cell-editing-td');
            }
            if (ssIsBlockedImageFormula(rawVal)) {
                showToast('🚫 Image formulas (e.g. =IMAGE, =SPARKLINE) are not allowed in the Spread Sheet modal.');
            }
            // Refresh any formula cells that depend on this cell
            Object.keys(sheet.cells).forEach(k => {
                if (String(sheet.cells[k] || '').startsWith('=')) {
                    const depInput = document.getElementById(`ss-cell-${k}`);
                    if (depInput && document.activeElement !== depInput) {
                        depInput.value = ssEvaluateCellDisplay(sheet.cells[k], sheet.cells);
                        ssSyncWrapMirror(depInput);
                    }
                }
            });
            ssRefreshSelectionHighlights();
            if (ssAutoSyncPushTimer || ssHasPendingSaveWhileInFlight) {
                scheduleSpreadsheetAutoSyncToGoogleDrive(true);
            }
        }

        function onFormulaBarInput(val) {
            if (typeof window.ssResetFormulaPointToken === 'function') {
                window.ssResetFormulaPointToken();
            }
            if (window.ssFormulaPointState) {
                if (String(val || '').trimStart().startsWith('=')) {
                    window.ssFormulaPointState.activeInputId = 'ss-formula-bar-input';
                    window.ssFormulaPointState.formulaCellCoord = activeCellCoord || 'A1';
                } else {
                    window.ssFormulaPointState.activeInputId = null;
                    window.ssFormulaPointState.formulaCellCoord = null;
                }
            }
            if (typeof window.ssHighlightFormulaReferencedCells === 'function') {
                window.ssHighlightFormulaReferencedCells(val);
            }
            const sheet = ssGetActiveSheet();
            if (String(val ?? '') === '') {
                delete sheet.cells[activeCellCoord];
            } else {
                sheet.cells[activeCellCoord] = String(val);
            }
            if (ssIsBlockedImageFormula(val)) {
                showToast('🚫 Image formulas (e.g. =IMAGE, =SPARKLINE) are not allowed in the Spread Sheet modal.');
            }
            const cellInput = document.getElementById(`ss-cell-${activeCellCoord}`);
            if (cellInput) {
                cellInput.value = ssEvaluateCellDisplay(val, sheet.cells);
                ssSyncWrapMirror(cellInput);
            }
            // Refresh dependent formula cells live
            Object.keys(sheet.cells).forEach(k => {
                if (k !== activeCellCoord && String(sheet.cells[k] || '').startsWith('=')) {
                    const depInput = document.getElementById(`ss-cell-${k}`);
                    if (depInput && document.activeElement !== depInput) {
                        depInput.value = ssEvaluateCellDisplay(sheet.cells[k], sheet.cells);
                        ssSyncWrapMirror(depInput);
                    }
                }
            });
            scheduleSpreadsheetAutoSyncToGoogleDrive();
        }

        function onFormulaBarKeyDown(event) {
            if (event.key === 'F4') {
                event.preventDefault();
                event.stopPropagation();
                if (typeof window.ssToggleDollarSignOnActiveFormula === 'function') {
                    window.ssToggleDollarSignOnActiveFormula(event.currentTarget);
                }
                return;
            }
            if (!['Shift', 'Control', 'Alt', 'Meta'].includes(event.key) && typeof window.ssResetFormulaPointToken === 'function') {
                window.ssResetFormulaPointToken();
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                if (typeof window.ssHighlightFormulaReferencedCells === 'function') {
                    window.ssHighlightFormulaReferencedCells('');
                }
                event.currentTarget.blur();
                const wrapper = document.getElementById('ss-grid-scroll-wrapper');
                if (wrapper) wrapper.focus({ preventScroll: true });
                return;
            }
            if (event.key === 'Enter') {
                event.preventDefault();
                if (typeof window.ssHighlightFormulaReferencedCells === 'function') {
                    window.ssHighlightFormulaReferencedCells('');
                }
                const sheet = ssGetActiveSheet();
                const parsed = ssParseCoord(activeCellCoord) || { colIndex: 0, rowNum: 1 };
                const nextRow = Math.min(sheet.row_count || 25, parsed.rowNum + 1);
                activeCellCoord = `${ssColIdxToLetter(parsed.colIndex)}${nextRow}`;
                ssSelectedCells = new Set([activeCellCoord]);
                renderSpreadsheetGrid();
                syncFormulaBarWithActiveCell();
                scheduleSpreadsheetAutoSyncToGoogleDrive(true);
                const wrapper = document.getElementById('ss-grid-scroll-wrapper');
                if (wrapper) wrapper.focus({ preventScroll: true });
            }
        }

        function onSpreadsheetCellKeyDown(event, colIdx, rowNum) {
            const sheet = ssGetActiveSheet();
            if (event.key === 'F4') {
                event.preventDefault();
                event.stopPropagation();
                if (typeof window.ssToggleDollarSignOnActiveFormula === 'function') {
                    window.ssToggleDollarSignOnActiveFormula(event.currentTarget);
                }
                return;
            }
            if (!['Shift', 'Control', 'Alt', 'Meta'].includes(event.key) && typeof window.ssResetFormulaPointToken === 'function') {
                window.ssResetFormulaPointToken();
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                ssExitCellEditMode();
                const wrapper = document.getElementById('ss-grid-scroll-wrapper');
                if (wrapper) wrapper.focus({ preventScroll: true });
                return;
            }
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                ssExitCellEditMode();
                const nextRow = Math.min(sheet.row_count || 25, rowNum + 1);
                activeCellCoord = `${ssColIdxToLetter(colIdx)}${nextRow}`;
                ssSelectedCells = new Set([activeCellCoord]);
                syncFormulaBarWithActiveCell();
                const wrapper = document.getElementById('ss-grid-scroll-wrapper');
                if (wrapper) wrapper.focus({ preventScroll: true });
                return;
            }
            if (event.key === 'Tab') {
                event.preventDefault();
                ssExitCellEditMode();
                const delta = event.shiftKey ? -1 : 1;
                const nextCol = Math.max(0, Math.min((sheet.col_count || 10) - 1, colIdx + delta));
                activeCellCoord = `${ssColIdxToLetter(nextCol)}${rowNum}`;
                ssSelectedCells = new Set([activeCellCoord]);
                syncFormulaBarWithActiveCell();
                const wrapper = document.getElementById('ss-grid-scroll-wrapper');
                if (wrapper) wrapper.focus({ preventScroll: true });
            }
        }

        function onSpreadsheetGridKeyDown(event) {
            if (event.key === 'F4') {
                event.preventDefault();
                event.stopPropagation();
                if (typeof window.ssToggleDollarSignOnActiveFormula === 'function') {
                    window.ssToggleDollarSignOnActiveFormula();
                }
                return;
            }
            // Do not intercept if the user is typing inside an inline editing cell or input box
            const activeTag = (document.activeElement?.tagName || '').toUpperCase();
            if (ssEditingCellCoord || activeTag === 'INPUT' || activeTag === 'TEXTAREA' || activeTag === 'SELECT') {
                return;
            }
            const sheet = ssGetActiveSheet();
            const parsed = ssParseCoord(activeCellCoord || 'A1') || { colIndex: 0, rowNum: 1 };
            let targetCol = parsed.colIndex;
            let targetRow = parsed.rowNum;

            if (event.key === 'ArrowDown') {
                event.preventDefault();
                targetRow = Math.min(sheet.row_count || 25, parsed.rowNum + 1);
            } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                targetRow = Math.max(1, parsed.rowNum - 1);
            } else if (event.key === 'ArrowRight' || (event.key === 'Tab' && !event.shiftKey)) {
                event.preventDefault();
                targetCol = Math.min((sheet.col_count || 10) - 1, parsed.colIndex + 1);
            } else if (event.key === 'ArrowLeft' || (event.key === 'Tab' && event.shiftKey)) {
                event.preventDefault();
                targetCol = Math.max(0, parsed.colIndex - 1);
            } else if (event.key === 'Enter' || event.key === 'F2') {
                event.preventDefault();
                ssEnterCellEditMode(activeCellCoord);
                return;
            } else if (event.key === 'Delete' || event.key === 'Backspace') {
                event.preventDefault();
                const coords = ssGetEffectiveSelectedCoords();
                coords.forEach(c => {
                    delete sheet.cells[c];
                    const el = document.getElementById(`ss-cell-${c}`);
                    if (el) {
                        el.value = '';
                        ssSyncWrapMirror(el);
                    }
                });
                syncFormulaBarWithActiveCell();
                scheduleSpreadsheetAutoSyncToGoogleDrive(true);
                return;
            } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
                event.preventDefault();
                ssEnterCellEditMode(activeCellCoord, event.key);
                return;
            } else {
                return;
            }

            const nextCoord = `${ssColIdxToLetter(targetCol)}${targetRow}`;
            activeCellCoord = nextCoord;
            ssSelectedCols.clear();
            ssSelectedRows.clear();
            ssSelectedCells = new Set([nextCoord]);
            syncFormulaBarWithActiveCell();
            const tdEl = document.getElementById(`ss-td-${nextCoord}`);
            if (tdEl && typeof tdEl.scrollIntoView === 'function') {
                tdEl.scrollIntoView({ block: 'nearest', inline: 'nearest' });
            }
        }

        function renderSpreadsheetSheetTabs() {
            const container = document.getElementById('ss-sheet-tabs-container');
            if (!container) return;
            const sheets = currentSpreadsheetWorkbook.sheets || [];
            container.innerHTML = sheets.map((sh, idx) => {
                const isActive = idx === activeSheetIndex;
                return `
                    <button
                        type="button"
                        onclick="switchSpreadsheetSheetTab(${idx})"
                        ondblclick="focusRenameSheetInput()"
                        class="px-3 py-1 rounded-lg text-xs font-bold border transition-all flex items-center gap-1.5 ${isActive ? 'bg-emerald-500/20 border-emerald-400 text-emerald-300 shadow-[0_0_10px_rgba(16,185,129,0.2)]' : 'bg-slate-900 border-slate-700 text-slate-400 hover:text-white'}"
                        title="Click to switch sheet • Use Rename box on the right to rename '${escapeHTML(sh.name)}'"
                    >
                        <i class="fas fa-table text-[10px]"></i>
                        <span>${escapeHTML(sh.name || `Sheet${idx + 1}`)}</span>
                    </button>
                `;
            }).join('');

            const activeSheet = ssGetActiveSheet();
            const renameInput = document.getElementById('ss-rename-sheet-input');
            if (renameInput) renameInput.value = activeSheet.name || 'Sheet1';
        }

        function switchSpreadsheetSheetTab(idx) {
            if (idx < 0 || idx >= (currentSpreadsheetWorkbook.sheets || []).length) return;
            ssExitCellEditMode();
            activeSheetIndex = idx;
            activeCellCoord = 'A1';
            ssSelectedCells = new Set(['A1']);
            ssSelectedCols.clear();
            ssSelectedRows.clear();
            renderSpreadsheetGrid();
            renderSpreadsheetSheetTabs();
            syncFormulaBarWithActiveCell();
        }

        function focusRenameSheetInput() {
            const input = document.getElementById('ss-rename-sheet-input');
            if (input) {
                input.focus();
                input.select();
            }
        }

        function applyRenameActiveSheet() {
            const input = document.getElementById('ss-rename-sheet-input');
            if (!input) return;
            const raw = (input.value || '').replace(/[\\/?*:[\]]/g, '').trim().slice(0, 31);
            if (!raw) {
                showToast('⚠️ Please enter a valid Sheet Name!');
                return;
            }
            const sheet = ssGetActiveSheet();
            sheet.name = raw;
            ssSaveSheetLayoutToLocalCache(sheet);
            renderSpreadsheetSheetTabs();
            scheduleSpreadsheetAutoSyncToGoogleDrive();
            showToast(`✅ Sheet renamed to "${raw}"! Click "Save .xlsx to Google Drive" to persist.`);
        }

        function addNewSpreadsheetSheetTab() {
            ssExitCellEditMode();
            const sheets = currentSpreadsheetWorkbook.sheets || [];
            const nextNum = sheets.length + 1;
            let candidate = `Sheet${nextNum}`;
            const existingLower = new Set(sheets.map(s => String(s.name || '').toLowerCase()));
            let suffix = nextNum;
            while (existingLower.has(candidate.toLowerCase())) {
                suffix++;
                candidate = `Sheet${suffix}`;
            }
            sheets.push({
                id: `sheet_${Date.now()}`,
                name: candidate,
                row_count: 25,
                col_count: 10,
                cells: {},
                wrap_cells: {},
                col_widths: {},
                row_heights: {}
            });
            activeSheetIndex = sheets.length - 1;
            activeCellCoord = 'A1';
            ssSelectedCells = new Set(['A1']);
            ssSelectedCols.clear();
            ssSelectedRows.clear();
            renderSpreadsheetGrid();
            renderSpreadsheetSheetTabs();
            syncFormulaBarWithActiveCell();
            scheduleSpreadsheetAutoSyncToGoogleDrive();
            showToast(`➕ Added new sheet "${candidate}"!`);
        }

        function deleteActiveSpreadsheetSheetTab() {
            ssExitCellEditMode();
            const sheets = currentSpreadsheetWorkbook.sheets || [];
            if (sheets.length <= 1) {
                showToast('⚠️ A workbook must have at least 1 sheet.');
                return;
            }
            const removedName = sheets[activeSheetIndex]?.name || 'Sheet';
            sheets.splice(activeSheetIndex, 1);
            activeSheetIndex = Math.max(0, activeSheetIndex - 1);
            activeCellCoord = 'A1';
            ssSelectedCells = new Set(['A1']);
            ssSelectedCols.clear();
            ssSelectedRows.clear();
            renderSpreadsheetGrid();
            renderSpreadsheetSheetTabs();
            syncFormulaBarWithActiveCell();
            scheduleSpreadsheetAutoSyncToGoogleDrive();
            showToast(`🗑️ Removed sheet "${removedName}".`);
        }

        function addSpreadsheetColumn() {
            const sheet = ssGetActiveSheet();
            sheet.col_count = Math.min(52, (sheet.col_count || 10) + 1);
            renderSpreadsheetGrid();
            showToast(`➕ Added Column ${ssColIdxToLetter(sheet.col_count - 1)}!`);
        }

        function addSpreadsheetRows(count = 10) {
            const sheet = ssGetActiveSheet();
            sheet.row_count = Math.min(500, (sheet.row_count || 25) + Number(count || 10));
            renderSpreadsheetGrid();
            showToast(`➕ Expanded to ${sheet.row_count} rows!`);
        }

        function clearActiveSheetCells() {
            ssExitCellEditMode();
            const sheet = ssGetActiveSheet();
            sheet.cells = {};
            sheet.wrap_cells = {};
            ssSaveSheetLayoutToLocalCache(sheet);
            renderSpreadsheetGrid();
            syncFormulaBarWithActiveCell();
            scheduleSpreadsheetAutoSyncToGoogleDrive();
            showToast(`🧹 Cleared all cells in "${sheet.name}".`);
        }

        function createNewBlankSpreadsheetWorkbook(notify = true) {
            if (ssAutoSyncPushTimer) {
                clearTimeout(ssAutoSyncPushTimer);
                ssAutoSyncPushTimer = null;
            }
            const newWb = createBlankSpreadsheetWorkbookState();
            newWb.title = `GlennBot_Sheet_${(savedSpreadsheetsList.length || 0) + 1}.xlsx`;
            loadWorkbookObjectIntoEditor(newWb);
            const sel = document.getElementById('ss-saved-workbooks-select');
            if (sel) sel.value = '';
            if (notify) {
                showToast(`📄 Opened a fresh blank worksheet! Click "Save .xlsx to Google Drive" when ready.`);
            }
        }

        async function onSelectSavedSpreadsheetWorkbook(wbId) {
            const cleanId = String(wbId || '').trim();
            if (!cleanId) {
                createNewBlankSpreadsheetWorkbook(false);
                return;
            }
            startSpreadsheetLiveAutoSyncPoller();
            const found = (savedSpreadsheetsList || []).find(w => String(w.workbook_id) === cleanId);
            if (found) {
                loadWorkbookObjectIntoEditor(found);
            }
            // Pull latest live data from Google Sheets / Drive in case the client edited the spreadsheet
            ssUpdateSyncBadgeStatus('Syncing latest cells from Google Sheets / Drive...', 'syncing');
            try {
                const res = await fetch(`/api/spreadsheets/${encodeURIComponent(cleanId)}/sync?force=true&_ts=${Date.now()}`, {
                    cache: 'no-store'
                });
                const data = await res.json();
                if (data.status === 'success' && data.workbook) {
                    if (Array.isArray(data.workbooks)) {
                        savedSpreadsheetsList = data.workbooks.map(w => ssSanitizeWorkbookCells(w));
                    }
                    loadWorkbookObjectIntoEditor(data.workbook);
                    showToast(`📂 Loaded "${data.workbook.title}" (${data.workbook.file_id || 'Google Drive'})!`);
                    return;
                }
            } catch (_) {}
            if (found) {
                showToast(`📂 Loaded "${found.title}"!`);
            }
        }

        async function saveCurrentSpreadsheetToCloudinary(isBackgroundAutoSync = false) {
            if (ssIsSavingInFlight) {
                ssHasPendingSaveWhileInFlight = true;
                return;
            }
            ssIsSavingInFlight = true;
            ssHasPendingSaveWhileInFlight = false;
            if (ssAutoSyncPushTimer) {
                clearTimeout(ssAutoSyncPushTimer);
                ssAutoSyncPushTimer = null;
            }

            const saveVersionAtStart = ssLocalEditVersion;
            const btn = document.getElementById('btn-save-xlsx-cloudinary');
            const titleEl = document.getElementById('ss-workbook-title');
            let titleVal = (titleEl?.value || 'GlennBot_Spreadsheet.xlsx').trim();
            if (!titleVal.toLowerCase().endsWith('.xlsx') && !titleVal.toLowerCase().endsWith('.xls')) {
                titleVal += '.xlsx';
                if (titleEl) titleEl.value = titleVal;
            }
            currentSpreadsheetWorkbook.title = titleVal;
            const sentSheetsSnapshot = JSON.parse(JSON.stringify(currentSpreadsheetWorkbook.sheets || []));
            const sentSignature = ssComputeWorkbookSignature({ sheets: sentSheetsSnapshot });

            const origHTML = btn ? btn.innerHTML : '';
            if (btn && !isBackgroundAutoSync) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> <span>Saving to Google Drive...</span>`;
            }
            ssUpdateSyncBadgeStatus('Saving .xlsx to Google Sheets / Drive...', 'syncing');

            try {
                const res = await fetch('/api/spreadsheets/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        workbook_id: currentSpreadsheetWorkbook.workbook_id || '',
                        file_id: currentSpreadsheetWorkbook.file_id || '',
                        gdrive_file_id: currentSpreadsheetWorkbook.gdrive_file_id || '',
                        title: currentSpreadsheetWorkbook.title,
                        sheets: sentSheetsSnapshot
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    if (data.workbook) {
                        // Update workbook IDs and metadata without clobbering any newer local cell edits typed while save was in-flight!
                        currentSpreadsheetWorkbook.workbook_id = data.workbook.workbook_id || currentSpreadsheetWorkbook.workbook_id || '';
                        currentSpreadsheetWorkbook.file_id = data.workbook.file_id || currentSpreadsheetWorkbook.file_id || '';
                        currentSpreadsheetWorkbook.gdrive_file_id = data.workbook.gdrive_file_id || currentSpreadsheetWorkbook.gdrive_file_id || '';
                        currentSpreadsheetWorkbook.gdrive_file_name = data.workbook.gdrive_file_name || currentSpreadsheetWorkbook.gdrive_file_name || '';
                        currentSpreadsheetWorkbook.gdrive_modified_time = data.workbook.gdrive_modified_time || '';
                        currentSpreadsheetWorkbook.gdrive_md5 = data.workbook.gdrive_md5 || '';
                        currentSpreadsheetWorkbook.web_view_link = data.workbook.web_view_link || currentSpreadsheetWorkbook.web_view_link || '';
                        currentSpreadsheetWorkbook.updated_at = data.workbook.updated_at || '';
                        currentSpreadsheetWorkbook.size_bytes = data.workbook.size_bytes || 0;
                        currentSpreadsheetWorkbook.size_formatted = data.workbook.size_formatted || '';
                        currentSpreadsheetWorkbook.title = data.workbook.title || titleVal;
                        lastSyncedSpreadsheetSignature = sentSignature;
                        if (titleEl && document.activeElement !== titleEl) {
                            titleEl.value = currentSpreadsheetWorkbook.title || titleVal;
                        }
                    }
                    if (Array.isArray(data.workbooks)) {
                        savedSpreadsheetsList = data.workbooks;
                    }
                    if (Array.isArray(data.files)) {
                        vaultFilesList = data.files;
                        if (typeof renderVaultFilesList === 'function') {
                            renderVaultFilesList();
                        }
                    } else if (typeof fetchVaultFiles === 'function') {
                        fetchVaultFiles(false);
                    }
                    updateSpreadsheetBadgesAndSelector();
                    if (!isBackgroundAutoSync) {
                        showToast(`✅ ${data.message || 'Saved .xlsx to Google Drive & Files Modal!'}`);
                    }
                } else {
                    ssUpdateSyncBadgeStatus('Google Drive Sync Paused', 'warn');
                    if (!isBackgroundAutoSync) {
                        showToast('⚠️ ' + (data.message || 'Failed to save .xlsx to Google Drive.'));
                    }
                }
            } catch (e) {
                ssUpdateSyncBadgeStatus('Network Error during Sync', 'warn');
                if (!isBackgroundAutoSync) {
                    showToast('⚠️ Network error while saving .xlsx to Google Drive.');
                }
            } finally {
                ssIsSavingInFlight = false;
                if (btn && !isBackgroundAutoSync) {
                    btn.disabled = false;
                    btn.innerHTML = origHTML || `<i class="fab fa-google-drive"></i> <span>Save .xlsx to Google Drive</span>`;
                }
                if (ssHasPendingSaveWhileInFlight || ssLocalEditVersion !== saveVersionAtStart) {
                    ssHasPendingSaveWhileInFlight = false;
                    setTimeout(() => {
                        saveCurrentSpreadsheetToCloudinary(true);
                    }, 30);
                }
            }
        }

        async function handleLocalXlsxImport(inputEl) {
            const file = inputEl?.files?.[0];
            if (!file) return;

            const rejectBanner = document.getElementById('ss-import-reject-banner');
            const rejectText = document.getElementById('ss-import-reject-text');
            const rejectTags = document.getElementById('ss-import-reject-tags');
            if (rejectBanner) rejectBanner.classList.add('hidden');

            const btn = document.getElementById('btn-import-local-xlsx');
            const origHTML = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> <span>Validating in Python...</span>`;
            }

            try {
                const formData = new FormData();
                formData.append('file', file);

                const res = await fetch('/api/spreadsheets/import', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();

                if (!res.ok || data.status !== 'success' || data.rejected) {
                    const msg = data.message || `Import Rejected by Python: '${file.name}' contains graphs, images, or non-tabular objects.`;
                    if (rejectBanner && rejectText) {
                        rejectText.textContent = msg;
                        if (rejectTags) {
                            const items = Array.isArray(data.detected_items) ? data.detected_items : [];
                            rejectTags.innerHTML = items.map(it => `<span class="px-2 py-0.5 rounded bg-rose-900/90 border border-rose-400/50 text-[10px] font-mono text-rose-200"><i class="fas fa-times-circle mr-1"></i>${escapeHTML(it)}</span>`).join('');
                        }
                        rejectBanner.classList.remove('hidden');
                    }
                    showToast('🚫 Rejected by Python: Spreadsheet contains graphs/images or unsupported objects!');
                    return;
                }

                // Valid plain tabular .xlsx or .xls! Load sheets into custom spreadsheet
                const importedWb = {
                    workbook_id: '',
                    file_id: '',
                    gdrive_file_id: '',
                    title: /\.(xlsx|xls)$/i.test(file.name) ? file.name : `${file.name}.xlsx`,
                    sheets: data.sheets || []
                };
                loadWorkbookObjectIntoEditor(importedWb);
                showToast(`✅ ${data.message || `Imported '${file.name}'! Click "Save .xlsx to Google Drive" to store in Files Vault.`}`);
            } catch (e) {
                showToast('⚠️ Error importing local spreadsheet file.');
            } finally {
                if (inputEl) inputEl.value = '';
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = origHTML || `<i class="fas fa-file-import"></i> <span>Import .xlsx / .xls</span>`;
                }
            }
        }

        async function downloadCurrentSpreadsheetXlsx() {
            const titleEl = document.getElementById('ss-workbook-title');
            let titleVal = (titleEl?.value || currentSpreadsheetWorkbook.title || 'GlennBot_Spreadsheet.xlsx').trim();
            if (!titleVal.toLowerCase().endsWith('.xlsx')) {
                titleVal = titleVal.replace(/\.xls$/i, '') + '.xlsx';
            }
            currentSpreadsheetWorkbook.title = titleVal;
            const sheet = ssGetActiveSheet();
            ssSaveSheetLayoutToLocalCache(sheet);

            try {
                const res = await fetch('/api/spreadsheets/export-xlsx', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        title: titleVal,
                        sheets: currentSpreadsheetWorkbook.sheets || []
                    })
                });
                if (res.ok) {
                    const blob = await res.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = titleVal;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    setTimeout(() => URL.revokeObjectURL(url), 3000);
                    showToast(`📥 Downloaded "${titleVal}" with saved column widths, row heights, wrap text & formulas!`);
                    return;
                }
            } catch (_) {}

            await saveCurrentSpreadsheetToCloudinary(false);
            const wbId = currentSpreadsheetWorkbook.workbook_id;
            if (!wbId) {
                showToast('⚠️ Could not export spreadsheet file.');
                return;
            }
            const a = document.createElement('a');
            a.href = `/api/spreadsheets/${encodeURIComponent(wbId)}/download`;
            a.download = currentSpreadsheetWorkbook.title || 'GlennBot_Spreadsheet.xlsx';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }

        async function deleteCurrentSpreadsheetFromCloudinary() {
            const wbId = currentSpreadsheetWorkbook.workbook_id;
            if (!wbId) {
                createNewBlankSpreadsheetWorkbook(true);
                return;
            }
            try {
                const res = await fetch(`/api/spreadsheets/${encodeURIComponent(wbId)}`, { method: 'DELETE' });
                const data = await res.json();
                if (data.status === 'success') {
                    savedSpreadsheetsList = Array.isArray(data.workbooks) ? data.workbooks : [];
                    if (Array.isArray(data.files)) {
                        vaultFilesList = data.files;
                        if (typeof renderVaultFilesList === 'function') {
                            renderVaultFilesList();
                        }
                    }
                    createNewBlankSpreadsheetWorkbook(false);
                    updateSpreadsheetBadgesAndSelector();
                    showToast(`🗑️ ${data.message || 'Deleted spreadsheet from Google Drive & Files Vault.'}`);
                }
            } catch (_) {
                showToast('⚠️ Could not delete spreadsheet from Google Drive.');
            }
        }

        // =========================================================================
        // --- PRE-DASHBOARD LOGIN GATE & ROLE-BASED ACCESS CONTROL (CLIENT vs ADMIN) ---
        // =========================================================================
        window.gbCurrentAuthUser = null;
        window.gbDashboardInitialized = false;
        let gbAdminOAuthPollTimer = null;

        // Automatically attach X-GlennBot-Session token header to all internal API fetches
        (function installGlennBotAuthFetchInterceptor() {
            const origFetch = window.fetch.bind(window);
            window.fetch = function(input, init) {
                try {
                    const tok = localStorage.getItem('gb_auth_session_token') || '';
                    if (tok) {
                        const urlStr = typeof input === 'string' ? input : (input && input.url ? input.url : '');
                        if (urlStr.startsWith('/') || urlStr.includes(window.location.host)) {
                            init = init ? Object.assign({}, init) : {};
                            const hdrs = new Headers(init.headers || {});
                            if (!hdrs.has('X-GlennBot-Session')) {
                                hdrs.set('X-GlennBot-Session', tok);
                            }
                            init.headers = hdrs;
                        }
                    }
                } catch (_) {}
                return origFetch(input, init);
            };
        })();

        function showGlennBotLoginAlert(msg, isSuccess = false) {
            const box = document.getElementById('gb-login-alert-box');
            const txt = document.getElementById('gb-login-alert-text');
            const icon = document.getElementById('gb-login-alert-icon');
            if (!box || !txt) return;
            box.classList.remove('hidden', 'border-rose-500/60', 'bg-rose-950/60', 'text-rose-200', 'border-emerald-500/60', 'bg-emerald-950/60', 'text-emerald-200');
            if (isSuccess) {
                box.classList.add('border-emerald-500/60', 'bg-emerald-950/60', 'text-emerald-200');
                if (icon) icon.className = 'fas fa-check-circle text-emerald-400 mt-0.5 shrink-0';
            } else {
                box.classList.add('border-rose-500/60', 'bg-rose-950/60', 'text-rose-200');
                if (icon) icon.className = 'fas fa-exclamation-triangle text-rose-400 mt-0.5 shrink-0';
            }
            txt.textContent = msg;
        }

        function toggleGlennBotLoginPasswordVisibility() {
            const pwdInput = document.getElementById('gb-login-password');
            const eyeIcon = document.getElementById('gb-login-pwd-eye');
            if (!pwdInput) return;
            if (pwdInput.type === 'password') {
                pwdInput.type = 'text';
                if (eyeIcon) eyeIcon.className = 'fas fa-eye-slash';
            } else {
                pwdInput.type = 'password';
                if (eyeIcon) eyeIcon.className = 'fas fa-eye';
            }
        }

        function applyDashboardAuthRoleUI(userObj) {
            window.gbCurrentAuthUser = userObj || null;
            const isAdmin = Boolean(userObj && userObj.is_admin);
            const headerInternalBtn = document.getElementById('header-internal-api-btn');
            const sidebarInternalBtn = document.getElementById('sidebar-internal-api-btn');
            const manageModalInternalBtn = document.getElementById('manage-api-internal-n8n-btn');
            const roleBadge = document.getElementById('header-auth-role-badge');
            const roleText = document.getElementById('header-auth-role-text');

            if (isAdmin) {
                if (headerInternalBtn) {
                    headerInternalBtn.classList.remove('!hidden');
                    headerInternalBtn.style.display = '';
                }
                if (sidebarInternalBtn) {
                    sidebarInternalBtn.classList.remove('hidden');
                    sidebarInternalBtn.style.display = '';
                }
                if (manageModalInternalBtn) {
                    manageModalInternalBtn.classList.remove('hidden');
                    manageModalInternalBtn.style.display = '';
                }
                if (roleBadge && roleText) {
                    roleBadge.className = 'hidden md:inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-[10px] font-bold border border-emerald-500/50 bg-emerald-950/60 text-emerald-300';
                    roleBadge.innerHTML = `<i class="fas fa-user-shield text-emerald-400"></i><span>ADMIN • ${userObj.email || 'glennardtasico@gmail.com'}</span>`;
                }
            } else {
                // Restricted Client Account: Hide all Internal API (n8n) buttons & close modal if open
                if (headerInternalBtn) {
                    headerInternalBtn.classList.add('!hidden');
                    headerInternalBtn.style.display = 'none';
                }
                if (sidebarInternalBtn) {
                    sidebarInternalBtn.classList.add('hidden');
                    sidebarInternalBtn.style.display = 'none';
                }
                if (manageModalInternalBtn) {
                    manageModalInternalBtn.classList.add('hidden');
                    manageModalInternalBtn.style.display = 'none';
                }
                const internalModal = document.getElementById('internal-api-n8n-modal');
                if (internalModal && !internalModal.classList.contains('hidden')) {
                    internalModal.classList.add('hidden');
                }
                if (roleBadge) {
                    const uidLabel = (userObj && userObj.user_id) ? userObj.user_id : 'Client';
                    roleBadge.className = 'hidden md:inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-[10px] font-bold border border-gb-cyan/40 bg-slate-900/90 text-gb-cyan';
                    roleBadge.innerHTML = `<i class="fas fa-user-lock text-gb-cyan"></i><span>CLIENT • ${uidLabel}</span>`;
                }
            }
        }

        async function unlockGlennBotDashboardWithSession(sessionToken, userObj, preloadedSettings = null, preloadedProfile = null) {
            if (sessionToken) {
                try {
                    localStorage.setItem('gb_auth_session_token', sessionToken);
                } catch (_) {}
            }
            applyDashboardAuthRoleUI(userObj);
            await loadUserSettings(preloadedSettings, preloadedProfile);
            const gate = document.getElementById('glennbot-login-gate-overlay');
            if (gate) {
                gate.classList.add('hidden');
            }
            await initializeGlennBotDashboardDataOnce();
        }

        async function submitGlennBotClientLogin(event) {
            if (event) event.preventDefault();
            const uidEl = document.getElementById('gb-login-userid');
            const pwdEl = document.getElementById('gb-login-password');
            const btn = document.getElementById('gb-login-submit-btn');
            const user_id = (uidEl ? uidEl.value : '').trim();
            const password = (pwdEl ? pwdEl.value : '').trim();

            if (!user_id || !password) {
                showGlennBotLoginAlert('Please enter both your User ID and Password.');
                return;
            }
            const origHtml = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i><span>Verifying Credentials...</span>';
            }
            try {
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id, password })
                });
                const data = await res.json();
                if (!res.ok || data.status !== 'success') {
                    showGlennBotLoginAlert(data.message || 'Invalid User ID or Password. Access Denied.');
                    return;
                }
                showGlennBotLoginAlert('Client credentials verified! Opening dashboard...', true);
                if (pwdEl) pwdEl.value = '';
                await unlockGlennBotDashboardWithSession(data.session_token, data.user, data.user_settings || null, data.settings_profile || null);
                showToast(`🔓 Signed in as Client (${data.user?.user_id || user_id})`);
            } catch (err) {
                showGlennBotLoginAlert('Network error while verifying credentials. Please make sure main.py is running.');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = origHtml;
                }
            }
        }

        function startGlennBotAdminGoogleLogin() {
            const btn = document.getElementById('gb-admin-google-login-btn');
            const state = `gb_admin_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
            showGlennBotLoginAlert('Opening Composio Google OAuth popup for Administrator verification...', true);

            const width = 540;
            const height = 680;
            const left = Math.max(0, Math.round((window.screen.width - width) / 2));
            const top = Math.max(0, Math.round((window.screen.height - height) / 2));
            const popupUrl = `/api/auth/google/redirect?state=${encodeURIComponent(state)}`;
            const popup = window.open(
                popupUrl,
                'GlennBotAdminGoogleOAuth',
                `width=${width},height=${height},left=${left},top=${top},resizable=yes,scrollbars=yes`
            );

            if (gbAdminOAuthPollTimer) {
                clearInterval(gbAdminOAuthPollTimer);
            }
            const startedAt = Date.now();
            gbAdminOAuthPollTimer = setInterval(async () => {
                if (Date.now() - startedAt > 180000) {
                    clearInterval(gbAdminOAuthPollTimer);
                    gbAdminOAuthPollTimer = null;
                    return;
                }
                try {
                    const r = await fetch(`/api/auth/google/poll?state=${encodeURIComponent(state)}`);
                    const d = await r.json();
                    if (d && d.status === 'success' && d.session_token && d.user) {
                        clearInterval(gbAdminOAuthPollTimer);
                        gbAdminOAuthPollTimer = null;
                        showGlennBotLoginAlert(d.message || 'Administrator verified!', true);
                        await unlockGlennBotDashboardWithSession(d.session_token, d.user, d.user_settings || null, d.settings_profile || null);
                        showToast(`🛡️ Welcome Administrator (${d.user.email || 'glennardtasico@gmail.com'})! Internal API (n8n) Unlocked.`);
                    } else if (d && d.status === 'error') {
                        clearInterval(gbAdminOAuthPollTimer);
                        gbAdminOAuthPollTimer = null;
                        showGlennBotLoginAlert(d.message || 'Administrator Google OAuth denied.');
                    }
                } catch (_) {}
            }, 1500);
        }

        window.addEventListener('message', async (event) => {
            const data = event && event.data;
            if (!data || data.type !== 'GLENNBOT_ADMIN_GOOGLE_AUTH_RESULT') return;
            if (gbAdminOAuthPollTimer) {
                clearInterval(gbAdminOAuthPollTimer);
                gbAdminOAuthPollTimer = null;
            }
            if (data.status === 'success' && data.session_token && data.user) {
                showGlennBotLoginAlert(data.message || 'Administrator verified!', true);
                await unlockGlennBotDashboardWithSession(data.session_token, data.user, data.user_settings || null, data.settings_profile || null);
                showToast(`🛡️ Welcome Administrator (${data.user.email || 'glennardtasico@gmail.com'})! Internal API (n8n) Unlocked.`);
            } else {
                showGlennBotLoginAlert(data.message || 'Administrator Google OAuth Access Denied.');
            }
        });

        async function logoutGlennBotDashboard() {
            const wasAdminLogout = Boolean(window.gbCurrentAuthUser && window.gbCurrentAuthUser.role === 'admin');
            try {
                await fetch('/api/auth/logout', { method: 'POST' });
            } catch (_) {}
            try {
                localStorage.removeItem('gb_auth_session_token');
            } catch (_) {}
            window.gbCurrentAuthUser = null;

            // Automatically remove glennardtasico@gmail.com from frontend Email Modal state so it never duplicates
            if (typeof emailAccountsList !== 'undefined' && Array.isArray(emailAccountsList)) {
                emailAccountsList = emailAccountsList.filter(acc => {
                    const addr = String((acc && acc.email_address) || '').trim().toLowerCase();
                    return addr !== 'glennardtasico@gmail.com';
                });
                if (emailAccountsList.length > 0) {
                    activeEmailAccountId = emailAccountsList[0].id;
                } else {
                    activeEmailAccountId = '';
                    activeEmailMessages = [];
                }
                if (typeof renderEmailPlatformColumnCards === 'function') renderEmailPlatformColumnCards();
                if (typeof updateEmailBadgesAndSelectors === 'function') updateEmailBadgesAndSelectors();
                if (typeof renderEmailMessagesList === 'function') renderEmailMessagesList();
            }

            const gate = document.getElementById('glennbot-login-gate-overlay');
            if (gate) {
                gate.classList.remove('hidden');
            }
            const alertBox = document.getElementById('gb-login-alert-box');
            if (alertBox) alertBox.classList.add('hidden');
            showToast(wasAdminLogout
                ? '🔒 Logged out of Admin account & disconnected glennardtasico@gmail.com from Email Modal.'
                : '🔒 Logged out of GlennBot Automations.');
        }

        async function initializeGlennBotDashboardDataOnce() {
            if (window.gbDashboardInitialized) return;
            window.gbDashboardInitialized = true;
            loadUserSettings();
            initCalendarControls();
            // Initialize real-time email webhook sequence baseline
            await pollRealtimeEmailWebhookEvents();
            // Load initial dashboard data in parallel so Analytics, Comments, Messages, Email, Contacts, Files, and Spread Sheet never block each other
            fetchAnalyticsData(false);
            fetchEmailAccounts(false);
            fetchCrmContacts(false);
            fetchVaultFiles(false);
            fetchSavedSpreadsheets(false);
            await Promise.allSettled([
                fetchSocialAccounts(),
                fetchScheduledPosts(),
                fetchComments(false),
                fetchConversations(false)
            ]);
        }

        window.onload = async () => {
            try {
                const sessRes = await fetch('/api/auth/session');
                const sessData = await sessRes.json();
                if (sessData && sessData.authenticated && sessData.user) {
                    await unlockGlennBotDashboardWithSession(null, sessData.user, sessData.user_settings || null, sessData.settings_profile || null);
                } else {
                    const gate = document.getElementById('glennbot-login-gate-overlay');
                    if (gate) gate.classList.remove('hidden');
                }
            } catch (_) {
                const gate = document.getElementById('glennbot-login-gate-overlay');
                if (gate) gate.classList.remove('hidden');
            }

            setInterval(() => {
                if (!window.gbCurrentAuthUser) return;
                if (activeTab === 'calendar' || activeTab === 'queue') {
                    fetchScheduledPosts();
                } else if (activeTab === 'analytics') {
                    fetchAnalyticsData(false);
                }
            }, 15000);

            // Quota-Safe Background Email Inbox Sync (every 15s) + Fast Webhook Event Queue Listener (every 3s)
            setInterval(async () => {
                if (!window.gbCurrentAuthUser) return;
                if (!activeEmailAccountId && Array.isArray(emailAccountsList) && emailAccountsList.length > 0) {
                    activeEmailAccountId = emailAccountsList[0].id;
                }
                if (activeEmailAccountId && activeEmailFolder === 'inbox') {
                    await refreshActiveEmailInbox(false, true);
                }
            }, 15000);

            setInterval(async () => {
                if (!window.gbCurrentAuthUser) return;
                await pollRealtimeEmailWebhookEvents();
            }, 3000);

            // Fast Non-Blocking Real-Time Polling for Comments & Messages across ALL tabs (guarded by in-flight locks so UI never freezes while n8n executes)
            let lastActivityPollTs = Date.now();
            setInterval(() => {
                if (!window.gbCurrentAuthUser) return;
                const now = Date.now();
                const intervalMs = 2000;
                if (now - lastActivityPollTs >= intervalMs) {
                    lastActivityPollTs = now;
                    fetchComments(false);
                    fetchConversations(false);
                }
            }, 650);

            document.addEventListener('visibilitychange', () => {
                if (!window.gbCurrentAuthUser) return;
                if (document.visibilityState === 'visible') {
                    lastActivityPollTs = Date.now();
                    fetchComments(false);
                    fetchConversations(false);
                    if (activeEmailAccountId) {
                        refreshActiveEmailInbox(false, true);
                    }
                    pollRealtimeEmailWebhookEvents();
                }
            });
        }

        // =========================================================================
        // --- TEXTBEE.DEV SMS GATEWAY (SIM 2) + CREATE NEW SMS MODAL ---
        // =========================================================================
        let textbeeCachedStatus = {
            api_key: '',
            sim_subscription_id: '2',
            device_id: '',
            webhook_secret: '',
            devices: [],
            webhook_url: ''
        };

        async function fetchTextbeeStatusSilently(discover = true) {
            try {
                const res = await fetch(`/api/sms/textbee/status?discover=${discover ? 'true' : 'false'}`);
                const data = await res.json();
                if (data.status === 'success') {
                    textbeeCachedStatus = {
                        ...textbeeCachedStatus,
                        ...data
                    };
                }
            } catch (e) {
                console.error("TextBee status fetch error:", e);
            }
            return textbeeCachedStatus;
        }

        function getCrmContactMobileNumber(c) {
            if (!c || typeof c !== 'object') return '';
            const raw = String(c.contact_number || c.phone || c.mobile_number || '').trim();
            if (!raw) return '';
            const digits = raw.replace(/\D+/g, '');
            return digits.length >= 7 ? raw : '';
        }

        function populateNewSmsCrmContactsDropdown(selectedPhone = '') {
            const contactSelect = document.getElementById('new-sms-crm-contact-picker');
            if (!contactSelect) return;

            const currentVal = selectedPhone || contactSelect.value || '';
            const allContacts = Array.isArray(crmContactsList) ? crmContactsList : [];
            const contactsWithPhone = allContacts.filter(c => getCrmContactMobileNumber(c) !== '');

            let opts = `<option value="">-- Select from Saved CRM Contacts (${contactsWithPhone.length} with Mobile Number) or type below --</option>`;
            contactsWithPhone.forEach(c => {
                const mobileNum = getCrmContactMobileNumber(c);
                const fullName = [c.first_name, c.middle_name, c.last_name]
                    .map(s => String(s || '').trim())
                    .filter(Boolean)
                    .join(' ')
                    .trim() || String(c.social_username || c.display_name || c.email_address || mobileNum).trim();
                const isSelected = (currentVal && currentVal === mobileNum) ? ' selected' : '';
                opts += `<option value="${escapeHTML(mobileNum)}" data-name="${escapeHTML(fullName)}"${isSelected}>${escapeHTML(fullName)} (${escapeHTML(mobileNum)})</option>`;
            });
            contactSelect.innerHTML = opts;
        }

        async function openCreateNewSmsModal(prefillPhone = '', prefillName = '') {
            const modal = document.getElementById('create-new-sms-modal');
            if (!modal) return;
            modal.classList.remove('hidden');

            const phoneInput = document.getElementById('new-sms-recipient-phone');
            const nameInput = document.getElementById('new-sms-recipient-name');
            const msgInput = document.getElementById('new-sms-message-body');
            if (phoneInput && prefillPhone) phoneInput.value = prefillPhone;
            if (nameInput && prefillName) nameInput.value = prefillName;
            if (msgInput) updateNewSmsCharCount();

            // Populate CRM contacts dropdown immediately from memory, then refresh from /api/contacts
            populateNewSmsCrmContactsDropdown(prefillPhone);
            try {
                const res = await fetch('/api/contacts?refresh=false');
                const data = await res.json();
                if (data && data.status === 'success' && Array.isArray(data.contacts)) {
                    crmContactsList = data.contacts;
                    updateCrmBadgesAndStats();
                    populateNewSmsCrmContactsDropdown(prefillPhone);
                }
            } catch (e) {
                console.warn('Could not refresh CRM contacts for SMS modal:', e);
            }

            const statusBadge = document.getElementById('new-sms-gateway-status-badge');
            if (statusBadge) {
                statusBadge.innerHTML = `<i class="fas fa-circle-notch fa-spin mr-1"></i> Checking TextBee SIM 2 Gateway...`;
            }

            const st = await fetchTextbeeStatusSilently(true);
            const simInput = document.getElementById('new-sms-sim-slot');
            if (simInput && st.sim_subscription_id) simInput.value = String(st.sim_subscription_id);

            if (statusBadge) {
                if (st.device_id) {
                    statusBadge.className = "px-2.5 py-1 rounded-full bg-emerald-500/15 border border-emerald-400/50 text-emerald-300 text-[11px] font-bold flex items-center gap-1.5";
                    statusBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> <span>TextBee Ready • SIM #${escapeHTML(st.sim_subscription_id || '2')} • Device: ${escapeHTML(st.device_id.slice(-8))}</span>`;
                } else {
                    statusBadge.className = "px-2.5 py-1 rounded-full bg-amber-500/15 border border-amber-400/50 text-amber-300 text-[11px] font-bold flex items-center gap-1.5 cursor-pointer";
                    statusBadge.innerHTML = `<i class="fas fa-exclamation-circle"></i> <span>Set Device ID in TextBee Settings (Click Here)</span>`;
                    statusBadge.onclick = () => {
                        closeCreateNewSmsModal();
                        openConnectAccountsModal('textbee');
                    };
                }
            }
        }

        function closeCreateNewSmsModal() {
            const modal = document.getElementById('create-new-sms-modal');
            if (modal) modal.classList.add('hidden');
        }

        function onNewSmsContactSelectChange(sel) {
            if (!sel || !sel.value) return;
            const phoneInput = document.getElementById('new-sms-recipient-phone');
            const nameInput = document.getElementById('new-sms-recipient-name');
            const selectedOpt = sel.options[sel.selectedIndex];
            const cName = selectedOpt ? selectedOpt.getAttribute('data-name') : '';
            if (phoneInput) phoneInput.value = sel.value;
            if (nameInput && cName) nameInput.value = cName;
        }

        function updateNewSmsCharCount() {
            const msgInput = document.getElementById('new-sms-message-body');
            const counter = document.getElementById('new-sms-char-counter');
            if (!msgInput || !counter) return;
            const len = (msgInput.value || '').length;
            const segments = len === 0 ? 0 : Math.ceil(len / 160);
            counter.textContent = `${len} chars • ${segments} SMS segment${segments === 1 ? '' : 's'}`;
        }

        function insertNewSmsQuickTemplate(txt) {
            const msgInput = document.getElementById('new-sms-message-body');
            if (!msgInput) return;
            msgInput.value = txt;
            updateNewSmsCharCount();
            msgInput.focus();
        }

        async function sendNewTextbeeSmsFromModal() {
            const phoneInput = document.getElementById('new-sms-recipient-phone');
            const nameInput = document.getElementById('new-sms-recipient-name');
            const msgInput = document.getElementById('new-sms-message-body');
            const simInput = document.getElementById('new-sms-sim-slot');
            const btn = document.getElementById('btn-submit-new-sms');

            const recipient = (phoneInput?.value || '').trim();
            const recipientName = (nameInput?.value || '').trim();
            const message = (msgInput?.value || '').trim();
            const simSlot = (simInput?.value || '2').trim();

            if (!recipient) {
                alert("Please enter the recipient's mobile phone number (e.g., 09171234567 or +639171234567).");
                if (phoneInput) phoneInput.focus();
                return;
            }
            if (!message) {
                alert("Please type your SMS message before clicking Send SMS.");
                if (msgInput) msgInput.focus();
                return;
            }

            const origHTML = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> <span>Sending SMS via SIM #${escapeHTML(simSlot)}...</span>`;
            }

            try {
                const res = await fetch('/api/sms/textbee/send', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        recipient: recipient,
                        recipient_name: recipientName,
                        message: message,
                        sim_subscription_id: simSlot
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast(`📱 SMS sent to ${data.recipient || recipient} via TextBee (SIM #${simSlot})!`);
                    if (msgInput) msgInput.value = '';
                    updateNewSmsCharCount();
                    closeCreateNewSmsModal();

                    await fetchConversations(false);
                    if (data.conversation && data.conversation.conv_key) {
                        selectMessageConversation(
                            data.conversation.conv_key,
                            data.conversation.conversation_id,
                            data.conversation.account_id
                        );
                    }
                } else {
                    alert("❌ Failed to send SMS via TextBee.dev:\n" + (data.message || "Unknown error"));
                }
            } catch (e) {
                console.error("Send new SMS error:", e);
                alert("❌ Network error while sending SMS via TextBee.dev.");
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = origHTML;
                }
            }
        }

        async function renderTextbeeConnectView() {
            const body = document.getElementById('connect-modal-body');
            if (!body) return;
            body.innerHTML = `
                <div class="text-center py-10 text-slate-400 text-xs">
                    <i class="fas fa-circle-notch fa-spin text-2xl text-emerald-400 mb-2"></i>
                    <p>Loading TextBee.dev SMS Gateway (SIM 2) configuration & scanning devices...</p>
                </div>
            `;

            const st = await fetchTextbeeStatusSilently(true);
            const devicesList = Array.isArray(st.devices) ? st.devices : [];
            const deviceOptionsHTML = devicesList.length > 0
                ? devicesList.map(d => `<option value="${escapeHTML(d.id)}" ${d.id === st.device_id ? 'selected' : ''}>${escapeHTML(d.name)} — ID: ${escapeHTML(d.id)}</option>`).join('')
                : `<option value="${escapeHTML(st.device_id || '')}">Configured Device ID — ${escapeHTML(st.device_id || '')}</option>`;

            body.innerHTML = `
                <div class="space-y-4">
                    <div class="p-4 rounded-2xl bg-gradient-to-r from-emerald-950/60 via-slate-900 to-slate-900 border border-emerald-500/40 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                        <div class="flex items-start gap-3">
                            <div class="w-11 h-11 rounded-xl bg-emerald-500/20 border border-emerald-400/50 flex items-center justify-center text-emerald-300 shrink-0 text-lg">
                                <i class="fas fa-sms"></i>
                            </div>
                            <div>
                                <div class="flex items-center gap-2 flex-wrap">
                                    <h4 class="text-sm sm:text-base font-extrabold text-white">TextBee.dev Android SMS Gateway (SIM 2)</h4>
                                    <span class="px-2 py-0.5 rounded-full bg-emerald-500/20 border border-emerald-400/50 text-emerald-300 text-[10px] font-bold">Separate Direct API</span>
                                </div>
                                <p class="text-xs text-slate-300 mt-0.5">
                                    Send & receive real SMS messages directly from Unified Inbox and n8n workflows using your Android phone's SIM 2.
                                </p>
                            </div>
                        </div>
                        <button type="button" onclick="closeConnectAccountsModal(); openCreateNewSmsModal();" class="px-3.5 py-2 rounded-xl bg-gradient-to-r from-emerald-400 to-gb-cyan text-slate-950 font-extrabold text-xs flex items-center gap-1.5 shrink-0 shadow-[0_0_15px_rgba(16,185,129,0.35)]">
                            <i class="fas fa-paper-plane"></i> <span>+ Create New SMS</span>
                        </button>
                    </div>

                    <div class="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                        <div class="p-3.5 rounded-xl bg-slate-900/90 border border-slate-700 space-y-1.5">
                            <label class="text-[11px] font-bold text-slate-300 uppercase tracking-wider flex items-center justify-between">
                                <span><i class="fas fa-key text-amber-400 mr-1"></i> TextBee API Key (.env)</span>
                                <span class="text-[10px] text-emerald-400 font-semibold">Pre-Configured</span>
                            </label>
                            <input type="text" id="textbee-cfg-api-key" value="${escapeHTML(st.api_key || '')}"
                                class="w-full bg-slate-950 border border-slate-700 focus:border-gb-cyan rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none">
                        </div>

                        <div class="p-3.5 rounded-xl bg-slate-900/90 border border-slate-700 space-y-1.5">
                            <label class="text-[11px] font-bold text-slate-300 uppercase tracking-wider flex items-center justify-between">
                                <span><i class="fas fa-sim-card text-gb-cyan mr-1"></i> SIM Subscription ID (SIM Slot)</span>
                                <span class="text-[10px] text-gb-cyan font-semibold">Default: SIM 2</span>
                            </label>
                            <select id="textbee-cfg-sim-id" class="w-full bg-slate-950 border border-slate-700 focus:border-gb-cyan rounded-lg px-3 py-2 text-xs text-white focus:outline-none cursor-pointer">
                                <option value="1" ${String(st.sim_subscription_id) === '1' ? 'selected' : ''}>SIM 1 (simSubscriptionId: 1)</option>
                                <option value="2" ${String(st.sim_subscription_id || '2') === '2' ? 'selected' : ''}>SIM 2 (simSubscriptionId: 2)</option>
                            </select>
                        </div>
                    </div>

                    <div class="p-4 rounded-xl bg-slate-900/90 border border-slate-700 space-y-3">
                        <div class="flex flex-wrap items-center justify-between gap-2">
                            <label class="text-[11px] font-bold text-slate-300 uppercase tracking-wider">
                                <i class="fas fa-mobile-alt text-emerald-400 mr-1"></i> TextBee Android Device ID (.env)
                            </label>
                            <button type="button" onclick="autoDetectTextbeeDevice()" class="px-3 py-1 rounded-lg bg-gb-cyan/15 hover:bg-gb-cyan/25 border border-gb-cyan/50 text-gb-cyan text-[11px] font-bold flex items-center gap-1.5 transition-all">
                                <i class="fas fa-sync-alt" id="textbee-detect-spin"></i> <span>Auto-Detect Device from TextBee API</span>
                            </button>
                        </div>

                        <select id="textbee-cfg-device-picker" onchange="if(this.value) document.getElementById('textbee-cfg-device-id').value = this.value;" class="w-full bg-slate-950 border border-slate-700 focus:border-gb-cyan rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none">
                            ${deviceOptionsHTML}
                        </select>

                        <input type="text" id="textbee-cfg-device-id" value="${escapeHTML(st.device_id || '')}"
                            placeholder="Paste your TextBee Device ID here (or click Auto-Detect above)"
                            class="w-full bg-slate-950 border border-slate-700 focus:border-gb-cyan rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none">
                    </div>

                    <div class="p-4 rounded-xl bg-slate-950/90 border border-slate-800 space-y-3">
                        <div class="flex flex-wrap items-center justify-between gap-2">
                            <span class="text-[11px] font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                                <i class="fas fa-satellite-dish text-purple-400"></i>
                                <span>Inbound SMS Webhook URL &amp; Signing Secret (Ngrok / Cloud)</span>
                            </span>
                            <div class="flex items-center gap-2">
                                <span class="px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-[10px] font-bold">
                                    HMAC-SHA256 Verified ${st.webhook_hits_count ? `• ${st.webhook_hits_count} received` : ''}
                                </span>
                                <button type="button" onclick="navigator.clipboard.writeText('${escapeHTML(st.webhook_url || '')}'); showToast('✅ Copied TextBee Webhook URL!');" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-600 text-gb-cyan text-[11px] font-semibold">
                                    <i class="fas fa-copy mr-1"></i> Copy URL
                                </button>
                            </div>
                        </div>
                        <div class="font-mono text-xs text-emerald-300 bg-slate-900 px-3 py-2 rounded-lg border border-slate-800 break-all">
                            ${escapeHTML(st.webhook_url || (window.location.origin + '/api/webhooks/textbee/sms'))}
                        </div>
                        <p class="text-[10px] text-slate-400">
                            <i class="fas fa-check-circle text-emerald-400 mr-1"></i>Both <code class="text-gb-cyan">/api/webhooks/textbee/sms</code> and <code class="text-gb-cyan">/webhooks</code> automatically detect &amp; verify TextBee <code class="text-emerald-300">MESSAGE_RECEIVED</code> webhooks.
                        </p>
                        <div class="space-y-1 pt-1">
                            <label class="text-[10px] font-bold text-slate-400 uppercase tracking-wider flex items-center justify-between">
                                <span><i class="fas fa-shield-alt text-emerald-400 mr-1"></i> TextBee Webhook Signing Secret (X-Signature • .env)</span>
                                <span class="text-[10px] text-emerald-400 font-semibold">TEXTBEE_WEBHOOK_SECRET</span>
                            </label>
                            <input type="text" id="textbee-cfg-webhook-secret" value="${escapeHTML(st.webhook_secret || '')}"
                                class="w-full bg-slate-900 border border-slate-700 focus:border-emerald-400 rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none">
                        </div>
                    </div>

                    <div class="flex justify-end gap-2 pt-1">
                        <button type="button" onclick="saveTextbeeModalConfig()" id="btn-save-textbee-cfg" class="px-5 py-2.5 rounded-xl bg-gradient-to-r from-emerald-400 to-gb-cyan text-slate-950 font-extrabold text-xs flex items-center gap-2 shadow-[0_0_15px_rgba(0,240,255,0.3)]">
                            <i class="fas fa-save"></i> <span>Save TextBee SMS Settings</span>
                        </button>
                    </div>
                </div>
            `;
        }

        async function autoDetectTextbeeDevice() {
            const spin = document.getElementById('textbee-detect-spin');
            if (spin) spin.classList.add('fa-spin');
            try {
                await saveTextbeeModalConfig(true);
            } finally {
                if (spin) spin.classList.remove('fa-spin');
            }
        }

        async function saveTextbeeModalConfig(isAutoDetect = false) {
            const apiKey = document.getElementById('textbee-cfg-api-key')?.value?.trim() || '';
            const simId = document.getElementById('textbee-cfg-sim-id')?.value?.trim() || '2';
            const devId = document.getElementById('textbee-cfg-device-id')?.value?.trim() || '';
            const whSec = document.getElementById('textbee-cfg-webhook-secret')?.value?.trim() || '';
            const btn = document.getElementById('btn-save-textbee-cfg');
            if (btn) btn.disabled = true;

            try {
                const res = await fetch('/api/sms/textbee/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        api_key: apiKey,
                        sim_subscription_id: simId,
                        device_id: devId,
                        webhook_secret: whSec
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    textbeeCachedStatus = data;
                    await renderTextbeeConnectView();
                    await fetchConversations(false);
                    if (isAutoDetect) {
                        if (data.devices && data.devices.length > 0) {
                            showToast(`📱 Auto-detected ${data.devices.length} TextBee Android device(s)!`);
                        } else {
                            showToast("⚠️ No additional Android devices returned by TextBee API. Using configured Device ID.");
                        }
                    } else {
                        showToast("✅ Saved TextBee.dev SMS (SIM " + simId + ") configuration!");
                    }
                }
            } catch (e) {
                console.error("Save TextBee config error:", e);
                alert("Failed to save TextBee configuration.");
            } finally {
                if (btn) btn.disabled = false;
            }
        }

