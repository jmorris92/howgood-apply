"""Submit a job application to HowGood's signed application API.

The API takes a JSON body and an X-HMAC-Signature header holding the hex
HMAC-SHA256 of that exact body, so this script builds the body once, signs
that string, and sends that same string.

The endpoint and signing secret come from HOWGOOD_ENDPOINT and
HOWGOOD_HMAC_SECRET, read from the environment or a local .env file (see
.env.example). The applicant details come from the JSON config file.

Usage:
    python apply.py --config config.json --dry-run   # show payload + signature, send nothing
    python apply.py --config config.json             # submit
"""
import argparse
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

import requests
from pydantic import ValidationError

from models.application_payload import ApplicationPayload
from models.settings import Settings

SUBMITTED_MARKER = Path(".submitted")


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sign(body, secret):
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


def submit(body, signature, endpoint, session=None, retries=3, backoff=1.5, timeout=15):
    """POST the signed body. Retry only network errors and 5xx, never 4xx.

    A 4xx means the request itself is wrong (the API's response body says
    what), so resending the same request would not help.
    """
    session = session or requests.Session()
    headers = {"Content-Type": "application/json", "X-HMAC-Signature": signature}
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = session.post(
                endpoint, data=body.encode("utf-8"), headers=headers, timeout=timeout
            )
        except requests.RequestException as exc:
            last_error = exc
        else:
            if response.status_code < 500:
                return response
            last_error = RuntimeError(f"server error {response.status_code}")
        if attempt < retries:
            time.sleep(backoff ** attempt)
    raise RuntimeError(f"giving up after {retries} attempts: {last_error}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Submit a HowGood application.")
    parser.add_argument("--config", default="config.json", help="path to the config file")
    parser.add_argument("--dry-run", action="store_true", help="print the request, send nothing")
    parser.add_argument("--force", action="store_true", help="submit even if already submitted")
    args = parser.parse_args(argv)

    try:
        settings = Settings()
    except ValidationError as exc:
        print(f"invalid settings (check .env or the environment):\n{exc}", file=sys.stderr)
        return 2
    try:
        payload = ApplicationPayload.model_validate(load_config(args.config))
    except ValidationError as exc:
        print(f"invalid config:\n{exc}", file=sys.stderr)
        return 2

    endpoint = str(settings.endpoint)
    body = payload.model_dump_json(exclude_none=True)
    signature = sign(body, settings.hmac_secret.get_secret_value())

    if args.dry_run:
        print(f"POST {endpoint}")
        print(f"X-HMAC-Signature: {signature}")
        print(json.dumps(json.loads(body), indent=2, ensure_ascii=False))
        return 0

    if SUBMITTED_MARKER.exists() and not args.force:
        print(
            f"already submitted ({SUBMITTED_MARKER.read_text().strip()}); use --force to resend",
            file=sys.stderr,
        )
        return 1

    try:
        response = submit(body, signature, endpoint)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(response.status_code, response.text)
    if response.status_code == 201:
        SUBMITTED_MARKER.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {response.text[:200]}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
