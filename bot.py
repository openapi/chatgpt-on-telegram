import json
import os
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
DEFAULT_MODEL = "gpt-5.5"

BOT_ENVIRONMENT = os.environ.get("BOT_ENVIRONMENT", "sandbox")
CHATGPT_PROMPT_ID = os.environ.get("CHATGPT_PROMPT_ID", "").strip()
OPENAI_API_KEY = (
    os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAPI_API_KEY") or ""
).strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL).strip()

LAST_RESPONSE_IDS: dict[int, str] = {}


def extract_response_text(payload: dict) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    chunks: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)

    if chunks:
        return "\n".join(chunks).strip()

    return "Non ho ricevuto una risposta testuale da GPT."


def extract_error_message(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip() or "Errore sconosciuto"

    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)

    return str(payload)


def ask_gpt(message: str, chat_id: int) -> str:
    if not OPENAI_API_KEY:
        return "Openapi API Key non configurata. Riavvia il bot dalla pagina web."

    request_payload: dict = {"input": message}
    previous_response_id = LAST_RESPONSE_IDS.get(chat_id)
    if previous_response_id:
        request_payload["previous_response_id"] = previous_response_id

    if CHATGPT_PROMPT_ID:
        request_payload["prompt"] = {
            "prompt_id": CHATGPT_PROMPT_ID,
            "variables": {
                "message": message,
                "environment": BOT_ENVIRONMENT,
            },
        }
    else:
        request_payload["model"] = OPENAI_MODEL

    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return f"GPT ha risposto con errore {error.code}: {extract_error_message(body)}"
    except urllib.error.URLError as error:
        return f"Impossibile raggiungere GPT: {error.reason}"
    except TimeoutError:
        return "La richiesta a GPT ha superato il tempo massimo."

    response_id = response_payload.get("id")
    if isinstance(response_id, str):
        LAST_RESPONSE_IDS[chat_id] = response_id

    return extract_response_text(response_payload)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    await update.message.reply_text(
        f"ChatGPT on Telegram e' attivo in modalita' {BOT_ENVIRONMENT}."
    )


async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    first_name = update.effective_user.first_name if update.effective_user else "there"
    await update.message.reply_text(f"Hello {first_name}")


async def answer_with_gpt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return

    chat_id = update.effective_chat.id if update.effective_chat else 0
    answer = ask_gpt(update.message.text, chat_id)
    await update.message.reply_text(answer)


def main() -> None:
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not telegram_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN mancante.")

    app = ApplicationBuilder().token(telegram_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("hello", hello))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer_with_gpt))
    app.run_polling()


if __name__ == "__main__":
    main()
