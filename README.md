# GlennBot Automations (Modular Architecture)

Full-stack social media scheduling, unified inbox, comments, analytics, multi-platform email hub, CRM, Google Drive vault, spreadsheet sync, calendar/meetings hub, and visual n8n workflow automation platform.

- **AI Studio Workspace**: https://ai.studio/apps/ed1f999a-2991-45d0-914c-3bd76f0a0307
- **Local Run Command**: `python main.py` (runs FastAPI + Uvicorn on `http://localhost:5001`)

---

## Complete Modular Folder Map (All Files < 2,850 Lines)

```text
glennbot-automations/
├── main.py                                    # FastAPI entry point, middleware, APScheduler init, router mounts
├── requirements.txt                           # Python dependencies
├── .env.example                               # Environment variable template (keep actual .env local only)
├── core/
│   ├── config.py                              # Environment variables, constants, dynamic URL helpers (433 lines)
│   └── database.py                            # SQLAlchemy engine, init_records_db(), APScheduler setup (641 lines)
├── services/
│   ├── gdrive_service.py                      # Google Drive API v3 OAuth & media storage (444 lines)
│   ├── cloudinary_service.py                  # Cloudinary config, API key pool, comments & messages store (617 lines)
│   ├── zernio_service.py                      # Zernio presigned upload, post publishing & account discovery (2,292 lines)
│   └── ai_service.py                          # Gemini 3.5 Flash Ask AI & web search helpers (420 lines)
├── routers/
│   ├── health.py                              # /health, /ping, /api/health (18 lines)
│   ├── auth_and_keys.py                       # Manage API keys, OAuth popups & connected accounts (932 lines)
│   ├── ai_routes.py                           # /api/ai/ask & /api/v1/ai/ask (49 lines)
│   ├── scheduler_routes.py                    # Custom presets, scheduled posts & chunked video upload (1,961 lines)
│   ├── comments_routes.py                     # Post-matched comments sync & Cloudinary notifications (2,476 lines)
│   ├── comment_actions_routes.py              # Get/reply/private-DM/like/hide comment endpoints (2,147 lines)
│   ├── messages_routes.py                     # Unified Inbox & Direct Messages engine (2,852 lines)
│   ├── sms_routes.py                          # TextBee.dev SMS Gateway integration (1,287 lines)
│   ├── webhooks_routes.py                     # Instant webhook receiver for Comments, DMs & SMS (1,227 lines)
│   ├── analytics_routes.py                    # Social media analytics engine (1,231 lines)
│   ├── email_accounts_routes.py               # Composio Email OAuth, IMAP/SMTP & inbox fetching (2,124 lines)
│   ├── email_send_webhooks_routes.py          # Email send, reply, trash, attachments & real-time webhook (1,503 lines)
│   ├── contacts_routes.py                     # Client Contacts & Lead CRM + Google Contacts OAuth2 (1,863 lines)
│   ├── internal_api_routes.py                 # GlennBot Internal REST API (v1) & n8n dispatcher core (1,956 lines)
│   ├── settings_rbac_routes.py                # Login Gate, RBAC, User Settings, Theme Store & Internal API GUI (2,394 lines)
│   ├── automations_routes.py                  # Visual Automations Canvas, native n8n engine & /api/v1/* (2,590 lines)
│   ├── files_routes.py                        # Google Drive File Vault & live stream proxy (1,251 lines)
│   ├── spreadsheet_routes.py                  # Custom Spreadsheet (.xlsx) two-way sync & /api/v1/spreadsheets/* (2,575 lines)
│   ├── calendar_sync_routes.py                # Composio Calendar OAuth, discovery & event sync (1,898 lines)
│   └── calendar_booking_routes.py             # Schedule/reschedule/cancel meetings, /api/v1/calendar/* & startup poller (2,202 lines)
├── static/
│   ├── css/
│   │   └── style.css                          # Custom CSS for Default, Dark & Light themes (370 lines)
│   └── js/
│       ├── app_core.js                        # Global state, user settings, modals, API pool, presets, Ask AI, navigation (1,790 lines)
│       ├── app_calendar_queue.js              # Dual-tab Calendar, Composio meetings popup, scheduled posts & Queue (1,447 lines)
│       ├── app_comments_inbox.js              # Comments & Notifications Hub + Unified Inbox & Direct Messages UI (2,326 lines)
│       ├── app_post_media.js                  # Create Post media upload, preview & chunked upload UI (885 lines)
│       ├── app_accounts_analytics.js          # Connect & Manage Social Accounts + Social Media Analytics UI (2,402 lines)
│       ├── app_email.js                       # Client Email Command Center & expanded email reader UI (1,964 lines)
│       ├── app_contacts_crm.js                # Contacts & Lead CRM + Google Contacts import + real-time email alerts (1,607 lines)
│       ├── app_internal_api_n8n.js            # Internal REST API (v1) & Ask AI n8n Workflow Architect UI (1,657 lines)
│       ├── app_files_sheets_sms.js            # Files Vault, Spreadsheet editor, Login Gate RBAC & TextBee SMS UI (2,211 lines)
│       └── app_automations.js                 # View 11: Automations Visual Canvas & native n8n JSON editor UI (1,785 lines)
└── templates/
    ├── index.html                             # Master Jinja2 HTML template
    └── partials/
        ├── header_nav.html                    # Top header bar & collapsible left sidebar (143 lines)
        ├── modals.html                        # Master modal include file (3 lines)
        ├── modals_auth_api_n8n.html           # Login Gate, Settings, API Manager, Internal API & AI Architect modals (1,056 lines)
        ├── modals_post_social_calendar.html   # Private DM, Media Source, Ask AI Caption, Presets, Social OAuth modals (506 lines)
        ├── modals_meetings_email_crm_sms.html # Meeting Schedule/Reschedule/Cancel, Email, CRM Contact & SMS modals (987 lines)
        ├── view_scheduler.html                # Tab 1: Create Post (125 lines)
        ├── view_calendar.html                 # Tab 2: Calendar (119 lines)
        ├── view_queue.html                    # Tab 3: Queue (25 lines)
        ├── view_messages.html                 # Tab 4: Unified Inbox & Direct Messages (100 lines)
        ├── view_comments.html                 # Tab 5: Comments & Notifications (92 lines)
        ├── view_analytics.html                # Tab 6: Social Media Analytics (99 lines)
        ├── view_email.html                    # View 7: Client Email Command Center (226 lines)
        ├── view_contacts.html                 # View 8: Contacts & Lead CRM (136 lines)
        ├── view_files.html                    # View 9: Files Vault (122 lines)
        ├── view_spreadsheet.html              # View 10: Spread Sheet (137 lines)
        └── view_automations.html              # View 11: Automations Visual Canvas (450 lines)
```

---

## Zero-Regression Rules for AI Coding Assistants
1. **No Placeholders**: Every file is small enough (<2,850 lines) to be edited completely without truncation or `# ... rest of code ...` placeholders.
2. **APScheduler Compatibility**: Keep `sys.modules.setdefault("main", sys.modules[__name__])` and the re-exported job functions in `main.py`.
3. **Global JS Scope**: All `<script src="/static/js/app_*.js">` tags in `templates/index.html` run in classic global scope (`window`) so inline HTML event handlers (`onclick="..."`) always work.
