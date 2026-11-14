(function (root, factory) {
    if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.GlennBotTimezoneUtils = factory();
    }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const FALLBACK_TIMEZONE = 'Asia/Manila';

    // Known friendly short abbreviations for popular timezones
    const KNOWN_ABBRS = {
        'Asia/Manila': 'PHT',
        'Asia/Singapore': 'SGT',
        'Asia/Hong_Kong': 'HKT',
        'Asia/Taipei': 'CST',
        'Asia/Tokyo': 'JST',
        'Asia/Seoul': 'KST',
        'Asia/Bangkok': 'ICT',
        'Asia/Jakarta': 'WIB',
        'Asia/Ho_Chi_Minh': 'ICT',
        'Asia/Kuala_Lumpur': 'MYT',
        'Asia/Dubai': 'GST',
        'Asia/Riyadh': 'AST',
        'Asia/Qatar': 'AST',
        'Asia/Kolkata': 'IST',
        'Asia/Karachi': 'PKT',
        'Asia/Dhaka': 'BST',
        'Asia/Jerusalem': 'IST',
        'Australia/Sydney': 'AEST/AEDT',
        'Australia/Melbourne': 'AEST/AEDT',
        'Australia/Brisbane': 'AEST',
        'Australia/Perth': 'AWST',
        'Pacific/Auckland': 'NZST/NZDT',
        'Pacific/Honolulu': 'HST',
        'Europe/London': 'GMT/BST',
        'Europe/Dublin': 'GMT/IST',
        'Europe/Paris': 'CET/CEST',
        'Europe/Berlin': 'CET/CEST',
        'Europe/Madrid': 'CET/CEST',
        'Europe/Rome': 'CET/CEST',
        'Europe/Amsterdam': 'CET/CEST',
        'Europe/Zurich': 'CET/CEST',
        'Europe/Stockholm': 'CET/CEST',
        'Europe/Warsaw': 'CET/CEST',
        'Europe/Athens': 'EET/EEST',
        'Europe/Istanbul': 'TRT',
        'Europe/Moscow': 'MSK',
        'Africa/Cairo': 'EET',
        'Africa/Johannesburg': 'SAST',
        'Africa/Lagos': 'WAT',
        'Africa/Nairobi': 'EAT',
        'America/New_York': 'EST/EDT',
        'America/Chicago': 'CST/CDT',
        'America/Denver': 'MST/MDT',
        'America/Los_Angeles': 'PST/PDT',
        'America/Phoenix': 'MST',
        'America/Anchorage': 'AKST/AKDT',
        'America/Toronto': 'EST/EDT',
        'America/Vancouver': 'PST/PDT',
        'America/Mexico_City': 'CST',
        'America/Sao_Paulo': 'BRT',
        'America/Argentina/Buenos_Aires': 'ART',
        'America/Bogota': 'COT',
        'America/Lima': 'PET',
        'America/Santiago': 'CLT/CLST',
        'UTC': 'UTC'
    };

    // Baseline fallback IANA zones if Intl.supportedValuesOf is unavailable
    const BASELINE_IANA_TIMEZONES = [
        'UTC',
        'Pacific/Midway', 'Pacific/Niue', 'Pacific/Pago_Pago',
        'Pacific/Honolulu', 'Pacific/Rarotonga', 'Pacific/Tahiti',
        'America/Anchorage', 'America/Juneau', 'America/Metlakatla', 'America/Nome', 'America/Sitka', 'America/Yakutat',
        'America/Los_Angeles', 'America/Tijuana', 'America/Vancouver',
        'America/Denver', 'America/Edmonton', 'America/Phoenix', 'America/Whitehorse',
        'America/Chicago', 'America/Guatemala', 'America/Managua', 'America/Mexico_City', 'America/Monterrey', 'America/Regina', 'America/Tegucigalpa', 'America/Winnipeg',
        'America/Bogota', 'America/Cancun', 'America/Cayman', 'America/Detroit', 'America/Havana', 'America/Jamaica', 'America/Lima', 'America/Nassau', 'America/New_York', 'America/Panama', 'America/Port-au-Prince', 'America/Toronto',
        'America/Asuncion', 'America/Barbados', 'America/Caracas', 'America/Cuiaba', 'America/Guyana', 'America/Halifax', 'America/La_Paz', 'America/Manaus', 'America/Puerto_Rico', 'America/Santiago', 'America/Santo_Domingo',
        'America/St_Johns',
        'America/Araguaina', 'America/Argentina/Buenos_Aires', 'America/Bahia', 'America/Belem', 'America/Cayenne', 'America/Fortaleza', 'America/Godthab', 'America/Maceio', 'America/Miquelon', 'America/Montevideo', 'America/Paramaribo', 'America/Recife', 'America/Sao_Paulo',
        'Atlantic/South_Georgia',
        'Atlantic/Azores', 'Atlantic/Cape_Verde',
        'Africa/Abidjan', 'Africa/Accra', 'Africa/Bamako', 'Africa/Banjul', 'Africa/Bissau', 'Africa/Casablanca', 'Africa/Conakry', 'Africa/Dakar', 'Africa/El_Aaiun', 'Africa/Freetown', 'Africa/Lome', 'Africa/Monrovia', 'Africa/Nouakchott', 'Africa/Ouagadougou', 'Africa/Sao_Tome', 'Atlantic/Reykjavik', 'Europe/Dublin', 'Europe/Lisbon', 'Europe/London',
        'Africa/Algiers', 'Africa/Bangui', 'Africa/Brazzaville', 'Africa/Ceuta', 'Africa/Douala', 'Africa/Kinshasa', 'Africa/Lagos', 'Africa/Libreville', 'Africa/Luanda', 'Africa/Malabo', 'Africa/Ndjamena', 'Africa/Niamey', 'Africa/Porto-Novo', 'Africa/Tunis', 'Africa/Windhoek',
        'Europe/Amsterdam', 'Europe/Andorra', 'Europe/Belgrade', 'Europe/Berlin', 'Europe/Bratislava', 'Europe/Brussels', 'Europe/Budapest', 'Europe/Copenhagen', 'Europe/Gibraltar', 'Europe/Ljubljana', 'Europe/Luxembourg', 'Europe/Madrid', 'Europe/Malta', 'Europe/Monaco', 'Europe/Oslo', 'Europe/Paris', 'Europe/Podgorica', 'Europe/Prague', 'Europe/Rome', 'Europe/San_Marino', 'Europe/Sarajevo', 'Europe/Skopje', 'Europe/Stockholm', 'Europe/Tirane', 'Europe/Vaduz', 'Europe/Vatican', 'Europe/Vienna', 'Europe/Warsaw', 'Europe/Zagreb', 'Europe/Zurich',
        'Africa/Blantyre', 'Africa/Bujumbura', 'Africa/Cairo', 'Africa/Gaborone', 'Africa/Harare', 'Africa/Johannesburg', 'Africa/Juba', 'Africa/Khartoum', 'Africa/Kigali', 'Africa/Lubumbashi', 'Africa/Lusaka', 'Africa/Maputo', 'Africa/Maseru', 'Africa/Mbabane', 'Africa/Tripoli',
        'Asia/Amman', 'Asia/Beirut', 'Asia/Damascus', 'Asia/Famagusta', 'Asia/Gaza', 'Asia/Hebron', 'Asia/Jerusalem', 'Asia/Nicosia',
        'Europe/Athens', 'Europe/Bucharest', 'Europe/Chisinau', 'Europe/Helsinki', 'Europe/Kaliningrad', 'Europe/Kyiv', 'Europe/Mariehamn', 'Europe/Riga', 'Europe/Sofia', 'Europe/Tallinn', 'Europe/Vilnius',
        'Africa/Addis_Ababa', 'Africa/Asmara', 'Africa/Dar_es_Salaam', 'Africa/Djibouti', 'Africa/Kampala', 'Africa/Mogadishu', 'Africa/Nairobi', 'Asia/Aden', 'Asia/Baghdad', 'Asia/Bahrain', 'Asia/Kuwait', 'Asia/Qatar', 'Asia/Riyadh', 'Europe/Istanbul', 'Europe/Kirov', 'Europe/Minsk', 'Europe/Moscow', 'Europe/Simferopol', 'Europe/Volgograd', 'Indian/Antananarivo', 'Indian/Comoro', 'Indian/Mayotte',
        'Asia/Tehran',
        'Asia/Baku', 'Asia/Dubai', 'Asia/Muscat', 'Asia/Tbilisi', 'Asia/Yerevan', 'Europe/Astrakhan', 'Europe/Samara', 'Europe/Saratov', 'Europe/Ulyanovsk', 'Indian/Mahe', 'Indian/Mauritius', 'Indian/Reunion',
        'Asia/Kabul',
        'Asia/Aqtau', 'Asia/Aqtobe', 'Asia/Ashgabat', 'Asia/Atyrau', 'Asia/Dushanbe', 'Asia/Karachi', 'Asia/Oral', 'Asia/Qyzylorda', 'Asia/Samarkand', 'Asia/Tashkent', 'Asia/Yekaterinburg', 'Indian/Kerguelen', 'Indian/Maldives',
        'Asia/Colombo', 'Asia/Kolkata',
        'Asia/Kathmandu',
        'Asia/Almaty', 'Asia/Bishkek', 'Asia/Dhaka', 'Asia/Omsk', 'Asia/Qostanay', 'Asia/Thimphu', 'Asia/Urumqi', 'Indian/Chagos',
        'Asia/Yangon', 'Indian/Cocos',
        'Asia/Bangkok', 'Asia/Barnaul', 'Asia/Hovd', 'Asia/Ho_Chi_Minh', 'Asia/Jakarta', 'Asia/Krasnoyarsk', 'Asia/Novokuznetsk', 'Asia/Novosibirsk', 'Asia/Phnom_Penh', 'Asia/Pontianak', 'Asia/Tomsk', 'Asia/Vientiane', 'Indian/Christmas',
        'Asia/Brunei', 'Asia/Choibalsan', 'Asia/Hong_Kong', 'Asia/Irkutsk', 'Asia/Kuala_Lumpur', 'Asia/Kuching', 'Asia/Macau', 'Asia/Makassar', 'Asia/Manila', 'Asia/Shanghai', 'Asia/Singapore', 'Asia/Taipei', 'Asia/Ulaanbaatar', 'Australia/Perth',
        'Australia/Eucla',
        'Asia/Chita', 'Asia/Dili', 'Asia/Jayapura', 'Asia/Khandyga', 'Asia/Pyongyang', 'Asia/Seoul', 'Asia/Tokyo', 'Asia/Yakutsk', 'Pacific/Palau',
        'Australia/Adelaide', 'Australia/Broken_Hill', 'Australia/Darwin',
        'Asia/Ust-Nera', 'Asia/Vladivostok', 'Australia/Brisbane', 'Australia/Hobart', 'Australia/Lindeman', 'Australia/Melbourne', 'Australia/Sydney', 'Pacific/Chuuk', 'Pacific/Guam', 'Pacific/Port_Moresby', 'Pacific/Saipan',
        'Australia/Lord_Howe',
        'Antarctica/Macquarie', 'Asia/Magadan', 'Asia/Sakhalin', 'Asia/Srednekolymsk', 'Pacific/Bougainville', 'Pacific/Efate', 'Pacific/Guadalcanal', 'Pacific/Kosrae', 'Pacific/Norfolk', 'Pacific/Noumea', 'Pacific/Pohnpei',
        'Asia/Anadyr', 'Asia/Kamchatka', 'Pacific/Auckland', 'Pacific/Fiji', 'Pacific/Funafuti', 'Pacific/Kwajalein', 'Pacific/Majuro', 'Pacific/Nauru', 'Pacific/Tarawa', 'Pacific/Wake', 'Pacific/Wallis',
        'Pacific/Chatham',
        'Pacific/Apia', 'Pacific/Enderbury', 'Pacific/Fakaofo', 'Pacific/Tongatapu',
        'Pacific/Kiritimati'
    ];

    const MONTH_SHORT_NAMES = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
    ];

    const COUNTRY_DEFAULT_TIMEZONES = {
        PH: 'Asia/Manila',
        SG: 'Asia/Singapore',
        MY: 'Asia/Kuala_Lumpur',
        HK: 'Asia/Hong_Kong',
        TW: 'Asia/Taipei',
        JP: 'Asia/Tokyo',
        KR: 'Asia/Seoul',
        TH: 'Asia/Bangkok',
        VN: 'Asia/Ho_Chi_Minh',
        ID: 'Asia/Jakarta',
        IN: 'Asia/Kolkata',
        PK: 'Asia/Karachi',
        BD: 'Asia/Dhaka',
        LK: 'Asia/Colombo',
        NP: 'Asia/Kathmandu',
        AE: 'Asia/Dubai',
        SA: 'Asia/Riyadh',
        QA: 'Asia/Qatar',
        KW: 'Asia/Kuwait',
        BH: 'Asia/Bahrain',
        OM: 'Asia/Muscat',
        IL: 'Asia/Jerusalem',
        TR: 'Europe/Istanbul',
        AU: 'Australia/Sydney',
        NZ: 'Pacific/Auckland',
        GB: 'Europe/London',
        UK: 'Europe/London',
        IE: 'Europe/Dublin',
        FR: 'Europe/Paris',
        DE: 'Europe/Berlin',
        ES: 'Europe/Madrid',
        IT: 'Europe/Rome',
        NL: 'Europe/Amsterdam',
        BE: 'Europe/Brussels',
        CH: 'Europe/Zurich',
        AT: 'Europe/Vienna',
        SE: 'Europe/Stockholm',
        NO: 'Europe/Oslo',
        DK: 'Europe/Copenhagen',
        FI: 'Europe/Helsinki',
        PL: 'Europe/Warsaw',
        PT: 'Europe/Lisbon',
        GR: 'Europe/Athens',
        ZA: 'Africa/Johannesburg',
        NG: 'Africa/Lagos',
        EG: 'Africa/Cairo',
        KE: 'Africa/Nairobi',
        US: 'America/New_York',
        CA: 'America/Toronto',
        MX: 'America/Mexico_City',
        BR: 'America/Sao_Paulo',
        AR: 'America/Argentina/Buenos_Aires',
        CL: 'America/Santiago',
        CO: 'America/Bogota',
        PE: 'America/Lima'
    };

    let _cachedTimezoneOptions = null;
    let _detectedUserTimezone = null;

    function isValidTimezone(tz) {
        const clean = String(tz || '').trim();
        if (!clean) return false;
        try {
            Intl.DateTimeFormat('en-US', { timeZone: clean });
            return true;
        } catch (_) {
            return false;
        }
    }

    function resolveTimezoneFromCountryCode(countryCode) {
        const code = String(countryCode || '').trim().toUpperCase();
        if (code && COUNTRY_DEFAULT_TIMEZONES[code] && isValidTimezone(COUNTRY_DEFAULT_TIMEZONES[code])) {
            return COUNTRY_DEFAULT_TIMEZONES[code];
        }
        return '';
    }

    /**
     * Auto-detects the current user's IANA timezone from their browser/OS country & region
     * (or returns a previously detected override). Falls back to Asia/Manila if unavailable.
     */
    function detectUserTimezone() {
        if (_detectedUserTimezone && isValidTimezone(_detectedUserTimezone)) {
            return _detectedUserTimezone;
        }
        try {
            const resolved = Intl.DateTimeFormat().resolvedOptions().timeZone;
            if (resolved && isValidTimezone(resolved) && !/^(UTC|Etc\/UTC|Etc\/GMT|GMT)$/i.test(resolved)) {
                _detectedUserTimezone = resolved;
                return resolved;
            }
        } catch (_) {}
        try {
            if (typeof navigator !== 'undefined') {
                const langs = Array.isArray(navigator.languages) && navigator.languages.length
                    ? navigator.languages
                    : [navigator.language || ''];
                for (const loc of langs) {
                    const m = String(loc || '').match(/[-_]([A-Za-z]{2})$/);
                    if (m) {
                        const byCountry = resolveTimezoneFromCountryCode(m[1]);
                        if (byCountry) {
                            _detectedUserTimezone = byCountry;
                            return byCountry;
                        }
                    }
                }
            }
        } catch (_) {}
        return FALLBACK_TIMEZONE;
    }

    function setDetectedUserTimezone(tz) {
        if (isValidTimezone(tz)) {
            _detectedUserTimezone = String(tz).trim();
            return _detectedUserTimezone;
        }
        const byCountry = resolveTimezoneFromCountryCode(tz);
        if (byCountry) {
            _detectedUserTimezone = byCountry;
            return _detectedUserTimezone;
        }
        return detectUserTimezone();
    }

    function normalizeTimezone(tz) {
        const clean = String(tz || '').trim();
        if (clean && isValidTimezone(clean)) return clean;
        return detectUserTimezone();
    }

    function getDynamicGmtOffsetString(dateObj, timeZone) {
        const d = (dateObj instanceof Date && !isNaN(dateObj.getTime())) ? dateObj : new Date();
        const tz = isValidTimezone(timeZone) ? String(timeZone).trim() : FALLBACK_TIMEZONE;
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
        return 'GMT+00:00';
    }

    function parseGmtOffsetMinutes(gmtStr) {
        const m = String(gmtStr || '').match(/^GMT([+-])(\d{2}):(\d{2})$/);
        if (!m) return 0;
        const sign = m[1] === '-' ? -1 : 1;
        return sign * (parseInt(m[2], 10) * 60 + parseInt(m[3], 10));
    }

    function getShortTimezoneAbbr(dateObj, tz) {
        if (KNOWN_ABBRS[tz]) return KNOWN_ABBRS[tz];
        try {
            const parts = new Intl.DateTimeFormat('en-US', {
                timeZone: tz,
                timeZoneName: 'short'
            }).formatToParts(dateObj);
            const tzPart = parts.find(p => p.type === 'timeZoneName');
            if (tzPart && tzPart.value && !/^GMT[+-]/i.test(tzPart.value)) {
                return tzPart.value;
            }
        } catch (_) {}
        return '';
    }

    /**
     * Builds and caches the complete list of all supported IANA timezones worldwide.
     */
    function getAllTimezoneOptions() {
        if (_cachedTimezoneOptions) return _cachedTimezoneOptions;

        const rawSet = new Set(BASELINE_IANA_TIMEZONES);
        try {
            if (typeof Intl !== 'undefined' && typeof Intl.supportedValuesOf === 'function') {
                const supported = Intl.supportedValuesOf('timeZone');
                if (Array.isArray(supported)) {
                    supported.forEach(z => rawSet.add(z));
                }
            }
        } catch (_) {}
        rawSet.add('UTC');
        rawSet.add('Asia/Manila');

        const now = new Date();
        const list = [];

        for (const tz of rawSet) {
            if (!isValidTimezone(tz)) continue;
            const gmt = getDynamicGmtOffsetString(now, tz);
            const offsetMinutes = parseGmtOffsetMinutes(gmt);
            const abbr = getShortTimezoneAbbr(now, tz);
            const abbrSuffix = abbr ? ` (${abbr})` : '';
            const label = `${gmt} • ${tz}${abbrSuffix}`;
            const shortLabel = `${tz} (${gmt})`;
            list.push({
                value: tz,
                gmt,
                offsetMinutes,
                abbr: abbr || tz.split('/').pop() || tz,
                label,
                shortLabel
            });
        }

        // Sort by GMT offset ascending, then keeping Asia/Manila & major hubs easy to scan, then alphabetically
        list.sort((a, b) => {
            if (a.offsetMinutes !== b.offsetMinutes) {
                return a.offsetMinutes - b.offsetMinutes;
            }
            return a.value.localeCompare(b.value);
        });

        _cachedTimezoneOptions = list;
        return _cachedTimezoneOptions;
    }

    function getTimezoneMeta(tz) {
        const clean = normalizeTimezone(tz);
        const all = getAllTimezoneOptions();
        const found = all.find(o => o.value === clean);
        if (found) return found;
        const gmt = getDynamicGmtOffsetString(new Date(), clean);
        const abbr = KNOWN_ABBRS[clean] || clean.split('/').pop() || clean;
        return {
            value: clean,
            gmt,
            offsetMinutes: parseGmtOffsetMinutes(gmt),
            abbr,
            label: `${gmt} • ${clean} (${abbr})`,
            shortLabel: `${clean} (${gmt})`
        };
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

        const utcGuessMs = Date.UTC(year, month - 1, day, hour, minute, 0, 0);
        const guessDate = new Date(utcGuessMs);

        const parts1 = getPartsInTimezone(guessDate, tz);
        const wallAsUtc1 = Date.UTC(parts1.year, parts1.month - 1, parts1.day, parts1.hour24, parts1.minute, 0, 0);
        const offsetMs1 = wallAsUtc1 - utcGuessMs;
        const adjustedMs1 = utcGuessMs - offsetMs1;
        const adjustedDate1 = new Date(adjustedMs1);

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
     * Resolves a post's canonical Date object from `scheduled_iso` or fallback `date_str` + `time_str`.
     */
    function resolvePostInstant(post) {
        if (!post || typeof post !== 'object') return null;
        if (post.scheduled_iso) {
            const d = new Date(post.scheduled_iso);
            if (!isNaN(d.getTime())) return d;
        }
        if (post.date_str && post.time_str) {
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
            const fallbackSourceTz = post.source_timezone || FALLBACK_TIMEZONE;
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
        const origManilaParts = getPartsInTimezone(instant, FALLBACK_TIMEZONE);
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
            if (/[Zz]|[+-]\d{2}:\d{2}$/.test(rawIso)) {
                const parsed = new Date(rawIso);
                if (!isNaN(parsed.getTime())) instant = parsed;
            } else if (ev.date_str && ev.time_24) {
                instant = zonedDateTimeToUtcDate(ev.date_str, ev.time_24, FALLBACK_TIMEZONE);
            }
        } else if (ev.date_str && ev.time_24) {
            instant = zonedDateTimeToUtcDate(ev.date_str, ev.time_24, FALLBACK_TIMEZONE);
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

    /**
     * Generates <option> tags for all global IANA timezones with explicit dark background
     * and white text classes so options are always readable in native OS dropdown menus.
     */
    function buildTimezoneOptionsHTML(selectedTz) {
        const active = normalizeTimezone(selectedTz || detectUserTimezone());
        const options = getAllTimezoneOptions();
        return options.map(opt => {
            const sel = opt.value === active ? 'selected' : '';
            return `<option value="${opt.value}" class="bg-slate-900 text-white" ${sel}>${opt.label}</option>`;
        }).join('');
    }

    return {
        get DEFAULT_TIMEZONE() { return detectUserTimezone(); },
        FALLBACK_TIMEZONE,
        COUNTRY_DEFAULT_TIMEZONES,
        get TIMEZONE_OPTIONS() { return getAllTimezoneOptions(); },
        isValidTimezone,
        resolveTimezoneFromCountryCode,
        detectUserTimezone,
        setDetectedUserTimezone,
        normalizeTimezone,
        getAllTimezoneOptions,
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
