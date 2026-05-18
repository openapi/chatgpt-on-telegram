import argparse
import atexit
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


HTML_PAGE = """<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ChatGPT on Telegram</title>
  <style>
    :root {
      color-scheme: light;
      --page: #eef3f8;
      --panel: #ffffff;
      --ink: #18202f;
      --muted: #637085;
      --line: #d9e0ea;
      --blue: #2481cc;
      --green: #12a884;
      --dark: #202938;
      --focus: #f1b642;
      --danger: #b42318;
      --ok: #087f5b;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 20% 12%, rgba(18, 168, 132, 0.12), transparent 32%),
        radial-gradient(circle at 82% 4%, rgba(36, 129, 204, 0.14), transparent 30%),
        var(--page);
    }

    main {
      width: min(1040px, calc(100% - 32px));
      margin: 0 auto;
      padding: 56px 0;
    }

    .shell {
      display: grid;
      gap: 24px;
    }

    .masthead {
      display: grid;
      gap: 20px;
      justify-items: center;
      text-align: center;
    }

    h1 {
      margin: 0;
      font-size: clamp(36px, 7vw, 72px);
      line-height: 0.96;
      letter-spacing: 0;
    }

    .equation {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: center;
      gap: 12px;
      color: var(--muted);
      font-weight: 700;
    }

    .brand {
      display: grid;
      width: 72px;
      height: 72px;
      place-items: center;
      border: 1px solid var(--line);
      border-radius: 22px;
      background: rgba(255, 255, 255, 0.86);
      color: var(--dark);
      box-shadow: 0 18px 36px rgba(24, 32, 47, 0.11);
    }

    .brand img {
      width: 42px;
      height: 42px;
      object-fit: contain;
    }

    .operator {
      min-width: 20px;
      color: var(--dark);
      font-size: 28px;
      font-weight: 900;
    }

    .emoji {
      font-size: 38px;
      line-height: 1;
    }

    .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: 0 18px 48px rgba(24, 32, 47, 0.08);
      overflow: hidden;
      backdrop-filter: blur(14px);
    }

    form {
      display: grid;
      gap: 18px;
      padding: 24px;
    }

    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 18px;
      align-items: end;
    }

    .field {
      display: grid;
      gap: 8px;
    }

    label {
      color: var(--muted);
      font-size: 14px;
      font-weight: 700;
    }

    input,
    select {
      width: 100%;
      min-height: 48px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 14px;
      color: var(--ink);
      background: #fff;
      font: inherit;
      outline: none;
    }

    input:focus,
    select:focus {
      border-color: var(--focus);
      box-shadow: 0 0 0 3px rgba(241, 182, 66, 0.22);
    }

    .action-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding-top: 4px;
    }

    button {
      min-height: 48px;
      border: 0;
      border-radius: 8px;
      padding: 0 20px;
      color: #fff;
      background: var(--dark);
      font: inherit;
      font-weight: 800;
      cursor: pointer;
    }

    button:hover {
      background: #111827;
    }

    button:disabled {
      cursor: wait;
      opacity: 0.72;
    }

    .status {
      min-height: 24px;
      color: var(--muted);
      font-size: 14px;
      font-weight: 700;
    }

    .status.error {
      color: var(--danger);
    }

    .status.ok {
      color: var(--ok);
    }

    .launch-box {
      display: none;
      gap: 12px;
      padding: 18px 24px 24px;
      border-top: 1px solid var(--line);
      background: #f8fafc;
    }

    .launch-box.visible {
      display: grid;
    }

    .launch-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto auto;
      gap: 10px;
      align-items: center;
    }

    .launch-row input {
      color: var(--muted);
      background: #fff;
    }

    .icon-button,
    .open-link {
      display: grid;
      width: 48px;
      height: 48px;
      place-items: center;
      border-radius: 8px;
      color: #fff;
      background: var(--dark);
      text-decoration: none;
    }

    .icon-button svg,
    .open-link svg {
      width: 20px;
      height: 20px;
      stroke: currentColor;
    }

    @media (max-width: 720px) {
      main {
        width: min(100% - 24px, 1040px);
        padding: 32px 0;
      }

      .grid {
        grid-template-columns: 1fr;
      }

      form {
        padding: 18px;
      }

      .brand {
        width: 58px;
        height: 58px;
        border-radius: 18px;
      }

      .brand img {
        width: 34px;
        height: 34px;
      }

      .operator {
        display: none;
      }

      .action-row,
      button,
      .launch-row {
        width: 100%;
      }

      .launch-row {
        grid-template-columns: 1fr;
      }

      .icon-button,
      .open-link {
        width: 100%;
      }
    }
  </style>
</head>
<body>
  <main>
    <div class="shell">
      <section class="masthead" aria-labelledby="page-title">
        <h1 id="page-title">ChatGPT on Telegram</h1>
        <div class="equation" aria-label="ChatGPT plus Telegram uguale Openapi plus emoji con occhiali da sole">
          <span class="brand" title="ChatGPT"><img src="/assets/images/chatgpt.png" alt="ChatGPT"></span>
          <span class="operator">+</span>
          <span class="brand" title="Telegram"><img src="/assets/images/telegram.png" alt="Telegram"></span>
          <span class="operator">=</span>
          <span class="brand" title="Openapi"><img src="/assets/images/openapi.png" alt="Openapi"></span>
          <span class="operator">+</span>
          <span class="brand" title="Cool"><span class="emoji" aria-label="Emoji con occhiali da sole">😎</span></span>
        </div>
      </section>

      <section class="panel" aria-label="Configurazione bot">
        <form id="bot-form" method="post" action="/start">
          <div class="field">
            <label for="chatgpt_prompt_id">ChatGPT Prompt ID</label>
            <input id="chatgpt_prompt_id" name="chatgpt_prompt_id" type="password" autocomplete="off" spellcheck="false" required>
          </div>

          <div class="field">
            <label for="telegram_bot_token">Telegram Bot HTTP API Token</label>
            <input id="telegram_bot_token" name="telegram_bot_token" type="password" autocomplete="off" spellcheck="false" required>
          </div>

          <div class="action-row">
            <div id="status" class="status" role="status" aria-live="polite"></div>
            <button id="start-button" type="submit">Start My Bot</button>
          </div>
        </form>

        <div id="launch-box" class="launch-box" aria-label="Super URL generato">
          <label for="launch-url">Super URL</label>
          <div class="launch-row">
            <input id="launch-url" type="password" readonly>
            <button id="copy-link" class="icon-button" type="button" title="Copia link" aria-label="Copia link">
              <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <rect x="9" y="9" width="13" height="13" rx="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
            </button>
            <a id="open-link" class="open-link" href="#" title="Apri link" aria-label="Apri link">
              <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M15 3h6v6"></path>
                <path d="M10 14 21 3"></path>
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
              </svg>
            </a>
          </div>
        </div>
      </section>
    </div>
  </main>

  <script>
    const form = document.querySelector("#bot-form");
    const button = document.querySelector("#start-button");
    const statusBox = document.querySelector("#status");
    const launchBox = document.querySelector("#launch-box");
    const launchUrl = document.querySelector("#launch-url");
    const copyLink = document.querySelector("#copy-link");
    const openLink = document.querySelector("#open-link");

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      button.disabled = true;
      statusBox.className = "status";
      statusBox.textContent = "Starting...";

      try {
        const response = await fetch("/start", {
          method: "POST",
          body: new URLSearchParams(new FormData(form)),
        });
        const payload = await response.json();
        statusBox.textContent = payload.message;
        statusBox.className = response.ok ? "status ok" : "status error";
        if (response.ok && payload.launch_url) {
          launchUrl.value = payload.launch_url;
          openLink.href = payload.launch_url;
          launchBox.classList.add("visible");
        }
      } catch (error) {
        statusBox.textContent = "Errore durante l'avvio del bot.";
        statusBox.className = "status error";
      } finally {
        button.disabled = false;
      }
    });

    copyLink.addEventListener("click", async () => {
      if (!launchUrl.value) {
        return;
      }

      await navigator.clipboard.writeText(launchUrl.value);
      statusBox.textContent = "Link copiato.";
      statusBox.className = "status ok";
    });
  </script>
</body>
</html>
"""


