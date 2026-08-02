"""
utils/mailer.py — Smart Resume Analyzer
=========================================
Standalone email module.  All email sending lives here — App.py
imports only the two public functions:

    send_welcome_email(to_email, full_name, dashboard_url)
    send_reset_email(to_email, reset_url)

Colour scheme  (matches the web UI):
    Indigo  #3730A3  — primary brand / headers
    Coral   #F4622A  — CTA buttons / accents
    Green   #059669  — success badges / feature icons

Template anatomy (both emails share the same shell):
    ┌─────────────────────────────────────┐
    │  INDIGO header bar  (logo + label)  │
    │  CORAL accent stripe                │
    ├─────────────────────────────────────┤
    │  Body content (unique per email)    │
    ├─────────────────────────────────────┤
    │  Grey footer  (disclaimer + date)   │
    └─────────────────────────────────────┘

Config is imported from App.py constants:
    EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_NAME, SMTP_HOST, SMTP_PORT
These are passed in at call time so this module stays config-free.
"""

import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text       import MIMEText

# ── Palette ───────────────────────────────────────────────────────────────────
# ── Primary: Orange · Secondary: Green · Accent: Indigo · Text: Black ─────────
_ORANGE        = "#F97316"   # primary — buttons, header stripe, highlights
_ORANGE_DARK   = "#EA6A08"   # hover / darker shade
_ORANGE_DIM    = "#FFF7ED"   # light orange background tint
_ORANGE_BORDER = "#FED7AA"   # orange border / divider

_GREEN         = "#16A34A"   # secondary — success, features, tip boxes
_GREEN_DARK    = "#15803D"
_GREEN_BG      = "#F0FDF4"   # very light green background
_GREEN_BORDER  = "#86EFAC"   # green border

_INDIGO        = "#3730A3"   # accent — links, badges, URL text
_INDIGO_DIM    = "#EEF2FF"   # light indigo tint
_INDIGO_BORDER = "#C7D2FE"   # indigo border

_BLACK         = "#000000"   # primary text
_DARK          = "#1a1a1a"   # body text (near-black)
_MUTED         = "#4B5563"   # secondary text (dark grey)
_LIGHT_MUTED   = "#9CA3AF"   # footer / disclaimer text
_SURFACE       = "#F9FAFB"   # footer background
_BORDER        = "#E5E7EB"   # dividers
_WHITE         = "#FFFFFF"
_BG            = "#F5F5F5"   # outer email background

# ── Shared HTML shell ─────────────────────────────────────────────────────────

def _shell(header_label: str, accent_color: str, body_html: str) -> str:
    """
    Wraps body_html in the shared 3-colour email shell.
    accent_color: colour for the thin stripe below the indigo header bar.
    """
    year = datetime.now(timezone.utc).year
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
</head>
<body style="margin:0;padding:0;background:{_BG};font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
    <tr>
      <td align="center" style="padding:32px 16px;">

        <table width="560" cellpadding="0" cellspacing="0" role="presentation"
               style="background:{_WHITE};border-radius:14px;overflow:hidden;
                      box-shadow:0 4px 24px rgba(0,0,0,.10);max-width:100%;">

          <!-- ── Indigo header bar ── -->
          <tr>
            <td style="background:{_ORANGE};padding:22px 32px 20px;">
              <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                <tr>
                  <td>
                    <p style="margin:0;color:{_WHITE};font-size:19px;
                               font-weight:bold;letter-spacing:-.2px;">
                      Smart Resume Analyzer
                    </p>
                    <p style="margin:5px 0 0;color:rgba(255,255,255,.85);font-size:12px;">
                      {header_label}
                    </p>
                  </td>
                  <td align="right" style="vertical-align:middle;">
                    <span style="display:inline-block;background:rgba(255,255,255,.18);
                                 color:{_WHITE};font-size:11px;font-weight:600;
                                 padding:5px 12px;border-radius:999px;
                                 border:1px solid rgba(255,255,255,.30);">
                      SRA
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- ── Accent stripe ── -->
          <tr>
            <td style="background:{accent_color};height:4px;font-size:0;line-height:0;">
              &nbsp;
            </td>
          </tr>

          <!-- ── Body ── -->
          <tr>
            <td style="padding:32px 32px 28px;">
              {body_html}
            </td>
          </tr>

          <!-- ── Footer ── -->
          <tr>
            <td style="background:{_SURFACE};padding:16px 32px;
                       border-top:1px solid {_BORDER};">
              <p style="margin:0;color:{_LIGHT_MUTED};font-size:11px;
                         text-align:center;line-height:1.6;">
                Smart Resume Analyzer &nbsp;·&nbsp;
                Automated message — please do not reply
                &nbsp;·&nbsp; &copy; {year}
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


# ── Reusable HTML snippets ────────────────────────────────────────────────────

