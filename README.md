# HowGood application client

A small command line client that submits a job application to HowGood's signed application API, as described on their how-to page. It is the code behind my application for the Senior Python Engineer role.

## Usage

```
pip install -r requirements.txt
cp config.example.json config.json   # your applicant details
cp .env.example .env                 # the endpoint and signing key
python apply.py --config config.json --dry-run
python apply.py --config config.json
```

`--dry-run` prints the exact request (URL, signature header, payload) and sends nothing. The signing key lives in `.env` (or a real environment variable), never in the config file, and `.env` is listed in `.gitignore`, so it is not part of this repo. `config.json` holds personal details and is ignored too.

## Settings

| Variable | Meaning |
|---|---|
| `HOWGOOD_ENDPOINT` | URL of the application API |
| `HOWGOOD_HMAC_SECRET` | key used to sign the request body |

Real environment variables take precedence over `.env`. The endpoint comes from settings, so tests and local runs can point at a different server.

## How it works

- `Settings` (in `models/settings.py`) reads the endpoint and signing key with `pydantic-settings` and keeps the key as a `SecretStr`, so it never shows up in a printout.
- `ApplicationPayload` (in `models/application_payload.py`, one model per file) is a Pydantic model of the API's documented request body. It rejects missing or blank required fields and non-integer years before any network call, and it ignores unknown keys in the config.
- The body is built once with `model_dump_json`. `sign` computes the HMAC-SHA256 of that exact string, and `submit` sends that same string, so the signature always matches what the server receives.
- `submit` retries network errors and 5xx responses with backoff. It does not retry 4xx responses: the API describes what is wrong in the response body, so resending the same request would not help.
- A successful submission writes a `.submitted` marker, and a second run refuses to send unless `--force` is passed, so a rerun does not create a duplicate application.

## Tests

```
python -m unittest -v
```

The tests cover model and settings validation (including `.env` loading and precedence), the signature against an independently computed HMAC, the retry rules, the submit guard, and that the signed body is the body sent. They mock the HTTP layer and never call the real API.

## Development note

Drafted with Claude Code and reviewed line by line by me.
