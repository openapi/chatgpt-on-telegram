import argparse
import atexit
import base64
import hashlib
import json
import mimetypes
import os
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
import urllib.error
import urllib.request

from cryptography.fernet import Fernet, InvalidToken


BASE_DIR = Path(__file__).resolve().parent
BOT_FILE = BASE_DIR / "bot.py"
LOG_FILE = BASE_DIR / "bot.log"
PUBLIC_DIR = BASE_DIR / "public"
MAX_FORM_SIZE = 64 * 1024
BOT_PROCESS: subprocess.Popen | None = None


def get_bot_python() -> str:
    venv_python = BASE_DIR / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)

    return sys.executable


def get_server_fernet() -> Fernet:
    env_key = os.environ.get("SERVER_SECRET_KEY", "").strip()
    if not env_key:
        raise ValueError("SERVER_SECRET_KEY mancante.")

    key = base64.urlsafe_b64encode(hashlib.sha256(env_key.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_setup(config: dict[str, str]) -> str:
    payload = json.dumps(config, separators=(",", ":")).encode("utf-8")
    return get_server_fernet().encrypt(payload).decode("utf-8")


def decrypt_setup(token: str) -> dict[str, str]:
    payload = get_server_fernet().decrypt(token.encode("utf-8"))
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("Payload non valido.")

    return {str(key): str(value) for key, value in decoded.items()}


def get_origin(handler: BaseHTTPRequestHandler) -> str:
    forwarded_proto = handler.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    scheme = forwarded_proto or "http"
    host = handler.headers.get("Host") or f"{handler.server.server_address[0]}:{handler.server.server_address[1]}"
    return f"{scheme}://{host}"


def build_launch_url(handler: BaseHTTPRequestHandler, config: dict[str, str]) -> str:
    token = encrypt_setup(config)
    return f"{get_origin(handler)}/launch/{quote(token, safe='')}"


def fetch_bot_username(telegram_token: str) -> str:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{telegram_token}/getMe",
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise ValueError(f"Telegram ha risposto con errore {error.code}: {body}") from error
    except urllib.error.URLError as error:
        raise ValueError(f"Impossibile contattare Telegram: {error.reason}") from error

    username = payload.get("result", {}).get("username")
    if not payload.get("ok") or not isinstance(username, str) or not username:
        raise ValueError("Token Telegram valido ma username bot non trovato.")

    return username


def stop_bot() -> None:
    global BOT_PROCESS

    if BOT_PROCESS is None:
        return

    if BOT_PROCESS.poll() is None:
        BOT_PROCESS.terminate()
        try:
            BOT_PROCESS.wait(timeout=5)
        except subprocess.TimeoutExpired:
            BOT_PROCESS.kill()
            BOT_PROCESS.wait(timeout=5)

    BOT_PROCESS = None


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
        return False, f"Campi mancanti: {', '.join(missing)}.", {}

    return True, "", {
        "chatgpt_prompt_id": form["chatgpt_prompt_id"].strip(),
        "telegram_bot_token": form["telegram_bot_token"].strip(),
        "openai_api_key": form["openai_api_key"].strip(),
    }


def start_bot(config: dict[str, str]) -> tuple[bool, str, str | None]:
    global BOT_PROCESS

    ok, message, normalized = normalize_setup(config)
    if not ok:
        return False, message, None

    try:
        username = fetch_bot_username(normalized["telegram_bot_token"])
    except ValueError as error:
        return False, str(error), None

    stop_bot()

    env = os.environ.copy()
    env.update(
        {
            "CHATGPT_PROMPT_ID": normalized["chatgpt_prompt_id"],
            "TELEGRAM_BOT_TOKEN": normalized["telegram_bot_token"],
            "OPENAI_API_KEY": normalized["openai_api_key"],
        }
    )

    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write("\n--- Starting ChatGPT on Telegram bot ---\n")
        BOT_PROCESS = subprocess.Popen(
            [get_bot_python(), str(BOT_FILE)],
            cwd=str(BASE_DIR),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )

    return True, f"Bot avviato. PID {BOT_PROCESS.pid}.", username


def parse_form(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


class AppHandler(BaseHTTPRequestHandler):
    server_version = "ChatGPTOnTelegram/1.0"

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
        if parsed_url.path != "/setup":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > MAX_FORM_SIZE:
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"message": "Form troppo grande."})
            return

        form = parse_form(self.rfile.read(content_length))
        ok, message, config = normalize_setup(form)
        if not ok:
            self.send_json(HTTPStatus.BAD_REQUEST, {"message": message})
            return

        try:
            launch_url = build_launch_url(self, config)
        except ValueError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"message": str(error)})
            return

        self.send_json(
            HTTPStatus.OK,
            {
                "message": "Chat URL creato. Aprilo per avviare il bot.",
                "chat_url": launch_url,
            },
        )

    def launch_from_url(self, token: str) -> None:
        try:
            config = decrypt_setup(unquote(token))
        except (InvalidToken, ValueError, json.JSONDecodeError):
            self.send_error(HTTPStatus.BAD_REQUEST, "Link non valido o non decifrabile.")
            return

        ok, message, username = start_bot(config)
        if not ok or username is None:
            self.send_html(
                f"""<!doctype html>
<html lang="it">
<meta charset="utf-8">
<title>ChatGPT on Telegram</title>
<body>
  <h1>ChatGPT on Telegram</h1>
  <p>{message}</p>
</body>
</html>"""
            )
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

    atexit.register(stop_bot)

    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    host, port = server.server_address
    print(f"Serving ChatGPT on Telegram at http://{host}:{port}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        stop_bot()


if __name__ == "__main__":
    main()
