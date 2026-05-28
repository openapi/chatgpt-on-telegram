#!make

# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
#                                                                             #
#      ____                               _                                   #
#     / __ \____  ___  ____  ____ _____  (_) ®                                #
#    / / / / __ \/ _ \/ __ \/ __ `/ __ \/ /                                   #
#   / /_/ / /_/ /  __/ / / / /_/ / /_/ / /                                    #
#   \____/ .___/\___/_/ /_/\__,_/ .___/_/                                     #
#       /_/                    /_/                                            #
#                                                                             #
#   The Largest Certified API Marketplace                                     #
#   Accelerate Digital Transformation • Simplify Processes • Lead Industry    #
#                                                                             #
#   ═══════════════════════════════════════════════════════════════════════   #
#                                                                             #
#   Project:        chatgpt-on-telegram                                       #
#   Version:        0.1.1                                                     #
#   Author:         Francesco Bianco (@francescobianco)                       #
#   Copyright:      (c) 2025 Openapi®. All rights reserved.                   #
#   License:        MIT                                                       #
#   Maintainer:     Francesco Bianco                                          #
#   Contact:        https://openapi.com/                                      #
#   Repository:     https://github.com/openapi/chatgpt-on-telegram            #
#   Documentation:  https://github.com/openapi/chatgpt-on-telegram            #
#                                                                             #
#   ═══════════════════════════════════════════════════════════════════════   #
#                                                                             #
#   "Truth lies at the source of the stream."                                 #
#                                  — English Proverb                          #
#                                                                             #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

PYTHON ?= ./.venv/bin/python
PIP ?= ./.venv/bin/python -m pip
HOST ?= 127.0.0.1
PORT ?= 8000
SERVER_SECRET_KEY ?= local-development-secret
DATA_PATH ?= ./data
NGROK_DOMAIN ?=
WEBHOOK_BASE_URL ?=
NGROK_API_URL ?= http://127.0.0.1:4040/api/tunnels

.PHONY: install kill-old start test docker-start docker-stop

install:
	python3 -m venv .venv
	$(PIP) install -r requirements.txt

kill-old:
	@pkill -f "$(CURDIR)/[s]erver.py" || true

start: kill-old
	@set -eu; \
	WEBHOOK_URL="$$(NGROK_DOMAIN="$(NGROK_DOMAIN)" NGROK_API_URL="$(NGROK_API_URL)" PORT="$(PORT)" python3 scripts/resolve_ngrok_url.py)"; \
	WEBHOOK_BASE_URL="$$WEBHOOK_URL" SERVER_SECRET_KEY="$(SERVER_SECRET_KEY)" DATA_PATH="$(DATA_PATH)" $(PYTHON) server.py --host $(HOST) --port $(PORT)

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

docker-start:
	@if [ -z "$(WEBHOOK_BASE_URL)" ]; then \
		echo "WEBHOOK_BASE_URL is required for Docker/prod because Telegram webhooks require HTTPS."; \
		echo "Example: make docker-start WEBHOOK_BASE_URL=https://example.com"; \
		exit 1; \
	fi
	SERVER_SECRET_KEY="$(SERVER_SECRET_KEY)" WEBHOOK_BASE_URL="$(WEBHOOK_BASE_URL)" DATA_PATH="$(DATA_PATH)" docker compose -f compose.yml up --build

docker-stop:
	docker compose -f compose.yml down
