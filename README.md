# ChatGPT on Telegram

Minimal Python server that launches a Telegram bot connected to GPT from the
local `ChatGPT on Telegram` web page.

## Setup

```bash
make install
```

## Run Locally

```bash
export SERVER_SECRET_KEY="any-private-string"
make start
```

Open `http://127.0.0.1:8000`, fill in `ChatGPT Prompt ID` and
`Telegram Bot HTTP API Token` and `OpenAI API Key`, then create the signed Chat
URL.

The server creates a Chat URL encrypted and signed with `SERVER_SECRET_KEY`.
You can keep that link and open it later to restart the bot with the same setup;
after startup it redirects to the bot's Telegram chat.

Sensitive fields on the page use password inputs. Values are not stored in a
database.

## Run With Docker

```bash
export SERVER_SECRET_KEY="any-private-string"
make docker-start
```

The app is exposed at `http://127.0.0.1:8000`.
