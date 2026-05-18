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

.PHONY: install start docker-start docker-stop

install:
	python3 -m venv .venv
	$(PIP) install -r requirements.txt

start:
	SERVER_SECRET_KEY="$(SERVER_SECRET_KEY)" OPENAI_API_KEY="$(OPENAI_API_KEY)" $(PYTHON) server.py --host $(HOST) --port $(PORT)

docker-start:
	SERVER_SECRET_KEY="$(SERVER_SECRET_KEY)" OPENAI_API_KEY="$(OPENAI_API_KEY)" docker compose -f compose.yml up --build

docker-stop:
	docker compose -f compose.yml down
