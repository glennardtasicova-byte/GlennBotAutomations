import os
import re
import json
import time
import xml.etree.ElementTree as ET
from typing import List, Optional, Any
import requests
from pydantic import BaseModel
from fastapi.responses import JSONResponse


# =========================================================================
# --- GEMINI 3.5 FLASH: ASK AI POST CONTENT, QUESTION SEARCH & REPLY API ---
# =========================================================================
class AskAIRequest(BaseModel):
    topic: Optional[str] = ""
    prompt: Optional[str] = ""
    question: Optional[str] = ""
    message: Optional[str] = ""
    comment: Optional[str] = ""
    tone: Optional[str] = "engaging"
    language: Optional[str] = "taglish"
    post_type: Optional[str] = "reels"
    platforms: Optional[List[str]] = None
    use_search: Optional[bool] = True


def _perform_free_web_search_for_ai(raw_query: str) -> str:
    """
    Performs a fast, free live internet search across Bing Web RSS, Google News RSS, and Wikipedia
    so Gemini AI can answer any factual or current-events question from social media comments/DMs
    without hitting Google AI Studio's paid-tier grounding quota limits.
    """
    clean_q = str(raw_query or "").strip()
    # Strip common instruction prefixes added by n8n prompts so the search engine gets the actual user question
    clean_q = re.sub(
        r"^(reply\s+politely[^:]*:|answer\s+this\s+question[^:]*:|respond\s+to\s+this\s+comment[^:]*:|comment\s*:|question\s*:)\s*",
        "",
        clean_q,
        flags=re.IGNORECASE
    ).strip()
    if not clean_q or len(clean_q) < 3:
        return ""

    search_q = clean_q[:180]
    snippets: List[str] = []

    # 1. Bing Web Search RSS (general web results & prices/facts)
    try:
        r_bing = requests.get(
            "https://www.bing.com/search",
            params={"q": search_q, "format": "rss"},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=4
        )
        if r_bing.status_code == 200 and "<rss" in r_bing.text:
            root = ET.fromstring(r_bing.text)
            for item in root.findall(".//item")[:4]:
                t_val = (item.findtext("title") or "").strip()
                d_val = re.sub(r"<[^>]+>", "", (item.findtext("description") or "")).strip()
                if t_val or d_val:
                    snippets.append(f"- [Web] {t_val}: {d_val[:240]}")
    except Exception:
        pass

    # 2. Google News RSS (latest news & current events in PH / Global)
    try:
        r_news = requests.get(
            "https://news.google.com/rss/search",
            params={"q": search_q, "hl": "en-PH", "gl": "PH", "ceid": "PH:en"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=4
        )
        if r_news.status_code == 200 and "<rss" in r_news.text:
            root = ET.fromstring(r_news.text)
            for item in root.findall(".//item")[:3]:
                t_val = (item.findtext("title") or "").strip()
                pub_val = (item.findtext("pubDate") or "").strip()
                if t_val:
                    snippets.append(f"- [News] {t_val} ({pub_val})")
    except Exception:
        pass

    # 3. Wikipedia API (encyclopedic & factual knowledge)
    try:
        r_wiki = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": search_q, "format": "json", "srlimit": 2},
            headers={"User-Agent": "GlennBot/2.0"},
            timeout=4
        )
        if r_wiki.status_code == 200:
            for s_item in r_wiki.json().get("query", {}).get("search", [])[:2]:
                w_title = s_item.get("title") or ""
                w_snip = re.sub(r"<[^>]+>", "", s_item.get("snippet") or "").strip()
                if w_title and w_snip:
                    snippets.append(f"- [Wikipedia: {w_title}] {w_snip}")
    except Exception:
        pass

    return "\n".join(snippets[:8])


