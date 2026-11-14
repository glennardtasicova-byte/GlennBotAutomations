import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import apolloUtils from '../static/js/apollo_leads_utils.js';

describe('GlennBotApolloUtils', () => {
    it('normalizes basic and advanced Apollo.io search filters for People & Companies', () => {
        const defaults = apolloUtils.normalizeApolloSearchFilters({});
        assert.equal(defaults.search_type, 'people');
        assert.equal(defaults.job_title, 'CEO / Founder');
        assert.equal(defaults.company, '');
        assert.equal(defaults.location, 'United States');
        assert.equal(defaults.industry, 'SaaS & Software');
        assert.equal(defaults.seniority, 'all');
        assert.equal(defaults.department, 'all');
        assert.equal(defaults.company_size, 'any');
        assert.equal(defaults.verified_email_only, true);

        const companySearch = apolloUtils.normalizeApolloSearchFilters({
            search_type: 'companies',
            job_title: '',
            company: 'Google',
            location: 'United States',
            industry: 'SaaS & Software',
            company_size: '10000+',
            revenue: '$1B+',
            funding_stage: 'Public / IPO',
            technology: 'Google Cloud'
        });
        assert.equal(companySearch.search_type, 'companies');
        assert.equal(companySearch.company, 'Google');
        assert.equal(companySearch.company_size, '10000+');
        assert.equal(companySearch.revenue, '$1B+');
        assert.equal(companySearch.funding_stage, 'Public / IPO');
        assert.equal(companySearch.technology, 'Google Cloud');
    });

    it('strictly validates B2B job titles and rejects non-B2B or inappropriate roles', () => {
        const validCeo = apolloUtils.validateApolloB2BRoleOrQuery('CEO / Founder');
        assert.equal(validCeo.valid, true);

        const validEng = apolloUtils.validateApolloB2BRoleOrQuery('Senior Software Engineer');
        assert.equal(validEng.valid, true);

        const blockedRole = apolloUtils.validateApolloB2BRoleOrQuery('Porn Star');
        assert.equal(blockedRole.valid, false);

        const gibberishRole = apolloUtils.validateApolloB2BRoleOrQuery('zxcvbnm12345');
        assert.equal(gibberishRole.valid, false);
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
