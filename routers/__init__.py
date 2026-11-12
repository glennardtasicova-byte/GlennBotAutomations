# GlennBot Automations - FastAPI Routers Package
import io
import pytz
from typing import Any


def bind_all_router_globals(app_instance: Any = None, templates_instance: Any = None) -> None:
    """
    Synchronizes top-level helper functions, Pydantic models, locks, and state dictionaries
    across all modular `routers/*.py` modules (plus `services/*` and `core/*`).
    Ensures cross-router calls and `if "..._helper" in globals():` checks always succeed
    identically to the unified single-module runtime.
    """
    from routers import (
        health,
        auth_and_keys,
        scheduler_routes,
        comments_routes,
        messages_routes,
        sms_routes,
        webhooks_routes,
        comment_actions_routes,
        analytics_routes,
        email_accounts_routes,
        email_send_webhooks_routes,
        contacts_routes,
        internal_api_routes,
        settings_rbac_routes,
        automations_routes,
        files_routes,
        spreadsheet_routes,
        calendar_sync_routes,
        calendar_booking_routes,
        ai_routes,
    )

    router_modules = [
        health,
        auth_and_keys,
        scheduler_routes,
        comments_routes,
        messages_routes,
        sms_routes,
        webhooks_routes,
        comment_actions_routes,
        analytics_routes,
        email_accounts_routes,
        email_send_webhooks_routes,
        contacts_routes,
        internal_api_routes,
        settings_rbac_routes,
        automations_routes,
        files_routes,
        spreadsheet_routes,
        calendar_sync_routes,
        calendar_booking_routes,
        ai_routes,
    ]

    shared_symbols = {
        "io": io,
        "manila_tz": pytz.timezone("Asia/Manila"),
    }
    if app_instance is not None:
        shared_symbols["app"] = app_instance
    if templates_instance is not None:
        shared_symbols["templates"] = templates_instance

    skip_names = {
        "router",
        "__name__",
        "__doc__",
        "__package__",
        "__loader__",
        "__spec__",
        "__file__",
        "__cached__",
        "__builtins__",
    }

    for mod in router_modules:
        for k, v in mod.__dict__.items():
            if k in skip_names or k.startswith("__"):
                continue
            shared_symbols[k] = v

    # Ensure explicit cross-router aliases are always registered
    try:
        import openpyxl as _openpyxl_mod
        shared_symbols.setdefault("openpyxl", _openpyxl_mod)
    except Exception:
        pass
    if "_save_internal_api_to_cloudinary" in shared_symbols:
        shared_symbols.setdefault("_save_internal_api_state", shared_symbols["_save_internal_api_to_cloudinary"])
    if "_save_spreadsheets_store" in shared_symbols:
        shared_symbols.setdefault("save_spreadsheets_store_async", shared_symbols["_save_spreadsheets_store"])
    if "_discover_composio_email_accounts" in shared_symbols:
        shared_symbols.setdefault("_auto_discover_composio_email_accounts", shared_symbols["_discover_composio_email_accounts"])
    if "_load_crm_contacts_state" in shared_symbols:
        shared_symbols.setdefault("_load_crm_contacts_store", shared_symbols["_load_crm_contacts_state"])

    for mod in router_modules:
        for k, v in shared_symbols.items():
            if k not in mod.__dict__:
                mod.__dict__[k] = v
