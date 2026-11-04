        // =========================================================================
        // --- CLIENT CONTACTS & LEAD CRM DATABASE + SMART NAME AUTO-DETECTION ---
        // =========================================================================
        let crmContactsList = [];

        function initContactsTabView() {
            fetchCrmContacts(false);
        }

        function updateCrmBadgesAndStats() {
            const total = crmContactsList.length;
            const navBadge = document.getElementById('contacts-total-badge');
            if (navBadge) navBadge.textContent = String(total);

            const statTotal = document.getElementById('crm-stat-total');
            const statSocial = document.getElementById('crm-stat-social');
            const statReachable = document.getElementById('crm-stat-reachable');
            const statClients = document.getElementById('crm-stat-clients');

            const socialCount = crmContactsList.filter(c => {
                const allPlats = `${c.platform || ''},${c.source_type || ''}`.toLowerCase();
                return ['facebook', 'instagram', 'tiktok', 'youtube', 'whatsapp', 'telegram'].some(p => allPlats.includes(p));
            }).length;
            const reachableCount = crmContactsList.filter(c => Boolean((c.contact_number || '').trim() || (c.email_address || '').trim())).length;
            const clientsCount = crmContactsList.filter(c => ['Active Client', 'VIP', 'Hot Prospect', 'Partner'].includes(c.category || '')).length;

            if (statTotal) statTotal.textContent = String(total);
            if (statSocial) statSocial.textContent = String(socialCount);
            if (statReachable) statReachable.textContent = String(reachableCount);
            if (statClients) statClients.textContent = String(clientsCount);
        }

        function normalizeCrmPhoneKey(phoneStr) {
            const raw = String(phoneStr || '').trim().split('@')[0];
            const digits = raw.replace(/\D/g, '');
            if (digits.length < 7) return '';
            if (digits.length === 11 && digits.startsWith('09')) return '63' + digits.slice(1);
            if (digits.length === 10 && digits.startsWith('9')) return '63' + digits;
            return digits;
        }

        async function fetchCrmContacts(showFeedback = false) {
            const syncIcon = document.getElementById('crm-sync-icon');
            if (syncIcon && showFeedback) syncIcon.classList.add('fa-spin');
            try {
                const res = await fetch(`/api/contacts?refresh=${showFeedback ? 'true' : 'false'}`);
                const data = await res.json();
                if (data.status === 'success') {
                    crmContactsList = data.contacts || [];
                    updateCrmBadgesAndStats();
                    renderCrmContactsTable();
                    if (typeof populateNewSmsCrmContactsDropdown === 'function') {
                        populateNewSmsCrmContactsDropdown();
                    }
                    if (showFeedback) {
                        showToast(`📒 Synced ${crmContactsList.length} contact(s) from Cloudinary, WhatsApp & Telegram!`);
                    }
                }
            } catch (e) {
                console.error('Error fetching CRM contacts:', e);
            } finally {
                if (syncIcon) syncIcon.classList.remove('fa-spin');
            }
        }

        async function syncAllCrmContactsWithDeduplication() {
            const syncIcon = document.getElementById('crm-sync-icon');
            if (syncIcon) syncIcon.classList.add('fa-spin');
            showToast('🔄 Syncing contacts from Cloudinary, WhatsApp & Telegram and combining duplicate numbers/emails...');
            try {
                const res = await fetch('/api/contacts/sync', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success') {
                    crmContactsList = data.contacts || [];
                    updateCrmBadgesAndStats();
                    renderCrmContactsTable();
                    const mergedCount = Number(data.merged_duplicates || 0);
                    if (mergedCount > 0) {
                        showToast(`✅ Synced ${crmContactsList.length} contact(s) & combined ${mergedCount} duplicate phone/email record(s) into 1!`);
                    } else {
                        showToast(`✅ Synced ${crmContactsList.length} contact(s) from Cloudinary, WhatsApp & Telegram!`);
                    }
                } else {
                    await fetchCrmContacts(true);
                }
            } catch (e) {
                await fetchCrmContacts(true);
            } finally {
                if (syncIcon) syncIcon.classList.remove('fa-spin');
            }
        }

        let detectedDuplicateContactCandidate = null;

        function checkCrmDuplicatePhoneOrEmailLive() {
            const currentId = (document.getElementById('crm-contact-id')?.value || '').trim();
            const phoneVal = (document.getElementById('crm-contact-number')?.value || '').trim();
            const emailVal = (document.getElementById('crm-email-address')?.value || '').trim().toLowerCase();
            const banner = document.getElementById('crm-duplicate-merge-banner');
            const desc = document.getElementById('crm-duplicate-merge-desc');
            if (!banner || !desc) return;

            const normPhone = normalizeCrmPhoneKey(phoneVal);
            let match = null;
            let matchType = '';

            for (const c of crmContactsList) {
                if (currentId && String(c.id) === currentId) continue;
                const cPhone = normalizeCrmPhoneKey(c.contact_number || '');
                const cEmail = String(c.email_address || '').trim().toLowerCase();
                if (normPhone && cPhone && normPhone === cPhone) {
                    match = c;
                    matchType = `Contact Number (${c.contact_number})`;
                    break;
                }
                if (emailVal && cEmail && emailVal === cEmail) {
                    match = c;
                    matchType = `Email Address (${c.email_address})`;
                    break;
                }
            }

            detectedDuplicateContactCandidate = match;
            if (match) {
                const matchName = [match.first_name, match.middle_name, match.last_name].filter(Boolean).join(' ') || match.social_username || 'Existing Contact';
                const matchPlat = (match.platform || 'manual').toUpperCase();
                banner.classList.remove('hidden');
                desc.textContent = `This matches the ${matchType} of "${matchName}" (${matchPlat}). Saving will automatically combine them into a single unified contact record!`;
            } else {
                banner.classList.add('hidden');
            }
        }

        function loadDetectedDuplicateContactIntoModal() {
            if (!detectedDuplicateContactCandidate) return;
            const c = detectedDuplicateContactCandidate;
            detectedDuplicateContactCandidate = null;
            openCrmContactModal(Object.assign({}, c, {
                smart_explanation: `Loaded existing record for "${[c.first_name, c.last_name].filter(Boolean).join(' ')}" so you can edit or combine its details directly.`
            }));
        }

        function findExistingCrmContact(rawNameOrUsername, platform = '', emailAddr = '', phoneStr = '') {
            const cleanTarget = String(rawNameOrUsername || '').trim().toLowerCase();
            const cleanHandle = cleanTarget.replace(/^@/, '');
            const cleanPlat = String(platform || '').trim().toLowerCase();
            const cleanEmail = String(emailAddr || '').trim().toLowerCase();
            const normPhone = normalizeCrmPhoneKey(phoneStr);

            return crmContactsList.find(c => {
                if (normPhone && normalizeCrmPhoneKey(c.contact_number || '') === normPhone) return true;
                if (cleanEmail && String(c.email_address || '').trim().toLowerCase() === cleanEmail) return true;
                const cHandle = String(c.social_username || '').trim().toLowerCase().replace(/^@/, '');
                const fullName = `${c.first_name || ''} ${c.middle_name || ''} ${c.last_name || ''}`.replace(/\s+/g, ' ').trim().toLowerCase();
                const firstLast = `${c.first_name || ''} ${c.last_name || ''}`.replace(/\s+/g, ' ').trim().toLowerCase();
                if (cleanHandle && cHandle && (cHandle === cleanHandle || cHandle.split('•').map(s => s.trim().replace(/^@/, '')).includes(cleanHandle))) return true;
                if (cleanTarget && (fullName === cleanTarget || firstLast === cleanTarget)) return true;
                return false;
            }) || null;
        }

        function toTitleCaseWord(word) {
            const w = String(word || '').trim();
            if (!w) return '';
            if (w.length <= 2 && w.endsWith('.')) return w.toUpperCase();
            return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
        }

        /**
         * Smart Name & Contact Auto-Detector:
         * Automatically distinguishes between a real full name (e.g. "Juan Dela Cruz" or "Maria S. Santos")
         * vs. a social handle/username (e.g. "@glenn_tasico24", "maria.santos_official", "yt_gamer_ph"),
         * and extracts any phone number or email address mentioned in the message/comment text.
         */
        function smartParseContactFromSocial(rawDisplayName, platform = 'manual', sampleText = '', explicitEmail = '') {
            const raw = String(rawDisplayName || '').trim();
            const plat = String(platform || 'manual').trim().toLowerCase();
            const text = String(sampleText || '');

            // 1. Extract email or phone from message/comment text if present
            let detectedEmail = String(explicitEmail || '').trim();
            if (!detectedEmail && text) {
                const emailMatch = text.match(/[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/);
                if (emailMatch) detectedEmail = emailMatch[0];
            }

            let detectedPhone = '';
            if (text) {
                const phoneMatch = text.match(/(?:\+?63[\s\-]?|0)9\d{2}[\s\-]?\d{3}[\s\-]?\d{4}\b|(?:\+?\d{1,3}[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}\b/);
                if (phoneMatch) detectedPhone = phoneMatch[0].trim();
            }

            if (!raw) {
                return {
                    first_name: '',
                    middle_name: '',
                    last_name: '',
                    social_username: '',
                    email_address: detectedEmail,
                    contact_number: detectedPhone,
                    is_username_guess: false,
                    explanation: 'Manual entry mode — fill in the contact details below.'
                };
            }

            // Determine if `raw` looks like a social handle/username rather than a spaced full name
            const startsWithAt = raw.startsWith('@');
            const hasNoSpaces = !/\s/.test(raw);
            const hasHandleChars = /[_\d]/.test(raw) || (hasNoSpaces && /[.]/.test(raw));
            const isLikelyHandle = startsWithAt || hasNoSpaces || (hasHandleChars && raw.split(/\s+/).length === 1);

            const compoundSurnamePrefixes = new Set(['dela', 'de', 'del', 'delos', 'san', 'sta', 'sta.', 'st', 'st.', 'van', 'von', 'da', 'dos']);

            if (!isLikelyHandle) {
                // Full Name with spaces (e.g. "Juan Dela Cruz", "Maria Clara Santos", "Glenn M. Tasico")
                const cleanFull = raw.replace(/[^\p{L}\p{N}\s.\-']/gu, ' ').replace(/\s+/g, ' ').trim();
                const parts = cleanFull.split(' ').filter(Boolean);

                let firstName = '';
                let middleName = '';
                let lastName = '';

                if (parts.length === 1) {
                    firstName = toTitleCaseWord(parts[0]);
                } else if (parts.length === 2) {
                    firstName = toTitleCaseWord(parts[0]);
                    lastName = toTitleCaseWord(parts[1]);
                } else if (parts.length === 3) {
                    if (compoundSurnamePrefixes.has(parts[1].toLowerCase())) {
                        // e.g. "Juan Dela Cruz" -> First: Juan, Last: Dela Cruz
                        firstName = toTitleCaseWord(parts[0]);
                        lastName = `${toTitleCaseWord(parts[1])} ${toTitleCaseWord(parts[2])}`;
                    } else {
                        // e.g. "Juan Miguel Cruz" or "Juan M. Cruz"
                        firstName = toTitleCaseWord(parts[0]);
                        middleName = toTitleCaseWord(parts[1]);
                        lastName = toTitleCaseWord(parts[2]);
                    }
                } else if (parts.length >= 4) {
                    const secondLastLower = parts[parts.length - 2].toLowerCase();
                    if (compoundSurnamePrefixes.has(secondLastLower)) {
                        // e.g. "Maria Clara Dela Cruz" or "Mark S. Dela Cruz"
                        lastName = `${toTitleCaseWord(parts[parts.length - 2])} ${toTitleCaseWord(parts[parts.length - 1])}`;
                        const rem = parts.slice(0, parts.length - 2);
                        if (rem.length === 1) {
                            firstName = toTitleCaseWord(rem[0]);
                        } else {
                            firstName = rem.slice(0, rem.length - 1).map(toTitleCaseWord).join(' ');
                            middleName = toTitleCaseWord(rem[rem.length - 1]);
                        }
                    } else {
                        lastName = toTitleCaseWord(parts[parts.length - 1]);
                        middleName = toTitleCaseWord(parts[parts.length - 2]);
                        firstName = parts.slice(0, parts.length - 2).map(toTitleCaseWord).join(' ');
                    }
                }

                return {
                    first_name: firstName,
                    middle_name: middleName,
                    last_name: lastName,
                    social_username: '',
                    email_address: detectedEmail,
                    contact_number: detectedPhone,
                    is_username_guess: false,
                    explanation: `Auto-filled from profile name ("${raw}"). You can review or edit the First, Middle, and Last Name before saving!`
                };
            }

            // Otherwise, it's a username/handle (e.g. Instagram @maria_santos24, YouTube @JuanDelaCruzTV, TikTok @glenn.tasico)
            const handleFormatted = raw.startsWith('@') ? raw : `@${raw}`;
            let stripped = raw.replace(/^@+/, '');
            // Split camelCase (e.g. "JuanDelaCruz" -> "Juan Dela Cruz")
            stripped = stripped.replace(/([a-z])([A-Z])/g, '$1 $2');
            // Replace underscores, dots, hyphens with spaces and strip trailing/standalone numbers
            stripped = stripped.replace(/[._\-]+/g, ' ').replace(/\d+/g, ' ');

            const noiseWords = new Set(['official', 'real', 'tv', 'ph', 'vlog', 'vlogs', 'yt', 'ig', 'channel', 'gaming', 'shop', 'store', 'the', 'iam', 'its']);
            const rawTokens = stripped
                .split(/\s+/)
                .map(t => t.replace(/[^a-zA-Z']/g, '').trim())
                .filter(t => t.length >= 2);

            const filteredTokens = rawTokens.filter(t => !noiseWords.has(t.toLowerCase()));
            const tokens = filteredTokens.length > 0 ? filteredTokens : rawTokens;

            let firstName = '';
            let middleName = '';
            let lastName = '';

            if (tokens.length === 0) {
                firstName = raw.replace(/^@+/, '');
            } else if (tokens.length === 1) {
                firstName = toTitleCaseWord(tokens[0]);
            } else if (tokens.length === 2) {
                firstName = toTitleCaseWord(tokens[0]);
                lastName = toTitleCaseWord(tokens[1]);
            } else {
                firstName = toTitleCaseWord(tokens[0]);
                if (compoundSurnamePrefixes.has(tokens[1].toLowerCase()) && tokens.length === 3) {
                    lastName = `${toTitleCaseWord(tokens[1])} ${toTitleCaseWord(tokens[2])}`;
                } else {
                    middleName = toTitleCaseWord(tokens[1]);
                    lastName = tokens.slice(2).map(toTitleCaseWord).join(' ');
                }
            }

            // For Facebook & Instagram, do not auto-populate social_username unless manually added by the user
            const autoSocialUsername = (plat === 'facebook' || plat === 'instagram') ? '' : handleFormatted;

            return {
                first_name: firstName,
                middle_name: middleName,
                last_name: lastName,
                social_username: autoSocialUsername,
                email_address: detectedEmail,
                contact_number: detectedPhone,
                is_username_guess: true,
                explanation: `Detected a username on ${(plat || 'social').toUpperCase()} (${handleFormatted}). Auto-filled as "${[firstName, middleName, lastName].filter(Boolean).join(' ')}" — feel free to edit before saving!`
            };
        }

        function swapCrmFirstAndLastName() {
            const fEl = document.getElementById('crm-first-name');
            const lEl = document.getElementById('crm-last-name');
            if (!fEl || !lEl) return;
            const tmp = fEl.value;
            fEl.value = lEl.value;
            lEl.value = tmp;
        }

        function clearCrmNameFields() {
            const fEl = document.getElementById('crm-first-name');
            const mEl = document.getElementById('crm-middle-name');
            const lEl = document.getElementById('crm-last-name');
            if (fEl) { fEl.value = ''; fEl.focus(); }
            if (mEl) mEl.value = '';
            if (lEl) lEl.value = '';
        }

        function openCrmContactModal(prefill = null) {
            const idEl = document.getElementById('crm-contact-id');
            const fEl = document.getElementById('crm-first-name');
            const mEl = document.getElementById('crm-middle-name');
            const lEl = document.getElementById('crm-last-name');
            const phoneEl = document.getElementById('crm-contact-number');
            const emailEl = document.getElementById('crm-email-address');
            const platEl = document.getElementById('crm-platform');
            const userEl = document.getElementById('crm-social-username');
            const catEl = document.getElementById('crm-category');
            const compEl = document.getElementById('crm-company');
            const accEl = document.getElementById('crm-account-name');
            const notesEl = document.getElementById('crm-notes');
            const srcTypeEl = document.getElementById('crm-contact-source-type');
            const srcRefEl = document.getElementById('crm-contact-source-ref');
            const avatarEl = document.getElementById('crm-contact-avatar');
            const titleEl = document.getElementById('crm-modal-title');
            const subtitleEl = document.getElementById('crm-modal-subtitle');
            const bannerEl = document.getElementById('crm-smart-detect-banner');
            const bannerTitleEl = document.getElementById('crm-smart-detect-title');
            const bannerDescEl = document.getElementById('crm-smart-detect-desc');

            const d = prefill || {};
            if (idEl) idEl.value = d.id || '';
            if (fEl) fEl.value = d.first_name || '';
            if (mEl) mEl.value = d.middle_name || '';
            if (lEl) lEl.value = d.last_name || '';
            if (phoneEl) phoneEl.value = d.contact_number || '';
            if (emailEl) emailEl.value = d.email_address || '';
            if (platEl) platEl.value = (d.platform || 'manual').toLowerCase();
            if (userEl) {
                const rawU = String(d.social_username || '').trim();
                const fullNameSpaced = [d.first_name, d.middle_name, d.last_name].filter(Boolean).join(' ').trim().toLowerCase();
                const firstLastSpaced = [d.first_name, d.last_name].filter(Boolean).join(' ').trim().toLowerCase();
                const isRedundantFullName = Boolean(rawU && !rawU.startsWith('@') && /\s/.test(rawU) && (rawU.toLowerCase() === fullNameSpaced || rawU.toLowerCase() === firstLastSpaced));
                userEl.value = isRedundantFullName ? '' : rawU;
            }
            if (catEl) catEl.value = d.category || 'New Lead';
            if (compEl) compEl.value = d.company || '';
            if (accEl) accEl.value = d.account_name || '';
            if (notesEl) notesEl.value = d.notes || '';
            if (srcTypeEl) srcTypeEl.value = d.source_type || 'manual';
            if (srcRefEl) srcRefEl.value = d.source_ref_id || '';
            if (avatarEl) avatarEl.value = d.avatar_url || '';

            if (titleEl) {
                titleEl.textContent = d.id ? 'Edit CRM Contact' : 'Add Contact to CRM Database';
            }
            if (subtitleEl) {
                subtitleEl.textContent = d.id
                    ? `Updating saved CRM record (${d.first_name || ''} ${d.last_name || ''})`
                    : 'Auto-detects First, Middle, and Last Name — freely editable before saving';
            }

            if (bannerEl) {
                if (d.smart_explanation) {
                    bannerEl.classList.remove('hidden');
                    if (bannerTitleEl) {
                        bannerTitleEl.textContent = d.is_username_guess
                            ? 'Smart Username Auto-Detection (Editable)'
                            : 'Smart Profile Name Auto-Filled';
                    }
                    if (bannerDescEl) {
                        bannerDescEl.textContent = d.smart_explanation;
                    }
                } else {
                    bannerEl.classList.add('hidden');
                }
            }

            checkCrmDuplicatePhoneOrEmailLive();
            openModalWithFade('crm-contact-modal');
            setTimeout(() => {
                fEl?.focus();
            }, 60);
        }

        function closeCrmContactModal() {
            closeModalWithFade('crm-contact-modal');
        }

        function openAddToContactsFromMessage(convKey, event) {
            if (event) event.stopPropagation();
            const conv = messagesConversationsList.find(c => c.conv_key === convKey) || activeConversationObj;
            if (!conv) return;

            const existing = findExistingCrmContact(
                conv.participant_name,
                conv.platform,
                conv.participant_email || '',
                conv.participant_phone || ''
            );
            if (existing) {
                openCrmContactModal(Object.assign({}, existing, {
                    smart_explanation: `"${conv.participant_name}" is already in your Contacts CRM. You can update or combine their details below!`
                }));
                return;
            }

            const sampleText = conv.last_message_text || '';
            const parsed = smartParseContactFromSocial(conv.participant_name, conv.platform, sampleText, conv.participant_email || '');
            const finalPhone = conv.participant_phone || parsed.contact_number || '';
            const finalHandle = conv.participant_handle || parsed.social_username || '';

            openCrmContactModal({
                id: '',
                first_name: parsed.first_name,
                middle_name: parsed.middle_name,
                last_name: parsed.last_name,
                contact_number: finalPhone,
                email_address: conv.participant_email || parsed.email_address,
                platform: (conv.platform || 'facebook').toLowerCase(),
                social_username: finalHandle,
                account_name: conv.account_name || '',
                category: 'New Lead',
                company: '',
                notes: sampleText ? `From ${(conv.platform || '').toUpperCase()} DM (${conv.account_name || ''}): "${sampleText}"` : `Added from ${(conv.platform || '').toUpperCase()} Messages`,
                source_type: (conv.platform || 'message').toLowerCase(),
                source_ref_id: conv.conversation_id || conv.conv_key || '',
                avatar_url: conv.participant_avatar || '',
                is_username_guess: parsed.is_username_guess,
                smart_explanation: parsed.explanation
            });
        }

        function openAddToContactsFromComment(recordId, commentOrReplyId, event) {
            if (event) event.stopPropagation();
            const postComments = commentsList.filter(c => c.record_id === recordId);
            const targetMatch = findTargetItemInPostComments(postComments.length ? postComments : commentsList, commentOrReplyId);
            const parentComm = targetMatch ? targetMatch.parentComment : (
                commentsList.find(c => c.record_id === recordId && c.comment_id === commentOrReplyId)
                || commentsList.find(c => c.comment_id === commentOrReplyId)
            );
            if (!parentComm) return;

            const targetReply = targetMatch ? targetMatch.targetReply : null;
            const authorName = targetReply ? (targetReply.author_name || parentComm.author_name || 'User') : (parentComm.author_name || 'User');
            const authorAvatar = targetReply ? (targetReply.author_avatar || parentComm.author_avatar || '') : (parentComm.author_avatar || '');
            const commentText = targetReply ? (targetReply.message || '') : (parentComm.message || '');
            const platform = (parentComm.platform || 'facebook').toLowerCase();

            const existing = findExistingCrmContact(authorName, platform);
            if (existing) {
                openCrmContactModal(Object.assign({}, existing, {
                    smart_explanation: `"${authorName}" is already in your Contacts CRM. You can edit their details below!`
                }));
                return;
            }

            const parsed = smartParseContactFromSocial(authorName, platform, commentText);
            openCrmContactModal({
                id: '',
                first_name: parsed.first_name,
                middle_name: parsed.middle_name,
                last_name: parsed.last_name,
                contact_number: parsed.contact_number,
                email_address: parsed.email_address,
                platform: platform,
                social_username: parsed.social_username,
                account_name: parentComm.account_name || '',
                category: 'New Lead',
                company: '',
                notes: commentText ? `Commented on ${platform.toUpperCase()} (${parentComm.account_name || ''}): "${commentText}"` : `Added from ${platform.toUpperCase()} Comments`,
                source_type: platform,
                source_ref_id: String(commentOrReplyId || recordId || ''),
                avatar_url: authorAvatar,
                is_username_guess: parsed.is_username_guess,
                smart_explanation: parsed.explanation
            });
        }

        function openAddToContactsFromEmail(msgId) {
            const msg = activeEmailMessages.find(m => m.id === msgId);
            if (!msg) return;
            const activeAcc = emailAccountsList.find(a => a.id === activeEmailAccountId);
            const provider = (activeAcc?.provider || 'gmail').toLowerCase();
            const senderEmails = extractEmailAddressesList(msg.sender_email || msg.sender || '');
            const senderEmail = senderEmails[0] || '';
            const rawName = (msg.sender_name || msg.sender || '').replace(/<[^>]+>/g, '').replace(/"/g, '').trim();

            const existing = findExistingCrmContact(rawName, provider, senderEmail);
            if (existing) {
                openCrmContactModal(Object.assign({}, existing, {
                    smart_explanation: `"${rawName || senderEmail}" is already in your Contacts CRM. You can update their details below!`
                }));
                return;
            }

            const parsed = smartParseContactFromSocial(rawName || senderEmail.split('@')[0], provider, msg.snippet || '', senderEmail);
            openCrmContactModal({
                id: '',
                first_name: parsed.first_name,
                middle_name: parsed.middle_name,
                last_name: parsed.last_name,
                contact_number: parsed.contact_number,
                email_address: senderEmail || parsed.email_address,
                platform: provider,
                social_username: senderEmail || parsed.social_username,
                account_name: activeAcc?.email_address || '',
                category: 'New Lead',
                company: '',
                notes: msg.subject ? `Email Subject: "${msg.subject}"` : 'Added from Email Inbox',
                source_type: provider,
                source_ref_id: msg.id || '',
                avatar_url: '',
                is_username_guess: parsed.is_username_guess,
                smart_explanation: parsed.explanation
            });
        }

        async function saveCrmContactFromModal() {
            const id = (document.getElementById('crm-contact-id')?.value || '').trim();
            const first_name = (document.getElementById('crm-first-name')?.value || '').trim();
            const middle_name = (document.getElementById('crm-middle-name')?.value || '').trim();
            const last_name = (document.getElementById('crm-last-name')?.value || '').trim();
            const contact_number = (document.getElementById('crm-contact-number')?.value || '').trim();
            const email_address = (document.getElementById('crm-email-address')?.value || '').trim();
            const platform = (document.getElementById('crm-platform')?.value || 'manual').trim().toLowerCase();
            const social_username = (document.getElementById('crm-social-username')?.value || '').trim();
            const category = (document.getElementById('crm-category')?.value || 'New Lead').trim();
            const company = (document.getElementById('crm-company')?.value || '').trim();
            const account_name = (document.getElementById('crm-account-name')?.value || '').trim();
            const notes = (document.getElementById('crm-notes')?.value || '').trim();
            const source_type = (document.getElementById('crm-contact-source-type')?.value || platform || 'manual').trim();
            const source_ref_id = (document.getElementById('crm-contact-source-ref')?.value || '').trim();
            const avatar_url = (document.getElementById('crm-contact-avatar')?.value || '').trim();
            const btn = document.getElementById('btn-save-crm-contact');

            if (!first_name && !last_name && !social_username && !email_address && !contact_number) {
                showToast('⚠️ Please enter at least a First Name, Username, Email, or Contact Number.');
                document.getElementById('crm-first-name')?.focus();
                return;
            }

            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Saving...`;
            }

            try {
                const res = await fetch('/api/contacts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        id,
                        first_name,
                        middle_name,
                        last_name,
                        contact_number,
                        email_address,
                        platform,
                        social_username,
                        account_name,
                        category,
                        company,
                        notes,
                        source_type,
                        source_ref_id,
                        avatar_url
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    closeCrmContactModal();
                    await fetchCrmContacts(false);
                    if (activeTab === 'messages') renderMessagesConversationsList();
                    if (activeTab === 'comments' && selectedRecordId) syncOpenPostThreadLive(selectedRecordId);
                    const fullName = [first_name, middle_name, last_name].filter(Boolean).join(' ') || social_username || email_address || contact_number;
                    if (data.combined_duplicate) {
                        showToast(`🔗 Combined duplicate & saved "${fullName}" (${data.matched_reason || 'Merged into 1 contact'})!`);
                    } else {
                        showToast(`✅ Saved "${fullName}" to Contacts CRM!`);
                    }
                } else {
                    showToast('❌ ' + (data.message || 'Could not save contact.'));
                }
            } catch (e) {
                showToast('❌ Network error while saving contact.');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<i class="fas fa-check-circle"></i> <span>Save Contact to CRM</span>`;
                }
            }
        }

        function editCrmContactById(contactId) {
            const c = crmContactsList.find(item => item.id === contactId);
            if (!c) return;
            openCrmContactModal(c);
        }

        async function deleteCrmContactById(contactId, displayName) {
            if (!confirm(`Delete "${displayName}" from your CRM Contacts Database?`)) return;
            try {
                const res = await fetch(`/api/contacts/${encodeURIComponent(contactId)}`, { method: 'DELETE' });
                const data = await res.json();
                if (data.status === 'success') {
                    crmContactsList = crmContactsList.filter(c => c.id !== contactId);
                    updateCrmBadgesAndStats();
                    renderCrmContactsTable();
                    showToast(`🗑️ Deleted "${displayName}" from Contacts.`);
                }
            } catch (e) {
                showToast('❌ Failed to delete contact.');
            }
        }

        function composeEmailToCrmContact(emailAddr) {
            const clean = String(emailAddr || '').trim();
            if (!clean) {
                showToast('⚠️ This contact does not have an email address yet.');
                return;
            }
            openComposeEmailModal(clean);
        }

        function isValidTelegramUsernameFormat(rawHandle) {
            const raw = String(rawHandle || '').trim();
            if (!raw || /\s/.test(raw)) return false;
            const stripped = raw.replace(/^@+/, '');
            if (!/^[a-zA-Z][a-zA-Z0-9_]{4,31}$/.test(stripped)) return false;
            if (stripped.includes('__') || stripped.endsWith('_')) return false;
            return true;
        }

        function getCrmContactEffectiveUsername(c) {
            if (!c || typeof c !== 'object') return '';
            const raw = String(c.social_username || '').trim();
            if (!raw) return '';
            // Ignore if it's just the contact's email address
            if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(raw)) return '';
            // Ignore if it's purely a phone number
            if (/^[\+\d\s\-\(\)]+$/.test(raw) && raw.replace(/\D/g, '').length >= 7) return '';
            // Ignore legacy auto-copied spaced full name on Facebook/Instagram contacts
            const fullNameSpaced = [c.first_name, c.middle_name, c.last_name].filter(Boolean).join(' ').trim().toLowerCase();
            const firstLastSpaced = [c.first_name, c.last_name].filter(Boolean).join(' ').trim().toLowerCase();
            if (!raw.startsWith('@') && /\s/.test(raw) && (raw.toLowerCase() === fullNameSpaced || raw.toLowerCase() === firstLastSpaced)) {
                return '';
            }
            return raw;
        }

        function getCrmContactMessagingCapabilities(c) {
            if (!c || typeof c !== 'object') {
                return {
                    hasMobile: false,
                    mobileNumber: '',
                    hasEmail: false,
                    emailAddress: '',
                    hasUsername: false,
                    socialUsername: '',
                    isValidTelegramHandle: false,
                    isReachable: false
                };
            }
            const mobileNumber = typeof getCrmContactMobileNumber === 'function'
                ? getCrmContactMobileNumber(c)
                : String(c.contact_number || '').trim();
            const hasMobile = Boolean(mobileNumber && mobileNumber.replace(/\D/g, '').length >= 7);
            const emailAddress = String(c.email_address || '').trim();
            const hasEmail = Boolean(emailAddress && emailAddress.includes('@'));
            const socialUsername = getCrmContactEffectiveUsername(c);
            const hasUsername = Boolean(socialUsername);
            const isValidTelegramHandle = hasUsername ? isValidTelegramUsernameFormat(socialUsername) : false;
            const isReachable = Boolean(hasMobile || hasEmail || hasUsername);

            return {
                hasMobile,
                mobileNumber,
                hasEmail,
                emailAddress,
                hasUsername,
                socialUsername,
                isValidTelegramHandle,
                isReachable
            };
        }

        function closeCrmOpenChatPlatformModal() {
            closeModalWithFade('crm-open-chat-platform-modal');
        }

        function handleOpenChatFromCrmContact(contactId, event) {
            if (event) event.stopPropagation();
            const c = crmContactsList.find(item => String(item.id) === String(contactId));
            if (!c) return;

            const caps = getCrmContactMessagingCapabilities(c);
            // Kapag sinave via Facebook or Instagram (o walang mobile number, email, at username),
            // HINDI mag-re-react yung "Open Chat in Message Tab" button!
            if (!caps.isReachable) {
                return;
            }

            const fullName = [c.first_name, c.middle_name, c.last_name].filter(Boolean).join(' ') || caps.socialUsername || caps.emailAddress || caps.mobileNumber || 'Contact';
            const plat = (c.platform || 'manual').toLowerCase();
            const subtitleEl = document.getElementById('crm-open-chat-contact-subtitle');
            const summaryEl = document.getElementById('crm-open-chat-contact-summary');
            const optionsEl = document.getElementById('crm-open-chat-options-list');

            if (subtitleEl) {
                subtitleEl.textContent = `Choose how you want to message ${fullName}`;
            }

            if (summaryEl) {
                summaryEl.innerHTML = `
                    <div class="flex items-center gap-3 min-w-0">
                        <div class="w-10 h-10 rounded-xl bg-slate-800 border border-slate-700 flex items-center justify-center text-gb-cyan font-extrabold text-sm shrink-0">
                            <i class="fas fa-user"></i>
                        </div>
                        <div class="min-w-0">
                            <div class="text-xs sm:text-sm font-extrabold text-white truncate">${escapeHTML(fullName)}</div>
                            <div class="flex flex-wrap items-center gap-1.5 mt-0.5 text-[10px] text-slate-400">
                                <span>Saved via <strong class="text-slate-200 uppercase">${escapeHTML(plat)}</strong></span>
                                ${caps.hasMobile ? `<span>• 📱 ${escapeHTML(caps.mobileNumber)}</span>` : ''}
                                ${caps.hasEmail ? `<span>• ✉️ ${escapeHTML(caps.emailAddress)}</span>` : ''}
                                ${caps.hasUsername ? `<span>• 👤 ${escapeHTML(caps.socialUsername)}</span>` : ''}
                            </div>
                        </div>
                    </div>
                    ${getCrmCategoryBadgeHTML(c.category)}
                `;
            }

            const optionCards = [];

            // 1. EMAIL OPTION (Uses Compose Email Modal + Connected Email Sender Picker)
            if (caps.hasEmail) {
                optionCards.push(`
                    <button type="button" onclick="closeCrmOpenChatPlatformModal(); composeEmailToCrmContact('${escapeHTML(caps.emailAddress)}');"
                        class="w-full p-3.5 rounded-xl bg-slate-900/90 hover:bg-gb-cyan/15 border border-slate-700 hover:border-gb-cyan text-left flex items-center justify-between gap-3 transition-all cursor-pointer group">
                        <div class="flex items-center gap-3 min-w-0">
                            <div class="w-10 h-10 rounded-xl bg-gb-cyan/15 border border-gb-cyan/40 flex items-center justify-center text-gb-cyan shrink-0 group-hover:scale-105 transition-transform">
                                <i class="fas fa-envelope text-base"></i>
                            </div>
                            <div class="min-w-0">
                                <div class="text-xs sm:text-sm font-extrabold text-white flex items-center gap-2">
                                    <span>Email (Compose Email Modal)</span>
                                    <span class="px-2 py-0.5 rounded-full bg-gb-cyan/20 border border-gb-cyan/40 text-gb-cyan text-[9px] font-bold">Choose Sender Email</span>
                                </div>
                                <div class="text-[11px] text-slate-400 truncate mt-0.5">
                                    To: <strong class="text-gb-cyan">${escapeHTML(caps.emailAddress)}</strong> • Select any connected Gmail / Outlook / IMAP as sender
                                </div>
                            </div>
                        </div>
                        <i class="fas fa-chevron-right text-slate-500 group-hover:text-gb-cyan text-xs shrink-0"></i>
                    </button>
                `);
            }

            // 2. SMS OPTION (Available when Mobile Number is present)
            if (caps.hasMobile) {
                optionCards.push(`
                    <button type="button" onclick="openCrmContactChatInMessagesTab('${escapeHTML(String(c.id))}', 'sms')"
                        class="w-full p-3.5 rounded-xl bg-slate-900/90 hover:bg-emerald-500/15 border border-slate-700 hover:border-emerald-400 text-left flex items-center justify-between gap-3 transition-all cursor-pointer group">
                        <div class="flex items-center gap-3 min-w-0">
                            <div class="w-10 h-10 rounded-xl bg-emerald-500/15 border border-emerald-400/40 flex items-center justify-center text-emerald-300 shrink-0 group-hover:scale-105 transition-transform">
                                <i class="fas fa-sms text-base"></i>
                            </div>
                            <div class="min-w-0">
                                <div class="text-xs sm:text-sm font-extrabold text-white flex items-center gap-2">
                                    <span>SMS (TextBee SIM 2)</span>
                                    <span class="px-2 py-0.5 rounded-full bg-emerald-500/20 border border-emerald-400/40 text-emerald-300 text-[9px] font-bold">Open in Messages Tab</span>
                                </div>
                                <div class="text-[11px] text-slate-400 truncate mt-0.5">
                                    Mobile: <strong class="text-emerald-300 font-mono">${escapeHTML(caps.mobileNumber)}</strong> • Direct SMS thread in Unified Inbox
                                </div>
                            </div>
                        </div>
                        <i class="fas fa-chevron-right text-slate-500 group-hover:text-emerald-300 text-xs shrink-0"></i>
                    </button>
                `);

                // 3. WHATSAPP OPTION (Available when Mobile Number is present)
                optionCards.push(`
                    <button type="button" onclick="openCrmContactChatInMessagesTab('${escapeHTML(String(c.id))}', 'whatsapp')"
                        class="w-full p-3.5 rounded-xl bg-slate-900/90 hover:bg-[#25D366]/15 border border-slate-700 hover:border-[#25D366] text-left flex items-center justify-between gap-3 transition-all cursor-pointer group">
                        <div class="flex items-center gap-3 min-w-0">
                            <div class="w-10 h-10 rounded-xl bg-[#25D366]/15 border border-[#25D366]/40 flex items-center justify-center text-[#25D366] shrink-0 group-hover:scale-105 transition-transform">
                                <i class="fab fa-whatsapp text-lg"></i>
                            </div>
                            <div class="min-w-0">
                                <div class="text-xs sm:text-sm font-extrabold text-white flex items-center gap-2">
                                    <span>WhatsApp</span>
                                    <span class="px-2 py-0.5 rounded-full bg-[#25D366]/20 border border-[#25D366]/40 text-[#25D366] text-[9px] font-bold">Open in Messages Tab</span>
                                </div>
                                <div class="text-[11px] text-slate-400 truncate mt-0.5">
                                    Mobile: <strong class="text-[#25D366] font-mono">${escapeHTML(caps.mobileNumber)}</strong> • Message via connected WhatsApp
                                </div>
                            </div>
                        </div>
                        <i class="fas fa-chevron-right text-slate-500 group-hover:text-[#25D366] text-xs shrink-0"></i>
                    </button>
                `);
            }

            // 4. TELEGRAM OPTION (Available when Social Username / Handle is present)
            if (caps.hasUsername) {
                const tgBadgeHTML = caps.isValidTelegramHandle
                    ? `<span class="px-2 py-0.5 rounded-full bg-[#229ED9]/20 border border-[#229ED9]/40 text-[#229ED9] text-[9px] font-bold">Valid @username Format</span>`
                    : `<span class="px-2 py-0.5 rounded-full bg-amber-500/20 border border-amber-400/50 text-amber-300 text-[9px] font-bold" title="Invalid Telegram username format — sending on Telegram will return an error unless a valid @username is set">⚠️ Invalid Telegram Handle</span>`;
                optionCards.push(`
                    <button type="button" onclick="openCrmContactChatInMessagesTab('${escapeHTML(String(c.id))}', 'telegram')"
                        class="w-full p-3.5 rounded-xl bg-slate-900/90 hover:bg-[#229ED9]/15 border border-slate-700 hover:border-[#229ED9] text-left flex items-center justify-between gap-3 transition-all cursor-pointer group">
                        <div class="flex items-center gap-3 min-w-0">
                            <div class="w-10 h-10 rounded-xl bg-[#229ED9]/15 border border-[#229ED9]/40 flex items-center justify-center text-[#229ED9] shrink-0 group-hover:scale-105 transition-transform">
                                <i class="fab fa-telegram-plane text-lg"></i>
                            </div>
                            <div class="min-w-0">
                                <div class="text-xs sm:text-sm font-extrabold text-white flex items-center gap-2 flex-wrap">
                                    <span>Telegram</span>
                                    ${tgBadgeHTML}
                                </div>
                                <div class="text-[11px] text-slate-400 truncate mt-0.5">
                                    Social Username / Handle: <strong class="text-[#229ED9] font-mono">${escapeHTML(caps.socialUsername)}</strong>
                                </div>
                            </div>
                        </div>
                        <i class="fas fa-chevron-right text-slate-500 group-hover:text-[#229ED9] text-xs shrink-0"></i>
                    </button>
                `);
            }

            if (optionsEl) {
                optionsEl.innerHTML = optionCards.join('');
            }
            openModalWithFade('crm-open-chat-platform-modal');
        }

        async function openCrmContactChatInMessagesTab(contactId, targetPlatform) {
            closeCrmOpenChatPlatformModal();
            const plat = String(targetPlatform || '').trim().toLowerCase();
            if (!plat) return;

            const contactObj = (crmContactsList || []).find(item => String(item.id) === String(contactId)) || {};
            const fullName = [contactObj.first_name, contactObj.middle_name, contactObj.last_name].filter(Boolean).join(' ').trim();

            try {
                const res = await fetch('/api/contacts/open-chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        contact_id: contactId,
                        platform: plat,
                        contact_number: contactObj.contact_number || '',
                        social_username: getCrmContactEffectiveUsername(contactObj) || contactObj.social_username || '',
                        participant_name: fullName || contactObj.social_username || contactObj.contact_number || 'Contact'
                    })
                });
                const rawText = await res.text();
                let data = {};
                try {
                    data = rawText ? JSON.parse(rawText) : {};
                } catch (_jsonErr) {
                    showToast(`❌ Server error (${res.status}): Make sure routers/scheduler_routes.py is updated and server is restarted.`);
                    return;
                }
                if (!res.ok || data.status !== 'success' || !data.conversation) {
                    showToast('❌ ' + (data.message || `Could not open ${plat.toUpperCase()} chat.`));
                    return;
                }

                const conv = data.conversation;
                const convKey = String(conv.conv_key || `${conv.account_id}_${conv.conversation_id}`);
                conv.conv_key = convKey;

                switchTab('messages');

                const filterEl = document.getElementById('messages-filter-platform');
                if (filterEl) {
                    filterEl.value = plat;
                }
                const pageFilterEl = document.getElementById('messages-filter-page');
                if (pageFilterEl) {
                    pageFilterEl.value = 'all';
                }

                await fetchConversations(false);

                // Ensure the conversation is in messagesConversationsList and select it immediately
                const existingIdx = messagesConversationsList.findIndex(item => item.conv_key === convKey);
                if (existingIdx >= 0) {
                    messagesConversationsList[existingIdx] = Object.assign({}, messagesConversationsList[existingIdx], conv);
                } else {
                    messagesConversationsList.unshift(conv);
                }
                renderMessagesConversationsList();
                await selectMessageConversation(convKey, conv.conversation_id, conv.account_id);
                setTimeout(() => {
                    document.getElementById('direct-message-input')?.focus();
                }, 120);
            } catch (e) {
                showToast('❌ Error opening chat in Messages tab: ' + (e.message || e));
            }
        }

        function openChatForCrmContact(contactId) {
            handleOpenChatFromCrmContact(contactId);
        }

        function getCrmCategoryBadgeHTML(category) {
            const cat = String(category || 'New Lead').trim();
            const styles = {
                'New Lead': 'bg-gb-cyan/15 text-gb-cyan border-gb-cyan/40',
                'Hot Prospect': 'bg-amber-500/15 text-amber-300 border-amber-400/40',
                'Active Client': 'bg-emerald-500/15 text-emerald-300 border-emerald-400/40',
                'VIP': 'bg-purple-500/20 text-purple-300 border-purple-400/50',
                'Inquirer': 'bg-blue-500/15 text-blue-300 border-blue-400/40',
                'Follow-Up': 'bg-rose-500/15 text-rose-300 border-rose-400/40',
                'Partner': 'bg-indigo-500/15 text-indigo-300 border-indigo-400/40'
            };
            const cls = styles[cat] || 'bg-slate-800 text-slate-300 border-slate-700';
            return `<span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold border ${cls} whitespace-nowrap">${escapeHTML(cat)}</span>`;
        }

        function renderCrmContactsTable() {
            const container = document.getElementById('crm-contacts-table-container');
            if (!container) return;

            const searchVal = (document.getElementById('crm-contacts-search')?.value || '').trim().toLowerCase();
            const platFilter = (document.getElementById('crm-filter-platform')?.value || 'all').toLowerCase();
            const catFilter = (document.getElementById('crm-filter-category')?.value || 'all');

            const filtered = crmContactsList.filter(c => {
                if (platFilter !== 'all') {
                    const combinedPlats = `${c.platform || 'manual'},${c.source_type || ''}`.toLowerCase();
                    if (!combinedPlats.includes(platFilter)) return false;
                }
                if (catFilter !== 'all' && (c.category || 'New Lead') !== catFilter) return false;
                if (searchVal) {
                    const hay = [
                        c.first_name,
                        c.middle_name,
                        c.last_name,
                        c.contact_number,
                        c.email_address,
                        c.social_username,
                        c.account_name,
                        c.company,
                        c.category,
                        c.notes,
                        c.platform,
                        c.source_type
                    ].join(' ').toLowerCase();
                    if (!hay.includes(searchVal)) return false;
                }
                return true;
            });

            if (filtered.length === 0) {
                container.innerHTML = `
                    <div class="flex flex-col items-center justify-center py-16 px-4 text-center text-slate-400">
                        <div class="w-14 h-14 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 mb-3">
                            <i class="fas fa-address-book text-2xl"></i>
                        </div>
                        <h4 class="text-sm font-bold text-white">${crmContactsList.length === 0 ? 'No Contacts in CRM Database Yet' : 'No Matching Contacts Found'}</h4>
                        <p class="text-xs text-slate-400 max-w-md mt-1">
                            ${crmContactsList.length === 0
                                ? 'Click "+ Create Contact", click "Sync & Combine" to pull from Cloudinary / WhatsApp / Telegram, or click "+ Add to Contacts" on any message or comment!'
                                : 'Try clearing your search or changing the Platform / Category filter above.'}
                        </p>
                        ${crmContactsList.length === 0 ? `
                            <div class="flex flex-wrap items-center justify-center gap-2 mt-4">
                                <button type="button" onclick="openCrmContactModal()" class="px-4 py-2 rounded-xl bg-gradient-to-r from-emerald-400 to-gb-cyan text-slate-950 font-extrabold text-xs flex items-center gap-2 shadow-lg">
                                    <i class="fas fa-user-plus"></i>
                                    <span>+ Create Your First Contact</span>
                                </button>
                                <button type="button" onclick="syncAllCrmContactsWithDeduplication()" class="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-gb-cyan/50 text-gb-cyan font-bold text-xs flex items-center gap-2">
                                    <i class="fas fa-sync-alt"></i>
                                    <span>Sync from Cloudinary, WhatsApp &amp; Telegram</span>
                                </button>
                                <button type="button" onclick="startGoogleContactsOAuthImport()" class="px-4 py-2 rounded-xl bg-red-500/15 hover:bg-red-500/25 border border-red-400/50 text-red-200 hover:text-white font-bold text-xs flex items-center gap-2">
                                    <i class="fab fa-google text-red-400"></i>
                                    <span>Import Google Contacts</span>
                                </button>
                            </div>
                        ` : ''}
                    </div>
                `;
                return;
            }

            const rowsHTML = filtered.map((c, idx) => {
                const fullName = [c.first_name, c.middle_name, c.last_name].filter(Boolean).join(' ') || c.social_username || 'Unnamed Contact';
                const plat = (c.platform || 'manual').toLowerCase();

                // Build multi-platform badges if this contact was combined from multiple sources (e.g. Manual + WhatsApp + Telegram)
                const rawSources = `${plat},${c.source_type || ''}`
                    .split(',')
                    .map(s => s.trim().toLowerCase())
                    .filter(s => ['facebook', 'instagram', 'tiktok', 'youtube', 'whatsapp', 'telegram', 'gmail', 'microsoft', 'imap', 'google_contacts', 'manual'].includes(s));
                const uniqueSources = [...new Set(rawSources)];
                if (uniqueSources.length === 0) uniqueSources.push('manual');

                const multiBadgesHTML = uniqueSources.map(sp => {
                    if (sp === 'manual') {
                        return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-800 border border-slate-600 text-[10px] font-semibold text-slate-300"><i class="fas fa-user-tag text-gb-cyan"></i> Manual</span>`;
                    }
                    return getPlatformBadge(sp, uniqueSources.length === 1);
                }).join(' ');

                const combinedBadgeHTML = uniqueSources.length > 1
                    ? `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/15 border border-amber-400/40 text-amber-300 text-[9px] font-bold" title="Combined duplicate contact across ${uniqueSources.join(', ').toUpperCase()}">
                           <i class="fas fa-code-branch"></i> Combined (${uniqueSources.length})
                       </span>`
                    : '';

                const phoneHTML = c.contact_number
                    ? `<a href="tel:${escapeHTML(c.contact_number)}" class="text-xs font-semibold text-emerald-300 hover:underline flex items-center gap-1 whitespace-nowrap">
                           <i class="fas fa-phone-alt text-[10px]"></i> ${escapeHTML(c.contact_number)}
                       </a>`
                    : `<span class="text-[11px] text-slate-600 italic">—</span>`;

                const emailHTML = c.email_address
                    ? `<button type="button" onclick="composeEmailToCrmContact('${escapeHTML(c.email_address)}')" class="text-xs font-semibold text-gb-cyan hover:underline flex items-center gap-1.5 text-left truncate max-w-[200px]" title="Click to compose email to ${escapeHTML(c.email_address)}">
                           <i class="fas fa-envelope text-[10px] shrink-0"></i>
                           <span class="truncate">${escapeHTML(c.email_address)}</span>
                       </button>`
                    : `<span class="text-[11px] text-slate-600 italic">—</span>`;

                const caps = getCrmContactMessagingCapabilities(c);
                const effUsername = caps.socialUsername;
                const openChatBtnClasses = caps.isReachable
                    ? 'p-1.5 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/30 border border-emerald-400/50 text-emerald-300 text-xs transition-all cursor-pointer shadow-[0_0_10px_rgba(16,185,129,0.18)]'
                    : 'p-1.5 rounded-lg bg-slate-800/40 border border-slate-700/60 text-slate-600 text-xs transition-all cursor-default';
                const openChatTitle = caps.isReachable
                    ? 'Open Chat in Message Tab (Choose Platform: Email, SMS, WhatsApp, or Telegram)'
                    : 'Open Chat in Message Tab (No Mobile Number, Email, or Social Username saved)';

                return `
                    <tr class="border-b border-slate-800/80 hover:bg-slate-900/80 transition-colors">
                        <td class="py-3 px-3.5 text-xs font-bold text-slate-500">#${idx + 1}</td>
                        <td class="py-3 px-3.5 whitespace-nowrap">
                            <span class="text-xs sm:text-sm font-bold text-white">${escapeHTML(c.first_name || '—')}</span>
                        </td>
                        <td class="py-3 px-3.5 whitespace-nowrap">
                            <span class="text-xs text-slate-300">${escapeHTML(c.middle_name || '—')}</span>
                        </td>
                        <td class="py-3 px-3.5 whitespace-nowrap">
                            <span class="text-xs sm:text-sm font-bold text-white">${escapeHTML(c.last_name || '—')}</span>
                        </td>
                        <td class="py-3 px-3.5 whitespace-nowrap">
                            ${phoneHTML}
                        </td>
                        <td class="py-3 px-3.5">
                            ${emailHTML}
                        </td>
                        <td class="py-3 px-3.5 whitespace-nowrap">
                            <div class="flex flex-col gap-1">
                                <div class="flex items-center gap-1.5 flex-wrap">${multiBadgesHTML} ${combinedBadgeHTML}</div>
                                ${effUsername ? `<span class="text-[11px] text-slate-300 font-medium truncate max-w-[180px]" title="${escapeHTML(effUsername)}">${escapeHTML(effUsername)}</span>` : ''}
                                ${c.account_name ? `<span class="text-[10px] text-slate-500 truncate max-w-[180px]">via ${escapeHTML(c.account_name)}</span>` : ''}
                            </div>
                        </td>
                        <td class="py-3 px-3.5 whitespace-nowrap">
                            ${getCrmCategoryBadgeHTML(c.category)}
                        </td>
                        <td class="py-3 px-3.5 max-w-[230px]">
                            ${c.company ? `<div class="text-xs font-semibold text-slate-200 truncate">${escapeHTML(c.company)}</div>` : ''}
                            <div class="text-[11px] text-slate-400 line-clamp-2" title="${escapeHTML(c.notes || '')}">${c.notes ? escapeHTML(c.notes) : '<span class="italic text-slate-600">No notes</span>'}</div>
                        </td>
                        <td class="py-3 px-3.5 whitespace-nowrap text-[11px] text-slate-400">
                            ${escapeHTML(c.updated_at || c.created_at || '')}
                        </td>
                        <td class="py-3 px-3.5 text-right whitespace-nowrap">
                            <div class="inline-flex items-center gap-1.5">
                                <button type="button" onclick="handleOpenChatFromCrmContact('${escapeHTML(c.id)}', event)" class="${openChatBtnClasses}" title="${escapeHTML(openChatTitle)}">
                                    <i class="fas fa-comments"></i>
                                </button>
                                <button type="button" onclick="editCrmContactById('${escapeHTML(c.id)}')" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-600 text-slate-200 hover:text-gb-cyan text-xs font-semibold transition-all" title="Edit Contact">
                                    <i class="fas fa-edit mr-1"></i>Edit
                                </button>
                                <button type="button" onclick="deleteCrmContactById('${escapeHTML(c.id)}', '${escapeHTML(fullName)}')" class="p-1.5 rounded-lg bg-rose-950/60 hover:bg-rose-600 border border-rose-500/40 text-rose-300 hover:text-white text-xs transition-all" title="Delete Contact">
                                    <i class="fas fa-trash-alt"></i>
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');

            container.innerHTML = `
                <table class="w-full text-left border-collapse min-w-[1050px]">
                    <thead>
                        <tr class="border-b border-slate-800 bg-slate-900/95 text-[10px] font-bold uppercase tracking-wider text-slate-400 sticky top-0 z-10">
                            <th class="py-3 px-3.5">#</th>
                            <th class="py-3 px-3.5">First Name</th>
                            <th class="py-3 px-3.5">Middle Name</th>
                            <th class="py-3 px-3.5">Last Name</th>
                            <th class="py-3 px-3.5">Contact Number</th>
                            <th class="py-3 px-3.5">Email Address</th>
                            <th class="py-3 px-3.5">Platform &amp; Username</th>
                            <th class="py-3 px-3.5">Category</th>
                            <th class="py-3 px-3.5">Company &amp; Notes</th>
                            <th class="py-3 px-3.5">Date Updated</th>
                            <th class="py-3 px-3.5 text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rowsHTML}
                    </tbody>
                </table>
            `;
        }


        // =========================================================================
        // --- GOOGLE CONTACTS OAUTH2 POPUP & AUTO-IMPORT (COMPOSIO API) ---
        // =========================================================================
        let googleContactsOAuthPollTimer = null;

        async function startGoogleContactsOAuthImport() {
            const btn = document.getElementById('btn-import-google-contacts');
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<i class="fas fa-circle-notch fa-spin text-red-400"></i> <span>Connecting Google...</span>';
            }

            const width = 560;
            const height = 680;
            const left = Math.max(0, Math.round((window.screen.width - width) / 2));
            const top = Math.max(0, Math.round((window.screen.height - height) / 2));
            const popup = window.open(
                'about:blank',
                'glennbot_google_contacts_oauth',
                `width=${width},height=${height},left=${left},top=${top},resizable=yes,scrollbars=yes`
            );

            if (popup) {
                try {
                    popup.document.open();
                    popup.document.write(`<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Import Google Contacts...</title></head>
<body style="background:#050b14;color:#e2e8f0;font-family:'Segoe UI',system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;">
    <div style="background:rgba(15,23,42,0.95);border:1px solid rgba(0,240,255,0.45);border-radius:16px;padding:32px 28px;max-width:390px;box-shadow:0 0 35px rgba(0,240,255,0.2);">
        <div style="width:36px;height:36px;border:3px solid rgba(0,240,255,0.2);border-top-color:#00f0ff;border-radius:50%;margin:0 auto 14px auto;animation:spin 0.8s linear infinite;"></div>
        <style>@keyframes spin { to { transform: rotate(360deg); } }</style>
        <div style="color:#00f0ff;font-size:17px;font-weight:700;margin-bottom:8px;">Connecting to Google Contacts...</div>
        <p style="color:#94a3b8;font-size:13px;line-height:1.5;margin:0;">Preparing secure Composio OAuth2 login. Your contacts will be imported automatically right after login...</p>
    </div>
</body>
</html>`);
                    popup.document.close();
                } catch (e) {}
            }

            showToast('🔗 Opening Google Account Login to import your Google Contacts...');

            try {
                const res = await fetch('/api/oauth/google-contacts/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
                const data = await res.json();
                if (data.status === 'success' && data.auth_url) {
                    const connId = data.connected_account_id || '';
                    const entityId = data.entity_id || '';
                    if (popup && !popup.closed) {
                        popup.location.href = data.auth_url;
                        popup.focus();
                    } else {
                        window.open(data.auth_url, '_blank');
                    }

                    if (googleContactsOAuthPollTimer) clearInterval(googleContactsOAuthPollTimer);
                    let attempts = 0;
                    googleContactsOAuthPollTimer = setInterval(async () => {
                        attempts++;
                        if (attempts > 45 || (popup && popup.closed)) {
                            clearInterval(googleContactsOAuthPollTimer);
                            googleContactsOAuthPollTimer = null;
                            try {
                                const impRes = await fetch('/api/contacts/import/google', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ connected_account_id: connId, entity_id: entityId })
                                });
                                const impData = await impRes.json();
                                if (impData.status === 'success') {
                                    crmContactsList = impData.contacts || [];
                                    updateCrmBadgesAndStats();
                                    renderCrmContactsTable();
                                    showToast(`✅ Imported ${impData.imported_count || 0} Google Contact(s) from ${impData.account_email || 'Google'}!`);
                                } else {
                                    await fetchCrmContacts(true);
                                }
                            } catch (_) {
                                await fetchCrmContacts(true);
                            }
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = '<i class="fab fa-google text-red-400"></i> <span>Import Google Contacts</span>';
                            }
                        }
                    }, 3000);
                } else {
                    if (popup && !popup.closed) popup.close();
                    showToast('❌ ' + (data.message || 'Could not start Google Contacts OAuth.'));
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = '<i class="fab fa-google text-red-400"></i> <span>Import Google Contacts</span>';
                    }
                }
            } catch (err) {
                if (popup && !popup.closed) popup.close();
                showToast('❌ Failed to launch Google Contacts OAuth popup.');
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fab fa-google text-red-400"></i> <span>Import Google Contacts</span>';
                }
            }
        }

        window.addEventListener('message', async (event) => {
            const d = event.data || {};
            if (d && d.type === 'GLENNBOT_GOOGLE_CONTACTS_IMPORT_DONE') {
                if (googleContactsOAuthPollTimer) {
                    clearInterval(googleContactsOAuthPollTimer);
                    googleContactsOAuthPollTimer = null;
                }
                const btn = document.getElementById('btn-import-google-contacts');
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fab fa-google text-red-400"></i> <span>Import Google Contacts</span>';
                }
                await fetchCrmContacts(false);
                showToast(`✅ Imported ${d.imported_count || 0} Google Contact(s) from ${d.account_email || 'Google Account'}!`);
            }
        });

        function exportCrmContactsToCsv() {
            if (crmContactsList.length === 0) {
                showToast('⚠️ No contacts to export yet.');
                return;
            }
            const headers = [
                'First Name',
                'Middle Name',
                'Last Name',
                'Contact Number',
                'Email Address',
                'Platform',
                'Social Username',
                'Connected Page',
                'Category',
                'Company',
                'Notes',
                'Updated At'
            ];
            const escapeCsv = (val) => `"${String(val || '').replace(/"/g, '""')}"`;
            const rows = crmContactsList.map(c => [
                c.first_name,
                c.middle_name,
                c.last_name,
                c.contact_number,
                c.email_address,
                c.platform,
                c.social_username,
                c.account_name,
                c.category,
                c.company,
                c.notes,
                c.updated_at || c.created_at
            ].map(escapeCsv).join(','));

            const csvContent = '\uFEFF' + [headers.map(escapeCsv).join(','), ...rows].join('\r\n');
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `GlennBot_CRM_Contacts_${new Date().toISOString().slice(0, 10)}.csv`;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => {
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }, 1000);
            showToast(`📥 Exported ${crmContactsList.length} contact(s) to CSV!`);
        }

        // =========================================================================
        // --- REAL-TIME EMAIL WEBHOOK & NOTIFICATION ENGINE ---
        // =========================================================================
        let lastEmailRealtimeSeq = -1;

        function playRealtimeEmailChime() {
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (!AudioCtx) return;
                const ctx = new AudioCtx();
                const now = ctx.currentTime;
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'sine';
                osc.frequency.setValueAtTime(587.33, now);       // D5
                osc.frequency.setValueAtTime(880.0, now + 0.11); // A5
                gain.gain.setValueAtTime(0.001, now);
                gain.gain.exponentialRampToValueAtTime(0.08, now + 0.02);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(now);
                osc.stop(now + 0.36);
            } catch (_) {}
        }

        async function openEmailWebhookModal() {
            const fallbackOrigin = window.location.origin.replace(/\/+$/, '');
            const urlInputInit = document.getElementById('email-webhook-url-input');
            const bannerCodeInit = document.getElementById('email-webhook-banner-code');
            if (urlInputInit && !urlInputInit.value) urlInputInit.value = `${fallbackOrigin}/webhooks`;
            if (bannerCodeInit && (!bannerCodeInit.textContent || bannerCodeInit.textContent === '/webhooks')) {
                bannerCodeInit.textContent = `${fallbackOrigin}/webhooks`;
            }
            openModalWithFade('email-webhook-modal');
            try {
                const res = await fetch('/api/email/webhook/status');
                const data = await res.json();
                if (data.status === 'success') {
                    const urlInput = document.getElementById('email-webhook-url-input');
                    const bannerCode = document.getElementById('email-webhook-banner-code');
                    const secInput = document.getElementById('email-webhook-secret-input');
                    const hitsEl = document.getElementById('email-webhook-hits-count');
                    const timeEl = document.getElementById('email-webhook-last-time');
                    if (urlInput && data.webhook_url) urlInput.value = data.webhook_url;
                    if (bannerCode && data.webhook_url) bannerCode.textContent = data.webhook_url;
                    if (secInput && data.signing_secret) secInput.value = data.signing_secret;
                    if (hitsEl) hitsEl.textContent = String(data.webhook_hits_count || 0);
                    if (timeEl) timeEl.textContent = data.last_webhook_received_at || 'Listening live...';
                }
            } catch (_) {}
        }

        function closeEmailWebhookModal() {
            closeModalWithFade('email-webhook-modal');
        }

        async function copyEmailWebhookField(inputId, label) {
            const el = document.getElementById(inputId);
            const val = (el ? el.value : '').trim();
            if (!val) return;
            try {
                await navigator.clipboard.writeText(val);
                showToast(`✅ Copied ${label}!`);
            } catch (_) {
                if (el) {
                    el.select();
                    document.execCommand('copy');
                    showToast(`✅ Copied ${label}!`);
                }
            }
        }

        async function saveAndActivateEmailWebhook() {
            const btn = document.getElementById('btn-save-email-webhook');
            const urlVal = (document.getElementById('email-webhook-url-input')?.value || '').trim();
            const secVal = (document.getElementById('email-webhook-secret-input')?.value || '').trim();
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Activating...`;
            }
            try {
                const res = await fetch('/api/email/webhook/setup', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ webhook_url: urlVal, signing_secret: secVal })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast('✅ Real-Time Email Webhook & Signing Secret saved and triggers activated!');
                } else {
                    showToast('⚠️ ' + (data.message || 'Could not save webhook settings.'));
                }
            } catch (e) {
                showToast('⚠️ Network error while saving webhook settings.');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<i class="fas fa-bolt"></i> <span>Save &amp; Activate Triggers</span>`;
                }
            }
        }

        async function sendTestEmailWebhookNotification() {
            const btn = document.getElementById('btn-test-email-webhook');
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Sending Test...`;
            }
            try {
                const res = await fetch('/api/email/webhook/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_id: activeEmailAccountId || '' })
                });
                const data = await res.json();
                if (data.status === 'success' && data.event) {
                    closeEmailWebhookModal();
                    handleIncomingRealtimeEmailEvent(data.event);
                }
            } catch (e) {
                showToast('⚠️ Could not trigger test email notification.');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<i class="fas fa-bell"></i> <span>Test Real-Time Email Notification</span>`;
                }
            }
        }

        function openEmailFromRealtimeNotification(accountId, messageId, bannerId) {
            const bannerEl = document.getElementById(bannerId);
            if (bannerEl) bannerEl.remove();
            if (activeTab !== 'email') {
                switchTab('email');
            }
            if (accountId && activeEmailAccountId !== accountId) {
                selectSingleEmailAccount(accountId).then(() => {
                    if (messageId) selectEmailMessageToRead(messageId, true);
                });
            } else if (messageId) {
                selectEmailMessageToRead(messageId, true);
            }
        }

        function showRealtimeEmailFloatingBanner(evt) {
            const container = document.getElementById('realtime-email-notification-container');
            if (!container || !evt || !evt.message) return;

            const msg = evt.message;
            const bannerId = `rt-email-banner-${evt.seq || Date.now()}`;
            const senderLabel = msg.sender_name || msg.sender || 'New Sender';
            const subjLabel = msg.subject || '(No Subject)';
            const accEmail = evt.account_email || 'Inbox';

            const card = document.createElement('div');
            card.id = bannerId;
            card.className = 'pointer-events-auto p-3.5 rounded-2xl bg-slate-950/95 border-2 border-gb-cyan shadow-[0_0_30px_rgba(0,240,255,0.35)] text-xs text-white flex flex-col gap-2 transition-all duration-300';
            card.innerHTML = `
                <div class="flex items-start justify-between gap-2">
                    <div class="flex items-center gap-2 min-w-0">
                        <span class="w-7 h-7 rounded-xl bg-gb-cyan/20 border border-gb-cyan/50 flex items-center justify-center text-gb-cyan shrink-0">
                            <i class="fas fa-bolt text-xs"></i>
                        </span>
                        <div class="min-w-0">
                            <div class="text-[10px] font-extrabold uppercase tracking-wider text-gb-cyan flex items-center gap-1.5">
                                <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping"></span>
                                <span>Real-Time Webhook • New Email</span>
                            </div>
                            <div class="text-[11px] text-slate-400 truncate">To: ${escapeHTML(accEmail)}</div>
                        </div>
                    </div>
                    <button type="button" onclick="document.getElementById('${bannerId}')?.remove()" class="text-slate-400 hover:text-white px-1">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="space-y-0.5 pl-1">
                    <div class="font-bold text-white truncate">${escapeHTML(senderLabel)}</div>
                    <div class="font-semibold text-gb-cyan line-clamp-1">${escapeHTML(subjLabel)}</div>
                    <div class="text-[11px] text-slate-300 line-clamp-2">${escapeHTML(msg.snippet || msg.body || '')}</div>
                </div>
                <div class="flex items-center justify-between gap-2 pt-1 border-t border-slate-800/80">
                    <span class="text-[9px] font-mono text-emerald-300/90 flex items-center gap-1">
                        <i class="fas fa-shield-alt"></i> /webhooks • HMAC Verified
                    </span>
                    <button type="button" onclick="openEmailFromRealtimeNotification('${escapeHTML(evt.account_id || '')}', '${escapeHTML(msg.id || '')}', '${bannerId}')"
                        class="px-3 py-1 rounded-lg bg-gb-cyan text-slate-950 font-extrabold text-[11px] flex items-center gap-1 hover:opacity-95 transition-all">
                        <i class="fas fa-eye text-[10px]"></i>
                        <span>Open Email</span>
                    </button>
                </div>
            `;
            container.prepend(card);
            setTimeout(() => {
                const el = document.getElementById(bannerId);
                if (el) el.remove();
            }, 14000);
        }

        const notifiedEmailMsgIdsClient = new Set();

        function handleIncomingRealtimeEmailEvent(evt) {
            if (!evt || !evt.message) return;
            const newMsg = evt.message;
            const msgIdStr = String(newMsg.id || '');
            const isTestEvt = msgIdStr.startsWith('test_wh_');

            if (evt.seq && evt.seq > lastEmailRealtimeSeq) {
                lastEmailRealtimeSeq = evt.seq;
            }

            // Only skip if this exact message ID already triggered a Webhook notification on the client!
            // NEVER skip just because the 2-second inbox sync already loaded the message into the inbox list,
            // so the Real-Time Webhook ALWAYS triggers the notification banner on every new email!
            const alreadyNotified = msgIdStr && notifiedEmailMsgIdsClient.has(msgIdStr) && !isTestEvt;
            if (msgIdStr) {
                notifiedEmailMsgIdsClient.add(msgIdStr);
            }

            // If user has this email account selected, smoothly prepend the new email into the Inbox list
            // WITHOUT resetting their scroll position or closing the email they are currently reading!
            const alreadyInList = (
                activeEmailAccountId &&
                evt.account_id === activeEmailAccountId &&
                activeEmailFolder === 'inbox' &&
                activeEmailMessages.some(m => String(m.id) === msgIdStr)
            );

            if (activeEmailAccountId && evt.account_id === activeEmailAccountId && activeEmailFolder === 'inbox' && !alreadyInList) {
                activeEmailMessages = [newMsg, ...activeEmailMessages];
                activeEmailMessages = sortEmailMessagesNewestFirst(activeEmailMessages);
                renderEmailMessagesList();
            }

            if (alreadyNotified) {
                return;
            }

            playRealtimeEmailChime();
            showRealtimeEmailFloatingBanner(evt);

            // Update Email sidebar unread badge immediately even if user is on another tab
            const unreadBadge = document.getElementById('nav-email-unread-badge');
            if (unreadBadge) {
                const curCount = parseInt(unreadBadge.textContent || '0', 10) || 0;
                const nextCount = curCount + 1;
                unreadBadge.textContent = String(nextCount);
                unreadBadge.classList.remove('hidden');
            }
        }

        async function pollRealtimeEmailWebhookEvents() {
            if (window._gbInFlightPolls && window._gbInFlightPolls.emailRealtime) return;
            if (window._gbInFlightPolls) window._gbInFlightPolls.emailRealtime = true;
            try {
                const res = await _gbFetchWithTimeout(`/api/email/realtime_events?since_seq=${lastEmailRealtimeSeq}`, {}, 7000);
                const data = await res.json();
                if (data.status !== 'success') return;

                const hitsEl = document.getElementById('email-webhook-hits-count');
                const timeEl = document.getElementById('email-webhook-last-time');
                if (hitsEl && data.webhook_hits_count !== undefined) {
                    hitsEl.textContent = String(data.webhook_hits_count);
                }
                if (timeEl && data.last_webhook_received_at) {
                    timeEl.textContent = data.last_webhook_received_at;
                }

                // First call after page load: sync sequence number without replaying old events
                if (lastEmailRealtimeSeq < 0) {
                    lastEmailRealtimeSeq = Number(data.latest_seq || 0);
                    return;
                }

                const events = Array.isArray(data.events) ? data.events : [];
                for (const evt of events) {
                    handleIncomingRealtimeEmailEvent(evt);
                }
            } catch (_) {
            } finally {
                if (window._gbInFlightPolls) window._gbInFlightPolls.emailRealtime = false;
            }
        }

