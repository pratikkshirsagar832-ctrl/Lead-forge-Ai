# LinkedIn Studio: AI posting and scheduling (official LinkedIn API)

LinkedIn Studio lets **Pro and Agency** users write LinkedIn posts with DeepSeek, turn them into carousels, and publish them now or on a schedule, to their **personal profile** and (after LinkedIn approval) their **company pages**. It optionally runs on **autopilot**.

Only LinkedIn's official API is used: OAuth 2.0, `/v2/userinfo`, and the REST `posts`, `images`, `documents` and `organizationAcls` endpoints. No scraping, no third-party posting services.

---

## 1. What users get

| Feature | Details |
|---|---|
| Connect LinkedIn | "Connect profile" (works immediately). "Company pages" is enabled after LinkedIn approves our Community Management API access |
| AI writing | Generate 3 variants from a topic and goal, **Humanize** (removes AI-sounding phrasing), **Rewrite** with an instruction. Each counts as 1 AI call on the plan's monthly AI quota |
| Post types | Text, 1 image, 2–20 images, or a **PDF document / carousel** |
| AI carousel | DeepSeek writes 6–10 slides plus a caption, rendered to a branded 1080×1350 PDF; slides are editable, then *Update PDF* |
| Scheduling | Pick a date and time (user's local time); up to 90 days ahead, at least 2 minutes in the future |
| Queue and calendar | Scheduled, drafts, published and needs-attention lists with edit, post now, cancel, delete (also deletes on LinkedIn) and a link to the live post |
| Autopilot | Posting days and times, content topics, audience and a voice sample. DeepSeek fills upcoming slots (up to 14 days ahead). Posts arrive as **drafts to approve** by default; publishing without approval needs explicit consent |
| Plan limits | Pro **60**, Agency **200** published posts per month (column `plans.linkedin_posts_monthly`; scheduled posts count toward the limit). Free and Solo see an upgrade screen |

## 2. LinkedIn platform rules we follow

- **Member tokens last 60 days and cannot be refreshed** (LinkedIn only gives refresh tokens to approved partner apps). The UI warns 7 days ahead. Once a token expires, that account's posts move to *needs reconnect* and resume automatically after the user reconnects.
- **Company pages** need the **Community Management API**. LinkedIn requires it on a **separate LinkedIn app**, and it goes through business verification. That app gets refresh tokens, which we renew automatically.
- **LinkedIn has no scheduling API**, so the Hyperclients backend runs its own scheduler (every 30 s). A post can't be published twice (the database claims each post atomically).
- The commentary limit is 3,000 characters. Text is converted to LinkedIn's "little text" format so characters like `( ) [ ] @ * _` are published literally and `#hashtags` stay clickable.
- Safety cap: **5 published posts per account per day** (`LINKEDIN_DAILY_POST_CAP`), well below LinkedIn's API limits.
- Personal-post analytics need restricted LinkedIn permissions, so they are not in v1.

## 3. One-time setup (owner)

### 3.1 LinkedIn app 1: "Hyperclients" (personal profiles), needed now
1. Go to https://www.linkedin.com/developers/apps → **Create app**. Name it *Hyperclients*, link it to the **Hyperclients LinkedIn company page**, upload the logo, accept the terms.
2. Open the **Settings** tab → *Verify* the app with the company page admin.
3. Open the **Products** tab → request **Sign In with LinkedIn using OpenID Connect** and **Share on LinkedIn** (both are self-serve and approved instantly).
4. Open the **Auth** tab:
   - Add the redirect URL `https://hyperclients.online/api/linkedin/callback`
   - Copy the **Client ID** and **Primary Client Secret**
   - Scopes should show `openid profile email w_member_social`

### 3.2 LinkedIn app 2: "Hyperclients Pages" (company pages), apply now; approval takes weeks
1. Create a **second** app linked to the same company page. LinkedIn requires Community Management API to be the only product on its app.
2. Open the **Products** tab → request **Community Management API** and fill the access form (business details, use case: "customers schedule and publish posts to their own company pages from Hyperclients").
3. Add the same redirect URL. After approval, set the env vars below and `LINKEDIN_PAGES_ENABLED=true`.

### 3.3 Backend environment
```
LINKEDIN_CLIENT_ID=...                 # app 1
LINKEDIN_CLIENT_SECRET=...
LINKEDIN_PAGES_CLIENT_ID=...           # app 2 (after approval)
LINKEDIN_PAGES_CLIENT_SECRET=...
LINKEDIN_PAGES_ENABLED=false           # true once Community Management API is approved
LINKEDIN_REDIRECT_URI=https://hyperclients.online/api/linkedin/callback
LINKEDIN_API_VERSION=202608            # LinkedIn REST version (YYYYMM); bump yearly
LINKEDIN_TOKEN_KEY=...                 # encrypts OAuth tokens at rest (see below)
LINKEDIN_DAILY_POST_CAP=5
LINKEDIN_SCHEDULER_ENABLED=true
```
Generate `LINKEDIN_TOKEN_KEY` once and **never change it**, because changing it makes stored tokens unreadable and users must reconnect:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
DeepSeek uses the existing `DEEPSEEK_API_KEY`.

### 3.4 Database
Run `supabase/migration_linkedin_studio_v21.sql` in the Supabase SQL Editor. It creates `linkedin_accounts`, `linkedin_posts` and `linkedin_autopilot`, the post-limit columns, the RPCs `claim_due_linkedin_posts` and `consume_linkedin_post_quota`, and the private storage bucket **`linkedin-media`**. If your project blocks bucket creation from SQL, create the private bucket `linkedin-media` in *Storage* by hand.

### 3.5 Deploy
Rebuild the backend (new Python packages: `cryptography`, `reportlab`) and the frontend. The scheduler starts with the backend automatically.

## 4. How it works

```
Compose / Autopilot ──► linkedin_posts (draft | scheduled)
                              │
      scheduler (30 s) ──► claim_due_linkedin_posts()  ── FOR UPDATE SKIP LOCKED
                              │
                              ▼
   check plan + monthly limit + daily cap ─► decrypt token (refresh pages token)
                              │
     upload media: storage ─► /rest/images | /rest/documents (initializeUpload + PUT)
                              │
                     POST /rest/posts  ─► x-restli-id = post URN ─► published
   401 → needs_reconnect (account marked expired) · 429/5xx → retry 3× with backoff
```

**Code map (backend):**
- `app/routers/linkedin_studio.py`: API (`/api/linkedin/*`)
- `app/services/linkedin_api.py`: official LinkedIn client (OAuth, signed state, media, posts, little-text)
- `app/services/linkedin_studio.py`: accounts, plan and quota, media storage, publishing
- `app/services/linkedin_scheduler.py`: background publisher and autopilot planner
- `app/services/linkedin_writer.py`: DeepSeek prompts (rules adapted from the MIT-licensed *linkedin-skills*)
- `app/services/carousel_pdf.py`: slides to PDF
- `app/services/token_crypto.py`: Fernet encryption of tokens

**Frontend:** `frontend/src/app/dashboard/linkedin/page.tsx` (sidebar: *LinkedIn Studio*).

## 5. Security
- OAuth `state` is HMAC-signed, bound to the user and app, and expires after 10 minutes.
- Access and refresh tokens are **encrypted with Fernet** before they reach the database and are never sent to the browser. The `linkedin_accounts` table isn't readable by clients (RLS).
- Media paths are scoped per user (`<user_id>/…`) and checked on every request. PDF files must be real PDFs, up to 100 MB; images up to 8 MB.
- Publishing without approval requires explicit consent (stored as `consent_at`).

## 6. Testing
```bash
cd backend && python -m pytest tests/test_linkedin_studio.py -q
```
Live check after setup: connect your own profile, post a **Connections only** text post, an image post and an AI carousel, confirm them on LinkedIn, and delete them from the Queue. Then schedule one 3 minutes ahead and confirm it's published once.
