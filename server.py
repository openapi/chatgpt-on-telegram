import argparse
import base64
import html
import hashlib
import hmac
import json
import mimetypes
import os
import random
import re
import secrets
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
import urllib.error
import urllib.request

from cryptography.fernet import Fernet, InvalidToken


BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
MAX_FORM_SIZE = 64 * 1024
MAX_WEBHOOK_SIZE = 1024 * 1024
SESSION_TTL_SECONDS = 60 * 60
DEFAULT_DATA_PATH = "./data"


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4o"
MAX_TOOL_ITERATIONS = 10
DEFAULT_BOT_ENVIRONMENT = os.environ.get("BOT_ENVIRONMENT", "sandbox").strip() or "sandbox"
DEFAULT_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

THINKING_PHRASES = [
    "Ottimo, dammi un momento per riflettere 🤔",
    "Ci penso subito...",
    "Elaboro e sono subito da te!",
    "Un secondo, sto pensando... 💭",
    "Interessante! Lasciami riflettere un attimo",
    "Ricevuto! Ci vediamo tra un istante 🙂",
    "Sto elaborando la risposta...",
    "Perfetto, dammi un minuto per ragionare",
    "Subito! Sto già lavorando alla risposta",
    "Mmm, lasciami pensare... 🧠",
    "In arrivo! Sto elaborando la tua richiesta",
    "Ci sto, dammi solo qualche secondo",
]


def random_thinking_phrase() -> str:
    return random.choice(THINKING_PHRASES)


def log_event(message: str) -> None:
    print(message, flush=True)


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


def is_markdown_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def split_markdown_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_markdown_table(table_lines: list[str]) -> str:
    rows = [split_markdown_table_row(line) for line in table_lines]
    column_count = max((len(row) for row in rows), default=0)
    normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
    widths = [
        max(len(row[column]) for row in normalized_rows)
        for column in range(column_count)
    ]

    rendered_rows = []
    for index, row in enumerate(normalized_rows):
        rendered_rows.append(" | ".join(
            row[column].ljust(widths[column])
            for column in range(column_count)
        ).rstrip())
        if index == 0:
            rendered_rows.append("-+-".join("-" * width for width in widths))

    return f"<pre>{html.escape(chr(10).join(rendered_rows))}</pre>"


def apply_basic_markdown(segment: str) -> str:
    safe = html.escape(segment)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    safe = re.sub(r"__(.+?)__", r"<b>\1</b>", safe)
    safe = re.sub(r"\*([^*\n]+)\*", r"<i>\1</i>", safe)
    safe = re.sub(r"_([^_\n]+)_", r"<i>\1</i>", safe)
    safe = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", safe, flags=re.MULTILINE)
    return safe


def format_regular_markdown(segment: str) -> str:
    lines = segment.splitlines(keepends=True)
    result: list[str] = []
    pending: list[str] = []
    index = 0

    while index < len(lines):
        current = lines[index].rstrip("\n")
        next_line = lines[index + 1].rstrip("\n") if index + 1 < len(lines) else ""

        if "|" in current and is_markdown_table_separator(next_line):
            if pending:
                result.append(apply_basic_markdown("".join(pending)))
                pending = []

            table_lines = [current]
            index += 2
            while index < len(lines):
                candidate = lines[index].rstrip("\n")
                if not candidate.strip() or "|" not in candidate:
                    break
                table_lines.append(candidate)
                index += 1

            result.append(render_markdown_table(table_lines))
            continue

        pending.append(lines[index])
        index += 1

    if pending:
        result.append(apply_basic_markdown("".join(pending)))

    return "".join(result)


def format_for_telegram(text: str) -> str:
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
            result.append(format_regular_markdown(segment))

    return ''.join(result)


def execute_tool_call(name: str, arguments_json: str) -> str:
    try:
        json.loads(arguments_json)
    except json.JSONDecodeError:
        pass

    log_event(f"Tool call: name={name} arguments={shorten(arguments_json, 120)}")
    return json.dumps({"error": f"Tool '{name}' is not implemented."})


