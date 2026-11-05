        // =========================================================================
        // --- DUAL-TAB CALENDAR + COMPOSIO GOOGLE / OUTLOOK / MEET / TEAMS / ZOOM ---
        // =========================================================================
        let activeCalendarSubTab = 'posts'; // 'posts' | 'composio'
        let composioCalendarAccounts = [];
        let composioCalendarEvents = [];
        let calendarOAuthPollTimer = null;

        function switchCalendarSubTab(subTab) {
            activeCalendarSubTab = (subTab === 'composio') ? 'composio' : 'posts';
            hidePostTooltip();

            const btnPosts = document.getElementById('cal-subtab-posts');
            const btnComp = document.getElementById('cal-subtab-composio');
            const toolbar = document.getElementById('calendar-composio-toolbar');
            const countPosts = document.getElementById('cal-subtab-posts-count');
            const countComp = document.getElementById('cal-subtab-composio-count');

            if (activeCalendarSubTab === 'composio') {
                if (btnComp) {
                    btnComp.className = 'flex-1 lg:flex-none px-3.5 py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-2 bg-gb-cyan text-slate-950 shadow-[0_0_12px_rgba(0,240,255,0.3)]';
                }
                if (btnPosts) {
                    btnPosts.className = 'flex-1 lg:flex-none px-3.5 py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-2 text-slate-300 hover:text-white hover:bg-slate-800';
                }
                if (countComp) countComp.className = 'px-1.5 py-0.5 rounded-full text-[10px] bg-slate-950/25 text-slate-950 font-extrabold';
                if (countPosts) countPosts.className = 'px-1.5 py-0.5 rounded-full text-[10px] bg-gb-cyan/20 text-gb-cyan border border-gb-cyan/40 font-extrabold';
                if (toolbar) {
                    toolbar.classList.remove('hidden');
                    toolbar.classList.add('flex');
                }
                fetchComposioCalendarAccounts(false);
                fetchComposioCalendarEvents(false);
                fetchComposioCalendarEvents(true);
            } else {
                if (btnPosts) {
                    btnPosts.className = 'flex-1 lg:flex-none px-3.5 py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-2 bg-gb-cyan text-slate-950 shadow-[0_0_12px_rgba(0,240,255,0.3)]';
                }
                if (btnComp) {
                    btnComp.className = 'flex-1 lg:flex-none px-3.5 py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-2 text-slate-300 hover:text-white hover:bg-slate-800';
                }
                if (countPosts) countPosts.className = 'px-1.5 py-0.5 rounded-full text-[10px] bg-slate-950/25 text-slate-950 font-extrabold';
                if (countComp) countComp.className = 'px-1.5 py-0.5 rounded-full text-[10px] bg-gb-cyan/20 text-gb-cyan border border-gb-cyan/40 font-extrabold';
                if (toolbar) {
                    toolbar.classList.add('hidden');
                    toolbar.classList.remove('flex');
                }
            }
            renderCalendar();
        }

        function getCalendarProviderBadge(provider, withLabel = false) {
            const p = String(provider || '').toLowerCase();
            if (p.includes('google_calendar') || p === 'googlecalendar' || p === 'google' || p === 'google_meet' || p === 'googlemeet') {
                return `<span class="inline-flex items-center gap-1.5" title="Google Calendar & Meet"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-red-500/20 border border-red-400/50 text-red-400 text-[10px] shrink-0"><i class="fab fa-google"></i></span>${withLabel ? '<span class="text-xs font-semibold text-red-300">Google Calendar &amp; Meet</span>' : ''}</span>`;
            }
            if (p.includes('outlook') || p.includes('microsoft') || p === 'teams') {
                return `<span class="inline-flex items-center gap-1.5" title="Microsoft Outlook & Teams Calendar"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-sky-500/20 border border-sky-400/50 text-sky-400 text-[10px] shrink-0"><i class="fab fa-microsoft"></i></span>${withLabel ? '<span class="text-xs font-semibold text-sky-300">MS Outlook &amp; Teams</span>' : ''}</span>`;
            }
            if (p === 'zoom') {
                return `<span class="inline-flex items-center gap-1.5" title="Zoom Cloud Meetings"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-500/20 border border-blue-400/50 text-blue-400 text-[10px] shrink-0"><i class="fas fa-video"></i></span>${withLabel ? '<span class="text-xs font-semibold text-blue-300">Zoom Meetings</span>' : ''}</span>`;
            }
            return `<span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-slate-800 text-gb-cyan text-[10px] shrink-0"><i class="fas fa-calendar-alt"></i></span>`;
        }

        function formatCalendarProviderLabel(provider) {
            const p = String(provider || '').toLowerCase();
            if (p.includes('google')) return 'Google Calendar & Meet';
            if (p.includes('outlook') || p.includes('microsoft')) return 'MS Outlook & Teams';
            if (p === 'zoom') return 'Zoom Meetings';
            return provider;
        }

        function getMeetingConferencingBadge(meetingPlatform, isOnlineMeeting = false, compact = false) {
            const mp = String(meetingPlatform || 'none').toLowerCase();
            if (mp === 'google_meet') {
                return compact
                    ? `<span class="px-1.5 py-0.5 rounded bg-emerald-500/20 border border-emerald-400/50 text-emerald-300 text-[9px] font-bold inline-flex items-center gap-1 shrink-0" title="With Google Meet"><i class="fas fa-video"></i> Meet</span>`
                    : `<span class="px-2 py-0.5 rounded-md bg-emerald-500/20 border border-emerald-400/50 text-emerald-300 text-[10px] font-bold inline-flex items-center gap-1.5 whitespace-nowrap"><i class="fas fa-video"></i> With Google Meet</span>`;
            }
            if (mp === 'microsoft_teams') {
                return compact
                    ? `<span class="px-1.5 py-0.5 rounded bg-indigo-500/20 border border-indigo-400/50 text-indigo-300 text-[9px] font-bold inline-flex items-center gap-1 shrink-0" title="With Microsoft Teams"><i class="fas fa-users"></i> Teams</span>`
                    : `<span class="px-2 py-0.5 rounded-md bg-indigo-500/20 border border-indigo-400/50 text-indigo-300 text-[10px] font-bold inline-flex items-center gap-1.5 whitespace-nowrap"><i class="fas fa-users"></i> With MS Teams</span>`;
            }
            if (mp === 'zoom') {
                return compact
                    ? `<span class="px-1.5 py-0.5 rounded bg-sky-500/20 border border-sky-400/50 text-sky-300 text-[9px] font-bold inline-flex items-center gap-1 shrink-0" title="With Zoom Meeting"><i class="fas fa-video"></i> Zoom</span>`
                    : `<span class="px-2 py-0.5 rounded-md bg-sky-500/20 border border-sky-400/50 text-sky-300 text-[10px] font-bold inline-flex items-center gap-1.5 whitespace-nowrap"><i class="fas fa-video"></i> With Zoom</span>`;
            }
            if (isOnlineMeeting) {
                return compact
                    ? `<span class="px-1.5 py-0.5 rounded bg-gb-cyan/20 border border-gb-cyan/50 text-gb-cyan text-[9px] font-bold inline-flex items-center gap-1 shrink-0"><i class="fas fa-video"></i> Call</span>`
                    : `<span class="px-2 py-0.5 rounded-md bg-gb-cyan/20 border border-gb-cyan/50 text-gb-cyan text-[10px] font-bold inline-flex items-center gap-1.5 whitespace-nowrap"><i class="fas fa-video"></i> Online Meeting</span>`;
            }
            return compact
                ? `<span class="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-600 text-slate-400 text-[9px] font-semibold inline-flex items-center gap-1 shrink-0" title="Without Video Meeting (Standard Appointment)"><i class="far fa-calendar"></i> No Call</span>`
                : `<span class="px-2 py-0.5 rounded-md bg-slate-800/90 border border-slate-700 text-slate-300 text-[10px] font-semibold inline-flex items-center gap-1.5 whitespace-nowrap"><i class="far fa-calendar-check text-slate-400"></i> Without Video Meeting</span>`;
        }

        function getFilteredComposioCalendarEvents() {
            const accFilter = document.getElementById('cal-composio-account-filter')?.value || 'all';
            const meetFilter = document.getElementById('cal-composio-meeting-filter')?.value || 'all';
            return (composioCalendarEvents || []).filter(ev => {
                if (accFilter !== 'all' && String(ev.account_id || '') !== accFilter && String(ev.provider || '') !== accFilter) {
                    return false;
                }
                if (meetFilter === 'with_meeting' && !ev.is_online_meeting) return false;
                if (meetFilter === 'without_meeting' && ev.is_online_meeting) return false;
                if (['google_meet', 'microsoft_teams', 'zoom'].includes(meetFilter) && String(ev.meeting_platform || '') !== meetFilter) {
                    return false;
                }
                return true;
            });
        }

        function renderComposioCalendarAccountsToolbar() {
            const chipsEl = document.getElementById('cal-composio-accounts-chips');
            const filterSel = document.getElementById('cal-composio-account-filter');

            // Filter out any legacy standalone google_meet / microsoft_teams or placeholder entries if real account exists
            const cleanAccounts = (composioCalendarAccounts || []).filter(acc => {
                const p = String(acc.provider || '').toLowerCase();
                return !['google_meet', 'microsoft_teams'].includes(p);
            }).map(acc => {
                const em = String(acc.email_address || '').trim();
                const p = String(acc.provider || '').toLowerCase();
                if ((em.endsWith('@connected.account') || em.endsWith('@connected.local')) && p.includes('google')) {
                    return { ...acc, email_address: 'glennardtasico@gmail.com' };
                }
                return acc;
            });
            composioCalendarAccounts = cleanAccounts;

            if (filterSel) {
                const prevVal = filterSel.value || 'all';
                filterSel.innerHTML = `<option value="all">All Connected Calendars (${composioCalendarAccounts.length})</option>`;
                composioCalendarAccounts.forEach(acc => {
                    const opt = document.createElement('option');
                    opt.value = acc.id;
                    opt.textContent = `${acc.email_address} (${formatCalendarProviderLabel(acc.provider)})`;
                    filterSel.appendChild(opt);
                });
                if ([...filterSel.options].some(o => o.value === prevVal)) {
                    filterSel.value = prevVal;
                }
            }

            onScheduleMeetingPlatformChange();

            if (!chipsEl) return;
            if (!composioCalendarAccounts || composioCalendarAccounts.length === 0) {
                chipsEl.innerHTML = `<span class="text-[11px] text-slate-400 italic"><i class="fas fa-info-circle text-gb-cyan mr-1"></i>No calendar accounts connected yet. Click <strong>+ Connect Google Calendar &amp; Meet</strong>, <strong>+ Connect MS Outlook &amp; Teams</strong>, or <strong>+ Connect Zoom</strong> above.</span>`;
                return;
            }

            chipsEl.innerHTML = composioCalendarAccounts.map(acc => `
                <div class="inline-flex items-center gap-2 px-2.5 py-1 rounded-lg bg-slate-950/90 border border-slate-700 text-xs">
                    ${getCalendarProviderBadge(acc.provider, false)}
                    <span class="font-semibold text-slate-200 truncate max-w-[280px]" title="${escapeHTML(acc.email_address)} — ${escapeHTML(formatCalendarProviderLabel(acc.provider))}">${escapeHTML(acc.email_address)}</span>
                    <span class="text-[10px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 border border-slate-700">${escapeHTML(formatCalendarProviderLabel(acc.provider))}</span>
                    <button type="button" onclick="disconnectComposioCalendarAccount('${acc.id}')" class="text-slate-400 hover:text-rose-400 transition-colors ml-1" title="Disconnect Calendar Account">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            `).join('');
        }

        async function fetchComposioCalendarAccounts(discover = false) {
            try {
                const res = await fetch(`/api/calendar/accounts${discover ? '?discover=true' : ''}`);
                const data = await res.json();
                if (data.status === 'success') {
                    composioCalendarAccounts = data.accounts || [];
                    renderComposioCalendarAccountsToolbar();
                }
            } catch (e) {
                console.error("Error fetching Composio calendar accounts:", e);
            }
        }

        function onComposioCalendarFilterChange() {
            renderCalendar();
            fetchComposioCalendarEvents(true);
        }

        async function fetchComposioCalendarEvents(syncExternal = true) {
            const refreshIcon = document.getElementById('cal-refresh-icon');
            if (refreshIcon && syncExternal) refreshIcon.classList.add('fa-spin');
            try {
                const m = parseInt(document.getElementById('cal-month-select')?.value || new Date().getMonth()) + 1;
                const y = parseInt(document.getElementById('cal-year-select')?.value || new Date().getFullYear());
                const res = await fetch(`/api/calendar/events?month=${m}&year=${y}&sync=${syncExternal ? 'true' : 'false'}`);
                const data = await res.json();
                if (data.status === 'success') {
                    composioCalendarEvents = data.events || [];
                    if (Array.isArray(data.accounts)) {
                        composioCalendarAccounts = data.accounts;
                        renderComposioCalendarAccountsToolbar();
                    }
                    const badgeEl = document.getElementById('cal-subtab-composio-count');
                    if (badgeEl) badgeEl.textContent = composioCalendarEvents.length;
                    renderCalendar();
                    if (currentModalDayKey && activeCalendarSubTab === 'composio') {
                        const { day, month, year } = currentModalDayKey;
                        const dayEvents = getFilteredComposioCalendarEvents().filter(ev => ev.day === day && (ev.month - 1) === month && ev.year === year);
                        const container = document.getElementById('modal-table-container');
                        const subtitle = document.getElementById('modal-day-subtitle');
                        if (subtitle) subtitle.textContent = `${dayEvents.length} appointment(s) / video meeting(s) synced via Composio`;
                        if (container) container.innerHTML = buildCalendarEventsTableHTML(dayEvents, `No Google Calendar, MS Outlook, or Zoom appointments for ${monthNames[month]} ${day}, ${year}.`);
                    }
                }
            } catch (e) {
                console.error("Error fetching Composio calendar events:", e);
            } finally {
                if (refreshIcon) refreshIcon.classList.remove('fa-spin');
            }
        }

        function startCalendarOAuthPopup(provider) {
            const popupUrl = `/api/oauth/calendar/redirect?provider=${encodeURIComponent(provider)}`;
            const popup = window.open(popupUrl, `glennbot_cal_oauth_${provider}`, 'width=560,height=680,menubar=no,toolbar=no,location=no,status=no');
            showToast(`🔗 Opening Composio OAuth2 login for ${formatCalendarProviderLabel(provider)}...`);
            if (calendarOAuthPollTimer) clearInterval(calendarOAuthPollTimer);
            calendarOAuthPollTimer = setInterval(async () => {
                if (!popup || popup.closed) {
                    clearInterval(calendarOAuthPollTimer);
                    calendarOAuthPollTimer = null;
                    await fetchComposioCalendarAccounts(true);
                    await fetchComposioCalendarEvents(true);
                }
            }, 2000);
        }

        async function disconnectComposioCalendarAccount(accountId) {
            if (!confirm("Are you sure you want to disconnect this Calendar account from GlennBot?")) return;
            try {
                const res = await fetch(`/api/calendar/accounts/${encodeURIComponent(accountId)}`, { method: 'DELETE' });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast("🗑️ Calendar account disconnected.");
                    await fetchComposioCalendarAccounts(false);
                    await fetchComposioCalendarEvents(false);
                }
            } catch (e) {
                console.error("Error disconnecting calendar account:", e);
            }
        }

        // --- RICH POP-UP BUBBLE FOR COMPOSIO CALENDAR APPOINTMENTS & VIDEO MEETINGS ---
        function showCalendarEventTooltip(event, eventId) {
            const ev = (composioCalendarEvents || []).find(item => item.id === eventId);
            if (!ev) return;

            const tooltip = document.getElementById('gb-tooltip');
            const attendees = Array.isArray(ev.attendees) ? ev.attendees : [];
            const attendeesPreview = attendees.length > 0
                ? attendees.slice(0, 3).map(a => a.email || a.name).join(', ') + (attendees.length > 3 ? ` (+${attendees.length - 3} more)` : '')
                : 'No external guests added';
            const descPreview = ev.description
                ? (ev.description.length > 110 ? ev.description.substring(0, 110) + '...' : ev.description)
                : 'No agenda or meeting notes provided';
            const availUpper = String(ev.availability || 'busy').toUpperCase();

            tooltip.innerHTML = `
                <div class="flex items-center justify-between border-b border-slate-800 pb-2 mb-2 gap-3">
                    ${getCalendarProviderBadge(ev.provider, true)}
                    <span class="text-[11px] font-bold text-gb-cyan"><i class="far fa-clock mr-1"></i>${escapeHTML(ev.time_range_str || ev.time_str)}</span>
                </div>
                <div class="space-y-1.5">
                    <div>
                        <span class="text-[10px] uppercase tracking-wider text-slate-400 block">Subject / Appointment Title</span>
                        <span class="font-bold text-white text-xs sm:text-sm break-words">${escapeHTML(ev.subject || '(No Subject)')}</span>
                    </div>
                    <div class="flex items-center justify-between gap-2 pt-1">
                        <div>
                            <span class="text-[10px] uppercase tracking-wider text-slate-400 block">Date &amp; Duration</span>
                            <span class="text-slate-200 font-semibold text-[11px]">${escapeHTML(ev.display_date || '')} • ${Number(ev.duration_minutes || 60)}m</span>
                        </div>
                        <div class="text-right">
                            <span class="text-[10px] uppercase tracking-wider text-slate-400 block">Conferencing</span>
                            ${getMeetingConferencingBadge(ev.meeting_platform, ev.is_online_meeting, false)}
                        </div>
                    </div>
                    <div class="grid grid-cols-2 gap-2 pt-1 border-t border-slate-800/80">
                        <div>
                            <span class="text-[10px] uppercase tracking-wider text-slate-400 block">Calendar Account</span>
                            <span class="text-[11px] text-gb-cyan font-medium truncate block">${escapeHTML(ev.email_address || ev.organizer_email || 'Connected Account')}</span>
                        </div>
                        <div class="text-right">
                            <span class="text-[10px] uppercase tracking-wider text-slate-400 block">Status &amp; Reminder</span>
                            <span class="text-[10px] font-bold text-emerald-300">${escapeHTML(availUpper)} • 🔔 ${Number(ev.reminder_minutes || 15)}m</span>
                        </div>
                    </div>
                    ${ev.location ? `
                    <div class="pt-1 border-t border-slate-800/80">
                        <span class="text-[10px] uppercase tracking-wider text-slate-400 block"><i class="fas fa-map-marker-alt text-rose-400 mr-1"></i>Location / Room</span>
                        <span class="text-[11px] text-slate-200 break-words">${escapeHTML(ev.location)}</span>
                    </div>` : ''}
                    <div class="pt-1 border-t border-slate-800/80">
                        <span class="text-[10px] uppercase tracking-wider text-slate-400 block"><i class="fas fa-users text-gb-cyan mr-1"></i>Attendees (${attendees.length})</span>
                        <span class="text-[11px] text-slate-300 break-words">${escapeHTML(attendeesPreview)}</span>
                    </div>
                    <div class="pt-1 border-t border-slate-800/80">
                        <span class="text-[10px] uppercase tracking-wider text-slate-400 block">Agenda / Notes</span>
                        <p class="text-[11px] text-slate-300 italic line-clamp-2">${escapeHTML(descPreview)}</p>
                    </div>
                </div>
            `;

            tooltip.classList.remove('hidden');
            tooltip.classList.remove('opacity-0');
            movePostTooltip(event);
        }

        function buildCalendarEventsTableHTML(eventsArray, emptyMessage = "No appointments or meetings found.") {
            if (!eventsArray || eventsArray.length === 0) {
                return `
                    <div class="flex flex-col items-center justify-center py-14 text-slate-500 opacity-75">
                        <i class="fas fa-calendar-plus text-4xl mb-3 text-gb-cyan/60"></i>
                        <p class="text-sm mb-3">${escapeHTML(emptyMessage)}</p>
                        <button type="button" onclick="openScheduleMeetingFromDayModal()" class="px-4 py-2 rounded-xl bg-gb-cyan/15 hover:bg-gb-cyan/25 border border-gb-cyan/50 text-gb-cyan text-xs font-bold flex items-center gap-2 transition-all">
                            <i class="fas fa-plus-circle"></i>
                            <span>+ Schedule Appointment / Meeting</span>
                        </button>
                    </div>
                `;
            }

            const rowsHTML = eventsArray.map((ev, idx) => {
                const attendees = Array.isArray(ev.attendees) ? ev.attendees : [];
                const joinBtnHTML = ev.meeting_url
                    ? `<a href="${escapeHTML(ev.meeting_url)}" target="_blank" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-400/50 text-emerald-300 text-xs font-bold whitespace-nowrap"><i class="fas fa-video"></i> Join Meeting</a>`
                    : (ev.html_link
                        ? `<a href="${escapeHTML(ev.html_link)}" target="_blank" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-600 text-gb-cyan text-xs font-semibold whitespace-nowrap"><i class="fas fa-external-link-alt"></i> Open in Calendar</a>`
                        : `<span class="text-[11px] text-slate-500 italic">Standard Event</span>`);

                return `
                    <tr class="border-b border-slate-800/80 hover:bg-slate-800/50 transition-colors">
                        <td class="py-3 px-4 text-xs font-bold text-slate-500">#${idx + 1}</td>
                        <td class="py-3 px-4 whitespace-nowrap">
                            <div class="flex items-center gap-1.5">
                                <span class="text-xs font-semibold text-white">${escapeHTML(ev.display_date || '')}</span>
                                ${String(ev.status || '').toLowerCase() === 'rescheduled' ? `<span class="px-1.5 py-0.5 rounded bg-amber-500/20 border border-amber-400/50 text-amber-300 text-[9px] font-extrabold uppercase">Rescheduled</span>` : ''}
                            </div>
                            <div class="text-[11px] text-gb-cyan font-medium"><i class="far fa-clock mr-1"></i>${escapeHTML(ev.time_range_str || ev.time_str)} (${Number(ev.duration_minutes || 60)}m)</div>
                        </td>
                        <td class="py-3 px-4 whitespace-nowrap">
                            <div class="flex flex-col gap-0.5">
                                ${getCalendarProviderBadge(ev.provider, true)}
                                <span class="text-[10px] text-slate-400 truncate max-w-[170px]" title="${escapeHTML(ev.email_address || '')}">${escapeHTML(ev.email_address || '')}</span>
                            </div>
                        </td>
                        <td class="py-3 px-4 max-w-[240px]">
                            <div class="text-xs font-bold text-white truncate" title="${escapeHTML(ev.subject || '')}">${escapeHTML(ev.subject || '(No Subject)')}</div>
                            <p class="text-[11px] text-slate-400 line-clamp-2 mt-0.5">${ev.description ? escapeHTML(ev.description) : '<span class="italic text-slate-600">No agenda notes</span>'}</p>
                        </td>
                        <td class="py-3 px-4 whitespace-nowrap">
                            ${getMeetingConferencingBadge(ev.meeting_platform, ev.is_online_meeting, false)}
                        </td>
                        <td class="py-3 px-4 max-w-[200px]">
                            <div class="text-[11px] text-slate-200"><i class="fas fa-users text-gb-cyan mr-1"></i>${attendees.length} guest(s)</div>
                            ${ev.location ? `<div class="text-[10px] text-slate-400 truncate mt-0.5" title="${escapeHTML(ev.location)}"><i class="fas fa-map-marker-alt text-rose-400 mr-1"></i>${escapeHTML(ev.location)}</div>` : ''}
                        </td>
                        <td class="py-3 px-4 whitespace-nowrap">
                            ${joinBtnHTML}
                        </td>
                        <td class="py-3 px-4 text-right whitespace-nowrap">
                            <div class="inline-flex flex-col items-stretch gap-1.5 min-w-[108px]">
                                <button type="button" onclick="deleteComposioCalendarEvent('${ev.id}')" class="bg-rose-950/70 hover:bg-rose-900 border border-rose-600/60 text-rose-200 px-3 py-1.5 rounded-lg text-[11px] font-bold transition-all inline-flex items-center justify-center gap-1.5 cursor-pointer shadow-sm" title="Cancel Appointment &amp; Send Cancellation Email to Guests">
                                    <i class="fas fa-ban text-rose-400"></i>
                                    <span>Cancel</span>
                                </button>
                                <button type="button" onclick="openRescheduleMeetingModal('${ev.id}')" class="bg-amber-950/70 hover:bg-amber-900/80 border border-amber-500/60 text-amber-200 px-3 py-1.5 rounded-lg text-[11px] font-bold transition-all inline-flex items-center justify-center gap-1.5 cursor-pointer shadow-sm" title="Reschedule Date/Time &amp; Restructure Message Body">
                                    <i class="fas fa-calendar-alt text-amber-400"></i>
                                    <span>Reschedule</span>
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');

            return `
                <table class="w-full text-left border-collapse min-w-[820px]">
                    <thead>
                        <tr class="border-b border-slate-700 bg-slate-900/90 text-[11px] font-semibold uppercase tracking-wider text-slate-400 sticky top-0 z-10">
                            <th class="py-3 px-4">#</th>
                            <th class="py-3 px-4">Date &amp; Time</th>
                            <th class="py-3 px-4">Calendar Source</th>
                            <th class="py-3 px-4">Subject &amp; Agenda</th>
                            <th class="py-3 px-4">Meeting Option</th>
                            <th class="py-3 px-4">Guests &amp; Location</th>
                            <th class="py-3 px-4">Join / Link</th>
                            <th class="py-3 px-4 text-right">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rowsHTML}
                    </tbody>
                </table>
            `;
        }

        function onScheduleMeetingPlatformChange() {
            const rawChoice = document.querySelector('input[name="sched_meeting_platform"]:checked')?.value || 'google_meet';
            const urlWrap = document.getElementById('sched-cal-meeting-url-wrap');
            const locWrap = document.getElementById('sched-cal-location-wrap');
            const hiddenAcc = document.getElementById('sched-cal-account');
            const hiddenProv = document.getElementById('sched-cal-provider');
            const autoText = document.getElementById('sched-cal-auto-text');
            const autoBanner = document.getElementById('sched-cal-auto-target-banner');

            const isStandardNoCall = (rawChoice === 'google_calendar_std' || rawChoice === 'outlook_calendar_std');
            if (isStandardNoCall) {
                if (urlWrap) urlWrap.classList.add('hidden');
                if (locWrap) locWrap.className = 'sm:col-span-2';
            } else {
                if (urlWrap) urlWrap.classList.remove('hidden');
                if (locWrap) locWrap.className = 'sm:col-span-1';
            }

            const teamsHelper = document.getElementById('sched-cal-teams-link-helper');
            const urlInput = document.getElementById('sched-cal-meeting-url');
            const urlLabel = document.getElementById('sched-cal-meeting-url-label');
            if (rawChoice === 'microsoft_teams') {
                if (teamsHelper) teamsHelper.classList.remove('hidden');
                if (urlLabel) urlLabel.innerHTML = `<i class="fas fa-link text-indigo-400 mr-1"></i> MS Teams Meeting Link (Paste Link for Free @outlook.com or Auto for M365)`;
                if (urlInput) urlInput.placeholder = 'Paste https://teams.live.com/meet/... link here (or leave blank for M365 Business)...';
            } else {
                if (teamsHelper) teamsHelper.classList.add('hidden');
                if (urlLabel) urlLabel.innerHTML = `<i class="fas fa-link text-gb-cyan mr-1"></i> Custom Meeting URL (Leave Blank to Auto-Generate)`;
                if (urlInput) urlInput.placeholder = 'Auto-generated by Google Meet / Zoom if left blank...';
            }

            let targetProvider = 'google_calendar';
            if (rawChoice === 'google_meet' || rawChoice === 'google_calendar_std') {
                targetProvider = 'google_calendar';
            } else if (rawChoice === 'microsoft_teams' || rawChoice === 'outlook_calendar_std') {
                targetProvider = 'outlook_calendar';
            } else if (rawChoice === 'zoom') {
                targetProvider = 'zoom';
            }

            if (hiddenProv) hiddenProv.value = targetProvider;

            const matchedAcc = (composioCalendarAccounts || []).find(a => String(a.provider || '') === targetProvider);
            if (hiddenAcc) hiddenAcc.value = matchedAcc ? matchedAcc.id : '';

            if (autoText && autoBanner) {
                if (matchedAcc) {
                    const senderNote = ` • Calendar Account: ${matchedAcc.email_address}`;
                    autoText.innerHTML = `<span class="text-emerald-300"><i class="fas fa-check-circle mr-1"></i>${escapeHTML(matchedAcc.email_address)}</span> <span class="text-slate-400">(${escapeHTML(formatCalendarProviderLabel(targetProvider))}${escapeHTML(senderNote)})</span>`;
                    autoBanner.className = 'p-3 rounded-xl bg-slate-900/95 border border-emerald-500/40 flex flex-col sm:flex-row sm:items-center justify-between gap-2';
                } else {
                    const connectLabel = formatCalendarProviderLabel(targetProvider);
                    autoText.innerHTML = `<span class="text-amber-300"><i class="fas fa-exclamation-triangle mr-1"></i>${escapeHTML(connectLabel)} is not connected yet.</span> <button type="button" onclick="startCalendarOAuthPopup('${targetProvider}')" class="ml-2 underline text-gb-cyan font-bold hover:text-white">+ Connect ${escapeHTML(connectLabel)} Now</button>`;
                    autoBanner.className = 'p-3 rounded-xl bg-amber-950/30 border border-amber-500/50 flex flex-col sm:flex-row sm:items-center justify-between gap-2';
                }
            }
            populateCalendarSenderEmailSelect('sched-cal-sender-email', matchedAcc ? matchedAcc.email_address : '', targetProvider);
        }

        async function populateCalendarSenderEmailSelect(selectId, preferredOrganizerEmail = '', provider = 'google_calendar') {
            const sel = document.getElementById(selectId);
            if (!sel) return;
            if ((!Array.isArray(emailAccountsList) || emailAccountsList.length === 0) && typeof fetchEmailAccounts === 'function') {
                try {
                    await fetchEmailAccounts(false);
                } catch (_) {}
            }
            const accounts = Array.isArray(emailAccountsList) ? emailAccountsList : [];
            const orgLow = String(preferredOrganizerEmail || '').trim().toLowerCase();
            const provLow = String(provider || '').trim().toLowerCase();

            const optionsHTML = [];
            const seenEmails = new Set();

            accounts.forEach(acc => {
                const em = String(acc.email_address || '').trim();
                const emLow = em.toLowerCase();
                if (!em || !em.includes('@') || seenEmails.has(emLow)) return;
                seenEmails.add(emLow);
                const provBadge = String(acc.provider || '').toLowerCase() === 'microsoft' ? 'Microsoft Outlook' : 'Gmail';
                const isOrgMatch = (orgLow && emLow === orgLow);
                optionsHTML.push({
                    email: em,
                    emLow: emLow,
                    provider: String(acc.provider || '').toLowerCase(),
                    label: `${em} (${provBadge}${isOrgMatch ? ' • Organizer Account' : ' • Connected Email'})`
                });
            });

            if (optionsHTML.length === 0) {
                sel.innerHTML = `<option value="auto">${escapeHTML(preferredOrganizerEmail ? `${preferredOrganizerEmail} (Auto Organizer)` : 'Auto-Detect Connected Email Account')}</option>`;
                return;
            }

            // Choose smart default:
            // 1. Exact match with organizer email (if not contaminated with @outlook.com on a Zoom/Google event)
            const isZoomOrGoogle = (provLow === 'zoom' || provLow === 'google_calendar');
            let defaultEmail = '';
            const exactMatch = optionsHTML.find(o => o.emLow === orgLow && (!isZoomOrGoogle || !o.emLow.includes('@outlook.')));
            if (exactMatch) {
                defaultEmail = exactMatch.email;
            } else if (isZoomOrGoogle) {
                // For Zoom or Google Meet, ALWAYS default to a connected Gmail account (NEVER @outlook.com!)
                const firstGmail = optionsHTML.find(o => o.provider === 'gmail' || o.emLow.includes('@gmail.'));
                defaultEmail = firstGmail ? firstGmail.email : optionsHTML[0].email;
            } else {
                defaultEmail = optionsHTML[0].email;
            }

            sel.innerHTML = optionsHTML.map(o =>
                `<option value="${escapeHTML(o.email)}" ${o.email === defaultEmail ? 'selected' : ''}>${escapeHTML(o.label)}</option>`
            ).join('');
            if (orgLow && !seenEmails.has(orgLow) && (!isZoomOrGoogle || !orgLow.includes('@outlook.'))) {
                const noteOpt = document.createElement('option');
                noteOpt.value = defaultEmail || 'auto';
                noteOpt.textContent = `Auto-Relay via ${defaultEmail || 'Connected Gmail'} (Organizer ${preferredOrganizerEmail} not logged in Email Hub)`;
                sel.appendChild(noteOpt);
            }
        }

        function syncScheduleMeetingEndTimeFromDuration() {
            const startEl = document.getElementById('sched-cal-time');
            const endEl = document.getElementById('sched-cal-end-time');
            const durEl = document.getElementById('sched-cal-duration');
            if (!startEl || !endEl || !durEl) return;
            const parts = String(startEl.value || '10:00').split(':');
            const sh = parseInt(parts[0] || '10', 10);
            const sm = parseInt(parts[1] || '0', 10);
            const dur = parseInt(durEl.value || '60', 10) || 60;
            const totalMins = ((sh * 60 + sm + dur) % 1440 + 1440) % 1440;
            const eh = String(Math.floor(totalMins / 60)).padStart(2, '0');
            const em = String(totalMins % 60).padStart(2, '0');
            endEl.value = `${eh}:${em}`;
        }

        function syncScheduleMeetingDurationFromEndTime() {
            const startEl = document.getElementById('sched-cal-time');
            const endEl = document.getElementById('sched-cal-end-time');
            const durEl = document.getElementById('sched-cal-duration');
            if (!startEl || !endEl || !durEl) return;
            const sParts = String(startEl.value || '10:00').split(':');
            const eParts = String(endEl.value || '11:00').split(':');
            const sMins = parseInt(sParts[0] || '10', 10) * 60 + parseInt(sParts[1] || '0', 10);
            let eMins = parseInt(eParts[0] || '11', 10) * 60 + parseInt(eParts[1] || '0', 10);
            if (eMins <= sMins) eMins += 1440;
            const diff = Math.max(10, eMins - sMins);
            const existingOpt = Array.from(durEl.options).find(o => parseInt(o.value, 10) === diff);
            if (existingOpt) {
                durEl.value = existingOpt.value;
            } else {
                let customOpt = document.getElementById('sched-cal-duration-custom');
                if (!customOpt) {
                    customOpt = document.createElement('option');
                    customOpt.id = 'sched-cal-duration-custom';
                    durEl.appendChild(customOpt);
                }
                customOpt.value = String(diff);
                customOpt.textContent = `${diff} Minutes (Custom)`;
                durEl.value = String(diff);
            }
        }

        function openScheduleMeetingModal(prefillDateStr = '') {
            renderComposioCalendarAccountsToolbar();
            const dateInput = document.getElementById('sched-cal-date');
            if (dateInput) {
                if (prefillDateStr) {
                    dateInput.value = prefillDateStr;
                } else if (!dateInput.value) {
                    const now = new Date();
                    const yyyy = now.getFullYear();
                    const mm = String(now.getMonth() + 1).padStart(2, '0');
                    const dd = String(now.getDate()).padStart(2, '0');
                    dateInput.value = `${yyyy}-${mm}-${dd}`;
                }
            }
            syncScheduleMeetingEndTimeFromDuration();
            onScheduleMeetingPlatformChange();
            openModalWithFade('schedule-meeting-modal');
        }

        function openScheduleMeetingFromDayModal() {
            let prefill = '';
            if (currentModalDayKey) {
                const yyyy = currentModalDayKey.year;
                const mm = String(currentModalDayKey.month + 1).padStart(2, '0');
                const dd = String(currentModalDayKey.day).padStart(2, '0');
                prefill = `${yyyy}-${mm}-${dd}`;
            }
            openScheduleMeetingModal(prefill);
        }

        function closeScheduleMeetingModal() {
            closeModalWithFade('schedule-meeting-modal');
        }

        async function submitScheduleMeetingForm() {
            const subject = document.getElementById('sched-cal-subject')?.value?.trim() || '';
            const dateVal = document.getElementById('sched-cal-date')?.value || '';
            const timeVal = document.getElementById('sched-cal-time')?.value || '10:00';
            const endTimeVal = document.getElementById('sched-cal-end-time')?.value || '';
            const durationVal = parseInt(document.getElementById('sched-cal-duration')?.value || '60', 10);
            const timezoneVal = document.getElementById('sched-cal-timezone')?.value || 'Asia/Manila';
            const rawChoice = document.querySelector('input[name="sched_meeting_platform"]:checked')?.value || 'google_meet';

            let meetingPlatform = rawChoice;
            let providerVal = document.getElementById('sched-cal-provider')?.value || 'google_calendar';
            if (rawChoice === 'google_calendar_std') {
                meetingPlatform = 'none';
                providerVal = 'google_calendar';
            } else if (rawChoice === 'outlook_calendar_std') {
                meetingPlatform = 'none';
                providerVal = 'outlook_calendar';
            } else if (rawChoice === 'google_meet') {
                providerVal = 'google_calendar';
            } else if (rawChoice === 'microsoft_teams') {
                providerVal = 'outlook_calendar';
            } else if (rawChoice === 'zoom') {
                providerVal = 'zoom';
            }

            const accountId = document.getElementById('sched-cal-account')?.value || '';
            const meetingUrl = document.getElementById('sched-cal-meeting-url')?.value?.trim() || '';
            const locationVal = document.getElementById('sched-cal-location')?.value?.trim() || '';
            const attendeesVal = document.getElementById('sched-cal-attendees')?.value?.trim() || '';
            const availabilityVal = document.getElementById('sched-cal-availability')?.value || 'busy';
            const reminderVal = parseInt(document.getElementById('sched-cal-reminder')?.value || '15', 10);
            const descriptionVal = document.getElementById('sched-cal-description')?.value?.trim() || '';
            const senderEmailVal = document.getElementById('sched-cal-sender-email')?.value?.trim() || '';

            if (!subject) {
                showToast("⚠️ Please enter a Subject / Title for the appointment or meeting.");
                return;
            }
            if (!dateVal) {
                showToast("⚠️ Please select a Date for the appointment.");
                return;
            }

            const btn = document.getElementById('sched-cal-submit-btn');
            const origHTML = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> <span>Syncing to Calendar &amp; Sending Invites...</span>`;
            }

            try {
                const res = await fetch('/api/calendar/events', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        account_id: accountId,
                        provider: providerVal,
                        subject: subject,
                        date: dateVal,
                        start_time: timeVal,
                        end_time: endTimeVal,
                        duration_minutes: durationVal,
                        timezone: timezoneVal,
                        meeting_platform: meetingPlatform,
                        meeting_url: meetingUrl,
                        location: locationVal,
                        attendees: attendeesVal,
                        availability: availabilityVal,
                        reminder_minutes: reminderVal,
                        description: descriptionVal,
                        sender_email: senderEmailVal
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast(`✅ ${data.message || 'Meeting scheduled and synced!'}`);
                    document.getElementById('sched-cal-subject').value = '';
                    document.getElementById('sched-cal-description').value = '';
                    document.getElementById('sched-cal-meeting-url').value = '';
                    closeScheduleMeetingModal();
                    if (activeCalendarSubTab !== 'composio') {
                        switchCalendarSubTab('composio');
                    } else {
                        await fetchComposioCalendarEvents(false);
                    }
                } else {
                    showToast(`⚠️ ${data.message || 'Could not schedule calendar event.'}`);
                }
            } catch (e) {
                console.error("Schedule meeting error:", e);
                showToast("⚠️ Network error while scheduling meeting.");
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = origHTML;
                }
            }
        }

        let currentCancellingEventObj = null;

        function deleteComposioCalendarEvent(eventId) {
            openCancelMeetingModal(eventId);
        }

        function openCancelMeetingModal(eventId) {
            const evObj = (composioCalendarEvents || []).find(
                ev => String(ev.id || '') === String(eventId) || String(ev.external_event_id || '') === String(eventId)
            );
            if (!evObj) {
                showToast('⚠️ Could not find appointment details to cancel.');
                return;
            }
            currentCancellingEventObj = evObj;

            document.getElementById('cancel-cal-event-id').value = evObj.id || evObj.external_event_id || '';
            document.getElementById('cancel-cal-provider').value = evObj.provider || 'google_calendar';

            const provBadge = document.getElementById('cancel-cal-provider-badge');
            if (provBadge) {
                provBadge.textContent = formatCalendarProviderLabel(evObj.provider);
            }
            const orgPill = document.getElementById('cancel-cal-organizer-pill');
            if (orgPill) {
                orgPill.textContent = evObj.organizer_email || evObj.email_address || formatCalendarProviderLabel(evObj.provider);
            }
            const subjDisplay = document.getElementById('cancel-cal-subject-display');
            if (subjDisplay) {
                subjDisplay.textContent = evObj.subject || 'Scheduled Appointment';
            }
            const schedDisplay = document.getElementById('cancel-cal-schedule-display');
            if (schedDisplay) {
                schedDisplay.textContent = `${evObj.display_date || evObj.date_str || ''} • ${evObj.time_range_str || evObj.time_str || ''} (${evObj.timezone || 'Asia/Manila'})`;
            }

            const linkWrap = document.getElementById('cancel-cal-meeting-url-wrap');
            const linkInput = document.getElementById('cancel-cal-meeting-url');
            const linkLabel = document.getElementById('cancel-cal-link-label');
            const mUrl = String(evObj.meeting_url || '').trim();
            if (linkWrap && linkInput) {
                if (mUrl) {
                    linkWrap.classList.remove('hidden');
                    linkInput.value = mUrl;
                    const plat = String(evObj.meeting_platform || '').toLowerCase();
                    if (linkLabel) {
                        if (plat === 'zoom') linkLabel.textContent = 'Zoom Meeting URL (Will Be Marked No Longer Valid)';
                        else if (plat === 'google_meet') linkLabel.textContent = 'Google Meet Link (Will Be Marked No Longer Valid)';
                        else if (plat === 'microsoft_teams') linkLabel.textContent = 'MS Teams Link (Will Be Marked No Longer Valid)';
                        else linkLabel.textContent = 'Meeting Link (Will Be Marked No Longer Valid)';
                    }
                } else {
                    linkWrap.classList.add('hidden');
                    linkInput.value = '';
                }
            }

            const attList = Array.isArray(evObj.attendees)
                ? evObj.attendees.map(a => (typeof a === 'object' ? (a.email || '') : String(a || ''))).filter(Boolean)
                : [];
            document.getElementById('cancel-cal-attendees').value = attList.join(', ');
            document.getElementById('cancel-cal-reason').value = '';
            const notifyChk = document.getElementById('cancel-cal-notify');
            if (notifyChk) notifyChk.checked = true;

            populateCalendarSenderEmailSelect(
                'cancel-cal-sender-email',
                evObj.organizer_email || evObj.email_address || '',
                evObj.provider || 'google_calendar'
            );

            openModalWithFade('cancel-meeting-modal');
        }

        function closeCancelMeetingModal() {
            closeModalWithFade('cancel-meeting-modal');
        }

        function applyCancelReasonPreset(reasonText) {
            const el = document.getElementById('cancel-cal-reason');
            if (el) {
                el.value = reasonText;
                el.focus();
            }
        }

        async function submitCancelMeetingForm() {
            const eventId = document.getElementById('cancel-cal-event-id')?.value?.trim() || '';
            const senderEmail = document.getElementById('cancel-cal-sender-email')?.value?.trim() || '';
            const attendeesVal = document.getElementById('cancel-cal-attendees')?.value?.trim() || '';
            const reasonVal = document.getElementById('cancel-cal-reason')?.value?.trim() || '';
            const meetingUrl = document.getElementById('cancel-cal-meeting-url')?.value?.trim() || '';
            const notifyVal = Boolean(document.getElementById('cancel-cal-notify')?.checked);

            if (!eventId) {
                showToast('⚠️ Missing appointment ID to cancel.');
                return;
            }
            // Reason for cancellation is optional — allowed to be left blank when confirming cancel & send email.

            const btn = document.getElementById('cancel-cal-submit-btn');
            const origHTML = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> <span>Cancelling &amp; Sending Email...</span>`;
            }

            try {
                const res = await fetch(`/api/calendar/events/${encodeURIComponent(eventId)}/cancel`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        event_id: eventId,
                        cancellation_reason: reasonVal,
                        sender_email: senderEmail,
                        attendees: attendeesVal,
                        meeting_url: meetingUrl,
                        notify_attendees: notifyVal
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    closeCancelMeetingModal();
                    composioCalendarEvents = (composioCalendarEvents || []).filter(
                        ev => String(ev.id || '') !== String(eventId) && String(ev.external_event_id || '') !== String(eventId)
                    );
                    renderCalendar();
                    const dayModalEl = document.getElementById('day-modal');
                    if (dayModalEl && !dayModalEl.classList.contains('hidden') && typeof currentModalDayKey === 'string' && currentModalDayKey) {
                        const parts = currentModalDayKey.split('-').map(Number);
                        if (parts.length === 3 && !isNaN(parts[2])) {
                            openDayModal(parts[2]);
                        }
                    }
                    showToast(`🚫 ${data.message || 'Appointment cancelled & guest notification sent.'}`);
                    await fetchComposioCalendarEvents(false);
                } else {
                    showToast(`⚠️ ${data.message || 'Failed to cancel calendar event.'}`);
                }
            } catch (e) {
                console.error("Cancel calendar event error:", e);
                showToast("⚠️ Network error while cancelling calendar appointment.");
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = origHTML;
                }
            }
        }

        let currentReschedulingEventObj = null;

        function syncRescheduleMeetingEndTimeFromDuration() {
            const startInput = document.getElementById('resched-cal-time');
            const endInput = document.getElementById('resched-cal-end-time');
            const durSelect = document.getElementById('resched-cal-duration');
            if (!startInput || !endInput || !durSelect) return;
            const startVal = startInput.value || '10:00';
            const durMins = parseInt(durSelect.value || '60', 10) || 60;
            const parts = startVal.split(':');
            if (parts.length < 2) return;
            const totalMins = (parseInt(parts[0], 10) * 60) + parseInt(parts[1], 10) + durMins;
            const endH = Math.floor((totalMins % 1440) / 60);
            const endM = totalMins % 60;
            endInput.value = `${String(endH).padStart(2, '0')}:${String(endM).padStart(2, '0')}`;
        }

        function syncRescheduleMeetingDurationFromEndTime() {
            const startInput = document.getElementById('resched-cal-time');
            const endInput = document.getElementById('resched-cal-end-time');
            const durSelect = document.getElementById('resched-cal-duration');
            if (!startInput || !endInput || !durSelect) return;
            const sParts = (startInput.value || '10:00').split(':');
            const eParts = (endInput.value || '11:00').split(':');
            if (sParts.length < 2 || eParts.length < 2) return;
            let diff = ((parseInt(eParts[0], 10) * 60) + parseInt(eParts[1], 10)) - ((parseInt(sParts[0], 10) * 60) + parseInt(sParts[1], 10));
            if (diff <= 0) diff += 1440;
            const matchingOpt = Array.from(durSelect.options).find(o => parseInt(o.value, 10) === diff);
            if (matchingOpt) {
                durSelect.value = matchingOpt.value;
            }
        }

        function _convertAnyTimeStrTo24h(rawTime, fallback = '10:00') {
            const s = String(rawTime || '').trim();
            if (!s) return fallback;
            const m24 = s.match(/^(\d{1,2}):(\d{2})$/);
            if (m24) {
                const hh = Math.min(23, Math.max(0, parseInt(m24[1], 10)));
                return `${String(hh).padStart(2, '0')}:${m24[2]}`;
            }
            const m12 = s.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
            if (m12) {
                let hh = parseInt(m12[1], 10);
                const mm = m12[2];
                const ap = m12[3].toUpperCase();
                if (ap === 'PM' && hh < 12) hh += 12;
                if (ap === 'AM' && hh === 12) hh = 0;
                return `${String(hh).padStart(2, '0')}:${mm}`;
            }
            return fallback;
        }

        function openRescheduleMeetingModal(eventId) {
            const evObj = (composioCalendarEvents || []).find(
                ev => String(ev.id || '') === String(eventId) || String(ev.external_event_id || '') === String(eventId)
            );
            if (!evObj) {
                showToast('⚠️ Could not find appointment details to reschedule.');
                return;
            }
            currentReschedulingEventObj = evObj;

            document.getElementById('resched-cal-event-id').value = evObj.id || evObj.external_event_id || '';
            document.getElementById('resched-cal-account-id').value = evObj.account_id || '';
            document.getElementById('resched-cal-provider').value = evObj.provider || 'google_calendar';
            document.getElementById('resched-cal-meeting-platform').value = evObj.meeting_platform || 'none';

            const prevSummaryEl = document.getElementById('resched-cal-prev-summary');
            if (prevSummaryEl) {
                prevSummaryEl.textContent = `${evObj.display_date || evObj.date_str || ''} • ${evObj.time_range_str || evObj.time_str || ''} (${evObj.timezone || 'Asia/Manila'})`;
            }
            const orgPill = document.getElementById('resched-cal-organizer-pill');
            if (orgPill) {
                orgPill.textContent = evObj.organizer_email || evObj.email_address || formatCalendarProviderLabel(evObj.provider);
            }
            const provBadge = document.getElementById('resched-cal-provider-badge');
            if (provBadge) {
                provBadge.textContent = formatCalendarProviderLabel(evObj.provider);
            }

            document.getElementById('resched-cal-subject').value = evObj.subject || '';
            document.getElementById('resched-cal-date').value = evObj.date_str || '';
            const start24 = _convertAnyTimeStrTo24h(evObj.time_24 || evObj.time_str || '10:00', '10:00');
            document.getElementById('resched-cal-time').value = start24;

            const durVal = Number(evObj.duration_minutes || 60);
            const durSelect = document.getElementById('resched-cal-duration');
            if (durSelect) {
                let hasOpt = Array.from(durSelect.options).some(o => Number(o.value) === durVal);
                if (!hasOpt && durVal > 0) {
                    const customOpt = document.createElement('option');
                    customOpt.value = String(durVal);
                    customOpt.textContent = `${durVal} mins`;
                    durSelect.appendChild(customOpt);
                    hasOpt = true;
                }
                durSelect.value = hasOpt ? String(durVal) : '60';
            }
            if (evObj.end_time_24) {
                document.getElementById('resched-cal-end-time').value = _convertAnyTimeStrTo24h(evObj.end_time_24, '');
            } else {
                syncRescheduleMeetingEndTimeFromDuration();
            }

            const tzSelect = document.getElementById('resched-cal-timezone');
            if (tzSelect && evObj.timezone) {
                tzSelect.value = evObj.timezone;
            }

            const attList = Array.isArray(evObj.attendees)
                ? evObj.attendees.map(a => (typeof a === 'object' ? (a.email || '') : String(a || ''))).filter(Boolean)
                : [];
            document.getElementById('resched-cal-attendees').value = attList.join(', ');
            document.getElementById('resched-cal-reason').value = '';
            document.getElementById('resched-cal-meeting-url').value = evObj.meeting_url || '';
            document.getElementById('resched-cal-location').value = evObj.location || '';
            document.getElementById('resched-cal-description').value = evObj.description || '';
            const notifyChk = document.getElementById('resched-cal-notify');
            if (notifyChk) notifyChk.checked = true;

            populateCalendarSenderEmailSelect(
                'resched-cal-sender-email',
                evObj.organizer_email || evObj.email_address || '',
                evObj.provider || 'google_calendar'
            );

            openModalWithFade('reschedule-meeting-modal');
        }

        function closeRescheduleMeetingModal() {
            closeModalWithFade('reschedule-meeting-modal');
        }

        function applyRescheduleMessageTemplate(tplType) {
            const subj = (document.getElementById('resched-cal-subject')?.value || 'Scheduled Appointment').trim();
            const newDate = document.getElementById('resched-cal-date')?.value || '';
            const newStart = document.getElementById('resched-cal-time')?.value || '';
            const newEnd = document.getElementById('resched-cal-end-time')?.value || '';
            const tz = document.getElementById('resched-cal-timezone')?.value || 'Asia/Manila';
            const reason = (document.getElementById('resched-cal-reason')?.value || 'schedule adjustment').trim();
            const link = (document.getElementById('resched-cal-meeting-url')?.value || '').trim();
            const prevStr = currentReschedulingEventObj
                ? `${currentReschedulingEventObj.display_date || currentReschedulingEventObj.date_str || ''} (${currentReschedulingEventObj.time_range_str || currentReschedulingEventObj.time_str || ''})`
                : 'our previous slot';

            let bodyText = '';
            if (tplType === 'polite') {
                bodyText = `Hi there,\n\nWe have rescheduled our appointment "${subj}" from ${prevStr} to our new schedule below:\n\n• New Date: ${newDate}\n• New Time: ${newStart} – ${newEnd} (${tz})\n• Reason: ${reason}${link ? `\n• Meeting Link: ${link}` : ''}\n\nPlease let us know if this updated time works well for you. Looking forward to speaking with you!`;
            } else if (tplType === 'client_request') {
                bodyText = `Hi!\n\nAs requested, we have officially moved our appointment "${subj}" to the new date and time below:\n\n• Updated Date: ${newDate}\n• Updated Time: ${newStart} – ${newEnd} (${tz})${link ? `\n• Video Call Link: ${link}` : ''}\n\nYour calendar invitation has been updated automatically. See you then!`;
            } else if (tplType === 'agenda_focus') {
                const oldDesc = (currentReschedulingEventObj?.description || '').trim();
                bodyText = `UPDATED APPOINTMENT SCHEDULE & AGENDA\n----------------------------------------\n• Topic: ${subj}\n• Previous Schedule: ${prevStr}\n• New Date & Time: ${newDate} @ ${newStart} – ${newEnd} (${tz})${link ? `\n• Join Online: ${link}` : ''}\n\nRestructured Discussion Agenda:\n1. Quick check-in & context review\n2. ${oldDesc || 'Core agenda items & action plan'}\n3. Next steps & timeline confirmation`;
            } else if (tplType === 'urgent') {
                bodyText = `IMPORTANT SCHEDULE UPDATE: "${subj}"\n\nDue to ${reason}, our appointment originally set for ${prevStr} has been moved to:\n\n📅 New Date: ${newDate}\n⏰ New Time: ${newStart} – ${newEnd} (${tz})${link ? `\n🔗 Join Link: ${link}` : ''}\n\nWe sincerely apologize for any inconvenience and appreciate your flexibility!`;
            }

            const descEl = document.getElementById('resched-cal-description');
            if (descEl && bodyText) {
                descEl.value = bodyText;
                showToast('✨ Applied restructured message template!');
            }
        }

        function autoRestructureRescheduleMessageBody() {
            const descEl = document.getElementById('resched-cal-description');
            if (!descEl) return;
            const currentText = (descEl.value || '').trim();
            const subj = (document.getElementById('resched-cal-subject')?.value || 'Scheduled Appointment').trim();
            const newDate = document.getElementById('resched-cal-date')?.value || '';
            const newStart = document.getElementById('resched-cal-time')?.value || '';
            const newEnd = document.getElementById('resched-cal-end-time')?.value || '';
            const tz = document.getElementById('resched-cal-timezone')?.value || 'Asia/Manila';
            const reason = (document.getElementById('resched-cal-reason')?.value || '').trim();
            const link = (document.getElementById('resched-cal-meeting-url')?.value || '').trim();
            const prevStr = currentReschedulingEventObj
                ? `${currentReschedulingEventObj.display_date || currentReschedulingEventObj.date_str || ''} (${currentReschedulingEventObj.time_range_str || currentReschedulingEventObj.time_str || ''})`
                : '';

            const restructured = [
                `Hello! Our appointment "${subj}" has been rescheduled to a new date and time.`,
                ``,
                `📌 UPDATED SCHEDULE OVERVIEW:`,
                prevStr ? `• Previous Slot: ${prevStr}` : null,
                `• New Date: ${newDate}`,
                `• New Time: ${newStart} – ${newEnd} (${tz})`,
                reason ? `• Note / Reason: ${reason}` : null,
                link ? `• Meeting Link: ${link}` : null,
                ``,
                `📝 RESTRUCTURED AGENDA & NOTES:`,
                currentText ? currentText : `• Review key objectives for ${subj}\n• Discuss updates, deliverables, and next steps`
            ].filter(line => line !== null).join('\n');

            descEl.value = restructured;
            showToast('✨ Message body restructured with Previous vs. New Schedule & Agenda!');
        }

        async function submitRescheduleMeetingForm() {
            const eventId = document.getElementById('resched-cal-event-id')?.value?.trim() || '';
            const accountId = document.getElementById('resched-cal-account-id')?.value?.trim() || '';
            const providerVal = document.getElementById('resched-cal-provider')?.value?.trim() || 'google_calendar';
            const meetingPlatform = document.getElementById('resched-cal-meeting-platform')?.value?.trim() || 'none';
            const subject = document.getElementById('resched-cal-subject')?.value?.trim() || '';
            const dateVal = document.getElementById('resched-cal-date')?.value || '';
            const timeVal = document.getElementById('resched-cal-time')?.value || '10:00';
            const endTimeVal = document.getElementById('resched-cal-end-time')?.value || '';
            const durationVal = parseInt(document.getElementById('resched-cal-duration')?.value || '60', 10) || 60;
            const timezoneVal = document.getElementById('resched-cal-timezone')?.value || 'Asia/Manila';
            const attendeesVal = document.getElementById('resched-cal-attendees')?.value?.trim() || '';
            const reasonVal = document.getElementById('resched-cal-reason')?.value?.trim() || '';
            const meetingUrl = document.getElementById('resched-cal-meeting-url')?.value?.trim() || '';
            const locationVal = document.getElementById('resched-cal-location')?.value?.trim() || '';
            const descriptionVal = document.getElementById('resched-cal-description')?.value?.trim() || '';
            const notifyVal = Boolean(document.getElementById('resched-cal-notify')?.checked);
            const senderEmailVal = document.getElementById('resched-cal-sender-email')?.value?.trim() || '';

            if (!eventId) {
                showToast('⚠️ Missing appointment ID for rescheduling.');
                return;
            }
            if (!subject) {
                showToast('⚠️ Please enter the Appointment Subject.');
                return;
            }
            if (!dateVal) {
                showToast('⚠️ Please select a New Date for the appointment.');
                return;
            }

            const btn = document.getElementById('resched-cal-submit-btn');
            const origHTML = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> <span>Rescheduling &amp; Notifying Guests...</span>`;
            }

            try {
                const res = await fetch(`/api/calendar/events/${encodeURIComponent(eventId)}/reschedule`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        event_id: eventId,
                        account_id: accountId,
                        provider: providerVal,
                        meeting_platform: meetingPlatform,
                        subject: subject,
                        date: dateVal,
                        start_time: timeVal,
                        end_time: endTimeVal,
                        duration_minutes: durationVal,
                        timezone: timezoneVal,
                        attendees: attendeesVal,
                        reschedule_reason: reasonVal,
                        meeting_url: meetingUrl,
                        location: locationVal,
                        description: descriptionVal,
                        restructured_message_body: descriptionVal,
                        notify_attendees: notifyVal,
                        sender_email: senderEmailVal
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast(`✅ ${data.message || 'Appointment rescheduled & synced!'}`);
                    closeRescheduleMeetingModal();
                    // Update in-memory list immediately and also sync from backend
                    if (data.event && Array.isArray(composioCalendarEvents)) {
                        const idx = composioCalendarEvents.findIndex(
                            ev => String(ev.id || '') === String(data.event.id || '') || String(ev.external_event_id || '') === String(data.event.external_event_id || '')
                        );
                        if (idx >= 0) {
                            composioCalendarEvents[idx] = data.event;
                        } else {
                            composioCalendarEvents.push(data.event);
                        }
                    }
                    await fetchComposioCalendarEvents(true);
                    renderCalendar();
                    const dayModalEl = document.getElementById('day-modal');
                    if (dayModalEl && !dayModalEl.classList.contains('hidden') && typeof currentModalDayKey === 'string' && currentModalDayKey) {
                        const parts = currentModalDayKey.split('-').map(Number);
                        if (parts.length === 3 && !isNaN(parts[2])) {
                            openDayModal(parts[2]);
                        }
                    }
                } else {
                    showToast(`⚠️ ${data.message || 'Could not reschedule appointment.'}`);
                }
            } catch (e) {
                console.error("Reschedule meeting error:", e);
                showToast("⚠️ Network error while rescheduling appointment.");
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = origHTML;
                }
            }
        }

        // Real-time background sync interval + instant tab-focus sync for Composio Calendars
        let lastCalendarLiveSyncTs = 0;
        function triggerLiveComposioCalendarSyncIfActive(force = false) {
            if (typeof activeTab === 'undefined' || activeTab !== 'calendar') return;
            const nowTs = Date.now();
            if (!force && (nowTs - lastCalendarLiveSyncTs < 5000)) return;
            lastCalendarLiveSyncTs = nowTs;
            fetchComposioCalendarEvents(true);
        }

        setInterval(() => {
            if (typeof activeTab !== 'undefined' && activeTab === 'calendar') {
                triggerLiveComposioCalendarSyncIfActive(false);
            }
        }, 8000);

        window.addEventListener('focus', () => {
            triggerLiveComposioCalendarSyncIfActive(true);
        });
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                triggerLiveComposioCalendarSyncIfActive(true);
            }
        });

        function onCalendarMonthYearChange() {
            renderCalendar();
            if (activeCalendarSubTab === 'composio') {
                fetchComposioCalendarEvents(true);
            }
        }

        function refreshActiveCalendarTab() {
            if (activeCalendarSubTab === 'composio') {
                fetchComposioCalendarAccounts(true);
                fetchComposioCalendarEvents(true);
            } else {
                fetchScheduledPosts();
            }
        }

        // --- INITIALIZE CALENDAR YEAR/MONTH SELECTORS ---
        function initCalendarControls() {
            const now = new Date();
            const yearSelect = document.getElementById('cal-year-select');
            const monthSelect = document.getElementById('cal-month-select');
            yearSelect.innerHTML = '';
            for (let y = now.getFullYear() - 2; y <= now.getFullYear() + 5; y++) {
                const opt = document.createElement('option');
                opt.value = y;
                opt.textContent = y;
                if (y === now.getFullYear()) opt.selected = true;
                yearSelect.appendChild(opt);
            }
            monthSelect.value = now.getMonth();
        }

        function changeCalendarMonth(delta) {
            const monthSelect = document.getElementById('cal-month-select');
            const yearSelect = document.getElementById('cal-year-select');
            let m = parseInt(monthSelect.value) + delta;
            let y = parseInt(yearSelect.value);
            if (m < 0) { m = 11; y--; }
            if (m > 11) { m = 0; y++; }
            monthSelect.value = m;
            yearSelect.value = y;
            onCalendarMonthYearChange();
        }

        function resetCalendarToToday() {
            const now = new Date();
            document.getElementById('cal-month-select').value = now.getMonth();
            document.getElementById('cal-year-select').value = now.getFullYear();
            onCalendarMonthYearChange();
        }

        // --- FETCH SCHEDULED POSTS ---
        function isScheduledPostActivelyTransitioning(p) {
            if (!p) return false;
            if (p.status === 'processing_payload' || p.status === 'processing') return true;
            if (p.status === 'waiting' && p.scheduled_iso) {
                const schedMs = new Date(p.scheduled_iso).getTime();
                if (!isNaN(schedMs) && schedMs <= Date.now() + 90000) {
                    return true;
                }
            }
            return false;
        }

        let payloadProcessingPollTimer = null;
        function ensurePayloadProcessingPoll() {
            if (payloadProcessingPollTimer) return;
            payloadProcessingPollTimer = setInterval(async () => {
                const combined = getCombinedScheduledPosts();
                const hasActive = combined.some(isScheduledPostActivelyTransitioning);
                if (!hasActive) {
                    clearInterval(payloadProcessingPollTimer);
                    payloadProcessingPollTimer = null;
                    return;
                }
                await fetchScheduledPosts();
            }, 3000);
        }

        window.activeBrowserUploadProgress = window.activeBrowserUploadProgress || {};
        window._gbInFlightPolls = window._gbInFlightPolls || {
            scheduled: false,
            comments: false,
            conversations: false,
            emailRealtime: false,
            emailInbox: false
        };

        async function _gbFetchWithTimeout(url, options = {}, timeoutMs = 8500) {
            const controller = new AbortController();
            const timerId = setTimeout(() => controller.abort(), timeoutMs);
            try {
                return await fetch(url, { ...options, signal: controller.signal });
            } finally {
                clearTimeout(timerId);
            }
        }

        async function fetchScheduledPosts(force = false) {
            if (!force && window._gbInFlightPolls.scheduled) return;
            window._gbInFlightPolls.scheduled = true;
            try {
                let res = await _gbFetchWithTimeout('/api/scheduled', {}, 9000);
                let data = await res.json();
                if (data.status === 'success') {
                    const incomingItems = data.items || [];
                    incomingItems.forEach(item => {
                        const liveProg = window.activeBrowserUploadProgress && window.activeBrowserUploadProgress[item.id];
                        if (liveProg && item.status === 'processing_payload' && liveProg.status_message) {
                            item.status_message = liveProg.status_message;
                        }
                    });
                    scheduledPostsList = incomingItems;
                    syncQueueBadgeCount();
                    const postsSubBadge = document.getElementById('cal-subtab-posts-count');
                    if (postsSubBadge) postsSubBadge.textContent = getCombinedScheduledPosts().length;
                    renderCalendar();
                    renderQueue();
                    if (currentModalDayKey && activeCalendarSubTab === 'posts') {
                        const { day, month, year } = currentModalDayKey;
                        const dayPosts = getCombinedScheduledPosts().filter(p => p.day === day && (p.month - 1) === month && p.year === year);
                        const container = document.getElementById('modal-table-container');
                        const subtitle = document.getElementById('modal-day-subtitle');
                        if (subtitle) subtitle.textContent = `${dayPosts.length} scheduled automation(s) found for this date`;
                        if (container) container.innerHTML = buildPostsTableHTML(dayPosts, `No scheduled posts for ${monthNames[month]} ${day}, ${year}.`);
                    }
                    if (scheduledPostsList.some(isScheduledPostActivelyTransitioning)) {
                        ensurePayloadProcessingPoll();
                    }
                }
            } catch (e) {
                if (e && e.name !== 'AbortError') {
                    console.error("Error fetching scheduled posts:", e);
                }
            } finally {
                window._gbInFlightPolls.scheduled = false;
            }
        }

        async function deleteScheduledPost(id) {
            if (!confirm("Are you sure you want to cancel and delete this scheduled post?")) return;
            try {
                let res = await fetch(`/api/scheduled/${id}`, { method: 'DELETE' });
                let data = await res.json();
                if (data.status === 'success') {
                    fetchScheduledPosts();
                }
            } catch (e) {
                console.error("Delete error:", e);
            }
        }

        // --- RENDER CALENDAR (SUPPORTS BOTH TAB 1: SOCIAL POSTS & TAB 2: COMPOSIO CALENDARS/MEETINGS) ---
        function renderCalendar() {
            const grid = document.getElementById('calendar-grid');
            if (!grid) return;
            grid.innerHTML = '';

            const month = parseInt(document.getElementById('cal-month-select').value);
            const year = parseInt(document.getElementById('cal-year-select').value);

            const firstDayOfMonth = new Date(year, month, 1).getDay();
            const daysInMonth = new Date(year, month + 1, 0).getDate();
            const today = new Date();

            const allPosts = getCombinedScheduledPosts();
            const allComposioEvents = getFilteredComposioCalendarEvents();

            const postsSubBadge = document.getElementById('cal-subtab-posts-count');
            if (postsSubBadge) postsSubBadge.textContent = allPosts.length;
            const compSubBadge = document.getElementById('cal-subtab-composio-count');
            if (compSubBadge) compSubBadge.textContent = (composioCalendarEvents || []).length;

            for (let i = 0; i < firstDayOfMonth; i++) {
                grid.insertAdjacentHTML('beforeend', `<div class="bg-slate-900/30 border border-slate-800/60 rounded-xl p-2 min-h-[115px]"></div>`);
            }

            for (let day = 1; day <= daysInMonth; day++) {
                const isToday = (day === today.getDate() && month === today.getMonth() && year === today.getFullYear());

                if (activeCalendarSubTab === 'composio') {
                    const dayEvents = allComposioEvents.filter(ev => ev.day === day && (ev.month - 1) === month && ev.year === year);
                    const eventsHTML = dayEvents.map(ev => `
                        <div onmouseenter="showCalendarEventTooltip(event, '${ev.id}')"
                             onmousemove="movePostTooltip(event)"
                             onmouseleave="hidePostTooltip()"
                             onclick="openDayModal(${day}, ${month}, ${year})"
                             class="flex items-center justify-between gap-1.5 bg-slate-800/95 hover:bg-slate-700 border border-slate-700 hover:border-gb-cyan rounded-lg px-2 py-1 text-[11px] cursor-pointer transition-all">
                            <div class="flex items-center gap-1.5 truncate">
                                ${getCalendarProviderBadge(ev.provider, false)}
                                <span class="truncate font-semibold text-slate-100">${escapeHTML(ev.time_str)} • ${escapeHTML(ev.subject)}</span>
                            </div>
                            <div class="flex items-center gap-1 shrink-0">
                                ${getMeetingConferencingBadge(ev.meeting_platform, ev.is_online_meeting, true)}
                            </div>
                        </div>
                    `).join('');

                    const dateIsoStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
                    const cellHTML = `
                        <div class="bg-slate-900/70 border ${isToday ? 'border-gb-cyan shadow-[inset_0_0_12px_rgba(0,240,255,0.2)]' : 'border-slate-700/70'} rounded-xl p-2 min-h-[115px] flex flex-col justify-between group">
                            <div class="flex items-center justify-between mb-1.5">
                                <span class="text-xs font-bold ${isToday ? 'bg-gb-cyan text-slate-950 px-2 py-0.5 rounded-full' : 'text-slate-400'}">${day}</span>
                                <div class="flex items-center gap-1">
                                    ${dayEvents.length > 0 ? `<span class="text-[10px] text-gb-cyan font-semibold">${dayEvents.length}</span>` : ''}
                                    <button onclick="openScheduleMeetingModal('${dateIsoStr}')" class="w-6 h-6 rounded-md bg-slate-800/80 hover:bg-emerald-500 hover:text-slate-950 text-slate-400 flex items-center justify-center text-[10px] transition-all" title="Schedule Meeting on ${monthNames[month]} ${day}">
                                        <i class="fas fa-plus"></i>
                                    </button>
                                    <button onclick="openDayModal(${day}, ${month}, ${year})" class="w-6 h-6 rounded-md bg-slate-800/80 hover:bg-gb-cyan hover:text-slate-950 text-slate-400 flex items-center justify-center text-[10px] transition-all" title="Expand Appointments for ${monthNames[month]} ${day}">
                                        <i class="fas fa-expand-alt"></i>
                                    </button>
                                </div>
                            </div>
                            <div class="flex-1 flex flex-col gap-1 overflow-y-auto max-h-[85px] pr-0.5">
                                ${eventsHTML}
                            </div>
                        </div>
                    `;
                    grid.insertAdjacentHTML('beforeend', cellHTML);
                } else {
                    const dayPosts = allPosts.filter(p => p.day === day && (p.month - 1) === month && p.year === year);
                    let postsHTML = dayPosts.map(p => {
                        const isProc = (p.status === 'processing_payload' || p.status === 'processing');
                        const calPctMatch = isProc ? String(p.status_message || '').match(/\((\d+)%/i) : null;
                        const calProcLabel = calPctMatch ? `Uploading ${calPctMatch[1]}%...` : 'Processing...';
                        return `
                        <div onmouseenter="showPostTooltip(event, '${p.id}')"
                             onmousemove="movePostTooltip(event)"
                             onmouseleave="hidePostTooltip()"
                             onclick="openDayModal(${day}, ${month}, ${year})"
                             class="flex items-center justify-between gap-1.5 ${isProc ? 'bg-amber-950/50 border-amber-400/60' : 'bg-slate-800/90 border-slate-700'} hover:bg-slate-700 border hover:border-gb-cyan rounded-lg px-2 py-1 text-[11px] cursor-pointer transition-all">
                            <div class="flex items-center gap-1.5 truncate">
                                ${getPlatformBadge(p.platform)}
                                <span class="truncate font-medium ${isProc ? 'text-amber-200' : 'text-slate-200'}">${isProc ? calProcLabel : p.time_str}</span>
                            </div>
                            <div class="flex items-center gap-1 shrink-0">
                                ${getStatusIcon(p.status)}
                            </div>
                        </div>
                    `}).join('');

                    const cellHTML = `
                        <div class="bg-slate-900/70 border ${isToday ? 'border-gb-cyan shadow-[inset_0_0_12px_rgba(0,240,255,0.2)]' : 'border-slate-700/70'} rounded-xl p-2 min-h-[115px] flex flex-col justify-between group">
                            <div class="flex items-center justify-between mb-1.5">
                                <span class="text-xs font-bold ${isToday ? 'bg-gb-cyan text-slate-950 px-2 py-0.5 rounded-full' : 'text-slate-400'}">${day}</span>
                                <div class="flex items-center gap-1.5">
                                    ${dayPosts.length > 0 ? `<span class="text-[10px] text-gb-cyan font-semibold">${dayPosts.length}</span>` : ''}
                                    <button onclick="openDayModal(${day}, ${month}, ${year})" class="w-6 h-6 rounded-md bg-slate-800/80 hover:bg-gb-cyan hover:text-slate-950 text-slate-400 flex items-center justify-center text-[10px] transition-all" title="Expand Tabular View for ${monthNames[month]} ${day}">
                                        <i class="fas fa-expand-alt"></i>
                                    </button>
                                </div>
                            </div>
                            <div class="flex-1 flex flex-col gap-1 overflow-y-auto max-h-[85px] pr-0.5">
                                ${postsHTML}
                            </div>
                        </div>
                    `;
                    grid.insertAdjacentHTML('beforeend', cellHTML);
                }
            }
        }

        // --- RENDER QUEUE (TABULAR FORMAT) ---
        function renderQueue() {
            const container = document.getElementById('queue-container');
            if (!container) return;
            const filterVal = document.getElementById('queue-filter-status').value;

            let filtered = getCombinedScheduledPosts();
            if (filterVal !== 'all') {
                if (filterVal === 'processing') {
                    filtered = filtered.filter(p => p.status === 'processing' || p.status === 'processing_payload');
                } else {
                    filtered = filtered.filter(p => p.status === filterVal);
                }
            }

            container.innerHTML = buildPostsTableHTML(filtered, "No scheduled posts in the queue.");
        }

