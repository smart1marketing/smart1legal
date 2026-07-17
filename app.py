import io
import json
import os
import re
import time
from typing import Any

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

# reportlab is pure-Python (no system libraries) so the PDF builder deploys
# cleanly on Render's native Python runtime with no Docker/apt changes.
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

load_dotenv()

app = Flask(__name__)

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
WEBHOOK_URL = os.getenv("SMART1_WEBHOOK_URL", "").strip()
# Absolute base used to build the public report_pdf_url (e.g. https://smart1legal.onrender.com).
# If empty, the app derives it from the incoming request.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
ENABLE_PDF = os.getenv("ENABLE_PDF", "1").strip() not in ("0", "false", "False", "")
REPORT_DIR = os.path.join(app.static_folder, "reports")

# ---------------------------------------------------------------------------
# Smart 1 "Smart Signage" Legal Conquesting package menu. The model must choose
# ONE of these tiers (exact name + price) — it may not invent prices.
# ---------------------------------------------------------------------------
PACKAGE_MENU = [
    ("$3,500/month", "Local Docket Starter"),
    ("$5,000/month", "Case Conquesting Growth"),
    ("$7,500/month", "Market Domination"),
    ("$10,000/month", "Total Legal Saturation"),
]

SYSTEM_PROMPT = """
You are the Smart 1 Marketing Legal Conquesting Market Intelligence Architect.
Create a practical, sales-oriented Digital Out-of-Home (DOOH) + mobile conquesting
market plan for a law firm. The core product is "Smart Signage": programmatic DOOH
across a network of digital screens (highway digital boards, gas stations, office/
elevator screens, transit hubs, gyms, convenience stores, bars & restaurants),
activated ONLY when and where the firm's ideal clients are present, then bridged to
the prospect's phone with location-based mobile retargeting.

WHY THIS BEATS A TRADITIONAL BILLBOARD (frame the plan around this)
- A static billboard charges a flat fee for 100% of passing traffic even though the
  vast majority never need a lawyer. It offers zero flexibility, zero audience data,
  and zero call attribution.
- Smart Signage activates digital screens by location and audience, layers in
  third-party data, can trigger on weather/real-world signals, captures anonymous
  mobile device IDs near the screens, and retargets those devices to the firm's site.

IMPORTANT ACCURACY RULES
- You do NOT have live access to maps, court dockets, or exact census/claims tables
  unless supplied in the request.
- Use geographic knowledge and conservative planning assumptions. Never claim a
  location or statistic was live-verified.
- Clearly label all population, household, and case/claim figures as AI planning
  estimates. Give ranges, a confidence level, and short assumptions.
- Do not invent precise street addresses. Use recognizable place names + city/state.
  An address field may be null.
- Prefer real, well-known venues/POIs you are reasonably confident exist. If
  uncertain, lower the confidence.
- Avoid duplicate locations. Favor practical, geofenceable points (buildings,
  facilities, intersections, venues) over vague open areas.

PRACTICE-AREA HIGH-INTENT TARGETING (tailor geofence_locations to the firm's area)
- Personal Injury / Auto Accident: hospitals & ER entrances, urgent care, orthopedic
  & chiropractic clinics, auto body / collision repair shops, tow yards & impound
  lots, high-crash intersections & interstate merge points, pharmacies, competitor PI
  firms (conquesting).
- Criminal Defense / DUI-DWI: county jail & detention centers, courthouses, police
  stations, bail bond offices, probation/parole offices; for DUI add bar & nightlife
  districts, stadiums, concert venues (evening/weekend dayparts).
- Family Law / Divorce: family & domestic court, marriage & family counseling
  offices, apartment/relocation complexes, competitor family firms.
- Workers' Compensation: industrial parks, warehouses & distribution centers,
  construction sites, manufacturing plants, occupational-health / urgent-care clinics.
- Mass Tort / Class Action: nursing homes & assisted living, hospitals, pharmacies,
  dialysis/oncology centers.
- Medical Malpractice: hospitals, specialty clinics, senior communities.
- Employment / Labor: large employers, business parks, staffing offices.
- Immigration: consulates, community centers, ethnic retail corridors, ESL/community
  colleges.
- Estate / Probate / Elder Law: senior living, hospitals/hospice, financial-planning
  offices, churches.
- Bankruptcy: courthouses, check-cashing/payday locations, foreclosure-heavy ZIPs.
If a practice area is not listed, choose the closest analog and explain briefly.

MEDIA & TARGETING RULES (ALLOWED channels ONLY)
- ALWAYS include "Digital Out-of-Home (DOOH) Smart Signage" as the anchor channel.
- ALWAYS include "Location Look-Back Mobile Retargeting" (capture anonymous device
  IDs seen near the screens/high-intent locations, then serve clickable display ads
  to those phones and bridge them to the firm's site/intake).
- ALWAYS include "In-Market Legal Intent Audience Data" (layer third-party data —
  e.g. Experian, TrueData, Proximic — for high-risk drivers, commuters, injury/legal
  in-market households, income/demographic filters).
- Then choose additional relevant chips from: "Point-Radius Proximity Geofencing",
  "Data-Driven Targeted Display", "Connected TV (CTV/OTT)", "Streaming Audio",
  "YouTube / Online Video", "Website Retargeting".
- NEVER recommend traditional/static billboards, print, newspapers, direct mail,
  terrestrial/broadcast radio, or linear/broadcast TV. NEVER recommend paid search,
  email, SMS, or ANY social media channel (Facebook, Instagram, TikTok, LinkedIn,
  Snapchat, Pinterest, X). Do not mention them anywhere.
- Return 5-7 media chips total.

WEATHER-TRIGGERED ACTIVATION
- weather_triggers ONLY meaningfully apply to Personal Injury / Auto Accident / DUI
  markets (crashes spike in rain, snow, ice, fog, first-freeze, holiday travel).
- For PI/auto/DUI firms, return 4-7 short punchy trigger labels (e.g. "Heavy rain",
  "Snow / ice event", "Dense fog", "First freeze", "Holiday travel weekend",
  "Rush-hour storm"). weather_triggers_applicable = true.
- For non-injury practice areas (family, immigration, estate, bankruptcy, employment),
  set weather_triggers_applicable = false and return an EMPTY weather_triggers list;
  do not force weather logic where it does not fit.

OUTPUT
Return only valid JSON matching the requested schema. Do not use markdown fences.
"""