def _call_openai_responses_with_key(
    request_payload: dict,
    client_request_id: str,
    openai_api_key: str,
) -> tuple[dict, int]:
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {openai_api_key}",
            "Content-Type": "application/json",
            "X-Client-Request-Id": client_request_id,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8")), response.status


def ask_gpt_stateless(
    message: str,
    chat_id: int | str,
    config: dict[str, str],
    previous_response_id: str | None = None,
    context_messages: list[dict[str, str]] | None = None,
) -> tuple[str, str | None]:
    openai_api_key = config.get("openai_api_key", "").strip()
    if not openai_api_key:
        return "OpenAI API Key is not configured. Restart the setup from the web page.", previous_response_id

    chatgpt_prompt_id = config.get("chatgpt_prompt_id", "").strip()
    openai_model = config.get("openai_model", DEFAULT_OPENAI_MODEL).strip() or DEFAULT_MODEL
    bot_environment = config.get("bot_environment", DEFAULT_BOT_ENVIRONMENT).strip() or DEFAULT_BOT_ENVIRONMENT

    base_config: dict = {}
    if chatgpt_prompt_id:
        base_config["prompt"] = {
            "id": chatgpt_prompt_id,
            "variables": {
                "message": message,
                "environment": bot_environment,
            },
        }
    else:
        base_config["model"] = openai_model

    input_payload: str | list[dict[str, str]] = message
    if context_messages:
        input_payload = [*context_messages, {"role": "user", "content": message}]

    request_payload: dict = {"input": input_payload, **base_config}
    if previous_response_id and not context_messages:
        request_payload["previous_response_id"] = previous_response_id

    client_request_id = str(uuid.uuid4())
    log_event(
        "OpenAI stateless request start "
        f"client_request_id={client_request_id} endpoint={OPENAI_RESPONSES_URL} "
        f"prompt_id={shorten(chatgpt_prompt_id) if chatgpt_prompt_id else 'none'} "
        f"model={openai_model if not chatgpt_prompt_id else 'from_prompt'} "
        f"previous_response_id={'yes' if previous_response_id and not context_messages else 'no'} "
        f"context_messages={len(context_messages or [])} "
        f"chat_id={chat_id} input_chars={len(message)}"
    )
    started_at = time.monotonic()
    current_response_id = previous_response_id

    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            response_payload, http_status = _call_openai_responses_with_key(
                request_payload,
                client_request_id,
                openai_api_key,
            )
        except urllib.error.HTTPError as error:
            request_id = error.headers.get("x-request-id", "unknown") if error.headers else "unknown"
            body = error.read().decode("utf-8", errors="replace")
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            log_event(
                "OpenAI stateless response error "
                f"client_request_id={client_request_id} request_id={request_id} "
                f"http_status={error.code} elapsed_ms={elapsed_ms} chat_id={chat_id} "
                f"message={shorten(extract_error_message(body), 180)}"
            )
            return f"GPT returned error {error.code}: {extract_error_message(body)}", current_response_id
        except urllib.error.URLError as error:
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            log_event(
                "OpenAI stateless request failed "
                f"client_request_id={client_request_id} elapsed_ms={elapsed_ms} "
                f"chat_id={chat_id} reason={error.reason}"
            )
            return f"Unable to reach GPT: {error.reason}", current_response_id
        except TimeoutError:
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            log_event(
                "OpenAI stateless request timed out "
                f"client_request_id={client_request_id} elapsed_ms={elapsed_ms} chat_id={chat_id}"
            )
            return "The GPT request timed out.", current_response_id

        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        log_event(
            "OpenAI stateless response received "
            f"client_request_id={client_request_id} iteration={iteration} "
            f"http_status={http_status} elapsed_ms={elapsed_ms} "
            f"{summarize_response_payload(response_payload)}"
        )

        response_id = response_payload.get("id")
        if isinstance(response_id, str):
            current_response_id = response_id

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
                    "OpenAI stateless response contained no extractable text "
                    f"client_request_id={client_request_id} chat_id={chat_id} "
                    f"{summarize_response_payload(response_payload)}"
                )
            else:
                log_event(
                    "OpenAI stateless text extracted "
                    f"client_request_id={client_request_id} chat_id={chat_id} output_chars={len(answer)}"
                )
            return answer, current_response_id

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
            f"Continuing stateless request with {len(continuation_inputs)} input(s) "
            f"({len(approval_requests)} approvals, {len(function_calls)} tool outputs) "
            f"client_request_id={client_request_id} chat_id={chat_id}"
        )
        request_payload = {
            "previous_response_id": current_response_id,
            "input": continuation_inputs,
            **base_config,
        }

    return "GPT did not complete after the maximum number of tool-call iterations.", current_response_id


