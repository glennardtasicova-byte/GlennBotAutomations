import csv
import io
import re
from typing import Any, Dict, List, Optional, Tuple


APOLLO_VALID_CATEGORIES = (
    "New Lead",
    "Hot Prospect",
    "Active Client",
    "VIP",
    "Inquirer",
    "Follow-Up",
    "Partner",
)


def clean_apollo_phone(raw_phone: Any) -> str:
    """
    Cleans phone numbers exported from Apollo CSV (e.g. Column T 'Corporate Phone').
    Apollo prefixes phone numbers with a single quote like "'+1 415-420-6461"
    to prevent spreadsheet formula evaluation.
    """
    if raw_phone is None:
        return ""
    s = str(raw_phone).strip()
    # Strip leading/trailing single quotes, double quotes, backticks, and whitespace
    s = s.lstrip("'‘’`\"").rstrip("'‘’`\"").strip()
    if not s or s.lower() in ("none", "null", "n/a", "na", "-"):
        return ""
    return s


def determine_apollo_lead_category(
    title: str = "",
    seniority: str = "",
    email_status: str = "",
    stage: str = "",
    category_override: str = "auto",
) -> str:
    """
    Determines the most appropriate CRM Lead Status / Category for an Apollo CSV row.
    Supported CRM categories:
      - Hot Prospect: Verified C-Suite, VP, Head, Director, Founder, Manager, Recruiter, or Senior decision-makers
      - Active Client: Stage indicates Active / Client / Customer / Won
      - Follow-Up: Stage indicates Warm / Follow-Up / Replied / Contacted
      - Partner: Partner / Alliance roles
      - New Lead: Standard / Entry / Cold leads
    """
    override_clean = (category_override or "").strip()
    if override_clean and override_clean.lower() != "auto":
        for valid_cat in APOLLO_VALID_CATEGORIES:
            if valid_cat.lower() == override_clean.lower():
                return valid_cat

    t_low = (title or "").strip().lower()
    s_low = (seniority or "").strip().lower()
    e_low = (email_status or "").strip().lower()
    st_low = (stage or "").strip().lower()

    if any(k in st_low for k in ("active", "client", "customer", "won", "closed won")):
        return "Active Client"
    if any(k in st_low for k in ("follow", "warm", "replied", "engaged", "meeting", "interested")):
        return "Follow-Up"

    is_verified = e_low in ("verified", "valid", "deliverable", "")
    high_seniority = s_low in (
        "c suite",
        "c-suite",
        "cxo",
        "vp",
        "vice president",
        "head",
        "director",
        "founder",
        "owner",
        "partner",
        "manager",
    )
    high_value_title = bool(
        re.search(
            r"\b(ceo|cto|cfo|coo|cmo|cio|chief|vp|vice president|president|founder|co-founder|owner|director|head|manager|lead|principal|recruiter|talent|hr)\b",
            t_low,
        )
    )

    if is_verified and (high_seniority or high_value_title):
        return "Hot Prospect"

    return "New Lead"


