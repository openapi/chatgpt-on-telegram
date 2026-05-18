import argparse
import atexit
import json
import os
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs


BASE_DIR = Path(__file__).resolve().parent
BOT_FILE = BASE_DIR / "bot.py"
LOG_FILE = BASE_DIR / "bot.log"
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
      --page: #f5f7fb;
      --panel: #ffffff;
      --ink: #18202f;
      --muted: #637085;
      --line: #d9e0ea;
      --blue: #2481cc;
      --green: #12a884;
      --dark: #202938;
      --focus: #f1b642;
      --danger: #b42318;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--page);
    }

    main {
      width: min(960px, calc(100% - 32px));
      margin: 0 auto;
      padding: 56px 0;
    }

    .shell {
      display: grid;
      gap: 28px;
    }

    .masthead {
      display: grid;
      gap: 18px;
      justify-items: center;
      text-align: center;
    }

    h1 {
      margin: 0;
      font-size: clamp(36px, 7vw, 72px);
      line-height: 0.95;
      letter-spacing: 0;
    }

    .equation {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: center;
      gap: 10px;
      color: var(--muted);
      font-weight: 700;
    }

    .brand {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 44px;
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--dark);
      box-shadow: 0 8px 22px rgba(24, 32, 47, 0.06);
    }

    .mark {
      display: grid;
      width: 28px;
      height: 28px;
      place-items: center;
      border-radius: 50%;
      color: #fff;
      font-size: 14px;
      font-weight: 800;
    }

    .mark.chatgpt {
      background: var(--green);
    }

    .mark.telegram {
      background: var(--blue);
    }

    .mark.openapi {
      background: var(--dark);
    }

    .mark.emoji {
      background: #ffe2a9;
      color: #1f2937;
      font-size: 18px;
    }

    .operator {
      min-width: 18px;
      color: var(--dark);
      font-size: 20px;
    }

    .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 18px 48px rgba(24, 32, 47, 0.08);
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
      color: var(--green);
    }

    @media (max-width: 720px) {
      main {
        width: min(100% - 24px, 960px);
        padding: 32px 0;
      }

      .grid {
        grid-template-columns: 1fr;
      }

      form {
        padding: 18px;
      }

      .brand {
        flex: 1 1 42%;
        justify-content: center;
      }

      .operator {
        display: none;
      }

      .action-row,
      button {
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
          <span class="brand"><span class="mark chatgpt">C</span>ChatGPT</span>
          <span class="operator">+</span>
          <span class="brand"><span class="mark telegram">T</span>Telegram</span>
          <span class="operator">=</span>
          <span class="brand"><span class="mark openapi">O</span>Openapi</span>
          <span class="operator">+</span>
          <span class="brand"><span class="mark emoji">😎</span></span>
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

          <div class="grid">
            <div class="field">
              <label for="bot_environment">Environment</label>
              <select id="bot_environment" name="bot_environment" required>
                <option value="prod">Prod</option>
                <option value="sandbox">Sandbox</option>
              </select>
            </div>

            <div class="field">
              <label for="openapi_api_key">Openapi API Key</label>
              <input id="openapi_api_key" name="openapi_api_key" type="password" autocomplete="off" spellcheck="false" required>
            </div>
          </div>

          <div class="action-row">
            <div id="status" class="status" role="status" aria-live="polite"></div>
            <button id="start-button" type="submit">Start My Bot</button>
          </div>
        </form>
      </section>
    </div>
  </main>

  <script>
    const form = document.querySelector("#bot-form");
    const button = document.querySelector("#start-button");
    const statusBox = document.querySelector("#status");

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
      } catch (error) {
        statusBox.textContent = "Errore durante l'avvio del bot.";
        statusBox.className = "status error";
      } finally {
        button.disabled = false;
      }
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


def start_bot(form: dict[str, str]) -> tuple[bool, str]:
    global BOT_PROCESS

    required_fields = {
        "chatgpt_prompt_id": "ChatGPT Prompt ID",
        "telegram_bot_token": "Telegram Bot HTTP API Token",
        "openapi_api_key": "Openapi API Key",
    }
    missing = [
        label for field, label in required_fields.items() if not form.get(field, "").strip()
    ]
    if missing:
        return False, f"Campi mancanti: {', '.join(missing)}."

    bot_environment = form.get("bot_environment", "sandbox").strip().lower()
    if bot_environment not in {"prod", "sandbox"}:
        return False, "Environment non valido."

    stop_bot()

    env = os.environ.copy()
    env.update(
        {
            "BOT_ENVIRONMENT": bot_environment,
            "CHATGPT_PROMPT_ID": form["chatgpt_prompt_id"].strip(),
            "TELEGRAM_BOT_TOKEN": form["telegram_bot_token"].strip(),
            "OPENAPI_API_KEY": form["openapi_api_key"].strip(),
            "OPENAI_API_KEY": form["openapi_api_key"].strip(),
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

    return True, f"Bot avviato. PID {BOT_PROCESS.pid}."


def parse_form(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


class AppHandler(BaseHTTPRequestHandler):
    server_version = "ChatGPTOnTelegram/1.0"

    def do_GET(self) -> None:
        if self.path == "/":
            self.send_html(HTML_PAGE)
            return

        if self.path == "/status":
            running = BOT_PROCESS is not None and BOT_PROCESS.poll() is None
            self.send_json(
                HTTPStatus.OK,
                {
                    "running": running,
                    "pid": BOT_PROCESS.pid if running and BOT_PROCESS else None,
                },
            )
            return

        if self.path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/start":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > MAX_FORM_SIZE:
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"message": "Form troppo grande."})
            return

        form = parse_form(self.rfile.read(content_length))
        ok, message = start_bot(form)
        self.send_json(HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST, {"message": message})

    def send_html(self, content: str) -> None:
        payload = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
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
