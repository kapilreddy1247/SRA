"""
App.py — Smart Resume Analyzer
================================
Flask application — routes, database, auth, and startup.

Database tables (10):
  users                    — registered users
  admins                   — admin accounts
  password_resets          — one-time reset tokens
  skills                   — master skill list    (seeded from skills.csv)
  job_roles                — master role list     (seeded from roles.csv)
  role_skills              — role ↔ skill map     (seeded from roles.csv)
  resumes                  — uploaded PDF records
  resume_skills            — skills detected per resume
  analyses                 — analysis results
  analysis_recommendations — top-5 recommended roles per analysis

Install:  pip install flask bcrypt
Run:      python App.py

Email:    Fill EMAIL_SENDER + EMAIL_PASSWORD in the config section below.
          Needs a Gmail App Password:
          myaccount.google.com → Security → 2-Step Verification → App passwords
"""

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  1. Imports                                                                 │
# └─────────────────────────────────────────────────────────────────────────────┘

import os
import re
import csv
import sqlite3
import secrets
import threading
import webbrowser
from datetime import datetime, timedelta

import bcrypt
from flask import (
    Flask, render_template, redirect, url_for,
    request, session, jsonify, g, send_file, send_from_directory,
)

from utils.pdf_parser import extract as pdf_extract
from utils.report_gen  import generate as generate_report
from utils.mailer      import send_welcome_email, send_reset_email
from model.analyser    import analyser

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  2. Flask app & file paths                                                  │
# └─────────────────────────────────────────────────────────────────────────────┘

app = Flask(__name__)
app.secret_key = "sra-secret-change-before-deploy-2024"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_PERMANENT"]       = False   # session cookie expires on browser close
# Do NOT set PERMANENT_SESSION_LIFETIME when SESSION_PERMANENT is False,
# as setting it can cause Werkzeug to attach an expiry and make the cookie persistent.
# timedelta is kept imported for password reset token logic only.

BASE       = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(BASE, "sra.db")
DATA_DIR   = os.path.join(BASE, "model", "data")
SKILLS_CSV = os.path.join(DATA_DIR, "skills.csv")
ROLES_CSV  = os.path.join(DATA_DIR, "roles.csv")
UPLOAD_DIR = os.path.join(BASE, "uploads", "resumes")
REPORT_DIR = os.path.join(BASE, "reports")
DEV_URL    = "http://127.0.0.1:5000"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  3. Email config  ← fill these two lines                                   │
# └─────────────────────────────────────────────────────────────────────────────┘
#
#   Steps to get an App Password:
#     1. Enable 2-Step Verification at myaccount.google.com → Security
#     2. Search "App passwords" → create one for Mail
#     3. Paste the 16-character key below (spaces are fine)
#
# ─────────────────────────────────────────────────────────────────────────────
EMAIL_SENDER   = "YOUR EMAIL"   # ← your Gmail address
EMAIL_PASSWORD = "YOUR PASSWORD"   # ← 16-char App Password
EMAIL_NAME     = "Smart Resume Analyzer"
SMTP_HOST      = "smtp.gmail.com"
SMTP_PORT      = 587

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  4. Server run ID  (invalidates all sessions on every restart)              │
# └─────────────────────────────────────────────────────────────────────────────┘

_RUN_ID_FILE = os.path.join(BASE, ".server_run_id")
if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    with open(_RUN_ID_FILE) as _f:
        SERVER_RUN_ID = _f.read().strip()
else:
    SERVER_RUN_ID = secrets.token_hex(8)
    with open(_RUN_ID_FILE, "w") as _f:
        _f.write(SERVER_RUN_ID)

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  5. Database — connection, teardown, initialisation                         │
# └─────────────────────────────────────────────────────────────────────────────┘

