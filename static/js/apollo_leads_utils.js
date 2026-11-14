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
            'VP of Sales',
            'Software Engineer',
            'Product Manager',
            'E-Commerce Manager',
            'Head of Growth'
        ],
        popularCompanies: [
            { name: 'Google', domain: 'google.com', industry: 'SaaS & Software', size: '10,000+' },
            { name: 'Apple', domain: 'apple.com', industry: 'Consumer Electronics & Tech', size: '10,000+' },
            { name: 'Microsoft', domain: 'microsoft.com', industry: 'SaaS & Software', size: '10,000+' },
            { name: 'Amazon', domain: 'amazon.com', industry: 'E-Commerce & Cloud', size: '10,000+' },
            { name: 'Stripe', domain: 'stripe.com', industry: 'Financial Services & FinTech', size: '5,001-10,000' },
            { name: 'Shopify', domain: 'shopify.com', industry: 'E-Commerce & Retail', size: '5,001-10,000' },
            { name: 'HubSpot', domain: 'hubspot.com', industry: 'Marketing & SaaS', size: '5,001-10,000' },
            { name: 'Salesforce', domain: 'salesforce.com', industry: 'SaaS & Software', size: '10,000+' },
            { name: 'Canva', domain: 'canva.com', industry: 'SaaS & Design', size: '1,001-5,000' },
            { name: 'Atlassian', domain: 'atlassian.com', industry: 'SaaS & Software', size: '5,001-10,000' }
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
            { value: 'All Industries', label: 'All Industries' },
            { value: 'SaaS & Software', label: 'SaaS & Computer Software' },
            { value: 'E-Commerce & Retail', label: 'E-Commerce & Internet Retail' },
            { value: 'Financial Services & FinTech', label: 'Financial Services & FinTech' },
            { value: 'Marketing & Advertising', label: 'Marketing & Advertising' },
            { value: 'Manufacturing & Industrial', label: 'Manufacturing & Industrial' },
            { value: 'Real Estate & Property', label: 'Real Estate & Property' },
            { value: 'Logistics & Supply Chain', label: 'Logistics & Supply Chain' },
            { value: 'Healthcare & Medical', label: 'Healthcare & Medical' },
            { value: 'Construction & Engineering', label: 'Construction & Engineering' }
        ],
        seniorities: [
            { value: 'all', label: 'All Seniority Levels' },
            { value: 'founder_owner', label: 'Founder / Owner' },
            { value: 'c_suite', label: 'C-Suite (CEO, COO, CTO, CFO, CMO)' },
            { value: 'vp', label: 'VP / Vice President' },
            { value: 'director', label: 'Director / Head' },
            { value: 'manager', label: 'Manager / Team Lead' },
            { value: 'senior', label: 'Senior IC / Specialist' }
        ],
        departments: [
            { value: 'all', label: 'All Departments' },
            { value: 'executive', label: 'Executive & Leadership' },
            { value: 'sales', label: 'Sales & Business Development' },
            { value: 'marketing', label: 'Marketing & Growth' },
            { value: 'operations', label: 'Operations & Logistics' },
            { value: 'engineering', label: 'Engineering & Technical' },
            { value: 'product', label: 'Product Management' },
            { value: 'finance', label: 'Finance & Accounting' },
            { value: 'hr', label: 'Human Resources & Talent' },
            { value: 'it', label: 'Information Technology' }
        ],
        companySizes: [
            { value: 'any', label: 'Any Headcount' },
            { value: '1-10', label: '1–10 Employees' },
            { value: '11-50', label: '11–50 Employees' },
            { value: '51-200', label: '51–200 Employees' },
            { value: '201-1000', label: '201–1,000 Employees' },
            { value: '1001-5000', label: '1,001–5,000 Employees' },
            { value: '5001-10000', label: '5,001–10,000 Employees' },
            { value: '10000+', label: '10,000+ Employees (Enterprise)' }
        ],
        emailStatuses: [
            { value: 'verified', label: 'Verified Emails Only' },
            { value: 'likely_to_engage', label: 'Verified + Likely to Engage' },
            { value: 'all', label: 'All Email Statuses' }
        ],
        revenues: [
            { value: 'any', label: 'Any Annual Revenue' },
            { value: '<$1M', label: 'Under $1M' },
            { value: '$1M-$10M', label: '$1M – $10M' },
            { value: '$10M-$50M', label: '$10M – $50M' },
            { value: '$50M-$100M', label: '$50M – $100M' },
            { value: '$100M-$500M', label: '$100M – $500M' },
            { value: '$500M-$1B', label: '$500M – $1B' },
            { value: '$1B+', label: '$1B+ (Enterprise)' }
        ],
        fundingStages: [
            { value: 'any', label: 'Any Funding Stage' },
            { value: 'Seed', label: 'Seed / Pre-Seed' },
            { value: 'Series A', label: 'Series A' },
            { value: 'Series B', label: 'Series B' },
            { value: 'Series C+', label: 'Series C / Late Stage' },
            { value: 'Public / IPO', label: 'Public / IPO' },
            { value: 'Bootstrapped', label: 'Bootstrapped / Private' }
        ],
        technologies: [
            'Salesforce',
            'HubSpot',
            'AWS',
            'Google Cloud',
            'Shopify',
            'Stripe',
            'React',
            'Python',
            'Snowflake',
            'Microsoft Azure',
            'Kubernetes',
            'Slack'
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

    const VALID_B2B_ROLE_KEYWORDS = [
        'ceo', 'cfo', 'coo', 'cto', 'cmo', 'cro', 'cio', 'ciso', 'cpo', 'chief',
        'founder', 'cofounder', 'co-founder', 'owner', 'partner', 'principal', 'president',
        'vp', 'vice president', 'director', 'head', 'manager', 'lead', 'supervisor',
        'engineer', 'developer', 'programmer', 'architect', 'scientist', 'devops', 'sre', 'qa',
        'product', 'designer', 'ux', 'ui', 'researcher', 'analyst', 'associate', 'specialist',
        'consultant', 'advisor', 'coordinator', 'administrator', 'admin', 'executive', 'officer',
        'sales', 'account', 'business development', 'bdr', 'sdr', 'revenue', 'commercial',
        'marketing', 'growth', 'brand', 'content', 'seo', 'media', 'communications', 'pr',
        'operations', 'ops', 'supply chain', 'logistics', 'procurement', 'purchasing', 'fulfillment',
        'finance', 'accounting', 'controller', 'treasurer', 'audit', 'tax', 'investment',
        'hr', 'human resources', 'talent', 'recruiter', 'recruiting', 'people', 'payroll',
        'it', 'information technology', 'security', 'cybersecurity', 'network', 'systems', 'cloud', 'data', 'ai',
        'legal', 'counsel', 'attorney', 'compliance', 'risk',
        'customer', 'support', 'success', 'service', 'client',
        'ecommerce', 'e-commerce', 'retail', 'merchandising', 'store',
        'real estate', 'broker', 'agent', 'property', 'leasing',
        'medical', 'healthcare', 'clinical', 'physician', 'doctor', 'nurse', 'pharmacy',
        'construction', 'civil', 'project', 'program', 'manufacturing', 'plant', 'quality', 'safety'
    ];

    const BLOCKED_NON_B2B_TERMS = [
        'porn', 'xxx', 'nsfw', 'onlyfans', 'adult entertainer', 'stripper', 'escort', 'hentai', 'sex worker'
    ];

    function validateApolloB2BRoleOrQuery(rawTitle) {
        const clean = String(rawTitle || '').trim().toLowerCase();
        if (!clean || clean === 'all' || clean === 'any') {
            return { valid: true, normalized: '' };
        }
        for (const blocked of BLOCKED_NON_B2B_TERMS) {
            if (clean.includes(blocked)) {
                return {
                    valid: false,
                    reason: `No verified B2B decision-makers or corporate roles matched "${rawTitle}" in the Apollo.io database.`
                };
            }
        }
        const matchesKnownB2B = VALID_B2B_ROLE_KEYWORDS.some(kw => clean.includes(kw));
        if (!matchesKnownB2B) {
            return {
                valid: false,
                reason: `No verified B2B job titles matched "${rawTitle}" in the Apollo.io professional taxonomy. Try roles like CEO, Software Engineer, Marketing Director, or VP of Sales.`
            };
        }
        return { valid: true, normalized: String(rawTitle).trim() };
    }

    function normalizeApolloSearchFilters(rawFilters) {
        const f = rawFilters && typeof rawFilters === 'object' ? rawFilters : {};
        const search_type = String(f.search_type || 'people').trim().toLowerCase() === 'companies' ? 'companies' : 'people';
        const hasExplicitJobTitle = Object.prototype.hasOwnProperty.call(f, 'job_title');
        const job_title = hasExplicitJobTitle
            ? String(f.job_title || '').trim()
            : 'CEO / Founder';
        const company = String(f.company || '').trim();
        const location = String(f.location || '').trim() || 'United States';
        const industry = String(f.industry || '').trim() || 'SaaS & Software';
        const seniority = String(f.seniority || 'all').trim().toLowerCase() || 'all';
        const department = String(f.department || 'all').trim().toLowerCase() || 'all';
        const company_size = String(f.company_size || 'any').trim() || 'any';
        const email_status = String(f.email_status || 'verified').trim().toLowerCase() || 'verified';
        const revenue = String(f.revenue || 'any').trim() || 'any';
        const funding_stage = String(f.funding_stage || 'any').trim() || 'any';
        const technology = String(f.technology || '').trim();
        const keyword = String(f.keyword || '').trim();
        const verified_email_only = f.verified_email_only !== false && email_status !== 'all';

        return {
            search_type,
            job_title,
            company,
            location,
            industry,
            seniority,
            department,
            company_size,
            email_status,
            revenue,
            funding_stage,
            technology,
            keyword,
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
        validateApolloB2BRoleOrQuery,
        normalizeApolloSearchFilters,
        mapApolloLeadToCrmPayload,
        buildColdOutreachEmailDraft,
        extractContactPlatformSources
    };
});
