        // =========================================================================
        // --- GLENNBOT INTERNAL REST API (v1) & N8N AUTOMATION HUB UI FUNCTIONS ---
        // =========================================================================
        let currentInternalApiKeys = [];

        async function openInternalApiModal(defaultTab = 'keys') {
            if (!window.gbCurrentAuthUser || !window.gbCurrentAuthUser.is_admin) {
                showToast('⛔ Restricted Access: Internal API (n8n) is strictly reserved for the Administrator (glennardtasico@gmail.com).');
                return;
            }
            openModalWithFade('internal-api-n8n-modal');
            switchInternalApiTab(defaultTab);
            await loadInternalApiConfig();
        }

        function closeInternalApiModal() {
            closeModalWithFade('internal-api-n8n-modal');
        }

        function switchInternalApiTab(tabName) {
            const tabs = ['keys', 'endpoints', 'webhook', 'logs'];
            tabs.forEach(t => {
                const btn = document.getElementById(`iapi-tab-${t}`);
                const panel = document.getElementById(`iapi-panel-${t}`);
                if (btn) {
                    if (t === tabName) {
                        btn.className = 'px-3.5 py-2 rounded-t-lg text-xs font-bold border border-b-0 border-gb-cyan bg-gb-cyan/15 text-gb-cyan flex items-center gap-1.5 transition-all';
                    } else {
                        btn.className = 'px-3.5 py-2 rounded-t-lg text-xs font-bold border border-b-0 border-slate-700 bg-slate-800/70 text-slate-300 hover:text-white flex items-center gap-1.5 transition-all';
                    }
                }
                if (panel) {
                    if (t === tabName) panel.classList.remove('hidden');
                    else panel.classList.add('hidden');
                }
            });
        }

        async function copyInternalApiText(val, label) {
            if (!val) return;
            let copiedOk = false;
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(val);
                    copiedOk = true;
                }
            } catch (_) {}
            if (!copiedOk) {
                try {
                    const ta = document.createElement('textarea');
                    ta.value = val;
                    ta.style.position = 'fixed';
                    ta.style.left = '-9999px';
                    ta.style.top = '0';
                    document.body.appendChild(ta);
                    ta.focus();
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                    copiedOk = true;
                } catch (_) {}
            }
            showToast(`✅ Copied ${label || 'to clipboard'}!`);
        }

        async function copyTextToClipboard(val, label) {
            return copyInternalApiText(val, label);
        }

        function renderInternalApiKeysList(keys) {
            currentInternalApiKeys = Array.isArray(keys) ? keys : [];
            const container = document.getElementById('iapi-keys-list-container');
            if (!container) return;

            if (!currentInternalApiKeys.length) {
                container.innerHTML = `<div class="p-6 text-center text-xs text-slate-400 bg-slate-950/60 rounded-xl border border-slate-800">No Internal API Keys found. Click <strong>Generate Key</strong> above.</div>`;
                return;
            }

            container.innerHTML = currentInternalApiKeys.map(k => `
                <div class="p-3.5 rounded-xl bg-slate-950/90 border border-slate-800 hover:border-gb-cyan/40 transition-all flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div class="space-y-1 min-w-0 flex-1">
                        <div class="flex items-center gap-2 flex-wrap">
                            <span class="font-bold text-xs sm:text-sm text-white">${escapeHTML(k.name || 'n8n Automation Key')}</span>
                            <span class="px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 text-[10px] font-bold">ACTIVE</span>
                            <span class="text-[10px] text-slate-400">Requests: <strong class="text-gb-cyan">${Number(k.requests_count || 0)}</strong></span>
                            <span class="text-[10px] text-slate-500">• Last used: ${escapeHTML(k.last_used_at || 'Never')}</span>
                        </div>
                        <div class="font-mono text-xs text-gb-cyan bg-slate-900/90 px-3 py-1.5 rounded-lg border border-slate-800 select-all break-all">${escapeHTML(k.api_key || '')}</div>
                    </div>
                    <div class="flex items-center gap-2 shrink-0">
                        <button type="button" onclick="copyInternalApiText('${escapeHTML(k.api_key || '')}', 'Internal API Key')" class="px-3 py-1.5 rounded-lg bg-gb-cyan/15 hover:bg-gb-cyan/25 border border-gb-cyan/50 text-gb-cyan text-xs font-bold flex items-center gap-1.5 transition-all">
                            <i class="fas fa-copy"></i>
                            <span>Copy Key</span>
                        </button>
                        <button type="button" onclick="deleteInternalApiKey('${escapeHTML(k.id || '')}')" class="px-2.5 py-1.5 rounded-lg bg-rose-950/50 hover:bg-rose-900/70 border border-rose-500/40 text-rose-300 text-xs font-semibold transition-all" title="Revoke & Delete Key">
                            <i class="fas fa-trash-alt"></i>
                        </button>
                    </div>
                </div>
            `).join('');
        }

        function renderInternalApiLogsList(logs) {
            const container = document.getElementById('iapi-logs-container');
            if (!container) return;
            const list = Array.isArray(logs) ? logs : [];
            if (!list.length) {
                container.innerHTML = `<div class="p-6 text-center text-xs text-slate-400 bg-slate-950/60 rounded-xl border border-slate-800">No recent API calls logged yet. Click <strong>Test API Status</strong> in the top-right corner or send a request from n8n!</div>`;
                return;
            }
            container.innerHTML = list.map(l => `
                <div class="px-3.5 py-2.5 rounded-xl bg-slate-950/90 border border-slate-800 flex flex-wrap items-center justify-between gap-2 text-xs">
                    <div class="flex items-center gap-2">
                        <span class="px-2 py-0.5 rounded bg-gb-cyan/15 text-gb-cyan border border-gb-cyan/40 font-mono font-bold text-[10px]">${escapeHTML(l.method || 'GET')}</span>
                        <span class="font-mono text-white">${escapeHTML(l.endpoint || '/api/v1/status')}</span>
                        <span class="text-[11px] text-slate-400">(${escapeHTML(l.key_name || 'API Key')})</span>
                    </div>
                    <div class="flex items-center gap-2 text-[11px]">
                        <span class="text-emerald-400 font-semibold">${escapeHTML(l.status || '200 OK')}</span>
                        <span class="text-slate-500">${escapeHTML(l.timestamp || '')}</span>
                    </div>
                </div>
            `).join('');
        }

        let currentN8nWorkflows = [];
        let pendingUploadedWorkflowJson = null;

        function injectLiveApiKeyIntoWorkflowJson(wfJsonObj) {
            if (!wfJsonObj || typeof wfJsonObj !== 'object') return wfJsonObj;
            const cloned = JSON.parse(JSON.stringify(wfJsonObj));
            const activeKey = (currentInternalApiKeys[0] && currentInternalApiKeys[0].api_key)
                ? currentInternalApiKeys[0].api_key
                : 'gb_live_7b09d447eb8fb86e44149927101f536e55cf';
            const baseUrlEl = document.getElementById('iapi-base-url-display');
            const fallbackBaseApi = `${window.location.origin.replace(/\/+$/, '')}/api/v1`;
            const rawBaseUrl = (baseUrlEl && baseUrlEl.textContent && baseUrlEl.textContent.trim().startsWith('http'))
                ? baseUrlEl.textContent.trim()
                : fallbackBaseApi;
            const baseUrl = rawBaseUrl.replace(/\/+$/, '');

            if (Array.isArray(cloned.nodes)) {
                cloned.nodes.forEach(node => {
                    if (!node || typeof node !== 'object') return;
                    const nType = String(node.type || '').toLowerCase();
                    const nName = String(node.name || '').toLowerCase();
                    if (!node.parameters || typeof node.parameters !== 'object') {
                        node.parameters = {};
                    }
                    const params = node.parameters;

                    // Auto-heal IF nodes (both v1/v2 schema compatibility and multi-platform combinators)
                    if (nType.endsWith('.if') || nType.includes('.if')) {
                        const conds = params.conditions;
                        if (conds && typeof conds === 'object') {
                            if (Array.isArray(conds.conditions) && conds.conditions.length > 0) {
                                const boolItems = Array.isArray(conds.boolean) ? [...conds.boolean] : [];
                                const strItems = Array.isArray(conds.string) ? [...conds.string] : [];
                                const numItems = Array.isArray(conds.number) ? [...conds.number] : [];

                                conds.conditions.forEach(c => {
                                    if (!c || typeof c !== 'object') return;
                                    const leftV = c.leftValue !== undefined ? c.leftValue : (c.value1 || '');
                                    const rightV = c.rightValue !== undefined ? c.rightValue : c.value2;
                                    const opRaw = c.operator !== undefined ? c.operator : (c.operation || 'equal');
                                    const opStr = String((opRaw && typeof opRaw === 'object') ? (opRaw.operation || 'equal') : (opRaw || 'equal')).trim();
                                    let leftStr = String(leftV || '');
                                    const isBoolCheck = (
                                        typeof rightV === 'boolean' ||
                                        ['true', 'false'].includes(String(rightV).trim().toLowerCase()) ||
                                        ['has_reply_to_sms', 'has_reply_to_comment', 'is_own', 'replied'].some(bk => leftStr.toLowerCase().includes(bk))
                                    );
                                    if (isBoolCheck) {
                                        const targetBool = (rightV === true || String(rightV).trim().toLowerCase() === 'true');
                                        if (leftStr.startsWith('={{') && leftStr.endsWith('}}') && !leftStr.includes('Boolean(')) {
                                            const innerExpr = leftStr.slice(3, -2).trim();
                                            leftStr = `={{ Boolean(${innerExpr}) }}`;
                                        }
                                        boolItems.push({ value1: leftStr, value2: targetBool });
                                    } else if (typeof rightV === 'number') {
                                        numItems.push({ value1: leftStr, operation: ['equals', 'equal'].includes(opStr) ? 'equal' : opStr, value2: rightV });
                                    } else {
                                        let v1Op = ['equals', 'equal'].includes(opStr) ? 'equal' : (['notEquals', 'notEqual'].includes(opStr) ? 'notEqual' : opStr);
                                        if (!['contains', 'notContains', 'equal', 'notEqual', 'startsWith', 'endsWith', 'regex', 'isEmpty', 'isNotEmpty'].includes(v1Op)) {
                                            v1Op = 'contains';
                                        }
                                        strItems.push({ value1: leftStr, operation: v1Op, value2: String(rightV ?? '') });
                                    }
                                });

                                const newConds = {};
                                if (boolItems.length) newConds.boolean = boolItems;
                                if (strItems.length) newConds.string = strItems;
                                if (numItems.length) newConds.number = numItems;
                                if (Object.keys(newConds).length) {
                                    const comb = String(conds.combinator || params.combineOperation || 'and').toLowerCase();
                                    node.typeVersion = 1;
                                    params.conditions = newConds;
                                    if (comb === 'or' || comb === 'any') params.combineOperation = 'any';
                                }
                            }
                            const activeConds = params.conditions || {};
                            if (Array.isArray(activeConds.string)) {
                                activeConds.string.forEach(s => {
                                    if (s && s.operation === 'equals') s.operation = 'equal';
                                });
                                if (activeConds.string.length >= 2) {
                                    const leftsV1 = activeConds.string.map(c => String((c && c.value1) || '').trim().toLowerCase());
                                    const rightsV1 = activeConds.string.map(c => String((c && c.value2) || '').trim().toLowerCase());
                                    const uniqueLeftsV1 = [...new Set(leftsV1)];
                                    const uniqueRightsV1 = [...new Set(rightsV1)];
                                    if (uniqueLeftsV1.length === 1 && uniqueRightsV1.length > 1 && ['platform', 'event', 'sender_email', 'account_email'].some(k => uniqueLeftsV1[0].includes(k))) {
                                        params.combineOperation = 'any';
                                    }
                                }
                            }
                            if (Array.isArray(activeConds.boolean)) {
                                activeConds.boolean.forEach(b => {
                                    if (b && typeof b.value1 === 'string' && b.value1.startsWith('={{') && b.value1.endsWith('}}') && !b.value1.includes('Boolean(')) {
                                        const innerB = b.value1.slice(3, -2).trim();
                                        b.value1 = `={{ Boolean(${innerB}) }}`;
                                    }
                                });
                                node.typeVersion = 1;
                            }
                        }
                    }

                    if (!nType.includes('httprequest')) return;
                    const rawUrl = String(params.url || '').trim();
                    let rawBodyStr = String(params.jsonBody || params.body || '');
                    if (rawBodyStr && rawBodyStr.includes("($'")) {
                        rawBodyStr = rawBodyStr.replace(/\(\$'([^']+)'\)/g, "$$('$1')");
                        if (params.jsonBody !== undefined) params.jsonBody = rawBodyStr;
                        else if (params.body !== undefined) params.body = rawBodyStr;
                    }
                    const jBody = rawBodyStr.toLowerCase();

                    const isAiAskNode = (
                        rawUrl.toLowerCase().includes('/api/ai/ask') ||
                        rawUrl.toLowerCase().includes('/api/v1/ai/ask') ||
                        (
                            ['gemini', 'ask ai', 'ai answer', 'ai reply', 'generate ai'].some(k => nName.includes(k)) &&
                            !jBody.includes('comment_id') &&
                            !jBody.includes('from_email') &&
                            !jBody.includes('conversation_id')
                        ) ||
                        (jBody.includes('"topic"') && !jBody.includes('comment_id'))
                    );

                    // 1. Auto-inject or normalize the GlennBot API URL even if blank or placeholder (preserving leading `=`)
                    if (isAiAskNode) {
                        params.url = `${baseUrl}/ai/ask`;
                    } else if (rawUrl.includes('/api/v1/')) {
                        const suffix = rawUrl.split('/api/v1/')[1].replace(/^\/+/, '');
                        if (suffix.startsWith('sms/thread-status') && (suffix.includes("' +") || suffix.includes("+ '") || suffix.endsWith('}}'))) {
                            params.url = `=${baseUrl}/sms/thread-status?phone={{ encodeURIComponent($('Webhook').item.json.body.recipient_phone || $('Webhook').item.json.body.sender_phone || $('Webhook').item.json.body.phone || $('Webhook').item.json.body.participant_id || '') }}&conversation_id={{ $('Webhook').item.json.body.conversation_id || '' }}&message_id={{ $('Webhook').item.json.body.message_id || '' }}&force=true`;
                        } else if (suffix.startsWith('comments/thread-status') && (suffix.includes("' +") || suffix.includes("+ '") || (suffix.endsWith('}}') && !rawUrl.startsWith('=')))) {
                            params.url = `=${baseUrl}/comments/thread-status?record_id={{ $('Webhook').item.json.body.record_id || $json.body.record_id || '' }}&comment_id={{ $('Webhook').item.json.body.comment_id || $json.body.comment_id || '' }}&force=true`;
                        } else if (rawUrl.startsWith('={{') && (suffix.includes("' +") || suffix.includes("+ '"))) {
                            params.url = `={{ '${baseUrl}/${suffix}`;
                        } else {
                            const hasExpr = suffix.includes('{{') && suffix.includes('}}');
                            const prefix = (rawUrl.startsWith('=') || hasExpr) ? '=' : '';
                            params.url = `${prefix}${baseUrl}/${suffix}`;
                        }
                    } else if (!rawUrl || ['your_url', 'paste_', 'localhost', '127.0.0.1', 'example.com', 'glennbot'].some(p => rawUrl.toLowerCase().includes(p))) {
                        if ((nName.includes('thread-status') || nName.includes('thread_status')) && nName.includes('sms')) {
                            params.url = `=${baseUrl}/sms/thread-status?phone={{ encodeURIComponent($('Webhook').item.json.body.recipient_phone || $('Webhook').item.json.body.sender_phone || $('Webhook').item.json.body.phone || $('Webhook').item.json.body.participant_id || '') }}&conversation_id={{ $('Webhook').item.json.body.conversation_id || '' }}&message_id={{ $('Webhook').item.json.body.message_id || '' }}&force=true`;
                        } else if (nName.includes('thread-status') || nName.includes('thread_status')) {
                            params.url = `=${baseUrl}/comments/thread-status?record_id={{ $('Webhook').item.json.body.record_id || $json.body.record_id || '' }}&comment_id={{ $('Webhook').item.json.body.comment_id || $json.body.comment_id || '' }}&force=true`;
                        } else if (nName.includes('like') && nName.includes('comment')) {
                            params.url = `${baseUrl}/comments/like`;
                        } else if (nName.includes('hide') && nName.includes('comment')) {
                            params.url = `${baseUrl}/comments/hide`;
                        } else if (['reschedule_reason', 'restructured_message_body', 'reschedule'].some(k => jBody.includes(k) || nName.includes(k))) {
                            params.url = `${baseUrl}/calendar/reschedule`;
                        } else if (['cancellation_reason'].some(k => jBody.includes(k)) || (nName.includes('cancel') && ['cal', 'meet', 'appoint'].some(m => nName.includes(m)))) {
                            params.url = `${baseUrl}/calendar/cancel`;
                        } else if (['meeting_platform', 'duration_minutes', 'start_time'].some(k => jBody.includes(k)) || ['calendar', 'appointment', 'google meet', 'zoom', 'teams'].some(k => nName.includes(k))) {
                            params.url = `${baseUrl}/calendar/schedule`;
                        } else if (['workbook_id', 'sheet_name', 'spreadsheet'].some(k => jBody.includes(k) || nName.includes(k))) {
                            if (nName.includes('append') || jBody.includes('"row"')) {
                                params.url = `${baseUrl}/spreadsheets/append-row`;
                            } else if (nName.includes('update') || jBody.includes('"cells"')) {
                                params.url = `${baseUrl}/spreadsheets/update-cells`;
                            } else {
                                params.url = `${baseUrl}/spreadsheets/read`;
                            }
                        } else if (['from_email', 'sender_email', 'email', 'gmail'].some(k => jBody.includes(k) || nName.includes(k))) {
                            params.url = `${baseUrl}/emails/send`;
                        } else if (['comment_id', 'send_dm', 'comment'].some(k => jBody.includes(k) || nName.includes(k))) {
                            params.url = `${baseUrl}/comments/reply`;
                        } else if (['recipient_phone', 'sim_subscription_id', 'textbee', 'send sms', 'sms'].some(k => jBody.includes(k) || nName.includes(k))) {
                            params.url = `${baseUrl}/sms/send`;
                        } else if (['conversation_id', 'participant_id', 'message', 'chat'].some(k => jBody.includes(k) || nName.includes(k))) {
                            params.url = `${baseUrl}/messages/send`;
                        } else if (['contact', 'crm'].some(k => jBody.includes(k) || nName.includes(k))) {
                            params.url = `${baseUrl}/contacts`;
                        } else if (['post', 'schedule'].some(k => jBody.includes(k) || nName.includes(k))) {
                            params.url = `${baseUrl}/posts/schedule`;
                        }
                    }

                    // 2. Auto-inject GET/POST method and active X-API-Key header
                    const finalUrlStr = String(params.url || '');
                    if (finalUrlStr.includes('/api/v1/')) {
                        if (['/comments/thread-status', '/sms/thread-status', '/spreadsheets/read', '/calendar/events', '/api/v1/status', '/api/v1/accounts', '/api/v1/files', '/api/v1/analytics', '/api/v1/presets'].some(ep => finalUrlStr.includes(ep))) {
                            params.method = 'GET';
                        } else if (!params.method) {
                            params.method = 'POST';
                        }
                        params.sendHeaders = true;
                        if (!params.headerParameters || typeof params.headerParameters !== 'object') {
                            params.headerParameters = { parameters: [] };
                        }
                        if (!Array.isArray(params.headerParameters.parameters)) {
                            params.headerParameters.parameters = [];
                        }
                        const hList = params.headerParameters.parameters;
                        let foundKey = false;
                        hList.forEach(hp => {
                            if (hp && ['x-api-key', 'x-glennbot-api-key'].includes(String(hp.name || '').toLowerCase())) {
                                hp.name = 'X-API-Key';
                                hp.value = activeKey;
                                foundKey = true;
                            }
                        });
                        if (!foundKey) {
                            hList.push({ name: 'X-API-Key', value: activeKey });
                        }
                    }
                });
            }
            return cloned;
        }

        async function copyPendingUploadedWorkflowJson() {
            if (!pendingUploadedWorkflowJson || !pendingUploadedWorkflowJson.workflow_json) return;
            const enriched = injectLiveApiKeyIntoWorkflowJson(pendingUploadedWorkflowJson.workflow_json);
            const jsonStr = JSON.stringify(enriched, null, 2);
            await copyInternalApiText(jsonStr, 'Auto-Injected Workflow JSON (Press Ctrl+V on your n8n canvas!)');
        }

        function analyzeN8nWorkflowJsonClient(wfJson) {
            const wf = (wfJson && typeof wfJson === 'object') ? wfJson : {};
            const wfName = String(wf.name || 'Uploaded n8n Workflow').trim() || 'Uploaded n8n Workflow';
            const nodes = Array.isArray(wf.nodes) ? wf.nodes : [];
            let webhookPath = '';
            const events = {
                'email.received': false,
                'message.received': false,
                'comment.received': false,
                'sms.received': false,
                'sms.sent': false,
                'calendar.scheduled': false,
                'calendar.rescheduled': false,
                'calendar.cancelled': false,
                'contact.saved': false,
                'post.scheduled': false
            };
            const explicitTriggerEvents = { ...events };
            const detectedConditions = [];

            nodes.forEach(node => {
                if (!node || typeof node !== 'object') return;
                const nType = String(node.type || '').toLowerCase();
                const nName = String(node.name || '').toLowerCase();
                const params = (node.parameters && typeof node.parameters === 'object') ? node.parameters : {};

                if (nType.includes('webhook')) {
                    const pVal = String(params.path || node.webhookId || '').trim().replace(/^\/+|\/+$/g, '');
                    if (pVal && !webhookPath) webhookPath = pVal;
                    const pLow = pVal.toLowerCase();
                    if (pLow.includes('cancel') && ['cal', 'meet', 'appoint', 'zoom', 'team'].some(w => pLow.includes(w))) explicitTriggerEvents['calendar.cancelled'] = true;
                    if (pLow.includes('resched')) explicitTriggerEvents['calendar.rescheduled'] = true;
                    if ((pLow.includes('calendar') || pLow.includes('appointment') || pLow.includes('meeting')) && !pLow.includes('cancel') && !pLow.includes('resched')) explicitTriggerEvents['calendar.scheduled'] = true;
                    if (pLow.includes('comment')) explicitTriggerEvents['comment.received'] = true;
                    if (pLow.includes('sms-sent') || pLow.includes('sms_sent') || pLow.includes('outbound-sms')) explicitTriggerEvents['sms.sent'] = true;
                    if (pLow.includes('sms') && !explicitTriggerEvents['sms.sent']) explicitTriggerEvents['sms.received'] = true;
                    if ((pLow.includes('email') || pLow.includes('gmail')) && !pLow.includes('calendar') && !pLow.includes('appoint')) explicitTriggerEvents['email.received'] = true;
                    if (pLow.includes('message') || pLow.includes('dm') || pLow.includes('inbox')) explicitTriggerEvents['message.received'] = true;
                    if (pLow.includes('contact') || pLow.includes('crm')) explicitTriggerEvents['contact.saved'] = true;
                    if (pLow.includes('post') && !pLow.includes('comment')) explicitTriggerEvents['post.scheduled'] = true;
                }

                if (nType.endsWith('.if') || nName.includes('if')) {
                    const conds = params.conditions;
                    if (conds && typeof conds === 'object') {
                        Object.values(conds).forEach(cList => {
                            if (Array.isArray(cList)) {
                                cList.forEach(cItem => {
                                    if (cItem && typeof cItem === 'object') {
                                        const v1 = String(cItem.value1 || cItem.leftValue || '').trim();
                                        const opRaw = cItem.operation || (cItem.operator && cItem.operator.operation) || 'contains';
                                        const op = String(opRaw).trim();
                                        const v2 = String(cItem.value2 || cItem.rightValue || '').trim();
                                        const v1Low = v1.toLowerCase();
                                        const v2Low = v2.toLowerCase();
                                        if (v1Low.includes('.event') || v1Low.endsWith('event')) {
                                            Object.keys(explicitTriggerEvents).forEach(evKey => {
                                                if (v2Low.includes(evKey)) explicitTriggerEvents[evKey] = true;
                                            });
                                        }
                                        if (v1 || v2) {
                                            let fieldHint = 'text';
                                            ['account_name', 'platform', 'is_own_comment', 'is_reply_to_comment', 'has_reply_to_comment', 'has_reply_to_sms', 'subject', 'account_email', 'sender_email', 'author_name', 'participant_name', 'recipient_phone', 'sender_phone', 'message', 'body'].some(f => {
                                                if (v1Low.includes(f)) {
                                                    fieldHint = f;
                                                    return true;
                                                }
                                                return false;
                                            });
                                            if (v2 && !['has_reply_to_comment', 'has_reply_to_sms'].includes(fieldHint) && !v1Low.includes('.event')) {
                                                detectedConditions.push({ field: fieldHint, operation: op, value: v2 });
                                            }
                                        }
                                    }
                                });
                            }
                        });
                    }
                }
            });

            const rawLow = JSON.stringify(wf).toLowerCase();
            // Check explicit event string literals first (e.g. "calendar.cancelled", "calendar.rescheduled", etc.)
            Object.keys(explicitTriggerEvents).forEach(evKey => {
                if (rawLow.includes(`"${evKey}"`) || rawLow.includes(`'${evKey}'`)) {
                    explicitTriggerEvents[evKey] = true;
                }
            });

            // Also inspect trigger-field expressions referencing $('Webhook') or $json.body
            if (!Object.values(explicitTriggerEvents).some(Boolean)) {
                if (['cancellation_reason', 'meeting_url_status'].some(k => rawLow.includes(`body.${k}`))) {
                    explicitTriggerEvents['calendar.cancelled'] = true;
                }
                if (['reschedule_reason', 'restructured_message_body', 'previous_date_str', 'previous_display_date', 'old_display_date'].some(k => rawLow.includes(`body.${k}`))) {
                    explicitTriggerEvents['calendar.rescheduled'] = true;
                }
                if (['meeting_platform', 'primary_guest_email', 'start_iso', 'date_str'].some(k => rawLow.includes(`body.${k}`)) && !explicitTriggerEvents['calendar.cancelled'] && !explicitTriggerEvents['calendar.rescheduled']) {
                    explicitTriggerEvents['calendar.scheduled'] = true;
                }
                if (['comment_id', 'is_own_comment', 'is_reply_to_comment'].some(k => rawLow.includes(`body.${k}`))) {
                    explicitTriggerEvents['comment.received'] = true;
                }
                if (['recipient_phone', 'sim_subscription_id'].some(k => rawLow.includes(`body.${k}`)) || rawLow.includes('/sms/thread-status')) {
                    explicitTriggerEvents['sms.sent'] = true;
                }
                if (['sender_phone'].some(k => rawLow.includes(`body.${k}`))) {
                    explicitTriggerEvents['sms.received'] = true;
                }
                if (['thread_id', 'account_email', 'sender_email'].some(k => rawLow.includes(`body.${k}`))) {
                    explicitTriggerEvents['email.received'] = true;
                }
                if (['conversation_id', 'participant_id'].some(k => rawLow.includes(`body.${k}`)) && !explicitTriggerEvents['sms.sent'] && !explicitTriggerEvents['sms.received']) {
                    explicitTriggerEvents['message.received'] = true;
                }
                if (rawLow.includes('body.contact')) {
                    explicitTriggerEvents['contact.saved'] = true;
                }
                if (rawLow.includes('body.queued_posts')) {
                    explicitTriggerEvents['post.scheduled'] = true;
                }
            }

            if (Object.values(explicitTriggerEvents).some(Boolean)) {
                Object.assign(events, explicitTriggerEvents);
            } else {
                // Fallback to broader action/keyword heuristics only when no explicit trigger event was found
                if (['calendar.cancelled', '/calendar/cancel', 'cancellation_reason'].some(k => rawLow.includes(k))) {
                    events['calendar.cancelled'] = true;
                }
                if (['calendar.rescheduled', '/calendar/reschedule', 'reschedule_reason', 'restructured_message_body', 'previous_date_str'].some(k => rawLow.includes(k))) {
                    events['calendar.rescheduled'] = true;
                }
                if (['calendar.scheduled', '/calendar/schedule', '/api/v1/calendar', 'glennbot-calendar', 'meeting_platform', 'start_iso'].some(k => rawLow.includes(k)) && !events['calendar.cancelled'] && !events['calendar.rescheduled']) {
                    events['calendar.scheduled'] = true;
                }
                if (['/comments/reply', '/comments/like', '/comments/hide', '/comments/thread-status', '/api/v1/comments', 'comment_id', 'is_own_comment', 'comment.received', 'glennbot-comment', 'comment-autodm'].some(k => rawLow.includes(k))) {
                    events['comment.received'] = true;
                }
                if (['sms.sent', 'recipient_phone', '/sms/thread-status'].some(k => rawLow.includes(k))) {
                    events['sms.sent'] = true;
                }
                if (['sms.received', 'sender_phone', '/sms/send', 'textbee'].some(k => rawLow.includes(k)) && !events['sms.sent']) {
                    events['sms.received'] = true;
                }
                if (['/messages/send', '/api/v1/messages', 'conversation_id', 'participant_id', 'message.received', 'glennbot-message'].some(k => rawLow.includes(k))) {
                    events['message.received'] = true;
                }
                if (['/emails/send', '/api/v1/emails', 'sender_email', 'account_email', 'thread_id', 'email.received', 'glennbot-email', 'gmail'].some(k => rawLow.includes(k)) && !events['calendar.scheduled'] && !events['calendar.rescheduled'] && !events['calendar.cancelled']) {
                    events['email.received'] = true;
                }
                if (['/contacts', 'contact.saved', 'glennbot-contact'].some(k => rawLow.includes(k)) && !Object.values(events).some(Boolean)) {
                    events['contact.saved'] = true;
                }
                if (['/posts/schedule', '/api/v1/posts', 'queued_posts', 'post.scheduled', 'glennbot-post'].some(k => rawLow.includes(k)) && !Object.values(events).some(Boolean)) {
                    events['post.scheduled'] = true;
                }
            }

            if (!Object.values(events).some(Boolean)) {
                events['comment.received'] = true;
            }

            return {
                name: wfName,
                webhook_path: webhookPath,
                events,
                detected_conditions: detectedConditions,
                node_count: nodes.length
            };
        }

        function guessN8nWebhookUrlFromPath(webhookPath) {
            if (!webhookPath) return '';
            const cleanPath = webhookPath.replace(/^\/+/, '');
            for (const wf of currentN8nWorkflows) {
                const u = String(wf.webhook_url || '').trim();
                const m = u.match(/^(https?:\/\/[^/]+\/webhook(?:-test)?)\//i);
                if (m && m[1]) {
                    return `${m[1]}/${cleanPath}`;
                }
            }
            return `http://localhost:5678/webhook/${cleanPath}`;
        }

        function renderN8nWorkflowsList(workflows) {
            currentN8nWorkflows = Array.isArray(workflows) ? workflows : [];
            const container = document.getElementById('iapi-workflows-list-container');
            const badge = document.getElementById('iapi-workflows-count-badge');
            if (badge) {
                const activeCount = currentN8nWorkflows.filter(w => w.enabled !== false && String(w.webhook_url || '').startsWith('http')).length;
                badge.textContent = `${currentN8nWorkflows.length} Workflow${currentN8nWorkflows.length === 1 ? '' : 's'} (${activeCount} Live)`;
            }
            if (!container) return;

            if (!currentN8nWorkflows.length) {
                container.innerHTML = `<div class="p-6 text-center text-xs text-slate-400 bg-slate-950/60 rounded-xl border border-slate-800">No saved n8n Workflow Automations yet. Click <strong>Upload Workflow .json</strong> above to get started!</div>`;
                return;
            }

            container.innerHTML = currentN8nWorkflows.map((wf, idx) => {
                const wfId = escapeHTML(wf.id || `wf_${idx}`);
                const isEnabled = wf.enabled !== false;
                const evts = (wf.events && typeof wf.events === 'object') ? wf.events : {};
                const conds = Array.isArray(wf.detected_conditions) ? wf.detected_conditions : [];
                const whPath = String(wf.webhook_path || '').trim();
                const whUrl = String(wf.webhook_url || '').trim();
                const hasUrl = whUrl.startsWith('http');
                const autoInjectedObj = injectLiveApiKeyIntoWorkflowJson(wf.workflow_json || {});
                const autoInjectedStr = JSON.stringify(autoInjectedObj, null, 2);

                const condBadgesHtml = conds.map(c =>
                    `<span class="px-2 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/40 font-mono text-[10px]"><i class="fas fa-filter mr-1"></i>${escapeHTML(c.field || 'field')} ${escapeHTML(c.operation || 'contains')} "${escapeHTML(c.value || '')}"</span>`
                ).join('');

                return `
                <div class="p-4 rounded-xl bg-slate-950/95 border ${isEnabled && hasUrl ? 'border-emerald-500/50 shadow-[0_0_20px_rgba(16,185,129,0.08)]' : 'border-slate-800'} space-y-3 transition-all">
                    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 border-b border-slate-800/90 pb-2.5">
                        <div class="space-y-1 min-w-0 flex-1">
                            <div class="flex items-center gap-2 flex-wrap">
                                <span class="px-2 py-0.5 rounded-md ${isEnabled && hasUrl ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40' : 'bg-amber-500/20 text-amber-300 border border-amber-500/40'} text-[10px] font-extrabold">
                                    ${isEnabled ? (hasUrl ? '● ACTIVE' : '● NEEDS WEBHOOK URL') : '○ PAUSED'}
                                </span>
                                <input type="text" id="wf-name-${wfId}" value="${escapeHTML(wf.name || 'n8n Workflow')}" class="bg-transparent border-b border-transparent hover:border-slate-700 focus:border-gb-cyan text-xs sm:text-sm font-extrabold text-white focus:outline-none px-1 py-0.5 min-w-[220px] sm:min-w-[320px]">
                            </div>
                            <div class="flex flex-wrap items-center gap-1.5 pt-0.5">
                                ${whPath ? `<span class="px-2 py-0.5 rounded bg-gb-cyan/15 text-gb-cyan border border-gb-cyan/40 font-mono text-[10px]"><i class="fas fa-link mr-1"></i>Path: /webhook/${escapeHTML(whPath)}</span>` : ''}
                                <span class="px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/40 font-mono text-[10px]"><i class="fas fa-key mr-1"></i>API Key &amp; URL Auto-Injected</span>
                                ${condBadgesHtml}
                            </div>
                        </div>

                        <div class="flex flex-wrap items-center gap-2 shrink-0">
                            <label class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-[11px] font-bold text-slate-200 cursor-pointer">
                                <input type="checkbox" id="wf-enabled-${wfId}" ${isEnabled ? 'checked' : ''} onchange="saveSingleN8nWorkflowCard('${wfId}')" class="accent-emerald-400">
                                <span>Enabled</span>
                            </label>
                            <input type="file" id="wf-reupload-${wfId}" accept=".json,application/json" class="hidden" onchange="handleUploadN8nWorkflowFile(this, '${wfId}')">
                            <button type="button" onclick="document.getElementById('wf-reupload-${wfId}').click()" class="px-2.5 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-200 text-[11px] font-semibold flex items-center gap-1 cursor-pointer" title="Upload a new .json file to update this workflow (Python will auto-inject your API Key & URLs!)">
                                <i class="fas fa-file-upload text-emerald-400"></i>
                                <span>Upload .json</span>
                            </button>
                            <button type="button" onclick="copyWorkflowCardJson('${wfId}')" class="px-2.5 py-1.5 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-400/60 text-emerald-200 text-[11px] font-bold flex items-center gap-1 cursor-pointer" title="Copy Auto-Injected Workflow JSON to clipboard (Press Ctrl+V on n8n canvas)">
                                <i class="fas fa-copy"></i>
                                <span>Copy JSON (Ctrl+V in n8n)</span>
                            </button>
                            <button type="button" onclick="downloadWorkflowCardJson('${wfId}')" class="px-2.5 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 border border-gb-cyan/40 text-gb-cyan text-[11px] font-bold flex items-center gap-1 cursor-pointer" title="Download this workflow as a .json file">
                                <i class="fas fa-download"></i>
                                <span>.json</span>
                            </button>
                            <button type="button" onclick="deleteSingleN8nWorkflowCard('${wfId}')" class="px-2.5 py-1.5 rounded-lg bg-rose-950/60 hover:bg-rose-900/80 border border-rose-500/50 text-rose-300 text-[11px] font-bold flex items-center gap-1 cursor-pointer" title="Delete Workflow from Dashboard & Cloudinary">
                                <i class="fas fa-trash-alt"></i>
                                <span>Delete</span>
                            </button>
                        </div>
                    </div>

                    <!-- Per-Workflow Webhook Trigger URL -->
                    <div class="space-y-1">
                        <label class="text-[11px] font-semibold text-slate-300 flex items-center justify-between">
                            <span>n8n Webhook Trigger URL (POST) for this Workflow:</span>
                            ${whPath && !whUrl ? `<span class="text-[10px] text-amber-300">Paste your n8n URL ending in <code class="font-mono">/webhook/${escapeHTML(whPath)}</code></span>` : ''}
                        </label>
                        <input type="text" id="wf-url-${wfId}" value="${escapeHTML(whUrl)}" placeholder="https://your-workspace.app.n8n.cloud/webhook/${escapeHTML(whPath || 'glennbot-webhook')}" class="w-full bg-slate-900 border border-slate-700 focus:border-gb-cyan rounded-xl px-3 py-2 text-xs text-white font-mono focus:outline-none">
                    </div>

                    <!-- Per-Workflow Events to Forward to n8n -->
                    <div class="space-y-1.5">
                        <span class="text-[11px] font-semibold text-slate-300 block">Events to Forward to n8n for this Workflow (Auto-Detected from JSON):</span>
                        <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-1.5 text-[11px]">
                            <label class="flex items-center gap-1.5 p-2 rounded-lg bg-slate-900/90 border ${evts['email.received'] ? 'border-gb-cyan/50 text-white' : 'border-slate-800 text-slate-400'} cursor-pointer">
                                <input type="checkbox" id="wf-evt-email-${wfId}" ${evts['email.received'] ? 'checked' : ''} class="accent-cyan-400">
                                <span>Email (<code class="text-gb-cyan text-[9px]">email.received</code>)</span>
                            </label>
                            <label class="flex items-center gap-1.5 p-2 rounded-lg bg-slate-900/90 border ${evts['comment.received'] ? 'border-gb-cyan/50 text-white' : 'border-slate-800 text-slate-400'} cursor-pointer">
                                <input type="checkbox" id="wf-evt-comment-${wfId}" ${evts['comment.received'] ? 'checked' : ''} class="accent-cyan-400">
                                <span>Comment (<code class="text-gb-cyan text-[9px]">comment.received</code>)</span>
                            </label>
                            <label class="flex items-center gap-1.5 p-2 rounded-lg bg-slate-900/90 border ${evts['message.received'] ? 'border-gb-cyan/50 text-white' : 'border-slate-800 text-slate-400'} cursor-pointer">
                                <input type="checkbox" id="wf-evt-message-${wfId}" ${evts['message.received'] ? 'checked' : ''} class="accent-cyan-400">
                                <span>Chat DM (<code class="text-gb-cyan text-[9px]">message.received</code>)</span>
                            </label>
                            <label class="flex items-center gap-1.5 p-2 rounded-lg bg-slate-900/90 border ${evts['sms.received'] ? 'border-gb-cyan/50 text-white' : 'border-slate-800 text-slate-400'} cursor-pointer">
                                <input type="checkbox" id="wf-evt-sms-received-${wfId}" ${evts['sms.received'] ? 'checked' : ''} class="accent-cyan-400">
                                <span>SMS In (<code class="text-gb-cyan text-[9px]">sms.received</code>)</span>
                            </label>
                            <label class="flex items-center gap-1.5 p-2 rounded-lg bg-slate-900/90 border ${evts['sms.sent'] ? 'border-gb-cyan/50 text-white' : 'border-slate-800 text-slate-400'} cursor-pointer">
                                <input type="checkbox" id="wf-evt-sms-sent-${wfId}" ${evts['sms.sent'] ? 'checked' : ''} class="accent-cyan-400">
                                <span>SMS Out (<code class="text-gb-cyan text-[9px]">sms.sent</code>)</span>
                            </label>
                            <label class="flex items-center gap-1.5 p-2 rounded-lg bg-slate-900/90 border ${evts['calendar.scheduled'] ? 'border-emerald-400/50 text-white' : 'border-slate-800 text-slate-400'} cursor-pointer">
                                <input type="checkbox" id="wf-evt-cal-scheduled-${wfId}" ${evts['calendar.scheduled'] ? 'checked' : ''} class="accent-emerald-400">
                                <span>Appt Booked (<code class="text-emerald-300 text-[9px]">calendar.scheduled</code>)</span>
                            </label>
                            <label class="flex items-center gap-1.5 p-2 rounded-lg bg-slate-900/90 border ${evts['calendar.rescheduled'] ? 'border-amber-400/50 text-white' : 'border-slate-800 text-slate-400'} cursor-pointer">
                                <input type="checkbox" id="wf-evt-cal-rescheduled-${wfId}" ${evts['calendar.rescheduled'] ? 'checked' : ''} class="accent-amber-400">
                                <span>Rescheduled (<code class="text-amber-300 text-[9px]">calendar.rescheduled</code>)</span>
                            </label>
                            <label class="flex items-center gap-1.5 p-2 rounded-lg bg-slate-900/90 border ${evts['calendar.cancelled'] ? 'border-rose-400/50 text-white' : 'border-slate-800 text-slate-400'} cursor-pointer">
                                <input type="checkbox" id="wf-evt-cal-cancelled-${wfId}" ${evts['calendar.cancelled'] ? 'checked' : ''} class="accent-rose-400">
                                <span>Cancelled (<code class="text-rose-300 text-[9px]">calendar.cancelled</code>)</span>
                            </label>
                            <label class="flex items-center gap-1.5 p-2 rounded-lg bg-slate-900/90 border ${evts['contact.saved'] ? 'border-gb-cyan/50 text-white' : 'border-slate-800 text-slate-400'} cursor-pointer">
                                <input type="checkbox" id="wf-evt-contact-${wfId}" ${evts['contact.saved'] ? 'checked' : ''} class="accent-cyan-400">
                                <span>Contact (<code class="text-gb-cyan text-[9px]">contact.saved</code>)</span>
                            </label>
                            <label class="flex items-center gap-1.5 p-2 rounded-lg bg-slate-900/90 border ${evts['post.scheduled'] ? 'border-gb-cyan/50 text-white' : 'border-slate-800 text-slate-400'} cursor-pointer">
                                <input type="checkbox" id="wf-evt-post-${wfId}" ${evts['post.scheduled'] ? 'checked' : ''} class="accent-cyan-400">
                                <span>Post (<code class="text-gb-cyan text-[9px]">post.scheduled</code>)</span>
                            </label>
                        </div>
                    </div>

                    <!-- Auto-Injected Ready-to-Copy Canvas JSON Box -->
                    <div class="space-y-1">
                        <span class="text-[10px] text-slate-400 font-semibold block">
                            <i class="fas fa-code text-emerald-400 mr-1"></i>Auto-Injected Canvas JSON (Pre-injected with <code class="text-emerald-300">X-API-Key</code> &amp; <code class="text-gb-cyan">/api/v1/*</code> URL — Click box to Copy, then press <code class="text-emerald-300">Ctrl+V</code> on the n8n canvas):
                        </span>
                        <textarea id="wf-json-box-${wfId}" readonly onclick="this.select(); document.execCommand('copy'); showToast('✅ Copied Auto-Injected Workflow JSON! Press Ctrl+V in n8n.');" class="w-full h-24 p-2.5 rounded-lg bg-slate-900 border border-slate-800 text-[11px] font-mono text-emerald-300 focus:outline-none focus:border-emerald-400 cursor-pointer">${escapeHTML(autoInjectedStr)}</textarea>
                    </div>

                    <!-- Card Footer Actions -->
                    <div class="pt-1 flex flex-wrap items-center justify-end gap-2">
                        <button type="button" id="btn-test-wf-${wfId}" onclick="testSingleN8nWorkflowCard('${wfId}')" class="px-3.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-gb-cyan/50 text-gb-cyan font-bold text-xs flex items-center gap-1.5 transition-all cursor-pointer">
                            <i class="fas fa-paper-plane"></i>
                            <span>Test This Workflow (Auto-Payload)</span>
                        </button>
                        <button type="button" id="btn-save-wf-${wfId}" onclick="saveSingleN8nWorkflowCard('${wfId}')" class="px-4 py-1.5 rounded-xl bg-gradient-to-r from-gb-blue to-gb-cyan text-slate-950 font-extrabold text-xs flex items-center gap-1.5 transition-all cursor-pointer">
                            <i class="fas fa-save"></i>
                            <span>Save Workflow Settings</span>
                        </button>
                    </div>
                </div>
                `;
            }).join('');
        }

        async function handleUploadN8nWorkflowFile(inputEl, targetWorkflowId = null) {
            const file = inputEl && inputEl.files && inputEl.files[0];
            if (!file) return;
            try {
                const rawText = await file.text();
                let parsed = null;
                try {
                    parsed = JSON.parse(rawText);
                } catch (_) {
                    showToast('⚠️ Invalid .json file. Make sure it is a valid n8n Workflow JSON.');
                    inputEl.value = '';
                    return;
                }

                let enrichedJson = injectLiveApiKeyIntoWorkflowJson(parsed);
                let analysis = analyzeN8nWorkflowJsonClient(enrichedJson);
                try {
                    const res = await fetch('/api/internal-api/n8n-workflows/analyze', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ workflow_json: enrichedJson })
                    });
                    const data = await res.json();
                    if (data.status === 'success') {
                        if (data.patched_workflow_json) {
                            enrichedJson = data.patched_workflow_json;
                        }
                        if (data.analysis) {
                            analysis = data.analysis;
                        }
                    }
                } catch (_) {}

                // If re-uploading into an existing workflow card, keep the user's manual card name!
                if (targetWorkflowId) {
                    const existing = currentN8nWorkflows.find(w => String(w.id) === String(targetWorkflowId));
                    const nameInputCard = document.getElementById(`wf-name-${targetWorkflowId}`);
                    const preservedName = (nameInputCard ? nameInputCard.value : (existing?.name || '')).trim() || 'Custom n8n Workflow';
                    const urlInput = document.getElementById(`wf-url-${targetWorkflowId}`);
                    const currentUrl = (urlInput ? urlInput.value : (existing?.webhook_url || '')).trim();
                    const saveRes = await fetch('/api/internal-api/n8n-workflows/save', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            id: targetWorkflowId,
                            name: preservedName,
                            enabled: existing ? existing.enabled !== false : true,
                            webhook_url: currentUrl || guessN8nWebhookUrlFromPath(analysis.webhook_path),
                            webhook_path: analysis.webhook_path || '',
                            events: analysis.events,
                            detected_conditions: analysis.detected_conditions || [],
                            workflow_json: enrichedJson
                        })
                    });
                    const saveData = await saveRes.json();
                    if (saveData.status === 'success') {
                        renderN8nWorkflowsList(saveData.n8n_workflows || []);
                        showToast(`✅ Auto-injected API Key & URLs into '${preservedName}' (Saved to Cloudinary)!`);
                    }
                    inputEl.value = '';
                    return;
                }

                // Otherwise open the New Uploaded Workflow preview panel
                pendingUploadedWorkflowJson = {
                    workflow_json: enrichedJson,
                    analysis
                };

                const panel = document.getElementById('iapi-new-wf-form-panel');
                if (panel) panel.classList.remove('hidden');

                const previewBox = document.getElementById('iapi-new-wf-json-preview');
                if (previewBox) {
                    previewBox.value = JSON.stringify(enrichedJson, null, 2);
                }

                // Leave Workflow Name empty and focus it so the user manually enters what this workflow is for!
                const nameInput = document.getElementById('iapi-new-wf-name');
                if (nameInput) {
                    nameInput.value = '';
                    setTimeout(() => nameInput.focus(), 60);
                }

                const urlInput = document.getElementById('iapi-new-wf-url');
                if (urlInput) {
                    const guessed = guessN8nWebhookUrlFromPath(analysis.webhook_path);
                    urlInput.value = guessed;
                    if (analysis.webhook_path) {
                        urlInput.placeholder = `https://your-workspace.app.n8n.cloud/webhook/${analysis.webhook_path}`;
                    }
                }

                const mapEvt = {
                    'iapi-new-wf-evt-email': 'email.received',
                    'iapi-new-wf-evt-message': 'message.received',
                    'iapi-new-wf-evt-comment': 'comment.received',
                    'iapi-new-wf-evt-sms-received': 'sms.received',
                    'iapi-new-wf-evt-sms-sent': 'sms.sent',
                    'iapi-new-wf-evt-cal-scheduled': 'calendar.scheduled',
                    'iapi-new-wf-evt-cal-rescheduled': 'calendar.rescheduled',
                    'iapi-new-wf-evt-cal-cancelled': 'calendar.cancelled',
                    'iapi-new-wf-evt-contact': 'contact.saved',
                    'iapi-new-wf-evt-post': 'post.scheduled'
                };
                Object.entries(mapEvt).forEach(([elId, evtKey]) => {
                    const el = document.getElementById(elId);
                    if (el) el.checked = Boolean(analysis.events && analysis.events[evtKey]);
                });

                const badgesEl = document.getElementById('iapi-new-wf-detected-badges');
                if (badgesEl) {
                    const badges = [];
                    badges.push(`<span class="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 text-[10px] font-bold"><i class="fas fa-check mr-1"></i>API Key &amp; URLs Auto-Injected (${Number(analysis.node_count || 0)} Nodes)</span>`);
                    if (analysis.webhook_path) {
                        badges.push(`<span class="px-2 py-0.5 rounded bg-gb-cyan/15 text-gb-cyan border border-gb-cyan/40 font-mono text-[10px]"><i class="fas fa-link mr-1"></i>Detected Webhook Path: /webhook/${escapeHTML(analysis.webhook_path)}</span>`);
                    }
                    (analysis.detected_conditions || []).forEach(c => {
                        badges.push(`<span class="px-2 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/40 font-mono text-[10px]"><i class="fas fa-filter mr-1"></i>Auto-Detected Condition: ${escapeHTML(c.field)} ${escapeHTML(c.operation)} "${escapeHTML(c.value)}"</span>`);
                    });
                    badgesEl.innerHTML = badges.join('');
                }

                showToast(`✅ Uploaded '${file.name}'! Enter a workflow name below and click Save.`);
            } catch (err) {
                showToast('⚠️ Could not read workflow .json file.');
            } finally {
                inputEl.value = '';
            }
        }

        function cancelNewUploadedWorkflowForm() {
            pendingUploadedWorkflowJson = null;
            const panel = document.getElementById('iapi-new-wf-form-panel');
            if (panel) panel.classList.add('hidden');
        }

        async function saveNewUploadedN8nWorkflow() {
            const btn = document.getElementById('btn-save-new-uploaded-wf');
            const nameInput = document.getElementById('iapi-new-wf-name');
            const nameVal = (nameInput?.value || '').trim();
            if (!nameVal) {
                showToast('⚠️ Please enter a name describing this workflow before saving!');
                if (nameInput) nameInput.focus();
                return;
            }
            const urlVal = (document.getElementById('iapi-new-wf-url')?.value || '').trim();
            const events = {
                'email.received': Boolean(document.getElementById('iapi-new-wf-evt-email')?.checked),
                'message.received': Boolean(document.getElementById('iapi-new-wf-evt-message')?.checked),
                'comment.received': Boolean(document.getElementById('iapi-new-wf-evt-comment')?.checked),
                'sms.received': Boolean(document.getElementById('iapi-new-wf-evt-sms-received')?.checked),
                'sms.sent': Boolean(document.getElementById('iapi-new-wf-evt-sms-sent')?.checked),
                'calendar.scheduled': Boolean(document.getElementById('iapi-new-wf-evt-cal-scheduled')?.checked),
                'calendar.rescheduled': Boolean(document.getElementById('iapi-new-wf-evt-cal-rescheduled')?.checked),
                'calendar.cancelled': Boolean(document.getElementById('iapi-new-wf-evt-cal-cancelled')?.checked),
                'contact.saved': Boolean(document.getElementById('iapi-new-wf-evt-contact')?.checked),
                'post.scheduled': Boolean(document.getElementById('iapi-new-wf-evt-post')?.checked)
            };
            const wfJson = pendingUploadedWorkflowJson ? pendingUploadedWorkflowJson.workflow_json : {};
            if (wfJson && typeof wfJson === 'object') {
                wfJson.name = nameVal;
            }
            const analysis = pendingUploadedWorkflowJson ? pendingUploadedWorkflowJson.analysis : {};

            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Saving to Cloudinary...`;
            }
            try {
                const res = await fetch('/api/internal-api/n8n-workflows/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: nameVal,
                        enabled: true,
                        webhook_url: urlVal,
                        webhook_path: analysis.webhook_path || '',
                        events,
                        detected_conditions: analysis.detected_conditions || [],
                        workflow_json: wfJson
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    cancelNewUploadedWorkflowForm();
                    renderN8nWorkflowsList(data.n8n_workflows || []);
                    showToast(`✅ Saved '${nameVal}' to Database & Cloudinary!`);
                } else {
                    showToast('⚠️ ' + (data.message || 'Could not save workflow.'));
                }
            } catch (_) {
                showToast('⚠️ Network error while saving workflow.');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<i class="fas fa-check-circle"></i> <span>Save & Activate Workflow Automation</span>`;
                }
            }
        }

        async function saveSingleN8nWorkflowCard(wfId) {
            const existing = currentN8nWorkflows.find(w => String(w.id) === String(wfId));
            if (!existing) return;
            const btn = document.getElementById(`btn-save-wf-${wfId}`);
            const nameVal = (document.getElementById(`wf-name-${wfId}`)?.value || existing.name || 'n8n Workflow').trim();
            const urlVal = (document.getElementById(`wf-url-${wfId}`)?.value || '').trim();
            const enabledVal = Boolean(document.getElementById(`wf-enabled-${wfId}`)?.checked);
            const events = {
                'email.received': Boolean(document.getElementById(`wf-evt-email-${wfId}`)?.checked),
                'comment.received': Boolean(document.getElementById(`wf-evt-comment-${wfId}`)?.checked),
                'message.received': Boolean(document.getElementById(`wf-evt-message-${wfId}`)?.checked),
                'sms.received': Boolean(document.getElementById(`wf-evt-sms-received-${wfId}`)?.checked),
                'sms.sent': Boolean(document.getElementById(`wf-evt-sms-sent-${wfId}`)?.checked),
                'calendar.scheduled': Boolean(document.getElementById(`wf-evt-cal-scheduled-${wfId}`)?.checked),
                'calendar.rescheduled': Boolean(document.getElementById(`wf-evt-cal-rescheduled-${wfId}`)?.checked),
                'calendar.cancelled': Boolean(document.getElementById(`wf-evt-cal-cancelled-${wfId}`)?.checked),
                'contact.saved': Boolean(document.getElementById(`wf-evt-contact-${wfId}`)?.checked),
                'post.scheduled': Boolean(document.getElementById(`wf-evt-post-${wfId}`)?.checked)
            };
            const globalSec = (document.getElementById('iapi-n8n-webhook-secret')?.value || '').trim();

            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Saving...`;
            }
            try {
                const res = await fetch('/api/internal-api/n8n-workflows/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        id: wfId,
                        name: nameVal,
                        enabled: enabledVal,
                        webhook_url: urlVal,
                        webhook_path: existing.webhook_path || '',
                        webhook_secret: existing.webhook_secret || '',
                        events,
                        detected_conditions: existing.detected_conditions || [],
                        workflow_json: existing.workflow_json || {},
                        global_webhook_secret: globalSec
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    renderN8nWorkflowsList(data.n8n_workflows || []);
                    showToast(`✅ Saved settings for '${nameVal}'!`);
                } else {
                    showToast('⚠️ ' + (data.message || 'Could not save workflow settings.'));
                }
            } catch (_) {
                showToast('⚠️ Network error while saving workflow settings.');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<i class="fas fa-save"></i> <span>Save Workflow Settings</span>`;
                }
            }
        }

        async function testSingleN8nWorkflowCard(wfId) {
            const existing = currentN8nWorkflows.find(w => String(w.id) === String(wfId));
            const btn = document.getElementById(`btn-test-wf-${wfId}`);
            const urlVal = (document.getElementById(`wf-url-${wfId}`)?.value || existing?.webhook_url || '').trim();
            if (!urlVal || !urlVal.startsWith('http')) {
                showToast('⚠️ Paste your n8n Webhook Trigger URL (POST) in this workflow card first!');
                return;
            }
            const checkedEvts = {
                'email.received': Boolean(document.getElementById(`wf-evt-email-${wfId}`)?.checked),
                'comment.received': Boolean(document.getElementById(`wf-evt-comment-${wfId}`)?.checked),
                'message.received': Boolean(document.getElementById(`wf-evt-message-${wfId}`)?.checked),
                'sms.received': Boolean(document.getElementById(`wf-evt-sms-received-${wfId}`)?.checked),
                'sms.sent': Boolean(document.getElementById(`wf-evt-sms-sent-${wfId}`)?.checked),
                'calendar.scheduled': Boolean(document.getElementById(`wf-evt-cal-scheduled-${wfId}`)?.checked),
                'calendar.rescheduled': Boolean(document.getElementById(`wf-evt-cal-rescheduled-${wfId}`)?.checked),
                'calendar.cancelled': Boolean(document.getElementById(`wf-evt-cal-cancelled-${wfId}`)?.checked),
                'contact.saved': Boolean(document.getElementById(`wf-evt-contact-${wfId}`)?.checked),
                'post.scheduled': Boolean(document.getElementById(`wf-evt-post-${wfId}`)?.checked)
            };
            const primaryEvent = Object.keys(checkedEvts).find(k => checkedEvts[k]) || 'comment.received';

            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Testing...`;
            }
            try {
                const res = await fetch('/api/internal-api/n8n-webhook/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        workflow_id: wfId,
                        n8n_webhook_url: urlVal,
                        event_type: primaryEvent
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast(`✅ ${data.message}`);
                    await loadInternalApiConfig();
                } else {
                    showToast('⚠️ ' + (data.message || 'Failed to test workflow webhook.'));
                }
            } catch (_) {
                showToast('⚠️ Network error while testing workflow webhook.');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<i class="fas fa-paper-plane"></i> <span>Test This Workflow (Auto-Payload)</span>`;
                }
            }
        }

        async function deleteSingleN8nWorkflowCard(wfId) {
            if (!wfId) return;
            try {
                const res = await fetch(`/api/internal-api/n8n-workflows/${encodeURIComponent(wfId)}`, { method: 'DELETE' });
                const data = await res.json();
                if (data.status === 'success') {
                    renderN8nWorkflowsList(data.n8n_workflows || []);
                    showToast('🗑️ Workflow automation deleted from Dashboard & Cloudinary!');
                }
            } catch (_) {
                showToast('⚠️ Could not delete workflow automation.');
            }
        }

        async function copyWorkflowCardJson(wfId) {
            const existing = currentN8nWorkflows.find(w => String(w.id) === String(wfId));
            if (!existing || !existing.workflow_json) {
                showToast('⚠️ No workflow JSON stored on this card.');
                return;
            }
            const enriched = injectLiveApiKeyIntoWorkflowJson(existing.workflow_json);
            const jsonStr = JSON.stringify(enriched, null, 2);
            await copyInternalApiText(jsonStr, `${existing.name || 'Workflow'} JSON (Press Ctrl+V on your n8n canvas!)`);
        }

        function downloadWorkflowCardJson(wfId) {
            const existing = currentN8nWorkflows.find(w => String(w.id) === String(wfId));
            if (!existing || !existing.workflow_json) {
                showToast('⚠️ No workflow JSON stored on this card.');
                return;
            }
            const enriched = injectLiveApiKeyIntoWorkflowJson(existing.workflow_json);
            const jsonStr = JSON.stringify(enriched, null, 2);
            const slug = String(existing.webhook_path || existing.name || 'n8n-workflow').toLowerCase().replace(/[^a-z0-9-_]+/g, '-').replace(/^-+|-+$/g, '');
            const blob = new Blob([jsonStr], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${slug || 'glennbot-workflow'}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            showToast(`✅ Downloaded ${slug || 'glennbot-workflow'}.json!`);
        }

        // =========================================================================
        // --- ASK AI: N8N WORKFLOW .JSON ARCHITECT ENGINE (GEMINI 3.5 FLASH) ---
        // =========================================================================
        let lastAiGeneratedN8nResult = null;
        let askAiN8nAttachedFiles = [];

        function openAskAiN8nModal() {
            openModalWithFade('ask-ai-n8n-modal');
            renderAskAiN8nAttachments();
            const promptEl = document.getElementById('ask-ai-n8n-prompt');
            setTimeout(() => {
                if (promptEl) promptEl.focus();
            }, 140);
        }

        function closeAskAiN8nModal() {
            closeModalWithFade('ask-ai-n8n-modal');
        }

        function _formatAskAiFileSize(bytes) {
            const n = Number(bytes || 0);
            if (n < 1024) return `${n} B`;
            if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
            return `${(n / (1024 * 1024)).toFixed(2)} MB`;
        }

        function _getAskAiFileIconClass(name, mimeType) {
            const lower = String(name || '').toLowerCase();
            const mime = String(mimeType || '').toLowerCase();
            if (mime.startsWith('image/') || /\.(png|jpe?g|webp|gif|bmp|svg|heic)$/i.test(lower)) return 'fa-file-image text-pink-400';
            if (mime === 'application/pdf' || lower.endsWith('.pdf')) return 'fa-file-pdf text-rose-400';
            if (/\.(xlsx|xls|csv|tsv)$/i.test(lower) || mime.includes('spreadsheet') || mime.includes('excel') || mime.includes('csv')) return 'fa-file-excel text-emerald-400';
            if (/\.(docx|doc)$/i.test(lower) || mime.includes('word')) return 'fa-file-word text-sky-400';
            if (/\.(json|js|ts|py|html|xml|yaml|yml)$/i.test(lower) || mime.includes('json')) return 'fa-file-code text-amber-300';
            if (mime.startsWith('audio/')) return 'fa-file-audio text-purple-400';
            if (mime.startsWith('video/')) return 'fa-file-video text-cyan-400';
            return 'fa-file-alt text-gb-cyan';
        }

        function _isAskAiTextReadableFile(name, mimeType) {
            const lower = String(name || '').toLowerCase();
            const mime = String(mimeType || '').toLowerCase();
            if (mime.startsWith('text/')) return true;
            if (mime.includes('json') || mime.includes('xml') || mime.includes('javascript') || mime.includes('yaml') || mime.includes('csv')) return true;
            return /\.(txt|md|markdown|json|csv|tsv|xml|yaml|yml|html|htm|js|ts|jsx|tsx|py|sql|sh|bat|ini|conf|env|log)$/i.test(lower);
        }

        function _readFileAsDataUrl(file) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(String(reader.result || ''));
                reader.onerror = () => reject(new Error(`Failed to read file ${file.name}`));
                reader.readAsDataURL(file);
            });
        }

        function _readFileAsTextSafe(file) {
            return new Promise((resolve) => {
                const reader = new FileReader();
                reader.onload = () => resolve(String(reader.result || ''));
                reader.onerror = () => resolve('');
                reader.readAsText(file);
            });
        }

        async function processAskAiN8nFileList(fileList) {
            if (!fileList || !fileList.length) return;
            const maxFiles = 8;
            const maxFileBytes = 20 * 1024 * 1024; // 20 MB per file

            for (const file of Array.from(fileList)) {
                if (askAiN8nAttachedFiles.length >= maxFiles) {
                    showToast(`⚠️ Maximum of ${maxFiles} attached files reached.`);
                    break;
                }
                if (file.size > maxFileBytes) {
                    showToast(`⚠️ "${file.name}" is larger than 20 MB. Please attach a smaller file.`);
                    continue;
                }
                try {
                    const dataUrl = await _readFileAsDataUrl(file);
                    const commaIdx = dataUrl.indexOf(',');
                    const base64Clean = commaIdx >= 0 ? dataUrl.slice(commaIdx + 1) : dataUrl;
                    let textContent = '';
                    if (_isAskAiTextReadableFile(file.name, file.type)) {
                        textContent = await _readFileAsTextSafe(file);
                    }
                    const mimeType = file.type || (file.name.toLowerCase().endsWith('.json') ? 'application/json' : 'application/octet-stream');
                    askAiN8nAttachedFiles.push({
                        id: `att_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
                        name: file.name || 'attached-file',
                        mime_type: mimeType,
                        size: file.size || 0,
                        data_url: dataUrl,
                        data_base64: base64Clean,
                        text_content: textContent ? textContent.slice(0, 80000) : ''
                    });
                } catch (err) {
                    console.error('Error reading Ask AI attachment:', err);
                    showToast(`⚠️ Could not read file "${file.name}".`);
                }
            }
            renderAskAiN8nAttachments();
            if (askAiN8nAttachedFiles.length > 0) {
                showToast(`📎 Attached ${fileList.length} file(s) — Gemini 3.5 Flash will read & interpret them!`);
            }
        }

        async function handleAskAiN8nFilesSelected(inputEl) {
            if (!inputEl || !inputEl.files || !inputEl.files.length) return;
            await processAskAiN8nFileList(inputEl.files);
            inputEl.value = '';
        }

        async function handleAskAiN8nPaste(event) {
            const items = event?.clipboardData?.items;
            if (!items) return;
            const files = [];
            for (const item of Array.from(items)) {
                if (item.kind === 'file') {
                    const f = item.getAsFile();
                    if (f) files.push(f);
                }
            }
            if (files.length > 0) {
                await processAskAiN8nFileList(files);
            }
        }

        async function handleAskAiN8nDrop(event) {
            event.preventDefault();
            const promptEl = document.getElementById('ask-ai-n8n-prompt');
            if (promptEl) promptEl.classList.remove('border-gb-cyan', 'ring-1', 'ring-gb-cyan');
            const files = event?.dataTransfer?.files;
            if (files && files.length > 0) {
                await processAskAiN8nFileList(files);
            }
        }

        function removeAskAiN8nAttachment(attId) {
            askAiN8nAttachedFiles = askAiN8nAttachedFiles.filter(f => f.id !== attId);
            renderAskAiN8nAttachments();
        }

        function clearAskAiN8nAttachments() {
            askAiN8nAttachedFiles = [];
            const fileInput = document.getElementById('ask-ai-n8n-file-input');
            if (fileInput) fileInput.value = '';
            renderAskAiN8nAttachments();
        }

        function renderAskAiN8nAttachments() {
            const barEl = document.getElementById('ask-ai-n8n-attachments-bar');
            const listEl = document.getElementById('ask-ai-n8n-attachments-list');
            const countEl = document.getElementById('ask-ai-n8n-attachments-count');
            const badgeEl = document.getElementById('ask-ai-n8n-attach-badge');
            const attachBtn = document.getElementById('ask-ai-n8n-attach-btn');

            const count = askAiN8nAttachedFiles.length;
            if (countEl) countEl.textContent = String(count);

            if (badgeEl) {
                if (count > 0) {
                    badgeEl.textContent = String(count);
                    badgeEl.classList.remove('hidden');
                } else {
                    badgeEl.classList.add('hidden');
                }
            }
            if (attachBtn) {
                if (count > 0) {
                    attachBtn.classList.add('border-gb-cyan', 'bg-purple-950/50', 'text-gb-cyan');
                } else {
                    attachBtn.classList.remove('border-gb-cyan', 'bg-purple-950/50', 'text-gb-cyan');
                }
            }

            if (!barEl || !listEl) return;
            if (count === 0) {
                barEl.classList.add('hidden');
                listEl.innerHTML = '';
                return;
            }

            barEl.classList.remove('hidden');
            listEl.innerHTML = askAiN8nAttachedFiles.map(att => {
                const isImg = String(att.mime_type || '').toLowerCase().startsWith('image/') && att.data_url;
                const iconCls = _getAskAiFileIconClass(att.name, att.mime_type);
                const thumbHtml = isImg
                    ? `<img src="${att.data_url}" alt="${escapeHTML(att.name)}" class="w-8 h-8 rounded-lg object-cover border border-purple-400/50 shrink-0">`
                    : `<div class="w-8 h-8 rounded-lg bg-slate-800 border border-slate-700 flex items-center justify-center shrink-0"><i class="fas ${iconCls} text-xs"></i></div>`;
                return `
                    <div class="flex items-center gap-2 px-2.5 py-1.5 rounded-xl bg-slate-950/90 border border-slate-700/90 hover:border-purple-400/60 text-xs max-w-[260px] group">
                        ${thumbHtml}
                        <div class="min-w-0 flex-1">
                            <div class="text-[11px] font-bold text-slate-200 truncate" title="${escapeHTML(att.name)}">${escapeHTML(att.name)}</div>
                            <div class="text-[9px] text-slate-400 font-mono">${escapeHTML(_formatAskAiFileSize(att.size))}</div>
                        </div>
                        <button type="button" onclick="removeAskAiN8nAttachment('${escapeHTML(att.id)}')"
                            title="Remove attached file"
                            class="w-5 h-5 rounded-md bg-slate-800 hover:bg-rose-500/30 text-slate-400 hover:text-rose-300 flex items-center justify-center shrink-0 transition-all cursor-pointer">
                            <i class="fas fa-times text-[10px]"></i>
                        </button>
                    </div>
                `;
            }).join('');
        }

        function fillAskAiN8nPromptExample(presetKey) {
            const promptEl = document.getElementById('ask-ai-n8n-prompt');
            if (!promptEl) return;
            const examples = {
                comment_autodm: "Kapag may nag-comment sa Facebook o Instagram post na may keyword na 'HOW MUCH' o 'OFFERS', automatic mag-reply sa comment ng 'Check your inbox! Sent you our full offer details.' at mag-send din ng Private DM sa nag-comment.",
                email_inquiry: "Kapag may bagong email sa Gmail na may subject na naglalaman ng 'INQUIRY', automatic mag-reply sa email thread ng 'Thank you for your inquiry! Our team will assist you shortly.' at i-save ang sender bilang Hot Lead sa GlennBot CRM Contacts.",
                chat_lead: "Kapag may nag-send ng Direct Message (DM) sa Facebook, Instagram, WhatsApp, o Telegram na may keyword na 'PRICE' o 'INQUIRE', automatic mag-reply sa conversation at i-save ang sender sa CRM Contacts.",
                calendar_book: "Kapag nakatanggap ng email (email.received) na may keyword na 'BOOK APPOINTMENT' o 'SCHEDULE CALL', automatic mag-create ng Google Meet appointment sa GlennBot Calendar (/api/v1/calendar/schedule) para sa sender, mag-reply sa email thread ng confirmation details, at i-save ang sender sa CRM Contacts.",
                calendar_reschedule: "Kapag may nag-reschedule ng appointment sa GlennBot Calendar (calendar.rescheduled) o nag-email ng 'RESCHEDULE', automatic i-update ang appointment date/time at i-restructure ang message body (/api/v1/calendar/reschedule) at mag-send ng SMS/Email confirmation sa guest.",
                calendar_cancel: "Kapag na-cancel ang appointment sa GlennBot Calendar (calendar.cancelled) o nag-email ang guest ng 'CANCEL APPOINTMENT', automatic i-cancel ang appointment (/api/v1/calendar/cancel) at mag-send ng polite follow-up email na may option mag-rebook.",
                multi_post: "Gumawa ng n8n workflow na may Webhook trigger kung saan kapag tinawag ay automatic mag-p-publish o mag-i-schedule ng social media post sa Facebook at Instagram gamit ang GlennBot /api/v1/posts/publish endpoint."
            };
            if (examples[presetKey]) {
                promptEl.value = examples[presetKey];
                promptEl.focus();
            }
        }

        async function triggerAskAiN8nGenerate(isRegenerate = false) {
            const promptEl = document.getElementById('ask-ai-n8n-prompt');
            const promptText = (promptEl?.value || '').trim();
            if (!promptText && askAiN8nAttachedFiles.length === 0) {
                showToast('⚠️ Paki-describe muna o mag-attach ng file/image kung anong n8n workflow automation ang gusto mong ipagawa kay Gemini 3.5 Flash!');
                if (promptEl) promptEl.focus();
                return;
            }

            const genBtn = document.getElementById('ask-ai-n8n-generate-btn');
            const regenBtn = document.getElementById('ask-ai-n8n-regen-btn');
            const origGenHTML = genBtn ? genBtn.innerHTML : '';
            const origRegenHTML = regenBtn ? regenBtn.innerHTML : '';

            if (genBtn) {
                genBtn.disabled = true;
                genBtn.innerHTML = `<i class="fas fa-circle-notch fa-spin text-amber-300"></i> <span>${askAiN8nAttachedFiles.length > 0 ? 'Gemini 3.5 Flash is reading file(s) & architecting .json...' : 'Gemini 3.5 Flash is architecting n8n .json...'}</span>`;
            }
            if (regenBtn) {
                regenBtn.disabled = true;
                regenBtn.innerHTML = `<i class="fas fa-circle-notch fa-spin text-gb-cyan"></i> <span>Regenerating...</span>`;
            }

            try {
                const payloadAttachments = askAiN8nAttachedFiles.map(att => ({
                    name: att.name,
                    mime_type: att.mime_type,
                    size: att.size,
                    data_base64: att.data_base64,
                    text_content: att.text_content || ''
                }));
                const res = await fetch('/api/internal-api/n8n-workflows/ask-ai', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        prompt: promptText,
                        attachments: payloadAttachments
                    })
                });
                const rawRespText = await res.text();
                let data = {};
                try {
                    data = JSON.parse(rawRespText);
                } catch (_) {
                    throw new Error(`Server returned HTTP ${res.status}: ${(rawRespText || 'Empty response').slice(0, 180)}`);
                }
                if (!res.ok || data.status !== 'success' || !data.workflow_json) {
                    throw new Error(data.message || `HTTP ${res.status}: Failed to generate n8n workflow JSON.`);
                }

                const enrichedWf = injectLiveApiKeyIntoWorkflowJson(data.workflow_json);
                const analysis = data.analysis || analyzeN8nWorkflowJsonClient(enrichedWf);
                const wfName = String(data.workflow_name || enrichedWf.name || analysis.name || 'AI Generated n8n Workflow').trim();
                enrichedWf.name = wfName;

                lastAiGeneratedN8nResult = {
                    workflow_name: wfName,
                    explanation: data.explanation || '',
                    workflow_json: enrichedWf,
                    analysis: analysis
                };

                const nameEl = document.getElementById('ask-ai-n8n-wf-name');
                const codeEl = document.getElementById('ask-ai-n8n-json-code');
                const expEl = document.getElementById('ask-ai-n8n-explanation');
                const badgesEl = document.getElementById('ask-ai-n8n-badges');
                const resSection = document.getElementById('ask-ai-n8n-results-section');

                if (nameEl) nameEl.value = wfName;
                if (codeEl) codeEl.value = JSON.stringify(enrichedWf, null, 2);
                if (expEl) expEl.textContent = data.explanation || `Generated '${wfName}' ready for n8n and GlennBot.`;

                if (badgesEl) {
                    const bList = [];
                    bList.push(`<span class="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 text-[10px] font-bold"><i class="fas fa-Layer-group mr-1"></i>${Number(analysis.node_count || (enrichedWf.nodes || []).length)} Nodes</span>`);
                    if (analysis.webhook_path) {
                        bList.push(`<span class="px-2 py-0.5 rounded bg-gb-cyan/15 text-gb-cyan border border-gb-cyan/40 font-mono text-[10px]"><i class="fas fa-link mr-1"></i>/webhook/${escapeHTML(analysis.webhook_path)}</span>`);
                    }
                    const activeEvts = Object.entries(analysis.events || {}).filter(([, v]) => v).map(([k]) => k);
                    activeEvts.forEach(ev => {
                        bList.push(`<span class="px-2 py-0.5 rounded bg-purple-500/20 text-purple-200 border border-purple-400/40 font-mono text-[10px]"><i class="fas fa-bolt mr-1"></i>${escapeHTML(ev)}</span>`);
                    });
                    (analysis.detected_conditions || []).forEach(c => {
                        bList.push(`<span class="px-2 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/40 font-mono text-[10px]"><i class="fas fa-filter mr-1"></i>${escapeHTML(c.field)} ${escapeHTML(c.operation)} "${escapeHTML(c.value)}"</span>`);
                    });
                    badgesEl.innerHTML = bList.join('');
                }

                if (resSection) {
                    resSection.classList.remove('hidden');
                    resSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }

                playNotificationSound();
                showToast(isRegenerate ? '✨ Regenerated n8n Workflow .json with Gemini 3.5 Flash!' : '✨ Gemini 3.5 Flash generated your custom n8n Workflow .json!');
            } catch (err) {
                console.error('Ask AI n8n error:', err);
                showToast(`⚠️ ${err.message || 'Could not generate n8n workflow JSON.'}`);
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

        function getParsedAiN8nWorkflowFromTextarea() {
            const codeEl = document.getElementById('ask-ai-n8n-json-code');
            const nameEl = document.getElementById('ask-ai-n8n-wf-name');
            const rawText = (codeEl?.value || '').trim();
            if (!rawText) {
                showToast('⚠️ Generate an n8n Workflow .json with Ask AI first!');
                return null;
            }
            try {
                const parsed = JSON.parse(rawText);
                const customName = (nameEl?.value || parsed.name || 'AI Generated n8n Workflow').trim();
                parsed.name = customName;
                return injectLiveApiKeyIntoWorkflowJson(parsed);
            } catch (_) {
                showToast('⚠️ The edited JSON in the code box has a syntax error. Please check your JSON or click Regenerate.');
                return null;
            }
        }

        async function copyAiGeneratedN8nWorkflowJson() {
            const wfObj = getParsedAiN8nWorkflowFromTextarea();
            if (!wfObj) return;
            const jsonStr = JSON.stringify(wfObj, null, 2);
            await copyInternalApiText(jsonStr, 'AI-Generated n8n Workflow JSON (Press Ctrl+V on your n8n canvas!)');
        }

        function downloadAiGeneratedN8nWorkflowJson() {
            const wfObj = getParsedAiN8nWorkflowFromTextarea();
            if (!wfObj) return;
            const jsonStr = JSON.stringify(wfObj, null, 2);
            const analysis = analyzeN8nWorkflowJsonClient(wfObj);
            const slug = String(analysis.webhook_path || wfObj.name || 'glennbot-ai-workflow')
                .toLowerCase()
                .replace(/[^a-z0-9-_]+/g, '-')
                .replace(/^-+|-+$/g, '');
            const blob = new Blob([jsonStr], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${slug || 'glennbot-ai-workflow'}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            showToast(`✅ Downloaded ${slug || 'glennbot-ai-workflow'}.json!`);
        }

        async function importAiGeneratedN8nWorkflow() {
            const wfObj = getParsedAiN8nWorkflowFromTextarea();
            if (!wfObj) return;

            const importBtn = document.getElementById('ask-ai-n8n-import-btn');
            const origHTML = importBtn ? importBtn.innerHTML : '';
            if (importBtn) {
                importBtn.disabled = true;
                importBtn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> <span>Importing Workflow...</span>`;
            }

            try {
                let enrichedJson = injectLiveApiKeyIntoWorkflowJson(wfObj);
                let analysis = analyzeN8nWorkflowJsonClient(enrichedJson);
                try {
                    const res = await fetch('/api/internal-api/n8n-workflows/analyze', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ workflow_json: enrichedJson })
                    });
                    const data = await res.json();
                    if (data.status === 'success') {
                        if (data.patched_workflow_json) enrichedJson = data.patched_workflow_json;
                        if (data.analysis) analysis = data.analysis;
                    }
                } catch (_) {}

                const customName = (document.getElementById('ask-ai-n8n-wf-name')?.value || enrichedJson.name || analysis.name || 'AI Generated n8n Workflow').trim();
                enrichedJson.name = customName;

                // Populate the exact same Upload Workflow .json Builder Panel (#iapi-new-wf-form-panel)
                pendingUploadedWorkflowJson = {
                    workflow_json: enrichedJson,
                    analysis: analysis
                };

                const panel = document.getElementById('iapi-new-wf-form-panel');
                if (panel) panel.classList.remove('hidden');

                const previewBox = document.getElementById('iapi-new-wf-json-preview');
                if (previewBox) {
                    previewBox.value = JSON.stringify(enrichedJson, null, 2);
                }

                const nameInput = document.getElementById('iapi-new-wf-name');
                if (nameInput) {
                    nameInput.value = customName;
                }

                const urlInput = document.getElementById('iapi-new-wf-url');
                if (urlInput) {
                    const guessed = guessN8nWebhookUrlFromPath(analysis.webhook_path);
                    urlInput.value = guessed;
                    if (analysis.webhook_path) {
                        urlInput.placeholder = `https://your-workspace.app.n8n.cloud/webhook/${analysis.webhook_path}`;
                    }
                }

                const mapEvt = {
                    'iapi-new-wf-evt-email': 'email.received',
                    'iapi-new-wf-evt-message': 'message.received',
                    'iapi-new-wf-evt-comment': 'comment.received',
                    'iapi-new-wf-evt-contact': 'contact.saved',
                    'iapi-new-wf-evt-post': 'post.scheduled'
                };
                Object.entries(mapEvt).forEach(([elId, evtKey]) => {
                    const el = document.getElementById(elId);
                    if (el) el.checked = Boolean(analysis.events && analysis.events[evtKey]);
                });

                const badgesEl = document.getElementById('iapi-new-wf-detected-badges');
                if (badgesEl) {
                    const badges = [];
                    badges.push(`<span class="px-2 py-0.5 rounded bg-purple-500/20 text-purple-200 border border-purple-400/50 text-[10px] font-bold"><i class="fas fa-magic text-amber-300 mr-1"></i>Generated by Gemini 3.5 Flash</span>`);
                    badges.push(`<span class="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 text-[10px] font-bold"><i class="fas fa-check mr-1"></i>API Key &amp; URLs Auto-Injected (${Number(analysis.node_count || 0)} Nodes)</span>`);
                    if (analysis.webhook_path) {
                        badges.push(`<span class="px-2 py-0.5 rounded bg-gb-cyan/15 text-gb-cyan border border-gb-cyan/40 font-mono text-[10px]"><i class="fas fa-link mr-1"></i>Detected Webhook Path: /webhook/${escapeHTML(analysis.webhook_path)}</span>`);
                    }
                    (analysis.detected_conditions || []).forEach(c => {
                        badges.push(`<span class="px-2 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/40 font-mono text-[10px]"><i class="fas fa-filter mr-1"></i>Auto-Detected Condition: ${escapeHTML(c.field)} ${escapeHTML(c.operation)} "${escapeHTML(c.value)}"</span>`);
                    });
                    badgesEl.innerHTML = badges.join('');
                }

                closeAskAiN8nModal();
                switchInternalApiTab('webhook');
                if (panel) {
                    setTimeout(() => panel.scrollIntoView({ behavior: 'smooth', block: 'center' }), 120);
                }
                playNotificationSound();
                showToast(`🎉 Imported '${customName}'! Review settings below and click "Save & Activate Workflow Automation".`);
            } finally {
                if (importBtn) {
                    importBtn.disabled = false;
                    importBtn.innerHTML = origHTML;
                }
            }
        }

        async function loadInternalApiConfig() {
            const baseUrlEl = document.getElementById('iapi-base-url-display');
            if (baseUrlEl && (!baseUrlEl.textContent || baseUrlEl.textContent.trim() === '/api/v1')) {
                baseUrlEl.textContent = `${window.location.origin.replace(/\/+$/, '')}/api/v1`;
            }
            try {
                const res = await fetch('/api/internal-api/config');
                const data = await res.json();
                if (data.status !== 'success') return;

                if (baseUrlEl && data.base_api_url) {
                    baseUrlEl.textContent = data.base_api_url;
                }

                renderInternalApiKeysList(data.keys || []);
                renderInternalApiLogsList(data.recent_logs || []);
                renderN8nWorkflowsList(data.n8n_workflows || []);

                const whSecInput = document.getElementById('iapi-n8n-webhook-secret');
                if (whSecInput) whSecInput.value = data.n8n_webhook_secret || 'gb_whsec_n8n_automation_2026';
            } catch (_) {}
        }

        async function generateNewInternalApiKey() {
            const nameInput = document.getElementById('iapi-new-key-name');
            const btn = document.getElementById('btn-generate-internal-key');
            const nameVal = (nameInput ? nameInput.value : '').trim() || 'n8n Automation Key';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Generating...`;
            }
            try {
                const res = await fetch('/api/internal-api/keys/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: nameVal })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    if (nameInput) nameInput.value = '';
                    renderInternalApiKeysList(data.keys || []);
                    showToast(`✅ ${data.message || 'Generated new Internal API Key!'}`);
                } else {
                    showToast('⚠️ ' + (data.message || 'Could not generate key.'));
                }
            } catch (_) {
                showToast('⚠️ Network error while generating Internal API Key.');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<i class="fas fa-key"></i> <span>Generate Key</span>`;
                }
            }
        }

        async function deleteInternalApiKey(keyId) {
            if (!keyId) return;
            try {
                const res = await fetch(`/api/internal-api/keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' });
                const data = await res.json();
                if (data.status === 'success') {
                    renderInternalApiKeysList(data.keys || []);
                    showToast('✅ Internal API Key revoked.');
                } else {
                    showToast('⚠️ ' + (data.message || 'Could not delete key.'));
                }
            } catch (_) {
                showToast('⚠️ Network error while deleting key.');
            }
        }

        async function saveOutboundN8nWebhookConfig() {
            const btn = document.getElementById('btn-save-n8n-webhook');
            const whSec = (document.getElementById('iapi-n8n-webhook-secret')?.value || '').trim();
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Saving...`;
            }
            try {
                const res = await fetch('/api/internal-api/n8n-webhook', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        n8n_webhook_secret: whSec
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast('✅ Default Webhook Signing Secret saved!');
                } else {
                    showToast('⚠️ ' + (data.message || 'Could not save Signing Secret.'));
                }
            } catch (_) {
                showToast('⚠️ Network error while saving Signing Secret.');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<i class="fas fa-save"></i> <span>Save Secret</span>`;
                }
            }
        }

        async function testInternalApiLiveEndpoint() {
            const btn = document.getElementById('btn-test-internal-api-live');
            const firstKey = (currentInternalApiKeys[0] && currentInternalApiKeys[0].api_key) ? currentInternalApiKeys[0].api_key : '';
            if (!firstKey) {
                showToast('⚠️ Generate an Internal API Key first.');
                return;
            }
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Testing...`;
            }
            try {
                const res = await fetch('/api/v1/status', {
                    headers: { 'X-API-Key': firstKey }
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast(`✅ Internal API v1 Verified! Social: ${data.counts?.connected_social_accounts || 0}, Email: ${data.counts?.connected_email_accounts || 0}, Contacts: ${data.counts?.crm_contacts || 0}`);
                    await loadInternalApiConfig();
                } else {
                    showToast('⚠️ ' + (data.message || 'API test failed.'));
                }
            } catch (_) {
                showToast('⚠️ Network error while testing /api/v1/status.');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<i class="fas fa-vial"></i> <span>Test API Status</span>`;
                }
            }
        }