def get_db():
    """Return a per-request SQLite connection (stored on Flask g)."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(_err=None):
    """Close DB connection at end of every request."""
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    """
    Create all 10 tables + indexes and seed CSVs.
    Idempotent — safe to call on every startup.
    """
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=OFF")   # re-enabled after seeding

    # ── Auth tables ───────────────────────────────────────────────────────────
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name     TEXT    NOT NULL,
            username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            email         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            phone         TEXT,
            role          TEXT    NOT NULL DEFAULT 'student',
            password_hash TEXT    NOT NULL,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS admins (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS password_resets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token      TEXT    NOT NULL UNIQUE,
            expires_at TEXT    NOT NULL,
            used       INTEGER NOT NULL DEFAULT 0
        );
    """)

    # ── Reference tables ──────────────────────────────────────────────────────
    db.executescript("""
        CREATE TABLE IF NOT EXISTS skills (
            id       INTEGER PRIMARY KEY,
            name     TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            category TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS job_roles (
            id       INTEGER PRIMARY KEY,
            name     TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            category TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS role_skills (
            role_id    INTEGER NOT NULL REFERENCES job_roles(id) ON DELETE CASCADE,
            skill_id   INTEGER NOT NULL REFERENCES skills(id)    ON DELETE CASCADE,
            importance TEXT    NOT NULL CHECK(importance IN ('core','secondary','bonus')),
            PRIMARY KEY (role_id, skill_id)
        );
    """)

    # ── User-data tables ──────────────────────────────────────────────────────
    db.executescript("""
        CREATE TABLE IF NOT EXISTS resumes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
            filename    TEXT    NOT NULL,
            stored_path TEXT    NOT NULL,
            raw_text    TEXT    NOT NULL DEFAULT '',
            uploaded_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS resume_skills (
            resume_id  INTEGER NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
            skill_id   INTEGER NOT NULL REFERENCES skills(id)  ON DELETE CASCADE,
            confidence REAL    NOT NULL DEFAULT 1.0,
            PRIMARY KEY (resume_id, skill_id)
        );

        CREATE TABLE IF NOT EXISTS analyses (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            resume_id         INTEGER NOT NULL REFERENCES resumes(id)  ON DELETE CASCADE,
            user_id           INTEGER NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
            selected_role_id  INTEGER NOT NULL REFERENCES job_roles(id),
            predicted_role_id INTEGER          REFERENCES job_roles(id),
            readiness_score   REAL    NOT NULL DEFAULT 0.0,
            report_path       TEXT,
            created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS analysis_recommendations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id INTEGER NOT NULL REFERENCES analyses(id)  ON DELETE CASCADE,
            role_id     INTEGER NOT NULL REFERENCES job_roles(id),
            match_score REAL    NOT NULL DEFAULT 0.0,
            rank        INTEGER NOT NULL CHECK(rank IN (1,2,3,4,5))
        );
    """)

    # ── Indexes ───────────────────────────────────────────────────────────────
    db.executescript("""
        CREATE INDEX IF NOT EXISTS idx_role_skills_role       ON role_skills(role_id);
        CREATE INDEX IF NOT EXISTS idx_role_skills_skill      ON role_skills(skill_id);
        CREATE INDEX IF NOT EXISTS idx_role_skills_importance ON role_skills(role_id, importance);
        CREATE INDEX IF NOT EXISTS idx_resume_skills_resume   ON resume_skills(resume_id);
        CREATE INDEX IF NOT EXISTS idx_analyses_user          ON analyses(user_id);
        CREATE INDEX IF NOT EXISTS idx_analyses_role          ON analyses(selected_role_id);
        CREATE INDEX IF NOT EXISTS idx_recommendations        ON analysis_recommendations(analysis_id);
    """)
    db.commit()

    # ── Default admin ─────────────────────────────────────────────────────────
    if db.execute("SELECT id FROM admins WHERE username='admin'").fetchone() is None:
        hashed = bcrypt.hashpw(b"Admin@123", bcrypt.gensalt()).decode()
        db.execute("INSERT INTO admins (username, password_hash) VALUES (?,?)",
                   ("admin", hashed))
        db.commit()
        print("  Seeded default admin  →  admin / Admin@123")

    # ── Seed skills.csv ───────────────────────────────────────────────────────
    if db.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 0:
        if not os.path.exists(SKILLS_CSV):
            print(f"  WARNING: {SKILLS_CSV} not found — skills not seeded")
        else:
            with open(SKILLS_CSV, encoding="utf-8") as f:
                rows = [(int(r["skill_id"]), r["skill_name"].strip(), r["category"].strip())
                        for r in csv.DictReader(f)]
            db.executemany(
                "INSERT OR IGNORE INTO skills (id, name, category) VALUES (?,?,?)", rows)
            db.commit()
            print(f"  Seeded {len(rows):,} skills")
    else:
        n = db.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        print(f"  Skills: {n:,} rows (already seeded)")

    # ── Seed roles.csv ────────────────────────────────────────────────────────
    if db.execute("SELECT COUNT(*) FROM job_roles").fetchone()[0] == 0:
        if not os.path.exists(ROLES_CSV):
            print(f"  WARNING: {ROLES_CSV} not found — roles not seeded")
        else:
            roles_seen, role_skill_rows = {}, []
            with open(ROLES_CSV, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    rid = int(r["role_id"])
                    if rid not in roles_seen:
                        roles_seen[rid] = (r["role_name"].strip(), r["category"].strip())
                    role_skill_rows.append(
                        (rid, int(r["skill_id"]), r["importance"].strip()))
            db.executemany(
                "INSERT OR IGNORE INTO job_roles (id, name, category) VALUES (?,?,?)",
                [(rid, v[0], v[1]) for rid, v in roles_seen.items()])
            db.executemany(
                "INSERT OR IGNORE INTO role_skills (role_id, skill_id, importance) VALUES (?,?,?)",
                role_skill_rows)
            db.commit()
            print(f"  Seeded {len(roles_seen):,} job roles")
            print(f"  Seeded {len(role_skill_rows):,} role-skill mappings")
    else:
        nr = db.execute("SELECT COUNT(*) FROM job_roles").fetchone()[0]
        ns = db.execute("SELECT COUNT(*) FROM role_skills").fetchone()[0]
        print(f"  Job roles: {nr:,} | Role-skills: {ns:,} (already seeded)")

    db.execute("PRAGMA foreign_keys=ON")
    db.close()
    print(f"\n  Database → {DB_PATH}")

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  6. Auth helpers                                                            │
# └─────────────────────────────────────────────────────────────────────────────┘

def hash_pw(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

def check_pw(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def logged_in() -> bool:
    """True when a valid user session exists."""
    return ("user_id" in session
            and session.get("server_run_id") == SERVER_RUN_ID)

def admin_logged_in() -> bool:
    """True when a valid admin session exists."""
    return (bool(session.get("is_admin"))
            and bool(session.get("admin_username"))
            and session.get("server_run_id") == SERVER_RUN_ID)

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  7. Email helpers  (thin wrappers — all logic lives in utils/mailer.py)     │
# └─────────────────────────────────────────────────────────────────────────────┘

def _mail_kwargs() -> dict:
    """Common SMTP kwargs passed to mailer functions."""
    return dict(sender=EMAIL_SENDER, password=EMAIL_PASSWORD,
                name=EMAIL_NAME, host=SMTP_HOST, port=SMTP_PORT)

def _send_welcome(email: str, full_name: str) -> None:
    send_welcome_email(
        to_email      = email,
        full_name     = full_name,
        dashboard_url = DEV_URL + "/dashboard",
        **_mail_kwargs(),
    )

def _send_reset(email: str, reset_url: str) -> bool:
    return send_reset_email(
        to_email  = email,
        reset_url = reset_url,
        **_mail_kwargs(),
    )

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  8. Static asset routes                                                     │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static", "img"),
        "favicon.ico", mimetype="image/vnd.microsoft.icon")

@app.route("/apple-touch-icon.png")
@app.route("/apple-touch-icon-precomposed.png")
def apple_touch_icon():
    return send_from_directory(
        os.path.join(app.root_path, "static", "img"),
        "apple-touch-icon.png", mimetype="image/png")

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  9. Auth routes — Login · Register · Forgot password · Reset password      │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/")
def index():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if logged_in():
        return redirect(url_for("dashboard"))
    if request.method == "GET":
        return render_template("Login.html",
                               identifier_error=None,
                               password_error=None,
                               identifier_value="")

    identifier = (request.form.get("identifier") or "").strip().lower()
    password   = request.form.get("password") or ""

    if not identifier or not password:
        return render_template("Login.html",
            identifier_error="Please enter your email or username." if not identifier else None,
            password_error  ="Please enter your password."          if not password   else None,
            identifier_value=identifier)

    db   = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE email=? OR username=?",
        (identifier, identifier),
    ).fetchone()

    if not user:
        return render_template("Login.html",
            identifier_error="No account found with that email or username.",
            password_error=None, identifier_value=identifier)

    if not check_pw(password, user["password_hash"]):
        return render_template("Login.html",
            identifier_error=None,
            password_error="Incorrect password.",
            identifier_value=identifier)

    session["user_id"]       = user["id"]
    session["username"]      = user["username"]
    session["full_name"]     = user["full_name"]
    session["server_run_id"] = SERVER_RUN_ID
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if logged_in():
        return redirect(url_for("dashboard"))
    if request.method == "GET":
        return render_template("Register.html", error=None, values={})

    name     = (request.form.get("name")     or "").strip()
    username = (request.form.get("username") or "").strip()
    email    = (request.form.get("email")    or "").strip().lower()
    phone    = (request.form.get("phone")    or "").strip()
    role     = request.form.get("role", "student")
    password = request.form.get("password") or ""
    confirm  = request.form.get("confirm")  or ""

    def fail(msg):
        return render_template("Register.html", error=msg,
                               values={"name": name, "username": username,
                                       "email": email, "phone": phone, "role": role})

    if not all([name, username, email, phone, password]):
        return fail("All fields are required.")
    if not re.match(r"^[a-zA-Z0-9_]{3,}$", username):
        return fail("Username: 3+ chars, letters / numbers / underscore only.")
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return fail("Invalid email address.")
    if len(password) < 8:
        return fail("Password must be at least 8 characters.")
    if password != confirm:
        return fail("Passwords do not match.")
    digits = re.sub(r"\D", "", phone)
    if (len(digits) != 10
            or not re.match(r"^[6-9]", digits)
            or re.match(r"^(\d)\1{9}$", digits)):
        return fail("Enter a valid 10-digit Indian mobile number.")
    phone = digits

    db = get_db()
    if db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
        return fail("Username already taken.")
    if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
        return fail("Email already registered.")

    cur = db.execute(
        "INSERT INTO users (full_name, username, email, phone, role, password_hash)"
        " VALUES (?,?,?,?,?,?)",
        (name, username, email, phone, role, hash_pw(password)),
    )
    db.commit()

    session["user_id"]       = cur.lastrowid
    session["username"]      = username
    session["full_name"]     = name
    session["server_run_id"] = SERVER_RUN_ID

    # Send welcome email only after successful DB insert + session set
    try:
        _send_welcome(email, name)
    except Exception as e:
        print(f"  [mailer] Welcome email error (non-fatal): {e}")

    return redirect(url_for("dashboard"))


@app.route("/api/register", methods=["POST"])
def api_register():
    """JSON endpoint used by register.js for live-validation registration."""
    if logged_in():
        return jsonify(success=True, redirect="/dashboard")

    data     = request.get_json(silent=True) or {}
    name     = (data.get("name")     or "").strip()
    username = (data.get("username") or "").strip()
    email    = (data.get("email")    or "").strip().lower()
    phone    = (data.get("phone")    or "").strip()
    role     = data.get("role", "student")
    password = data.get("password") or ""
    confirm  = data.get("confirm")  or ""

    def fail(msg):
        return jsonify(success=False, message=msg), 400

    if not all([name, username, email, phone, password]):
        return fail("All fields are required.")
    if not re.match(r"^[a-zA-Z0-9_]{3,}$", username):
        return fail("Username: 3+ chars, letters / numbers / underscore only.")
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return fail("Invalid email address.")
    if len(password) < 8:
        return fail("Password must be at least 8 characters.")
    if password != confirm:
        return fail("Passwords do not match.")
    digits = re.sub(r"\D", "", phone)
    if (len(digits) != 10
            or not re.match(r"^[6-9]", digits)
            or re.match(r"^(\d)\1{9}$", digits)):
        return fail("Enter a valid 10-digit Indian mobile number.")
    phone = digits

    db = get_db()
    if db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
        return fail("Username already taken.")
    if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
        return fail("Email already registered.")

    cur = db.execute(
        "INSERT INTO users (full_name, username, email, phone, role, password_hash)"
        " VALUES (?,?,?,?,?,?)",
        (name, username, email, phone, role, hash_pw(password)),
    )
    db.commit()
    user_id = cur.lastrowid
    if not user_id:
        return fail("Registration failed. Please try again.")

    session["user_id"]       = user_id
    session["username"]      = username
    session["full_name"]     = name
    session["server_run_id"] = SERVER_RUN_ID

    # Send welcome email only after successful DB insert + session set
    try:
        _send_welcome(email, name)
    except Exception as e:
        print(f"  [mailer] Welcome email error (non-fatal): {e}")

    return jsonify(success=True, redirect="/dashboard")


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "GET":
        return render_template("Forgot.html", error=None, success=None)

    email = (request.form.get("email") or "").strip().lower()
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return render_template("Forgot.html",
                               error="Enter a valid email address.", success=None)

    db   = get_db()
    user = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if not user:
        return render_template("Forgot.html",
            error="No account found with that email address. Please check and try again.",
            success=None)

    token     = secrets.token_urlsafe(32)
    expires   = (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    reset_url = DEV_URL + "/reset-password/" + token
    db.execute(
        "INSERT INTO password_resets (user_id, token, expires_at) VALUES (?,?,?)",
        (user["id"], token, expires))
    db.commit()

    _send_reset(email, reset_url)
    return render_template("Forgot.html", error=None, success="Reset link sent!")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    db    = get_db()
    reset = db.execute(
        "SELECT * FROM password_resets WHERE token=? AND used=0", (token,)
    ).fetchone()
    if not reset:
        return "<h2>Invalid or expired reset link.</h2>", 400
    if datetime.utcnow() > datetime.strptime(reset["expires_at"], "%Y-%m-%d %H:%M:%S"):
        return "<h2>This reset link has expired.</h2>", 400

    if request.method == "POST":
        password = request.form.get("password") or ""
        confirm  = request.form.get("confirm")  or ""
        if len(password) < 8:
            return render_template("ResetPassword.html", token=token,
                                   error="Password must be at least 8 characters.")
        if password != confirm:
            return render_template("ResetPassword.html", token=token,
                                   error="Passwords do not match.")
        db.execute("UPDATE users          SET password_hash=? WHERE id=?",
                   (hash_pw(password), reset["user_id"]))
        db.execute("UPDATE password_resets SET used=1         WHERE token=?", (token,))
        db.commit()
        return redirect(url_for("login"))

    return render_template("ResetPassword.html", token=token, error=None)

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  10. User dashboard & analysis API                                          │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/dashboard")
def dashboard():
    if not logged_in():
        return redirect(url_for("login"))
    db       = get_db()
    user     = db.execute("SELECT * FROM users WHERE id=?",
                          (session["user_id"],)).fetchone()
    analyses = db.execute("""
        SELECT a.id              AS analysis_id,
               a.readiness_score,
               a.created_at,
               a.report_path,
               jr.name          AS role_name,
               jr.category      AS role_category,
               r.filename       AS resume_filename
        FROM   analyses a
        JOIN   job_roles jr ON jr.id = a.selected_role_id
        JOIN   resumes   r  ON r.id  = a.resume_id
        WHERE  a.user_id = ?
        ORDER  BY a.created_at DESC
        LIMIT  10
    """, (session["user_id"],)).fetchall()
    return render_template("Dashboard.html", user=user, analyses=analyses)


@app.route("/api/roles")
def api_roles():
    """Role autocomplete — returns up to 10 matches."""
    q    = (request.args.get("q") or "").strip()
    rows = get_db().execute(
        "SELECT id, name, category FROM job_roles WHERE name LIKE ? ORDER BY name LIMIT 10",
        (f"%{q}%",),
    ).fetchall()
    return jsonify([{"id": r["id"], "name": r["name"], "category": r["category"]}
                    for r in rows])


@app.route("/api/history")
def api_history():
    """Last 10 analyses for the logged-in user."""
    if not logged_in():
        return jsonify(success=False, message="Not logged in."), 401
    rows = get_db().execute("""
        SELECT a.id              AS analysis_id,
               a.readiness_score,
               a.created_at,
               a.report_path,
               jr.name          AS role_name,
               jr.category      AS role_category,
               r.filename       AS resume_filename
        FROM   analyses a
        JOIN   job_roles jr ON jr.id = a.selected_role_id
        JOIN   resumes   r  ON r.id  = a.resume_id
        WHERE  a.user_id = ?
        ORDER  BY a.created_at DESC
        LIMIT  10
    """, (session["user_id"],)).fetchall()
    return jsonify(success=True, analyses=[dict(r) for r in rows])


@app.route("/api/analyse", methods=["POST"])
def api_analyse():
    """
    Full analysis pipeline:
      1. Validate role + PDF file
      2. Save PDF → extract text → run analyser
      3. Persist: resumes, resume_skills, analyses, analysis_recommendations
      4. Generate PDF report (non-fatal)
      5. Return JSON result
    """
    if not logged_in():
        return jsonify(success=False, message="Not logged in."), 401
    if not analyser.ready:
        return jsonify(success=False,
                       message="Analysis model not loaded. Run model/trainer.py first."), 503

    # ── Validate role ─────────────────────────────────────────────────────────
    role_id = request.form.get("role_id")
    if not role_id:
        return jsonify(success=False, message="Please select a job role."), 400
    try:
        role_id = int(role_id)
    except ValueError:
        return jsonify(success=False, message="Invalid role."), 400

    db   = get_db()
    role = db.execute("SELECT id, name FROM job_roles WHERE id=?", (role_id,)).fetchone()
    if not role:
        return jsonify(success=False, message="Role not found."), 404

    # ── Validate file ─────────────────────────────────────────────────────────
    if "resume" not in request.files:
        return jsonify(success=False, message="No file uploaded."), 400
    f = request.files["resume"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify(success=False, message="Only PDF files are accepted."), 400
    f.seek(0, 2); size = f.tell(); f.seek(0)
    if size > 5 * 1024 * 1024:
        return jsonify(success=False, message="File must be under 5 MB."), 400

    # ── Save PDF ──────────────────────────────────────────────────────────────
    safe_name  = f"{secrets.token_hex(8)}_{f.filename}"
    store_path = os.path.join(UPLOAD_DIR, safe_name)
    f.save(store_path)

    # ── Extract text ──────────────────────────────────────────────────────────
    raw_text = pdf_extract(store_path)
    if not raw_text.strip():
        return jsonify(success=False,
                       message="Could not extract text from this PDF. "
                               "It may be a scanned image — please use a text-based PDF."), 422

    # ── Run analyser ──────────────────────────────────────────────────────────
    try:
        result = analyser.run(raw_text, role_id, db)
    except Exception as e:
        return jsonify(success=False, message=f"Analysis failed: {e}"), 500

    # ── Persist results ───────────────────────────────────────────────────────
    resume_id = db.execute(
        "INSERT INTO resumes (user_id, filename, stored_path, raw_text) VALUES (?,?,?,?)",
        (session["user_id"], f.filename, store_path, raw_text),
    ).lastrowid

    if result["matched_skills"]:
        db.executemany(
            "INSERT OR IGNORE INTO resume_skills (resume_id, skill_id, confidence) VALUES (?,?,?)",
            [(resume_id, s["id"], 1.0) for s in result["matched_skills"]],
        )

    analysis_id = db.execute(
        "INSERT INTO analyses"
        " (resume_id, user_id, selected_role_id, predicted_role_id, readiness_score)"
        " VALUES (?,?,?,?,?)",
        (resume_id, session["user_id"], role_id,
         result["predicted_role_id"], result["readiness_score"]),
    ).lastrowid

    if result["recommendations"]:
        db.executemany(
            "INSERT INTO analysis_recommendations"
            " (analysis_id, role_id, match_score, rank) VALUES (?,?,?,?)",
            [(analysis_id, r["role_id"], r["score"], r["rank"])
             for r in result["recommendations"]],
        )
    db.commit()

    # ── Generate PDF report (non-fatal) ───────────────────────────────────────
    try:
        user_name   = db.execute("SELECT full_name FROM users WHERE id=?",
                                 (session["user_id"],)).fetchone()["full_name"]
        report_path = generate_report(analysis_id, result, user_name, role["name"], REPORT_DIR)
        db.execute("UPDATE analyses SET report_path=? WHERE id=?",
                   (report_path, analysis_id))
        db.commit()
    except Exception as e:
        print(f"  [report_gen] WARNING: {e}")

    return jsonify(
        success           = True,
        analysis_id       = analysis_id,
        readiness_score   = result["readiness_score"],
        predicted_role    = result["predicted_role"],
        selected_role     = role["name"],
        core_matched      = result["core_matched"],
        core_total        = result["core_total"],
        secondary_matched = result["secondary_matched"],
        secondary_total   = result["secondary_total"],
        bonus_matched     = result["bonus_matched"],
        bonus_total       = result["bonus_total"],
        matched_skills    = result["matched_skills"],
        missing_skills    = result["missing_skills"],
        recommendations   = result["recommendations"],
        scoring_breakdown = result["scoring_breakdown"],
    ), 200


@app.route("/api/result/<int:analysis_id>")
def api_result(analysis_id):
    """
    Full result JSON for the results panel.
    Re-runs analyser on stored raw_text so matched/missing skills
    always reflect the current role_skills definition.
    """
    if not logged_in():
        return jsonify(success=False, message="Not logged in."), 401

    db  = get_db()
    row = db.execute("""
        SELECT a.id,
               a.readiness_score,
               a.created_at,
               a.report_path,
               a.selected_role_id,
               jr_sel.name  AS selected_role,
               jr_pred.name AS predicted_role,
               r.filename   AS resume_filename,
               r.raw_text   AS raw_text
        FROM   analyses a
        JOIN   job_roles jr_sel       ON jr_sel.id  = a.selected_role_id
        LEFT JOIN job_roles jr_pred   ON jr_pred.id = a.predicted_role_id
        JOIN   resumes r              ON r.id        = a.resume_id
        WHERE  a.id=? AND a.user_id=?
    """, (analysis_id, session["user_id"])).fetchone()

    if not row:
        return jsonify(success=False, message="Analysis not found."), 404

    try:
        result            = analyser.run(row["raw_text"], row["selected_role_id"], db)
        matched_skills    = result["matched_skills"]
        missing_skills    = result["missing_skills"]
        scoring_breakdown = result.get("scoring_breakdown", {})
    except Exception:
        matched_skills = missing_skills = []
        scoring_breakdown = {}

    recs = db.execute("""
        SELECT ar.rank, ar.match_score, jr.name AS role_name
        FROM   analysis_recommendations ar
        JOIN   job_roles jr ON jr.id = ar.role_id
        WHERE  ar.analysis_id=?
        ORDER  BY ar.rank
    """, (analysis_id,)).fetchall()

    return jsonify(
        success           = True,
        analysis_id       = row["id"],
        readiness_score   = row["readiness_score"],
        selected_role     = row["selected_role"],
        predicted_role    = row["predicted_role"],
        resume_filename   = row["resume_filename"],
        created_at        = row["created_at"],
        report_path       = bool(row["report_path"]),
        matched_skills    = matched_skills,
        missing_skills    = missing_skills,
        scoring_breakdown = scoring_breakdown,
        recommendations   = [dict(r) for r in recs],
    )


@app.route("/report/<int:analysis_id>")
def download_report(analysis_id):
    """Download PDF report. Users: own only. Admins: any."""
    is_admin = admin_logged_in()
    is_user  = logged_in()
    if not is_admin and not is_user:
        return redirect(url_for("login"))

    db  = get_db()
    row = db.execute("SELECT report_path, user_id FROM analyses WHERE id=?",
                     (analysis_id,)).fetchone()
    if not row:
        return "Report not found.", 404
    if not is_admin and row["user_id"] != session.get("user_id"):
        return "Report not found.", 404
    if not row["report_path"] or not os.path.exists(row["report_path"]):
        return "Report file missing.", 404

    return send_file(row["report_path"], as_attachment=True,
                     download_name=f"analysis_{analysis_id}.pdf")

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  11. Admin routes — Login · Dashboard · User & admin management             │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/admin", methods=["GET", "POST"])
def admin_login_page():
    if admin_logged_in():
        return redirect(url_for("admin_dashboard"))
    if request.method == "GET":
        return render_template("Admin.html",
                               username_error=None, password_error=None, username_value="")

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    if not username:
        return render_template("Admin.html",
            username_error="Admin username is required.",
            password_error=None, username_value="")
    if not password:
        return render_template("Admin.html",
            username_error=None,
            password_error="Password is required.",
            username_value=username)

    db        = get_db()
    admin_row = db.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
    if not admin_row:
        return render_template("Admin.html",
            username_error="No admin account with that username.",
            password_error=None, username_value=username)
    if not check_pw(password, admin_row["password_hash"]):
        return render_template("Admin.html",
            username_error=None,
            password_error="Incorrect password.",
            username_value=username)

    session["is_admin"]       = True
    session["admin_username"] = username
    session["server_run_id"]  = SERVER_RUN_ID
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login_page"))


@app.route("/admin/api/beacon-logout", methods=["POST"])
def admin_beacon_logout():
    """Called via sendBeacon() when the admin tab/window closes."""
    session.clear()
    return "", 204


@app.route("/api/beacon-logout", methods=["POST"])
def user_beacon_logout():
    """Called via sendBeacon() when the user tab/window closes."""
    session.clear()
    return "", 204


@app.route("/admin/dashboard")
def admin_dashboard():
    if not admin_logged_in():
        return redirect(url_for("admin_login_page"))

    db     = get_db()
    users  = db.execute(
        "SELECT id, full_name, username, email, phone, role, created_at"
        " FROM users ORDER BY created_at DESC"
    ).fetchall()
    admins = db.execute("SELECT id, username FROM admins ORDER BY id").fetchall()

    top_role = db.execute("""
        SELECT jr.name, COUNT(*) AS cnt
        FROM   analyses a
        JOIN   job_roles jr ON jr.id = a.selected_role_id
        GROUP  BY a.selected_role_id
        ORDER  BY cnt DESC LIMIT 1
    """).fetchone()

    stats = {
        "total_analyses": db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0],
        "avg_readiness" : db.execute(
            "SELECT ROUND(AVG(readiness_score),1) FROM analyses").fetchone()[0] or 0,
        "top_role_name" : top_role["name"] if top_role else "—",
        "top_role_count": top_role["cnt"]  if top_role else 0,
    }

    recent_analyses = db.execute("""
        SELECT a.id, a.readiness_score, a.created_at, a.report_path,
               u.full_name, u.username,
               jr.name AS role_name
        FROM   analyses a
        JOIN   users     u  ON u.id  = a.user_id
        JOIN   job_roles jr ON jr.id = a.selected_role_id
        ORDER  BY a.created_at DESC
        LIMIT  20
    """).fetchall()

    return render_template("AdminDashboard.html",
                           users=users, admins=admins,
                           current_admin=session.get("admin_username"),
                           stats=stats, recent_analyses=recent_analyses)


@app.route("/admin/delete-user", methods=["POST"])
def admin_delete_user():
    if not admin_logged_in():
        return redirect(url_for("admin_login_page"))
    try:
        uid = int(request.form.get("user_id", ""))
        db  = get_db()
        db.execute("DELETE FROM users WHERE id=?", (uid,))
        db.commit()
    except (ValueError, TypeError):
        pass
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete-admin", methods=["POST"])
def admin_delete_admin():
    if not admin_logged_in():
        print(f"  [delete-admin] BLOCKED — not admin_logged_in. session={dict(session)}")
        return redirect(url_for("admin_login_page"))
    aid_raw = request.form.get("admin_id", "").strip()
    print(f"  [delete-admin] aid_raw={aid_raw!r} session_admin={session.get('admin_username')}")
    if not aid_raw or not aid_raw.isdigit():
        return redirect(url_for("admin_dashboard"))
    aid = int(aid_raw)
    db  = get_db()
    target = db.execute("SELECT username FROM admins WHERE id=?", (aid,)).fetchone()
    if not target:
        print(f"  [delete-admin] admin id={aid} not found in DB")
        return redirect(url_for("admin_dashboard"))
    if target["username"] == session.get("admin_username"):
        print(f"  [delete-admin] BLOCKED — cannot delete own account")
        return redirect(url_for("admin_dashboard"))
    count = db.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    if count <= 1:
        print(f"  [delete-admin] BLOCKED — last admin account")
        return redirect(url_for("admin_dashboard"))
    db.execute("DELETE FROM admins WHERE id=?", (aid,))
    db.commit()
    print(f"  [delete-admin] DELETED admin id={aid} username={target['username']}")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/add-admin", methods=["POST"])
def admin_add_admin():
    if not admin_logged_in():
        return redirect(url_for("admin_login_page"))

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    db       = get_db()

    def _admin_dashboard_ctx(admin_error=None):
        """Re-build admin dashboard context for error re-renders."""
        top_role = db.execute("""
            SELECT jr.name, COUNT(*) AS cnt FROM analyses a
            JOIN job_roles jr ON jr.id=a.selected_role_id
            GROUP BY a.selected_role_id ORDER BY cnt DESC LIMIT 1
        """).fetchone()
        return render_template("AdminDashboard.html",
            users  = db.execute("SELECT id, full_name, username, email, phone, role, created_at"
                                " FROM users ORDER BY created_at DESC").fetchall(),
            admins = db.execute("SELECT id, username FROM admins ORDER BY id").fetchall(),
            current_admin = session.get("admin_username"),
            stats = {
                "total_analyses": db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0],
                "avg_readiness" : db.execute(
                    "SELECT ROUND(AVG(readiness_score),1) FROM analyses").fetchone()[0] or 0,
                "top_role_name" : top_role["name"] if top_role else "—",
                "top_role_count": top_role["cnt"]  if top_role else 0,
            },
            recent_analyses = db.execute("""
                SELECT a.id, a.readiness_score, a.created_at, a.report_path,
                       u.full_name, u.username, jr.name AS role_name
                FROM analyses a JOIN users u ON u.id=a.user_id
                JOIN job_roles jr ON jr.id=a.selected_role_id
                ORDER BY a.created_at DESC LIMIT 20
            """).fetchall(),
            admin_error = admin_error,
        )

    if not username or not password:
        return _admin_dashboard_ctx("Username and password are required.")
    if len(username) < 3:
        return _admin_dashboard_ctx("Username must be at least 3 characters.")
    if len(password) < 8:
        return _admin_dashboard_ctx("Password must be at least 8 characters.")
    if (not re.search(r"[A-Z]", password)
            or not re.search(r"[0-9]", password)
            or not re.search(r"[^A-Za-z0-9]", password)):
        return _admin_dashboard_ctx(
            "Password needs an uppercase letter, a number, and a symbol.")
    if db.execute("SELECT id FROM admins WHERE username=?", (username,)).fetchone():
        return _admin_dashboard_ctx("Admin username already exists.")

    db.execute("INSERT INTO admins (username, password_hash) VALUES (?,?)",
               (username, hash_pw(password)))
    db.commit()
    return redirect(url_for("admin_dashboard"))


@app.route("/api/admin/add-admin", methods=["POST"])
def api_admin_add_admin():
    """JSON endpoint for Add Admin used by adminDashboard.js."""
    if not admin_logged_in():
        return jsonify(success=False, message="Unauthorised."), 403
    data     = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify(success=False, message="Username and password are required.")
    if len(username) < 3:
        return jsonify(success=False, message="Username must be at least 3 characters.")
    if len(password) < 8:
        return jsonify(success=False, message="Password must be at least 8 characters.")
    if (not re.search(r"[A-Z]", password)
            or not re.search(r"[0-9]", password)
            or not re.search(r"[^A-Za-z0-9]", password)):
        return jsonify(success=False,
                       message="Password needs an uppercase letter, a number, and a symbol.")
    db = get_db()
    if db.execute("SELECT id FROM admins WHERE username=?", (username,)).fetchone():
        return jsonify(success=False, message="Admin username already exists.")
    db.execute("INSERT INTO admins (username, password_hash) VALUES (?,?)",
               (username, hash_pw(password)))
    db.commit()
    return jsonify(success=True, message=f"Admin '{username}' added successfully.")


@app.route("/api/admin/delete-admin", methods=["POST"])
def api_admin_delete_admin():
    """JSON endpoint for Delete Admin used by adminDashboard.js."""
    if not admin_logged_in():
        return jsonify(success=False, message="Unauthorised."), 403
    data = request.get_json(force=True) or {}
    aid  = data.get("admin_id")
    if not aid:
        return jsonify(success=False, message="admin_id required.")
    try:
        aid = int(aid)
    except (ValueError, TypeError):
        return jsonify(success=False, message="Invalid admin_id.")
    db     = get_db()
    target = db.execute("SELECT username FROM admins WHERE id=?", (aid,)).fetchone()
    if not target:
        return jsonify(success=False, message="Admin not found.")
    if target["username"] == session.get("admin_username"):
        return jsonify(success=False, message="You cannot delete your own account.")
    if db.execute("SELECT COUNT(*) FROM admins").fetchone()[0] <= 1:
        return jsonify(success=False, message="Cannot delete the last admin account.")
    db.execute("DELETE FROM admins WHERE id=?", (aid,))
    db.commit()
    return jsonify(success=True, message=f"Admin '{target['username']}' deleted.")

@app.route("/api/admin/user/<int:uid>", methods=["DELETE"])
def api_delete_user(uid):
    """DELETE /api/admin/user/<id> — remove a user and all their data directly from the DB."""
    if not admin_logged_in():
        return jsonify(success=False, message="Unauthorised."), 403
    db = get_db()
    row = db.execute("SELECT id, full_name FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return jsonify(success=False, message="User not found."), 404
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    return jsonify(success=True, message=f"User '{row['full_name']}' deleted.")


@app.route("/api/admin/admin/<int:aid>", methods=["DELETE"])
def api_delete_admin(aid):
    """DELETE /api/admin/admin/<id> — remove an admin account directly from the DB."""
    if not admin_logged_in():
        return jsonify(success=False, message="Unauthorised."), 403
    db     = get_db()
    target = db.execute("SELECT username FROM admins WHERE id=?", (aid,)).fetchone()
    if not target:
        return jsonify(success=False, message="Admin not found."), 404
    if target["username"] == session.get("admin_username"):
        return jsonify(success=False, message="You cannot delete your own account."), 400
    if db.execute("SELECT COUNT(*) FROM admins").fetchone()[0] <= 1:
        return jsonify(success=False, message="Cannot delete the last admin account."), 400
    db.execute("DELETE FROM admins WHERE id=?", (aid,))
    db.commit()
    return jsonify(success=True, message=f"Admin '{target['username']}' deleted.")


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  12. Admin API — DB-based skills & roles management                         │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/admin/api/skills")
def admin_list_skills():
    if not admin_logged_in(): return jsonify(success=False), 403
    rows = get_db().execute(
        "SELECT id, name, category FROM skills ORDER BY category, name").fetchall()
    return jsonify(success=True, skills=[dict(r) for r in rows])


@app.route("/admin/api/skills/add", methods=["POST"])
def admin_add_skill():
    if not admin_logged_in(): return jsonify(success=False, error="Unauthorised"), 403
    data     = request.get_json(force=True) or {}
    name     = (data.get("name")     or "").strip()
    category = (data.get("category") or "").strip()
    if not name:     return jsonify(success=False, error="Skill name is required.")
    if not category: return jsonify(success=False, error="Category is required.")
    db = get_db()
    if db.execute("SELECT id FROM skills WHERE name=? COLLATE NOCASE", (name,)).fetchone():
        return jsonify(success=False, error=f"Skill '{name}' already exists.")
    db.execute("INSERT INTO skills (name, category) VALUES (?,?)", (name, category))
    db.commit()
    sid = db.execute("SELECT id FROM skills WHERE name=? COLLATE NOCASE",
                     (name,)).fetchone()["id"]
    return jsonify(success=True, skill={"id": sid, "name": name, "category": category})


@app.route("/admin/api/skills/delete", methods=["POST"])
def admin_delete_skill():
    if not admin_logged_in(): return jsonify(success=False, error="Unauthorised"), 403
    data     = request.get_json(force=True) or {}
    skill_id = data.get("skill_id")
    if not skill_id: return jsonify(success=False, error="skill_id required.")
    db   = get_db()
    used = db.execute("SELECT COUNT(*) FROM role_skills WHERE skill_id=?",
                      (skill_id,)).fetchone()[0]
    if used:
        return jsonify(success=False,
                       error=f"Cannot delete — skill used in {used} role(s). "
                             "Remove from those roles first.")
    db.execute("DELETE FROM skills WHERE id=?", (skill_id,))
    db.commit()
    return jsonify(success=True)


@app.route("/admin/api/roles/list")
def admin_list_roles():
    if not admin_logged_in(): return jsonify(success=False), 403
    q    = (request.args.get("q") or "").strip()
    rows = get_db().execute(
        "SELECT id, name, category FROM job_roles"
        " WHERE name LIKE ? ORDER BY category, name LIMIT 50",
        (f"%{q}%",)).fetchall()
    return jsonify(success=True, roles=[dict(r) for r in rows])


@app.route("/admin/api/roles/add", methods=["POST"])
def admin_add_role():
    if not admin_logged_in(): return jsonify(success=False, error="Unauthorised"), 403
    data     = request.get_json(force=True) or {}
    name     = (data.get("name")     or "").strip()
    category = (data.get("category") or "").strip()
    if not name:     return jsonify(success=False, error="Role name is required.")
    if not category: return jsonify(success=False, error="Category is required.")
    db = get_db()
    if db.execute("SELECT id FROM job_roles WHERE name=? COLLATE NOCASE",
                  (name,)).fetchone():
        return jsonify(success=False, error=f"Role '{name}' already exists.")
    db.execute("INSERT INTO job_roles (name, category) VALUES (?,?)", (name, category))
    db.commit()
    rid = db.execute("SELECT id FROM job_roles WHERE name=? COLLATE NOCASE",
                     (name,)).fetchone()["id"]
    return jsonify(success=True, role={"id": rid, "name": name, "category": category})


@app.route("/admin/api/roles/delete", methods=["POST"])
def admin_delete_role():
    if not admin_logged_in(): return jsonify(success=False, error="Unauthorised"), 403
    data    = request.get_json(force=True) or {}
    role_id = data.get("role_id")
    if not role_id: return jsonify(success=False, error="role_id required.")
    db   = get_db()
    used = db.execute("SELECT COUNT(*) FROM analyses WHERE selected_role_id=?",
                      (role_id,)).fetchone()[0]
    if used:
        return jsonify(success=False,
                       error=f"Cannot delete — role has {used} existing analysis/analyses.")
    db.execute("DELETE FROM role_skills WHERE role_id=?", (role_id,))
    db.execute("DELETE FROM job_roles   WHERE id=?",      (role_id,))
    db.commit()
    return jsonify(success=True)


@app.route("/admin/api/roles/<int:role_id>/skills")
def admin_role_skills(role_id):
    if not admin_logged_in(): return jsonify(success=False), 403
    db   = get_db()
    role = db.execute("SELECT id, name, category FROM job_roles WHERE id=?",
                      (role_id,)).fetchone()
    if not role: return jsonify(success=False, error="Role not found."), 404
    rows = db.execute("""
        SELECT s.id, s.name, s.category, rs.importance
        FROM   role_skills rs JOIN skills s ON s.id = rs.skill_id
        WHERE  rs.role_id=?
        ORDER  BY CASE rs.importance
                    WHEN 'core'      THEN 1
                    WHEN 'secondary' THEN 2
                    ELSE 3 END, s.name
    """, (role_id,)).fetchall()
    return jsonify(success=True, role=dict(role), skills=[dict(r) for r in rows])


@app.route("/admin/api/roles/<int:role_id>/skills/add", methods=["POST"])
def admin_add_role_skill(role_id):
    if not admin_logged_in(): return jsonify(success=False, error="Unauthorised"), 403
    data       = request.get_json(force=True) or {}
    skill_id   = data.get("skill_id")
    importance = (data.get("importance") or "").strip()
    if not skill_id:
        return jsonify(success=False, error="skill_id required.")
    if importance not in ("core", "secondary", "bonus"):
        return jsonify(success=False, error="importance must be core, secondary or bonus.")
    db = get_db()
    if not db.execute("SELECT id FROM job_roles WHERE id=?", (role_id,)).fetchone():
        return jsonify(success=False, error="Role not found."), 404
    if not db.execute("SELECT id FROM skills WHERE id=?", (skill_id,)).fetchone():
        return jsonify(success=False, error="Skill not found.")
    if db.execute("SELECT 1 FROM role_skills WHERE role_id=? AND skill_id=?",
                  (role_id, skill_id)).fetchone():
        return jsonify(success=False, error="Skill already assigned to this role.")
    db.execute("INSERT INTO role_skills (role_id, skill_id, importance) VALUES (?,?,?)",
               (role_id, skill_id, importance))
    db.commit()
    s = db.execute("SELECT id, name, category FROM skills WHERE id=?",
                   (skill_id,)).fetchone()
    return jsonify(success=True,
                   skill={"id": s["id"], "name": s["name"],
                          "category": s["category"], "importance": importance})


@app.route("/admin/api/roles/<int:role_id>/skills/remove", methods=["POST"])
def admin_remove_role_skill(role_id):
    if not admin_logged_in(): return jsonify(success=False, error="Unauthorised"), 403
    data     = request.get_json(force=True) or {}
    skill_id = data.get("skill_id")
    if not skill_id: return jsonify(success=False, error="skill_id required.")
    db = get_db()
    db.execute("DELETE FROM role_skills WHERE role_id=? AND skill_id=?",
               (role_id, skill_id))
    db.commit()
    return jsonify(success=True)


@app.route("/admin/api/roles/<int:role_id>/skills/update", methods=["POST"])
def admin_update_role_skill(role_id):
    if not admin_logged_in(): return jsonify(success=False, error="Unauthorised"), 403
    data       = request.get_json(force=True) or {}
    skill_id   = data.get("skill_id")
    importance = (data.get("importance") or "").strip()
    if not skill_id: return jsonify(success=False, error="skill_id required.")
    if importance not in ("core", "secondary", "bonus"):
        return jsonify(success=False, error="importance must be core, secondary or bonus.")
    db = get_db()
    db.execute("UPDATE role_skills SET importance=? WHERE role_id=? AND skill_id=?",
               (importance, role_id, skill_id))
    db.commit()
    return jsonify(success=True)

# 
#  13. Data Manager — CSV-backed skills & roles  (admin)                      
# 

# ── CSV readers ───────────────────────────────────────────────────────────────

def _read_skills_csv() -> list:
    if not os.path.exists(SKILLS_CSV):
        return []
    with open(SKILLS_CSV, encoding="utf-8") as f:
        return sorted(
            [{"skill_id":   int(r["skill_id"]),
              "skill_name": r["skill_name"].strip(),
              "category":   r["category"].strip()}
             for r in csv.DictReader(f)],
            key=lambda x: x["skill_id"])


def _read_roles_csv() -> list:
    if not os.path.exists(ROLES_CSV):
        return []
    seen, roles = {}, []
    with open(ROLES_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rid = int(r["role_id"])
            if rid not in seen:
                seen[rid] = True
                roles.append({"role_id":   rid,
                               "role_name": r["role_name"].strip(),
                               "category":  r["category"].strip()})
    return sorted(roles, key=lambda x: x["role_id"])


def _read_role_skills_csv(role_id: int) -> list:
    if not os.path.exists(ROLES_CSV):
        return []
    with open(ROLES_CSV, encoding="utf-8") as f:
        return [{"skill_id":   int(r["skill_id"]),
                 "skill_name": r["skill_name"].strip(),
                 "importance": r["importance"].strip()}
                for r in csv.DictReader(f)
                if r["role_id"].strip() and int(r["role_id"]) == role_id
                and r["skill_id"].strip()]

# ── List endpoints ────────────────────────────────────────────────────────────

@app.route("/admin/api/dm/skills")
def dm_list_skills():
    if not admin_logged_in(): return jsonify(success=False), 403
    return jsonify(success=True, skills=_read_skills_csv())


@app.route("/admin/api/dm/roles")
def dm_list_roles():
    if not admin_logged_in(): return jsonify(success=False), 403
    return jsonify(success=True, roles=_read_roles_csv())


@app.route("/admin/api/dm/roles/<int:role_id>/skills")
def dm_role_skills(role_id):
    if not admin_logged_in(): return jsonify(success=False), 403
    return jsonify(success=True, skills=_read_role_skills_csv(role_id))

# ── Write endpoints ───────────────────────────────────────────────────────────

@app.route("/admin/api/dm/skills/add", methods=["POST"])
def dm_add_skill():
    if not admin_logged_in(): return jsonify(success=False, error="Unauthorised"), 403
    data     = request.get_json(force=True) or {}
    name     = (data.get("name")     or "").strip()
    category = (data.get("category") or "").strip()
    if not name:     return jsonify(success=False, error="Skill name is required.")
    if not category: return jsonify(success=False, error="Category is required.")
    existing = _read_skills_csv()
    if any(r["skill_name"].lower() == name.lower() for r in existing):
        return jsonify(success=False, error=f"Skill '{name}' already exists in CSV.")
    new_id = (max(r["skill_id"] for r in existing) + 1) if existing else 1
    with open(SKILLS_CSV, "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow([new_id, name, category])
    return jsonify(success=True,
                   skill={"skill_id": new_id, "skill_name": name, "category": category})


@app.route("/admin/api/dm/roles/add", methods=["POST"])
def dm_add_role():
    if not admin_logged_in(): return jsonify(success=False, error="Unauthorised"), 403
    data     = request.get_json(force=True) or {}
    name     = (data.get("name")     or "").strip()
    category = (data.get("category") or "").strip()
    if not name:     return jsonify(success=False, error="Role name is required.")
    if not category: return jsonify(success=False, error="Category is required.")
    existing = _read_roles_csv()
    if any(r["role_name"].lower() == name.lower() for r in existing):
        return jsonify(success=False, error=f"Role '{name}' already exists in CSV.")
    new_id = (max(r["role_id"] for r in existing) + 1) if existing else 1
    with open(ROLES_CSV, "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow([new_id, name, category, "", "", ""])
    return jsonify(success=True,
                   role={"role_id": new_id, "role_name": name, "category": category})


@app.route("/admin/api/dm/roles/<int:role_id>/map", methods=["POST"])
def dm_map_role_skills(role_id):
    """Replace all skill mappings for a role in roles.csv."""
    if not admin_logged_in(): return jsonify(success=False, error="Unauthorised"), 403
    data = request.get_json(force=True) or {}
    raw  = (data.get("mappings") or "").strip()

    roles = _read_roles_csv()
    role  = next((r for r in roles if r["role_id"] == role_id), None)
    if not role:
        return jsonify(success=False, error="Role not found in CSV.")

    skill_map = {r["skill_id"]: r["skill_name"] for r in _read_skills_csv()}
    valid_imp = {"core", "secondary", "bonus"}
    parsed, errors = [], []

    for token in raw.replace("\n", ",").split(","):
        token = token.strip()
        if not token: continue
        if ":" not in token:
            errors.append(f"'{token}' — missing colon, use ID:importance"); continue
        sid_str, imp = token.split(":", 1)
        sid_str = sid_str.strip(); imp = imp.strip().lower()
        if not sid_str.isdigit():
            errors.append(f"'{sid_str}' — not a valid skill ID"); continue
        sid = int(sid_str)
        if sid not in skill_map:
            errors.append(f"Skill ID {sid} not found in skills.csv"); continue
        if imp not in valid_imp:
            errors.append(f"'{imp}' — must be core, secondary or bonus"); continue
        parsed.append((sid, skill_map[sid], imp))

    if errors:
        return jsonify(success=False, error="Errors:<br>" + "<br>".join(errors))
    if not parsed:
        return jsonify(success=False, error="No valid skill mappings entered.")

    with open(ROLES_CSV, encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    kept = [r for r in all_rows if int(r["role_id"]) != role_id]
    new_rows = [{"role_id": role_id, "role_name": role["role_name"],
                 "category": role["category"],
                 "skill_id": sid, "skill_name": sname, "importance": imp}
                for sid, sname, imp in parsed]
    with open(ROLES_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["role_id", "role_name", "category",
                                          "skill_id", "skill_name", "importance"])
        w.writeheader()
        w.writerows(kept + new_rows)

    return jsonify(success=True, count=len(parsed),
                   skills=[{"skill_id": s, "skill_name": n, "importance": i}
                           for s, n, i in parsed])


@app.route("/admin/api/dm/sync", methods=["POST"])
def dm_sync_to_db():
    """Sync skills.csv + roles.csv into the live DB. Additive only — never deletes."""
    if not admin_logged_in(): return jsonify(success=False, error="Unauthorised"), 403
    db = get_db()
    added_skills = added_roles = added_mappings = 0

    for r in _read_skills_csv():
        if not db.execute("SELECT id FROM skills WHERE id=?",
                          (r["skill_id"],)).fetchone():
            db.execute("INSERT OR IGNORE INTO skills (id, name, category) VALUES (?,?,?)",
                       (r["skill_id"], r["skill_name"], r["category"]))
            added_skills += 1

    if os.path.exists(ROLES_CSV):
        roles_seen, role_skill_rows = {}, []
        with open(ROLES_CSV, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rid = row["role_id"].strip()
                sid = row["skill_id"].strip()
                imp = row["importance"].strip()
                if not rid or not rid.isdigit(): continue
                rid = int(rid)
                if rid not in roles_seen:
                    roles_seen[rid] = (row["role_name"].strip(), row["category"].strip())
                if sid and sid.isdigit() and imp in ("core", "secondary", "bonus"):
                    role_skill_rows.append((rid, int(sid), imp))

        for rid, (rname, rcat) in roles_seen.items():
            if not db.execute("SELECT id FROM job_roles WHERE id=?", (rid,)).fetchone():
                db.execute(
                    "INSERT OR IGNORE INTO job_roles (id, name, category) VALUES (?,?,?)",
                    (rid, rname, rcat))
                added_roles += 1

        for rid, sid, imp in role_skill_rows:
            if not db.execute("SELECT 1 FROM role_skills WHERE role_id=? AND skill_id=?",
                              (rid, sid)).fetchone():
                db.execute(
                    "INSERT OR IGNORE INTO role_skills (role_id, skill_id, importance) VALUES (?,?,?)",
                    (rid, sid, imp))
                added_mappings += 1

    db.commit()
    return jsonify(
        success        = True,
        added_skills   = added_skills,
        added_roles    = added_roles,
        added_mappings = added_mappings,
        message        = (f"Sync complete — {added_skills} skill(s), "
                          f"{added_roles} role(s), {added_mappings} mapping(s) added to DB."),
    )

# 
#   14. Entry point                                                            
# 

if __name__ == "__main__":
    print("\n── Smart Resume Analyzer ───────────────────────────")
    init_db()
    try:
        analyser.load()
    except FileNotFoundError as e:
        print(f"  WARNING: {e}")
        print("  Analysis will be unavailable until model is trained.")
    threading.Timer(1.2, lambda: webbrowser.open(DEV_URL)).start()
    print(f"  Server  → {DEV_URL}\n")
    app.run(debug=True, host="127.0.0.1", port=5000)