<div align="center">
  <a href="https://openapi.com/">
    <img alt="Openapi CLI" src=".github/assets/images/repo-header.png" >
  </a>

  <h1>ChatGPT on Telegram</h1>
  <h4>Connect Telegram bots to GPT with the power of certified <a href="https://openapi.com/">Openapi®</a> APIs</h4>

[![License](https://img.shields.io/github/license/openapi/chatgpt-on-telegram?ts=1771243284)](LICENSE)
[![Linux Foundation Member](https://img.shields.io/badge/Linux%20Foundation-Silver%20Member-003778?logo=linux-foundation&logoColor=white)](https://www.linuxfoundation.org/about/members)
</div>

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

## Contributing

Contributions are always welcome! Whether you want to report bugs, suggest new features, improve documentation, or contribute code, your help is appreciated.

## Authors

- Openapi Team ([@openapi-it](https://github.com/openapi-it))

## Partners

Meet our partners using Openapi or contributing to this project:

- [Blank](https://www.blank.app/)
- [Credit Safe](https://www.creditsafe.com/)
- [Deliveroo](https://deliveroo.it/)
- [Gruppo MOL](https://molgroupitaly.it/it/)
- [Jakala](https://www.jakala.com/)
- [Octotelematics](https://www.octotelematics.com/)
- [OTOQI](https://otoqi.com/)
- [PWC](https://www.pwc.com/)
- [QOMODO S.R.L.](https://www.qomodo.me/)
- [SOUNDREEF S.P.A.](https://www.soundreef.com/)

## Our Commitments

We believe in open source and we act on that belief. We became Silver Members
of the Linux Foundation because we wanted to formally support the ecosystem
we build on every day. Open standards, open collaboration, and open governance
are part of how we work and how we think about software.

## License

This project is licensed under the [MIT License](LICENSE).

The MIT License is a permissive open-source license that allows you to freely use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the software, provided that the original copyright notice and this permission notice are included in all copies or substantial portions of the software.

For more details, see the full license text at the [MIT License page](https://choosealicense.com/licenses/mit/).