def _btn(url: str, label: str, color: str = None) -> str:
    """Solid colour CTA button. Defaults to orange."""
    bg = color or _ORANGE
    return f"""
<table cellpadding="0" cellspacing="0" role="presentation" style="margin:24px 0;">
  <tr>
    <td style="background:{bg};border-radius:8px;
               box-shadow:0 2px 6px rgba(0,0,0,.15);">
      <a href="{url}"
         style="display:inline-block;padding:13px 32px;color:{_WHITE};
                font-size:14px;font-weight:bold;text-decoration:none;
                letter-spacing:.2px;">
        {label}
      </a>
    </td>
  </tr>
</table>"""


def _feature_row(icon: str, title: str, desc: str,
                 accent: str = None, border: str = None) -> str:
    """Single feature row with left-coloured border."""
    bg  = accent or _ORANGE_DIM
    bdr = border or _ORANGE
    return f"""
<tr>
  <td style="padding:11px 15px;background:{bg};border-radius:8px;
             border-left:4px solid {bdr};">
    <p style="margin:0;color:{_BLACK};font-size:13px;
               font-weight:700;line-height:1.4;">
      {icon}&nbsp; {title}
    </p>
    <p style="margin:3px 0 0;color:{_MUTED};font-size:12px;line-height:1.5;">
      {desc}
    </p>
  </td>
</tr>
<tr><td style="height:8px;"></td></tr>"""


def _divider() -> str:
    return f'<hr style="border:none;border-top:1px solid {_BORDER};margin:24px 0;"/>'


def _small_note(text: str) -> str:
    return (f'<p style="margin:0;color:{_LIGHT_MUTED};font-size:12px;'
            f'line-height:1.7;">{text}</p>')


# ── Welcome email ─────────────────────────────────────────────────────────────

def _welcome_html(first_name: str, dashboard_url: str) -> str:
    features = (
        _feature_row("📄", "Upload your resume",
                     "Supports text-based PDF files up to 5 MB",
                     _ORANGE_DIM, _ORANGE)
      + _feature_row("🎯", "Choose a target job role",
                     "686+ roles across 16 industry categories",
                     _GREEN_BG, _GREEN)
      + _feature_row("📊", "Get your readiness score",
                     "Full skill gap breakdown — core, secondary & bonus",
                     _ORANGE_DIM, _ORANGE)
      + _feature_row("💡", "Personalised recommendations",
                     "Top 5 roles that match your existing skills",
                     _GREEN_BG, _GREEN)
    )

    body = f"""
      <!-- Greeting -->
      <p style="margin:0 0 4px;color:{_BLACK};font-size:23px;font-weight:800;
                 letter-spacing:-.3px;">
        Welcome, {first_name}! 🎉
      </p>
      <p style="margin:0 0 24px;color:{_MUTED};font-size:14px;line-height:1.65;">
        Your Smart Resume Analyzer account is all set.
        Here's what you can do right now:
      </p>

      <!-- Feature list -->
      <table cellpadding="0" cellspacing="0" width="100%"
             role="presentation" style="margin-bottom:24px;">
        {features}
      </table>

      <!-- CTA — orange -->
      {_btn(dashboard_url, "Go to My Dashboard →", _ORANGE)}

      <!-- Divider -->
      <hr style="border:none;border-top:1px solid {_BORDER};margin:24px 0;"/>

      <!-- Green tip box -->
      <table cellpadding="0" cellspacing="0" width="100%" role="presentation">
        <tr>
          <td style="background:{_GREEN_BG};border-radius:8px;
                     border-left:4px solid {_GREEN};padding:13px 16px;">
            <p style="margin:0;color:{_GREEN_DARK};font-size:13px;font-weight:700;">
              💡 Pro tip
            </p>
            <p style="margin:5px 0 0;color:{_DARK};font-size:12px;line-height:1.65;">
              Use a <b>text-based PDF</b> (not a scanned image) for the best results.
              Make sure your skills are spelled correctly — the analyser matches
              them word-for-word.
            </p>
          </td>
        </tr>
      </table>

      <br/>
      <p style="margin:0;color:{_LIGHT_MUTED};font-size:12px;line-height:1.6;">
        If you didn't create this account, you can safely ignore this email.
      </p>
    """
    return _shell("Welcome aboard", _GREEN, body)


def _welcome_plain(first_name: str, dashboard_url: str) -> str:
    return f"""Hi {first_name},

Welcome to Smart Resume Analyzer! Your account is ready.

Here's what you can do:
  • Upload your resume (PDF, up to 5 MB)
  • Select a target job role from 686+ options
  • Get your readiness score with full skill gap analysis
  • See top role recommendations based on your skills

Get started: {dashboard_url}

Pro tip: Use a text-based PDF (not a scanned image) for best results.

Happy analysing!
— Smart Resume Analyzer Team

If you didn't create this account, please ignore this email.
"""


# ── Reset-password email ──────────────────────────────────────────────────────

