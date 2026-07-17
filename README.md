# Smart 1 Legal — Legal Conquesting Market Intelligence Tool

A self-contained lead-gen web app for **Smart 1 Marketing's "Smart Signage" Legal
Conquesting Package**. A law firm fills out a short intake form; the app uses OpenAI
to build a Digital Out-of-Home (DOOH) + mobile-retargeting market plan tailored to the
firm's practice area and ZIP code, renders a branded proposal PDF, and pushes the lead
+ opportunity into Smart1Suite (HighLevel) via webhook.

This is the legal sibling of the Boat Dealer (`smart1boat`) and RV Dealer (`smart1rv`)
apps — same architecture, tuned for law firms.

## What it produces

For each firm the AI returns a structured plan:

- **Market profile** — estimated population, households, and annual case/claim volume
  (ranges + confidence + assumptions).
- **Why Smart Signage beats a static billboard** — the core sales frame.
- **Recommended package** — one tier from the Smart 1 legal menu (see below).
- **Media & targeting** — always anchored by DOOH Smart Signage, Location Look-Back
  Mobile Retargeting, and In-Market Legal Intent Audience Data, plus relevant add-ons.
  (Never billboards/print/broadcast/paid search/email/SMS/social.)
- **Weather-triggered activation** — auto-enabled for Personal Injury / Auto / DUI
  markets, suppressed for non-injury areas.
- **Month-by-month plan** with budget pacing (Peak 100% / Shoulder 60% / Low 40%).
- **High-intent geofence locations** — practice-area specific POIs (hospitals, body
  shops, accident intersections, jails, courthouses, industrial parks, etc.) with
  priority, method, radius, and confidence.

## Package menu (tiers)

| Monthly | Package |
|---|---|
| $3,500/month | Local Docket Starter |
| $5,000/month | Case Conquesting Growth |
| $7,500/month | Market Domination |
| $10,000/month | Total Legal Saturation |

Prices/names are enforced server-side (`PACKAGE_MENU` in `app.py`); the model must pick
one and may not invent prices.

## Endpoints

- `GET /` — intake form UI (`templates/index.html`)
- `POST /api/analyze` — `{firm_name, website, firm_zip, practice_area, target_radius,
  primary_goal, secondary_practice_areas, contact_*, notes}` → `{ok, report, report_pdf_url}`
- `GET /health` — health check

## Environment variables

| Var | Required | Notes |
|---|---|---|
| `OPENAI_API_KEY` | yes | OpenAI key |
| `OPENAI_MODEL` | no | defaults to `gpt-4.1-mini` |
| `SMART1_WEBHOOK_URL` | no | Smart1Suite / HighLevel inbound webhook. If unset, lead push is skipped. |
| `PUBLIC_BASE_URL` | no | e.g. `https://smart1legal.onrender.com` — makes the PDF URL absolute. |
| `ENABLE_PDF` | no | `1` (default) / `0` to disable PDF generation. |

## Run locally

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
python app.py         # http://localhost:5000
```

## Deploy (Render)

`render.yaml` is included. Create a new Blueprint from this repo, set `OPENAI_API_KEY`,
`SMART1_WEBHOOK_URL`, and `PUBLIC_BASE_URL` in the dashboard, and deploy. Runs on the
native Python runtime (reportlab is pure-Python — no Docker/apt needed).

## Notes

- All figures are labeled AI planning estimates, never audited counts.
- PDF/webhook failures are guarded so they never block the lead from being captured.