REPORT_SCHEMA = {
    "name": "legal_conquesting_report",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "market_summary": {"type": "string"},
            "practice_area": {"type": "string"},
            "market_type": {"type": "string"},
            "market_type_description": {"type": "string"},
            "market_opportunity": {"type": "string"},
            "billboard_comparison": {"type": "string"},
            "market_profile": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "estimated_population_low": {"type": "integer"},
                    "estimated_population_base": {"type": "integer"},
                    "estimated_population_high": {"type": "integer"},
                    "estimated_households_low": {"type": "integer"},
                    "estimated_households_base": {"type": "integer"},
                    "estimated_households_high": {"type": "integer"},
                    "estimated_annual_cases_low": {"type": "integer"},
                    "estimated_annual_cases_base": {"type": "integer"},
                    "estimated_annual_cases_high": {"type": "integer"},
                    "case_volume_label": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "assumptions": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "estimated_population_low",
                    "estimated_population_base",
                    "estimated_population_high",
                    "estimated_households_low",
                    "estimated_households_base",
                    "estimated_households_high",
                    "estimated_annual_cases_low",
                    "estimated_annual_cases_base",
                    "estimated_annual_cases_high",
                    "case_volume_label",
                    "confidence",
                    "assumptions",
                ],
            },
            "recommended_package": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "package_name": {"type": "string"},
                    "monthly_investment": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["package_name", "monthly_investment", "description"],
            },
            "media_channels": {"type": "array", "items": {"type": "string"}},
            "mobile_retargeting_note": {"type": "string"},
            "weather_triggers_applicable": {"type": "boolean"},
            "weather_triggers": {"type": "array", "items": {"type": "string"}},
            "monthly_plan": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "month": {"type": "string"},
                        "focus": {"type": "string"},
                        "message": {"type": "string"},
                        "triggers": {"type": "array", "items": {"type": "string"}},
                        "pacing": {"type": "string"},
                    },
                    "required": ["month", "focus", "message", "triggers", "pacing"],
                },
            },
            "geofence_locations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "city_state": {"type": "string"},
                        "address": {"type": ["string", "null"]},
                        "category": {"type": "string"},
                        "priority": {"type": "integer", "enum": [1, 2, 3]},
                        "recommended_method": {
                            "type": "string",
                            "enum": ["location_lookback", "real_time_proximity", "both"],
                        },
                        "recommended_radius_miles": {"type": "number"},
                        "audience_reason": {"type": "string"},
                        "best_message": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    },
                    "required": [
                        "name",
                        "city_state",
                        "address",
                        "category",
                        "priority",
                        "recommended_method",
                        "recommended_radius_miles",
                        "audience_reason",
                        "best_message",
                        "confidence",
                    ],
                },
            },
            "disclaimer": {"type": "string"},
        },
        "required": [
            "market_summary",
            "practice_area",
            "market_type",
            "market_type_description",
            "market_opportunity",
            "billboard_comparison",
            "market_profile",
            "recommended_package",
            "media_channels",
            "mobile_retargeting_note",
            "weather_triggers_applicable",
            "weather_triggers",
            "monthly_plan",
            "geofence_locations",
            "disclaimer",
        ],
    },
    "strict": True,
}


