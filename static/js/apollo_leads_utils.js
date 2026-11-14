(function (root, factory) {
    if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.GlennBotApolloUtils = factory();
    }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const APOLLO_FILTER_OPTIONS = {
        popularTitles: [
            'CEO / Founder',
            'Operations Director',
            'Marketing Director',
            'E-Commerce Manager',
            'Sales Director',
            'Real Estate Broker',
            'Supply Chain Manager',
            'Head of Growth'
        ],
        locations: [
            { value: 'United States', label: 'United States' },
            { value: 'Australia', label: 'Australia' },
            { value: 'United Kingdom', label: 'United Kingdom' },
            { value: 'Canada', label: 'Canada' },
            { value: 'Singapore', label: 'Singapore' },
            { value: 'United Arab Emirates', label: 'United Arab Emirates (Dubai)' },
            { value: 'Philippines', label: 'Philippines' },
            { value: 'Germany', label: 'Germany' },
            { value: 'Netherlands', label: 'Netherlands' },
            { value: 'New Zealand', label: 'New Zealand' },
            { value: 'Global', label: 'Global / Any Country' }
        ],
        industries: [
            { value: 'SaaS & Software', label: 'SaaS & Software' },
            { value: 'E-Commerce & Retail', label: 'E-Commerce & Retail' },
            { value: 'Manufacturing & Industrial', label: 'Manufacturing & Industrial' },
            { value: 'Real Estate & Property', label: 'Real Estate & Property' },
            { value: 'Marketing & Advertising', label: 'Marketing & Advertising Agency' },
            { value: 'Logistics & Supply Chain', label: 'Logistics & Supply Chain' },
            { value: 'Healthcare & Medical', label: 'Healthcare & Medical' },
            { value: 'Financial Services & FinTech', label: 'Financial Services & FinTech' },
            { value: 'Construction & Engineering', label: 'Construction & Engineering' }
        ],
        seniorities: [
            { value: 'all', label: 'All Decision Makers' },
            { value: 'founder_owner', label: 'Founder / Owner' },
            { value: 'c_suite', label: 'C-Suite (CEO, COO, CTO, CFO)' },
            { value: 'vp', label: 'VP / Vice President' },
            { value: 'director', label: 'Director / Head' },
            { value: 'manager', label: 'Manager / Team Lead' }
        ],
        companySizes: [
            { value: 'any', label: 'Any Company Size' },
            { value: '1-10', label: '1–10 Employees (Startup)' },
            { value: '11-50', label: '11–50 Employees (Small Business)' },
            { value: '51-200', label: '51–200 Employees (Mid-Market)' },
            { value: '201-1000', label: '201–1,000+ Employees (Enterprise)' }
        ]
    };

    const KNOWN_CRM_PLATFORMS = [
        'apollo',
        'facebook',
        'instagram',
        'tiktok',
        'youtube',
        'whatsapp',
        'telegram',
        'gmail',
        'microsoft',
        'imap',
        'google_contacts',
        'sms',
        'textbee',
        'manual'
    ];

    function normalizeApolloSearchFilters(rawFilters) {
        const f = rawFilters && typeof rawFilters === 'object' ? rawFilters : {};
        const job_title = String(f.job_title || '').trim() || 'CEO / Founder';
        const location = String(f.location || '').trim() || 'United States';
        const industry = String(f.industry || '').trim() || 'SaaS & Software';
        const seniority = String(f.seniority || 'all').trim().toLowerCase() || 'all';
        const company_size = String(f.company_size || 'any').trim() || 'any';
        const verified_email_only = f.verified_email_only !== false;

        return {
            job_title,
            location,
            industry,
            seniority,
            company_size,
            verified_email_only
        };
    }

    function mapApolloLeadToCrmPayload(lead) {
        const l = lead && typeof lead === 'object' ? lead : {};
        const firstName = String(l.first_name || '').trim();
        const lastName = String(l.last_name || '').trim();
        const fullTitle = String(l.job_title || l.title || '').trim();
        const companyName = String(l.company || l.organization_name || '').trim();
        const industry = String(l.industry || '').trim();
        const location = String(l.location || l.country || '').trim();
        const companySize = String(l.company_size || l.employees_range || '').trim();
        const linkedinUrl = String(l.linkedin_url || l.linkedin_handle || '').trim();
        const email = String(l.email || l.email_address || '').trim().toLowerCase();
        const phone = String(l.phone || l.contact_number || '').trim();

        const companyField = companyName && fullTitle
            ? `${companyName} (${fullTitle})`
            : (companyName || fullTitle);

        const noteParts = ['Saved from Apollo.io B2B Lead Finder'];
        if (fullTitle) noteParts.push(`Role: ${fullTitle}`);
        if (industry) noteParts.push(`Industry: ${industry}`);
        if (location) noteParts.push(`Location: ${location}`);
        if (companySize && companySize !== 'any') noteParts.push(`Size: ${companySize} employees`);
        if (linkedinUrl) noteParts.push(`LinkedIn: ${linkedinUrl}`);

        return {
            id: '',
            first_name: firstName,
            middle_name: '',
            last_name: lastName,
            contact_number: phone,
            email_address: email,
            platform: 'apollo',
            social_username: linkedinUrl || (email ? email.split('@')[0] : ''),
            account_name: 'Apollo.io Lead Finder',
            category: 'Hot Prospect',
            company: companyField,
            notes: noteParts.join(' • '),
            source_type: 'apollo',
            source_ref_id: String(l.apollo_id || l.id || email || ''),
            avatar_url: String(l.avatar_url || '')
        };
    }

    function buildColdOutreachEmailDraft(lead) {
        const l = lead && typeof lead === 'object' ? lead : {};
        const firstName = String(l.first_name || 'there').trim();
        const company = String(l.company || l.organization_name || 'your team').trim();
        const role = String(l.job_title || l.title || 'leadership').trim();
        const industry = String(l.industry || 'operations').trim();

        const subject = `Quick question regarding ${company}'s ${industry.toLowerCase()} workflows`;
        const body = [
            `Hi ${firstName},`,
            ``,
            `I came across ${company} while researching leaders in ${industry} and noticed your role as ${role}.`,
            ``,
            `We help growing teams eliminate repetitive manual work across lead triage, social publishing, CRM syncing, and automated follow-ups using custom AI & workflow pipelines.`,
            ``,
            `Would you be open to a quick 10-minute chat this week to see if a tailored automation pipeline could save your team 15+ hours a week?`,
            ``,
            `Best regards,`,
            `Glennard Tasico`
        ].join('\n');

        return { subject, body };
    }

    function extractContactPlatformSources(contact) {
        const c = contact && typeof contact === 'object' ? contact : {};
        const raw = `${c.platform || 'manual'},${c.source_type || ''}`
            .split(',')
            .map(s => s.trim().toLowerCase())
            .filter(s => KNOWN_CRM_PLATFORMS.includes(s));
        const unique = Array.from(new Set(raw));
        return unique.length > 0 ? unique : ['manual'];
    }

    return {
        APOLLO_FILTER_OPTIONS,
        KNOWN_CRM_PLATFORMS,
        normalizeApolloSearchFilters,
        mapApolloLeadToCrmPayload,
        buildColdOutreachEmailDraft,
        extractContactPlatformSources
    };
});
