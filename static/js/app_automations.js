        // ============================================================================
        // --- VIEW 11: AUTOMATIONS VISUAL CANVAS & NATIVE N8N JSON EDITOR ENGINE ---
        // Starts as a strictly locked Blank Canvas until the user uploads a .JSON file
        // or generates one via "Ask AI". Supports Dashboard Event Trigger (Webhook),
        // IF, Wait, Code, HTTP Request, and Set nodes!
        // ============================================================================
        let automationsCanvasSavedWorkflows = [];
        let automationsCanvasExecutionHistory = [];
        let automationsCanvasCurrentId = '';
        let automationsCanvasCurrentJson = null; // null = Blank Locked Canvas!
        let automationsCanvasIsActive = true;
        let automationsCanvasSelectedNodeName = '';
        let automationsCanvasLastTraceByNode = {};
        let automationsCanvasZoom = 1;
        let automationsCanvasPanX = 30;
        let automationsCanvasPanY = 30;
        let automationsCanvasDragState = null;
        let automationsCanvasIsFullscreen = false;
        let automationsCanvasFloatingDrawerOpen = false;

        function parseFlexibleN8nWorkflowJson(rawInput) {
            if (rawInput && typeof rawInput === 'object') {
                if (Array.isArray(rawInput) && rawInput.length > 0) return parseFlexibleN8nWorkflowJson(rawInput[0]);
                if (rawInput.workflow_json && typeof rawInput.workflow_json === 'object') return rawInput.workflow_json;
                if (rawInput.data && typeof rawInput.data === 'object' && Array.isArray(rawInput.data.nodes)) return rawInput.data;
                return rawInput;
            }
            let s = String(rawInput || '').replace(/^\uFEFF/, '').trim();
            if (!s) throw new Error('Empty JSON content.');
            // Strip markdown code fences if present
            if (s.startsWith('```')) {
                s = s.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
            }
            let parsed;
            try {
                parsed = JSON.parse(s);
            } catch (firstErr) {
                // If wrapped in outer quotes like "{ \"name\": ... }"
                if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
                    const unquoted = s.slice(1, -1).trim();
                    parsed = JSON.parse(unquoted);
                } else {
                    throw firstErr;
                }
            }
            if (typeof parsed === 'string') {
                parsed = JSON.parse(parsed);
            }
            return parseFlexibleN8nWorkflowJson(parsed);
        }

        let automationsCanvasLivePollTimer = null;
        let automationsCanvasLastSeenExecId = '';

        async function initAutomationsCanvasView() {
            try {
                const res = await fetch('/api/automations/workflows');
                const data = await res.json();
                if (data.status === 'success') {
                    automationsCanvasSavedWorkflows = Array.isArray(data.workflows) ? data.workflows : [];
                    automationsCanvasExecutionHistory = Array.isArray(data.execution_history) ? data.execution_history : [];
                    if (automationsCanvasExecutionHistory.length > 0) {
                        automationsCanvasLastSeenExecId = String(automationsCanvasExecutionHistory[0].execution_id || '');
                    }
                    renderAutomationsSavedWorkflowSelect();
                    renderAutomationsExecutionHistoryPane();
                }
            } catch (e) {
                console.warn('Automations canvas init warning:', e);
            }
            renderAutomationsCanvasAll();
            if (!automationsCanvasLivePollTimer) {
                automationsCanvasLivePollTimer = setInterval(pollAutomationsCanvasLiveExecutions, 3000);
            }
        }

        async function pollAutomationsCanvasLiveExecutions() {
            if (typeof activeTab !== 'undefined' && activeTab !== 'automations') return;
            try {
                const res = await fetch('/api/automations/workflows');
                const data = await res.json();
                if (data.status === 'success' && Array.isArray(data.execution_history)) {
                    automationsCanvasExecutionHistory = data.execution_history;
                    const latest = automationsCanvasExecutionHistory[0];
                    if (latest && latest.execution_id && String(latest.execution_id) !== automationsCanvasLastSeenExecId) {
                        automationsCanvasLastSeenExecId = String(latest.execution_id);
                        if (automationsCanvasCurrentJson && Array.isArray(latest.trace)) {
                            automationsCanvasLastTraceByNode = {};
                            latest.trace.forEach(step => {
                                automationsCanvasLastTraceByNode[step.node_name] = step;
                            });
                            const summaryEl = document.getElementById('auto-canvas-last-trace-summary');
                            if (summaryEl) {
                                const badgeColor = latest.status === 'success' ? 'text-emerald-300' : 'text-rose-300';
                                summaryEl.innerHTML = `
                                    <span class="${badgeColor} font-extrabold">● Live Run (${escapeHtml(latest.event_type)}): ${latest.steps_count} nodes executed in ${latest.duration_ms}ms</span>
                                    <span class="text-slate-400">• ${(latest.trace || []).map(t => `${escapeHtml(t.node_name)} (${t.status === 'success' ? '✓' : '✕'})`).join(' → ')}</span>
                                `;
                            }
                            renderAutomationsCanvasNodesAndEdges();
                        }
                        renderAutomationsExecutionHistoryPane();
                        if (!latest.is_test_run) {
                            showToast(`⚡ Live Automation Triggered (${latest.event_type}): "${latest.workflow_name}"!`);
                        }
                    }
                }
            } catch (_) {}
        }

        function syncAutomationsDeleteWorkflowButtons() {
            const sel = document.getElementById('auto-canvas-saved-wf-select');
            const selectedId = String(automationsCanvasCurrentId || (sel && sel.value) || '').trim();
            const hasSavedSelection = Boolean(selectedId);
            const delBtn = document.getElementById('auto-canvas-delete-wf-btn');
            const toolbarDelBtn = document.getElementById('auto-canvas-toolbar-delete-wf-btn');
            const fsDelBtn = document.getElementById('auto-canvas-fs-delete-wf-btn');
            if (delBtn) delBtn.disabled = !hasSavedSelection;
            if (toolbarDelBtn) {
                toolbarDelBtn.disabled = !hasSavedSelection;
                toolbarDelBtn.classList.toggle('opacity-40', !hasSavedSelection);
                toolbarDelBtn.classList.toggle('pointer-events-none', !hasSavedSelection);
            }
            if (fsDelBtn) {
                fsDelBtn.disabled = !hasSavedSelection;
                fsDelBtn.classList.toggle('opacity-40', !hasSavedSelection);
                fsDelBtn.classList.toggle('pointer-events-none', !hasSavedSelection);
            }
        }

        function renderAutomationsSavedWorkflowSelect() {
            const sel = document.getElementById('auto-canvas-saved-wf-select');
            if (!sel) return;
            let html = `<option value="">-- Blank Canvas (Locked / No .JSON) --</option>`;
            automationsCanvasSavedWorkflows.forEach(wf => {
                const isSel = automationsCanvasCurrentId && String(wf.id) === String(automationsCanvasCurrentId) ? 'selected' : '';
                const stTag = wf.active ? '🟢 ACTIVE' : '⏸️ PAUSED';
                html += `<option value="${escapeHtml(String(wf.id))}" ${isSel}>${escapeHtml(wf.name || 'Workflow')} (${stTag})</option>`;
            });
            sel.innerHTML = html;
            syncAutomationsDeleteWorkflowButtons();
        }

        function loadSavedAutomationWorkflowFromSelect(wfId) {
            if (!wfId) {
                clearAutomationsCanvasToBlankLocked();
                return;
            }
            const found = automationsCanvasSavedWorkflows.find(w => String(w.id) === String(wfId));
            if (found && found.workflow_json) {
                unlockAndLoadJsonIntoAutomationsCanvas(found.workflow_json, {
                    id: found.id,
                    name: found.name || found.workflow_json.name || 'Automation Workflow',
                    active: Boolean(found.active)
                });
            }
            syncAutomationsDeleteWorkflowButtons();
        }

        function clearAutomationsCanvasToBlankLocked() {
            automationsCanvasCurrentId = '';
            automationsCanvasCurrentJson = null;
            automationsCanvasSelectedNodeName = '';
            automationsCanvasLastTraceByNode = {};
            const sel = document.getElementById('auto-canvas-saved-wf-select');
            if (sel) sel.value = '';
            renderAutomationsCanvasAll();
            showToast('🔒 Automations Canvas reset to Blank Locked state.');
        }

        function unlockAndLoadJsonIntoAutomationsCanvas(rawWorkflowObj, meta = {}) {
            let wfObj = rawWorkflowObj;
            try {
                wfObj = parseFlexibleN8nWorkflowJson(rawWorkflowObj);
            } catch (e) {
                alert('Invalid JSON object: ' + (e.message || e));
                return false;
            }
            if (!wfObj || typeof wfObj !== 'object') {
                alert('Invalid JSON object.');
                return false;
            }
            const wfJson = JSON.parse(JSON.stringify(wfObj));

            if (!Array.isArray(wfJson.nodes)) {
                alert('Ang uploaded .JSON ay walang valid n8n "nodes" array. Mag-upload ng .JSON galing sa Ask AI o n8n.');
                return false;
            }
            if (!wfJson.connections || typeof wfJson.connections !== 'object') {
                wfJson.connections = {};
            }
            // Ensure every node has position [x, y] and a unique name
            wfJson.nodes.forEach((n, idx) => {
                if (!n.id) n.id = 'node_' + idx + '_' + Date.now();
                if (!n.name) n.name = 'Node ' + (idx + 1);
                if (!Array.isArray(n.position) || n.position.length < 2) {
                    n.position = [120 + idx * 290, 220];
                }
                if (!n.parameters || typeof n.parameters !== 'object') {
                    n.parameters = {};
                }
            });

            automationsCanvasCurrentId = meta.id || wfJson.id || '';
            wfJson.name = meta.name || wfJson.name || 'Imported n8n Automation';
            automationsCanvasIsActive = meta.active !== undefined ? Boolean(meta.active) : Boolean(wfJson.active ?? true);
            wfJson.active = automationsCanvasIsActive;
            automationsCanvasCurrentJson = wfJson;
            automationsCanvasLastTraceByNode = {};
            automationsCanvasSelectedNodeName = wfJson.nodes.length > 0 ? wfJson.nodes[0].name : '';

            // Reset viewport so all nodes are cleanly centered and fitted
            if (wfJson.nodes.length > 0) {
                const minX = Math.min(...wfJson.nodes.map(n => Number(n.position[0]) || 0));
                const minY = Math.min(...wfJson.nodes.map(n => Number(n.position[1]) || 0));
                automationsCanvasZoom = 0.92;
                automationsCanvasPanX = Math.max(24, 60 - minX * 0.92);
                automationsCanvasPanY = Math.max(24, 60 - minY * 0.92);
            }

            renderAutomationsCanvasAll();
            setTimeout(() => fitAutomationsCanvasNodesToViewport(), 35);
            return true;
        }

        async function handleAutomationsCanvasFileUpload(inputEl) {
            const file = inputEl && inputEl.files && inputEl.files[0];
            if (!file) return;
            try {
                const text = await file.text();
                const parsed = parseFlexibleN8nWorkflowJson(text);
                // Also run backend credential injection so X-API-Key & live /api/v1/* URLs are up-to-date
                let patched = parsed;
                try {
                    const r = await fetch('/api/internal-api/n8n-workflows/analyze', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ workflow_json: parsed })
                    });
                    const d = await r.json();
                    if (d.status === 'success' && d.patched_workflow_json && Array.isArray(d.patched_workflow_json.nodes)) {
                        patched = d.patched_workflow_json;
                    }
                } catch (_) {}

                const fallbackName = file.name.replace(/\.json$/i, '');
                if (unlockAndLoadJsonIntoAutomationsCanvas(patched, { name: patched.name || fallbackName, active: true })) {
                    await saveCurrentAutomationsCanvasWorkflow(true);
                    showToast(`🔓 Unlocked & Activated "${patched.name || fallbackName}" (${(patched.nodes || []).length} nodes) in Production Mode!`);
                }
            } catch (e) {
                console.error('Automations Canvas JSON upload error:', e);
                alert('Failed to parse .JSON file: ' + (e.message || e));
            } finally {
                inputEl.value = '';
            }
        }

        async function openPasteAutomationJsonPrompt() {
            const raw = prompt('Paste your n8n Workflow .JSON (from Ask AI or n8n) below to unlock the Automations Canvas:');
            if (!raw || !raw.trim()) return;
            try {
                const parsed = parseFlexibleN8nWorkflowJson(raw);
                if (unlockAndLoadJsonIntoAutomationsCanvas(parsed, { name: parsed.name || 'Pasted n8n Workflow', active: true })) {
                    await saveCurrentAutomationsCanvasWorkflow(true);
                    showToast('🔓 Unlocked & Activated pasted .JSON in Production Mode!');
                }
            } catch (e) {
                alert('Invalid JSON format: ' + (e.message || e));
            }
        }

        async function openAiGeneratedWorkflowInAutomationsCanvas() {
            const codeEl = document.getElementById('ask-ai-n8n-json-code');
            const nameEl = document.getElementById('ask-ai-n8n-wf-name');
            const rawText = codeEl ? codeEl.value.trim() : '';
            if (!rawText) {
                alert('Mag-generate muna ng .JSON workflow gamit ang Ask AI bago buksan sa Automations Canvas.');
                return;
            }
            try {
                const parsed = parseFlexibleN8nWorkflowJson(rawText);
                const wfName = (nameEl && nameEl.textContent.trim()) || parsed.name || 'AI Generated Automation';
                closeAskAiN8nModal();
                switchTab('automations');
                if (unlockAndLoadJsonIntoAutomationsCanvas(parsed, { name: wfName, active: true })) {
                    await saveCurrentAutomationsCanvasWorkflow(true);
                    showToast(`🔓 Loaded & Activated "${wfName}" from Ask AI in Production Mode!`);
                }
            } catch (e) {
                alert('Invalid JSON in Ask AI output: ' + (e.message || e));
            }
        }

        function loadSavvyFindsPresetIntoAutomationsCanvas() {
            const presetJson = {
                "name": "Savvy Finds Comment & Page Reply Thread Logger (Single Row per Conversation)",
                "nodes": [
                    {
                        "parameters": {
                            "httpMethod": "POST",
                            "path": "savvy-finds-comment-logger",
                            "responseMode": "onReceived",
                            "options": {}
                        },
                        "id": "node-webhook-trigger",
                        "name": "Webhook Trigger",
                        "type": "n8n-nodes-base.webhook",
                        "typeVersion": 2,
                        "position": [120, 240],
                        "webhookId": "savvy-finds-comment-logger"
                    },
                    {
                        "parameters": {
                            "conditions": {
                                "string": [
                                    {
                                        "value1": "={{ $json.body.account_name || $json.account_name || '' }}",
                                        "operation": "contains",
                                        "value2": "Savvy Finds"
                                    },
                                    {
                                        "value1": "={{ $json.body.platform || $json.platform || '' }}",
                                        "operation": "contains",
                                        "value2": "facebook"
                                    }
                                ],
                                "boolean": [
                                    {
                                        "value1": "={{ Boolean(!($json.body.is_own_comment ?? $json.is_own_comment) || ($json.body.is_reply_to_comment ?? $json.is_reply_to_comment) || ($json.body.parent_comment_id ?? $json.parent_comment_id)) }}",
                                        "value2": true
                                    }
                                ]
                            },
                            "combineOperation": "all"
                        },
                        "id": "node-filter-savvy-finds",
                        "name": "Filter Savvy Finds FB Comments",
                        "type": "n8n-nodes-base.if",
                        "typeVersion": 1,
                        "position": [430, 240]
                    },
                    {
                        "parameters": {
                            "method": "GET",
                            "url": "={{ window.location.origin + '/api/v1/spreadsheets/read?workbook_id=file_011d8d793a98&sheet_name=Sheet1&sync_gdrive=false' }}",
                            "sendHeaders": true,
                            "headerParameters": {
                                "parameters": [
                                    { "name": "X-API-Key", "value": "gb_live_99b6d02bdd6093ac7d58fb09c034ee05b04b" }
                                ]
                            },
                            "options": {}
                        },
                        "id": "node-read-sheet",
                        "name": "Read Existing Sheet1 Rows",
                        "type": "n8n-nodes-base.httpRequest",
                        "typeVersion": 4.2,
                        "position": [740, 240]
                    },
                    {
                        "parameters": {
                            "jsCode": "const wb = $('Webhook Trigger').first().json.body || $('Webhook Trigger').first().json || {};\nconst sheetResp = $input.first().json || {};\nconst existingRows = Array.isArray(sheetResp.rows) ? sheetResp.rows : [];\nconst norm = (id) => { const s = String(id || '').trim(); return s.includes('_') ? s.split('_').slice(1).join('_') : s; };\nconst cid = String(wb.comment_id || '').trim();\nconst parentCid = String(wb.parent_comment_id || wb.replied_to_id || '').trim();\nconst threadId = norm(wb.thread_id || wb.root_comment_id || parentCid || cid) || 'unknown_thread';\nconst threadTag = `[Thread: ${threadId}]`;\nconst isOwn = Boolean(wb.is_own_comment);\nconst commenterId = String(isOwn ? (wb.parent_author_id || wb.author_id || '') : (wb.author_id || wb.author_name || 'Commenter')).trim();\nconst commenterName = String(isOwn ? (wb.parent_author_name || 'Commenter') : (wb.author_name || 'Commenter')).trim();\nconst speaker = isOwn ? 'Savvy Finds (Page)' : commenterName;\nconst newLine = `${speaker}: ${String(wb.message || '').trim()}`;\nlet matchedRowNumber = null;\nlet existingColB = '';\nfor (const r of existingRows) {\n  if (!r || Number(r.row_number) <= 1) continue;\n  const aVal = String((r.values || {}).A || '').trim();\n  const bVal = String((r.values || {}).B || '').trim();\n  if (aVal.includes(threadTag)) { matchedRowNumber = Number(r.row_number); existingColB = bVal; break; }\n}\nconst targetRowNumber = matchedRowNumber !== null ? matchedRowNumber : Math.max(2, existingRows.length + 1);\nconst finalColA = `${commenterId} ${threadTag}`.trim();\nconst rawTranscript = wb.thread_transcript ? String(wb.thread_transcript).trim().replace(/\\r?\\n+/g, '  |  ') : '';\nconst finalColB = rawTranscript ? rawTranscript : (existingColB ? (existingColB.includes(newLine) ? existingColB : `${existingColB}  |  ${newLine}`) : newLine);\nreturn [{ json: { targetRowNumber, threadId, colA: finalColA, colB: finalColB } }];"
                        },
                        "id": "node-group-thread-code",
                        "name": "Group Thread & Find Matching Row",
                        "type": "n8n-nodes-base.code",
                        "typeVersion": 2,
                        "position": [1050, 240]
                    },
                    {
                        "parameters": {
                            "method": "POST",
                            "url": "={{ window.location.origin + '/api/v1/spreadsheets/append-row' }}",
                            "sendHeaders": true,
                            "headerParameters": {
                                "parameters": [
                                    { "name": "X-API-Key", "value": "gb_live_99b6d02bdd6093ac7d58fb09c034ee05b04b" },
                                    { "name": "Content-Type", "value": "application/json" }
                                ]
                            },
                            "sendBody": true,
                            "specifyBody": "json",
                            "jsonBody": "={{ JSON.stringify({ workbook_id: 'file_011d8d793a98', sheet_name: 'Sheet1', row_number: $json.targetRowNumber, thread_id: $json.threadId, row: { A: $json.colA, B: $json.colB } }) }}",
                            "options": {}
                        },
                        "id": "node-upsert-thread-row",
                        "name": "Upsert Single-Row Thread in Conversations.xlsx",
                        "type": "n8n-nodes-base.httpRequest",
                        "typeVersion": 4.2,
                        "position": [1360, 240]
                    }
                ],
                "connections": {
                    "Webhook Trigger": {
                        "main": [[{ "node": "Filter Savvy Finds FB Comments", "type": "main", "index": 0 }]]
                    },
                    "Filter Savvy Finds FB Comments": {
                        "main": [[{ "node": "Read Existing Sheet1 Rows", "type": "main", "index": 0 }]]
                    },
                    "Read Existing Sheet1 Rows": {
                        "main": [[{ "node": "Group Thread & Find Matching Row", "type": "main", "index": 0 }]]
                    },
                    "Group Thread & Find Matching Row": {
                        "main": [[{ "node": "Upsert Single-Row Thread in Conversations.xlsx", "type": "main", "index": 0 }]]
                    }
                },
                "active": true,
                "settings": { "executionOrder": "v1" }
            };
            if (unlockAndLoadJsonIntoAutomationsCanvas(presetJson, {
                name: presetJson.name,
                active: true
            })) {
                saveCurrentAutomationsCanvasWorkflow(true);
            }
            showToast('🔓 Loaded & Activated Savvy Finds Single-Row Thread Grouping .JSON in Production Mode!');
        }

        function getAutomationsNodeVisualMeta(nodeType) {
            const t = String(nodeType || '').toLowerCase();
            if (t.includes('webhook') || t.includes('trigger') || t.includes('manual')) {
                return {
                    category: 'DASHBOARD TRIGGER (WEBHOOK)',
                    icon: 'fa-bolt',
                    badgeBg: 'rgba(0, 240, 255, 0.16)',
                    borderColor: 'rgba(0, 240, 255, 0.65)',
                    accentColor: '#00f0ff',
                    isIf: false,
                    isTrigger: true
                };
            }
            if (t.endsWith('.if') || t.endsWith('.filter') || t === 'if') {
                return {
                    category: 'IF / CONDITION',
                    icon: 'fa-code-branch',
                    badgeBg: 'rgba(245, 158, 11, 0.18)',
                    borderColor: 'rgba(245, 158, 11, 0.65)',
                    accentColor: '#fbbf24',
                    isIf: true,
                    isTrigger: false
                };
            }
            if (t.endsWith('.wait') || t === 'wait') {
                return {
                    category: 'WAIT TIMER',
                    icon: 'fa-hourglass-half',
                    badgeBg: 'rgba(56, 189, 248, 0.18)',
                    borderColor: 'rgba(56, 189, 248, 0.65)',
                    accentColor: '#38bdf8',
                    isIf: false,
                    isTrigger: false
                };
            }
            if (t.endsWith('.code') || t.endsWith('.function') || t === 'code') {
                return {
                    category: 'CODE (JS / PYTHON)',
                    icon: 'fa-code',
                    badgeBg: 'rgba(168, 85, 247, 0.18)',
                    borderColor: 'rgba(168, 85, 247, 0.65)',
                    accentColor: '#c084fc',
                    isIf: false,
                    isTrigger: false
                };
            }
            if (t.includes('httprequest') || t === 'http') {
                return {
                    category: 'HTTP / GLENNBOT API',
                    icon: 'fa-globe',
                    badgeBg: 'rgba(16, 185, 129, 0.18)',
                    borderColor: 'rgba(16, 185, 129, 0.65)',
                    accentColor: '#34d399',
                    isIf: false,
                    isTrigger: false
                };
            }
            if (t.endsWith('.set') || t === 'set') {
                return {
                    category: 'SET / EDIT FIELDS',
                    icon: 'fa-pen-fancy',
                    badgeBg: 'rgba(236, 72, 153, 0.18)',
                    borderColor: 'rgba(236, 72, 153, 0.65)',
                    accentColor: '#f472b6',
                    isIf: false,
                    isTrigger: false
                };
            }
            return {
                category: 'GENERIC N8N NODE',
                icon: 'fa-cube',
                badgeBg: 'rgba(148, 163, 184, 0.16)',
                borderColor: 'rgba(148, 163, 184, 0.5)',
                accentColor: '#cbd5e1',
                isIf: false,
                isTrigger: false
            };
        }

        function summarizeAutomationsNodeSubtitle(node) {
            const t = String(node.type || '').toLowerCase();
            const p = node.parameters || {};
            if (t.includes('webhook') || t.includes('trigger')) {
                const path = p.path || node.webhookId || 'dashboard-event';
                return `In-Dashboard Event Bridge (/webhook/${path})`;
            }
            if (t.endsWith('.if') || t.endsWith('.filter')) {
                const c = p.conditions || {};
                const sCount = (c.string || []).length + (c.boolean || []).length + (c.number || []).length + (c.conditions || []).length;
                const comb = p.combineOperation || c.combinator || 'all';
                return `${sCount} condition(s) • Combine: ${String(comb).toUpperCase()}`;
            }
            if (t.endsWith('.wait')) {
                return `Wait ${p.amount || 1} ${p.unit || 'minutes'} before next node`;
            }
            if (t.endsWith('.code') || t.endsWith('.function')) {
                const code = String(p.jsCode || p.functionCode || '').trim();
                const lines = code ? code.split('\n').length : 0;
                return `JavaScript transformation (${lines} lines)`;
            }
            if (t.includes('httprequest')) {
                const m = String(p.method || 'GET').toUpperCase();
                const u = String(p.url || '').replace(/^=/, '');
                const shortPath = (u.match(/\/api\/v1\/[^\s"'?]+/) || [u.slice(0, 34)])[0];
                return `${m} ${shortPath}`;
            }
            return String(node.type || 'n8n-node');
        }

        function renderAutomationsCanvasAll() {
            const isUnlocked = Boolean(automationsCanvasCurrentJson && Array.isArray(automationsCanvasCurrentJson.nodes));
            const overlay = document.getElementById('auto-canvas-locked-overlay');
            const toolbar = document.getElementById('auto-canvas-editing-toolbar');
            const statusPill = document.getElementById('auto-canvas-status-pill');
            const sidebarBadge = document.getElementById('automations-canvas-lock-badge');
            const autoLayoutBtn = document.getElementById('auto-canvas-autolayout-btn');
            const nameInput = document.getElementById('auto-canvas-wf-name-input');
            const bridgeInfo = document.getElementById('auto-canvas-trigger-bridge-info');
            const rawJsonArea = document.getElementById('auto-inspector-raw-json-textarea');

            if (overlay) overlay.classList.toggle('hidden', isUnlocked);
            if (toolbar) {
                toolbar.classList.toggle('opacity-45', !isUnlocked);
                toolbar.classList.toggle('pointer-events-none', !isUnlocked);
                toolbar.classList.toggle('select-none', !isUnlocked);
            }
            if (autoLayoutBtn) autoLayoutBtn.disabled = !isUnlocked;

            const fsNameInput = document.getElementById('auto-canvas-fs-name-input');
            const fsAddNodesGroup = document.getElementById('auto-canvas-fs-add-nodes-group');
            if (fsAddNodesGroup) {
                fsAddNodesGroup.classList.toggle('opacity-40', !isUnlocked);
                fsAddNodesGroup.classList.toggle('pointer-events-none', !isUnlocked);
            }
            syncAutomationsDeleteWorkflowButtons();

            if (!isUnlocked) {
                if (statusPill) {
                    statusPill.className = 'px-2.5 py-0.5 rounded-full text-[10px] font-extrabold uppercase tracking-wider bg-rose-500/20 text-rose-300 border border-rose-500/40 flex items-center gap-1.5';
                    statusPill.innerHTML = `<i class="fas fa-lock text-[9px]"></i><span>Blank Canvas (Locked — Upload .JSON or Ask AI)</span>`;
                }
                if (sidebarBadge) {
                    sidebarBadge.className = 'bg-slate-800 text-slate-400 border border-slate-700 px-2 py-0.5 rounded-full text-[10px] font-bold';
                    sidebarBadge.textContent = 'LOCKED';
                }
                if (nameInput) nameInput.value = '';
                if (fsNameInput) fsNameInput.value = '';
                if (bridgeInfo) bridgeInfo.textContent = 'No .JSON loaded — Upload or Ask AI to bind internal dashboard events';
                if (rawJsonArea) rawJsonArea.value = '';
                const nodesLayer = document.getElementById('auto-canvas-nodes-layer');
                const edgesSvg = document.getElementById('auto-canvas-edges-svg');
                if (nodesLayer) nodesLayer.innerHTML = '';
                if (edgesSvg) edgesSvg.innerHTML = '';
                const countBadge = document.getElementById('auto-canvas-node-count-badge');
                if (countBadge) countBadge.textContent = '0 nodes • 0 connections';
                renderAutomationsNodeInspector();
                return;
            }

            const wf = automationsCanvasCurrentJson;
            const nodes = wf.nodes || [];
            if (statusPill) {
                statusPill.className = 'px-2.5 py-0.5 rounded-full text-[10px] font-extrabold uppercase tracking-wider bg-emerald-500/20 text-emerald-300 border border-emerald-400/50 flex items-center gap-1.5';
                statusPill.innerHTML = `<i class="fas fa-unlock text-[9px]"></i><span>Canvas Unlocked (${nodes.length} Nodes)</span>`;
            }
            if (sidebarBadge) {
                sidebarBadge.className = 'bg-purple-500/20 text-purple-300 border border-purple-400/50 px-2 py-0.5 rounded-full text-[10px] font-bold';
                sidebarBadge.textContent = `${nodes.length} NODES`;
            }
            if (nameInput && document.activeElement !== nameInput) {
                nameInput.value = wf.name || 'Automation Workflow';
            }
            if (fsNameInput && document.activeElement !== fsNameInput) {
                fsNameInput.value = wf.name || 'Automation Workflow';
            }

            // Update Active Toggle UI (Both normal & fullscreen floating buttons)
            const toggleBtn = document.getElementById('auto-canvas-active-toggle-btn');
            const toggleDot = document.getElementById('auto-canvas-active-dot');
            const toggleLbl = document.getElementById('auto-canvas-active-label');
            const fsToggleBtn = document.getElementById('auto-canvas-fs-active-btn');
            const fsToggleDot = document.getElementById('auto-canvas-fs-active-dot');
            const fsToggleLbl = document.getElementById('auto-canvas-fs-active-label');
            if (toggleBtn && toggleDot && toggleLbl) {
                if (automationsCanvasIsActive) {
                    toggleBtn.className = 'px-3 py-1.5 rounded-xl bg-emerald-500/20 border border-emerald-400/50 text-emerald-300 text-xs font-extrabold flex items-center gap-1.5 transition-all cursor-pointer';
                    toggleDot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-pulse';
                    toggleLbl.textContent = 'ACTIVE IN DASHBOARD';
                } else {
                    toggleBtn.className = 'px-3 py-1.5 rounded-xl bg-slate-800 border border-slate-600 text-slate-400 text-xs font-extrabold flex items-center gap-1.5 transition-all cursor-pointer';
                    toggleDot.className = 'w-2 h-2 rounded-full bg-slate-500';
                    toggleLbl.textContent = 'PAUSED';
                }
            }
            if (fsToggleBtn && fsToggleDot && fsToggleLbl) {
                if (automationsCanvasIsActive) {
                    fsToggleBtn.className = 'px-2.5 py-1 rounded-xl bg-emerald-500/20 border border-emerald-400/50 text-emerald-300 text-[11px] font-extrabold flex items-center gap-1.5 cursor-pointer';
                    fsToggleDot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-pulse';
                    fsToggleLbl.textContent = 'ACTIVE';
                } else {
                    fsToggleBtn.className = 'px-2.5 py-1 rounded-xl bg-slate-800 border border-slate-600 text-slate-400 text-[11px] font-extrabold flex items-center gap-1.5 cursor-pointer';
                    fsToggleDot.className = 'w-2 h-2 rounded-full bg-slate-500';
                    fsToggleLbl.textContent = 'PAUSED';
                }
            }

            // Update Dashboard Webhook Bridge Info
            const whNode = nodes.find(n => String(n.type || '').toLowerCase().includes('webhook'));
            if (bridgeInfo) {
                if (whNode) {
                    const whPath = (whNode.parameters && whNode.parameters.path) || whNode.webhookId || 'auto-trigger';
                    bridgeInfo.innerHTML = `<span class="text-emerald-300 font-bold">● Native In-Dashboard Trigger</span> • Node <strong class="text-white">"${escapeHtml(whNode.name)}"</strong> listens directly to GlennBot events + n8n path <code class="text-gb-cyan">/webhook/${escapeHtml(whPath)}</code>`;
                } else {
                    bridgeInfo.textContent = 'Manual / Custom Trigger active inside GlennBot Dashboard';
                }
            }

            if (rawJsonArea && document.activeElement !== rawJsonArea) {
                rawJsonArea.value = JSON.stringify(wf, null, 2);
            }

            applyAutomationsCanvasTransform();
            renderAutomationsCanvasNodesAndEdges();
            renderAutomationsNodeInspector();
        }

        function applyAutomationsCanvasTransform() {
            const stage = document.getElementById('auto-canvas-stage');
            const zoomLbl = document.getElementById('auto-canvas-zoom-label');
            const fsZoomLbl = document.getElementById('auto-canvas-fs-zoom-label');
            if (stage) {
                stage.style.transform = `translate(${Math.round(automationsCanvasPanX)}px, ${Math.round(automationsCanvasPanY)}px) scale(${automationsCanvasZoom.toFixed(2)})`;
            }
            const pctText = `${Math.round(automationsCanvasZoom * 100)}%`;
            if (zoomLbl) zoomLbl.textContent = pctText;
            if (fsZoomLbl) fsZoomLbl.textContent = pctText;
        }

        function zoomAutomationsCanvas(delta) {
            automationsCanvasZoom = Math.min(1.8, Math.max(0.35, automationsCanvasZoom + delta));
            applyAutomationsCanvasTransform();
        }

        function onAutomationsCanvasWheel(e) {
            if (!automationsCanvasCurrentJson) return;
            e.preventDefault();
            const delta = e.deltaY < 0 ? 0.08 : -0.08;
            zoomAutomationsCanvas(delta);
        }

        function resetAutomationsCanvasViewport() {
            fitAutomationsCanvasNodesToViewport();
        }

        function fitAutomationsCanvasNodesToViewport() {
            const viewport = document.getElementById('auto-canvas-viewport');
            const nodes = (automationsCanvasCurrentJson && automationsCanvasCurrentJson.nodes) || [];
            if (!viewport || nodes.length === 0) {
                automationsCanvasZoom = 0.95;
                automationsCanvasPanX = 40;
                automationsCanvasPanY = automationsCanvasIsFullscreen ? 95 : 40;
                applyAutomationsCanvasTransform();
                return;
            }
            const CARD_W = 244;
            const CARD_H = 108;
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            nodes.forEach(n => {
                const x = Number(n.position && n.position[0]) || 0;
                const y = Number(n.position && n.position[1]) || 0;
                if (x < minX) minX = x;
                if (y < minY) minY = y;
                if (x + CARD_W > maxX) maxX = x + CARD_W;
                if (y + CARD_H > maxY) maxY = y + CARD_H;
            });
            const graphW = Math.max(300, maxX - minX);
            const graphH = Math.max(160, maxY - minY);
            const rect = viewport.getBoundingClientRect();
            const vw = Math.max(400, rect.width || window.innerWidth);
            const vh = Math.max(300, rect.height || window.innerHeight);

            const topPad = automationsCanvasIsFullscreen ? 96 : 48;
            const bottomPad = automationsCanvasIsFullscreen ? 72 : 48;
            const rightPad = (automationsCanvasIsFullscreen && automationsCanvasFloatingDrawerOpen) ? 450 : 60;
            const leftPad = 60;

            const availW = Math.max(260, vw - leftPad - rightPad);
            const availH = Math.max(180, vh - topPad - bottomPad);
            const scaleX = availW / graphW;
            const scaleY = availH / graphH;
            automationsCanvasZoom = Math.min(1.15, Math.max(0.42, Math.min(scaleX, scaleY)));

            automationsCanvasPanX = Math.round(leftPad + (availW - graphW * automationsCanvasZoom) / 2 - minX * automationsCanvasZoom);
            automationsCanvasPanY = Math.round(topPad + (availH - graphH * automationsCanvasZoom) / 2 - minY * automationsCanvasZoom);
            applyAutomationsCanvasTransform();
        }

        function autoLayoutAutomationsCanvasNodes() {
            if (!automationsCanvasCurrentJson || !Array.isArray(automationsCanvasCurrentJson.nodes)) return;
            automationsCanvasCurrentJson.nodes.forEach((n, idx) => {
                n.position = [100 + idx * 300, 220 + (idx % 2 === 1 ? 28 : 0)];
            });
            renderAutomationsCanvasNodesAndEdges();
            fitAutomationsCanvasNodesToViewport();
            syncRawJsonTextareaFromCanvas();
        }

        function toggleAutomationsCanvasFullscreen(forceState) {
            automationsCanvasIsFullscreen = typeof forceState === 'boolean' ? forceState : !automationsCanvasIsFullscreen;
            const mainCard = document.getElementById('auto-canvas-main-card');
            const normalSubbar = document.getElementById('auto-canvas-normal-subbar');
            const floatingHud = document.getElementById('auto-canvas-floating-hud');
            const traceFooter = document.getElementById('auto-canvas-trace-footer');
            const inspectorPanel = document.getElementById('auto-canvas-inspector-panel');
            const closeDrawerBtn = document.getElementById('auto-insp-close-floating-btn');

            if (!mainCard) return;

            if (automationsCanvasIsFullscreen) {
                // Fullscreen Canvas Mode: 100vw x 100vh edge-to-edge canvas + floating glass controls
                mainCard.className = 'fixed inset-0 z-[9990] w-screen h-screen bg-[#060b16] overflow-hidden flex flex-col';
                mainCard.style.height = '100vh';
                if (normalSubbar) normalSubbar.classList.add('hidden');
                if (floatingHud) floatingHud.classList.remove('hidden');
                if (traceFooter) {
                    traceFooter.className = 'absolute bottom-3 left-4 right-4 px-4 py-2 rounded-2xl bg-slate-950/88 backdrop-blur-xl border border-slate-700/80 shadow-[0_10px_35px_rgba(0,0,0,0.75)] text-[11px] text-slate-300 flex flex-wrap items-center justify-between gap-2 z-40 pointer-events-auto';
                }
                if (closeDrawerBtn) {
                    closeDrawerBtn.classList.remove('hidden');
                    closeDrawerBtn.classList.add('flex');
                }
                // Start with pure unobstructed canvas by default; user can click any node or click "Inspector / Logs"
                automationsCanvasFloatingDrawerOpen = false;
                syncAutomationsCanvasFloatingDrawerUI();
                setTimeout(() => fitAutomationsCanvasNodesToViewport(), 40);
                showToast('⛶ Fullscreen Canvas Mode active! Click any node to open floating settings, or press ESC to exit.');
            } else {
                // Restore Normal Dashboard Split Mode (Auto-fits full monitor height)
                mainCard.className = 'xl:col-span-8 glass-panel rounded-2xl border border-slate-800 overflow-hidden relative flex flex-col min-h-[540px] lg:h-full';
                mainCard.style.height = '';
                if (normalSubbar) normalSubbar.classList.remove('hidden');
                if (floatingHud) floatingHud.classList.add('hidden');
                if (traceFooter) {
                    traceFooter.className = 'px-4 py-2 bg-slate-950/95 border-t border-slate-800 text-[11px] text-slate-400 flex flex-wrap items-center justify-between gap-2 z-30';
                }
                if (closeDrawerBtn) {
                    closeDrawerBtn.classList.add('hidden');
                    closeDrawerBtn.classList.remove('flex');
                }
                if (inspectorPanel) {
                    inspectorPanel.className = 'xl:col-span-4 glass-panel rounded-2xl border border-slate-800 flex flex-col overflow-hidden min-h-[540px] lg:h-full';
                    inspectorPanel.style.height = '';
                }
                setTimeout(() => fitAutomationsCanvasNodesToViewport(), 40);
            }
        }

        function toggleAutomationsCanvasFloatingDrawer(forceOpen) {
            if (!automationsCanvasIsFullscreen) return;
            automationsCanvasFloatingDrawerOpen = typeof forceOpen === 'boolean' ? forceOpen : !automationsCanvasFloatingDrawerOpen;
            syncAutomationsCanvasFloatingDrawerUI();
        }

        function syncAutomationsCanvasFloatingDrawerUI() {
            const inspectorPanel = document.getElementById('auto-canvas-inspector-panel');
            const drawerBtn = document.getElementById('auto-canvas-fs-drawer-btn');
            if (!inspectorPanel || !automationsCanvasIsFullscreen) return;

            if (automationsCanvasFloatingDrawerOpen) {
                inspectorPanel.className = 'fixed top-16 right-4 bottom-16 w-[410px] max-w-[92vw] z-[9995] rounded-2xl bg-slate-950/92 backdrop-blur-2xl border border-purple-500/50 shadow-[0_20px_70px_rgba(0,0,0,0.9)] flex flex-col overflow-hidden';
                inspectorPanel.style.height = 'auto';
                if (drawerBtn) {
                    drawerBtn.className = 'px-2.5 py-1 rounded-xl bg-purple-500/30 border border-purple-400 text-white text-[11px] font-extrabold flex items-center gap-1.5 cursor-pointer shadow-[0_0_15px_rgba(168,85,247,0.4)]';
                }
            } else {
                inspectorPanel.className = 'hidden';
                if (drawerBtn) {
                    drawerBtn.className = 'px-2.5 py-1 rounded-xl bg-slate-900 hover:bg-purple-500/25 border border-purple-400/50 text-purple-200 text-[11px] font-bold flex items-center gap-1.5 cursor-pointer';
                }
            }
        }

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && automationsCanvasIsFullscreen) {
                if (automationsCanvasFloatingDrawerOpen) {
                    toggleAutomationsCanvasFloatingDrawer(false);
                } else {
                    toggleAutomationsCanvasFullscreen(false);
                }
            }
        });

        function renderAutomationsCanvasNodesAndEdges() {
            const nodesLayer = document.getElementById('auto-canvas-nodes-layer');
            const edgesSvg = document.getElementById('auto-canvas-edges-svg');
            const countBadge = document.getElementById('auto-canvas-node-count-badge');
            if (!nodesLayer || !edgesSvg || !automationsCanvasCurrentJson) return;

            const nodes = automationsCanvasCurrentJson.nodes || [];
            const connections = automationsCanvasCurrentJson.connections || {};
            const nodeMap = {};
            nodes.forEach(n => { nodeMap[n.name] = n; });

            const CARD_W = 244;
            const CARD_H = 108;

            // 1. Render SVG Bezier Edges
            let edgeCount = 0;
            let svgHtml = `
                <defs>
                    <marker id="auto-arrow-cyan" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
                        <path d="M0,0 L8,4 L0,8 Z" fill="#00f0ff" />
                    </marker>
                    <marker id="auto-arrow-emerald" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
                        <path d="M0,0 L8,4 L0,8 Z" fill="#34d399" />
                    </marker>
                    <marker id="auto-arrow-rose" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
                        <path d="M0,0 L8,4 L0,8 Z" fill="#fb7185" />
                    </marker>
                </defs>
            `;

            Object.keys(connections).forEach(srcName => {
                const srcNode = nodeMap[srcName];
                if (!srcNode) return;
                const srcMeta = getAutomationsNodeVisualMeta(srcNode.type);
                const mainBranches = (connections[srcName] && connections[srcName].main) || [];
                mainBranches.forEach((branchEdges, branchIdx) => {
                    if (!Array.isArray(branchEdges)) return;
                    branchEdges.forEach(edge => {
                        if (!edge || !edge.node || !nodeMap[edge.node]) return;
                        const dstNode = nodeMap[edge.node];
                        edgeCount++;

                        const x1 = (Number(srcNode.position[0]) || 0) + CARD_W;
                        const y1 = (Number(srcNode.position[1]) || 0) + (srcMeta.isIf ? (branchIdx === 0 ? 38 : 78) : CARD_H / 2);
                        const x2 = (Number(dstNode.position[0]) || 0);
                        const y2 = (Number(dstNode.position[1]) || 0) + CARD_H / 2;

                        const dx = Math.max(60, Math.abs(x2 - x1) * 0.48);
                        const pathD = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;

                        let strokeColor = '#00f0ff';
                        let markerId = 'auto-arrow-cyan';
                        let branchLabel = '';
                        if (srcMeta.isIf) {
                            if (branchIdx === 0) {
                                strokeColor = '#34d399';
                                markerId = 'auto-arrow-emerald';
                                branchLabel = 'TRUE';
                            } else {
                                strokeColor = '#fb7185';
                                markerId = 'auto-arrow-rose';
                                branchLabel = 'FALSE';
                            }
                        }

                        const midX = (x1 + x2) / 2;
                        const midY = (y1 + y2) / 2;

                        svgHtml += `
                            <path d="${pathD}" fill="none" stroke="${strokeColor}" stroke-width="2.5" stroke-opacity="0.82" marker-end="url(#${markerId})" />
                        `;
                        if (branchLabel) {
                            svgHtml += `
                                <rect x="${midX - 22}" y="${midY - 10}" width="44" height="16" rx="6" fill="#0f172a" stroke="${strokeColor}" stroke-width="1" />
                                <text x="${midX}" y="${midY + 1}" text-anchor="middle" fill="${strokeColor}" font-size="9" font-weight="800" font-family="monospace">${branchLabel}</text>
                            `;
                        }
                    });
                });
            });
            edgesSvg.innerHTML = svgHtml;

            // 2. Render Draggable Node Cards
            let nodesHtml = '';
            nodes.forEach((node, idx) => {
                const meta = getAutomationsNodeVisualMeta(node.type);
                const x = Number(node.position[0]) || 0;
                const y = Number(node.position[1]) || 0;
                const isSelected = automationsCanvasSelectedNodeName === node.name;
                const traceInfo = automationsCanvasLastTraceByNode[node.name];
                const subtitle = summarizeAutomationsNodeSubtitle(node);

                let traceBadgeHtml = '';
                let ringStyle = isSelected
                    ? `box-shadow: 0 0 0 2px #fff, 0 0 28px ${meta.accentColor}66; border-color: ${meta.accentColor};`
                    : `border-color: ${meta.borderColor}; box-shadow: 0 10px 25px rgba(0,0,0,0.55);`;

                if (traceInfo) {
                    if (traceInfo.status === 'success') {
                        traceBadgeHtml = `<span class="px-1.5 py-0.5 rounded bg-emerald-500/25 border border-emerald-400/60 text-emerald-300 text-[9px] font-extrabold">✓ ${traceInfo.duration_ms}ms</span>`;
                        if (!isSelected) ringStyle = `border-color: #34d399; box-shadow: 0 0 22px rgba(16,185,129,0.35);`;
                    } else if (traceInfo.status === 'error') {
                        traceBadgeHtml = `<span class="px-1.5 py-0.5 rounded bg-rose-500/25 border border-rose-400/60 text-rose-300 text-[9px] font-extrabold">✕ ERR</span>`;
                        if (!isSelected) ringStyle = `border-color: #fb7185; box-shadow: 0 0 22px rgba(244,63,94,0.35);`;
                    }
                }

                const encodedName = encodeURIComponent(node.name);
                nodesHtml += `
                    <div data-node-name="${encodedName}"
                        onmousedown="onAutomationsNodeMouseDown(event, decodeURIComponent('${encodedName}'))"
                        style="position: absolute; left: ${x}px; top: ${y}px; width: ${CARD_W}px; min-height: ${CARD_H}px; ${ringStyle}"
                        class="rounded-2xl bg-slate-900/95 border p-3 cursor-move transition-shadow select-none flex flex-col justify-between group">

                        <!-- Input Port Dot -->
                        ${!meta.isTrigger ? `
                            <div title="Input Port" style="position:absolute; left:-7px; top:50%; transform:translateY(-50%);" class="w-3.5 h-3.5 rounded-full bg-slate-950 border-2 border-gb-cyan"></div>
                        ` : ''}

                        <!-- Output Port Dot(s) -->
                        ${meta.isIf ? `
                            <div title="TRUE Branch (Index 0)" style="position:absolute; right:-7px; top:38px; transform:translateY(-50%);" class="w-3.5 h-3.5 rounded-full bg-emerald-400 border-2 border-slate-950"></div>
                            <div title="FALSE Branch (Index 1)" style="position:absolute; right:-7px; top:78px; transform:translateY(-50%);" class="w-3.5 h-3.5 rounded-full bg-rose-400 border-2 border-slate-950"></div>
                        ` : `
                            <div title="Output Port" style="position:absolute; right:-7px; top:50%; transform:translateY(-50%);" class="w-3.5 h-3.5 rounded-full bg-gb-cyan border-2 border-slate-950"></div>
                        `}

                        <div>
                            <div class="flex items-center justify-between gap-1.5 mb-1.5">
                                <span style="background:${meta.badgeBg}; color:${meta.accentColor};" class="px-2 py-0.5 rounded-md text-[9px] font-extrabold uppercase tracking-wider flex items-center gap-1">
                                    <i class="fas ${meta.icon}"></i>
                                    <span>${escapeHtml(meta.category)}</span>
                                </span>
                                <div class="flex items-center gap-1">
                                    ${traceBadgeHtml}
                                    <span class="text-[9px] font-mono text-slate-500">#${idx + 1}</span>
                                </div>
                            </div>
                            <div class="text-xs font-extrabold text-white truncate" title="${escapeHtml(node.name)}">
                                ${escapeHtml(node.name)}
                            </div>
                        </div>

                        <div class="mt-2 pt-1.5 border-t border-slate-800/90 text-[10px] text-slate-400 font-mono truncate" title="${escapeHtml(subtitle)}">
                            ${escapeHtml(subtitle)}
                        </div>
                    </div>
                `;
            });
            nodesLayer.innerHTML = nodesHtml;

            if (countBadge) {
                countBadge.textContent = `${nodes.length} node(s) • ${edgeCount} connection(s)`;
            }
        }

        function onAutomationsNodeMouseDown(e, nodeName) {
            e.stopPropagation();
            const wasSelected = automationsCanvasSelectedNodeName === nodeName;
            automationsCanvasSelectedNodeName = nodeName;
            renderAutomationsCanvasNodesAndEdges();
            renderAutomationsNodeInspector();

            // In Fullscreen Mode, clicking a node opens the Floating Inspector Drawer on Node Config tab
            if (automationsCanvasIsFullscreen) {
                automationsCanvasFloatingDrawerOpen = true;
                syncAutomationsCanvasFloatingDrawerUI();
                if (!wasSelected) {
                    switchAutomationsInspectorTab('node');
                }
            }

            const node = (automationsCanvasCurrentJson && automationsCanvasCurrentJson.nodes || []).find(n => n.name === nodeName);
            if (!node) return;
            automationsCanvasDragState = {
                mode: 'node',
                nodeName: nodeName,
                startMouseX: e.clientX,
                startMouseY: e.clientY,
                origX: Number(node.position[0]) || 0,
                origY: Number(node.position[1]) || 0
            };
        }

        function onAutomationsCanvasViewportMouseDown(e) {
            if (!automationsCanvasCurrentJson) return;
            automationsCanvasDragState = {
                mode: 'pan',
                startMouseX: e.clientX,
                startMouseY: e.clientY,
                origPanX: automationsCanvasPanX,
                origPanY: automationsCanvasPanY
            };
        }

        function onAutomationsCanvasViewportMouseMove(e) {
            if (!automationsCanvasDragState) return;
            if (automationsCanvasDragState.mode === 'pan') {
                automationsCanvasPanX = automationsCanvasDragState.origPanX + (e.clientX - automationsCanvasDragState.startMouseX);
                automationsCanvasPanY = automationsCanvasDragState.origPanY + (e.clientY - automationsCanvasDragState.startMouseY);
                applyAutomationsCanvasTransform();
            } else if (automationsCanvasDragState.mode === 'node' && automationsCanvasCurrentJson) {
                const node = (automationsCanvasCurrentJson.nodes || []).find(n => n.name === automationsCanvasDragState.nodeName);
                if (!node) return;
                const dx = (e.clientX - automationsCanvasDragState.startMouseX) / automationsCanvasZoom;
                const dy = (e.clientY - automationsCanvasDragState.startMouseY) / automationsCanvasZoom;
                node.position = [
                    Math.max(20, Math.round(automationsCanvasDragState.origX + dx)),
                    Math.max(20, Math.round(automationsCanvasDragState.origY + dy))
                ];
                renderAutomationsCanvasNodesAndEdges();
            }
        }

        function onAutomationsCanvasViewportMouseUp() {
            if (automationsCanvasDragState && automationsCanvasDragState.mode === 'node') {
                syncRawJsonTextareaFromCanvas();
            }
            automationsCanvasDragState = null;
        }

        function switchAutomationsInspectorTab(tab) {
            const panes = {
                node: document.getElementById('auto-inspector-node-pane'),
                json: document.getElementById('auto-inspector-json-pane'),
                runs: document.getElementById('auto-inspector-runs-pane')
            };
            const btns = {
                node: document.getElementById('auto-insp-tab-node'),
                json: document.getElementById('auto-insp-tab-json'),
                runs: document.getElementById('auto-insp-tab-runs')
            };
            Object.keys(panes).forEach(k => {
                if (panes[k]) panes[k].classList.toggle('hidden', k !== tab);
                if (btns[k]) {
                    btns[k].className = k === tab
                        ? 'px-2.5 py-1 rounded-lg bg-purple-500/25 border border-purple-400/50 text-purple-200 text-[11px] font-bold cursor-pointer'
                        : 'px-2.5 py-1 rounded-lg bg-slate-800 border border-slate-700 text-slate-400 text-[11px] font-bold cursor-pointer';
                }
            });
            if (tab === 'json') syncRawJsonTextareaFromCanvas();
            if (tab === 'runs') renderAutomationsExecutionHistoryPane();
        }

        function syncRawJsonTextareaFromCanvas() {
            const rawJsonArea = document.getElementById('auto-inspector-raw-json-textarea');
            if (rawJsonArea && automationsCanvasCurrentJson) {
                rawJsonArea.value = JSON.stringify(automationsCanvasCurrentJson, null, 2);
            }
        }

        function renderAutomationsNodeInspector() {
            const pane = document.getElementById('auto-inspector-node-pane');
            if (!pane) return;
            if (!automationsCanvasCurrentJson || !Array.isArray(automationsCanvasCurrentJson.nodes)) {
                pane.innerHTML = `
                    <div class="text-center py-14 text-slate-500 space-y-2">
                        <i class="fas fa-lock text-2xl text-rose-400/70"></i>
                        <p class="text-xs font-bold text-slate-300">Canvas Locked</p>
                        <p class="text-[11px] text-slate-500 max-w-xs mx-auto">
                            Upload a <code class="text-purple-300">.JSON</code> file or generate one via <strong>Ask AI</strong> first to unlock node inspection and editing.
                        </p>
                    </div>
                `;
                return;
            }

            const nodes = automationsCanvasCurrentJson.nodes;
            const node = nodes.find(n => n.name === automationsCanvasSelectedNodeName) || nodes[0];
            if (!node) return;
            automationsCanvasSelectedNodeName = node.name;
            const meta = getAutomationsNodeVisualMeta(node.type);
            const params = node.parameters || {};
            const tLow = String(node.type || '').toLowerCase();

            // Build outgoing connections editor
            const conns = (automationsCanvasCurrentJson.connections && automationsCanvasCurrentJson.connections[node.name] && automationsCanvasCurrentJson.connections[node.name].main) || [[]];
            const branch0Targets = (conns[0] || []).map(e => e.node);
            const branch1Targets = (conns[1] || []).map(e => e.node);
            const otherNodes = nodes.filter(n => n.name !== node.name);

            let specificConfigHtml = '';

            // 1. WEBHOOK / IN-DASHBOARD EVENT TRIGGER CONFIG
            if (meta.isTrigger) {
                const pathVal = params.path || node.webhookId || 'dashboard-event';
                specificConfigHtml = `
                    <div class="p-3 rounded-xl bg-gb-cyan/10 border border-gb-cyan/30 space-y-2">
                        <div class="text-[11px] font-extrabold text-gb-cyan flex items-center gap-1.5">
                            <i class="fas fa-satellite-dish"></i>
                            <span>In-Dashboard Native Event Trigger</span>
                        </div>
                        <p class="text-[11px] text-slate-300 leading-relaxed">
                            Dahil nasa loob ka na mismo ng GlennBot Dashboard, ang <code>n8n-nodes-base.webhook</code> node na ito ay automatic na nagti-trigger kapag may bagong comment, reply, message, email, SMS, o calendar event sa GlennBot — kahit walang external n8n server!
                        </p>
                        <div>
                            <label class="text-[10px] font-bold text-slate-400 uppercase block mb-1">Webhook Slug / Path (n8n Compatible)</label>
                            <input type="text" value="${escapeHtml(pathVal)}"
                                onchange="updateSelectedAutomationNodeWebhookPath(this.value)"
                                class="w-full bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-gb-cyan font-mono focus:outline-none">
                        </div>
                    </div>
                `;
            }

            // 2. IF / CONDITION NODE CONFIG
            else if (meta.isIf) {
                const condsObj = params.conditions || {};
                const strConds = Array.isArray(condsObj.string) ? condsObj.string : [];
                const boolConds = Array.isArray(condsObj.boolean) ? condsObj.boolean : [];
                const combineOp = params.combineOperation || 'all';

                let condRowsHtml = '';
                strConds.forEach((c, idx) => {
                    condRowsHtml += `
                        <div class="p-2.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1.5">
                            <div class="flex items-center justify-between">
                                <span class="text-[10px] font-bold text-amber-300">String Condition #${idx + 1}</span>
                                <button type="button" onclick="removeAutomationIfCondition('string', ${idx})" class="text-[10px] text-rose-400 hover:underline cursor-pointer">Remove</button>
                            </div>
                            <input type="text" value="${escapeHtml(c.value1 || '')}" placeholder="Value 1 (e.g. ={{ $json.body.account_name }})"
                                onchange="updateAutomationIfCondition('string', ${idx}, 'value1', this.value)"
                                class="w-full bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 text-[11px] text-white font-mono">
                            <select onchange="updateAutomationIfCondition('string', ${idx}, 'operation', this.value)"
                                class="w-full bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 text-[11px] text-amber-300 font-bold">
                                ${['contains', 'notContains', 'equal', 'notEqual', 'startsWith', 'endsWith', 'isNotEmpty', 'isEmpty'].map(op =>
                                    `<option value="${op}" ${c.operation === op ? 'selected' : ''}>${op}</option>`
                                ).join('')}
                            </select>
                            <input type="text" value="${escapeHtml(c.value2 || '')}" placeholder="Value 2 (e.g. Savvy Finds)"
                                onchange="updateAutomationIfCondition('string', ${idx}, 'value2', this.value)"
                                class="w-full bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 text-[11px] text-emerald-300 font-mono">
                        </div>
                    `;
                });
                boolConds.forEach((c, idx) => {
                    condRowsHtml += `
                        <div class="p-2.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1.5">
                            <div class="flex items-center justify-between">
                                <span class="text-[10px] font-bold text-gb-cyan">Boolean Expression #${idx + 1}</span>
                                <button type="button" onclick="removeAutomationIfCondition('boolean', ${idx})" class="text-[10px] text-rose-400 hover:underline cursor-pointer">Remove</button>
                            </div>
                            <input type="text" value="${escapeHtml(String(c.value1 ?? ''))}"
                                onchange="updateAutomationIfCondition('boolean', ${idx}, 'value1', this.value)"
                                class="w-full bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 text-[11px] text-white font-mono">
                        </div>
                    `;
                });

                specificConfigHtml = `
                    <div class="space-y-2.5">
                        <div class="flex items-center justify-between">
                            <label class="text-[10px] font-bold text-slate-400 uppercase">Combine Conditions</label>
                            <select onchange="updateAutomationNodeParam('combineOperation', this.value)"
                                class="bg-slate-950 border border-slate-700 rounded-lg px-2 py-1 text-xs text-amber-300 font-bold">
                                <option value="all" ${combineOp === 'all' ? 'selected' : ''}>AND (Match All)</option>
                                <option value="any" ${combineOp === 'any' ? 'selected' : ''}>OR (Match Any)</option>
                            </select>
                        </div>
                        <div class="space-y-2">${condRowsHtml || '<p class="text-[11px] text-slate-500">No conditions yet.</p>'}</div>
                        <button type="button" onclick="addAutomationIfStringCondition()"
                            class="w-full py-1.5 rounded-lg bg-amber-500/15 hover:bg-amber-500/25 border border-amber-400/40 text-amber-300 text-[11px] font-bold cursor-pointer">
                            + Add String Condition
                        </button>
                    </div>
                `;
            }

            // 3. WAIT NODE CONFIG
            else if (tLow.endsWith('.wait') || tLow === 'wait') {
                const amt = params.amount !== undefined ? params.amount : 2;
                const unit = params.unit || 'minutes';
                specificConfigHtml = `
                    <div class="grid grid-cols-2 gap-2">
                        <div>
                            <label class="text-[10px] font-bold text-slate-400 uppercase block mb-1">Wait Amount</label>
                            <input type="number" min="1" value="${escapeHtml(String(amt))}"
                                onchange="updateAutomationNodeParam('amount', Number(this.value) || 1)"
                                class="w-full bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-sky-300 font-bold">
                        </div>
                        <div>
                            <label class="text-[10px] font-bold text-slate-400 uppercase block mb-1">Time Unit</label>
                            <select onchange="updateAutomationNodeParam('unit', this.value)"
                                class="w-full bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-white font-bold">
                                <option value="seconds" ${unit === 'seconds' ? 'selected' : ''}>Seconds</option>
                                <option value="minutes" ${unit === 'minutes' ? 'selected' : ''}>Minutes</option>
                                <option value="hours" ${unit === 'hours' ? 'selected' : ''}>Hours</option>
                            </select>
                        </div>
                    </div>
                `;
            }

            // 4. CODE NODE CONFIG
            else if (tLow.endsWith('.code') || tLow.endsWith('.function') || tLow === 'code') {
                const jsCode = params.jsCode || params.functionCode || '';
                specificConfigHtml = `
                    <div class="space-y-1.5">
                        <label class="text-[10px] font-bold text-purple-300 uppercase block">JavaScript Transformation Code (jsCode)</label>
                        <textarea rows="9" spellcheck="false"
                            onchange="updateAutomationNodeParam('jsCode', this.value)"
                            class="w-full p-2.5 rounded-xl bg-slate-950 border border-purple-500/40 font-mono text-[11px] text-purple-200 focus:outline-none">${escapeHtml(jsCode)}</textarea>
                    </div>
                `;
            }

            // 5. HTTP REQUEST / GLENNBOT API NODE CONFIG
            else if (tLow.includes('httprequest') || tLow === 'http') {
                const method = String(params.method || 'POST').toUpperCase();
                const url = params.url || '';
                const jsonBody = typeof params.jsonBody === 'string' ? params.jsonBody : (params.jsonBody ? JSON.stringify(params.jsonBody, null, 2) : '');
                specificConfigHtml = `
                    <div class="space-y-2.5">
                        <div class="grid grid-cols-3 gap-2">
                            <div>
                                <label class="text-[10px] font-bold text-slate-400 uppercase block mb-1">Method</label>
                                <select onchange="updateAutomationNodeParam('method', this.value)"
                                    class="w-full bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-emerald-300 font-bold">
                                    ${['GET', 'POST', 'PUT', 'DELETE'].map(m => `<option value="${m}" ${method === m ? 'selected' : ''}>${m}</option>`).join('')}
                                </select>
                            </div>
                            <div class="col-span-2">
                                <label class="text-[10px] font-bold text-slate-400 uppercase block mb-1">Quick GlennBot Endpoint</label>
                                <select onchange="if(this.value) updateAutomationNodeParam('url', window.location.origin + this.value)"
                                    class="w-full bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-[11px] text-gb-cyan">
                                    <option value="">-- Select /api/v1/* endpoint --</option>
                                    <option value="/api/v1/spreadsheets/append-row">POST /api/v1/spreadsheets/append-row</option>
                                    <option value="/api/v1/spreadsheets/read?workbook_id=file_011d8d793a98&sheet_name=Sheet1">GET /api/v1/spreadsheets/read</option>
                                    <option value="/api/v1/comments/reply">POST /api/v1/comments/reply</option>
                                    <option value="/api/v1/comments/like">POST /api/v1/comments/like</option>
                                    <option value="/api/v1/comments/thread-status">GET /api/v1/comments/thread-status</option>
                                    <option value="/api/v1/messages/send-dm">POST /api/v1/messages/send-dm</option>
                                    <option value="/api/v1/emails/send">POST /api/v1/emails/send</option>
                                    <option value="/api/v1/sms/send">POST /api/v1/sms/send</option>
                                    <option value="/api/v1/calendar/schedule">POST /api/v1/calendar/schedule</option>
                                </select>
                            </div>
                        </div>
                        <div>
                            <label class="text-[10px] font-bold text-slate-400 uppercase block mb-1">Endpoint URL</label>
                            <input type="text" value="${escapeHtml(url)}"
                                onchange="updateAutomationNodeParam('url', this.value)"
                                class="w-full bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-[11px] text-emerald-300 font-mono">
                        </div>
                        <div>
                            <label class="text-[10px] font-bold text-slate-400 uppercase block mb-1">JSON Body Expression (jsonBody)</label>
                            <textarea rows="6" spellcheck="false"
                                onchange="updateAutomationNodeParam('jsonBody', this.value)"
                                class="w-full p-2.5 rounded-xl bg-slate-950 border border-slate-700 font-mono text-[11px] text-emerald-200 focus:outline-none">${escapeHtml(jsonBody)}</textarea>
                        </div>
                    </div>
                `;
            }

            // 6. GENERIC / SET PARAMETERS FALLBACK
            else {
                specificConfigHtml = `
                    <div class="space-y-1.5">
                        <label class="text-[10px] font-bold text-slate-400 uppercase block">Node Parameters (JSON)</label>
                        <textarea rows="6" spellcheck="false"
                            onchange="try { automationsCanvasCurrentJson.nodes.find(n=>n.name===automationsCanvasSelectedNodeName).parameters = JSON.parse(this.value); renderAutomationsCanvasAll(); } catch(e){ alert('Invalid JSON parameters'); }"
                            class="w-full p-2.5 rounded-xl bg-slate-950 border border-slate-700 font-mono text-[11px] text-slate-200">${escapeHtml(JSON.stringify(params, null, 2))}</textarea>
                    </div>
                `;
            }

            pane.innerHTML = `
                <div class="space-y-3">
                    <div class="flex items-center justify-between gap-2 pb-2 border-b border-slate-800">
                        <span style="background:${meta.badgeBg}; color:${meta.accentColor};" class="px-2 py-0.5 rounded-md text-[10px] font-extrabold uppercase">
                            <i class="fas ${meta.icon} mr-1"></i>${escapeHtml(meta.category)}
                        </span>
                        <button type="button" onclick="deleteSelectedAutomationNode()"
                            class="px-2.5 py-1 rounded-lg bg-rose-500/15 hover:bg-rose-500/30 border border-rose-500/40 text-rose-300 text-[11px] font-bold cursor-pointer">
                            <i class="fas fa-trash-alt mr-1"></i>Delete Node
                        </button>
                    </div>

                    <div>
                        <label class="text-[10px] font-bold text-slate-400 uppercase block mb-1">Node Name</label>
                        <input type="text" value="${escapeHtml(node.name)}"
                            onchange="renameSelectedAutomationNode(this.value)"
                            class="w-full bg-slate-950 border border-slate-700 focus:border-purple-400 rounded-lg px-2.5 py-1.5 text-xs font-bold text-white">
                    </div>

                    ${specificConfigHtml}

                    <!-- Outgoing Wire Connections Manager -->
                    <div class="pt-3 border-t border-slate-800 space-y-2">
                        <label class="text-[10px] font-bold text-slate-400 uppercase block">
                            <i class="fas fa-project-diagram text-gb-cyan mr-1"></i>Outgoing Connections (Next Step)
                        </label>
                        <div>
                            <span class="text-[10px] text-emerald-300 font-bold block mb-1">${meta.isIf ? 'TRUE Branch (Index 0) Connects To:' : 'Connects To Next Node:'}</span>
                            <select onchange="setAutomationNodeConnectionTarget(0, this.value)"
                                class="w-full bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-white">
                                <option value="">-- None (End of Branch) --</option>
                                ${otherNodes.map(on => `<option value="${escapeHtml(on.name)}" ${branch0Targets.includes(on.name) ? 'selected' : ''}>${escapeHtml(on.name)}</option>`).join('')}
                            </select>
                        </div>
                        ${meta.isIf ? `
                            <div>
                                <span class="text-[10px] text-rose-300 font-bold block mb-1">FALSE Branch (Index 1) Connects To:</span>
                                <select onchange="setAutomationNodeConnectionTarget(1, this.value)"
                                    class="w-full bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-white">
                                    <option value="">-- None (End of Branch) --</option>
                                    ${otherNodes.map(on => `<option value="${escapeHtml(on.name)}" ${branch1Targets.includes(on.name) ? 'selected' : ''}>${escapeHtml(on.name)}</option>`).join('')}
                                </select>
                            </div>
                        ` : ''}
                    </div>
                </div>
            `;
        }

        function updateAutomationNodeParam(key, val) {
            if (!automationsCanvasCurrentJson) return;
            const node = (automationsCanvasCurrentJson.nodes || []).find(n => n.name === automationsCanvasSelectedNodeName);
            if (!node) return;
            if (!node.parameters) node.parameters = {};
            node.parameters[key] = val;
            renderAutomationsCanvasAll();
        }

        function updateSelectedAutomationNodeWebhookPath(newPath) {
            if (!automationsCanvasCurrentJson) return;
            const node = (automationsCanvasCurrentJson.nodes || []).find(n => n.name === automationsCanvasSelectedNodeName);
            if (!node) return;
            const clean = String(newPath || '').trim().replace(/^\/+/, '') || 'dashboard-event';
            if (!node.parameters) node.parameters = {};
            node.parameters.path = clean;
            node.webhookId = clean;
            renderAutomationsCanvasAll();
        }

        function updateAutomationIfCondition(dtype, idx, field, val) {
            if (!automationsCanvasCurrentJson) return;
            const node = (automationsCanvasCurrentJson.nodes || []).find(n => n.name === automationsCanvasSelectedNodeName);
            if (!node || !node.parameters || !node.parameters.conditions) return;
            const arr = node.parameters.conditions[dtype];
            if (Array.isArray(arr) && arr[idx]) {
                arr[idx][field] = val;
                renderAutomationsCanvasAll();
            }
        }

        function addAutomationIfStringCondition() {
            if (!automationsCanvasCurrentJson) return;
            const node = (automationsCanvasCurrentJson.nodes || []).find(n => n.name === automationsCanvasSelectedNodeName);
            if (!node) return;
            if (!node.parameters) node.parameters = {};
            if (!node.parameters.conditions) node.parameters.conditions = {};
            if (!Array.isArray(node.parameters.conditions.string)) node.parameters.conditions.string = [];
            node.parameters.conditions.string.push({
                value1: "={{ $json.body.account_name || '' }}",
                operation: "contains",
                value2: "Savvy Finds"
            });
            renderAutomationsCanvasAll();
        }

        function removeAutomationIfCondition(dtype, idx) {
            if (!automationsCanvasCurrentJson) return;
            const node = (automationsCanvasCurrentJson.nodes || []).find(n => n.name === automationsCanvasSelectedNodeName);
            if (!node || !node.parameters || !node.parameters.conditions) return;
            const arr = node.parameters.conditions[dtype];
            if (Array.isArray(arr)) {
                arr.splice(idx, 1);
                renderAutomationsCanvasAll();
            }
        }

        function renameSelectedAutomationNode(newNameRaw) {
            if (!automationsCanvasCurrentJson) return;
            const newName = String(newNameRaw || '').trim();
            const oldName = automationsCanvasSelectedNodeName;
            if (!newName || newName === oldName) return;
            const nodes = automationsCanvasCurrentJson.nodes || [];
            if (nodes.some(n => n.name === newName)) {
                alert('A node with that name already exists in this workflow.');
                return;
            }
            const node = nodes.find(n => n.name === oldName);
            if (!node) return;
            node.name = newName;

            const conns = automationsCanvasCurrentJson.connections || {};
            if (conns[oldName]) {
                conns[newName] = conns[oldName];
                delete conns[oldName];
            }
            Object.keys(conns).forEach(src => {
                const main = (conns[src] && conns[src].main) || [];
                main.forEach(branch => {
                    if (Array.isArray(branch)) {
                        branch.forEach(edge => {
                            if (edge && edge.node === oldName) edge.node = newName;
                        });
                    }
                });
            });
            automationsCanvasSelectedNodeName = newName;
            renderAutomationsCanvasAll();
        }

        function setAutomationNodeConnectionTarget(branchIdx, targetNodeName) {
            if (!automationsCanvasCurrentJson) return;
            const srcName = automationsCanvasSelectedNodeName;
            if (!srcName) return;
            if (!automationsCanvasCurrentJson.connections) automationsCanvasCurrentJson.connections = {};
            if (!automationsCanvasCurrentJson.connections[srcName]) {
                automationsCanvasCurrentJson.connections[srcName] = { main: [[], []] };
            }
            const main = automationsCanvasCurrentJson.connections[srcName].main;
            while (main.length <= branchIdx) main.push([]);
            main[branchIdx] = targetNodeName ? [{ node: targetNodeName, type: 'main', index: 0 }] : [];
            renderAutomationsCanvasAll();
        }

        function addGenericNodeToAutomationsCanvas(kind) {
            if (!automationsCanvasCurrentJson || !Array.isArray(automationsCanvasCurrentJson.nodes)) {
                alert('Mag-upload muna ng .JSON file o mag-generate sa Ask AI para ma-unlock ang Automations Canvas!');
                return;
            }
            const nodes = automationsCanvasCurrentJson.nodes;
            const count = nodes.length + 1;
            const lastNode = nodes.find(n => n.name === automationsCanvasSelectedNodeName) || nodes[nodes.length - 1];
            const posX = lastNode ? (Number(lastNode.position[0]) || 120) + 300 : 160;
            const posY = lastNode ? (Number(lastNode.position[1]) || 220) : 220;

            let newNode = null;
            if (kind === 'if') {
                newNode = {
                    id: 'node_if_' + Date.now(),
                    name: 'IF Condition ' + count,
                    type: 'n8n-nodes-base.if',
                    typeVersion: 1,
                    position: [posX, posY],
                    parameters: {
                        conditions: {
                            string: [
                                { value1: "={{ $json.body.account_name || '' }}", operation: 'contains', value2: 'Savvy Finds' }
                            ]
                        },
                        combineOperation: 'all'
                    }
                };
            } else if (kind === 'wait') {
                newNode = {
                    id: 'node_wait_' + Date.now(),
                    name: 'Wait Timer ' + count,
                    type: 'n8n-nodes-base.wait',
                    typeVersion: 1.1,
                    position: [posX, posY],
                    parameters: { resume: 'timeInterval', amount: 2, unit: 'minutes' }
                };
            } else if (kind === 'code') {
                newNode = {
                    id: 'node_code_' + Date.now(),
                    name: 'Code Transform ' + count,
                    type: 'n8n-nodes-base.code',
                    typeVersion: 2,
                    position: [posX, posY],
                    parameters: {
                        jsCode: "const item = $input.first().json;\nreturn [{ json: { ...item, processed_at: new Date().toISOString() } }];"
                    }
                };
            } else if (kind === 'httpRequest') {
                newNode = {
                    id: 'node_http_' + Date.now(),
                    name: 'GlennBot API Action ' + count,
                    type: 'n8n-nodes-base.httpRequest',
                    typeVersion: 4.2,
                    position: [posX, posY],
                    parameters: {
                        method: 'POST',
                        url: window.location.origin + '/api/v1/comments/reply',
                        sendHeaders: true,
                        headerParameters: {
                            parameters: [
                                { name: 'X-API-Key', value: 'gb_live_99b6d02bdd6093ac7d58fb09c034ee05b04b' },
                                { name: 'Content-Type', value: 'application/json' }
                            ]
                        },
                        sendBody: true,
                        specifyBody: 'json',
                        jsonBody: "={{ JSON.stringify({ record_id: $('Webhook Trigger').item.json.body.record_id, comment_id: $('Webhook Trigger').item.json.body.comment_id, message: 'Thank you for your comment!' }) }}"
                    }
                };
            } else if (kind === 'set') {
                newNode = {
                    id: 'node_set_' + Date.now(),
                    name: 'Set Fields ' + count,
                    type: 'n8n-nodes-base.set',
                    typeVersion: 3.4,
                    position: [posX, posY],
                    parameters: {
                        assignments: {
                            assignments: [
                                { id: 'assign_1', name: 'custom_tag', value: 'SavvyFindsLead', type: 'string' }
                            ]
                        }
                    }
                };
            } else {
                newNode = {
                    id: 'node_wh_' + Date.now(),
                    name: 'Webhook Trigger ' + count,
                    type: 'n8n-nodes-base.webhook',
                    typeVersion: 2,
                    position: [posX, posY],
                    webhookId: 'dashboard-event-' + count,
                    parameters: { httpMethod: 'POST', path: 'dashboard-event-' + count, responseMode: 'onReceived' }
                };
            }

            nodes.push(newNode);
            // Auto-connect from currently selected node if it has no outgoing connection yet
            if (lastNode && lastNode.name !== newNode.name) {
                if (!automationsCanvasCurrentJson.connections) automationsCanvasCurrentJson.connections = {};
                if (!automationsCanvasCurrentJson.connections[lastNode.name]) {
                    automationsCanvasCurrentJson.connections[lastNode.name] = { main: [[{ node: newNode.name, type: 'main', index: 0 }]] };
                }
            }
            automationsCanvasSelectedNodeName = newNode.name;
            renderAutomationsCanvasAll();
            showToast(`➕ Added "${newNode.name}" to Automations Canvas!`);
        }

        function deleteSelectedAutomationNode() {
            if (!automationsCanvasCurrentJson || !automationsCanvasSelectedNodeName) return;
            const target = automationsCanvasSelectedNodeName;
            automationsCanvasCurrentJson.nodes = (automationsCanvasCurrentJson.nodes || []).filter(n => n.name !== target);
            const conns = automationsCanvasCurrentJson.connections || {};
            delete conns[target];
            Object.keys(conns).forEach(src => {
                const main = (conns[src] && conns[src].main) || [];
                main.forEach((branch, idx) => {
                    if (Array.isArray(branch)) {
                        main[idx] = branch.filter(edge => edge && edge.node !== target);
                    }
                });
            });
            automationsCanvasSelectedNodeName = automationsCanvasCurrentJson.nodes[0] ? automationsCanvasCurrentJson.nodes[0].name : '';
            renderAutomationsCanvasAll();
        }

        function onAutomationsCanvasWorkflowNameInput(val) {
            if (!automationsCanvasCurrentJson) return;
            automationsCanvasCurrentJson.name = String(val || '').trim() || 'Automation Workflow';
            const normalInput = document.getElementById('auto-canvas-wf-name-input');
            const fsInput = document.getElementById('auto-canvas-fs-name-input');
            if (normalInput && document.activeElement !== normalInput) normalInput.value = val;
            if (fsInput && document.activeElement !== fsInput) fsInput.value = val;
            syncRawJsonTextareaFromCanvas();
        }

        async function toggleAutomationsCanvasWorkflowActive() {
            if (!automationsCanvasCurrentJson) return;
            automationsCanvasIsActive = !automationsCanvasIsActive;
            automationsCanvasCurrentJson.active = automationsCanvasIsActive;
            renderAutomationsCanvasAll();
            await saveCurrentAutomationsCanvasWorkflow(true);
            showToast(automationsCanvasIsActive ? '🟢 Workflow ACTIVE in Production Mode!' : '⏸️ Workflow PAUSED.');
        }

        async function applyRawJsonEditToAutomationsCanvas() {
            const area = document.getElementById('auto-inspector-raw-json-textarea');
            if (!area || !area.value.trim()) return;
            try {
                const parsed = parseFlexibleN8nWorkflowJson(area.value);
                if (unlockAndLoadJsonIntoAutomationsCanvas(parsed, {
                    id: automationsCanvasCurrentId,
                    name: parsed.name || 'Automation Workflow',
                    active: automationsCanvasIsActive
                })) {
                    await saveCurrentAutomationsCanvasWorkflow(true);
                    showToast('✅ Applied & Saved raw .JSON edits to Automations Canvas!');
                }
            } catch (e) {
                alert('Invalid JSON syntax: ' + (e.message || e));
            }
        }

        function copyCurrentAutomationsCanvasJson() {
            if (!automationsCanvasCurrentJson) return;
            navigator.clipboard.writeText(JSON.stringify(automationsCanvasCurrentJson, null, 2));
            showToast('📋 Copied n8n .JSON to clipboard!');
        }

        function downloadCurrentAutomationsCanvasJson() {
            if (!automationsCanvasCurrentJson) return;
            const raw = JSON.stringify(automationsCanvasCurrentJson, null, 2);
            const slug = String(automationsCanvasCurrentJson.name || 'glennbot-automation')
                .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'workflow';
            const blob = new Blob([raw], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${slug}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            showToast(`⬇️ Downloaded "${slug}.json"!`);
        }

        async function saveCurrentAutomationsCanvasWorkflow(silent = false) {
            if (!automationsCanvasCurrentJson) return;
            try {
                const res = await fetch('/api/automations/workflows/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        id: automationsCanvasCurrentId || undefined,
                        name: automationsCanvasCurrentJson.name || 'Automation Workflow',
                        active: automationsCanvasIsActive,
                        workflow_json: automationsCanvasCurrentJson
                    })
                });
                const data = await res.json();
                if (data.status === 'success' && data.workflow) {
                    automationsCanvasCurrentId = data.workflow.id;
                    automationsCanvasCurrentJson = data.workflow.workflow_json;
                    automationsCanvasSavedWorkflows = Array.isArray(data.workflows) ? data.workflows : automationsCanvasSavedWorkflows;
                    renderAutomationsSavedWorkflowSelect();
                    renderAutomationsCanvasAll();
                    if (!silent) {
                        showToast(`💾 Saved "${data.workflow.name}" to In-Dashboard Automations (Production Mode Active)!`);
                    }
                } else if (!silent) {
                    alert(data.message || 'Failed to save workflow.');
                }
            } catch (e) {
                if (!silent) {
                    alert('Error saving workflow: ' + (e.message || e));
                }
            }
        }

        async function deleteSelectedAutomationsCanvasWorkflow() {
            const sel = document.getElementById('auto-canvas-saved-wf-select');
            const targetId = String(automationsCanvasCurrentId || (sel && sel.value) || '').trim();
            if (!targetId) {
                showToast('⚠️ Pumili muna ng saved .JSON workflow sa dropdown para ma-delete.');
                return;
            }
            const found = automationsCanvasSavedWorkflows.find(w => String(w.id) === targetId);
            const wfName = (found && found.name) || (automationsCanvasCurrentJson && automationsCanvasCurrentJson.name) || 'Automation Workflow';
            if (!confirm(`Delete saved .JSON workflow "${wfName}" from Automations?`)) {
                return;
            }
            try {
                const res = await fetch(`/api/automations/workflows/${encodeURIComponent(targetId)}`, {
                    method: 'DELETE'
                });
                const data = await res.json();
                if (data.status === 'success') {
                    automationsCanvasSavedWorkflows = Array.isArray(data.workflows)
                        ? data.workflows
                        : automationsCanvasSavedWorkflows.filter(w => String(w.id) !== targetId);
                    automationsCanvasCurrentId = '';
                    automationsCanvasCurrentJson = null;
                    automationsCanvasSelectedNodeName = '';
                    automationsCanvasLastTraceByNode = {};
                    renderAutomationsSavedWorkflowSelect();
                    renderAutomationsCanvasAll();
                    showToast(`🗑️ Deleted "${wfName}" (.JSON) from Automations!`);
                } else {
                    alert(data.message || 'Failed to delete workflow.');
                }
            } catch (e) {
                alert('Error deleting workflow: ' + (e.message || e));
            }
        }

        async function executeAutomationsCanvasWorkflowTest() {
            if (!automationsCanvasCurrentJson) return;
            const runBtn = document.getElementById('auto-canvas-run-btn');
            const fsRunBtn = document.getElementById('auto-canvas-fs-run-btn');
            const summaryEl = document.getElementById('auto-canvas-last-trace-summary');
            if (runBtn) {
                runBtn.disabled = true;
                runBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i><span>Running...</span>`;
            }
            if (fsRunBtn) {
                fsRunBtn.disabled = true;
                fsRunBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i><span>Running...</span>`;
            }
            try {
                const res = await fetch('/api/automations/workflows/execute', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        workflow_id: automationsCanvasCurrentId || undefined,
                        workflow_json: automationsCanvasCurrentJson
                    })
                });
                const data = await res.json();
                if (data.status === 'success' && data.execution) {
                    const exec = data.execution;
                    automationsCanvasLastTraceByNode = {};
                    (exec.trace || []).forEach(step => {
                        automationsCanvasLastTraceByNode[step.node_name] = step;
                    });
                    if (Array.isArray(data.execution_history)) {
                        automationsCanvasExecutionHistory = data.execution_history;
                    }
                    if (summaryEl) {
                        const badgeColor = exec.status === 'success' ? 'text-emerald-300' : 'text-rose-300';
                        summaryEl.innerHTML = `
                            <span class="${badgeColor} font-extrabold">● Last Run (${escapeHtml(exec.event_type)}): ${exec.steps_count} nodes executed in ${exec.duration_ms}ms</span>
                            <span class="text-slate-400">• ${(exec.trace || []).map(t => `${escapeHtml(t.node_name)} (${t.status === 'success' ? '✓' : '✕'})`).join(' → ')}</span>
                        `;
                    }
                    renderAutomationsCanvasNodesAndEdges();
                    renderAutomationsExecutionHistoryPane();
                    switchAutomationsInspectorTab('runs');
                    if (automationsCanvasIsFullscreen) {
                        automationsCanvasFloatingDrawerOpen = true;
                        syncAutomationsCanvasFloatingDrawerUI();
                    }
                    showToast(`▶️ Executed ${exec.steps_count} nodes natively in ${exec.duration_ms}ms!`);
                } else {
                    alert(data.message || 'Execution failed.');
                }
            } catch (e) {
                alert('Error executing workflow: ' + (e.message || e));
            } finally {
                if (runBtn) {
                    runBtn.disabled = false;
                    runBtn.innerHTML = `<i class="fas fa-play"></i><span>Test Run</span>`;
                }
                if (fsRunBtn) {
                    fsRunBtn.disabled = false;
                    fsRunBtn.innerHTML = `<i class="fas fa-play"></i><span>Test Run</span>`;
                }
            }
        }

        function renderAutomationsExecutionHistoryPane() {
            const pane = document.getElementById('auto-inspector-runs-pane');
            if (!pane) return;
            if (!automationsCanvasExecutionHistory || automationsCanvasExecutionHistory.length === 0) {
                pane.innerHTML = `
                    <div class="text-center py-12 text-slate-500">
                        <i class="fas fa-history text-xl mb-1.5"></i>
                        <p>No workflow executions recorded yet. Click <strong>Test Run</strong> to execute the loaded canvas natively.</p>
                    </div>
                `;
                return;
            }
            pane.innerHTML = automationsCanvasExecutionHistory.map(run => `
                <div class="p-3 rounded-xl bg-slate-950 border ${run.status === 'success' ? 'border-emerald-500/40' : 'border-rose-500/40'} space-y-2">
                    <div class="flex items-center justify-between gap-2">
                        <span class="font-extrabold text-white truncate">${escapeHtml(run.workflow_name || 'Workflow')}</span>
                        <span class="px-2 py-0.5 rounded text-[10px] font-bold ${run.status === 'success' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'}">
                            ${run.status === 'success' ? 'SUCCESS' : 'ERROR'} • ${run.duration_ms}ms
                        </span>
                    </div>
                    <div class="text-[10px] text-slate-400 font-mono">${escapeHtml(run.timestamp || '')} • Event: ${escapeHtml(run.event_type || '')}</div>
                    <div class="space-y-1 pt-1 border-t border-slate-800/80">
                        ${(run.trace || []).map(step => `
                            <div class="text-[11px] flex items-start justify-between gap-2">
                                <span class="${step.status === 'success' ? 'text-emerald-300' : 'text-rose-300'} font-semibold">
                                    ${step.status === 'success' ? '✓' : '✕'} ${escapeHtml(step.node_name)}
                                </span>
                                <span class="text-[10px] text-slate-400 text-right">${escapeHtml(step.detail || '')}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `).join('');
        }