def resolve_data_path() -> Path:
    configured = Path(os.environ.get("DATA_PATH", DEFAULT_DATA_PATH)).expanduser()
    if configured.is_absolute():
        return configured
    return (BASE_DIR / configured).resolve()


DATA_DIR = resolve_data_path()
BOTS_DIR = DATA_DIR / "bots"
SESSIONS_DIR = DATA_DIR / "sessions"


def ensure_data_path() -> None:
    BOTS_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def get_server_secret() -> str:
    secret = os.environ.get("SERVER_SECRET_KEY", "").strip()
    if not secret:
        raise ValueError("SERVER_SECRET_KEY is missing.")
    return secret


def get_server_fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(get_server_secret().encode("utf-8")).digest())
    return Fernet(key)


def encrypt_payload(config: dict) -> str:
    payload = json.dumps(config, separators=(",", ":")).encode("utf-8")
    return get_server_fernet().encrypt(payload).decode("utf-8")


def decrypt_payload(token: str) -> dict:
    payload = get_server_fernet().decrypt(token.encode("utf-8"))
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("Invalid payload.")
    return decoded


def make_bot_id(telegram_bot_id: str) -> str:
    digest = hmac.new(
        get_server_secret().encode("utf-8"),
        telegram_bot_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:32]


def bot_record_path(bot_id: str) -> Path:
    return BOTS_DIR / f"{bot_id}.json"


def session_record_path(bot_id: str, chat_id: str) -> Path:
    safe_chat_id = quote(chat_id, safe="")
    return SESSIONS_DIR / bot_id / f"{safe_chat_id}.json"


def load_bot_record(bot_id: str) -> dict | None:
    path = bot_record_path(bot_id)
    if not path.is_file():
        return None
    return read_json(path)


def load_bot_config(record: dict) -> dict[str, str]:
    encrypted_config = record.get("encrypted_config")
    if not isinstance(encrypted_config, str):
        raise ValueError("Bot configuration is missing.")
    decoded = decrypt_payload(encrypted_config)
    return {str(key): str(value) for key, value in decoded.items()}


def load_session(bot_id: str, chat_id: str) -> dict:
    path = session_record_path(bot_id, chat_id)
    if not path.is_file():
        return {}

    stored = read_json(path)
    encrypted_session = stored.get("encrypted_session")
    if isinstance(encrypted_session, str):
        return decrypt_payload(encrypted_session)
    return stored


def save_session(bot_id: str, chat_id: str, session: dict) -> None:
    session["updated_at"] = int(time.time())
    atomic_write_json(session_record_path(bot_id, chat_id), {"encrypted_session": encrypt_payload(session)})


def get_recent_messages(session: dict, now: int) -> list[dict[str, str]]:
    messages = session.get("messages")
    if not isinstance(messages, list):
        return []

    recent: list[dict[str, str]] = []
    cutoff = now - SESSION_TTL_SECONDS
    for item in messages:
        if not isinstance(item, dict):
            continue
        timestamp = item.get("ts")
        role = item.get("role")
        content = item.get("content")
        if not isinstance(timestamp, int) or timestamp < cutoff:
            continue
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content:
            continue
        recent.append({"role": role, "content": content})
    return recent


