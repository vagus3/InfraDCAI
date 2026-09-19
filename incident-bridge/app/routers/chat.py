import json
import logging

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.auth import get_current_user
from app.config import settings
from app.llm import UpstreamIncompleteError, stream_llm_response
from app.logging_config import log_event
from app.models import User
from app.redis_client import get_redis
from app.schemas import ChatRequest

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


def _history_key(user_id: str) -> str:
    return f"chat_history:{user_id}"


@router.get("/history")
async def get_history(current_user: User = Depends(get_current_user)):
    r = get_redis()
    raw = await r.lrange(_history_key(str(current_user.id)), 0, -1)
    return [json.loads(m) for m in raw]


@router.delete("/history", status_code=204)
async def clear_history(current_user: User = Depends(get_current_user)):
    r = get_redis()
    await r.delete(_history_key(str(current_user.id)))


@router.post("/stream")
async def chat_stream(req: ChatRequest, current_user: User = Depends(get_current_user)):
    """Server-Sent Events endpoint.

    Rolling history lives in Redis rather than Postgres: it is short-lived,
    read on every single turn, and losing it costs a user their context but
    not their account. Postgres holds the things that must survive a restart.
    """
    r = get_redis()
    key = _history_key(str(current_user.id))

    raw_history = await r.lrange(key, 0, -1)
    history = [json.loads(m) for m in raw_history]
    history.append({"role": "user", "content": req.message})

    async def event_generator():
        full_reply = ""
        # Tells the client that history came back from Redis and we are about
        # to call the model. The pipeline view in the UI reads these, so it
        # shows real server progress rather than a guessed animation.
        yield f"data: {json.dumps({'stage': 'history_loaded', 'messages': len(history)})}\n\n"
        try:
            async for chunk in stream_llm_response(history):
                full_reply += chunk
                yield f"data: {json.dumps({'content': chunk})}\n\n"
        except httpx.HTTPStatusError as exc:
            # The upstream model rejected us (bad key, rate limit, model not
            # pulled). Status is already 200 by now, so the only way to tell
            # the client is an in-band error event.
            log_event(
                logger,
                logging.ERROR,
                "llm_upstream_error",
                status_code=exc.response.status_code,
                provider=settings.llm_provider,
            )
            yield f"data: {json.dumps({'error': 'The model is unavailable right now.'})}\n\n"
            return
        except httpx.RequestError:
            log_event(logger, logging.ERROR, "llm_unreachable", provider=settings.llm_provider)
            yield f"data: {json.dumps({'error': 'Could not reach the model.'})}\n\n"
            return
        except UpstreamIncompleteError:
            # The connection ended without the provider's own completion
            # signal -- a dropped connection or an early close, not a clean
            # finish. Without this, the loop above would have simply stopped
            # and the code below would persist reply_chars as if it were the
            # whole answer.
            log_event(
                logger,
                logging.ERROR,
                "llm_incomplete_stream",
                provider=settings.llm_provider,
                reply_chars=len(full_reply),
            )
            yield f"data: {json.dumps({'error': 'The response was cut off before it finished.'})}\n\n"
            return

        # Only persist once a full reply came back, so a failed turn does not
        # poison the next request's context with a half-finished answer.
        await r.rpush(key, json.dumps({"role": "user", "content": req.message}))
        await r.rpush(key, json.dumps({"role": "assistant", "content": full_reply}))
        await r.ltrim(key, -settings.chat_history_max_messages, -1)
        await r.expire(key, settings.chat_history_ttl_seconds)

        log_event(logger, logging.INFO, "chat_completed", reply_chars=len(full_reply))
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
