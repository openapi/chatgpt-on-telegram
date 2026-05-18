import html
import json
import os
import re
import time
import uuid
import urllib.error
import urllib.request

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4o"
MAX_TOOL_ITERATIONS = 10

BOT_ENVIRONMENT = os.environ.get("BOT_ENVIRONMENT", "sandbox")
CHATGPT_PROMPT_ID = os.environ.get("CHATGPT_PROMPT_ID", "").strip()
TELEGRAM_BOT_KEY = os.environ.get("TELEGRAM_BOT_KEY", "").strip()
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "").strip()
OPENAI_API_KEY = (
    os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAPI_API_KEY") or ""
).strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL).strip()

LAST_RESPONSE_IDS: dict[int, str] = {}


def log_event(message: str) -> None:
    if TELEGRAM_BOT_USERNAME:
        print(message, flush=True)
        return

    key_label = f" bot={TELEGRAM_BOT_KEY}" if TELEGRAM_BOT_KEY else ""
    print(f"[bot{key_label}] {message}", flush=True)


def shorten(value: str, limit: int = 80) -> str:
    if len(value) <= limit:
        return value

    return f"{value[:limit]}..."


def summarize_response_payload(payload: dict) -> str:
    output = payload.get("output")
    if not isinstance(output, list):
        return f"keys={sorted(payload.keys())} output_type={type(output).__name__}"

    summaries: list[str] = []
    for index, item in enumerate(output):
        if not isinstance(item, dict):
            summaries.append(f"{index}:type={type(item).__name__}")
            continue

        item_type = item.get("type", "unknown")
        content = item.get("content")
        if isinstance(content, list):
            content_summary = []
            for content_index, content_item in enumerate(content):
                if not isinstance(content_item, dict):
                    content_summary.append(f"{content_index}:{type(content_item).__name__}")
                    continue

                text_value = content_item.get("text")
                text_len = len(text_value) if isinstance(text_value, str) else 0
                content_summary.append(
                    f"{content_index}:{content_item.get('type', 'unknown')}:text_len={text_len}"
                )
            summaries.append(f"{index}:{item_type}:content=[{','.join(content_summary)}]")
        elif item_type == "function_call":
            summaries.append(
                f"{index}:function_call:name={item.get('name', '?')}:"
                f"call_id={item.get('call_id', item.get('id', '?'))}"
            )
        elif item_type == "mcp_approval_request":
            summaries.append(
                f"{index}:mcp_approval_request:name={item.get('name', '?')}:"
                f"server={item.get('server_label', '?')}"
            )
        else:
            summaries.append(f"{index}:{item_type}")

    return (
        f"id={payload.get('id')} status={payload.get('status')} "
        f"model={payload.get('model')} output=[{'; '.join(summaries)}]"
    )


def extract_text_from_content(content: object) -> list[str]:
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str) and text.strip():
            return [text.strip()]

        chunks: list[str] = []
        for value in content.values():
            chunks.extend(extract_text_from_content(value))
        return chunks

    if isinstance(content, list):
        chunks = []
        for item in content:
            chunks.extend(extract_text_from_content(item))
        return chunks

    return []


def extract_response_text(payload: dict) -> str:
    # Only extract text from final message items, not from reasoning or intermediate items.
    chunks: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        chunks.extend(extract_text_from_content(item.get("content", [])))

    if chunks:
        return "\n".join(chunks).strip()

    return "I did not receive a text response from GPT."


def extract_error_message(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip() or "Unknown error"

    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)

    return str(payload)


def format_for_telegram(text: str) -> str:
    # Split into code blocks (preserved as-is) and regular text segments.
    segments = re.split(r'(```(?:[^\n]*)?\n[\s\S]*?```|`[^`\n]+`)', text)
    result: list[str] = []

    for i, segment in enumerate(segments):
        if i % 2 == 1:
            if segment.startswith('```'):
                code = re.sub(r'^```[^\n]*\n?', '', segment)
                code = re.sub(r'\n?```$', '', code)
                result.append(f'<pre>{html.escape(code)}</pre>')
            else:
                result.append(f'<code>{html.escape(segment[1:-1])}</code>')
        else:
            safe = html.escape(segment)
            safe = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', safe)
            safe = re.sub(r'__(.+?)__', r'<b>\1</b>', safe)
            safe = re.sub(r'\*([^*\n]+)\*', r'<i>\1</i>', safe)
            safe = re.sub(r'_([^_\n]+)_', r'<i>\1</i>', safe)
            safe = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', safe, flags=re.MULTILINE)
            result.append(safe)

    return ''.join(result)


def execute_tool_call(name: str, arguments_json: str) -> str:
    try:
        arguments = json.loads(arguments_json)
    except json.JSONDecodeError:
        arguments = {}

    log_event(f"Tool call: name={name} arguments={shorten(arguments_json, 120)}")
    # Dispatch to registered tool handlers here.
    return json.dumps({"error": f"Tool '{name}' is not implemented."})


def _call_openai_responses(request_payload: dict, client_request_id: str) -> tuple[dict, int]:
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
            "X-Client-Request-Id": client_request_id,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8")), response.status


