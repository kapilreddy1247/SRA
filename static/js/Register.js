/* register.js
 * Live validation + inline field-level error messages only — no top banner.
 * On submit → JSON POST to /api/register → Flask inserts into SQLite.
 */

var _role = "student";

/* ── Role toggle ────────────────────────────────────────────────── */
function setRole(r) {
  _role = r;
  document.getElementById("roleStudent")
    .classList.toggle("active", r === "student");
  document.getElementById("roleProfessional")
    .classList.toggle("active", r === "professional");
}

/* ── Individual live validators ─────────────────────────────────── */
function liveValidateName() {
  var v   = document.getElementById("regName").value.trim();
  var inp = document.getElementById("regName");
  if (!v)          { setInputState(inp, "");        setHint("hintName", "", "");                     return; }
  if (v.length < 2){ setInputState(inp, "invalid"); setHint("hintName", "Name is too short", "err"); return; }
  setInputState(inp, "valid"); setHint("hintName", "✓ Looks good", "ok");
}

function liveValidateUsername() {
  var v   = document.getElementById("regUser").value.trim();
  var inp = document.getElementById("regUser");
  if (!v) { setInputState(inp, ""); setHint("hintUser", "", ""); return; }
  if (!/^[a-zA-Z0-9_]{3,}$/.test(v)) {
    setInputState(inp, "invalid");
    setHint("hintUser", "3+ chars · letters, numbers or _ only", "err");
    return;
  }
  setInputState(inp, "valid"); setHint("hintUser", "✓ Valid username", "ok");
}

function liveValidateEmail() {
  var v   = document.getElementById("regEmail").value.trim();
  var inp = document.getElementById("regEmail");
  if (!v) { setInputState(inp, ""); setHint("hintEmail", "", ""); return; }
  if (!isValidEmail(v)) {
    setInputState(inp, "invalid"); setHint("hintEmail", "Enter a valid email address", "err"); return;
  }
  setInputState(inp, "valid"); setHint("hintEmail", "✓ Valid email", "ok");
}

function liveValidatePhone() {
  var v   = document.getElementById("regPhone").value;
  var inp = document.getElementById("regPhone");
  if (!v) { setInputState(inp, ""); setHint("hintPhone", "", ""); return; }
  if (v.length < 10) {
    setInputState(inp, "invalid"); setHint("hintPhone", v.length + " / 10 digits", "err"); return;
  }
  if (!/^[6-9]/.test(v)) {
    setInputState(inp, "invalid"); setHint("hintPhone", "Must start with 6, 7, 8 or 9", "err"); return;
  }
  if (/^(.)\1{9}$/.test(v)) {
    setInputState(inp, "invalid"); setHint("hintPhone", "Not a valid number", "err"); return;
  }
  setInputState(inp, "valid"); setHint("hintPhone", "✓ Valid mobile number", "ok");
}

/* ── Password strength ──────────────────────────────────────────── */
function _pwStrength(pw) {
  var s = 0;
  if (pw.length >= 8)           s++;
  if (/[A-Z]/.test(pw))        s++;
  if (/[0-9]/.test(pw))        s++;
  if (/[^A-Za-z0-9]/.test(pw)) s++;
  return s;
}

var _strengthColors = ["", "s1", "s2", "s3", "s4"];
var _strengthLabels = ["", "Weak", "Fair", "Good", "Strong"];

function _renderBar(score) {
  var segs = document.querySelectorAll("#pwStrengthBar .strength-seg");
  segs.forEach(function(seg, i) {
    seg.className = "strength-seg" + (i < score ? " " + _strengthColors[score] : "");
  });
}

function liveValidatePassword() {
  var pw    = document.getElementById("regPw").value;
  var inp   = document.getElementById("regPw");
  var score = _pwStrength(pw);

  if (!pw) {
    setInputState(inp, ""); _renderBar(0); setHint("hintPw", "", "");
    liveValidateConfirm(); return;
  }
  _renderBar(score);
  if (score < 4) {
    setInputState(inp, "invalid");
    var missing = [];
    if (pw.length < 8)            missing.push("8+ chars");
    if (!/[A-Z]/.test(pw))        missing.push("uppercase");
    if (!/[0-9]/.test(pw))        missing.push("number");
    if (!/[^A-Za-z0-9]/.test(pw)) missing.push("symbol");
    setHint("hintPw", _strengthLabels[score] + " — needs: " + missing.join(", "), "err");
  } else {
    setInputState(inp, "valid");
    setHint("hintPw", "✓ Strong password", "ok");
  }
  liveValidateConfirm();
}