def clean_payload(data: dict) -> dict:
    fields = [
        "firm_name",
        "website",
        "firm_zip",
        "target_radius",
        "practice_area",
        "secondary_practice_areas",
        "primary_goal",
        "contact_name",
        "contact_email",
        "contact_phone",
        "proposal_recipient_email",
        "notes",
    ]
    cleaned = {k: str(data.get(k, "")).strip()[:1500] for k in fields}
    if not re.fullmatch(r"\d{5}(-\d{4})?", cleaned["firm_zip"]):
        raise ValueError("A valid U.S. ZIP code is required.")
    if not cleaned["practice_area"]:
        cleaned["practice_area"] = "Personal Injury"
    # Where the finished plan should be sent — defaults to the contact email.
    if not cleaned["proposal_recipient_email"]:
        cleaned["proposal_recipient_email"] = cleaned["contact_email"]
    return cleaned


def _package_menu_text() -> str:
    return "\n".join(f"    * {price} — {name}" for price, name in PACKAGE_MENU)


def generate_report(payload: dict) -> Any:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    from openai import OpenAI  # lazy import: PDF/webhook paths don't need the SDK
    client = OpenAI(api_key=api_key)
    user_prompt = (
        "\nBuild a Smart Signage Legal Conquesting DOOH + mobile plan from these inputs:\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "The firm gave only a ZIP code, a practice area, and a target radius. You must "
        "supply everything else yourself:\n"
        "- Derive the state, city area, and region from the ZIP code and base all "
        "geography, density, and seasonality on it.\n"
        "- Identify the local high-intent venues/POIs for this practice area yourself "
        "(hospitals, body shops, courthouses, jails, industrial parks, etc. as relevant) "
        "and include the best of them in geofence_locations.\n\n"
        "Populate every field of the schema:\n"
        "- market_summary: one or two sentences framing the DOOH conquesting opportunity "
        "for this firm and market (reference the firm name, practice area, and area).\n"
        "- practice_area: echo the firm's primary practice area.\n"
        "- market_type: a short badge label, e.g. 'Major Metro Personal-Injury Market' or "
        "'Suburban Family-Law Market'. market_type_description: one sentence on the demand pattern.\n"
        "- billboard_comparison: 1-2 punchy sentences contrasting a wasteful static billboard "
        "flat-fee buy with targeted Smart Signage for THIS firm's practice area.\n"
        "- market_profile: low/base/high estimates for population, households, and estimated "
        "annual case/claim volume for this practice area in the radius; set case_volume_label to "
        "what is being counted (e.g. 'estimated annual injury claims', 'estimated annual DUI "
        "arrests', 'estimated annual divorce filings'); include confidence and short assumptions. "
        "Present ownership/claim figures as percentages/decimals where natural, not as verified counts.\n"
        "- market_opportunity: ONE short, plain sentence on the firm's opportunity in this market.\n"
        "- recommended_package: choose the best-fit tier from the Smart 1 legal package menu below. "
        "Use its EXACT name and price as monthly_investment, and write a short description of what "
        "that level buys. Pick the tier from market size, competition, and case volume.\n"
        "  SMART 1 LEGAL PACKAGE MENU (use these, do not invent prices):\n"
        f"{_package_menu_text()}\n"
        "- media_channels: ALLOWED channels only, per the system rules. ALWAYS include the three "
        "anchor chips ('Digital Out-of-Home (DOOH) Smart Signage', 'Location Look-Back Mobile "
        "Retargeting', 'In-Market Legal Intent Audience Data'), then 2-4 more relevant chips. Return "
        "5-7 total. NEVER include static billboards, print, broadcast, paid search, email, SMS, or social.\n"
        "- mobile_retargeting_note: 1-2 sentences describing the physical-screen-to-phone bridge: "
        "capture anonymous device IDs seen near the screens/high-intent locations, then serve clickable "
        "display ads to those phones and route them to the firm's site/intake.\n"
        "- weather_triggers_applicable + weather_triggers: per the system rules — populate triggers for "
        "PI/auto/DUI markets, otherwise set applicable=false and return an empty list.\n"
        "- monthly_plan: all 12 months (January-December). Each month: a focus title, a short client-facing "
        "message, 1-2 relevant trigger labels (only if weather applies; otherwise use a short seasonal/legal "
        "hook like 'Post-holiday divorce season' or 'Back-to-work injury spike' or leave triggers empty), and "
        "a 'pacing' string.\n"
        "  BUDGET PACING RULE for 'pacing': the recommended_package monthly_investment is the PEAK monthly "
        "budget (100%). In shoulder months spend 60%; in lower-demand months spend 40%. Classify each month "
        "as Peak, Shoulder, or Low based on this practice area's demand cycle, and set pacing to a short "
        "string with tier, percent, and the computed dollar amount — e.g. 'Peak — 100% ($7,500)', "
        "'Shoulder — 60% ($4,500)', 'Low — 40% ($3,000)'. Compute dollars from the chosen package price.\n"
        "- geofence_locations: 12-18 high-intent locations tuned to the practice area. Prioritize locations "
        "inside the target radius; lower confidence for uncertain ones. Keep text concise.\n"
        "- disclaimer: a short note that figures are AI planning estimates for the market, not exact counts.\n"
    )
    response = client.responses.create(
        model=MODEL,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        text={"format": {"type": "json_schema", **REPORT_SCHEMA}},
        temperature=0.25,
        max_output_tokens=8000,
    )
    text = (response.output_text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# PDF report — reportlab, pure Python. Produces a hosted PDF the team can send
# from Smart1Suite. Guarded so any failure never blocks the lead/webhook.
# ---------------------------------------------------------------------------

NAVY = colors.HexColor("#1A2E58")
BLUE = colors.HexColor("#28477F")
GOLD = colors.HexColor("#B8892B")
LINE = colors.HexColor("#dfe3ea")
MUTED = colors.HexColor("#687386")
MIST = colors.HexColor("#f2f5fa")


def _money_to_int(value: str):
    """'$7,500/month' -> 7500 (int) or None."""
    digits = re.sub(r"[^\d]", "", (value or "").split("/")[0])
    return int(digits) if digits else None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "report").lower()).strip("-") or "report"