def _sanitize_outbound_social_or_email_text(raw_val: Any) -> str:
    """
    Ensures that raw or truncated AI JSON objects (e.g. {"reply": "...", "title": "...", "facebook_caption": "..."})
    are NEVER posted as literal text to Facebook/Instagram comments, Messenger/IG DMs, SMS, or Emails.
    Automatically unwraps and returns the clean conversational string.
    """
    if isinstance(raw_val, dict):
        for k in ("reply", "message", "response", "text", "answer", "caption"):
            v = raw_val.get(k)
            if isinstance(v, str) and v.strip():
                return _sanitize_outbound_social_or_email_text(v.strip())
        return ""

    s = str(raw_val or "").strip()
    if not s:
        return ""

    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()

    # Check if s looks like a JSON object (complete or truncated at token limit) containing AI payload keys
    if s.startswith("{") and any(
        marker in s
        for marker in ('"reply"', '"caption"', '"facebook_caption"', '"instagram_caption"', '"response"', '"message"', '"answer"')
    ):
        try:
            parsed_obj = json.loads(s)
            if isinstance(parsed_obj, dict):
                for k in ("reply", "message", "response", "text", "answer", "caption"):
                    v = parsed_obj.get(k)
                    if isinstance(v, str) and v.strip():
                        return _sanitize_outbound_social_or_email_text(v.strip())
        except Exception:
            pass

        # Regex extraction fallback for truncated JSON strings (e.g. cut off mid-youtube_description)
        for k in ("reply", "message", "response", "text", "answer", "caption"):
            m_val = re.search(rf'"{k}"\s*:\s*"((?:\\.|[^"\\])*)"', s, re.DOTALL)
            if m_val:
                raw_inner = m_val.group(1)
                try:
                    unquoted = json.loads(f'"{raw_inner}"')
                except Exception:
                    unquoted = (
                        raw_inner.replace('\\n', '\n')
                        .replace('\\r', '\r')
                        .replace('\\t', '\t')
                        .replace('\\"', '"')
                        .replace('\\\\', '\\')
                    )
                if str(unquoted).strip():
                    return str(unquoted).strip()

    return s