def ask_gpt(message: str, chat_id: int) -> str:
    if not OPENAI_API_KEY:
        log_event(f"Missing OpenAI API key for chat_id={chat_id}")
        return "OpenAI API Key is not configured. Restart the bot from the web page."

    previous_response_id = LAST_RESPONSE_IDS.get(chat_id)

    base_config: dict = {}
    if CHATGPT_PROMPT_ID:
        base_config["prompt"] = {
            "id": CHATGPT_PROMPT_ID,
            "variables": {
                "message": message,
                "environment": BOT_ENVIRONMENT,
            },
        }
    else:
        base_config["model"] = OPENAI_MODEL

    request_payload: dict = {"input": message, **base_config}
    if previous_response_id:
        request_payload["previous_response_id"] = previous_response_id

    client_request_id = str(uuid.uuid4())
    log_event(
        "OpenAI request start "
        f"client_request_id={client_request_id} endpoint={OPENAI_RESPONSES_URL} "
        f"prompt_id={shorten(CHATGPT_PROMPT_ID) if CHATGPT_PROMPT_ID else 'none'} "
        f"model={OPENAI_MODEL if not CHATGPT_PROMPT_ID else 'from_prompt'} "
        f"previous_response_id={'yes' if previous_response_id else 'no'} "
        f"input_chars={len(message)}"
    )
    started_at = time.monotonic()

    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            response_payload, http_status = _call_openai_responses(request_payload, client_request_id)
        except urllib.error.HTTPError as error:
            request_id = error.headers.get("x-request-id", "unknown") if error.headers else "unknown"
            body = error.read().decode("utf-8", errors="replace")
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            log_event(
                "OpenAI response error "
                f"client_request_id={client_request_id} request_id={request_id} "
                f"http_status={error.code} elapsed_ms={elapsed_ms} chat_id={chat_id} "
                f"message={shorten(extract_error_message(body), 180)}"
            )
            return f"GPT returned error {error.code}: {extract_error_message(body)}"
        except urllib.error.URLError as error:
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            log_event(
                "OpenAI request failed "
                f"client_request_id={client_request_id} elapsed_ms={elapsed_ms} "
                f"chat_id={chat_id} reason={error.reason}"
            )
            return f"Unable to reach GPT: {error.reason}"
        except TimeoutError:
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            log_event(
                "OpenAI request timed out "
                f"client_request_id={client_request_id} elapsed_ms={elapsed_ms} chat_id={chat_id}"
            )
            return "The GPT request timed out."

        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        log_event(
            "OpenAI response received "
            f"client_request_id={client_request_id} iteration={iteration} "
            f"http_status={http_status} elapsed_ms={elapsed_ms} "
            f"{summarize_response_payload(response_payload)}"
        )

        response_id = response_payload.get("id")
        if isinstance(response_id, str):
            LAST_RESPONSE_IDS[chat_id] = response_id

        output_items = response_payload.get("output", [])
        function_calls = [
            item for item in output_items
            if isinstance(item, dict) and item.get("type") == "function_call"
        ]
        approval_requests = [
            item for item in output_items
            if isinstance(item, dict) and item.get("type") == "mcp_approval_request"
        ]

        if not function_calls and not approval_requests:
            answer = extract_response_text(response_payload)
            if answer == "I did not receive a text response from GPT.":
                log_event(
                    "OpenAI response contained no extractable text "
                    f"client_request_id={client_request_id} chat_id={chat_id} "
                    f"{summarize_response_payload(response_payload)}"
                )
            else:
                log_event(
                    "OpenAI text extracted "
                    f"client_request_id={client_request_id} chat_id={chat_id} output_chars={len(answer)}"
                )
            return answer

        continuation_inputs: list[dict] = []

        for req in approval_requests:
            log_event(
                f"Auto-approving MCP tool: name={req.get('name', '?')} "
                f"server={req.get('server_label', '?')} "
                f"client_request_id={client_request_id}"
            )
            continuation_inputs.append({
                "type": "mcp_approval_response",
                "approve": True,
                "approval_request_id": req.get("id", ""),
            })

        for call in function_calls:
            call_id = call.get("call_id") or call.get("id", "")
            output = execute_tool_call(call.get("name", ""), call.get("arguments", "{}"))
            continuation_inputs.append({
                "type": "function_call_output",
                "call_id": call_id,
                "output": output,
            })

        log_event(
            f"Continuing with {len(continuation_inputs)} input(s) "
            f"({len(approval_requests)} approvals, {len(function_calls)} tool outputs) "
            f"client_request_id={client_request_id} chat_id={chat_id}"
        )
        request_payload = {
            "previous_response_id": response_id,
            "input": continuation_inputs,
            **base_config,
        }

    return "GPT did not complete after the maximum number of tool-call iterations."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    chat_id = update.effective_chat.id if update.effective_chat else 0
    log_event(f"Received /start from chat_id={chat_id}")
    await update.message.reply_text(
        f"ChatGPT on Telegram is active in {BOT_ENVIRONMENT} mode."
    )


async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    chat_id = update.effective_chat.id if update.effective_chat else 0
    log_event(f"Received /hello from chat_id={chat_id}")
    first_name = update.effective_user.first_name if update.effective_user else "there"
    await update.message.reply_text(f"Hello {first_name}")


async def answer_with_gpt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return

    chat_id = update.effective_chat.id if update.effective_chat else 0
    log_event(f"Received text message from chat_id={chat_id}")
    answer = ask_gpt(update.message.text, chat_id)
    try:
        await update.message.reply_text(format_for_telegram(answer), parse_mode="HTML")
    except Exception:
        await update.message.reply_text(answer)
    log_event(f"Sent reply to chat_id={chat_id}")


def main() -> None:
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not telegram_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing.")

    log_event("Process started")
    app = ApplicationBuilder().token(telegram_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("hello", hello))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer_with_gpt))
    log_event("Polling started")
    app.run_polling()


if __name__ == "__main__":
    main()