def _pdf_styles():
    ss = getSampleStyleSheet()
    body = ParagraphStyle("s1body", parent=ss["Normal"], fontName="Helvetica",
                          fontSize=9.5, leading=14, textColor=colors.HexColor("#25364b"))
    h2 = ParagraphStyle("s1h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                        fontSize=13, leading=16, textColor=NAVY, spaceBefore=16, spaceAfter=6)
    title = ParagraphStyle("s1title", parent=ss["Title"], fontName="Helvetica-Bold",
                           fontSize=22, leading=25, textColor=NAVY, alignment=TA_LEFT, spaceAfter=4)
    eyebrow = ParagraphStyle("s1eye", parent=body, fontName="Helvetica-Bold",
                             fontSize=8, textColor=GOLD, spaceAfter=2)
    small = ParagraphStyle("s1small", parent=body, fontSize=8, textColor=MUTED, leading=11)
    cell = ParagraphStyle("s1cell", parent=body, fontSize=8, leading=10.5)
    cellw = ParagraphStyle("s1cellw", parent=cell, textColor=colors.white)
    return dict(body=body, h2=h2, title=title, eyebrow=eyebrow, small=small, cell=cell, cellw=cellw)


def build_report_pdf(report: dict, firm: str, base_url: str) -> str:
    """Render the report JSON to a branded PDF, save under static/reports,
    and return its absolute public URL (or '' on failure)."""
    if not ENABLE_PDF:
        return ""
    try:
        os.makedirs(REPORT_DIR, exist_ok=True)
        st = _pdf_styles()
        fmt = lambda n: f"{int(n):,}" if n is not None else "—"
        rng = lambda a, b: f"{fmt(a)}–{fmt(b)}"
        m = report.get("market_profile", {}) or {}
        rp = report.get("recommended_package", {}) or {}

        filename = f"{_slug(firm)}-{int(time.time())}.pdf"
        path = os.path.join(REPORT_DIR, filename)

        story = []
        story.append(Paragraph("SMART 1 MARKETING &nbsp;|&nbsp; LEGAL CONQUESTING PLAN", st["eyebrow"]))
        story.append(Paragraph(firm or "Legal Market Report", st["title"]))
        pa = report.get("practice_area", "")
        if pa:
            story.append(Paragraph(f"<b>Practice Area:</b> {pa}", st["small"]))
        story.append(Spacer(1, 4))
        story.append(Paragraph(report.get("market_summary", ""), st["body"]))
        story.append(Spacer(1, 6))

        if report.get("market_type"):
            story.append(Paragraph(f"<b>{report.get('market_type')}</b> — {report.get('market_type_description','')}", st["small"]))

        cvl = (m.get("case_volume_label") or "ESTIMATED ANNUAL CASES").upper()
        stat_data = [[
            Paragraph(f"<b>{rng(m.get('estimated_population_low'), m.get('estimated_population_high'))}</b><br/><font size=7 color='#68798c'>ESTIMATED POPULATION</font>", st["cell"]),
            Paragraph(f"<b>{rng(m.get('estimated_households_low'), m.get('estimated_households_high'))}</b><br/><font size=7 color='#68798c'>ESTIMATED HOUSEHOLDS</font>", st["cell"]),
            Paragraph(f"<b>{rng(m.get('estimated_annual_cases_low'), m.get('estimated_annual_cases_high'))}</b><br/><font size=7 color='#68798c'>{cvl}</font>", st["cell"]),
        ]]
        stat = Table(stat_data, colWidths=[2.4 * inch] * 3)
        stat.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), MIST),
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(Spacer(1, 8))
        story.append(stat)

        if report.get("billboard_comparison"):
            story.append(Paragraph("Why Smart Signage, Not a Static Billboard", st["h2"]))
            story.append(Paragraph(report.get("billboard_comparison", ""), st["body"]))

        story.append(Paragraph("Your Market Opportunity", st["h2"]))
        story.append(Paragraph(report.get("market_opportunity", ""), st["body"]))

        story.append(Paragraph("Recommended Package", st["h2"]))
        story.append(Paragraph(f"<b>{rp.get('monthly_investment','')} — {rp.get('package_name','')}</b>", st["body"]))
        story.append(Paragraph(rp.get("description", ""), st["small"]))

        chans = report.get("media_channels", []) or []
        if chans:
            story.append(Paragraph("Recommended Media & Targeting", st["h2"]))
            story.append(Paragraph(" &nbsp;•&nbsp; ".join(chans), st["body"]))

        if report.get("mobile_retargeting_note"):
            story.append(Paragraph("The Mobile Retargeting Bridge", st["h2"]))
            story.append(Paragraph(report.get("mobile_retargeting_note", ""), st["body"]))

        trigs = report.get("weather_triggers", []) or []
        if report.get("weather_triggers_applicable") and trigs:
            story.append(Paragraph("Weather-Triggered Activation", st["h2"]))
            story.append(Paragraph(" &nbsp;•&nbsp; ".join(trigs), st["body"]))

        plan = report.get("monthly_plan", []) or []
        if plan:
            story.append(Paragraph("Month-by-Month Campaign Plan", st["h2"]))
            rows = [[Paragraph("<b>Month</b>", st["cellw"]), Paragraph("<b>Focus</b>", st["cellw"]), Paragraph("<b>Budget Pacing</b>", st["cellw"])]]
            for x in plan:
                rows.append([
                    Paragraph(x.get("month", ""), st["cell"]),
                    Paragraph(x.get("focus", ""), st["cell"]),
                    Paragraph(x.get("pacing", ""), st["cell"]),
                ])
            t = Table(rows, colWidths=[1.1 * inch, 3.3 * inch, 2.8 * inch], repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, MIST]),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(t)

        geo = sorted(report.get("geofence_locations", []) or [], key=lambda g: g.get("priority", 3))
        if geo:
            story.append(Paragraph("High-Intent Geofence & DOOH Targeting Locations", st["h2"]))
            rows = [[Paragraph(f"<b>{h}</b>", st["cellw"]) for h in ("P", "Location", "Category", "Method", "Radius", "Conf.")]]
            for g in geo:
                rows.append([
                    Paragraph(f"P{g.get('priority','')}", st["cell"]),
                    Paragraph(f"<b>{g.get('name','')}</b><br/>{g.get('city_state','')}", st["cell"]),
                    Paragraph(g.get("category", ""), st["cell"]),
                    Paragraph(str(g.get("recommended_method", "")).replace("_", " "), st["cell"]),
                    Paragraph(f"{g.get('recommended_radius_miles','')} mi", st["cell"]),
                    Paragraph(g.get("confidence", ""), st["cell"]),
                ])
            t = Table(rows, colWidths=[0.4 * inch, 2.2 * inch, 1.5 * inch, 1.3 * inch, 0.7 * inch, 0.6 * inch], repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, MIST]),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(t)

        story.append(Spacer(1, 12))
        story.append(Paragraph(report.get("disclaimer", ""), st["small"]))

        doc = SimpleDocTemplate(path, pagesize=letter, title=f"{firm} Legal Conquesting Plan",
                                leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                                topMargin=0.6 * inch, bottomMargin=0.6 * inch)
        doc.build(story)

        base = base_url or PUBLIC_BASE_URL
        return f"{base.rstrip('/')}/static/reports/{filename}" if base else f"/static/reports/{filename}"
    except Exception:
        app.logger.exception("PDF generation failed")
        return ""


