# ChatGPT on Telegram

Minimal Python server that launches a Telegram bot connected to GPT from the
local `ChatGPT on Telegram` web page.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run Locally

```bash
export OPENAI_API_KEY="sk-..."
export SERVER_SECRET_KEY="use-a-fernet-key-here"
python server.py
```

Open `http://127.0.0.1:8000`, fill in `ChatGPT Prompt ID` and
`Telegram Bot HTTP API Token`, then press `Start My Bot`.

The server creates a Super URL encrypted and signed with `SERVER_SECRET_KEY`.
You can keep that link and open it later to restart the bot with the same setup;
after startup it redirects to the bot's Telegram chat.

Sensitive fields on the page use password inputs. Values are not stored in a
database.

Generate a valid server secret with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Run With Docker

```bash
export OPENAI_API_KEY="sk-..."
export SERVER_SECRET_KEY="use-a-fernet-key-here"
docker compose -f compose.yml up --build
```

The app is exposed at `http://127.0.0.1:8000`.