def save_recent_exchange(bot_id: str, chat_id: str, recent_messages: list[dict[str, str]], user_text: str, answer: str) -> None:
    now = int(time.time())
    serialized = [
        {"ts": now, "role": message["role"], "content": message["content"]}
        for message in recent_messages
    ]
    serialized.extend([
        {"ts": now, "role": "user", "content": user_text},
        {"ts": now, "role": "assistant", "content": answer},
    ])
    save_session(bot_id, chat_id, {"messages": serialized})


def mask_secret(value: str) -> str:
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def get_origin(handler: BaseHTTPRequestHandler) -> str:
    configured = os.environ.get("WEBHOOK_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured

    forwarded_proto = handler.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    scheme = forwarded_proto or "http"
    host = handler.headers.get("Host") or f"{handler.server.server_address[0]}:{handler.server.server_address[1]}"
    return f"{scheme}://{host}"


def build_launch_url(handler: BaseHTTPRequestHandler, bot_id: str) -> str:
    return f"{get_origin(handler)}/launch/{quote(bot_id, safe='')}"


def build_webhook_url(handler: BaseHTTPRequestHandler, bot_id: str) -> str:
    return f"{get_origin(handler)}/webhook/{quote(bot_id, safe='')}"


def validate_webhook_url(webhook_url: str) -> None:
    if webhook_url.startswith("https://"):
        return

    raise ValueError(
        "Telegram webhooks require a public HTTPS URL. "
        "Set WEBHOOK_BASE_URL to your external HTTPS origin, "
        "for example WEBHOOK_BASE_URL=https://example.com, "
        "or run the server behind an HTTPS reverse proxy that forwards X-Forwarded-Proto=https."
    )


def telegram_api_request(telegram_token: str, method: str, payload: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{telegram_token}/{method}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise ValueError(f"Telegram returned error {error.code}: {body}") from error
    except urllib.error.URLError as error:
        raise ValueError(f"Unable to reach Telegram: {error.reason}") from error

    if not decoded.get("ok"):
        raise ValueError(f"Telegram returned error: {decoded}")
    return decoded


def fetch_bot_identity(telegram_token: str) -> tuple[str, str]:
    payload = telegram_api_request(telegram_token, "getMe")
    result = payload.get("result", {})
    username = result.get("username")
    bot_id = result.get("id")
    if not isinstance(username, str) or not username:
        raise ValueError("Telegram token is valid, but bot username was not found.")
    if bot_id is None:
        return username, username
    return username, str(bot_id)


def set_telegram_webhook(telegram_token: str, webhook_url: str, secret_token: str) -> None:
    telegram_api_request(
        telegram_token,
        "setWebhook",
        {
            "url": webhook_url,
            "secret_token": secret_token,
            "drop_pending_updates": False,
            "allowed_updates": ["message"],
        },
    )


def send_telegram_message(
    telegram_token: str,
    chat_id: int | str,
    text: str,
    parse_mode: str | None = None,
) -> None:
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    telegram_api_request(telegram_token, "sendMessage", payload)


def normalize_setup(form: dict[str, str]) -> tuple[bool, str, dict[str, str]]:
    required_fields = {
        "chatgpt_prompt_id": "ChatGPT Prompt ID",
        "telegram_bot_token": "Telegram Bot HTTP API Token",
        "openai_api_key": "OpenAI API Key",
    }
    missing = [
        label for field, label in required_fields.items() if not form.get(field, "").strip()
    ]
    if missing:
        return False, f"Missing fields: {', '.join(missing)}.", {}

    return True, "", {
        "chatgpt_prompt_id": form["chatgpt_prompt_id"].strip(),
        "telegram_bot_token": form["telegram_bot_token"].strip(),
        "openai_api_key": form["openai_api_key"].strip(),
        "openai_model": os.environ.get("OPENAI_MODEL", "gpt-4o").strip(),
        "bot_environment": os.environ.get("BOT_ENVIRONMENT", "sandbox").strip(),
    }


def save_bot_setup(
    handler: BaseHTTPRequestHandler,
    config: dict[str, str],
    telegram_username: str,
    telegram_bot_id: str,
) -> tuple[str, str, str]:
    ensure_data_path()
    bot_id = make_bot_id(telegram_bot_id)
    existing_record = load_bot_record(bot_id)
    webhook_secret = (
        existing_record.get("webhook_secret")
        if isinstance(existing_record, dict) and isinstance(existing_record.get("webhook_secret"), str)
        else secrets.token_urlsafe(32)
    )
    webhook_url = build_webhook_url(handler, bot_id)
    validate_webhook_url(webhook_url)

    set_telegram_webhook(config["telegram_bot_token"], webhook_url, webhook_secret)

    now = int(time.time())
    record = {
        "bot_id": bot_id,
        "telegram_bot_id": telegram_bot_id,
        "telegram_username": telegram_username,
        "webhook_url": webhook_url,
        "webhook_secret": webhook_secret,
        "encrypted_config": encrypt_payload(config),
        "created_at": existing_record.get("created_at", now) if isinstance(existing_record, dict) else now,
        "updated_at": now,
    }
    atomic_write_json(bot_record_path(bot_id), record)
    return bot_id, build_launch_url(handler, bot_id), webhook_url


def parse_form(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def extract_message(update: dict) -> tuple[int | str, str] | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None

    text = message.get("text")
    chat = message.get("chat")
    if not isinstance(text, str) or not text.strip() or not isinstance(chat, dict):
        return None

    chat_id = chat.get("id")
    if not isinstance(chat_id, (int, str)):
        return None

    return chat_id, text.strip()


def process_webhook_update(bot_id: str, update: dict) -> None:
    record = load_bot_record(bot_id)
    if record is None:
        print(f"Ignoring webhook for unknown bot_id={bot_id}", flush=True)
        return

    try:
        config = load_bot_config(record)
    except (InvalidToken, ValueError, json.JSONDecodeError) as error:
        print(f"Unable to load bot config bot_id={bot_id}: {error}", flush=True)
        return

    extracted = extract_message(update)
    if extracted is None:
        print(f"Ignoring unsupported Telegram update bot_id={bot_id}", flush=True)
        return

    chat_id, text = extracted
    telegram_token = config["telegram_bot_token"]

    if text.startswith("/start"):
        send_telegram_message(
            telegram_token,
            chat_id,
            f"ChatGPT on Telegram is active for @{record.get('telegram_username', 'your bot')}.",
        )
        return

    if text.startswith("/hello"):
        send_telegram_message(telegram_token, chat_id, "Hello there")
        return

    print(f"Webhook message bot_id={bot_id} chat_id={chat_id} chars={len(text)}", flush=True)
    try:
        send_telegram_message(telegram_token, chat_id, random_thinking_phrase())
    except ValueError as error:
        print(f"Unable to send thinking message bot_id={bot_id} chat_id={chat_id}: {error}", flush=True)

    session = load_session(bot_id, str(chat_id))
    recent_messages = get_recent_messages(session, int(time.time()))

    answer, _response_id = ask_gpt_stateless(
        text,
        f"{bot_id}:{chat_id}",
        config,
        context_messages=recent_messages,
    )
    save_recent_exchange(bot_id, str(chat_id), recent_messages, text, answer)

    formatted = format_for_telegram(answer)
    try:
        send_telegram_message(telegram_token, chat_id, formatted, parse_mode="HTML")
    except ValueError as error:
        print(f"HTML Telegram send failed bot_id={bot_id} chat_id={chat_id}: {error}", flush=True)
        send_telegram_message(telegram_token, chat_id, answer)


def process_webhook_update_async(bot_id: str, update: dict) -> None:
    thread = threading.Thread(
        target=process_webhook_update,
        args=(bot_id, update),
        name=f"telegram-webhook-{bot_id}",
        daemon=True,
    )
    thread.start()


class AppHandler(BaseHTTPRequestHandler):
    server_version = "ChatGPTOnTelegram/2.0"

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)

        if parsed_url.path == "/":
            self.send_static("/index.html")
            return

        if parsed_url.path.startswith("/assets/"):
            self.send_static(parsed_url.path)
            return

        if parsed_url.path.startswith("/launch/"):
            self.launch_from_url(parsed_url.path.removeprefix("/launch/"))
            return

        if parsed_url.path == "/favicon.ico":
            self.send_static("/assets/favicon.ico")
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        if parsed_url.path == "/setup":
            self.handle_setup()
            return

        if parsed_url.path.startswith("/webhook/"):
            self.handle_webhook(parsed_url.path.removeprefix("/webhook/"))
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def handle_setup(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > MAX_FORM_SIZE:
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"message": "Form is too large."})
            return

        form = parse_form(self.rfile.read(content_length))
        ok, message, config = normalize_setup(form)
        if not ok:
            self.send_json(HTTPStatus.BAD_REQUEST, {"message": message})
            return

        try:
            telegram_username, telegram_bot_id = fetch_bot_identity(config["telegram_bot_token"])
            bot_id, launch_url, webhook_url = save_bot_setup(
                self,
                config,
                telegram_username,
                telegram_bot_id,
            )
        except ValueError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"message": str(error)})
            return

        print(
            "Configured stateless Telegram bot "
            f"bot_id={bot_id} username=@{telegram_username} "
            f"prompt_id={config['chatgpt_prompt_id']} "
            f"telegram_token={mask_secret(config['telegram_bot_token'])} "
            f"openai_key={mask_secret(config['openai_api_key'])} "
            f"webhook={webhook_url}",
            flush=True,
        )
        self.send_json(
            HTTPStatus.OK,
            {
                "message": "Telegram webhook configured. Open the chat to start the bot.",
                "chat_url": launch_url,
                "telegram_url": f"https://t.me/{telegram_username}",
                "bot_id": bot_id,
            },
        )

    def handle_webhook(self, raw_bot_id: str) -> None:
        bot_id = unquote(raw_bot_id)
        record = load_bot_record(bot_id)
        if record is None:
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "Unknown bot."})
            return

        expected_secret = record.get("webhook_secret")
        received_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not isinstance(expected_secret, str) or not hmac.compare_digest(received_secret, expected_secret):
            self.send_json(HTTPStatus.FORBIDDEN, {"ok": False, "message": "Invalid webhook secret."})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > MAX_WEBHOOK_SIZE:
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False})
            return

        try:
            update = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except json.JSONDecodeError:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False})
            return

        if not isinstance(update, dict):
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False})
            return

        process_webhook_update_async(bot_id, update)
        self.send_json(HTTPStatus.OK, {"ok": True})

    def launch_from_url(self, raw_bot_id: str) -> None:
        bot_id = unquote(raw_bot_id)
        record = load_bot_record(bot_id)
        if record is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown bot link.")
            return

        username = record.get("telegram_username")
        if not isinstance(username, str) or not username:
            self.send_error(HTTPStatus.BAD_REQUEST, "Bot username is missing.")
            return

        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", f"https://t.me/{username}")
        self.end_headers()

    def send_html(self, content: str) -> None:
        payload = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_static(self, request_path: str) -> None:
        relative_path = request_path.removeprefix("/").lstrip("/")
        file_path = (PUBLIC_DIR / relative_path).resolve()
        public_root = PUBLIC_DIR.resolve()

        if public_root not in file_path.parents or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        payload = file_path.read_bytes()
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, status: HTTPStatus, payload: dict) -> None:
        response = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s - - %s\n" % (self.address_string(), format % args))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    ensure_data_path()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    host, port = server.server_address
    local_url = f"http://{host}:{port}"
    configured_webhook_base_url = os.environ.get("WEBHOOK_BASE_URL", "").strip().rstrip("/")
    webhook_base_url = configured_webhook_base_url or local_url
    print(f"Serving ChatGPT on Telegram at {local_url}", flush=True)
    print(f"Using DATA_PATH={DATA_DIR}", flush=True)
    print(f"Using WEBHOOK_BASE_URL={webhook_base_url}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