def send_webhook(payload: dict, report: Any, status: str, pdf_url: str = "") -> None:
    if not WEBHOOK_URL:
        return
    report = report or {}
    mp = report.get("market_profile", {}) or {}
    rp = report.get("recommended_package", {}) or {}
    monthly = _money_to_int(rp.get("monthly_investment", ""))
    body = {
        # --- Contact / lead fields ---
        **payload,
        "source": "Smart 1 Legal Conquesting Market Intelligence",
        "report_status": status,
        # --- Opportunity fields ---
        "opportunity_name": f"{payload.get('firm_name', 'Lead')} — Legal Conquesting Plan",
        "recommended_package": rp.get("package_name", ""),
        "recommended_investment": rp.get("monthly_investment", ""),
        "opportunity_value_monthly": monthly,
        "opportunity_value_annual": monthly * 12 if monthly else None,
        # --- Report custom fields ---
        "practice_area": report.get("practice_area", payload.get("practice_area", "")),
        "market_type": report.get("market_type", ""),
        "market_summary": report.get("market_summary", ""),
        "estimated_annual_cases_base": mp.get("estimated_annual_cases_base"),
        "case_volume_label": mp.get("case_volume_label", ""),
        "weather_triggers": ", ".join(report.get("weather_triggers", []) or []),
        "report_pdf_url": pdf_url,
        "report_json": json.dumps(report, separators=(",", ":"))[:60000],
    }
    try:
        requests.post(WEBHOOK_URL, json=body, timeout=12)
    except requests.RequestException:
        app.logger.exception("Webhook delivery failed")


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "smart1legal"})


@app.post("/api/analyze")
def analyze():
    try:
        payload = clean_payload(request.get_json(silent=True) or {})
        report = generate_report(payload)
        base_url = PUBLIC_BASE_URL or request.url_root
        pdf_url = build_report_pdf(report, payload.get("firm_name", "Legal Market Report"), base_url)
        send_webhook(payload, report, "completed", pdf_url)
        return jsonify({"ok": True, "report": report, "report_pdf_url": pdf_url})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("Analysis failed")
        try:
            send_webhook(clean_payload(request.get_json(silent=True) or {}), None, "failed")
        except Exception:
            pass
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "The plan could not be generated. Check the server configuration and try again.",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            ),
            500,
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
