import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import tzUtils from '../static/js/timezone_utils.js';

describe('GlennBotTimezoneUtils', () => {
    it('defaults to Asia/Manila with GMT+08:00 metadata', () => {
        assert.equal(tzUtils.DEFAULT_TIMEZONE, 'Asia/Manila');
        assert.equal(tzUtils.normalizeTimezone(''), 'Asia/Manila');
        assert.equal(tzUtils.normalizeTimezone('Invalid/Zone'), 'Asia/Manila');

        const meta = tzUtils.getTimezoneMeta('Asia/Manila');
        assert.equal(meta.value, 'Asia/Manila');
        assert.equal(meta.gmt, 'GMT+08:00');
        assert.ok(meta.label.includes('GMT+08:00'));
        assert.ok(meta.label.includes('Asia/Manila'));
    });

    it('converts wall-clock date and time from Asia/Manila (GMT+08:00) to UTC and America/New_York', () => {
        // 2026-11-15 08:30 in Asia/Manila (UTC+8) -> 2026-11-15 00:30 in UTC
        const toUtc = tzUtils.convertWallDateTimeBetweenTimezones(
            '2026-11-15',
            '08:30',
            'Asia/Manila',
            'UTC'
        );
        assert.equal(toUtc.date_str, '2026-11-15');
        assert.equal(toUtc.time_24, '00:30');
        assert.equal(toUtc.time_str, '12:30 AM');

        // 2026-11-15 08:30 in Asia/Manila (UTC+8) -> 2026-11-14 19:30 in America/New_York (EST, UTC-5)
        const toNy = tzUtils.convertWallDateTimeBetweenTimezones(
            '2026-11-15',
            '08:30',
            'Asia/Manila',
            'America/New_York'
        );
        assert.equal(toNy.date_str, '2026-11-14');
        assert.equal(toNy.time_24, '19:30');
        assert.equal(toNy.display_date, 'Nov 14, 2026');
        assert.equal(toNy.time_str, '07:30 PM');
    });

    it('projects a scheduled post from Asia/Manila ISO into another timezone and updates day, month, year, display_date, and time_str', () => {
        // Post scheduled for Jan 1, 2027 at 05:00 AM Asia/Manila (+08:00)
        // In UTC that is Dec 31, 2026 at 09:00 PM (21:00)
        const manilaPost = {
            id: 'post-1',
            platform: 'facebook',
            scheduled_iso: '2027-01-01T05:00:00+08:00',
            date_str: '2027-01-01',
            display_date: 'Jan 01, 2027',
            time_str: '05:00 AM',
            day: 1,
            month: 1,
            year: 2027
        };

        const inManila = tzUtils.projectPostToTimezone(manilaPost, 'Asia/Manila');
        assert.equal(inManila.year, 2027);
        assert.equal(inManila.month, 1);
        assert.equal(inManila.day, 1);
        assert.equal(inManila.display_date, 'Jan 01, 2027');
        assert.equal(inManila.time_str, '05:00 AM');
        assert.equal(inManila.gmt_label, 'GMT+08:00');

        const inUtc = tzUtils.projectPostToTimezone(manilaPost, 'UTC');
        assert.equal(inUtc.year, 2026);
        assert.equal(inUtc.month, 12);
        assert.equal(inUtc.day, 31);
        assert.equal(inUtc.display_date, 'Dec 31, 2026');
        assert.equal(inUtc.time_str, '09:00 PM');
        assert.equal(inUtc.gmt_label, 'GMT+00:00');

        const inTokyo = tzUtils.projectPostToTimezone(manilaPost, 'Asia/Tokyo');
        assert.equal(inTokyo.year, 2027);
        assert.equal(inTokyo.month, 1);
        assert.equal(inTokyo.day, 1);
        assert.equal(inTokyo.display_date, 'Jan 01, 2027');
        assert.equal(inTokyo.time_str, '06:00 AM');
        assert.equal(inTokyo.gmt_label, 'GMT+09:00');
    });

    it('sorts and arranges posts chronologically in the selected timezone', () => {
        const posts = [
            {
                id: 'later-post',
                scheduled_iso: '2026-11-16T10:00:00+08:00'
            },
            {
                id: 'earlier-post',
                scheduled_iso: '2026-11-15T22:00:00+08:00'
            }
        ];

        const arranged = tzUtils.projectAndSortPostsInTimezone(posts, 'America/Los_Angeles', 'asc');
        assert.equal(arranged[0].id, 'earlier-post');
        assert.equal(arranged[1].id, 'later-post');
        assert.equal(arranged[0].display_date, 'Nov 15, 2026');
        assert.equal(arranged[0].time_str, '06:00 AM');
        assert.equal(arranged[1].display_date, 'Nov 15, 2026');
        assert.equal(arranged[1].time_str, '06:00 PM');
    });
});