def _decode_csv_bytes(csv_bytes: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return csv_bytes.decode(enc)
        except Exception:
            continue
    return csv_bytes.decode("utf-8", errors="replace")


def _safe_cell(row: List[str], idx: Optional[int]) -> str:
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    return str(row[idx] or "").strip()


def parse_apollo_csv_bytes(
    csv_bytes: bytes,
    source_filename: str = "apollo-contacts-export.csv",
    file_id: str = "",
    category_override: str = "auto",
) -> Dict[str, Any]:
    """
    Parses an Apollo CSV file according to the user's specification:
      - Column E (index 4): Company Name ('Company Name for Emails', fallback Col D 'Company Name')
      - Column F (index 5): Email Address ('Email')
      - Column T (index 19): Contact Number ('Corporate Phone', fallback Work/Mobile phone if Col T is blank)
      - Column A (index 0) & Column B (index 1): First Name & Last Name
      - Lead Status / Category: Auto-determined via determine_apollo_lead_category()
    """
    if not csv_bytes:
        return {
            "rows_parsed": 0,
            "contacts": [],
            "skipped_rows": 0,
            "column_mapping": {
                "company_col": "Column E (Company Name for Emails)",
                "email_col": "Column F (Email)",
                "phone_col": "Column T (Corporate Phone)",
            },
        }

    text = _decode_csv_bytes(csv_bytes)
    reader = csv.reader(io.StringIO(text))
    all_rows = [r for r in reader if any(str(cell or "").strip() for cell in r)]
    if not all_rows:
        return {
            "rows_parsed": 0,
            "contacts": [],
            "skipped_rows": 0,
            "column_mapping": {
                "company_col": "Column E (Company Name for Emails)",
                "email_col": "Column F (Email)",
                "phone_col": "Column T (Corporate Phone)",
            },
        }

    # Default fixed Apollo CSV indices requested by user:
    # Col A = 0 (First Name), Col B = 1 (Last Name), Col C = 2 (Title), Col D = 3 (Company Name),
    # Col E = 4 (Company Name for Emails), Col F = 5 (Email), Col G = 6 (Email Status),
    # Col M = 12 (Seniority), Col Q = 16 (Work Direct Phone), Col S = 18 (Mobile Phone),
    # Col T = 19 (Corporate Phone), Col W = 22 (Stage), Col AD = 29 (Person Linkedin Url)
    first_row_lower = [str(c or "").strip().lower() for c in all_rows[0]]
    has_header = any(
        h in first_row_lower
        for h in (
            "first name",
            "last name",
            "email",
            "company name for emails",
            "company name",
            "corporate phone",
        )
    )

    data_rows = all_rows[1:] if has_header else all_rows

    # Always prioritize Column E (index 4), Column F (index 5), Column T (index 19)
    # when the row has standard Apollo columns, with header lookup fallback for custom exports
    header_map: Dict[str, int] = {}
    if has_header:
        for idx, col_name in enumerate(first_row_lower):
            if col_name and col_name not in header_map:
                header_map[col_name] = idx

    col_first_name = header_map.get("first name", 0)
    col_last_name = header_map.get("last name", 1)
    col_title = header_map.get("title", 2)
    col_company_d = header_map.get("company name", 3)
    col_company_e = 4 if len(all_rows[0]) > 4 else header_map.get("company name for emails", col_company_d)
    col_email_f = 5 if len(all_rows[0]) > 5 else header_map.get("email", 5)
    col_email_status = header_map.get("email status", 6)
    col_seniority = header_map.get("seniority", 12)
    col_work_phone = header_map.get("work direct phone", 16)
    col_mobile_phone = header_map.get("mobile phone", 18)
    col_corp_phone_t = 19 if len(all_rows[0]) > 19 else header_map.get("corporate phone", 19)
    col_stage = header_map.get("stage", 22)
    col_linkedin = header_map.get("person linkedin url", 29)
    col_city = header_map.get("city", 33)
    col_country = header_map.get("country", 35)

    parsed_contacts: List[Dict[str, Any]] = []
    skipped_rows = 0
    clean_source_name = str(source_filename or "apollo-contacts-export.csv").strip()

    for row_idx, row in enumerate(data_rows, start=2 if has_header else 1):
        # Column E -> Company Name (fallback to Column D if Column E is empty)
        company_name = _safe_cell(row, col_company_e) or _safe_cell(row, col_company_d)
        # Column F -> Email Address
        email_address = _safe_cell(row, col_email_f).lower()
        # Column T -> Contact Number (fallback to Work Direct Phone / Mobile Phone if Col T is empty)
        raw_col_t_phone = _safe_cell(row, col_corp_phone_t)
        contact_number = clean_apollo_phone(raw_col_t_phone)
        if not contact_number:
            contact_number = (
                clean_apollo_phone(_safe_cell(row, col_mobile_phone))
                or clean_apollo_phone(_safe_cell(row, col_work_phone))
            )

        first_name = _safe_cell(row, col_first_name)
        last_name = _safe_cell(row, col_last_name)
        title = _safe_cell(row, col_title)
        email_status = _safe_cell(row, col_email_status)
        seniority = _safe_cell(row, col_seniority)
        stage = _safe_cell(row, col_stage)
        linkedin_url = _safe_cell(row, col_linkedin)
        city = _safe_cell(row, col_city)
        country = _safe_cell(row, col_country)

        # Skip completely blank rows
        if not any([first_name, last_name, company_name, email_address, contact_number]):
            skipped_rows += 1
            continue

        # If First Name is missing on an Apollo row, derive a readable name from email or company
        if not first_name and not last_name:
            if email_address and "@" in email_address:
                local_part = email_address.split("@", 1)[0].replace(".", " ").replace("_", " ").strip()
                parts = [p.capitalize() for p in local_part.split() if p]
                first_name = parts[0] if parts else (company_name or "Apollo Lead")
                last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
            else:
                first_name = company_name or "Apollo Lead"

        category = determine_apollo_lead_category(
            title=title,
            seniority=seniority,
            email_status=email_status,
            stage=stage,
            category_override=category_override,
        )

        # Build social_username / handle display (e.g., LinkedIn handle or Role @ Company)
        social_username = ""
        if linkedin_url:
            m = re.search(r"linkedin\.com/in/([^/?#]+)", linkedin_url, re.IGNORECASE)
            social_username = f"linkedin.com/in/{m.group(1)}" if m else linkedin_url
        elif title:
            social_username = title

        # Build rich notes
        notes_parts: List[str] = []
        if title:
            notes_parts.append(f"Title: {title}")
        if seniority:
            notes_parts.append(f"Seniority: {seniority}")
        if email_status:
            notes_parts.append(f"Email Status: {email_status}")
        if stage:
            notes_parts.append(f"Apollo Stage: {stage}")
        loc_str = ", ".join([p for p in (city, country) if p])
        if loc_str:
            notes_parts.append(f"Location: {loc_str}")
        if linkedin_url:
            notes_parts.append(f"LinkedIn: {linkedin_url}")
        notes_parts.append(f"Imported via Apollo CSV ({clean_source_name})")
        if file_id:
            notes_parts.append(f"Vault File ID: {file_id}")

        full_name = " ".join([p for p in (first_name, last_name) if p]).strip()

        parsed_contacts.append(
            {
                "first_name": first_name,
                "middle_name": "",
                "last_name": last_name,
                "full_name": full_name,
                "company": company_name,
                "email_address": email_address,
                "contact_number": contact_number,
                "platform": "apollo",
                "social_username": social_username,
                "account_name": f"Apollo CSV • {clean_source_name}",
                "category": category,
                "notes": " | ".join(notes_parts),
                "source_type": "apollo",
                "source_ref": f"apollo_csv:{file_id or clean_source_name}:row_{row_idx}",
            }
        )

    return {
        "rows_parsed": len(parsed_contacts),
        "contacts": parsed_contacts,
        "skipped_rows": skipped_rows,
        "column_mapping": {
            "company_col": "Column E (Company Name for Emails)",
            "email_col": "Column F (Email)",
            "phone_col": "Column T (Corporate Phone)",
        },
    }
