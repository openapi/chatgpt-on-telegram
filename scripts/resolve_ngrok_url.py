#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request


def normalize_domain(value: str) -> str:
    value = value.strip().rstrip("/")
    if value.startswith(("http://", "https://")):
        return value.replace("http://", "https://", 1)
    return f"https://{value}"


def domain_host(value: str) -> str:
    if not value:
        return ""
    return urllib.parse.urlparse(normalize_domain(value)).netloc


def read_ngrok_urls(api_url: str) -> list[str]:
    try:
        with urllib.request.urlopen(api_url, timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []

    urls: list[str] = []
    for tunnel in payload.get("tunnels", []):
        public_url = tunnel.get("public_url", "")
        if isinstance(public_url, str) and public_url.startswith("https://"):
            urls.append(public_url.rstrip("/"))
    return urls


def matching_url(urls: list[str], requested_domain: str) -> str:
    if not urls:
        return ""
    if not requested_domain:
        return urls[0]

    expected_host = domain_host(requested_domain)
    for url in urls:
        if urllib.parse.urlparse(url).netloc == expected_host:
            return url
    return ""


def start_ngrok(port: str, requested_domain: str, log_path: str) -> None:
    command = ["ngrok", "http"]
    if requested_domain:
        command.extend(["--domain", domain_host(requested_domain)])
    command.append(port)

    print("Starting " + " ".join(command) + "...", file=sys.stderr)
    with open(log_path, "ab") as log_file:
        subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def main() -> int:
    requested_domain = os.environ.get("NGROK_DOMAIN", "").strip()
    api_url = os.environ.get("NGROK_API_URL", "http://127.0.0.1:4040/api/tunnels")
    port = os.environ.get("PORT", "8000")
    log_path = os.environ.get("NGROK_LOG_PATH", "/tmp/chatgpt-on-telegram-ngrok.log")

    if shutil.which("ngrok") is None:
        print(
            "ngrok is required for make start. Install ngrok or configure WEBHOOK_BASE_URL manually for Docker/prod.",
            file=sys.stderr,
        )
        return 1

    urls = read_ngrok_urls(api_url)
    public_url = matching_url(urls, requested_domain)
    if public_url:
        print(public_url)
        return 0

    start_ngrok(port, requested_domain, log_path)

    for _ in range(15):
        time.sleep(1)
        urls = read_ngrok_urls(api_url)
        public_url = matching_url(urls, requested_domain)
        if public_url:
            print(public_url)
            return 0

    if requested_domain:
        expected = normalize_domain(requested_domain)
        print(f"Unable to discover requested ngrok tunnel {expected}. See {log_path}", file=sys.stderr)
    else:
        print(f"Unable to discover ngrok HTTPS tunnel. See {log_path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
