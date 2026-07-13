"""Interactive chat: each conversation is a durable ChatWorkflow.

The UI starts a session, signals user messages in, and polls the workflow
query for the transcript — which survives page reloads and worker crashes.
"""
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agentloom import config
from agentloom.workflows.chat import ChatWorkflow

from ..temporal_client import get_temporal_client

router = APIRouter(prefix="/api/chat", tags=["chat"])


class StartChatRequest(BaseModel):
    system_prompt: str | None = None


class MessageBody(BaseModel):
    text: str


@router.post("/")
async def start_chat(req: StartChatRequest | None = None) -> dict:
    client = await get_temporal_client()
    workflow_id = f"chat-{uuid.uuid4().hex[:8]}"
    await client.start_workflow(
        ChatWorkflow.run,
        req.system_prompt if req else None,
        id=workflow_id,
        task_queue=config.TASK_QUEUE,
    )
    return {"workflow_id": workflow_id}


@router.post("/{workflow_id}/message")
async def send_message(workflow_id: str, body: MessageBody) -> dict:
    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)
    try:
        await handle.signal("user_message", body.text)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@router.get("/{workflow_id}/history")
async def history(workflow_id: str) -> dict:
    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)
    try:
        # Queried without a result type hint, ChatState arrives as a plain dict.
        state: dict = await handle.query("get_history")
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "messages": state.get("messages", []),
        "responding": state.get("responding", False),
        "ended": state.get("ended", False),
    }


@router.post("/{workflow_id}/end")
async def end_chat(workflow_id: str) -> dict:
    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)
    try:
        await handle.signal("end_chat")
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}