def get_bot_python() -> str:
    venv_python = BASE_DIR / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)

    return sys.executable


def get_server_fernet() -> Fernet:
    env_key = os.environ.get("SERVER_SECRET_KEY", "").strip()
    if not env_key:
        raise ValueError("SERVER_SECRET_KEY mancante.")

    return Fernet(env_key.encode("utf-8"))


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
    }
    missing = [
        label for field, label in required_fields.items() if not form.get(field, "").strip()
    ]
    if missing:
        return False, f"Campi mancanti: {', '.join(missing)}.", {}

    return True, "", {
        "chatgpt_prompt_id": form["chatgpt_prompt_id"].strip(),
        "telegram_bot_token": form["telegram_bot_token"].strip(),
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
            self.send_html(HTML_PAGE)
            return

        if parsed_url.path.startswith("/assets/"):
            self.send_static(parsed_url.path)
            return

        if parsed_url.path.startswith("/launch/"):
            self.launch_from_url(parsed_url.path.removeprefix("/launch/"))
            return

        if parsed_url.path == "/status":
            running = BOT_PROCESS is not None and BOT_PROCESS.poll() is None
            self.send_json(
                HTTPStatus.OK,
                {
                    "running": running,
                    "pid": BOT_PROCESS.pid if running and BOT_PROCESS else None,
                },
            )
            return

        if parsed_url.path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        if parsed_url.path != "/start":
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

        ok, message, username = start_bot(config)
        if not ok:
            self.send_json(HTTPStatus.BAD_REQUEST, {"message": message})
            return

        self.send_json(
            HTTPStatus.OK,
            {
                "message": message,
                "launch_url": launch_url,
                "telegram_url": f"https://t.me/{username}",
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
