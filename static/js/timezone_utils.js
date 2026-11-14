(function (root, factory) {
    if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.GlennBotTimezoneUtils = factory();
    }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const DEFAULT_TIMEZONE = 'Asia/Manila';

    const TIMEZONE_OPTIONS = [
        {
            value: 'Asia/Manila',
            gmt: 'GMT+08:00',
            abbr: 'PHT',
            label: 'GMT+08:00 • Asia/Manila (PHT)',
            shortLabel: 'Asia/Manila (GMT+08:00)'
        },
        {
            value: 'Asia/Singapore',
            gmt: 'GMT+08:00',
            abbr: 'SGT',
            label: 'GMT+08:00 • Asia/Singapore (SGT)',
            shortLabel: 'Asia/Singapore (GMT+08:00)'
        },
        {
            value: 'Asia/Hong_Kong',
            gmt: 'GMT+08:00',
            abbr: 'HKT',
            label: 'GMT+08:00 • Asia/Hong_Kong (HKT)',
            shortLabel: 'Asia/Hong_Kong (GMT+08:00)'
        },
        {
            value: 'Asia/Tokyo',
            gmt: 'GMT+09:00',
            abbr: 'JST',
            label: 'GMT+09:00 • Asia/Tokyo (JST)',
            shortLabel: 'Asia/Tokyo (GMT+09:00)'
        },
        {
            value: 'Australia/Sydney',
            gmt: 'GMT+10:00',
            abbr: 'AEST',
            label: 'GMT+10:00 • Australia/Sydney (AEST/AEDT)',
            shortLabel: 'Australia/Sydney (GMT+10:00)'
        },
        {
            value: 'Asia/Dubai',
            gmt: 'GMT+04:00',
            abbr: 'GST',
            label: 'GMT+04:00 • Asia/Dubai (GST)',
            shortLabel: 'Asia/Dubai (GMT+04:00)'
        },
        {
            value: 'Europe/Berlin',
            gmt: 'GMT+01:00',
            abbr: 'CET',
            label: 'GMT+01:00 • Europe/Berlin (CET/CEST)',
            shortLabel: 'Europe/Berlin (GMT+01:00)'
        },
        {
            value: 'Europe/London',
            gmt: 'GMT+00:00',
            abbr: 'GMT',
            label: 'GMT+00:00 • Europe/London (GMT/BST)',
            shortLabel: 'Europe/London (GMT+00:00)'
        },
        {
            value: 'UTC',
            gmt: 'GMT+00:00',
            abbr: 'UTC',
            label: 'GMT+00:00 • UTC (Universal Time)',
            shortLabel: 'UTC (GMT+00:00)'
        },
        {
            value: 'America/New_York',
            gmt: 'GMT-05:00',
            abbr: 'EST',
            label: 'GMT-05:00 • America/New_York (EST/EDT)',
            shortLabel: 'America/New_York (GMT-05:00)'
        },
        {
            value: 'America/Chicago',
            gmt: 'GMT-06:00',
            abbr: 'CST',
            label: 'GMT-06:00 • America/Chicago (CST/CDT)',
            shortLabel: 'America/Chicago (GMT-06:00)'
        },
        {
            value: 'America/Denver',
            gmt: 'GMT-07:00',
            abbr: 'MST',
            label: 'GMT-07:00 • America/Denver (MST/MDT)',
            shortLabel: 'America/Denver (GMT-07:00)'
        },
        {
            value: 'America/Los_Angeles',
            gmt: 'GMT-08:00',
            abbr: 'PST',
            label: 'GMT-08:00 • America/Los_Angeles (PST/PDT)',
            shortLabel: 'America/Los_Angeles (GMT-08:00)'
        }
    ];

    const MONTH_SHORT_NAMES = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
    ];

    function normalizeTimezone(tz) {
        const clean = String(tz || '').trim();
        if (!clean) return DEFAULT_TIMEZONE;
        try {
            Intl.DateTimeFormat('en-US', { timeZone: clean });
            return clean;
        } catch (_) {
            return DEFAULT_TIMEZONE;
        }
    }

    function getTimezoneMeta(tz) {
        const clean = normalizeTimezone(tz);
        const found = TIMEZONE_OPTIONS.find(o => o.value === clean);
        if (found) return found;
        return {
            value: clean,
            gmt: getDynamicGmtOffsetString(new Date(), clean),
            abbr: clean.split('/').pop() || clean,
            label: `${getDynamicGmtOffsetString(new Date(), clean)} • ${clean}`,
            shortLabel: `${clean} (${getDynamicGmtOffsetString(new Date(), clean)})`
        };
    }

    function getDynamicGmtOffsetString(dateObj, timeZone) {
        const d = (dateObj instanceof Date && !isNaN(dateObj.getTime())) ? dateObj : new Date();
        const tz = normalizeTimezone(timeZone);
        try {
            const parts = new Intl.DateTimeFormat('en-US', {
                timeZone: tz,
                timeZoneName: 'longOffset'
            }).formatToParts(d);
            const tzPart = parts.find(p => p.type === 'timeZoneName');
            if (tzPart && tzPart.value) {
                if (tzPart.value === 'GMT' || tzPart.value === 'UTC') return 'GMT+00:00';
                return tzPart.value.replace(/^UTC/, 'GMT');
            }
        } catch (_) {}
        const fallback = TIMEZONE_OPTIONS.find(o => o.value === tz);
        return fallback ? fallback.gmt : 'GMT+08:00';
    }

    /**
     * Extract numeric date/time components of a Date instant in a target IANA timezone.
     */
    function getPartsInTimezone(dateObj, timeZone) {
        const tz = normalizeTimezone(timeZone);
        const formatter = new Intl.DateTimeFormat('en-US', {
            timeZone: tz,
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hourCycle: 'h23'
        });
        const parts = formatter.formatToParts(dateObj);
        const map = {};
        for (const p of parts) {
            if (p.type !== 'literal') map[p.type] = p.value;
        }
        const year = parseInt(map.year, 10);
        const month = parseInt(map.month, 10);
        const day = parseInt(map.day, 10);
        let hour24 = parseInt(map.hour, 10);
        if (hour24 === 24) hour24 = 0;
        const minute = parseInt(map.minute, 10);
        const second = parseInt(map.second || '0', 10);

        const date_str = `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        const time_24 = `${String(hour24).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
        const monthShort = MONTH_SHORT_NAMES[month - 1] || 'Jan';
        const display_date = `${monthShort} ${String(day).padStart(2, '0')}, ${year}`;
        const ampm = hour24 >= 12 ? 'PM' : 'AM';
        const hour12 = String(hour24 % 12 || 12).padStart(2, '0');
        const time_str = `${hour12}:${String(minute).padStart(2, '0')} ${ampm}`;
        const gmt = getDynamicGmtOffsetString(dateObj, tz);

        return {
            year,
            month,
            day,
            hour24,
            minute,
            second,
            date_str,
            time_24,
            display_date,
            time_str,
            display_datetime: `${display_date} • ${time_str}`,
            gmt,
            timezone: tz
        };
    }

    /**
     * Given a wall-clock YYYY-MM-DD and HH:MM in `sourceTz`, returns a UTC Date object
     * representing that exact moment.
     */
    function zonedDateTimeToUtcDate(dateStr, timeStr, sourceTz) {
        const cleanDate = String(dateStr || '').trim();
        const cleanTime = String(timeStr || '').trim();
        if (!/^\d{4}-\d{2}-\d{2}$/.test(cleanDate) || !/^\d{2}:\d{2}/.test(cleanTime)) {
            return null;
        }
        const tz = normalizeTimezone(sourceTz);
        const [year, month, day] = cleanDate.split('-').map(Number);
        const [hour, minute] = cleanTime.slice(0, 5).split(':').map(Number);

        // Initial guess assuming wall-clock is UTC
        const utcGuessMs = Date.UTC(year, month - 1, day, hour, minute, 0, 0);
        const guessDate = new Date(utcGuessMs);

        // Compare what wall-clock `guessDate` produces in `tz`
        const parts1 = getPartsInTimezone(guessDate, tz);
        const wallAsUtc1 = Date.UTC(parts1.year, parts1.month - 1, parts1.day, parts1.hour24, parts1.minute, 0, 0);
        const offsetMs1 = wallAsUtc1 - utcGuessMs;
        const adjustedMs1 = utcGuessMs - offsetMs1;
        const adjustedDate1 = new Date(adjustedMs1);

        // Second pass in case adjustment crossed a DST boundary
        const parts2 = getPartsInTimezone(adjustedDate1, tz);
        const wallAsUtc2 = Date.UTC(parts2.year, parts2.month - 1, parts2.day, parts2.hour24, parts2.minute, 0, 0);
        const offsetMs2 = wallAsUtc2 - adjustedMs1;
        return new Date(utcGuessMs - offsetMs2);
    }

    /**
     * Converts a wall-clock date (YYYY-MM-DD) and time (HH:MM) from `fromTz` to `toTz`.
     */
    function convertWallDateTimeBetweenTimezones(dateStr, timeStr, fromTz, toTz) {
        const utcDate = zonedDateTimeToUtcDate(dateStr, timeStr, fromTz);
        if (!utcDate || isNaN(utcDate.getTime())) {
            return {
                date_str: String(dateStr || ''),
                time_24: String(timeStr || ''),
                display_date: '',
                time_str: '',
                iso: ''
            };
        }
        const targetParts = getPartsInTimezone(utcDate, toTz);
        return {
            date_str: targetParts.date_str,
            time_24: targetParts.time_24,
            display_date: targetParts.display_date,
            time_str: targetParts.time_str,
            gmt: targetParts.gmt,
            timezone: targetParts.timezone,
            iso: utcDate.toISOString(),
            epoch_ms: utcDate.getTime()
        };
    }

    /**
     * Resolves a post's canonical Date object from `scheduled_iso` or fallback `date_str` + `time_str` (assumed Asia/Manila).
     */
    function resolvePostInstant(post) {
        if (!post || typeof post !== 'object') return null;
        if (post.scheduled_iso) {
            const d = new Date(post.scheduled_iso);
            if (!isNaN(d.getTime())) return d;
        }
        if (post.date_str && post.time_str) {
            // Parse 12-hour "06:30 PM" or 24-hour "18:30"
            const rawTime = String(post.time_str).trim();
            let time24 = rawTime;
            const m12 = rawTime.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
            if (m12) {
                let hh = parseInt(m12[1], 10);
                const mm = m12[2];
                const mer = m12[3].toUpperCase();
                if (mer === 'PM' && hh < 12) hh += 12;
                if (mer === 'AM' && hh === 12) hh = 0;
                time24 = `${String(hh).padStart(2, '0')}:${mm}`;
            }
            const fallbackSourceTz = post.source_timezone || DEFAULT_TIMEZONE;
            return zonedDateTimeToUtcDate(post.date_str, time24, fallbackSourceTz);
        }
        return null;
    }

    /**
     * Returns a shallow copy of a scheduled post with `day`, `month`, `year`,
     * `date_str`, `display_date`, `time_str`, `display_datetime`, `gmt_label`,
     * and `epoch_ms` recalculated in `targetTz`.
     */
    function projectPostToTimezone(post, targetTz) {
        if (!post || typeof post !== 'object') return post;
        const tz = normalizeTimezone(targetTz);
        const instant = resolvePostInstant(post);
        if (!instant || isNaN(instant.getTime())) {
            return Object.assign({}, post, {
                display_timezone: tz,
                gmt_label: getTimezoneMeta(tz).gmt,
                epoch_ms: 0
            });
        }

        const parts = getPartsInTimezone(instant, tz);
        const origManilaParts = getPartsInTimezone(instant, DEFAULT_TIMEZONE);
        const meta = getTimezoneMeta(tz);

        return Object.assign({}, post, {
            day: parts.day,
            month: parts.month,
            year: parts.year,
            date_str: parts.date_str,
            time_24: parts.time_24,
            display_date: parts.display_date,
            time_str: parts.time_str,
            display_datetime: `${parts.display_date} • ${parts.time_str}`,
            display_timezone: tz,
            display_timezone_short: meta.shortLabel,
            gmt_label: parts.gmt,
            orig_manila_datetime: `${origManilaParts.display_date} • ${origManilaParts.time_str} (Asia/Manila)`,
            epoch_ms: instant.getTime()
        });
    }

    /**
     * Projects an array of scheduled posts into `targetTz` and sorts them chronologically
     * (`direction`: 'asc' | 'desc') based on their scheduled timestamp.
     */
    function projectAndSortPostsInTimezone(posts, targetTz, direction = 'asc') {
        if (!Array.isArray(posts)) return [];
        const tz = normalizeTimezone(targetTz);
        const projected = posts.map(p => projectPostToTimezone(p, tz));
        projected.sort((a, b) => {
            const diff = (a.epoch_ms || 0) - (b.epoch_ms || 0);
            if (diff !== 0) return direction === 'desc' ? -diff : diff;
            return String(a.id || '').localeCompare(String(b.id || ''));
        });
        return projected;
    }

    /**
     * Projects a Composio Google Calendar event into `targetTz` when `start_iso` or `date_str` + `time_24` is present.
     */
    function projectCalendarEventToTimezone(ev, targetTz) {
        if (!ev || typeof ev !== 'object') return ev;
        const tz = normalizeTimezone(targetTz);
        if (ev.is_all_day || (!ev.start_iso && !ev.time_24)) {
            return Object.assign({}, ev, {
                display_timezone: tz,
                gmt_label: getTimezoneMeta(tz).gmt
            });
        }
        let instant = null;
        if (ev.start_iso && /T/.test(String(ev.start_iso))) {
            const rawIso = String(ev.start_iso).trim();
            // If start_iso has an explicit offset or Z, parse directly; otherwise treat as Asia/Manila
            if (/[Zz]|[+-]\d{2}:\d{2}$/.test(rawIso)) {
                const parsed = new Date(rawIso);
                if (!isNaN(parsed.getTime())) instant = parsed;
            } else if (ev.date_str && ev.time_24) {
                instant = zonedDateTimeToUtcDate(ev.date_str, ev.time_24, DEFAULT_TIMEZONE);
            }
        } else if (ev.date_str && ev.time_24) {
            instant = zonedDateTimeToUtcDate(ev.date_str, ev.time_24, DEFAULT_TIMEZONE);
        }

        if (!instant || isNaN(instant.getTime())) {
            return Object.assign({}, ev, {
                display_timezone: tz,
                gmt_label: getTimezoneMeta(tz).gmt
            });
        }

        const parts = getPartsInTimezone(instant, tz);
        return Object.assign({}, ev, {
            day: parts.day,
            month: parts.month,
            year: parts.year,
            date_str: parts.date_str,
            time_24: parts.time_24,
            display_date: parts.display_date,
            time_str: parts.time_str,
            display_timezone: tz,
            gmt_label: parts.gmt,
            epoch_ms: instant.getTime()
        });
    }

    function buildTimezoneOptionsHTML(selectedTz) {
        const active = normalizeTimezone(selectedTz);
        return TIMEZONE_OPTIONS.map(opt => {
            const sel = opt.value === active ? 'selected' : '';
            return `<option value="${opt.value}" ${sel}>${opt.label}</option>`;
        }).join('');
    }

    return {
        DEFAULT_TIMEZONE,
        TIMEZONE_OPTIONS,
        normalizeTimezone,
        getTimezoneMeta,
        getDynamicGmtOffsetString,
        getPartsInTimezone,
        zonedDateTimeToUtcDate,
        convertWallDateTimeBetweenTimezones,
        resolvePostInstant,
        projectPostToTimezone,
        projectAndSortPostsInTimezone,
        projectCalendarEventToTimezone,
        buildTimezoneOptionsHTML
    };
});
