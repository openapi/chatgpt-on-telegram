# ChatGPT on Telegram

Minimal Python server that connects Telegram bots to GPT through a stateless
webhook flow. The server does not keep one process alive for each bot: setup
registers a Telegram webhook, and each Telegram update is processed by the
single HTTP server instance.

## Setup

```bash
make install
```

## Run Locally

Telegram webhooks require a public HTTPS URL. For local development, `make start`
can start ngrok automatically when `NGROK_DOMAIN` is not provided. It reads the
HTTPS tunnel from the local ngrok API and exports it as `WEBHOOK_BASE_URL` for
the server process.

```bash
export SERVER_SECRET_KEY="any-private-string"
export DATA_PATH="./data"
make start
```

If you already have a fixed ngrok domain, pass it explicitly. `make start` will
start ngrok with that domain using `ngrok http --domain <domain> 8000` and will
add `https://` to `WEBHOOK_BASE_URL` when omitted.

```bash
make start NGROK_DOMAIN="your-domain.ngrok-free.app"
make start NGROK_DOMAIN="https://your-domain.ngrok-free.app"
```

On startup the server prints the effective `WEBHOOK_BASE_URL`, so you can verify
that the webhook origin is the expected public HTTPS URL.

Open `http://127.0.0.1:8000`, fill in `ChatGPT Prompt ID`,
`Telegram Bot HTTP API Token` and `OpenAI API Key`, then create the bot link.

During setup the server:

- validates the Telegram token with `getMe`
- stores the encrypted bot configuration under `DATA_PATH`
- registers a Telegram webhook at `/webhook/<bot-id>`
- returns a `/launch/<bot-id>` link that redirects to the Telegram chat

In production or Docker, configure `WEBHOOK_BASE_URL` directly with the external
HTTPS origin that Telegram can reach. Do not include `/webhook/...`; the server
adds the webhook path itself.

```bash
export WEBHOOK_BASE_URL="https://example.com"
```

If you run behind a reverse proxy, `WEBHOOK_BASE_URL` should be the public HTTPS
origin of that proxy.

## Runtime Storage

`DATA_PATH` defaults to `./data`. It contains encrypted bot payloads and encrypted chat
session state. Mount it to persistent external storage in production.

Conversation context is not kept forever: the server stores chat history with
timestamps and sends only messages from the last hour as context. Older messages
are not sent back to OpenAI.

Sensitive fields are encrypted at rest with `SERVER_SECRET_KEY`. Keep that key
stable across restarts or existing bot configurations cannot be decrypted.

## Run With Docker

```bash
export SERVER_SECRET_KEY="any-private-string"
export WEBHOOK_BASE_URL="https://example.com"
export DATA_PATH="./data"
make docker-start
```

The app is exposed at `http://127.0.0.1:8000`. In `compose.yml`, host
`DATA_PATH` is mounted into the container at `CONTAINER_DATA_PATH`
(default `/data`). The container reads its storage location from the `DATA_PATH`
environment variable.
