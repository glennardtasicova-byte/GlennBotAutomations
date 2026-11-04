        // =========================================================================
        // --- COMMENTS & NOTIFICATIONS HUB (EXTERNAL API + DELETE / CLEAR) ---
        // =========================================================================
        function getCommentUnreadCount(c) {
            const parentUnread = (c.parent_is_read !== undefined) ? (!c.parent_is_read ? 1 : 0) : (!c.is_read ? 1 : 0);
            const repliesUnread = Number(c.unread_replies_count || 0);
            return parentUnread + repliesUnread;
        }

        function updateCommentsBadges() {
            const unreadCount = commentsList.reduce((sum, c) => sum + getCommentUnreadCount(c), 0);
            const totalCount = commentsList.length;

            const navUnreadBadge = document.getElementById('comments-unread-badge');
            const navTotalBadge = document.getElementById('comments-total-badge');
            const headerPill = document.getElementById('comments-header-unread-pill');

            navTotalBadge.textContent = totalCount;

            if (unreadCount > 0) {
                navUnreadBadge.textContent = `${unreadCount} new`;
                navUnreadBadge.classList.remove('hidden');
                headerPill.textContent = `${unreadCount} Unread`;
                headerPill.classList.remove('hidden');
            } else {
                navUnreadBadge.classList.add('hidden');
                headerPill.classList.add('hidden');
            }
        }

        function getGroupedPostNotifications() {
            const platformFilter = document.getElementById('comments-filter-platform')?.value || 'all';
            const readFilter = document.getElementById('comments-filter-read')?.value || 'all';

            let baseList = commentsList;
            if (platformFilter !== 'all') {
                baseList = baseList.filter(c => c.platform === platformFilter);
            }

            const groupsMap = new Map();
            baseList.forEach(c => {
                const key = c.record_id || c.comment_id;
                const activityIso = c.latest_activity_iso || c.created_iso || '';
                if (!groupsMap.has(key)) {
                    groupsMap.set(key, {
                        record_id: key,
                        platform: c.platform,
                        auth_source: 'external_api',
                        account_name: c.account_name,
                        post_type: c.post_type,
                        post_caption: c.post_caption,
                        post_permalink: c.post_permalink,
                        latest_comment: c,
                        latest_activity_iso: activityIso,
                        comments: [],
                        unread_count: 0,
                        total_likes: 0,
                        has_own_reply: false,
                        total_replies: 0
                    });
                }
                const g = groupsMap.get(key);
                g.comments.push(c);
                if (activityIso > (g.latest_activity_iso || '')) {
                    g.latest_activity_iso = activityIso;
                    g.latest_comment = c;
                }
                g.unread_count += getCommentUnreadCount(c);
                g.total_likes += (c.like_count || 0);
                const reps = c.replies || [];
                g.total_replies += reps.length;
                if (reps.some(r => r.is_own)) g.has_own_reply = true;
            });

            let groups = Array.from(groupsMap.values());
            groups.forEach(g => {
                g.comments.sort((a, b) => (b.latest_activity_iso || b.created_iso || '').localeCompare(a.latest_activity_iso || a.created_iso || ''));
                if (g.comments.length > 0) {
                    g.latest_comment = g.comments[0];
                    g.latest_activity_iso = g.comments[0].latest_activity_iso || g.comments[0].created_iso || '';
                }
            });
            groups.sort((a, b) => (b.latest_activity_iso || '').localeCompare(a.latest_activity_iso || ''));
            if (readFilter === 'unread') {
                groups = groups.filter(g => g.unread_count > 0);
            }
            return groups;
        }

        function findTargetItemInPostComments(postComments, targetId) {
            if (!Array.isArray(postComments) || postComments.length === 0) return null;
            const cleanTarget = String(targetId || '');
            for (const c of postComments) {
                if (String(c.comment_id) === cleanTarget) {
                    return {
                        parentComment: c,
                        targetReply: null,
                        targetId: String(c.comment_id),
                        authorName: c.author_name || 'User',
                        accountName: c.account_name || ''
                    };
                }
                for (const r of (c.replies || [])) {
                    if (String(r.id) === cleanTarget) {
                        return {
                            parentComment: c,
                            targetReply: r,
                            targetId: String(r.id),
                            authorName: r.author_name || c.author_name || 'User',
                            accountName: c.account_name || ''
                        };
                    }
                }
            }
            const firstC = postComments[0];
            const preferredId = firstC.latest_comment_or_reply_id || firstC.comment_id;
            if (preferredId && String(preferredId) !== cleanTarget) {
                for (const r of (firstC.replies || [])) {
                    if (String(r.id) === String(preferredId)) {
                        return {
                            parentComment: firstC,
                            targetReply: r,
                            targetId: String(r.id),
                            authorName: r.author_name || firstC.author_name || 'User',
                            accountName: firstC.account_name || ''
                        };
                    }
                }
            }
            return {
                parentComment: firstC,
                targetReply: null,
                targetId: String(firstC.comment_id),
                authorName: firstC.author_name || 'User',
                accountName: firstC.account_name || ''
            };
        }

        // --- DELETE / CLEAR COMMENT NOTIFICATIONS FUNCTIONS ---
        async function deletePostNotificationCard(recordId, event) {
            if (event) event.stopPropagation();
            const postComms = commentsList.filter(c => c.record_id === recordId);
            const cids = postComms.map(c => c.comment_id);

            commentsList = commentsList.filter(c => c.record_id !== recordId);
            if (selectedRecordId === recordId) {
                selectedRecordId = null;
                selectedCommentId = null;
                resetCommentDetailPanel();
            }
            updateCommentsBadges();
            renderCommentsList();
            showToast("🗑️ Notification removed from Cloudinary (Comment history preserved for future comments)!");

            try {
                await fetch('/api/comments/dismiss', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ record_id: recordId, comment_ids: cids, clear_all: false, single_comment: false })
                });
            } catch (e) {
                console.error("Delete notification error:", e);
            }
        }

        async function deleteSingleCommentNotification(recordId, commentId, event) {
            if (event) event.stopPropagation();
            commentsList = commentsList.filter(c => c.comment_id !== commentId);
            const remainingForPost = commentsList.filter(c => c.record_id === recordId);
            if (remainingForPost.length === 0) {
                if (selectedRecordId === recordId) {
                    selectedRecordId = null;
                    selectedCommentId = null;
                    resetCommentDetailPanel();
                }
            } else {
                if (selectedCommentId === commentId) {
                    selectedCommentId = remainingForPost[0].comment_id;
                }
                syncOpenPostThreadLive(recordId);
            }
            updateCommentsBadges();
            renderCommentsList();
            showToast("🗑️ Comment removed from Cloudinary!");

            try {
                await fetch('/api/comments/dismiss', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ record_id: recordId, comment_ids: [commentId], clear_all: false, single_comment: true })
                });
            } catch (e) {
                console.error("Delete single comment error:", e);
            }
        }

        async function clearAllCommentNotifications() {
            if (commentsList.length === 0) {
                return showToast("✨ Your Comment Notifications are already clean!");
            }
            if (!confirm(`Clear all ${commentsList.length} notification(s) from your tab?\n\n(They will be hidden from the Notification tab and saved to Cloudinary, and will only reappear when a new comment arrives—with the full comment history intact!)`)) return;

            const allCids = commentsList.map(c => c.comment_id);
            commentsList = [];
            selectedRecordId = null;
            selectedCommentId = null;
            updateCommentsBadges();
            renderCommentsList();
            resetCommentDetailPanel();
            showToast("🧹 All comment notifications cleared!");

            try {
                await fetch('/api/comments/dismiss', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ comment_ids: allCids, clear_all: true, single_comment: false })
                });
            } catch (e) {
                console.error("Clear all notifications error:", e);
            }
        }

        async function fetchComments(showFeedback = false) {
            if (!showFeedback && window._gbInFlightPolls && window._gbInFlightPolls.comments) {
                return;
            }
            if (window._gbInFlightPolls) window._gbInFlightPolls.comments = true;

            const syncIcon = document.getElementById('sync-comments-icon');
            if (syncIcon && showFeedback) syncIcon.classList.add('fa-spin');

            try {
                const activeParam = selectedRecordId ? `active_record_id=${encodeURIComponent(selectedRecordId)}` : '';
                const url = showFeedback
                    ? `/api/comments?force=true${activeParam ? '&' + activeParam : ''}`
                    : `/api/comments${activeParam ? '?' + activeParam : ''}`;
                let res = await _gbFetchWithTimeout(url, {}, showFeedback ? 20000 : 8000);
                let data = await res.json();
                if (data.status === 'success') {
                    const incoming = data.comments || [];

                    incoming.forEach(c => {
                        const pendingList = pendingOptimisticReplies[c.comment_id] || [];
                        if (pendingList.length > 0) {
                            c.replies = c.replies || [];
                            pendingList.forEach(optRep => {
                                const exists = c.replies.some(r =>
                                    r.id === optRep.id || (r.is_own && (r.message || '').trim() === (optRep.message || '').trim())
                                );
                                if (!exists) {
                                    c.replies.push(optRep);
                                }
                            });
                        }
                    });

                    let newlyArrived = [];
                    incoming.forEach(c => {
                        if (!knownCommentIds.has(c.comment_id)) {
                            knownCommentIds.add(c.comment_id);
                            if (!isInitialCommentsLoad && !c.parent_is_read && !c.is_own_comment) {
                                newlyArrived.push({
                                    kind: 'comment',
                                    platform: c.platform,
                                    author_name: c.author_name,
                                    account_name: c.account_name || '',
                                    record_id: c.record_id || '',
                                    comment_id: c.comment_id || '',
                                    message: c.message
                                });
                            }
                        }
                        (c.replies || []).forEach(rep => {
                            if (!rep.id) return;
                            if (!knownReplyIds.has(rep.id)) {
                                knownReplyIds.add(rep.id);
                                if (!isInitialCommentsLoad && !rep.is_own && !rep.is_read) {
                                    newlyArrived.push({
                                        kind: 'reply',
                                        platform: c.platform,
                                        author_name: rep.author_name,
                                        account_name: c.account_name || '',
                                        record_id: c.record_id || '',
                                        comment_id: c.comment_id || '',
                                        message: rep.message
                                    });
                                }
                            }
                        });
                    });
                    isInitialCommentsLoad = false;

                    commentsList = incoming;
                    updateCommentsBadges();
                    renderCommentsList();

                    const warnBanner = document.getElementById('comments-warning-banner');
                    const warnText = document.getElementById('comments-warning-text');
                    if (data.permissions_warnings && data.permissions_warnings.length > 0) {
                        warnText.textContent = data.permissions_warnings.join(' | ');
                        warnBanner.classList.remove('hidden');
                    } else {
                        warnBanner.classList.add('hidden');
                    }

                    if (selectedRecordId) {
                        const postStillHasComments = commentsList.some(c => c.record_id === selectedRecordId);
                        if (postStillHasComments) {
                            syncOpenPostThreadLive(selectedRecordId);
                        } else {
                            selectedRecordId = null;
                            selectedCommentId = null;
                            resetCommentDetailPanel();
                        }
                    }

                    if (showFeedback) {
                        showToast(`🔔 Synced ${commentsList.length} comment thread(s)!`);
                    } else if (newlyArrived.length > 0) {
                        const latestNew = newlyArrived[0];
                        const actionWord = latestNew.kind === 'reply' ? 'reply' : 'comment';
                        const burstSuffix = newlyArrived.length > 1 ? ` (+${newlyArrived.length - 1} more simultaneous)` : '';
                        triggerIncomingActivityAlert({
                            type: 'comment',
                            platform: latestNew.platform || 'facebook',
                            author: latestNew.author_name || 'Someone',
                            accountName: latestNew.account_name || '',
                            text: `${latestNew.message || ''}${burstSuffix}`,
                            recordId: latestNew.record_id || '',
                            commentId: latestNew.comment_id || '',
                            kind: latestNew.kind || 'comment',
                            fallbackText: `🔔 New ${(latestNew.platform || '').toUpperCase()} ${actionWord} from ${latestNew.author_name}: "${(latestNew.message || '').slice(0, 45)}"${burstSuffix}`
                        });
                    }
                }
            } catch (e) {
                if (e && e.name !== 'AbortError') {
                    console.error("Error fetching comments:", e);
                }
            } finally {
                if (window._gbInFlightPolls) window._gbInFlightPolls.comments = false;
                if (syncIcon) syncIcon.classList.remove('fa-spin');
            }
        }

        function renderCommentsList() {
            const container = document.getElementById('comments-list-container');
            const counterEl = document.getElementById('comments-list-counter');
            if (!container) return;

            const groups = getGroupedPostNotifications();
            const totalFilteredComments = groups.reduce((acc, g) => acc + g.comments.length, 0);

            if (counterEl) {
                counterEl.textContent = `${groups.length} post${groups.length === 1 ? '' : 's'} • ${totalFilteredComments} comment${totalFilteredComments === 1 ? '' : 's'}`;
            }

            if (groups.length === 0) {
                container.innerHTML = `
                    <div class="flex flex-col items-center justify-center py-12 px-4 text-center text-slate-500">
                        <i class="fas fa-comment-slash text-3xl mb-2.5 opacity-60"></i>
                        <p class="text-xs sm:text-sm font-medium text-slate-400">No comment notifications found.</p>
                        <p class="text-[11px] mt-1 text-slate-500">External API Sync is active. When someone comments on your published posts, their message will appear here automatically.</p>
                    </div>
                `;
                return;
            }

            container.innerHTML = groups.map(g => {
                const c = g.latest_comment;
                const latestRep = c.latest_commenter_reply;
                const showCommenterReply = Boolean(
                    latestRep && (c.has_unread_reply || (latestRep.created_iso || '') > (c.created_iso || ''))
                );
                const displayAuthor = showCommenterReply ? (latestRep.author_name || c.author_name) : c.author_name;
                const displayAvatar = showCommenterReply ? (latestRep.author_avatar || c.author_avatar) : c.author_avatar;
                const displayTime = showCommenterReply ? (latestRep.display_time || c.display_time) : c.display_time;
                const displayMessage = showCommenterReply ? (latestRep.message || c.message) : c.message;

                const totalCommentsOnPost = g.comments.length;
                const othersCount = totalCommentsOnPost - 1;
                const isSelected = (g.record_id === selectedRecordId);
                const hasUnread = g.unread_count > 0;

                const unreadIndicator = hasUnread
                    ? `<span class="inline-flex items-center gap-1"><span class="px-1.5 py-0.5 rounded-full bg-rose-500 text-white text-[10px] font-bold shadow-[0_0_8px_#f43f5e]">${g.unread_count} new</span></span>`
                    : `<span class="w-2 h-2 rounded-full bg-slate-700 shrink-0" title="All Read"></span>`;

                const avatarHTML = displayAvatar
                    ? `<img src="${displayAvatar}" class="w-9 h-9 rounded-full object-cover border border-slate-600 shrink-0" onerror="this.outerHTML='<div class=\\'w-9 h-9 rounded-full bg-slate-800 border border-slate-600 flex items-center justify-center text-xs font-bold text-gb-cyan shrink-0\\'><i class=\\'fas fa-user\\'></i></div>'">`
                    : `<div class="w-9 h-9 rounded-full bg-slate-800 border border-slate-600 flex items-center justify-center text-xs font-bold text-gb-cyan shrink-0"><i class="fas fa-user"></i></div>`;

                const actionVerbHTML = showCommenterReply
                    ? `<span class="text-rose-300 font-semibold">replied to a comment</span> on`
                    : `commented on`;

                const sourcePillHTML = `<span class="px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-300 border border-purple-500/30 text-[9px] font-semibold">External API</span>`;

                const summarySentenceHTML = othersCount > 0
                    ? `<span class="font-bold text-white">${escapeHTML(displayAuthor)}</span> <span class="text-slate-300 font-medium">and ${othersCount} other${othersCount === 1 ? '' : 's'}</span> ${actionVerbHTML} <span class="text-gb-cyan font-semibold">"${escapeHTML(g.account_name)}"</span> • <span class="text-slate-300">${formatPostTypeLabel(g.post_type)}</span>`
                    : `<span class="font-bold text-white">${escapeHTML(displayAuthor)}</span> ${actionVerbHTML} <span class="text-gb-cyan font-semibold">"${escapeHTML(g.account_name)}"</span> • <span class="text-slate-300">${formatPostTypeLabel(g.post_type)}</span>`;

                return `
                    <div onclick="selectPostCommentNotification('${g.record_id}')"
                         class="p-3 rounded-xl border transition-all cursor-pointer ${isSelected ? 'bg-gb-cyan/15 border-gb-cyan shadow-[0_0_15px_rgba(0,240,255,0.2)]' : (hasUnread ? 'bg-slate-800/95 border-rose-500/40 hover:border-gb-cyan/60' : 'bg-slate-800/50 border-slate-700/70 hover:bg-slate-800/90 hover:border-slate-600')}">
                        <div class="flex items-start gap-2.5">
                            <div class="relative shrink-0">
                                ${avatarHTML}
                                <span class="absolute -bottom-1 -right-1">${getPlatformBadge(g.platform)}</span>
                            </div>
                            <div class="min-w-0 flex-1">
                                <div class="flex items-start justify-between gap-2">
                                    <p class="text-xs text-slate-300 leading-snug">
                                        ${summarySentenceHTML}
                                    </p>
                                    <div class="flex items-center gap-1.5 shrink-0">
                                        <span class="text-[10px] text-slate-400">${displayTime}</span>
                                        ${unreadIndicator}
                                        <!-- DELETE NOTIFICATION CARD BUTTON -->
                                        <button type="button" onclick="deletePostNotificationCard('${g.record_id}', event)"
                                            class="w-6 h-6 rounded-lg bg-slate-900/90 hover:bg-rose-600 border border-slate-700 hover:border-rose-400 text-slate-400 hover:text-white flex items-center justify-center text-[10px] transition-all ml-1"
                                            title="Delete this notification">
                                            <i class="fas fa-trash-alt"></i>
                                        </button>
                                    </div>
                                </div>
                                <div class="mt-2 p-2 rounded-lg bg-slate-950/70 border ${showCommenterReply && c.has_unread_reply ? 'border-rose-500/40' : 'border-slate-800'} text-xs text-slate-200">
                                    <p class="line-clamp-2">${showCommenterReply
                                        ? `<span class="text-rose-400 font-semibold"><i class="fas fa-reply mr-1"></i>${escapeHTML(displayAuthor)}:</span> `
                                        : (othersCount > 0 ? `<span class="text-gb-cyan font-semibold">${escapeHTML(displayAuthor)}:</span> ` : '')
                                    }"${escapeHTML((displayMessage || '').trim())}"</p>
                                </div>
                                <div class="mt-2 flex items-center justify-between gap-2 text-[10px]">
                                    <div class="flex items-center gap-1.5 flex-wrap">
                                        ${sourcePillHTML}
                                        <span class="px-2 py-0.5 rounded bg-gb-cyan/15 text-gb-cyan border border-gb-cyan/30 font-semibold">
                                            <i class="fas fa-comments mr-1"></i>${totalCommentsOnPost} comment${totalCommentsOnPost === 1 ? '' : 's'}
                                        </span>
                                        ${g.has_own_reply
                                            ? `<span class="px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-semibold"><i class="fas fa-check mr-1"></i>Replied (${g.total_replies})</span>`
                                            : (g.total_replies > 0
                                                ? `<span class="px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700"><i class="fas fa-reply mr-1"></i>${g.total_replies} repl${g.total_replies === 1 ? 'y' : 'ies'}</span>`
                                                : `<span class="text-slate-500"><i class="far fa-comment-dots mr-1"></i>Click to view & manage</span>`)}
                                    </div>
                                    ${g.total_likes > 0 ? `<span class="text-rose-400 shrink-0 font-semibold"><i class="fas fa-heart mr-1"></i>${g.total_likes}</span>` : ''}
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function selectPostCommentNotification(recordId) {
            selectedRecordId = recordId;
            const postComments = commentsList.filter(c => c.record_id === recordId);
            if (postComments.length === 0) return;

            postComments.sort((a, b) => (b.latest_activity_iso || b.created_iso || '').localeCompare(a.latest_activity_iso || a.created_iso || ''));
            const topLatest = postComments[0];
            selectedCommentId = topLatest.latest_comment_or_reply_id || topLatest.comment_id;

            const idsToMarkRead = [];
            postComments.forEach(c => {
                if (!c.parent_is_read || !c.is_read) {
                    idsToMarkRead.push(c.comment_id);
                }
                if (Array.isArray(c.unread_reply_ids) && c.unread_reply_ids.length > 0) {
                    idsToMarkRead.push(...c.unread_reply_ids);
                }
                c.is_read = true;
                c.parent_is_read = true;
                c.has_unread_reply = false;
                c.unread_replies_count = 0;
                c.unread_reply_ids = [];
                (c.replies || []).forEach(r => { r.is_read = true; });
            });

            if (idsToMarkRead.length > 0) {
                updateCommentsBadges();
                renderCommentsList();
                fetch('/api/comments/mark_read', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        comment_ids: idsToMarkRead,
                        record_id: recordId,
                        platform: postComments[0].platform
                    })
                }).catch(() => {});
            } else {
                renderCommentsList();
            }

            await renderSelectedCommentDetail(recordId, true);
        }

        function selectActiveReplyComment(recordId, commentId) {
            selectedRecordId = recordId;
            selectedCommentId = commentId;
            const panel = document.getElementById('comment-detail-panel');
            if (panel && panel.dataset.recordId === String(recordId) && document.getElementById('post-comments-thread-list')) {
                syncOpenPostThreadLive(recordId);
            } else {
                renderSelectedCommentDetail(recordId, false);
            }
            setTimeout(() => {
                const input = document.getElementById('comment-reply-input');
                if (input) input.focus();
            }, 30);
        }

        function resetCommentDetailPanel() {
            const panel = document.getElementById('comment-detail-panel');
            if (!panel) return;
            delete panel.dataset.recordId;
            panel.innerHTML = `
                <div class="flex flex-col items-center justify-center h-full py-16 px-6 text-center text-slate-500">
                    <div class="w-16 h-16 rounded-2xl bg-slate-800/80 border border-slate-700 flex items-center justify-center mb-3 text-gb-cyan">
                        <i class="fas fa-comments text-2xl"></i>
                    </div>
                    <h4 class="text-sm font-semibold text-slate-300">Select a Comment Notification on the Left</h4>
                    <p class="text-xs text-slate-500 max-w-sm mt-1">
                        Click any post notification to play the video or view the photo right here, read all comments on that post, and send a direct reply without leaving GlennBot.
                    </p>
                </div>
            `;
        }

        function buildPostCommentsThreadHTML(recordId, postComments, activeCommentId) {
            return postComments.map(c => {
                const repliesList = c.replies || [];
                const hasReplies = repliesList.length > 0;
                const isParentTargetForReply = (!hasReplies && String(c.comment_id) === String(activeCommentId));
                const platLower = (c.platform || '').toLowerCase();
                const canSendDm = (platLower === 'facebook' || platLower === 'instagram');
                const canLikeComment = (platLower === 'facebook');
                const canHideComment = (platLower === 'facebook' || platLower === 'instagram' || platLower === 'tiktok');

                const repliesHTML = hasReplies
                    ? repliesList.map(rep => {
                        const isReplyTarget = (String(rep.id) === String(activeCommentId));
                        const repLikeBtn = (!rep.is_own && canLikeComment)
                            ? `<button type="button" id="btn-like-comment-${rep.id}" onclick="toggleLikeComment('${recordId}', '${rep.id}', event)"
                                    class="px-2.5 py-1 rounded-lg text-[10px] font-semibold transition-all inline-flex items-center gap-1.5 ${rep.is_liked ? 'bg-blue-600 text-white border border-blue-400 shadow-[0_0_8px_rgba(37,99,235,0.4)]' : 'bg-slate-900/90 hover:bg-blue-500/25 border border-slate-700 hover:border-blue-400/50 text-slate-300 hover:text-blue-200'}"
                                    title="${rep.is_liked ? 'Unlike this reply on Facebook' : 'Like this reply on Facebook'}">
                                    <i class="${rep.is_liked ? 'fas' : 'far'} fa-thumbs-up text-[9px]"></i> <span>${rep.is_liked ? 'Liked' : 'Like'}</span>
                               </button>`
                            : '';
                        const repHideBtn = (!rep.is_own && canHideComment)
                            ? `<button type="button" id="btn-hide-comment-${rep.id}" onclick="toggleHideComment('${recordId}', '${rep.id}', event)"
                                    class="px-2.5 py-1 rounded-lg text-[10px] font-semibold transition-all inline-flex items-center gap-1.5 ${rep.is_hidden ? 'bg-amber-500/30 hover:bg-amber-500/45 border border-amber-400 text-amber-200' : 'bg-slate-900/90 hover:bg-amber-500/25 border border-slate-700 hover:border-amber-400/50 text-slate-300 hover:text-amber-200'}"
                                    title="${rep.is_hidden ? 'Unhide this reply on the actual ' + platLower.toUpperCase() + ' post' : 'Hide this reply on the actual ' + platLower.toUpperCase() + ' post'}">
                                    <i class="fas ${rep.is_hidden ? 'fa-eye' : 'fa-eye-slash'} text-[9px]"></i> <span>${rep.is_hidden ? 'Unhide' : 'Hide'}</span>
                               </button>`
                            : '';
                        const repSendDmBtn = (!rep.is_own && canSendDm)
                            ? `<button type="button" onclick="openCommentDmModal('${recordId}', '${rep.id}', event)"
                                    class="px-2.5 py-1 rounded-lg text-[10px] font-semibold transition-all inline-flex items-center gap-1.5 bg-slate-900/90 hover:bg-indigo-500/30 border border-slate-700 hover:border-indigo-400/50 text-indigo-300 hover:text-white"
                                    title="Send a Direct Message (Private Reply) to ${escapeHTML(rep.author_name)}">
                                    <i class="fas fa-paper-plane text-[9px]"></i> <span>Send a DM</span>
                               </button>`
                            : '';
                        const repSavedContact = !rep.is_own ? findExistingCrmContact(rep.author_name, platLower) : null;
                        const repAddContactBtn = !rep.is_own
                            ? `<button type="button" onclick="openAddToContactsFromComment('${recordId}', '${rep.id}', event)"
                                    class="px-2.5 py-1 rounded-lg text-[10px] font-semibold transition-all inline-flex items-center gap-1.5 ${repSavedContact ? 'bg-emerald-500/20 hover:bg-emerald-500/35 border border-emerald-400/60 text-emerald-300' : 'bg-slate-900/90 hover:bg-emerald-500/25 border border-slate-700 hover:border-emerald-400/55 text-emerald-300 hover:text-white'}"
                                    title="${repSavedContact ? 'Already in Contacts — Click to View/Edit' : 'Add ' + escapeHTML(rep.author_name) + ' to CRM Contacts'}">
                                    <i class="fas ${repSavedContact ? 'fa-user-check' : 'fa-user-plus'} text-[9px]"></i> <span>${repSavedContact ? 'In Contacts' : 'Add to Contacts'}</span>
                               </button>`
                            : '';
                        return `
                        <div onclick="selectActiveReplyComment('${recordId}', '${rep.id}'); event.stopPropagation();"
                             class="ml-6 mt-2 p-2.5 rounded-xl border transition-all cursor-pointer ${rep.pending ? 'bg-amber-500/10 border-amber-400/50 animate-pulse' : (isReplyTarget ? 'bg-slate-800/95 border-gb-cyan shadow-[0_0_12px_rgba(0,240,255,0.2)]' : (rep.is_own ? 'bg-gb-cyan/10 border-gb-cyan/40 hover:border-gb-cyan' : (rep.is_read === false ? 'bg-rose-500/10 border-rose-500/50 hover:border-gb-cyan' : 'bg-slate-800/70 border-slate-700 hover:border-slate-500')))} ${rep.is_hidden ? 'opacity-75 border-dashed border-amber-500/50' : ''}">
                            <div class="flex items-center justify-between gap-2 mb-1.5">
                                <div class="flex items-center gap-1.5 flex-wrap min-w-0">
                                    <span class="text-xs font-bold ${rep.is_own ? 'text-gb-cyan' : 'text-white'}">${escapeHTML(rep.author_name)}</span>
                                    ${rep.pending
                                        ? `<span class="text-[9px] uppercase px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40 font-bold"><i class="fas fa-circle-notch fa-spin mr-1"></i>Sending...</span>`
                                        : (rep.is_own
                                            ? `<span class="text-[9px] uppercase px-1.5 py-0.5 rounded bg-gb-cyan/20 text-gb-cyan font-bold"><i class="fas fa-check mr-1"></i>Page Reply</span>`
                                            : (rep.is_read === false
                                                ? `<span class="text-[9px] uppercase px-1.5 py-0.5 rounded bg-rose-500 text-white font-bold">New Reply</span>`
                                                : ''))
                                    }
                                    ${rep.is_hidden ? `<span class="text-[9px] uppercase px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-400/40 font-bold"><i class="fas fa-eye-slash mr-1"></i>Hidden on Page</span>` : ''}
                                    ${rep.dm_sent ? `<span class="text-[9px] uppercase px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-400/40 font-bold"><i class="fas fa-check mr-1"></i>DM Sent</span>` : ''}
                                    ${isReplyTarget ? `<span class="text-[9px] uppercase px-1.5 py-0.5 rounded bg-gb-cyan/20 text-gb-cyan border border-gb-cyan/40 font-bold">Replying</span>` : ''}
                                </div>
                                <span class="text-[10px] text-slate-400 shrink-0">${rep.display_time}</span>
                            </div>
                            <p class="text-xs text-slate-200 bg-slate-950/60 p-2 rounded-lg border border-slate-800/80 whitespace-pre-wrap">${escapeHTML(rep.message)}</p>
                            <div class="flex items-center gap-1.5 flex-wrap mt-2 pt-1.5 border-t border-slate-700/50">
                                <button type="button" onclick="selectActiveReplyComment('${recordId}', '${rep.id}'); event.stopPropagation();"
                                    class="px-2.5 py-1 rounded-lg text-[10px] font-semibold transition-all inline-flex items-center gap-1.5 ${isReplyTarget ? 'bg-gb-cyan text-slate-950 font-bold' : 'bg-slate-900/90 hover:bg-gb-cyan/20 border border-slate-700 text-slate-200 hover:text-gb-cyan'}">
                                    <i class="fas fa-reply text-[9px]"></i> <span>Reply</span>
                                </button>
                                ${repLikeBtn}
                                ${repHideBtn}
                                ${repSendDmBtn}
                                ${repAddContactBtn}
                            </div>
                        </div>
                    `}).join('')
                    : '';

                const parentReplyButtonHTML = `<button type="button" onclick="selectActiveReplyComment('${recordId}', '${c.comment_id}'); event.stopPropagation();"
                        class="px-3 py-1 rounded-lg text-[11px] font-semibold transition-all inline-flex items-center gap-1.5 ${isParentTargetForReply ? 'bg-gb-cyan text-slate-950 font-bold shadow-[0_0_10px_rgba(0,240,255,0.3)]' : 'bg-slate-900/90 hover:bg-gb-cyan/20 border border-slate-700 hover:border-gb-cyan/50 text-slate-200 hover:text-gb-cyan'}"
                        title="Reply to ${escapeHTML(c.author_name)}">
                        <i class="fas fa-reply text-[10px]"></i> <span>Reply</span>
                   </button>`;

                const parentLikeButtonHTML = canLikeComment
                    ? `<button type="button" id="btn-like-comment-${c.comment_id}" onclick="toggleLikeComment('${recordId}', '${c.comment_id}', event)"
                            class="px-3 py-1 rounded-lg text-[11px] font-semibold transition-all inline-flex items-center gap-1.5 ${c.is_liked ? 'bg-blue-600 text-white border border-blue-400 shadow-[0_0_10px_rgba(37,99,235,0.45)]' : 'bg-slate-900/90 hover:bg-blue-500/25 border border-slate-700 hover:border-blue-400/50 text-slate-300 hover:text-blue-200'}"
                            title="${c.is_liked ? 'Unlike this comment on Facebook' : 'Like this comment on Facebook'}">
                            <i class="${c.is_liked ? 'fas' : 'far'} fa-thumbs-up text-[10px]"></i> <span>${c.is_liked ? 'Liked' : 'Like'}</span>
                       </button>`
                    : '';

                const parentHideButtonHTML = canHideComment
                    ? `<button type="button" id="btn-hide-comment-${c.comment_id}" onclick="toggleHideComment('${recordId}', '${c.comment_id}', event)"
                            class="px-3 py-1 rounded-lg text-[11px] font-semibold transition-all inline-flex items-center gap-1.5 ${c.is_hidden ? 'bg-amber-500/30 hover:bg-amber-500/45 border border-amber-400 text-amber-200 shadow-[0_0_10px_rgba(245,158,11,0.25)]' : 'bg-slate-900/90 hover:bg-amber-500/25 border border-slate-700 hover:border-amber-400/50 text-slate-300 hover:text-amber-200'}"
                            title="${c.is_hidden ? 'Unhide this comment on the actual ' + platLower.toUpperCase() + ' post' : 'Hide this comment on the actual ' + platLower.toUpperCase() + ' post'}">
                            <i class="fas ${c.is_hidden ? 'fa-eye' : 'fa-eye-slash'} text-[10px]"></i> <span>${c.is_hidden ? 'Unhide' : 'Hide'}</span>
                       </button>`
                    : '';

                const parentSendDmButtonHTML = canSendDm
                    ? `<button type="button" onclick="openCommentDmModal('${recordId}', '${c.comment_id}', event)"
                            class="px-3 py-1 rounded-lg text-[11px] font-semibold transition-all inline-flex items-center gap-1.5 bg-slate-900/90 hover:bg-indigo-500/30 border border-slate-700 hover:border-indigo-400/55 text-indigo-300 hover:text-white"
                            title="Send a Direct Message (Private Reply) to ${escapeHTML(c.author_name)}">
                            <i class="fas fa-paper-plane text-[10px]"></i> <span>Send a DM</span>
                       </button>`
                    : '';

                const parentSavedContact = findExistingCrmContact(c.author_name, platLower);
                const parentAddContactButtonHTML = `<button type="button" onclick="openAddToContactsFromComment('${recordId}', '${c.comment_id}', event)"
                        class="px-3 py-1 rounded-lg text-[11px] font-semibold transition-all inline-flex items-center gap-1.5 ${parentSavedContact ? 'bg-emerald-500/20 hover:bg-emerald-500/35 border border-emerald-400/60 text-emerald-300' : 'bg-slate-900/90 hover:bg-emerald-500/25 border border-slate-700 hover:border-emerald-400/55 text-emerald-300 hover:text-white'}"
                        title="${parentSavedContact ? 'Already in Contacts — Click to View/Edit' : 'Add ' + escapeHTML(c.author_name) + ' to CRM Contacts'}">
                        <i class="fas ${parentSavedContact ? 'fa-user-check' : 'fa-user-plus'} text-[10px]"></i> <span>${parentSavedContact ? 'In Contacts' : 'Add to Contacts'}</span>
                   </button>`;

                return `
                    <div class="space-y-1">
                        <div ${!hasReplies ? `onclick="selectActiveReplyComment('${recordId}', '${c.comment_id}')"` : ''}
                             class="p-3 rounded-xl border transition-all ${!hasReplies ? 'cursor-pointer' : ''} ${isParentTargetForReply ? 'bg-slate-800/95 border-gb-cyan shadow-[0_0_12px_rgba(0,240,255,0.15)]' : 'bg-slate-800/60 border-slate-700 hover:border-slate-500'} ${c.is_hidden ? 'opacity-75 border-dashed border-amber-500/50' : ''}">
                            <!-- TOP ROW: AUTHOR INFO & TIMESTAMP ON LEFT, EXTERNAL LINK & DELETE ICON ON RIGHT -->
                            <div class="flex items-start justify-between gap-3 mb-2">
                                <div class="flex items-center gap-2.5 min-w-0">
                                    ${c.author_avatar
                                        ? `<img src="${c.author_avatar}" class="w-8 h-8 rounded-full object-cover border border-gb-cyan/50 shrink-0" onerror="this.outerHTML='<span class=\\'w-8 h-8 rounded-full bg-gb-cyan/20 border border-gb-cyan/50 flex items-center justify-center text-gb-cyan text-xs font-bold shrink-0\\'><i class=\\'fas fa-user\\'></i></span>'">`
                                        : `<span class="w-8 h-8 rounded-full bg-gb-cyan/20 border border-gb-cyan/50 flex items-center justify-center text-gb-cyan text-xs font-bold shrink-0"><i class="fas fa-user"></i></span>`
                                    }
                                    <div class="min-w-0">
                                        <div class="flex items-center gap-1.5 flex-wrap">
                                            <span class="text-xs sm:text-sm font-bold text-white leading-tight">${escapeHTML(c.author_name)}</span>
                                            ${c.is_hidden ? `<span class="text-[9px] uppercase px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-400/40 font-bold"><i class="fas fa-eye-slash mr-1"></i>Hidden on Page</span>` : ''}
                                            ${c.dm_sent ? `<span class="text-[9px] uppercase px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-400/40 font-bold"><i class="fas fa-check mr-1"></i>DM Sent</span>` : ''}
                                            ${isParentTargetForReply ? `<span class="text-[9px] uppercase px-1.5 py-0.5 rounded bg-gb-cyan/20 text-gb-cyan border border-gb-cyan/40 font-bold">Replying</span>` : ''}
                                        </div>
                                        <span class="text-[10px] text-slate-400 block mt-0.5">${c.display_time}</span>
                                    </div>
                                </div>
                                <div class="flex items-center gap-1.5 shrink-0">
                                    ${c.comment_permalink ? `
                                        <a href="${c.comment_permalink}" target="_blank" onclick="event.stopPropagation();" class="w-7 h-7 rounded-lg bg-slate-900/90 hover:bg-gb-cyan/20 border border-slate-700 hover:border-gb-cyan/60 text-slate-300 hover:text-gb-cyan flex items-center justify-center text-[11px] transition-all" title="View exact comment on ${c.platform}">
                                            <i class="fas fa-external-link-alt"></i>
                                        </a>
                                    ` : ''}
                                    <button type="button" onclick="deleteSingleCommentNotification('${recordId}', '${c.comment_id}', event)"
                                        class="w-7 h-7 rounded-lg bg-slate-900/90 hover:bg-rose-600 border border-slate-700 hover:border-rose-400 text-slate-400 hover:text-white flex items-center justify-center text-[11px] transition-all"
                                        title="Delete this comment notification">
                                        <i class="fas fa-trash-alt"></i>
                                    </button>
                                </div>
                            </div>

                            <!-- MIDDLE: COMMENT MESSAGE BUBBLE -->
                            <p class="text-xs sm:text-sm text-white bg-slate-950/80 p-2.5 rounded-lg border border-slate-800 whitespace-pre-wrap">${escapeHTML(c.message)}</p>

                            <!-- BOTTOM: DEDICATED SOCIAL ACTION BAR -->
                            <div class="flex items-center gap-2 flex-wrap mt-2.5 pt-2 border-t border-slate-700/60">
                                ${parentReplyButtonHTML}
                                ${parentLikeButtonHTML}
                                ${parentHideButtonHTML}
                                ${parentSendDmButtonHTML}
                                ${parentAddContactButtonHTML}
                            </div>
                        </div>
                        ${repliesHTML}
                    </div>
                `;
            }).join('');
        }

        function syncOpenPostThreadLive(recordId) {
            const panel = document.getElementById('comment-detail-panel');
            const threadContainer = document.getElementById('post-comments-thread-list');
            if (!panel || panel.dataset.recordId !== String(recordId) || !threadContainer) {
                renderSelectedCommentDetail(recordId, false);
                return;
            }

            const postComments = commentsList.filter(c => c.record_id === recordId);
            if (postComments.length === 0) return;
            postComments.sort((a, b) => (b.latest_activity_iso || b.created_iso || '').localeCompare(a.latest_activity_iso || a.created_iso || ''));

            const targetMatch = findTargetItemInPostComments(postComments, selectedCommentId);
            const activeComment = targetMatch ? targetMatch.parentComment : postComments[0];
            const activeTargetId = targetMatch ? targetMatch.targetId : activeComment.comment_id;
            const activeTargetAuthor = targetMatch ? targetMatch.authorName : activeComment.author_name;
            selectedCommentId = activeTargetId;

            const prevScrollTop = threadContainer.scrollTop;
            threadContainer.innerHTML = buildPostCommentsThreadHTML(recordId, postComments, activeTargetId);
            threadContainer.scrollTop = prevScrollTop;

            const countEl = document.getElementById('post-comments-count-label');
            if (countEl) {
                countEl.innerHTML = `<i class="fas fa-comments mr-1"></i> Comments on This Post (${postComments.length})`;
            }

            const replyLabelEl = document.getElementById('reply-target-label');
            if (replyLabelEl) {
                replyLabelEl.innerHTML = `Reply to <span class="text-gb-cyan">${escapeHTML(activeTargetAuthor)}</span> as <span class="text-gb-cyan">${escapeHTML(activeComment.account_name)}</span>`;
            }

            const replyInput = document.getElementById('comment-reply-input');
            if (replyInput) {
                replyInput.placeholder = `Type your reply to ${activeTargetAuthor}... (Press Enter to send or click Send Reply)`;
            }

            const sendBtn = document.getElementById('btn-send-reply');
            if (sendBtn) {
                sendBtn.setAttribute('onclick', `sendCommentReply('${activeComment.record_id}', '${activeTargetId}')`);
            }

            const sendDmBottomBtn = document.getElementById('btn-send-dm-from-composer');
            if (sendDmBottomBtn) {
                sendDmBottomBtn.setAttribute('onclick', `openCommentDmModal('${activeComment.record_id}', '${activeTargetId}', event)`);
            }
        }

        async function markAllCommentsRead() {
            const unreadIds = [];
            commentsList.forEach(c => {
                if (!c.parent_is_read || !c.is_read) unreadIds.push(c.comment_id);
                if (Array.isArray(c.unread_reply_ids)) unreadIds.push(...c.unread_reply_ids);
            });
            if (unreadIds.length === 0) {
                return showToast("✅ All comments and replies are already marked as read.");
            }
            commentsList.forEach(c => {
                c.is_read = true;
                c.parent_is_read = true;
                c.has_unread_reply = false;
                c.unread_replies_count = 0;
                c.unread_reply_ids = [];
                (c.replies || []).forEach(r => { r.is_read = true; });
            });
            updateCommentsBadges();
            renderCommentsList();

            try {
                await fetch('/api/comments/mark_read', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ comment_ids: unreadIds })
                });
                showToast(`✅ Marked ${unreadIds.length} notification(s) as read!`);
            } catch (e) {
                console.error("Mark all read error:", e);
            }
        }

        async function renderSelectedCommentDetail(recordIdOrCommentObj, fetchFreshMedia = false) {
            const panel = document.getElementById('comment-detail-panel');
            if (!panel) return;

            const recordId = typeof recordIdOrCommentObj === 'string'
                ? recordIdOrCommentObj
                : (recordIdOrCommentObj?.record_id || selectedRecordId);

            const postComments = commentsList.filter(c => c.record_id === recordId);
            if (postComments.length === 0) return;
            postComments.sort((a, b) => (b.latest_activity_iso || b.created_iso || '').localeCompare(a.latest_activity_iso || a.created_iso || ''));

            const targetMatch = findTargetItemInPostComments(postComments, selectedCommentId);
            const activeComment = targetMatch ? targetMatch.parentComment : postComments[0];
            const activeTargetId = targetMatch ? targetMatch.targetId : activeComment.comment_id;
            const activeTargetAuthor = targetMatch ? targetMatch.authorName : activeComment.author_name;
            selectedCommentId = activeTargetId;

            let postDetails = livePostDetailsCache[recordId];

            if (!postDetails || fetchFreshMedia) {
                panel.innerHTML = `
                    <div class="flex flex-col items-center justify-center h-full py-16 text-slate-400">
                        <i class="fas fa-circle-notch fa-spin text-3xl text-gb-cyan mb-3"></i>
                        <p class="text-xs sm:text-sm font-medium text-white">Fetching live post media from ${activeComment.platform.toUpperCase()}...</p>
                    </div>
                `;
                try {
                    let res = await fetch(`/api/posts/${recordId}/live_details`);
                    let data = await res.json();
                    if (data.status === 'success' && data.details) {
                        postDetails = data.details;
                        livePostDetailsCache[recordId] = postDetails;
                    }
                } catch (e) {
                    console.error("Live post details error:", e);
                }
            }

            const permalink = postDetails?.permalink_url || activeComment.post_permalink || activeComment.comment_permalink || '';
            const videoUrl = postDetails?.video_url || '';
            const thumbUrl = postDetails?.thumbnail_url || '';
            const imagesArr = postDetails?.images || [];
            const fallbackPreview = postDetails?.fallback_preview_url || '';

            let mediaViewerHTML = '';
            if (videoUrl) {
                mediaViewerHTML = `
                    <div class="w-full bg-black rounded-xl overflow-hidden border border-slate-700 flex items-center justify-center">
                        <video src="${videoUrl}" poster="${thumbUrl}" controls playsinline class="max-h-[280px] w-full object-contain"></video>
                    </div>
                `;
            } else if (imagesArr.length > 0) {
                const imgsGrid = imagesArr.map(imgUrl => `
                    <div onclick="openImageLightbox('${imgUrl}')" class="relative group cursor-zoom-in rounded-xl overflow-hidden border border-slate-700 bg-black h-44 flex items-center justify-center">
                        <img src="${imgUrl}" class="max-h-full max-w-full object-contain group-hover:scale-105 transition-transform">
                        <div class="absolute bottom-2 right-2 bg-black/75 text-gb-cyan px-2 py-0.5 rounded text-[10px] border border-gb-cyan/40">
                            <i class="fas fa-search-plus mr-1"></i>Click to Enlarge
                        </div>
                    </div>
                `).join('');
                mediaViewerHTML = `<div class="grid ${imagesArr.length > 1 ? 'grid-cols-2' : 'grid-cols-1'} gap-2.5">${imgsGrid}</div>`;
            } else if (fallbackPreview) {
                if (fallbackPreview.match(/\.(mp4|mov|webm)$/i) && activeComment.post_type !== 'image') {
                    mediaViewerHTML = `
                        <div class="w-full bg-black rounded-xl overflow-hidden border border-slate-700 flex items-center justify-center">
                            <video src="${fallbackPreview}" controls playsinline class="max-h-[280px] w-full object-contain"></video>
                        </div>
                    `;
                } else {
                    mediaViewerHTML = `
                        <div onclick="openImageLightbox('${fallbackPreview}')" class="relative cursor-zoom-in rounded-xl overflow-hidden border border-slate-700 bg-black h-44 flex items-center justify-center">
                            <img src="${fallbackPreview}" class="max-h-full max-w-full object-contain">
                        </div>
                    `;
                }
            } else if (activeComment.post_type === 'text') {
                mediaViewerHTML = `
                    <div class="p-3 rounded-xl bg-slate-950/60 border border-slate-800 text-xs text-slate-400 italic">
                        <i class="fas fa-align-left text-gb-cyan mr-1.5"></i> Text-only post (no video or image attached).
                    </div>
                `;
            } else {
                mediaViewerHTML = `
                    <div class="p-4 rounded-xl bg-slate-950/60 border border-slate-800 text-center text-xs text-slate-400">
                        <p>Direct media stream can be opened on ${activeComment.platform.toUpperCase()}.</p>
                        ${permalink ? `<a href="${permalink}" target="_blank" class="mt-2 inline-flex items-center gap-1.5 bg-gb-cyan/20 hover:bg-gb-cyan/30 text-gb-cyan border border-gb-cyan/50 px-3 py-1.5 rounded-lg font-semibold"><i class="fas fa-external-link-alt"></i> Open & Play Post on ${activeComment.platform.toUpperCase()}</a>` : ''}
                    </div>
                `;
            }

            const allPostCommentsHTML = buildPostCommentsThreadHTML(recordId, postComments, activeTargetId);
            panel.dataset.recordId = String(recordId);

            const methodBadge = `<span class="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-300 border border-purple-500/40 font-semibold"><i class="fas fa-bolt mr-1"></i>External API Reply</span>`;
            const canSendDmForPost = (activeComment.platform === 'facebook' || activeComment.platform === 'instagram');

            panel.innerHTML = `
                <div class="p-4 space-y-4 flex-1 flex flex-col justify-between">
                    <!-- TOP: ACTUAL POST CONTENT CARD -->
                    <div class="space-y-3">
                        <div class="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-slate-800">
                            <div class="flex items-center gap-2 flex-wrap">
                                ${getPlatformBadge(activeComment.platform, true)}
                                <span class="text-slate-600">•</span>
                                <span class="text-xs font-bold text-white">${escapeHTML(activeComment.account_name)}</span>
                                ${formatPostTypeBadge(activeComment.post_type)}
                                ${methodBadge}
                            </div>
                            <div class="flex items-center gap-2">
                                ${permalink ? `
                                    <a href="${permalink}" target="_blank" class="bg-gb-cyan/15 hover:bg-gb-cyan/25 border border-gb-cyan/50 text-gb-cyan px-3 py-1 rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 transition-all">
                                        <i class="fas fa-external-link-alt"></i> <span>Open Actual Post</span>
                                    </a>
                                ` : ''}
                                <button type="button" onclick="deletePostNotificationCard('${recordId}', event)"
                                    class="bg-rose-950/70 hover:bg-rose-600 border border-rose-500/60 text-rose-200 hover:text-white px-2.5 py-1 rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 transition-all"
                                    title="Delete all notifications for this post">
                                    <i class="fas fa-trash-alt"></i> <span>Delete Thread</span>
                                </button>
                            </div>
                        </div>

                        <!-- PLAYABLE VIDEO OR HIGH-RES IMAGES -->
                        ${mediaViewerHTML}

                        <!-- POST CAPTION -->
                        <div class="p-3 rounded-xl bg-slate-950/70 border border-slate-800/90">
                            <span class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold block mb-1">Original Post Caption</span>
                            <p class="text-xs text-slate-200 whitespace-pre-wrap max-h-20 overflow-y-auto">${activeComment.post_caption ? escapeHTML(activeComment.post_caption) : '<span class="italic text-slate-500">No caption</span>'}</p>
                        </div>

                        <!-- ALL COMMENTS ON THIS POST THREAD -->
                        <div class="pt-2 border-t border-slate-800">
                            <div class="flex items-center justify-between mb-2">
                                <span id="post-comments-count-label" class="text-[10px] uppercase tracking-wider text-gb-cyan font-semibold">
                                    <i class="fas fa-comments mr-1"></i> Comments on This Post (${postComments.length})
                                </span>
                                ${postComments.length > 1 ? `<span class="text-[10px] text-slate-400">Click any comment below to select who to reply to</span>` : ''}
                            </div>

                            <div id="post-comments-thread-list" class="space-y-2.5 max-h-[320px] overflow-y-auto pr-1">
                                ${allPostCommentsHTML}
                            </div>
                        </div>
                    </div>

                    <!-- BOTTOM: DIRECT REPLY BOX (ENTER KEY OR CLICK SEND REPLY) -->
                    <div class="pt-3 border-t border-slate-800 bg-slate-900/90 rounded-xl p-3 border border-slate-700/80">
                        <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
                            <label class="text-xs font-semibold text-white flex items-center gap-1.5">
                                <i class="fas fa-reply text-gb-cyan"></i>
                                <span id="reply-target-label">Reply to <span class="text-gb-cyan">${escapeHTML(activeTargetAuthor)}</span> as <span class="text-gb-cyan">${escapeHTML(activeComment.account_name)}</span></span>
                            </label>
                            <div class="flex flex-wrap gap-1">
                                <button type="button" onclick="insertQuickReply('Thank you! ❤️')" class="text-[10px] bg-slate-800 hover:bg-slate-700 border border-slate-600 text-slate-300 px-2 py-0.5 rounded transition-all">Thank you! ❤️</button>
                                <button type="button" onclick="insertQuickReply('We sent you a DM! 📩')" class="text-[10px] bg-slate-800 hover:bg-slate-700 border border-slate-600 text-slate-300 px-2 py-0.5 rounded transition-all">Sent you a DM 📩</button>
                                <button type="button" onclick="insertQuickReply('Sent you the details! 🚀')" class="text-[10px] bg-slate-800 hover:bg-slate-700 border border-slate-600 text-slate-300 px-2 py-0.5 rounded transition-all">Sent details 🚀</button>
                            </div>
                        </div>
                        <div class="flex flex-col sm:flex-row gap-2">
                            <textarea id="comment-reply-input" rows="2" onkeydown="handleCommentReplyKeyDown(event)" placeholder="Type your reply to ${escapeHTML(activeTargetAuthor)}... (Press Enter to send or click Send Reply)" class="flex-1 bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-xs sm:text-sm text-white focus:border-gb-cyan focus:outline-none resize-none"></textarea>
                            <div class="flex sm:flex-col gap-1.5 shrink-0">
                                <button id="btn-send-reply" onclick="sendCommentReply('${activeComment.record_id}', '${activeTargetId}')" class="flex-1 bg-gradient-to-r from-gb-blue to-gb-cyan text-slate-950 font-bold px-5 py-2 rounded-lg text-xs sm:text-sm shadow-[0_0_15px_rgba(0,240,255,0.3)] hover:shadow-[0_0_20px_rgba(0,240,255,0.6)] transition-all flex items-center justify-center gap-2">
                                    <i class="fas fa-reply"></i> <span>Send Reply</span>
                                </button>
                                ${canSendDmForPost ? `
                                    <button type="button" id="btn-send-dm-from-composer" onclick="openCommentDmModal('${activeComment.record_id}', '${activeTargetId}', event)" class="flex-1 bg-indigo-500/25 hover:bg-indigo-500/40 border border-indigo-400/60 text-indigo-200 hover:text-white font-semibold px-4 py-1.5 rounded-lg text-xs transition-all flex items-center justify-center gap-1.5" title="Send a Direct Message (Private Reply) to ${escapeHTML(activeTargetAuthor)}">
                                        <i class="fas fa-paper-plane text-[10px]"></i> <span>Send a DM</span>
                                    </button>
                                ` : ''}
                            </div>
                        </div>
                        <div class="mt-1.5 flex items-center justify-between text-[10px] text-slate-400">
                            <span><i class="fas fa-keyboard text-gb-cyan mr-1"></i>Press <strong>Enter</strong> to post reply or click <strong>Send Reply</strong></span>
                            <span><strong>Shift + Enter</strong> for new line</span>
                        </div>
                    </div>
                </div>
            `;
        }

        function insertQuickReply(text) {
            const input = document.getElementById('comment-reply-input');
            if (!input) return;
            input.value = text;
            input.focus();
        }

        function handleCommentReplyKeyDown(event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                const btn = document.getElementById('btn-send-reply');
                if (btn && !btn.disabled) {
                    btn.click();
                }
            }
        }

        // --- SEND A DM (PRIVATE REPLY) TO FACEBOOK / INSTAGRAM COMMENTER ---
        let activeCommentDmTarget = { recordId: '', commentId: '', authorName: '', accountName: '', platform: '' };

        function openCommentDmModal(recordId, commentId, event) {
            if (event) event.stopPropagation();
            const postComments = commentsList.filter(c => c.record_id === recordId);
            const targetMatch = findTargetItemInPostComments(postComments.length ? postComments : commentsList, commentId);
            const parentComm = targetMatch ? targetMatch.parentComment : (
                commentsList.find(c => c.record_id === recordId && c.comment_id === commentId)
                || commentsList.find(c => c.comment_id === commentId)
            );
            if (!parentComm) return;

            const plat = (parentComm.platform || '').toLowerCase();
            if (plat !== 'facebook' && plat !== 'instagram') {
                return showToast("⚠️ Send a DM from comments is only supported on Facebook and Instagram.");
            }

            const targetReply = targetMatch ? targetMatch.targetReply : null;
            const authorName = targetReply ? (targetReply.author_name || parentComm.author_name || 'User') : (parentComm.author_name || 'User');
            const commentText = targetReply ? (targetReply.message || parentComm.message || '') : (parentComm.message || '');
            const displayTime = targetReply ? (targetReply.display_time || parentComm.display_time || '') : (parentComm.display_time || '');
            const effCommentId = targetReply ? String(targetReply.id) : String(parentComm.comment_id);

            activeCommentDmTarget = {
                recordId: String(recordId),
                commentId: effCommentId,
                authorName: authorName,
                accountName: parentComm.account_name || plat.toUpperCase(),
                platform: plat
            };

            const modal = document.getElementById('comment-dm-modal');
            const badgeEl = document.getElementById('comment-dm-platform-badge');
            const accEl = document.getElementById('comment-dm-account-name');
            const authorEl = document.getElementById('comment-dm-author-name');
            const timeEl = document.getElementById('comment-dm-time');
            const previewEl = document.getElementById('comment-dm-comment-preview');
            const dmInput = document.getElementById('comment-dm-input');
            const replyBoxInput = document.getElementById('comment-reply-input');

            clearAttachmentForContext('comment_dm');

            if (badgeEl) badgeEl.innerHTML = getPlatformBadge(plat, true);
            if (accEl) accEl.textContent = activeCommentDmTarget.accountName;
            if (authorEl) authorEl.textContent = authorName;
            if (timeEl) timeEl.textContent = displayTime;
            if (previewEl) previewEl.textContent = `"${(commentText || '').trim()}"`;

            if (dmInput) {
                dmInput.value = (replyBoxInput && replyBoxInput.value.trim()) ? replyBoxInput.value.trim() : '';
                dmInput.placeholder = `Type your Direct Message to ${authorName}... (Press Enter to send or click Send a DM)`;
            }

            if (modal) {
                openModalWithFade('comment-dm-modal');
                setTimeout(() => { if (dmInput) dmInput.focus(); }, 40);
            }
        }

        function closeCommentDmModal() {
            clearAttachmentForContext('comment_dm');
            closeModalWithFade('comment-dm-modal');
        }

        function insertQuickCommentDm(text) {
            const dmInput = document.getElementById('comment-dm-input');
            if (!dmInput) return;
            dmInput.value = text;
            dmInput.focus();
        }

        function handleCommentDmKeyDown(event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                const btn = document.getElementById('btn-confirm-send-comment-dm');
                if (btn && !btn.disabled) {
                    submitCommentDm();
                }
            }
        }

        async function submitCommentDm() {
            const dmInput = document.getElementById('comment-dm-input');
            const btn = document.getElementById('btn-confirm-send-comment-dm');
            if (!dmInput || !btn) return;

            const message = dmInput.value.trim();
            const att = activeCommentDmAttachment;
            if (!message && !att) {
                return alert("Please type a Direct Message or attach a file before sending.");
            }

            const { recordId, commentId, authorName, platform } = activeCommentDmTarget;
            if (!recordId || !commentId) return;

            const origHTML = btn.innerHTML;
            btn.disabled = true;

            try {
                let fileIdToSend = '';
                let mediaUrlToSend = '';
                let filenameToSend = '';
                let mediaTypeToSend = '';

                if (att) {
                    if (att.source === 'vault' && att.file_id) {
                        fileIdToSend = String(att.file_id);
                        filenameToSend = String(att.filename || '');
                        mediaTypeToSend = String(att.media_type || '');
                    } else if (att.source === 'local' && att.localFile) {
                        btn.innerHTML = `<i class="fas fa-cloud-upload-alt fa-bounce"></i> <span>Uploading File...</span>`;
                        const upRes = await uploadLocalAttachmentForDmOrChat(att.localFile, platform || 'facebook', '');
                        mediaUrlToSend = upRes.media_url;
                        filenameToSend = upRes.filename || att.filename || '';
                        mediaTypeToSend = upRes.media_type || att.media_type || 'image';
                    }
                }

                btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> <span>Sending DM...</span>`;

                const res = await fetch('/api/comments/send_dm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        record_id: recordId,
                        comment_id: commentId,
                        message: message,
                        file_id: fileIdToSend,
                        media_url: mediaUrlToSend,
                        filename: filenameToSend,
                        media_type: mediaTypeToSend
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    const postComments = commentsList.filter(c => c.record_id === recordId);
                    const targetMatch = findTargetItemInPostComments(postComments.length ? postComments : commentsList, commentId);
                    if (targetMatch) {
                        if (targetMatch.targetReply) {
                            targetMatch.targetReply.dm_sent = true;
                        } else if (targetMatch.parentComment) {
                            targetMatch.parentComment.dm_sent = true;
                        }
                    }
                    dmInput.value = '';
                    clearAttachmentForContext('comment_dm');
                    closeCommentDmModal();
                    renderCommentsList();
                    if (selectedRecordId === recordId) {
                        syncOpenPostThreadLive(recordId);
                    }
                    showToast(`📩 Direct Message sent to ${authorName}!`);
                    try {
                        if (typeof fetchConversations === 'function') {
                            fetchConversations(false);
                        }
                    } catch (refreshErr) {
                        console.warn("Background conversation refresh warning:", refreshErr);
                    }
                } else {
                    alert("❌ Failed to send DM:\n" + (data.message || "Unknown error"));
                }
            } catch (e) {
                console.error("Send comment DM error:", e);
                alert("❌ Failed to send Direct Message:\n" + (e.message || "Network error while sending Direct Message."));
            } finally {
                btn.innerHTML = origHTML;
                btn.disabled = false;
            }
        }

        // --- LIKE COMMENT (FACEBOOK ONLY) & HIDE COMMENT (FACEBOOK, INSTAGRAM, TIKTOK) ---
        async function toggleLikeComment(recordId, commentId, event) {
            if (event) event.stopPropagation();
            const postComments = commentsList.filter(c => c.record_id === recordId);
            const targetMatch = findTargetItemInPostComments(postComments.length ? postComments : commentsList, commentId);
            const parentComm = targetMatch ? targetMatch.parentComment : (
                commentsList.find(c => c.record_id === recordId && c.comment_id === commentId)
                || commentsList.find(c => c.comment_id === commentId)
            );
            if (!parentComm) return;

            const plat = (parentComm.platform || '').toLowerCase();
            if (plat !== 'facebook') {
                return showToast("⚠️ Comment Like is only supported on Facebook.");
            }

            const targetObj = (targetMatch && targetMatch.targetReply) ? targetMatch.targetReply : parentComm;
            const nextLikedState = !Boolean(targetObj.is_liked);
            const btn = document.getElementById(`btn-like-comment-${commentId}`);
            const origBtnHTML = btn ? btn.innerHTML : '';
            if (btn) {
                btn.innerHTML = `<i class="fas fa-spinner fa-spin text-[10px]"></i>`;
                btn.disabled = true;
            }

            try {
                const res = await fetch('/api/comments/like', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        record_id: String(recordId),
                        comment_id: String(commentId),
                        liked: nextLikedState
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    targetObj.is_liked = nextLikedState;
                    renderCommentsList();
                    if (selectedRecordId === recordId) {
                        syncOpenPostThreadLive(recordId);
                    }
                    showToast(nextLikedState
                        ? `👍 Liked ${targetObj.author_name || 'user'}'s comment on Facebook!`
                        : `👍 Removed like from ${targetObj.author_name || 'user'}'s comment.`
                    );
                } else {
                    if (btn) {
                        btn.innerHTML = origBtnHTML;
                        btn.disabled = false;
                    }
                    alert("❌ Failed to like/unlike comment:\n" + (data.message || "Unknown error"));
                }
            } catch (e) {
                console.error("Toggle like comment error:", e);
                if (btn) {
                    btn.innerHTML = origBtnHTML;
                    btn.disabled = false;
                }
                alert("❌ Network error while liking comment.");
            }
        }

        async function toggleHideComment(recordId, commentId, event) {
            if (event) event.stopPropagation();
            const postComments = commentsList.filter(c => c.record_id === recordId);
            const targetMatch = findTargetItemInPostComments(postComments.length ? postComments : commentsList, commentId);
            const parentComm = targetMatch ? targetMatch.parentComment : (
                commentsList.find(c => c.record_id === recordId && c.comment_id === commentId)
                || commentsList.find(c => c.comment_id === commentId)
            );
            if (!parentComm) return;

            const plat = (parentComm.platform || '').toLowerCase();
            if (plat !== 'facebook' && plat !== 'instagram' && plat !== 'tiktok') {
                return showToast("⚠️ Comment Hide is only supported on Facebook, Instagram, and TikTok.");
            }

            const targetObj = (targetMatch && targetMatch.targetReply) ? targetMatch.targetReply : parentComm;
            const nextHiddenState = !Boolean(targetObj.is_hidden);
            const btn = document.getElementById(`btn-hide-comment-${commentId}`);
            const origBtnHTML = btn ? btn.innerHTML : '';
            if (btn) {
                btn.innerHTML = `<i class="fas fa-spinner fa-spin text-[10px]"></i>`;
                btn.disabled = true;
            }

            try {
                const res = await fetch('/api/comments/hide', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        record_id: String(recordId),
                        comment_id: String(commentId),
                        hidden: nextHiddenState
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    targetObj.is_hidden = nextHiddenState;
                    renderCommentsList();
                    if (selectedRecordId === recordId) {
                        syncOpenPostThreadLive(recordId);
                    }
                    showToast(nextHiddenState
                        ? `🙈 Hidden ${targetObj.author_name || 'user'}'s comment on ${plat.toUpperCase()}!`
                        : `👁️ Unhidden ${targetObj.author_name || 'user'}'s comment on ${plat.toUpperCase()}!`
                    );
                } else {
                    if (btn) {
                        btn.innerHTML = origBtnHTML;
                        btn.disabled = false;
                    }
                    alert("❌ Failed to hide/unhide comment:\n" + (data.message || "Unknown error"));
                }
            } catch (e) {
                console.error("Toggle hide comment error:", e);
                if (btn) {
                    btn.innerHTML = origBtnHTML;
                    btn.disabled = false;
                }
                alert("❌ Network error while hiding comment.");
            }
        }

        async function sendCommentReply(recordId, commentId) {
            const input = document.getElementById('comment-reply-input');
            const btn = document.getElementById('btn-send-reply');
            if (!input || !btn) return;

            const message = input.value.trim();

            if (!message) {
                return alert("Please type a reply message before clicking Send Reply.");
            }

            input.value = '';
            const postCommentsForReply = commentsList.filter(c => c.record_id === recordId);
            const targetMatch = findTargetItemInPostComments(postCommentsForReply.length ? postCommentsForReply : commentsList, commentId);
            const targetComment = targetMatch ? targetMatch.parentComment : (
                commentsList.find(c => c.record_id === recordId && c.comment_id === commentId)
                || commentsList.find(c => c.comment_id === commentId)
            );
            const parentCommentKey = targetComment ? targetComment.comment_id : commentId;

            const tempReplyId = `opt_${Date.now()}`;
            const optimisticReply = {
                id: tempReplyId,
                parent_comment_id: parentCommentKey,
                replied_to_id: commentId,
                author_name: targetComment?.account_name || 'You',
                author_avatar: '',
                is_own: true,
                is_read: true,
                can_reply: true,
                pending: true,
                message: message,
                created_iso: new Date().toISOString(),
                display_time: 'Sending...'
            };

            if (!pendingOptimisticReplies[parentCommentKey]) {
                pendingOptimisticReplies[parentCommentKey] = [];
            }
            pendingOptimisticReplies[parentCommentKey].push(optimisticReply);

            if (targetComment) {
                targetComment.replies = targetComment.replies || [];
                targetComment.replies.push(optimisticReply);
                targetComment.is_read = true;
                targetComment.parent_is_read = true;
                targetComment.has_unread_reply = false;
                targetComment.unread_replies_count = 0;
            }

            updateCommentsBadges();
            renderCommentsList();
            syncOpenPostThreadLive(recordId);

            const threadListEl = document.getElementById('post-comments-thread-list');
            if (threadListEl) {
                threadListEl.scrollTop = threadListEl.scrollHeight;
            }

            const origHTML = btn.innerHTML;
            btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> <span>Sending...</span>`;
            btn.disabled = true;

            try {
                let res = await fetch('/api/comments/reply', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        record_id: recordId,
                        comment_id: commentId,
                        message: message
                    })
                });
                let data = await res.json();
                if (data.status === 'success') {
                    optimisticReply.pending = false;
                    optimisticReply.id = data.reply?.id || data.reply_id || tempReplyId;
                    optimisticReply.display_time = data.reply?.display_time || 'Just now';
                    knownReplyIds.add(optimisticReply.id);

                    pendingOptimisticReplies[parentCommentKey] = (pendingOptimisticReplies[parentCommentKey] || []).filter(r => r.id !== tempReplyId && r.id !== optimisticReply.id);

                    renderCommentsList();
                    syncOpenPostThreadLive(recordId);
                    showToast("✅ Reply posted directly to comment!");
                } else {
                    pendingOptimisticReplies[parentCommentKey] = (pendingOptimisticReplies[parentCommentKey] || []).filter(r => r.id !== tempReplyId);
                    if (targetComment && Array.isArray(targetComment.replies)) {
                        targetComment.replies = targetComment.replies.filter(r => r.id !== tempReplyId);
                    }
                    if (!input.value) input.value = message;
                    renderCommentsList();
                    syncOpenPostThreadLive(recordId);
                    alert("❌ Failed to send reply:\n" + (data.message || "Unknown error"));
                }
            } catch (e) {
                console.error("Reply error:", e);
                pendingOptimisticReplies[parentCommentKey] = (pendingOptimisticReplies[parentCommentKey] || []).filter(r => r.id !== tempReplyId);
                if (targetComment && Array.isArray(targetComment.replies)) {
                    targetComment.replies = targetComment.replies.filter(r => r.id !== tempReplyId);
                }
                if (!input.value) input.value = message;
                renderCommentsList();
                syncOpenPostThreadLive(recordId);
                alert("❌ Network error while sending reply.");
            } finally {
                btn.innerHTML = origHTML;
                btn.disabled = false;
            }
        }
// ==================== END OF PART 2 (PASTE PART 3 RIGHT BELOW THIS LINE) ====================
// =========================================================================
        // --- UNIFIED INBOX & DIRECT MESSAGES (10 PER PAGE + SEE MORE + FILTER) ---
        // =========================================================================
        function updateMessagesBadges(totalUnread = null, totalDisplayed = null) {
            const unreadCount = (totalUnread !== null)
                ? totalUnread
                : messagesConversationsList.reduce((acc, c) => acc + (!c.is_read ? Math.max(1, Number(c.unread_count || 1)) : 0), 0);
            const totalCount = (totalDisplayed !== null) ? totalDisplayed : messagesConversationsList.length;

            const navUnread = document.getElementById('messages-unread-badge');
            const navTotal = document.getElementById('messages-total-badge');
            const headerPill = document.getElementById('messages-header-unread-pill');

            if (navTotal) navTotal.textContent = totalCount;

            if (unreadCount > 0) {
                if (navUnread) {
                    navUnread.textContent = `${unreadCount} new`;
                    navUnread.classList.remove('hidden');
                }
                if (headerPill) {
                    headerPill.textContent = `${unreadCount} Unread`;
                    headerPill.classList.remove('hidden');
                }
            } else {
                if (navUnread) navUnread.classList.add('hidden');
                if (headerPill) headerPill.classList.add('hidden');
            }
        }

        function populateMessagesPageFilterDropdown(pagesSummary) {
            const pageSelect = document.getElementById('messages-filter-page');
            const platFilter = document.getElementById('messages-filter-platform')?.value || 'all';
            if (!pageSelect) return;

            const currentVal = pageSelect.value || 'all';
            const list = Array.isArray(pagesSummary) ? pagesSummary : [];
            const filteredPages = (platFilter === 'all')
                ? list
                : list.filter(p => p.platform === platFilter);

            let html = `<option value="all">All Social Media Pages (${filteredPages.length})</option>`;
            filteredPages.forEach(p => {
                const platLabel = (p.platform || '').toUpperCase();
                const unreadTag = p.unread_count > 0 ? ` • ${p.unread_count} new` : '';
                const sel = (String(p.account_id) === String(currentVal)) ? 'selected' : '';
                html += `<option value="${escapeHTML(p.account_id)}" ${sel}>[${platLabel}] ${escapeHTML(p.account_name)} (${p.total_conversations || 0}${unreadTag})</option>`;
            });

            pageSelect.innerHTML = html;
            if (currentVal !== 'all' && !filteredPages.some(p => String(p.account_id) === String(currentVal))) {
                pageSelect.value = 'all';
            }
        }

        function onMessagesPlatformFilterChange() {
            populateMessagesPageFilterDropdown(messagesConnectedPagesSummary);
            fetchConversations(false);
        }

        function onMessagesPageFilterChange() {
            fetchConversations(false);
        }

        async function loadMoreConversationsForPage(accountId, event) {
            if (event) event.stopPropagation();
            const currentLim = Number(messagesPageLimits[accountId] || 10);
            messagesPageLimits[accountId] = currentLim + 10;
            await fetchConversations(false);
            showToast("📩 Loaded up to " + messagesPageLimits[accountId] + " conversations for this page!");
        }

        async function fetchConversations(showFeedback = false) {
            if (!showFeedback && window._gbInFlightPolls && window._gbInFlightPolls.conversations) {
                return;
            }
            if (window._gbInFlightPolls) window._gbInFlightPolls.conversations = true;

            const syncIcon = document.getElementById('sync-messages-icon');
            if (syncIcon && showFeedback) syncIcon.classList.add('fa-spin');

            try {
                const platFilter = document.getElementById('messages-filter-platform')?.value || 'all';
                const pageFilter = document.getElementById('messages-filter-page')?.value || 'all';
                const pageLimitsJson = encodeURIComponent(JSON.stringify(messagesPageLimits));

                const url = `/api/messages/conversations?force=${showFeedback ? 'true' : 'false'}&platform=${encodeURIComponent(platFilter)}&account_id=${encodeURIComponent(pageFilter)}&limit_per_page=10&page_limits=${pageLimitsJson}`;
                const res = await _gbFetchWithTimeout(url, {}, showFeedback ? 20000 : 8000);
                const data = await res.json();

                if (data.status === 'success') {
                    const incomingConvs = data.conversations || [];
                    messagesConnectedPagesSummary = data.connected_pages || [];

                    // Detect newly arrived unread messages for toast notification
                    let newlyArrivedMsg = null;
                    incomingConvs.forEach(c => {
                        const prevIso = knownMessageStateMap.get(c.conv_key);
                        if (!prevIso) {
                            knownMessageStateMap.set(c.conv_key, c.updated_iso || '');
                            if (!isInitialMessagesLoad && !c.is_read && !c.last_message_is_own) {
                                newlyArrivedMsg = c;
                            }
                        } else if ((c.updated_iso || '') > prevIso) {
                            knownMessageStateMap.set(c.conv_key, c.updated_iso || '');
                            if (!c.is_read && !c.last_message_is_own) {
                                newlyArrivedMsg = c;
                            }
                        }
                    });
                    isInitialMessagesLoad = false;

                    messagesConversationsList = incomingConvs;
                    populateMessagesPageFilterDropdown(messagesConnectedPagesSummary);
                    updateMessagesBadges(data.total_unread, data.total_displayed);
                    renderMessagesConversationsList();

                    if (selectedConversationKey) {
                        const stillExists = messagesConversationsList.find(c => c.conv_key === selectedConversationKey);
                        if (stillExists && activeTab === 'messages') {
                            await refreshOpenConversationSilently(stillExists.conversation_id, stillExists.account_id);
                        }
                    }

                    if (showFeedback) {
                        showToast(`💬 Synced ${messagesConversationsList.length} conversation(s)!`);
                    } else if (newlyArrivedMsg) {
                        triggerIncomingActivityAlert({
                            type: 'message',
                            platform: newlyArrivedMsg.platform || 'facebook',
                            author: newlyArrivedMsg.participant_name || 'Someone',
                            accountName: newlyArrivedMsg.account_name || '',
                            text: newlyArrivedMsg.last_message_text || '',
                            convKey: newlyArrivedMsg.conv_key || '',
                            fallbackText: `💬 New message from ${newlyArrivedMsg.participant_name} on ${newlyArrivedMsg.account_name}: "${(newlyArrivedMsg.last_message_text || '').slice(0, 45)}"`
                        });
                    }
                }
            } catch (e) {
                if (e && e.name !== 'AbortError') {
                    console.error("Error fetching conversations:", e);
                }
            } finally {
                if (window._gbInFlightPolls) window._gbInFlightPolls.conversations = false;
                if (syncIcon) syncIcon.classList.remove('fa-spin');
            }
        }

        function renderSingleConversationCardHTML(c) {
            const isSelected = (c.conv_key === selectedConversationKey);
            const hasUnread = !c.is_read;

            const avatarHTML = c.participant_avatar
                ? `<img src="${c.participant_avatar}" class="w-10 h-10 rounded-full object-cover border border-slate-600 shrink-0" onerror="this.outerHTML='<div class=\\'w-10 h-10 rounded-full bg-slate-800 border border-slate-600 flex items-center justify-center text-xs font-bold text-gb-cyan shrink-0\\'><i class=\\'fas fa-user\\'></i></div>'">`
                : `<div class="w-10 h-10 rounded-full bg-slate-800 border border-slate-600 flex items-center justify-center text-xs font-bold text-gb-cyan shrink-0"><i class="fas fa-user"></i></div>`;

            const unreadBadge = hasUnread
                ? `<span class="px-1.5 py-0.5 rounded-full bg-rose-500 text-white text-[10px] font-bold shadow-[0_0_8px_#f43f5e]">${c.unread_count > 1 ? c.unread_count + ' new' : 'New'}</span>`
                : `<span class="w-2 h-2 rounded-full bg-slate-700 shrink-0" title="Read"></span>`;

            const previewPrefix = c.last_message_is_own
                ? `<span class="text-gb-cyan font-semibold">You: </span>`
                : '';

            const existingContact = findExistingCrmContact(c.participant_name, c.platform);

            return `
                <div onclick="selectMessageConversation('${escapeHTML(c.conv_key)}', '${escapeHTML(c.conversation_id)}', '${escapeHTML(c.account_id)}')"
                     class="p-3 rounded-xl border transition-all cursor-pointer ${isSelected ? 'bg-gb-cyan/15 border-gb-cyan shadow-[0_0_15px_rgba(0,240,255,0.2)]' : (hasUnread ? 'bg-slate-800/95 border-rose-500/40 hover:border-gb-cyan/60' : 'bg-slate-800/50 border-slate-700/70 hover:bg-slate-800/90 hover:border-slate-600')}">
                    <div class="flex items-start gap-3">
                        <div class="relative shrink-0">
                            ${avatarHTML}
                            <span class="absolute -bottom-1 -right-1">${getPlatformBadge(c.platform)}</span>
                        </div>
                        <div class="min-w-0 flex-1">
                            <div class="flex items-start justify-between gap-2">
                                <div class="min-w-0">
                                    <h4 class="text-xs sm:text-sm font-bold text-white truncate">${escapeHTML(c.participant_name)}</h4>
                                    <span class="text-[10px] text-gb-cyan font-medium block truncate">
                                        <i class="fas fa-flag mr-1 text-[9px]"></i>${escapeHTML(c.account_name)}
                                    </span>
                                </div>
                                <div class="flex items-center gap-1.5 shrink-0">
                                    <button type="button" onclick="openAddToContactsFromMessage('${escapeHTML(c.conv_key)}', event)"
                                        class="px-2 py-0.5 rounded-lg text-[10px] font-bold border transition-all inline-flex items-center gap-1 ${existingContact ? 'bg-emerald-500/20 border-emerald-400/50 text-emerald-300' : 'bg-slate-900/90 hover:bg-emerald-500/25 border-emerald-500/40 text-emerald-300 hover:text-white'}"
                                        title="${existingContact ? 'Saved in Contacts — Click to View/Edit' : 'Add ' + escapeHTML(c.participant_name) + ' to CRM Contacts'}">
                                        <i class="fas ${existingContact ? 'fa-user-check' : 'fa-user-plus'} text-[9px]"></i>
                                        <span>${existingContact ? 'In Contacts' : '+ Contact'}</span>
                                    </button>
                                    <button type="button" onclick="promptDeleteMessageConversation('${escapeHTML(c.conv_key)}', '${escapeHTML(c.conversation_id)}', '${escapeHTML(c.participant_name || 'Conversation')}', event)"
                                        class="px-2 py-0.5 rounded-lg bg-rose-950/70 hover:bg-rose-600 border border-rose-500/50 text-rose-300 hover:text-white text-[10px] font-bold transition-all inline-flex items-center gap-1"
                                        title="Delete this conversation">
                                        <i class="fas fa-trash-alt text-[9px]"></i>
                                    </button>
                                    <span class="text-[10px] text-slate-400">${escapeHTML(c.display_time || '')}</span>
                                    ${unreadBadge}
                                </div>
                            </div>
                            <div class="mt-1.5 text-xs ${hasUnread ? 'text-white font-semibold' : 'text-slate-300'} bg-slate-950/60 px-2.5 py-1.5 rounded-lg border border-slate-800/90">
                                <span class="block truncate">${previewPrefix}${escapeHTML((c.last_message_text || 'No messages yet').replace(/\s+/g, ' ').trim())}</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        function renderMessagesConversationsList() {
            const container = document.getElementById('messages-list-container');
            const counterEl = document.getElementById('messages-list-counter');
            if (!container) return;

            const readFilter = document.getElementById('messages-filter-read')?.value || 'all';
            const pageFilter = document.getElementById('messages-filter-page')?.value || 'all';
            const platFilter = document.getElementById('messages-filter-platform')?.value || 'all';

            let filtered = messagesConversationsList;
            if (readFilter === 'unread') {
                filtered = filtered.filter(c => !c.is_read);
            }

            if (counterEl) {
                counterEl.textContent = `${filtered.length} person${filtered.length === 1 ? '' : 's'} shown`;
            }

            if (filtered.length === 0) {
                container.innerHTML = `
                    <div class="flex flex-col items-center justify-center py-12 px-4 text-center text-slate-500">
                        <i class="fas fa-inbox text-3xl mb-2.5 opacity-60"></i>
                        <p class="text-xs sm:text-sm font-medium text-slate-400">No conversations found.</p>
                        <p class="text-[11px] mt-1 text-slate-500">Click "Sync Messages" above or wait for new direct messages from your connected Social Media Pages.</p>
                    </div>
                `;
                return;
            }

            // Group by Social Media Page so each Page cleanly enforces its 10-person limit and has its own "See More (+10)" button
            const activePages = messagesConnectedPagesSummary.filter(p => {
                if (platFilter !== 'all' && p.platform !== platFilter) return false;
                if (pageFilter !== 'all' && String(p.account_id) !== String(pageFilter)) return false;
                return true;
            });

            if (activePages.length > 0) {
                let sectionsHTML = '';
                activePages.forEach(pageInfo => {
                    const pageConvs = filtered.filter(c => String(c.account_id) === String(pageInfo.account_id));
                    if (pageConvs.length === 0) return;

                    const cardsHTML = pageConvs.map(c => renderSingleConversationCardHTML(c)).join('');
                    const seeMoreBtnHTML = pageInfo.has_more
                        ? `
                            <button type="button" onclick="loadMoreConversationsForPage('${escapeHTML(pageInfo.account_id)}', event)"
                                class="w-full py-2 px-3 rounded-xl bg-slate-800/90 hover:bg-gb-cyan/20 border border-gb-cyan/40 text-gb-cyan text-xs font-bold flex items-center justify-center gap-2 transition-all shadow-[0_0_10px_rgba(0,240,255,0.1)]">
                                <i class="fas fa-plus-circle"></i>
                                <span>See More for ${escapeHTML(pageInfo.account_name)} (+10 People • ${pageInfo.remaining_count} more)</span>
                            </button>
                        `
                        : '';

                    sectionsHTML += `
                        <div class="space-y-2 pb-2">
                            <div class="px-2.5 py-1.5 rounded-lg bg-slate-950/90 border border-slate-800 flex items-center justify-between text-[11px]">
                                <span class="font-bold text-white flex items-center gap-1.5 truncate">
                                    ${getPlatformBadge(pageInfo.platform)}
                                    <span class="truncate">${escapeHTML(pageInfo.account_name)}</span>
                                </span>
                                <span class="text-[10px] text-slate-400 shrink-0">
                                    Showing ${pageConvs.length} of ${pageInfo.total_conversations} (Limit: ${pageInfo.current_limit})
                                </span>
                            </div>
                            <div class="space-y-2">
                                ${cardsHTML}
                            </div>
                            ${seeMoreBtnHTML}
                        </div>
                    `;
                });

                container.innerHTML = sectionsHTML || filtered.map(c => renderSingleConversationCardHTML(c)).join('');
            } else {
                container.innerHTML = filtered.map(c => renderSingleConversationCardHTML(c)).join('');
            }
        }

        async function selectMessageConversation(convKey, conversationId, accountId) {
            if (selectedConversationKey !== convKey) {
                clearAttachmentForContext('messages_chat');
            }
            selectedConversationKey = convKey;
            selectedConversationId = conversationId;
            selectedConversationAccountId = accountId;

            const target = messagesConversationsList.find(c => c.conv_key === convKey);
            if (target) {
                target.is_read = true;
                target.unread_count = 0;
                activeConversationObj = target;
            }
            updateMessagesBadges();
            renderMessagesConversationsList();

            const panel = document.getElementById('message-detail-panel');
            if (panel) {
                panel.innerHTML = `
                    <div class="flex flex-col items-center justify-center h-full py-16 text-slate-400">
                        <i class="fas fa-circle-notch fa-spin text-3xl text-gb-cyan mb-3"></i>
                        <p class="text-xs sm:text-sm font-medium text-white">Loading conversation history...</p>
                    </div>
                `;
            }

            try {
                const res = await fetch(`/api/messages/${encodeURIComponent(conversationId)}/thread?account_id=${encodeURIComponent(accountId)}&force=true`);
                const data = await res.json();
                if (data.status === 'success') {
                    activeConversationObj = data.conversation || target;
                    activeConversationMessages = data.messages || [];
                    renderActiveConversationThread(true);
                } else {
                    if (panel) {
                        panel.innerHTML = `<div class="p-8 text-center text-rose-400 text-xs">${escapeHTML(data.message || 'Could not load conversation messages.')}</div>`;
                    }
                }
            } catch (e) {
                console.error("Load conversation thread error:", e);
                if (panel) {
                    panel.innerHTML = `<div class="p-8 text-center text-rose-400 text-xs">Network error while loading conversation thread.</div>`;
                }
            }
        }

        async function refreshOpenConversationSilently(conversationId, accountId) {
            try {
                const res = await fetch(`/api/messages/${encodeURIComponent(conversationId)}/thread?account_id=${encodeURIComponent(accountId)}&force=false`);
                const data = await res.json();
                if (data.status === 'success') {
                    activeConversationObj = data.conversation || activeConversationObj;
                    const incomingMsgs = data.messages || [];
                    const pendingList = pendingOptimisticMessages[selectedConversationKey] || [];

                    pendingList.forEach(optM => {
                        const exists = incomingMsgs.some(m =>
                            m.id === optM.id || (m.is_own && (m.message || '').trim() === (optM.message || '').trim())
                        );
                        if (!exists) incomingMsgs.push(optM);
                    });

                    if (incomingMsgs.length !== activeConversationMessages.length) {
                        activeConversationMessages = incomingMsgs;
                        renderActiveConversationThread(true);
                    }
                }
            } catch (e) {
                console.error("Silent conversation refresh error:", e);
            }
        }

        function buildConversationMessagesBubblesHTML(messagesArr, participantName, accountName) {
            const validMessages = (Array.isArray(messagesArr) ? messagesArr : []).filter(m => {
                if (!m || typeof m !== 'object') return false;
                const hasText = Boolean((m.message || '').trim());
                const hasAtts = Array.isArray(m.attachments) && m.attachments.length > 0;
                return hasText || hasAtts;
            });

            if (validMessages.length === 0) {
                return `
                    <div class="flex flex-col items-center justify-center h-full py-12 text-slate-500 text-xs">
                        <i class="far fa-comments text-3xl mb-2 opacity-50"></i>
                        <p>No messages in this thread yet. Send a message below to start chatting!</p>
                    </div>
                `;
            }

            return validMessages.map(m => {
                const isOwn = Boolean(m.is_own);
                const senderLabel = isOwn ? (accountName || 'You') : (m.sender_name || participantName || 'User');
                const cleanMsgText = escapeHTML((m.message || '').trim());

                const attachmentsHTML = (Array.isArray(m.attachments) && m.attachments.length > 0)
                    ? `<div class="${cleanMsgText ? 'mt-2' : ''} flex flex-wrap gap-2">${m.attachments.map(att => {
                        const attUrl = String(att.url || '').trim();
                        const attType = String(att.type || '').toLowerCase();
                        const attName = String(att.name || 'Attachment').trim();
                        const lowUrl = attUrl.toLowerCase().split('?')[0];
                        if (attType === 'video' || /\.(mp4|mov|webm|mkv|avi|m4v)$/i.test(lowUrl)) {
                            return `<video src="${escapeHTML(attUrl)}" controls playsinline class="max-h-48 max-w-full rounded-lg border border-slate-600 bg-black"></video>`;
                        }
                        if (attType === 'file') {
                            return `<a href="${escapeHTML(attUrl)}" target="_blank" class="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-900/90 border border-gb-cyan/40 text-xs text-gb-cyan hover:bg-slate-800 transition-all"><i class="fas fa-file-download"></i><span>${escapeHTML(attName)}</span></a>`;
                        }
                        return `<img src="${escapeHTML(attUrl)}" onclick="openImageLightbox('${escapeHTML(attUrl)}')" class="max-h-40 rounded-lg border border-slate-600 cursor-zoom-in object-cover" onerror="this.outerHTML='<a href=\\'${escapeHTML(attUrl)}\\' target=\\'_blank\\' class=\\'text-xs text-gb-cyan underline\\'><i class=\\'fas fa-paperclip mr-1\\'></i>Open Attachment</a>'">`;
                    }).join('')}</div>`
                    : '';

                const msgIdSafe = escapeHTML(m.id || '');
                const deleteMsgBtnHTML = msgIdSafe
                    ? `<button type="button" onclick="promptDeleteSingleChatMessage('${msgIdSafe}', event)" class="px-1.5 py-0.5 rounded bg-rose-950/60 hover:bg-rose-600 border border-rose-500/40 text-rose-300 hover:text-white text-[9px] font-semibold transition-all inline-flex items-center gap-1" title="Delete this message"><i class="fas fa-trash-alt text-[8px]"></i></button>`
                    : '';

                if (isOwn) {
                    return `
                        <div class="flex flex-col items-end group">
                            <div class="flex items-center gap-1.5 mb-1 px-1">
                                ${deleteMsgBtnHTML}
                                <span class="text-[10px] text-slate-400">${escapeHTML(m.display_time || '')}</span>
                                <span class="text-[10px] font-bold text-gb-cyan">${escapeHTML(senderLabel)}</span>
                                ${m.pending ? `<span class="text-[9px] text-amber-300 font-semibold"><i class="fas fa-circle-notch fa-spin"></i> Sending...</span>` : ''}
                            </div>
                            <div class="w-fit max-w-[82%] sm:max-w-[75%] px-3.5 py-2 rounded-2xl rounded-tr-none ${m.pending ? 'bg-amber-500/15 border border-amber-400/50' : 'bg-gb-cyan/15 border border-gb-cyan/50 shadow-[0_0_12px_rgba(0,240,255,0.12)]'} text-xs sm:text-sm text-white leading-snug break-words">${cleanMsgText ? `<span class="whitespace-pre-wrap">${cleanMsgText}</span>` : ''}${attachmentsHTML}</div>
                        </div>
                    `;
                } else {
                    return `
                        <div class="flex flex-col items-start group">
                            <div class="flex items-center gap-1.5 mb-1 px-1">
                                <span class="text-[10px] font-bold text-white">${escapeHTML(senderLabel)}</span>
                                <span class="text-[10px] text-slate-400">${escapeHTML(m.display_time || '')}</span>
                                ${deleteMsgBtnHTML}
                            </div>
                            <div class="w-fit max-w-[82%] sm:max-w-[75%] px-3.5 py-2 rounded-2xl rounded-tl-none bg-slate-800/95 border border-slate-700 text-xs sm:text-sm text-slate-100 leading-snug break-words">${cleanMsgText ? `<span class="whitespace-pre-wrap">${cleanMsgText}</span>` : ''}${attachmentsHTML}</div>
                        </div>
                    `;
                }
            }).join('');
        }

        function renderActiveConversationThread(scrollToBottom = true) {
            const panel = document.getElementById('message-detail-panel');
            if (!panel || !activeConversationObj) return;

            const c = activeConversationObj;
            const avatarHTML = c.participant_avatar
                ? `<img src="${c.participant_avatar}" class="w-10 h-10 rounded-full object-cover border border-gb-cyan/50 shrink-0" onerror="this.outerHTML='<div class=\\'w-10 h-10 rounded-full bg-slate-800 border border-gb-cyan/50 flex items-center justify-center text-xs font-bold text-gb-cyan shrink-0\\'><i class=\\'fas fa-user\\'></i></div>'">`
                : `<div class="w-10 h-10 rounded-full bg-slate-800 border border-gb-cyan/50 flex items-center justify-center text-xs font-bold text-gb-cyan shrink-0"><i class="fas fa-user"></i></div>`;

            const bubblesHTML = buildConversationMessagesBubblesHTML(
                activeConversationMessages,
                c.participant_name,
                c.account_name
            );

            const existingDraftText = document.getElementById('direct-message-input')?.value || '';

            panel.innerHTML = `
                <div class="flex flex-col h-full justify-between overflow-hidden">
                    <!-- TOP: CONVERSATION HEADER -->
                    <div class="flex-none px-4 py-3 bg-slate-900/95 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2">
                        <div class="flex items-center gap-3 min-w-0">
                            <div class="relative shrink-0">
                                ${avatarHTML}
                                <span class="absolute -bottom-1 -right-1">${getPlatformBadge(c.platform)}</span>
                            </div>
                            <div class="min-w-0">
                                <h3 class="text-xs sm:text-sm font-bold text-white truncate">${escapeHTML(c.participant_name)}</h3>
                                <p class="text-[11px] text-slate-400 truncate">
                                    Chatting via <span class="text-gb-cyan font-semibold">${escapeHTML(c.account_name)}</span> • <span class="${c.platform === 'sms' ? 'text-emerald-300 font-semibold' : 'text-purple-300'}">${c.platform === 'sms' ? 'TextBee.dev SMS Gateway' : 'External API'}</span>
                                </p>
                            </div>
                        </div>
                        <div class="flex items-center gap-2 shrink-0">
                            <button type="button" onclick="openAddToContactsFromMessage('${escapeHTML(c.conv_key)}', event)"
                                class="px-3 py-1 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/35 border border-emerald-400/60 text-emerald-300 hover:text-white text-xs font-bold inline-flex items-center gap-1.5 transition-all shadow-[0_0_10px_rgba(16,185,129,0.2)]"
                                title="Add ${escapeHTML(c.participant_name)} to CRM Contacts with Auto-Fill">
                                <i class="fas fa-user-plus text-[10px]"></i> <span>Add to Contacts</span>
                            </button>
                            <button type="button" onclick="promptDeleteMessageConversation('${escapeHTML(c.conv_key)}', '${escapeHTML(c.conversation_id)}', '${escapeHTML(c.participant_name || 'Conversation')}', event)"
                                class="px-2.5 py-1 rounded-lg bg-rose-950/70 hover:bg-rose-600 border border-rose-500/60 text-rose-300 hover:text-white text-xs font-semibold inline-flex items-center gap-1.5 transition-all"
                                title="Delete this entire conversation">
                                <i class="fas fa-trash-alt text-[10px]"></i> <span>Delete Chat</span>
                            </button>
                            <button type="button" onclick="selectMessageConversation('${escapeHTML(c.conv_key)}', '${escapeHTML(c.conversation_id)}', '${escapeHTML(c.account_id)}')"
                                class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-600 text-gb-cyan text-xs font-semibold inline-flex items-center gap-1.5 transition-all"
                                title="Refresh this chat thread">
                                <i class="fas fa-sync-alt text-[10px]"></i> <span>Refresh Chat</span>
                            </button>
                        </div>
                    </div>

                    <!-- MIDDLE: SCROLLABLE CHAT BUBBLES -->
                    <div id="conversation-messages-scroll-box" class="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-950/40">
                        ${bubblesHTML}
                    </div>

                    <!-- BOTTOM: DIRECT MESSAGE COMPOSER -->
                    <div class="flex-none p-3 bg-slate-900/95 border-t border-slate-800">
                        <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
                            <div class="flex flex-wrap items-center gap-2">
                                <span class="text-[11px] font-semibold text-slate-300">
                                    <i class="fas fa-paper-plane text-gb-cyan mr-1"></i>Replying as <span class="text-gb-cyan">${escapeHTML(c.account_name)}</span>
                                </span>
                                ${(c.platform === 'facebook' || c.platform === 'instagram') ? (() => {
                                    let lastCustIso = '';
                                    const msgsArr = Array.isArray(activeConversationMessages) ? activeConversationMessages : [];
                                    for (let i = msgsArr.length - 1; i >= 0; i--) {
                                        if (msgsArr[i] && !msgsArr[i].is_own && msgsArr[i].created_iso) {
                                            lastCustIso = msgsArr[i].created_iso;
                                            break;
                                        }
                                    }
                                    if (!lastCustIso && !c.last_message_is_own && c.updated_iso) lastCustIso = c.updated_iso;
                                    const diffHrs = lastCustIso ? Math.max(0, (Date.now() - new Date(lastCustIso).getTime()) / 3600000) : 0;
                                    let winBadge = '<span class="px-2 py-0.5 rounded-md bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-[10px] font-semibold"><i class="fas fa-clock mr-1"></i>24h Window Active</span>';
                                    if (diffHrs >= 24 && diffHrs <= 168) {
                                        winBadge = '<span class="px-2 py-0.5 rounded-md bg-amber-500/15 border border-amber-400/50 text-amber-300 text-[10px] font-semibold" title="Standard 24h window expired; HUMAN_AGENT tag extends reply window up to 7 days"><i class="fas fa-user-shield mr-1"></i>7-Day Human Agent Window (' + Math.floor(diffHrs / 24) + 'd ago)</span>';
                                    } else if (diffHrs > 168) {
                                        winBadge = '<span class="px-2 py-0.5 rounded-md bg-rose-500/15 border border-rose-500/40 text-rose-300 text-[10px] font-semibold" title="Last customer message is over 7 days old"><i class="fas fa-exclamation-triangle mr-1"></i>Over 7-Day Window</span>';
                                    }
                                    return winBadge + `
                                    <label class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-slate-800/90 border border-gb-cyan/40 text-[10px] text-gb-cyan font-semibold cursor-pointer select-none" title="Uses Meta HUMAN_AGENT message tag to extend reply window from 24 hours up to 7 days">
                                        <input type="checkbox" id="dm-human-agent-toggle" checked class="accent-cyan-400 rounded cursor-pointer">
                                        <i class="fas fa-user-check text-[9px]"></i>
                                        <span>HUMAN_AGENT (7-Day Tag)</span>
                                    </label>`;
                                })() : ''}
                            </div>
                            <div class="flex flex-wrap gap-1">
                                <button type="button" onclick="insertQuickMessageReply('Hello! How can we help you today? 👋')" class="text-[10px] bg-slate-800 hover:bg-slate-700 border border-slate-600 text-slate-300 px-2 py-0.5 rounded transition-all">How can we help? 👋</button>
                                <button type="button" onclick="insertQuickMessageReply('Thank you for messaging us! ❤️')" class="text-[10px] bg-slate-800 hover:bg-slate-700 border border-slate-600 text-slate-300 px-2 py-0.5 rounded transition-all">Thank you! ❤️</button>
                                <button type="button" onclick="insertQuickMessageReply('Here are the details you requested! 🚀')" class="text-[10px] bg-slate-800 hover:bg-slate-700 border border-slate-600 text-slate-300 px-2 py-0.5 rounded transition-all">Here are the details 🚀</button>
                            </div>
                        </div>

                        <div id="chat-composer-attachment-preview" class="${activeChatAttachment ? 'mb-2' : 'hidden mb-2'}">${activeChatAttachment ? buildAttachmentPreviewCardHTML(activeChatAttachment, 'messages_chat') : ''}</div>

                        <div class="flex flex-col sm:flex-row gap-2 items-stretch sm:items-center">
                            <div class="flex items-stretch gap-2 flex-1">
                                <button type="button" onclick="openAttachmentSourceModal('messages_chat', event)"
                                    class="px-3.5 py-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-gb-cyan/50 hover:border-gb-cyan text-gb-cyan text-xs font-bold flex items-center justify-center gap-1.5 shrink-0 transition-all shadow-[0_0_12px_rgba(0,240,255,0.12)] cursor-pointer"
                                    title="Attach a file from your Local Device or from the Files Modal (Google Drive Vault)">
                                    <i class="fas fa-paperclip text-sm"></i>
                                    <span class="hidden md:inline">Attach File</span>
                                </button>
                                <textarea id="direct-message-input" rows="2"
                                    onkeydown="if(event.key==='Enter' && !event.shiftKey){ event.preventDefault(); sendDirectMessage('${escapeHTML(c.conversation_id)}', '${escapeHTML(c.account_id)}', '${escapeHTML(c.participant_id || '')}'); }"
                                    placeholder="Write a message to ${escapeHTML(c.participant_name)}... (Press Enter to send)"
                                    class="flex-1 bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-xs sm:text-sm text-white focus:border-gb-cyan focus:outline-none resize-none">${escapeHTML(existingDraftText)}</textarea>
                            </div>
                            <button id="btn-send-dm" onclick="sendDirectMessage('${escapeHTML(c.conversation_id)}', '${escapeHTML(c.account_id)}', '${escapeHTML(c.participant_id || '')}')"
                                class="bg-gradient-to-r from-gb-blue to-gb-cyan text-slate-950 font-bold px-5 py-2.5 rounded-lg text-xs sm:text-sm shadow-[0_0_15px_rgba(0,240,255,0.3)] hover:shadow-[0_0_20px_rgba(0,240,255,0.6)] transition-all flex items-center justify-center gap-2 shrink-0">
                                <i class="fas fa-paper-plane"></i> <span>Send</span>
                            </button>
                        </div>
                    </div>
                </div>
            `;

            if (scrollToBottom) {
                const scrollBox = document.getElementById('conversation-messages-scroll-box');
                if (scrollBox) {
                    scrollBox.scrollTop = scrollBox.scrollHeight;
                }
            }
        }

        // ==================== MESSAGES DELETE & DELETE ALL (WITH YES/NO CONFIRMATION MODAL) ====================
        let pendingMessagesDeleteAction = null;

        function openMessagesDeleteConfirmModal(descriptionText, onConfirmCallback) {
            pendingMessagesDeleteAction = typeof onConfirmCallback === 'function' ? onConfirmCallback : null;
            const modal = document.getElementById('gb-messages-delete-confirm-modal');
            const titleEl = document.getElementById('gb-messages-delete-confirm-title');
            const descEl = document.getElementById('gb-messages-delete-confirm-desc');
            if (titleEl) titleEl.textContent = 'Are you sure you want to delete?';
            if (descEl) descEl.textContent = descriptionText || 'This action will permanently remove the selected message(s) from your Messages hub.';
            if (modal) modal.classList.remove('hidden');
        }

        function closeMessagesDeleteConfirmModal() {
            pendingMessagesDeleteAction = null;
            const modal = document.getElementById('gb-messages-delete-confirm-modal');
            if (modal) modal.classList.add('hidden');
        }

        async function confirmMessagesDeleteAction() {
            const actionFn = pendingMessagesDeleteAction;
            closeMessagesDeleteConfirmModal();
            if (typeof actionFn === 'function') {
                await actionFn();
            }
        }

        function promptDeleteAllMessages() {
            const platFilter = document.getElementById('messages-filter-platform')?.value || 'all';
            const pageFilter = document.getElementById('messages-filter-page')?.value || 'all';
            const visibleCount = Array.isArray(messagesConversationsList) ? messagesConversationsList.length : 0;
            if (visibleCount === 0) {
                showToast('No messages or conversations to delete.');
                return;
            }
            const scopeDesc = (platFilter !== 'all' || pageFilter !== 'all')
                ? `This will delete all ${visibleCount} currently filtered conversation(s) in your Messages modal.`
                : `This will delete all ${visibleCount} conversation(s) and messages in your Messages modal.`;

            openMessagesDeleteConfirmModal(scopeDesc, async () => {
                try {
                    const res = await fetch('/api/messages/delete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            delete_all: true,
                            platform: platFilter,
                            account_id: pageFilter
                        })
                    });
                    const data = await res.json();
                    if (data.status === 'success') {
                        messagesConversationsList = [];
                        selectedConversationKey = null;
                        selectedConversationId = null;
                        selectedConversationAccountId = null;
                        activeConversationObj = null;
                        activeConversationMessages = [];
                        updateMessagesBadges();
                        renderMessagesConversationsList();
                        const panel = document.getElementById('message-detail-panel');
                        if (panel) {
                            panel.innerHTML = `
                                <div class="flex flex-col items-center justify-center h-full py-16 px-6 text-center text-slate-500">
                                    <div class="w-16 h-16 rounded-2xl bg-slate-800/80 border border-slate-700 flex items-center justify-center mb-3 text-slate-400">
                                        <i class="fas fa-comments text-2xl text-gb-cyan/70"></i>
                                    </div>
                                    <h3 class="text-sm sm:text-base font-bold text-slate-300 mb-1">Select a Person on the Left to View Conversation</h3>
                                    <p class="text-xs text-slate-400 max-w-md">Click any person from your connected Social Media Pages to read the full chat history and send a direct reply.</p>
                                </div>
                            `;
                        }
                        showToast('🗑️ All messages deleted successfully.');
                        fetchConversations(false);
                    } else {
                        showToast('⚠️ ' + (data.message || 'Failed to delete all messages.'));
                    }
                } catch (err) {
                    console.error('Delete all messages error:', err);
                    showToast('⚠️ Network error while deleting all messages.');
                }
            });
        }

        function promptDeleteMessageConversation(convKey, conversationId, participantName, ev) {
            if (ev && typeof ev.stopPropagation === 'function') {
                ev.stopPropagation();
                ev.preventDefault();
            }
            const label = participantName ? `"${participantName}"` : 'this conversation';
            openMessagesDeleteConfirmModal(`Delete the entire conversation with ${label}?`, async () => {
                try {
                    const res = await fetch('/api/messages/delete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            delete_all: false,
                            conversation_key: convKey,
                            conversation_id: conversationId
                        })
                    });
                    const data = await res.json();
                    if (data.status === 'success') {
                        messagesConversationsList = messagesConversationsList.filter(
                            c => c.conv_key !== convKey && String(c.conversation_id) !== String(conversationId)
                        );
                        if (selectedConversationKey === convKey || String(selectedConversationId) === String(conversationId)) {
                            selectedConversationKey = null;
                            selectedConversationId = null;
                            selectedConversationAccountId = null;
                            activeConversationObj = null;
                            activeConversationMessages = [];
                            const panel = document.getElementById('message-detail-panel');
                            if (panel) {
                                panel.innerHTML = `
                                    <div class="flex flex-col items-center justify-center h-full py-16 px-6 text-center text-slate-500">
                                        <div class="w-16 h-16 rounded-2xl bg-slate-800/80 border border-slate-700 flex items-center justify-center mb-3 text-slate-400">
                                            <i class="fas fa-comments text-2xl text-gb-cyan/70"></i>
                                        </div>
                                        <h3 class="text-sm sm:text-base font-bold text-slate-300 mb-1">Select a Person on the Left to View Conversation</h3>
                                        <p class="text-xs text-slate-400 max-w-md">Click any person from your connected Social Media Pages to read the full chat history and send a direct reply.</p>
                                    </div>
                                `;
                            }
                        }
                        updateMessagesBadges();
                        renderMessagesConversationsList();
                        showToast('🗑️ Conversation deleted.');
                    } else {
                        showToast('⚠️ ' + (data.message || 'Could not delete conversation.'));
                    }
                } catch (err) {
                    console.error('Delete conversation error:', err);
                    showToast('⚠️ Network error while deleting conversation.');
                }
            });
        }

        function promptDeleteSingleChatMessage(messageId, ev) {
            if (ev && typeof ev.stopPropagation === 'function') {
                ev.stopPropagation();
                ev.preventDefault();
            }
            if (!messageId) return;
            const convKey = selectedConversationKey || (activeConversationObj && activeConversationObj.conv_key) || '';
            const convId = selectedConversationId || (activeConversationObj && activeConversationObj.conversation_id) || '';

            openMessagesDeleteConfirmModal('Delete this specific message from the conversation?', async () => {
                try {
                    const res = await fetch('/api/messages/delete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            delete_all: false,
                            conversation_key: convKey,
                            conversation_id: convId,
                            message_id: messageId
                        })
                    });
                    const data = await res.json();
                    if (data.status === 'success') {
                        activeConversationMessages = (Array.isArray(activeConversationMessages) ? activeConversationMessages : []).filter(
                            m => String(m.id || '') !== String(messageId)
                        );
                        if (selectedConversationKey && pendingOptimisticMessages[selectedConversationKey]) {
                            pendingOptimisticMessages[selectedConversationKey] = pendingOptimisticMessages[selectedConversationKey].filter(
                                m => String(m.id || '') !== String(messageId)
                            );
                        }
                        if (data.conversation_empty) {
                            messagesConversationsList = messagesConversationsList.filter(
                                c => c.conv_key !== convKey && String(c.conversation_id) !== String(convId)
                            );
                            selectedConversationKey = null;
                            selectedConversationId = null;
                            selectedConversationAccountId = null;
                            activeConversationObj = null;
                            activeConversationMessages = [];
                            const panel = document.getElementById('message-detail-panel');
                            if (panel) {
                                panel.innerHTML = `
                                    <div class="flex flex-col items-center justify-center h-full py-16 px-6 text-center text-slate-500">
                                        <div class="w-16 h-16 rounded-2xl bg-slate-800/80 border border-slate-700 flex items-center justify-center mb-3 text-slate-400">
                                            <i class="fas fa-comments text-2xl text-gb-cyan/70"></i>
                                        </div>
                                        <h3 class="text-sm sm:text-base font-bold text-slate-300 mb-1">Select a Person on the Left to View Conversation</h3>
                                        <p class="text-xs text-slate-400 max-w-md">Click any person from your connected Social Media Pages to read the full chat history and send a direct reply.</p>
                                    </div>
                                `;
                            }
                        } else {
                            const convTarget = messagesConversationsList.find(c => c.conv_key === convKey);
                            if (convTarget && activeConversationMessages.length > 0) {
                                const latestMsg = activeConversationMessages[activeConversationMessages.length - 1];
                                convTarget.last_message_text = latestMsg.message || '[Media Attachment]';
                                convTarget.last_message_is_own = Boolean(latestMsg.is_own);
                            }
                            renderActiveConversationThread(false);
                        }
                        updateMessagesBadges();
                        renderMessagesConversationsList();
                        showToast('🗑️ Message deleted.');
                    } else {
                        showToast('⚠️ ' + (data.message || 'Could not delete message.'));
                    }
                } catch (err) {
                    console.error('Delete single message error:', err);
                    showToast('⚠️ Network error while deleting message.');
                }
            });
        }

        function insertQuickMessageReply(text) {
            const input = document.getElementById('direct-message-input');
            if (!input) return;
            input.value = text;
            input.focus();
        }

        async function sendDirectMessage(conversationId, accountId, recipientId = '') {
            const input = document.getElementById('direct-message-input');
            const btn = document.getElementById('btn-send-dm');
            if (!input || !btn) return;

            const message = input.value.trim();
            const att = activeChatAttachment;
            if (!message && !att) {
                return alert("Please type a message or attach a file before clicking Send.");
            }

            const plat = (activeConversationObj?.platform || 'facebook').toLowerCase();
            const origHTML = btn.innerHTML;
            btn.disabled = true;

            let fileIdToSend = '';
            let mediaUrlToSend = '';
            let filenameToSend = '';
            let mediaTypeToSend = '';
            let optimisticAttachments = [];

            try {
                if (att) {
                    if (att.source === 'vault' && att.file_id) {
                        fileIdToSend = String(att.file_id);
                        filenameToSend = String(att.filename || '');
                        mediaTypeToSend = String(att.media_type || 'image');
                        optimisticAttachments = [{
                            type: mediaTypeToSend,
                            url: att.preview_url || (`/api/files/${encodeURIComponent(fileIdToSend)}/stream`),
                            name: filenameToSend,
                            file_id: fileIdToSend
                        }];
                    } else if (att.source === 'local' && att.localFile) {
                        btn.innerHTML = `<i class="fas fa-cloud-upload-alt fa-bounce"></i> <span>Uploading...</span>`;
                        const upRes = await uploadLocalAttachmentForDmOrChat(att.localFile, plat, accountId);
                        mediaUrlToSend = upRes.media_url;
                        filenameToSend = upRes.filename || att.filename || '';
                        mediaTypeToSend = upRes.media_type || att.media_type || 'image';
                        optimisticAttachments = [{
                            type: mediaTypeToSend,
                            url: mediaUrlToSend,
                            name: filenameToSend
                        }];
                    }
                }
            } catch (upErr) {
                console.error("Chat attachment upload error:", upErr);
                btn.innerHTML = origHTML;
                btn.disabled = false;
                return alert("❌ Failed to upload attached file:\n" + (upErr.message || "Unknown upload error"));
            }

            const effDisplayMsg = message || (filenameToSend ? `📎 ${filenameToSend}` : 'Here is the file you requested:');
            input.value = '';
            clearAttachmentForContext('messages_chat');

            const tempId = `opt_dm_${Date.now()}`;
            const optimisticMsg = {
                id: tempId,
                sender_id: accountId,
                sender_name: activeConversationObj?.account_name || 'You',
                sender_avatar: '',
                is_own: true,
                pending: true,
                message: message,
                attachments: optimisticAttachments,
                created_iso: new Date().toISOString(),
                display_time: 'Sending...'
            };

            if (!pendingOptimisticMessages[selectedConversationKey]) {
                pendingOptimisticMessages[selectedConversationKey] = [];
            }
            pendingOptimisticMessages[selectedConversationKey].push(optimisticMsg);

            activeConversationMessages.push(optimisticMsg);
            if (activeConversationObj) {
                activeConversationObj.last_message_text = effDisplayMsg;
                activeConversationObj.last_message_is_own = true;
            }
            renderActiveConversationThread(true);
            renderMessagesConversationsList();

            const liveBtn = document.getElementById('btn-send-dm');
            if (liveBtn) {
                liveBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> <span>Sending...</span>`;
                liveBtn.disabled = true;
            }

            try {
                const res = await fetch('/api/messages/send', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        conversation_id: conversationId,
                        account_id: accountId,
                        recipient_id: recipientId,
                        message: message,
                        file_id: fileIdToSend,
                        media_url: mediaUrlToSend,
                        filename: filenameToSend,
                        media_type: mediaTypeToSend
                    })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    optimisticMsg.pending = false;
                    optimisticMsg.id = data.message_id || data.message?.id || tempId;
                    optimisticMsg.display_time = data.message?.display_time || 'Just now';
                    if (data.message?.attachments && data.message.attachments.length > 0) {
                        optimisticMsg.attachments = data.message.attachments;
                    }

                    pendingOptimisticMessages[selectedConversationKey] = (pendingOptimisticMessages[selectedConversationKey] || []).filter(m => m.id !== tempId);
                    renderActiveConversationThread(true);
                    renderMessagesConversationsList();
                    showToast("✅ Message sent!");
                } else {
                    pendingOptimisticMessages[selectedConversationKey] = (pendingOptimisticMessages[selectedConversationKey] || []).filter(m => m.id !== tempId);
                    activeConversationMessages = activeConversationMessages.filter(m => m.id !== tempId);
                    const curInput = document.getElementById('direct-message-input');
                    if (curInput && !curInput.value) curInput.value = message;
                    renderActiveConversationThread(true);
                    showToast("❌ " + (data.message || "Failed to send message."));
                    alert("❌ Failed to send message:\n" + (data.message || "Unknown error"));
                }
            } catch (e) {
                console.error("Send DM error:", e);
                pendingOptimisticMessages[selectedConversationKey] = (pendingOptimisticMessages[selectedConversationKey] || []).filter(m => m.id !== tempId);
                activeConversationMessages = activeConversationMessages.filter(m => m.id !== tempId);
                const curInput = document.getElementById('direct-message-input');
                if (curInput && !curInput.value) curInput.value = message;
                renderActiveConversationThread(true);
                alert("❌ Network error while sending message.");
            } finally {
                const finalBtn = document.getElementById('btn-send-dm');
                if (finalBtn) {
                    finalBtn.innerHTML = origHTML;
                    finalBtn.disabled = false;
                }
            }
        }

        async function markAllMessagesRead() {
            const unreadConvs = messagesConversationsList.filter(c => !c.is_read);
            if (unreadConvs.length === 0) {
                return showToast("✅ All conversations are already marked as read.");
            }
            messagesConversationsList.forEach(c => {
                c.is_read = true;
                c.unread_count = 0;
            });
            updateMessagesBadges(0, messagesConversationsList.length);
            renderMessagesConversationsList();

            try {
                await fetch('/api/messages/mark_read', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mark_all: true })
                });
                showToast(`✅ Marked ${unreadConvs.length} conversation(s) as read!`);
            } catch (e) {
                console.error("Mark all messages read error:", e);
            }
        }

