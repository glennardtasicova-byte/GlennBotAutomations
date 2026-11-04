from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from services.ai_service import AskAIRequest, _execute_glennbot_ask_ai_core

router = APIRouter()


@router.post("/api/ai/ask")
@router.post("/api/v1/ai/ask")
async def api_ask_ai(request: Request):
    """
    Generate viral social media titles/captions OR answer user questions/comments politely with live internet search using Gemini 3.5 Flash.
    Supports both Create Post GUI (`/api/ai/ask`) and n8n HTTP Request nodes (`/api/v1/ai/ask`).
    Strictly reads GEMINI_API_KEY from .env; never exposes the key to client/GUI.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    user_topic = str(
        body.get("topic")
        or body.get("prompt")
        or body.get("question")
        or body.get("message")
        or body.get("comment")
        or body.get("query")
        or ""
    ).strip()
    tone_str = str(body.get("tone") or "engaging").strip()
    lang_str = str(body.get("language") or "taglish").strip()
    post_type_str = str(body.get("post_type") or "reels").strip()
    platforms_list = body.get("platforms") if isinstance(body.get("platforms"), list) else None
    use_search = bool(body.get("use_search", True))
    is_v1_route = "/api/v1/" in str(request.url.path or "")

    return await run_in_threadpool(
        lambda: _execute_glennbot_ask_ai_core(
            user_topic=user_topic,
            tone_str=tone_str,
            lang_str=lang_str,
            post_type_str=post_type_str,
            platforms_list=platforms_list,
            force_reply_mode=is_v1_route,
            use_search=use_search
        )
    )
