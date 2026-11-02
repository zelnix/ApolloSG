"""Protection explanations for the app: Apollo Protections and the common Device Protections, reviewed text only."""
import base64
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import protection_explanations as explanations

router = APIRouter(tags=["protections"])
log = logging.getLogger(__name__)


# ── Screenshot verification for manual-check device settings ──────────────

class VerifySettingRequest(BaseModel):
    setting_id: str
    setting_name: str
    expected_state: str  # e.g. "off", "automatic", "disabled"
    image_base64: str    # base64-encoded screenshot
    device_id: str | None = None


@router.post("/protections/device/verify-screenshot")
async def verify_setting_screenshot(body: VerifySettingRequest):
    """Accept a screenshot of a device setting and ask the AI whether the setting is configured correctly."""
    from services.higgins import ai_settings, provider
    from services.higgins.ai_request import Part, Message
    from services.higgins.llm_boundary import Purpose

    try:
        image_bytes = base64.b64decode(body.image_base64)
    except Exception:
        raise HTTPException(400, "Invalid base64 image data.")

    if len(image_bytes) > 10_000_000:
        raise HTTPException(413, "Screenshot too large — keep it under 10 MB.")

    mime = "image/jpeg"
    if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        mime = "image/png"
    elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
        mime = "image/webp"

    model = await ai_settings.investigation_model()

    system_prompt = (
        "You are Higgins, a helpful security assistant inside ApolloSG. "
        "The user is showing you a screenshot of a device setting so you can confirm it is configured safely.\n\n"
        f"Setting name: {body.setting_name}\n"
        f"Expected safe state: {body.expected_state}\n\n"
        "Analyse the screenshot and respond in this JSON format:\n"
        '{"confirmed": true/false, "summary": "one sentence saying what you see", '
        '"advice": "if not confirmed, a short plain-English instruction on what to change; if confirmed, null"}\n\n'
        "Rules:\n"
        "- confirmed = true means the setting matches the expected safe state.\n"
        "- confirmed = false means it doesn't match, or you can't tell from the screenshot.\n"
        "- Keep summary under 30 words.\n"
        "- Keep advice under 50 words if present.\n"
        "- If the screenshot doesn't show the relevant setting at all, set confirmed to false "
        'and advice to "Please take a screenshot that shows the [setting name] setting."'
    )

    contents = [
        Message(role="user", parts=[
            Part(text=f"Here is a screenshot of my {body.setting_name} settings. Is it configured correctly?"),
            Part.from_bytes(data=image_bytes, mime_type=mime),
        ]),
    ]

    try:
        result = await provider.generate(
            system_prompt, contents,
            model=model, capability="vision", json_output=True,
            purpose=Purpose.DEVICE_SETTING_VERIFICATION,
            device_id=body.device_id,
        )
        data = result.object()
        return {
            "confirmed": bool(data.get("confirmed", False)),
            "summary": str(data.get("summary", "Could not determine the setting state.")),
            "advice": data.get("advice"),
            "model": result.model,
        }
    except Exception as exc:
        log.warning("verify_setting_screenshot: AI call failed: %s", exc, exc_info=True)
        return {
            "confirmed": False,
            "summary": "Higgins couldn't analyse the screenshot right now.",
            "advice": "Try again in a moment, or mark it manually.",
            "model": None,
        }


@router.get("/protections/apollo/{protection_id}")
async def apollo_protection(protection_id: str):
    found = explanations.apollo_explanation(protection_id)
    if not found:
        raise HTTPException(404, "ApolloSG has no protection by that name.")
    return found


@router.get("/protections/device/{protection_id}")
async def reviewed_device_protection(protection_id: str):
    found = explanations.reviewed_device_explanation(protection_id)
    if not found:
        raise HTTPException(404, "ApolloSG has no explanation of that protection yet.")
    return found
