# Hyperclients API v1 — Developer Guide

Find **people who need your service right now** on LinkedIn and **local businesses to prospect** on Google Maps, straight from your own code, CRM, Zapier or n8n.

- **Base URL:** `https://hyperclients.online/v1` (the app domain proxies `/v1` to the API)
- **Interactive reference:** `/v1/docs` (Swagger, with an *Authorize* button so you can make live calls) · `/v1/redoc` (clean reading view) · `/v1/openapi.json` (import into Postman or Insomnia, or generate an SDK)
- **Format:** JSON over HTTPS. Money is in **INR**. Timestamps are ISO-8601 UTC.

---

## Contents

1. [Quick start](#1-quick-start)
2. [Authentication](#2-authentication)
3. [Pricing and wallet](#3-pricing-and-wallet)
4. [Core concepts](#4-core-concepts)
5. [Endpoints](#5-endpoints)
6. [Objects](#6-objects)
7. [Webhooks](#7-webhooks)
8. [Errors](#8-errors)
9. [Rate limits](#9-rate-limits)
10. [Best practices](#10-best-practices)
11. [FAQ](#11-faq)
12. [For Hyperclients operators (setup)](#12-for-hyperclients-operators-setup)
13. [Changelog](#13-changelog)

---

## 1. Quick start

**Step 1 — Get a key.** In the dashboard open **Developer API → API keys → Create key**. Copy the `hc_live_…` key and the `whsec_…` webhook secret; both are shown **once**.

**Step 2 — Add funds.** Go to **Developer API → API wallet**. Top-ups are ₹10,000 to ₹1,00,000 per payment, through Razorpay.

**Step 3 — Run a search.**

```bash
export HYPERCLIENTS_API_KEY="hc_live_..."

# Start: 5 LinkedIn posts from people who need a video editor
curl -X POST https://hyperclients.online/v1/searches \
  -H "Authorization: Bearer $HYPERCLIENTS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source": "linkedin", "service": "video editing", "mode": "freelancer", "leads": 5}'
# → 202 {"id": "3f0c…", "status": "queued", "max_charge_inr": 250.0, ...}

# Poll every ~5 s until status is completed / failed / cancelled
curl https://hyperclients.online/v1/searches/3f0c… -H "Authorization: Bearer $HYPERCLIENTS_API_KEY"

# Fetch the leads
curl https://hyperclients.online/v1/searches/3f0c…/leads -H "Authorization: Bearer $HYPERCLIENTS_API_KEY"
```

If you'd rather not poll, add `"webhook_url": "https://your.app/hooks/hyperclients"` and we'll `POST` the results to you when the search finishes (see [Webhooks](#7-webhooks)).

---

## 2. Authentication

Every request needs an API key, sent in **either** header:

```
Authorization: Bearer hc_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
X-API-Key: hc_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

- Keys start with `hc_live_`. Hyperclients stores only a SHA-256 hash, so **a lost key can't be recovered**. Create a new one and revoke the old one.
- You can have up to **10 active keys** per account. Use one per integration (for example "Zapier" and "CRM sync") so you can revoke them independently.
- A revoked key stops working **immediately** (`401 unauthorized`).
- **Never** put a key in browser, mobile or other client-side code. Call the API from your server.

---

## 3. Pricing and wallet

| Source | Price per lead delivered (INR) | USD equivalent |
|---|---|---|
| LinkedIn (`source: "linkedin"`) | **₹50** | **$0.52** |
| Google Maps (`source: "google_maps"`) | **₹5** | **$0.052** |

The wallet is funded and billed in **INR**. Every price and charge is also returned in **USD** (the `*_usd` fields) for easy reporting. The API is **prepaid**. It is separate from, and doesn't use, your web-app plan's monthly lead quota.

**How a charge works:**

1. **Hold.** Creating a search reserves `leads × price` from your *available* balance. If the available balance is too low, the request fails with `402 insufficient_balance` and nothing is created.
2. **Charge.** When the search finishes, you pay **only for leads actually delivered**.
3. **Release.** The unused part of the hold returns to your available balance automatically.

| Scenario | Hold | Delivered | Charged | Released |
|---|---|---|---|---|
| LinkedIn, `leads: 10` | ₹500 ($5.20) | 10 | ₹500 ($5.20) | ₹0 |
| LinkedIn, `leads: 10`, only 7 genuine buyers found | ₹500 ($5.20) | 7 | **₹350 ($3.64)** | ₹150 |
| Google Maps, `leads: 50` | ₹250 ($2.60) | 50 | ₹250 ($2.60) | ₹0 |
| Search `failed` | ₹250 | 0 | **₹0** | ₹250 |
| You cancel after 2 of 5 LinkedIn leads | ₹250 ($2.60) | 2 | ₹100 ($1.04) | ₹150 |

- **Balance** is the money in your wallet. **Held** is the amount reserved by running searches. **Available** is `balance − held`, which is what new searches can use.
- Top-ups must be between **₹10,000 and ₹1,00,000** per payment.
- Every movement (`topup`, `hold`, `charge`, `release`, `adjust`) is recorded in the wallet ledger (`GET /v1/wallet`).

---

## 4. Core concepts

### Sources
| `source` | What you get | `leads` range | Typical time |
|---|---|---|---|
| `linkedin` | Recent LinkedIn **posts from people who need your service** ("looking for a video editor…"), with the author, post link and full post text | 1–10 | 20 s – 3 min |
| `google_maps` | **Local businesses** (name, phone, website, rating, address) to prospect | 1–100 | ~1 min |

### `service`: describe what you sell, in any words
The LinkedIn engine understands free text in any industry: `"video editing"`, `"I am a CA"`, `"we are a law firm"`, `"SEO + web design"`, `"wedding photography in Pune"`, even Hinglish. It works out the real service, how buyers phrase their need (for example "need a CA for GST filing"), and which similar services *don't* count. For Google Maps, `service` is the business type you want to reach (for example `"dentists"`).

### `mode` (LinkedIn only)
| `mode` | Finds posts where… | Example |
|---|---|---|
| `freelancer` (default) | someone needs an **individual** freelancer or contractor | "Need a video editor for 10 reels this month" |
| `agency` | a client wants an **agency, studio or firm** | "Looking for an SEO agency for our relaunch" / "Need a good law firm" |

### Quality guarantees (LinkedIn)
- **Genuine buyers only.** An AI checks every post and rejects sellers, job seekers, employee job ads, recruiters, advice or "thought leadership" posts and self-promotion.
- **Latest posts first.** Only posts from the **last 7 days** are used, sorted newest first by their exact publish time.
- **Delivered live.** Each lead is saved the moment it is qualified, so `GET /v1/searches/{id}/leads` already returns the first (newest) buyers while the search is still `running`. Poll every 5 s to show them as they arrive.
- **Live posts only.** Each lead is checked on LinkedIn just before it is delivered. Deleted posts and asks that are already filled ("UPDATE: CONTRACT AWARDED") are replaced, never delivered.
- **Exact count, never more.** You get exactly `leads` results, or fewer only when not enough genuine buyers exist right now (you pay only for what's delivered).

### Search lifecycle
```
queued ──▶ running ──▶ completed
                   ├─▶ failed      (e.g. a temporary provider outage; you're charged ₹0)
                   └─▶ cancelled   (by you; charged only for leads delivered so far)
```

---

## 5. Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/searches` | Start a search |
| `GET` | `/v1/searches/{id}` | Status, progress and billing of a search |
| `GET` | `/v1/searches/{id}/leads` | Leads of a search |
| `POST` | `/v1/searches/{id}/cancel` | Cancel a running search |
| `GET` | `/v1/searches` | List your API searches |
| `GET` | `/v1/wallet` | Balance, held amount, prices and transactions |

### 5.1 `POST /v1/searches`: start a search

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| `source` | `"linkedin"` \| `"google_maps"` | yes | Where to find leads |
| `service` | string (2–200) | yes | LinkedIn: the service you sell, in any words. Maps: the business type |
| `leads` | integer | yes | Exact number wanted. LinkedIn 1–10, Maps 1–100 |
| `mode` | `"freelancer"` \| `"agency"` | no | LinkedIn only. Default `freelancer` |
| `location` | string | Maps only (required) | City, region or country, e.g. `"Austin, TX"` |
| `webhook_url` | https URL | no | Called when the search finishes |

```json
{ "source": "linkedin", "service": "I am a CA", "mode": "freelancer", "leads": 3,
  "webhook_url": "https://example.com/hooks/hyperclients" }
```

```json
{ "source": "google_maps", "service": "dentists", "location": "Pune, India", "leads": 50 }
```

**Response `202 Accepted`**

```json
{
  "id": "3f0c2a4e-8a51-4a7b-9f0e-2b8f7d1c9a10",
  "object": "search",
  "source": "linkedin",
  "service": "I am a CA",
  "mode": "freelancer",
  "status": "queued",
  "progress_percent": 0,
  "message": "Search queued",
  "requested": 3,
  "delivered": 0,
  "price_per_lead_inr": 50.0,
  "price_per_lead_usd": 0.52,
  "max_charge_inr": 150.0,
  "max_charge_usd": 1.56,
  "charged_inr": null,
  "charged_usd": null,
  "webhook_url": "https://example.com/hooks/hyperclients",
  "created_at": "2026-09-23T10:15:02Z",
  "completed_at": null,
  "wallet": { "balance_inr": 10000.0, "available_inr": 9850.0 }
}
```

**Errors:** `400 invalid_request` (bad field, LinkedIn `leads` > 10, Maps without `location`, or a non-https / private `webhook_url`) · `402 insufficient_balance` (includes `required_inr` and `available_inr`) · `429 rate_limited`.

### 5.2 `GET /v1/searches/{id}`: status and billing

Poll this every **5–10 seconds** until `status` is `completed`, `failed` or `cancelled`.

```json
{
  "id": "3f0c…", "object": "search", "source": "linkedin", "service": "I am a CA",
  "mode": "freelancer", "status": "completed", "progress_percent": 100,
  "message": "Done! 3 qualified leads found and saved.",
  "requested": 3, "delivered": 3,
  "price_per_lead_inr": 50.0, "price_per_lead_usd": 0.52,
  "max_charge_inr": 150.0, "max_charge_usd": 1.56,
  "charged_inr": 150.0, "charged_usd": 1.56,
  "webhook_url": null, "created_at": "2026-09-23T10:15:02Z", "completed_at": "2026-09-23T10:16:40Z"
}
```

`charged_inr` / `charged_usd` are `null` while the search is running (the funds are still held). A `failed` search also carries an `error` string.

### 5.3 `GET /v1/searches/{id}/leads`: the leads

```json
{
  "object": "list",
  "search_id": "3f0c…",
  "status": "completed",
  "count": 3,
  "data": [ { "...lead object..." } ]
}
```

You can call it while the search is running to see leads found so far. Lead objects are documented in [Objects](#6-objects).

### 5.4 `POST /v1/searches/{id}/cancel`

This stops a `queued` or `running` search and settles immediately: you pay for leads delivered so far and the rest of the hold is released. It returns the updated search. Cancelling a finished search returns `409 invalid_state`.

### 5.5 `GET /v1/searches`: list

Query parameters: `limit` (1–100, default 20), `offset` (default 0), `status` (`queued|running|completed|failed|cancelled`).

```json
{ "object": "list", "total": 42, "limit": 20, "offset": 0, "data": [ { "...search..." } ] }
```

### 5.6 `GET /v1/wallet`

```json
{
  "currency": "INR",
  "balance_inr": 9850.0,
  "held_inr": 0.0,
  "available_inr": 9850.0,
  "prices": { "linkedin_per_lead_inr": 50.0, "google_maps_per_lead_inr": 5.0,
              "linkedin_per_lead_usd": 0.52, "google_maps_per_lead_usd": 0.052 },
  "ledger": [
    { "type": "charge", "amount_inr": -150.0, "balance_after_inr": 9850.0,
      "search_id": "3f0c…", "note": "3 lead(s) delivered", "created_at": "2026-09-23T10:16:40Z" },
    { "type": "hold", "amount_inr": 150.0, "balance_after_inr": 10000.0,
      "search_id": "3f0c…", "note": "reserved for search", "created_at": "2026-09-23T10:15:02Z" },
    { "type": "topup", "amount_inr": 10000.0, "balance_after_inr": 10000.0,
      "search_id": null, "note": "Razorpay top-up order_…", "created_at": "2026-09-23T10:00:00Z" }
  ]
}
```

---

## 6. Objects

### Search object
| Field | Type | Notes |
|---|---|---|
| `id` | uuid | |
| `object` | `"search"` | |
| `source` | `linkedin` \| `google_maps` | |
| `service` | string | As you sent it |
| `mode` | `freelancer` \| `agency` | LinkedIn only |
| `location` | string | Maps only |
| `status` | `queued` \| `running` \| `completed` \| `failed` \| `cancelled` | |
| `progress_percent` | 0–100 | Approximate |
| `message` | string | Human-readable progress |
| `requested` / `delivered` | integer | |
| `price_per_lead_inr` / `price_per_lead_usd` | number | Locked when the search was created |
| `max_charge_inr` / `max_charge_usd` | number | `requested × price` (the hold) |
| `charged_inr` / `charged_usd` | number \| null | Final charge; `null` until settled |
| `webhook_url` | string \| null | |
| `error` | string | Only when `failed` |
| `created_at` / `completed_at` | ISO-8601 | |

### LinkedIn lead
```json
{
  "id": "b1e…", "object": "lead", "source": "linkedin",
  "type": "freelancer_needed",
  "author_name": "Jane Doe",
  "author_profile_url": "https://www.linkedin.com/in/jane-doe",
  "post_url": "https://www.linkedin.com/posts/jane-doe_need-a-video-editor-activity-75…",
  "post_text": "Looking for a video editor for 12 reels this month, paid per reel…",
  "posted_at": "2026-09-22T13:53:02Z",
  "quality_score": 84.5,
  "service_match_score": 92.0,
  "intent": "explicit",
  "urgency": 2.1,
  "created_at": "2026-09-23T10:16:39Z"
}
```
- `type` is `freelancer_needed` (mode `freelancer`) or `agency_wanted` (mode `agency`).
- `intent` is one of `explicit` (a clear ask), `active_search` (sourcing now) or `recommendation` (asking for referrals).
- `quality_score` and `service_match_score` range from 0 to 100.
- `urgency` is how pressing the buyer's need reads, from `0` (low) to `3` (urgent); `null` when it could not be judged.

### Google Maps lead
```json
{
  "id": "9c2…", "object": "lead", "source": "google_maps",
  "business_name": "Smile Dental Clinic", "category": "Dentist",
  "phone": "+91 98xxxxxx10", "email": null, "website": "https://smiledental.example",
  "address": "FC Road, Pune 411004", "rating": 4.6, "reviews": 212,
  "google_maps_url": "https://maps.google.com/?cid=…", "has_website": true,
  "created_at": "2026-09-23T10:17:05Z"
}
```

Fields may be `null` when the source doesn't provide them. **New fields may be added** to any object at any time, so ignore fields you don't recognise.

---

## 7. Webhooks

Add `webhook_url` (must be **https** and publicly reachable) when creating a search. When the search reaches a final state, Hyperclients sends:

```
POST <webhook_url>
Content-Type: application/json
User-Agent: Hyperclients-Webhooks/1.0
X-Hyperclients-Event: search.completed
X-Hyperclients-Signature: t=1727086600,v1=5257a869e7ecebeda32affa62cdca3fa51cad7e77a0e56ff536d0ce8e108d8bd
```

```json
{
  "event": "search.completed",
  "created_at": "2026-09-23T10:16:41Z",
  "data": {
    "search": { "...search object, with charged_inr set..." },
    "leads": [ { "...lead objects..." } ]
  }
}
```

Events: `search.completed`, `search.failed`, `search.cancelled` (`leads` is empty for the last two).

### Verify the signature
The signature is an HMAC-SHA256, with your key's **webhook secret** (`whsec_…`), of `"<t>.<raw request body>"`. Always:
1. Compute the HMAC over the **raw bytes** of the body (not re-serialised JSON).
2. Compare it with `v1` using a constant-time comparison.
3. Reject timestamps older than 5 minutes (replay protection).

**Node.js (Express)**
```js
import crypto from "crypto";
app.post("/hooks/hyperclients", express.raw({ type: "application/json" }), (req, res) => {
  const parts = Object.fromEntries((req.get("X-Hyperclients-Signature") || "").split(",").map(p => p.split("=")));
  const expected = crypto.createHmac("sha256", process.env.HYPERCLIENTS_WEBHOOK_SECRET)
    .update(`${parts.t}.${req.body}`).digest("hex");
  const fresh = Math.abs(Date.now() / 1000 - Number(parts.t)) < 300;
  if (!fresh || !parts.v1 || !crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(parts.v1)))
    return res.status(400).send("invalid signature");
  const { event, data } = JSON.parse(req.body);
  // … upsert data.leads into your CRM (idempotently, by lead id) …
  res.sendStatus(200);
});
```

**Python (Flask)**
```python
import hashlib, hmac, os, time
from flask import Flask, request, abort

app = Flask(__name__)

@app.post("/hooks/hyperclients")
def hyperclients_hook():
    parts = dict(p.split("=", 1) for p in request.headers.get("X-Hyperclients-Signature", "").split(","))
    body = request.get_data()  # raw bytes
    expected = hmac.new(os.environ["HYPERCLIENTS_WEBHOOK_SECRET"].encode(),
                        f"{parts.get('t')}.".encode() + body, hashlib.sha256).hexdigest()
    if abs(time.time() - int(parts.get("t", 0))) > 300 or not hmac.compare_digest(expected, parts.get("v1", "")):
        abort(400)
    event = request.get_json()
    # … process event["data"]["leads"] …
    return "", 200
```

**PHP**
```php
$raw = file_get_contents('php://input');
parse_str(str_replace(',', '&', $_SERVER['HTTP_X_HYPERCLIENTS_SIGNATURE'] ?? ''), $p);
$expected = hash_hmac('sha256', $p['t'] . '.' . $raw, getenv('HYPERCLIENTS_WEBHOOK_SECRET'));
if (abs(time() - (int)$p['t']) > 300 || !hash_equals($expected, $p['v1'] ?? '')) { http_response_code(400); exit; }
$event = json_decode($raw, true);
http_response_code(200);
```

### Delivery rules
- Respond with any **2xx within 10 seconds**. Do heavy processing asynchronously.
- If delivery fails (timeout, network error or non-2xx), it is retried **3 more times** after 2 s, 10 s and 30 s.
- Redirects are **not** followed. Private, internal and loopback addresses are never called.
- Deliveries can occasionally arrive more than once, so make your handler **idempotent** (key on `data.search.id` and the lead `id`s).
- The same data is always available through `GET /v1/searches/{id}` and `/leads`, so polling is a reliable fallback.

---

## 8. Errors

Every error has the same shape:

```json
{ "error": { "code": "insufficient_balance", "message": "This search needs ₹500.00 available (10 × ₹50.00); you have ₹120.00. Top up your wallet in the Hyperclients dashboard.", "required_inr": 500.0, "required_usd": 5.2, "available_inr": 120.0 } }
```

| HTTP | `code` | Meaning | What to do |
|---|---|---|---|
| 400 | `invalid_request` | A field is missing or invalid (`param` names it) | Fix the request |
| 401 | `unauthorized` | Missing, malformed, unknown or revoked key | Check the key; create a new one |
| 402 | `insufficient_balance` | Available balance < `leads × price` | Top up, or request fewer leads |
| 404 | `not_found` | No such search (or it belongs to another account) | Check the id |
| 409 | `invalid_state` | e.g. cancelling a finished search | Nothing to do |
| 429 | `rate_limited` | Too many requests | Wait for `Retry-After` seconds |
| 500 | `internal_error` | Unexpected server error | Retry with backoff |
| 503 | `service_unavailable` | Temporary dependency problem | Retry with backoff |

---

## 9. Rate limits

Per API key, in a sliding one-minute window:
- `POST /v1/searches`: **20 per minute**
- All other endpoints: **120 per minute**

When you exceed a limit you get `429 rate_limited` with a `Retry-After: 60` header. Polling a search every 5 seconds uses 12 requests per minute, well within limits.

---

## 10. Best practices

- **Use webhooks for scale**, and poll as a fallback. Don't poll faster than every 5 s.
- **Budget with holds:** `available_inr` must cover `leads × price` for every search you start at once.
- **Describe the service the way you'd sell it:** "video editing for YouTubers", "trademark lawyer", "GST filing". For professional services, task-style wording helps.
- **Pick the right mode:** a solo professional should use `freelancer`; a firm or studio should use `agency`.
- **Store leads by `id`** and treat them as immutable. LinkedIn posts can later be deleted by their authors; that's expected.
- **Contact leads promptly.** Buyer intent on LinkedIn is freshest in the first 24–72 hours.
- **Keep keys secret**, use one per integration, and rotate by creating a new key and then revoking the old one.

---

## 11. FAQ

**Do I pay if fewer leads are found than I asked for?** No. You pay only for delivered leads, and the rest of the hold is released automatically.

**Does the API use my web plan's monthly quota?** No. API usage is billed only from the API wallet.

**Why can LinkedIn return fewer leads than requested?** The engine only delivers genuine, live buyer posts from the last 7 days. Some niches (for example CA or law firms) have few public "I need…" posts. For those, `google_maps` (prospecting businesses that need you) usually works better.

**Can I get more than 10 LinkedIn leads?** Start several searches (for example with different `service` wordings, or `freelancer` and `agency` modes). Each search is deduplicated against leads your account already owns.

**Is there a sandbox?** Not yet. Use small `leads` values (a 1-lead LinkedIn search costs at most ₹50, about $0.52).

**Can I pay in USD?** Wallet top-ups are in INR through Razorpay (international cards are supported where enabled). USD values are shown for reference: $0.52 per LinkedIn lead, $0.052 per Google Maps lead.

**Refunds for unused wallet balance?** Contact support.

---

## 12. For Hyperclients operators (setup)

1. **Database:** run `supabase/migration_public_api_v20.sql` in the Supabase SQL editor. It creates `api_keys`, `api_wallets` and `api_wallet_ledger`, adds the API billing columns to `searches`, and adds the atomic RPCs `api_wallet_hold`, `api_wallet_settle` and `api_wallet_credit`.
2. **Backend env** (optional overrides; defaults shown):
   ```
   API_PRICE_LINKEDIN_INR=50
   API_PRICE_MAPS_INR=5
   API_PRICE_LINKEDIN_USD=0.52                  # shown next to INR everywhere
   API_PRICE_MAPS_USD=0.052
   API_MIN_TOPUP_INR=10000
   API_MAX_TOPUP_INR=100000
   API_RATE_CREATE_PER_MIN=20
   API_RATE_READ_PER_MIN=120
   PUBLIC_API_BASE_URL=https://hyperclients.online   # shown in /v1/docs
   ```
   Razorpay uses the existing `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET`. The existing Razorpay webhook (`/api/subscriptions/webhook`) also credits wallet top-ups, so a customer who closes the browser mid-payment is still credited, once.
3. **Frontend:** `next.config.mjs` proxies `/v1/*` to the backend, so the API and docs work on the app domain.
4. **Crediting a wallet manually** (support or testing), in SQL: `select public.api_wallet_credit('<user uuid>', 20000, null, 'adjust', 'support credit');` (the amount is in paise; 20000 = ₹200).
5. **Code map:**
   - `app/routers/public_api.py`: the `/v1` endpoints
   - `app/routers/developer.py`: dashboard keys, wallet and top-ups
   - `app/services/api_keys.py`, `api_wallet.py`, `api_public.py`: keys, wallet, serializers and webhooks
   - `app/middleware/api_key_auth.py`: key auth and rate limits
   - `app/public_docs.py`: `/v1/docs`
   - `app/services/usage.py` → `_settle_api_wallet`: the billing hook used by both engines
6. **Tests:** `cd backend && python -m pytest tests/test_public_api.py -q`

---

## 13. Changelog

- **v1.0.0 (2026-09):** first release. LinkedIn and Google Maps searches, pay-per-delivered-lead wallet billing, completion webhooks and API keys.
