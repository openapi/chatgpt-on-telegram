# ChatGPT on Telegram

Server Python minimale per avviare un bot Telegram collegato a GPT dalla pagina
web locale `ChatGPT on Telegram`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Avvio

```bash
python server.py
```

Apri `http://127.0.0.1:8000`, compila i campi e premi `Start My Bot`.

I campi sensibili della pagina sono input password. I valori vengono passati al
processo del bot come variabili d'ambiente e non vengono salvati nel repository.
