# Claude Watermark Remover API

Detect and remove hidden Unicode characters from AI-generated text (zero-width
spaces, soft hyphens, word joiners, byte order marks, stray joiners, and
variation selectors), with a full report of what changed.

Emoji sequences are preserved: marks that belong to multi-code-point emoji are
reported but not removed.

---

## Base URL

Call the API through RapidAPI (not the origin server directly):

```
https://{your-api-host}.p.rapidapi.com
```

Use the host shown in your RapidAPI subscription dashboard / code snippets.

---

## Authentication

Every request must include your RapidAPI application key:

| Header | Required | Description |
|---|---|---|
| `X-RapidAPI-Key` | Yes | Your RapidAPI key |
| `X-RapidAPI-Host` | Yes | The API host from your RapidAPI subscription |
| `Content-Type` | Yes | `application/json` |

RapidAPI authenticates you and forwards the request. You do **not** receive or
send a proxy secret.

---

## Endpoint

### `POST /v1/remove-watermark`

Clean text and return a structured report.

#### Request body

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | Yes | — | Plain text to clean, exactly as copied |
| `mode` | string | No | `"careful"` | `"careful"` or `"thorough"` |

##### Modes

| Mode | What it does | Availability |
|---|---|---|
| `careful` | Removes hidden Unicode; wording is unchanged | All plans |
| `thorough` | Also lightly rewrites wording to disrupt recurring patterns, then runs the Unicode pass | Paid plans only (`PRO`, `ULTRA`, `MEGA`, `CUSTOM`) |

#### Limits

| Limit | Value |
|---|---|
| Maximum `text` length (any mode) | 200,000 characters |
| Maximum `text` length (`thorough`) | 20,000 characters |
| Rate limit | 60 requests / 60 seconds per subscriber |

Whitespace-only `text` is rejected.

#### Example request

```bash
curl -X POST 'https://{your-api-host}.p.rapidapi.com/v1/remove-watermark' \
  -H 'Content-Type: application/json' \
  -H 'X-RapidAPI-Key: YOUR_RAPIDAPI_KEY' \
  -H 'X-RapidAPI-Host: {your-api-host}.p.rapidapi.com' \
  -d '{
    "text": "A tidy draft\u200b can still carry invisible edits.",
    "mode": "careful"
  }'
```

```python
import requests

url = "https://{your-api-host}.p.rapidapi.com/v1/remove-watermark"

headers = {
    "Content-Type": "application/json",
    "X-RapidAPI-Key": "YOUR_RAPIDAPI_KEY",
    "X-RapidAPI-Host": "{your-api-host}.p.rapidapi.com",
}

payload = {
    "text": "A tidy draft\u200b can still carry invisible edits.",
    "mode": "careful",  # or "thorough" on a paid plan
}

response = requests.post(url, json=payload, headers=headers, timeout=30)
print(response.status_code)
print(response.json())
```

```javascript
const response = await fetch(
  "https://{your-api-host}.p.rapidapi.com/v1/remove-watermark",
  {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-RapidAPI-Key": "YOUR_RAPIDAPI_KEY",
      "X-RapidAPI-Host": "{your-api-host}.p.rapidapi.com",
    },
    body: JSON.stringify({
      text: "A tidy draft\u200b can still carry invisible edits.",
      mode: "careful",
    }),
  }
);

console.log(await response.json());
```

#### Success response `200`

```json
{
  "text": "A tidy draft can still carry invisible edits.",
  "mode": "careful",
  "input_characters": 45,
  "output_characters": 44,
  "removed_characters": 1,
  "normalized": false,
  "findings": [
    {
      "codepoint": "U+200B",
      "tag": "ZWSP",
      "label": "Zero-width space",
      "note": "Invisible spacing character",
      "count": 1,
      "positions": [13],
      "action": "removed",
      "sensitive": false
    }
  ]
}
```

In `thorough` mode an extra `rewrite` object is included:

```json
{
  "text": "...",
  "mode": "thorough",
  "input_characters": 45,
  "output_characters": 44,
  "removed_characters": 1,
  "normalized": false,
  "findings": [],
  "rewrite": {
    "applied": true
  }
}
```

If the wording rewrite could not run, the Unicode pass still completes and the
response remains `200`:

```json
{
  "rewrite": {
    "applied": false,
    "reason": "The wording rewrite was unavailable, so only hidden Unicode was removed. The wording was not changed."
  }
}
```

#### Response fields

| Field | Type | Description |
|---|---|---|
| `text` | string | Cleaned text |
| `mode` | string | Mode that ran (`careful` or `thorough`) |
| `input_characters` | integer | Length of the scanned text |
| `output_characters` | integer | Length of the cleaned text |
| `removed_characters` | integer | Hidden characters removed (preserved marks are not counted) |
| `normalized` | boolean | `true` if NFC normalization also changed the text |
| `findings` | array | One entry per code point and outcome |
| `rewrite` | object \| omitted | Present only for `thorough` |

##### `findings[]`

| Field | Type | Description |
|---|---|---|
| `codepoint` | string | Unicode code point, e.g. `U+200B` |
| `tag` | string | Short label, e.g. `ZWSP` |
| `label` | string | Human-readable name |
| `note` | string | What the character normally does |
| `count` | integer | Occurrences with this outcome |
| `positions` | integer[] | 1-based positions (at most the first eight) |
| `action` | string | `removed` or `preserved` |
| `sensitive` | boolean | `true` for joiners / variation selectors that can carry meaning |

##### `rewrite` (thorough only)

| Field | Type | Description |
|---|---|---|
| `applied` | boolean | Whether the wording rewrite ran |
| `reason` | string \| null | Why it was skipped, when `applied` is `false` |

---

## Errors

All errors use the same JSON shape:

```json
{
  "code": "machine_readable_code",
  "error": "Human-readable explanation."
}
```

| Status | Code | When |
|---|---|---|
| `400` | `text_required` | `text` is missing or only whitespace |
| `400` | `invalid_request` | Body failed validation (bad `mode`, wrong types, etc.) |
| `403` | `thorough_requires_paid_plan` | `mode=thorough` on a free / unpaid plan |
| `413` | `text_too_large` | `text` exceeds the overall character limit |
| `413` | `text_too_large_for_thorough` | `text` exceeds the thorough-mode limit |
| `429` | `rate_limit_reached` | Too many requests; honour `Retry-After` (seconds) |
| `503` | `thorough_unavailable` | Thorough mode is temporarily unavailable |

Rate-limited responses include:

```http
Retry-After: 12
```

---

## Notes

- Send text exactly as copied. Do not pre-normalize or strip characters first if
  you want an accurate findings report.
- `careful` never changes wording; only invisible / discretionary marks are
  removed (except those kept for emoji).
- `thorough` is a light rewrite for recurring wording patterns — not a guarantee
  that any detector will score the text differently.
- Prefer splitting long documents for `thorough` rather than sending near the
  20,000-character ceiling in one call.