function liveValidateConfirm() {
  var pw  = document.getElementById("regPw").value;
  var cfm = document.getElementById("regConfirm").value;
  var inp = document.getElementById("regConfirm");
  if (!cfm) { setInputState(inp, ""); setHint("hintConfirm", "", ""); return; }
  if (pw !== cfm) {
    setInputState(inp, "invalid"); setHint("hintConfirm", "Passwords do not match", "err"); return;
  }
  setInputState(inp, "valid"); setHint("hintConfirm", "✓ Passwords match", "ok");
}

/* ── Inline field error (client + server errors both use this) ───── */
function _fieldErr(hintId, inputId, msg) {
  var inp = document.getElementById(inputId);
  if (inp) { setInputState(inp, "invalid"); inp.focus(); }
  setHint(hintId, msg, "err");
}

/* ── Submit ──────────────────────────────────────────────────────── */
function handleRegister() {
  var name    = document.getElementById("regName").value.trim();
  var user    = document.getElementById("regUser").value.trim();
  var email   = document.getElementById("regEmail").value.trim();
  var phone   = document.getElementById("regPhone").value.trim();
  var pw      = document.getElementById("regPw").value;
  var confirm = document.getElementById("regConfirm").value;
  var btn     = document.getElementById("regBtn");

  /* ── Client-side guards — all go to field hints, no top banner ── */
  if (!name || name.length < 2) {
    _fieldErr("hintName", "regName", name ? "Name is too short" : "Full name is required"); return;
  }
  if (!user) {
    _fieldErr("hintUser", "regUser", "Username is required"); return;
  }
  if (!/^[a-zA-Z0-9_]{3,}$/.test(user)) {
    _fieldErr("hintUser", "regUser", "3+ chars · letters, numbers or _ only"); return;
  }
  if (!email || !isValidEmail(email)) {
    _fieldErr("hintEmail", "regEmail", email ? "Enter a valid email address" : "Email is required"); return;
  }
  if (_pwStrength(pw) < 4) {
    _fieldErr("hintPw", "regPw", "Use a stronger password (uppercase, number, symbol, 8+ chars)"); return;
  }
  if (pw !== confirm) {
    _fieldErr("hintConfirm", "regConfirm", "Passwords do not match"); return;
  }
  /* Phone is required — full client-side validation */
  if (!phone) {
    _fieldErr("hintPhone", "regPhone", "Phone number is required"); return;
  }
  if (!/^[6-9]/.test(phone)) {
    _fieldErr("hintPhone", "regPhone", "Must start with 6, 7, 8 or 9"); return;
  }
  if (phone.length !== 10) {
    _fieldErr("hintPhone", "regPhone", "Enter a valid 10-digit phone number"); return;
  }
  if (/^(.)\1{9}$/.test(phone)) {
    _fieldErr("hintPhone", "regPhone", "Not a valid phone number"); return;
  }

  btn.disabled    = true;
  btn.textContent = "Creating account…";

  fetch("/api/register", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: name, username: user, email: email,
      phone: phone, role: _role,
      password: pw, confirm: confirm
    })
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.success) {
      btn.textContent = "Welcome! Redirecting…";
      window.location.href = data.redirect || "/dashboard";
      return;
    }

    btn.disabled    = false;
    btn.textContent = "Create Account";

    /* ── Route server error to the exact field ── */
    var msg = (data.message || "").toLowerCase();
    if (msg.includes("username")) {
      _fieldErr("hintUser",    "regUser",    data.message);
    } else if (msg.includes("email")) {
      _fieldErr("hintEmail",   "regEmail",   data.message);
    } else if (msg.includes("phone") || msg.includes("mobile")) {
      _fieldErr("hintPhone",   "regPhone",   data.message);
    } else if (msg.includes("password")) {
      _fieldErr("hintPw",      "regPw",      data.message);
    } else if (msg.includes("name")) {
      _fieldErr("hintName",    "regName",    data.message);
    } else {
      _fieldErr("hintUser",    "regUser",    data.message || "Registration failed. Please try again.");
    }
  })
  .catch(function() {
    btn.disabled    = false;
    btn.textContent = "Create Account";
    _fieldErr("hintUser", "regUser", "Network error — please try again.");
  });
}