def _execute_glennbot_ask_ai_core(
    user_topic: str,
    tone_str: str = "engaging",
    lang_str: str = "taglish",
    post_type_str: str = "reels",
    platforms_list: Optional[List[str]] = None,
    force_reply_mode: bool = False,
    use_search: bool = True
):
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "Gemini API key is not configured in .env. Please set GEMINI_API_KEY in your .env file."
            }
        )

    user_topic = (user_topic or "").strip()
    if not user_topic:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Please enter some details or a question/comment for Gemini AI."}
        )

    preferred_model = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    candidate_models: List[str] = []
    # Map legacy/alias names to active v1beta model identifiers first to avoid unnecessary 404 roundtrips
    normalized_pref = "gemini-2.5-flash" if preferred_model in ("gemini-3.5-flash", "gemini-3.5-flash-lite") else preferred_model
    for candidate_m in [
        normalized_pref,
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.5-flash-lite",
        "gemini-flash-latest",
    ]:
        if candidate_m and candidate_m not in candidate_models:
            candidate_models.append(candidate_m)

    tone_str = (tone_str or "engaging").strip()
    lang_str = (lang_str or "taglish").strip()
    post_type_str = (post_type_str or "reels").strip()
    platforms_list = platforms_list or ["facebook", "instagram", "tiktok", "youtube"]

    topic_low = user_topic.lower()
    is_reply_mode = (
        force_reply_mode
        or post_type_str.lower() in ("comment_reply", "reply", "dm_reply", "email_reply", "chat", "comment")
        or any(k in topic_low for k in ("reply politely", "reply to this comment", "answer this question", "analyze this", "comment:", "?"))
    )
    wants_full_social_post_pack = (
        not is_reply_mode
        or post_type_str.lower() in ("reels", "video169", "image", "text", "post", "carousel")
        and not force_reply_mode
        and not any(k in topic_low for k in ("analyze this", "reply to", "comment_reply", "draft a very polite", "customer's comment"))
    )

    is_script_guided_reply = (
        post_type_str.lower() in ("dm_reply", "comment_reply", "reply", "chat")
        or "script.xlsx" in topic_low
        or "script-based reply instructions" in topic_low
    )
    web_search_context = ""
    if use_search and not is_script_guided_reply:
        try:
            web_search_context = _perform_free_web_search_for_ai(user_topic)
        except Exception:
            web_search_context = ""

    search_block = (
        f"\nLive Internet Search Context (Use these real-time facts if relevant to answer the user's question accurately):\n{web_search_context}\n"
        if web_search_context else ""
    )

    if is_script_guided_reply and not wants_full_social_post_pack:
        system_instruction = (
            "You are Glennard R. Tasico (AI Automation Specialist & Industrial Engineer), replying personally in first-person "
            "('I', 'me', 'my' in English; 'ako', 'ko', 'akin' in Tagalog/Taglish) to a social media Direct Message or Post Comment. "
            "CRITICAL RULES:\n"
            "1. Read the Full Conversation History (separated by '|') carefully so you remember the exact context and flow of the conversation. "
            "NEVER lose track of the ongoing topic or reply with a generic introductory sales pitch in the middle of a conversation.\n"
            "2. Check the Script.xlsx (Sheet1) knowledge base (Column A = keywords/key phrases, Column B = reference answer). "
            "If the user's message or question matches a topic in Script.xlsx, use Column B's facts to construct your own natural, conversational message (DO NOT copy-paste Column B verbatim).\n"
            "3. If the user is reacting to your previous reply, asking a follow-up question, expressing doubt/frustration (e.g. 'ang bagal kaya', 'bakit hindi ka nagrereply', 'ano raw', 'iniba mo ang topic'), "
            "or chatting conversationally, address their exact remark directly, empathetically, and naturally while staying in context with the '|' conversation history.\n"
            "4. Always reply in the EXACT SAME language (Tagalog, Taglish, or pure English) used by the sender in their latest message. "
            "Output ONLY valid JSON with a 'reply' field containing clean plain text (no markdown fences, no hashtags)."
        )
        prompt = f"""{user_topic}

Respond ONLY with a raw JSON object in this exact format:
{{
  "reply": "Your natural, context-aware first-person reply as Glennard that directly responds to the user's latest message while honoring the '|' conversation history and Script.xlsx facts",
  "intent": "contextual_reply"
}}"""
    elif is_reply_mode and not wants_full_social_post_pack:
        system_instruction = (
            "You are GlennBot AI, an elite social media strategist, helpful customer support specialist, and intelligent research assistant. "
            "When replying to user comments, messages, or emails, write natural, polite, human-like plain text inside the 'reply' field (NEVER nest JSON inside 'reply' and NEVER include hashtag walls in 'reply'). "
            "Respect the requested language and tone. Output ONLY valid JSON matching the exact schema provided."
        )
        prompt = f"""Incoming Prompt / Comment / Message Analysis Request:
"{user_topic}"
{search_block}
Mode: {post_type_str}
Requested Tone: {tone_str}
Requested Language: {lang_str}

Instructions:
1. "reply": A direct, polite, friendly, and accurate conversational reply to the user's comment, DM, or question in natural {lang_str} ({tone_str} tone). MUST be clean plain text only (1-4 sentences, NO raw JSON, NO hashtag blocks). If the user is asking about their parcel/order/delivery and did not provide a tracking number, politely ask them to send their Tracking Number or Order ID so you can check it right away.
2. "is_relevant": Boolean (true or false). If the prompt asks to determine whether the comment/message matches a specific topic (such as delivery/parcel status, order tracking, pricing inquiry, etc.), set true ONLY if the user's message is genuinely about that topic; otherwise false.
3. "is_delivery_related": Boolean (true or false). True if the user's comment/message is asking about parcel status, shipping, delivery, courier, order tracking, or where their package is; otherwise false.
4. "has_tracking_number": Boolean (true or false). True if an explicit tracking number or order ID code is present in the user's comment/message; otherwise false.
5. "tracking_number": Extracted tracking number or order code string from the user's comment/message (or "" if none was provided).
6. "intent": Short snake_case label of the user's intent (e.g. "delivery_inquiry", "price_inquiry", "general_question", "compliment", "other").
7. "title": Short summary title (under 80 chars).

You MUST respond ONLY with a raw JSON object (no markdown formatting, no extra explanation) formatted like this:
{{
  "reply": "...",
  "is_relevant": true,
  "is_delivery_related": false,
  "has_tracking_number": false,
  "tracking_number": "",
  "intent": "...",
  "title": "..."
}}
"""
    else:
        system_instruction = (
            "You are GlennBot AI, an elite social media strategist, helpful customer support specialist, and intelligent research assistant. "
            "When replying to user comments, messages, or emails, write natural, polite, human-like plain text inside the 'reply' field (NEVER nest JSON inside 'reply' and NEVER include hashtag walls in 'reply'). "
            "Respect the requested language and tone. Output ONLY valid JSON matching the exact schema provided."
        )
        prompt = f"""Content Details / Comment / Question from User:
"{user_topic}"
{search_block}
Post Format / Mode: {post_type_str}
Requested Tone: {tone_str}
Requested Language: {lang_str}
Target Platforms: {', '.join(str(p) for p in platforms_list)}

Instructions:
1. "reply": A direct, polite, friendly, and accurate conversational reply/answer to the user's comment or question (1-3 sentences, natural {lang_str} tone, NO hashtag blocks). If they asked a question, provide a helpful, factual answer. If they left a compliment or general comment, reply warmly and politely.
2. "title": A catchy, clickable title suitable for YouTube, Reels, or Video (under 95 chars).
3. "caption": A primary all-around engaging post caption complete with an attention-grabbing hook, clear body with bullet points or emojis, call-to-action (CTA), and relevant hashtags.
4. "facebook_caption": Tailored for Facebook with engaging conversational tone, emojis, and discussion question / CTA.
5. "instagram_caption": Tailored for Instagram with hook, clean line spacing, strong CTA, and 10-15 targeted hashtags.
6. "tiktok_caption": Short, snappy, punchy caption for TikTok (under 150 chars) plus 4-6 trending hashtags.
7. "youtube_title": Catchy, SEO-optimized title for YouTube (max 95 chars).
8. "youtube_description": Comprehensive YouTube description with summary, chapter timestamps guide, links placeholder, and search tags.
9. "hashtags": Space-separated list of 8-12 top relevant hashtags (e.g., #Tech #Review #Philippines).

You MUST respond ONLY with a raw JSON object (no markdown formatting, no extra explanation) formatted like this:
{{
  "reply": "...",
  "title": "...",
  "caption": "...",
  "facebook_caption": "...",
  "instagram_caption": "...",
  "tiktok_caption": "...",
  "youtube_title": "...",
  "youtube_description": "...",
  "hashtags": "..."
}}
"""

    last_err = ""
    for current_model in candidate_models:
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": f"{system_instruction}\n\n{prompt}"}]}],
            "generationConfig": {
                "temperature": 0.45 if is_script_guided_reply else (0.55 if is_reply_mode else 0.65),
                "maxOutputTokens": 2048 if is_script_guided_reply else 4096,
                "responseMimeType": "application/json"
            }
        }

        for attempt in range(1, 3):
            try:
                resp = requests.post(gemini_url, json=payload, timeout=16)
                if resp.status_code == 200:
                    res_data = resp.json()
                    candidates = res_data.get("candidates", [])
                    if not candidates:
                        last_err = "No response returned from Gemini."
                        break

                    parts = candidates[0].get("content", {}).get("parts", [])
                    raw_text = "".join(part.get("text", "") for part in parts).strip()

                    if raw_text.startswith("```"):
                        lines = raw_text.splitlines()
                        if lines and lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].startswith("```"):
                            lines = lines[:-1]
                        raw_text = "\n".join(lines).strip()

                    parsed = None
                    try:
                        parsed = json.loads(raw_text)
                    except Exception:
                        m = re.search(r"\{.*\}", raw_text, re.DOTALL)
                        if m:
                            try:
                                parsed = json.loads(m.group(0))
                            except Exception:
                                pass

                    if not isinstance(parsed, dict):
                        clean_fallback_reply = _sanitize_outbound_social_or_email_text(raw_text)
                        parsed = {
                            "reply": clean_fallback_reply,
                            "title": user_topic[:80],
                            "caption": clean_fallback_reply,
                            "facebook_caption": clean_fallback_reply,
                            "instagram_caption": clean_fallback_reply,
                            "tiktok_caption": clean_fallback_reply[:150],
                            "youtube_title": user_topic[:80],
                            "youtube_description": clean_fallback_reply,
                            "hashtags": ""
                        }

                    raw_reply_candidate = str(parsed.get("reply") or parsed.get("caption") or "").strip()
                    reply_text = _sanitize_outbound_social_or_email_text(raw_reply_candidate)
                    if not reply_text:
                        last_err = "Empty reply text returned from Gemini."
                        break
                    caption_text = _sanitize_outbound_social_or_email_text(str(parsed.get("caption") or reply_text).strip()) if is_reply_mode else str(parsed.get("caption") or reply_text).strip()
                    title_text = str(parsed.get("title") or user_topic[:80]).strip()

                    # Extract or infer delivery/tracking & relevance fields for n8n conditional nodes
                    is_deliv = parsed.get("is_delivery_related")
                    if not isinstance(is_deliv, bool):
                        is_deliv = bool(re.search(r"\b(parcel|delivery|deliver|tracking|order|package|padala|ship|shipping|status|asaan|nasaan|rider|courier)\b", topic_low))
                    is_rel = parsed.get("is_relevant")
                    if not isinstance(is_rel, bool):
                        is_rel = is_deliv if ("delivery" in topic_low or "parcel" in topic_low or "tracking" in topic_low) else True
                    extracted_trk = str(parsed.get("tracking_number") or "").strip()
                    if extracted_trk.lower() in ("none", "null", "n/a", "false", "undefined"):
                        extracted_trk = ""
                    has_trk = bool(parsed.get("has_tracking_number")) if isinstance(parsed.get("has_tracking_number"), bool) else bool(extracted_trk)
                    intent_str = str(parsed.get("intent") or ("delivery_inquiry" if is_deliv else "general")).strip()

                    return {
                        "status": "success",
                        "model": current_model,
                        "reply": reply_text,
                        "response": reply_text,
                        "text": reply_text,
                        "answer": reply_text,
                        "message": reply_text,
                        "title": title_text,
                        "caption": reply_text if is_reply_mode else caption_text,
                        "is_relevant": is_rel,
                        "is_delivery_related": is_deliv,
                        "has_tracking_number": has_trk,
                        "tracking_number": extracted_trk,
                        "intent": intent_str,
                        "search_used": bool(web_search_context),
                        "data": {
                            "reply": reply_text,
                            "response": reply_text,
                            "title": title_text,
                            "caption": caption_text,
                            "is_relevant": is_rel,
                            "is_delivery_related": is_deliv,
                            "has_tracking_number": has_trk,
                            "tracking_number": extracted_trk,
                            "intent": intent_str,
                            "facebook_caption": parsed.get("facebook_caption") or caption_text,
                            "instagram_caption": parsed.get("instagram_caption") or caption_text,
                            "tiktok_caption": parsed.get("tiktok_caption") or caption_text,
                            "youtube_title": parsed.get("youtube_title") or title_text,
                            "youtube_description": parsed.get("youtube_description") or caption_text,
                            "hashtags": parsed.get("hashtags") or ""
                        }
                    }
                elif resp.status_code in (429, 503) and attempt == 1:
                    last_err = f"Gemini {current_model} returned HTTP {resp.status_code}: {resp.text[:200]}"
                    time.sleep(1.1)
                    continue
                elif resp.status_code in (429, 404, 503, 500):
                    last_err = f"Gemini {current_model} returned HTTP {resp.status_code}: {resp.text[:200]}"
                    break
                else:
                    err_detail = resp.text[:300]
                    last_err = f"Gemini API returned HTTP {resp.status_code}: {err_detail}"
                    break
            except Exception as ex:
                last_err = f"Network error connecting to Gemini API ({current_model}): {str(ex)}"
                if attempt == 1:
                    time.sleep(0.8)
                    continue
                break

    if is_reply_mode:
        # Resilient context-aware fallback if all Gemini models are unreachable
        m_guide = re.search(r'Base Script Answer to Rephrase\):\s*"([^"]+)"', user_topic)
        m_latest = re.search(r'Latest (?:Direct Message|Comment) from [^:]+:\s*"([^"]+)"', user_topic)
        latest_user_msg = (m_latest.group(1).strip() if m_latest else user_topic).strip()
        is_tl = "tagalog" in lang_str.lower() or "taglish" in lang_str.lower() or bool(
            re.search(r"\b(ano|anong|bakit|paano|pano|kaya|naman|lang|ung|yung|ba|po|opo|sakin|sayo|ikaw|ako|mo|ko|kita|dyan|diyan)\b", latest_user_msg.lower())
        )
        if m_guide and m_guide.group(1).strip():
            fallback_reply = m_guide.group(1).strip()
        elif is_tl:
            fallback_reply = (
                "Pasensya na po kung nagkaroon ng kaunting delay o kalituhan sa sagot kanina! "
                "Nandito lang ako—ano po ang specific na tanong o kailangan ninyong i-clarify para masagot ko nang maayos?"
            )
        else:
            fallback_reply = (
                "My apologies for the brief delay! I'm right here—could you let me know what specific question or detail you'd like me to clarify for you?"
            )
        return {
            "status": "success",
            "model": "glennbot-resilient-fallback",
            "reply": fallback_reply,
            "response": fallback_reply,
            "text": fallback_reply,
            "answer": fallback_reply,
            "message": fallback_reply,
            "title": user_topic[:80],
            "caption": fallback_reply,
            "is_relevant": True,
            "is_delivery_related": False,
            "has_tracking_number": False,
            "tracking_number": "",
            "intent": "general",
            "search_used": False,
            "data": {
                "reply": fallback_reply,
                "response": fallback_reply,
                "title": user_topic[:80],
                "caption": fallback_reply,
            }
        }

    return JSONResponse(status_code=500, content={"status": "error", "message": last_err or "Failed to connect to Gemini."})