def _reset_html(reset_url: str) -> str:
    body = f"""
      <!-- Orange badge -->
      <table cellpadding="0" cellspacing="0" role="presentation"
             style="margin-bottom:22px;">
        <tr>
          <td style="background:{_ORANGE_DIM};border:1.5px solid {_ORANGE_BORDER};
                     border-radius:999px;padding:7px 18px;">
            <p style="margin:0;color:{_ORANGE_DARK};font-size:13px;font-weight:700;">
              🔐 Password Reset Request
            </p>
          </td>
        </tr>
      </table>

      <!-- Heading -->
      <p style="margin:0 0 8px;color:{_BLACK};font-size:21px;font-weight:800;
                 letter-spacing:-.2px;">
        Reset your password
      </p>
      <p style="margin:0 0 22px;color:{_MUTED};font-size:14px;line-height:1.65;">
        We received a request to reset the password for your
        Smart Resume Analyzer account.<br/>
        This link is valid for
        <strong style="color:{_BLACK};">1 hour</strong>.
        Click the button below to continue.
      </p>

      <!-- CTA — orange -->
      {_btn(reset_url, "Reset My Password", _ORANGE)}

      <!-- Indigo URL fallback -->
      <p style="margin:0 0 6px;color:{_MUTED};font-size:12px;">
        Or copy and paste this link into your browser:
      </p>
      <p style="margin:0 0 24px;word-break:break-all;">
        <a href="{reset_url}"
           style="color:{_INDIGO};font-size:12px;text-decoration:underline;">
          {reset_url}
        </a>
      </p>

      <!-- Divider -->
      <hr style="border:none;border-top:1px solid {_BORDER};margin:8px 0 20px;"/>

      <!-- Green safety note -->
      <table cellpadding="0" cellspacing="0" width="100%" role="presentation">
        <tr>
          <td style="background:{_GREEN_BG};border-radius:8px;
                     border-left:4px solid {_GREEN};padding:13px 16px;">
            <p style="margin:0;color:{_GREEN_DARK};font-size:13px;font-weight:700;">
              ✅ Didn't request this?
            </p>
            <p style="margin:5px 0 0;color:{_DARK};font-size:12px;line-height:1.65;">
              No action needed — your password will
              <strong>not</strong> change unless you click the button above.
              You can safely ignore this email.
            </p>
          </td>
        </tr>
      </table>
    """
    return _shell("Password Reset", _ORANGE, body)


def _reset_plain(reset_url: str) -> str:
    return f"""Hi,

We received a request to reset your Smart Resume Analyzer password.

Reset link (valid for 1 hour):
{reset_url}

If you did not request this, ignore this email — your password will not change.

— Smart Resume Analyzer Team
"""


# ── SMTP core ─────────────────────────────────────────────────────────────────

def _smtp_send(
    *,
    to_email:   str,
    subject:    str,
    plain:      str,
    html:       str,
    sender:     str,
    password:   str,
    name:       str,
    host:       str,
    port:       int,
) -> bool:
    """
    Low-level SMTP send. All config passed explicitly — no globals.
    Returns True on success, False on any error.
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{name} <{sender}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(plain, "plain", "utf-8"))
        msg.attach(MIMEText(html,  "html",  "utf-8"))

        with smtplib.SMTP(host, port) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(sender, password)
            srv.sendmail(sender, to_email, msg.as_string())

        return True

    except Exception as exc:
        print(f"  [mailer] ERROR sending to {to_email}: {exc}")
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def send_welcome_email(
    *,
    to_email:      str,
    full_name:     str,
    dashboard_url: str,
    sender:        str,
    password:      str,
    name:          str  = "Smart Resume Analyzer",
    host:          str  = "smtp.gmail.com",
    port:          int  = 587,
) -> bool:
    """
    Send the welcome email to a newly registered user.

    Usage (from App.py):
        from utils.mailer import send_welcome_email
        send_welcome_email(
            to_email      = email,
            full_name     = name,
            dashboard_url = DEV_URL + "/dashboard",
            sender        = EMAIL_SENDER,
            password      = EMAIL_PASSWORD,
        )
    """
    first   = full_name.split()[0] if full_name else "there"
    subject = f"Welcome to Smart Resume Analyzer, {first}!"
    plain   = _welcome_plain(first, dashboard_url)
    html    = _welcome_html(first, dashboard_url)

    ok = _smtp_send(to_email=to_email, subject=subject, plain=plain, html=html,
                    sender=sender, password=password, name=name, host=host, port=port)
    if ok:
        print(f"  [mailer] Welcome email → {to_email}")
    return ok


def send_reset_email(
    *,
    to_email: str,
    reset_url: str,
    sender:   str,
    password: str,
    name:     str = "Smart Resume Analyzer",
    host:     str = "smtp.gmail.com",
    port:     int = 587,
) -> bool:
    """
    Send the password-reset email.

    Usage (from App.py):
        from utils.mailer import send_reset_email
        send_reset_email(
            to_email  = email,
            reset_url = DEV_URL + "/reset-password/" + token,
            sender    = EMAIL_SENDER,
            password  = EMAIL_PASSWORD,
        )
    """
    subject = "Reset your Smart Resume Analyzer password"
    plain   = _reset_plain(reset_url)
    html    = _reset_html(reset_url)

    ok = _smtp_send(to_email=to_email, subject=subject, plain=plain, html=html,
                    sender=sender, password=password, name=name, host=host, port=port)
    if ok:
        print(f"  [mailer] Reset email → {to_email}")
    else:
        print(f"  [mailer] FAILED — reset link (for dev): {reset_url}")
    return ok