from fastapi import APIRouter, Request
from core.config import LOCAL_DEVICE_URL, get_dynamic_base_url

router = APIRouter()


@router.api_route("/health", methods=["GET", "HEAD"])
@router.api_route("/ping", methods=["GET", "HEAD"])
@router.api_route("/api/health", methods=["GET", "HEAD"])
async def health_check(request: Request):
    live_base = get_dynamic_base_url(request=request, prefer_public=True)
    return {
        "status": "ok",
        "service": "glennbot-scheduler",
        "public_url": live_base,
        "local_url": LOCAL_DEVICE_URL,
        "webhook_endpoint": f"{live_base}/api/webhooks/zernio"
    }
