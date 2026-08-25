# RapidAPI service

A FastAPI application that exposes the Claude watermark remover to RapidAPI
subscribers. It runs as a **separate process** from the Flask site and does not
modify it.

## Why it is separate

The Flask endpoint at `/v1/remove-watermark` authenticates a `cwr_` API key and
meters every call against the caller's Stripe subscription. A RapidAPI
subscriber has neither, so that endpoint would reject them with a 401 before
doing any work.

This service authenticates differently — it trusts the `X-RapidAPI-Proxy-Secret`
header that Rapid adds to forwarded requests — and does no Stripe metering at
all, because Rapid bills the subscriber and pays out separately. Metering here
too would mean paying Stripe for calls someone else is already collecting on.

The cleaning itself is **imported** from the Flask application rather than
reimplemented, so the marketplace listing cannot drift from the behaviour
documented on the website.

## Running it

1. Copy `.env.example` to `.env` and set at least `RAPIDAPI_PROXY_SECRET`
   (Gateway tab of your Rapid listing) and `OPENAI_API_KEY` (for thorough mode).
2. Install and start:

```bash
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

Or install the user systemd unit so it stays up:

```bash
cp deploy/claude-watermark-rapidapi.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now claude-watermark-rapidapi
```

Point the RapidAPI listing's base URL at a **public HTTPS origin** that
proxies to this process (not `localhost`).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `RAPIDAPI_PROXY_SECRET` | *(none)* | Rapid's per-API secret. **Required** — without it the service returns 503 for every request rather than accepting unverified traffic. |
| `RAPIDAPI_THOROUGH_TIERS` | `PRO,ULTRA,MEGA,CUSTOM` | Plans allowed to use `thorough`. Set to an empty string to allow every plan. |
| `RAPIDAPI_MAX_CHARACTERS` | `200000` | Overall input ceiling. |
| `RAPIDAPI_RATE_LIMIT` | `60` | Requests per window, per subscriber. |
| `RAPIDAPI_RATE_WINDOW_SECONDS` | `60` | Length of that window. |

The `OPENAI_*` variables are shared with the Flask app, so one `.env` drives
both processes. `thorough` is unavailable, and returns 503, when no model
credentials are configured.

## Why `thorough` is gated by plan

Every `thorough` call spends real money at the model provider. Rapid listings
normally include a free `BASIC` tier, so leaving `thorough` open there is an
uncapped bill. The default keeps it on paid plans only. When Rapid omits the
`X-RapidAPI-Subscription` header, the request is treated as `BASIC`, so the
check fails closed.

## The OpenAPI document

`GET /openapi.json` returns a spec you can upload directly when creating the
listing, which is faster and more accurate than defining endpoints by hand.
`GET /docs` renders it for local inspection. Neither reveals the proxy secret,
the rewrite model, or any Stripe identifier.

The response models in `schemas.py` are the published contract. Adding a field
is safe; renaming or removing one breaks every existing subscriber.

## Endpoints

- `POST /v1/remove-watermark` — the listed endpoint.
- `GET /health` — liveness and configuration check, for your own monitoring.

## Deployment notes

Some reverse proxies strip unrecognised headers. If `X-RapidAPI-Proxy-Secret`
does not survive the hop from nginx to this process, every request returns 403
`proxy_secret_invalid`. Verify that first if the listing appears dead.

Rate limit state is per process, so running several workers multiplies the
effective limit. Consider a shared store if that matters.

Rapid's threat protection scans request bodies against injection patterns.
This product's entire input is arbitrary pasted text containing unusual
Unicode, which makes false positives unusually likely — consider disabling it
on the listing.

## Tests

```bash
python3 -m pytest tests -q
```
