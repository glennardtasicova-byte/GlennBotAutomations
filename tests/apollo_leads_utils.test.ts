import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import apolloUtils from '../static/js/apollo_leads_utils.js';

describe('GlennBotApolloUtils', () => {
    it('normalizes the 5 core Apollo.io search filters with sensible defaults', () => {
        const defaults = apolloUtils.normalizeApolloSearchFilters({});
        assert.equal(defaults.job_title, 'CEO / Founder');
        assert.equal(defaults.location, 'United States');
        assert.equal(defaults.industry, 'SaaS & Software');
        assert.equal(defaults.seniority, 'all');
        assert.equal(defaults.company_size, 'any');
        assert.equal(defaults.verified_email_only, true);

        const custom = apolloUtils.normalizeApolloSearchFilters({
            job_title: 'Operations Director',
            location: 'Australia',
            industry: 'Manufacturing & Industrial',
            seniority: 'director',
            company_size: '51-200',
            verified_email_only: true
        });
        assert.equal(custom.job_title, 'Operations Director');
        assert.equal(custom.location, 'Australia');
        assert.equal(custom.industry, 'Manufacturing & Industrial');
        assert.equal(custom.seniority, 'director');
        assert.equal(custom.company_size, '51-200');
    });

    it('maps an Apollo.io lead into a CRM contact payload with platform="apollo" and source_type="apollo"', () => {
        const mapped = apolloUtils.mapApolloLeadToCrmPayload({
            apollo_id: 'ap_lead_101',
            first_name: 'Marcus',
            last_name: 'Vance',
            job_title: 'Operations Director',
            company: 'Apex Precision Manufacturing',
            industry: 'Manufacturing & Industrial',
            location: 'Sydney, Australia',
            company_size: '51-200',
            email: 'marcus.vance@apexprecision.io',
            phone: '+61 2 9012 4480',
            linkedin_url: '@marcus-vance-ops'
        });

        assert.equal(mapped.platform, 'apollo');
        assert.equal(mapped.source_type, 'apollo');
        assert.equal(mapped.first_name, 'Marcus');
        assert.equal(mapped.last_name, 'Vance');
        assert.equal(mapped.email_address, 'marcus.vance@apexprecision.io');
        assert.equal(mapped.contact_number, '+61 2 9012 4480');
        assert.equal(mapped.category, 'Hot Prospect');
        assert.ok(mapped.company.includes('Apex Precision Manufacturing'));
        assert.ok(mapped.company.includes('Operations Director'));
        assert.ok(mapped.notes.includes('Saved from Apollo.io B2B Lead Finder'));
    });

    it('distinguishes Apollo.io platform sources alongside existing CRM platforms', () => {
        const apolloOnly = apolloUtils.extractContactPlatformSources({
            platform: 'apollo',
            source_type: 'apollo'
        });
        assert.deepEqual(apolloOnly, ['apollo']);

        const combined = apolloUtils.extractContactPlatformSources({
            platform: 'apollo',
            source_type: 'apollo,gmail,whatsapp'
        });
        assert.deepEqual(combined, ['apollo', 'gmail', 'whatsapp']);
    });

    it('builds a personalized cold outreach email draft for the Email Modal', () => {
        const draft = apolloUtils.buildColdOutreachEmailDraft({
            first_name: 'Elena',
            company: 'NovaCloud SaaS',
            job_title: 'CEO & Co-Founder',
            industry: 'SaaS & Software'
        });
        assert.ok(draft.subject.includes('NovaCloud SaaS'));
        assert.ok(draft.body.includes('Hi Elena,'));
        assert.ok(draft.body.includes('CEO & Co-Founder'));
    });
});
