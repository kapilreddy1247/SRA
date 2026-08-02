/* utils.js — shared helpers */

function toggleVisibility(inputId, btn) {
  var input = document.getElementById(inputId);
  if (!input) return;
  if (input.type === "password") {
    input.type = "text";
    btn.textContent = "Hide";
  } else {
    input.type = "password";
    btn.textContent = "Show";
  }
}

function showAlert(id, msg, type) {
  var el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.className = "alert alert-" + type + " show";
}

function hideAlert(id) {
  var el = document.getElementById(id);
  if (el) { el.className = "alert"; el.textContent = ""; }
}

function setHint(id, msg, cls) {
  var el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.className   = "field-hint" + (msg && cls ? " " + cls : "");
}

/* Clear login field error as user retypes */
function clearLoginErr(inputId, hintId) {
  var inp = document.getElementById(inputId);
  if (inp) inp.classList.remove("input-err");
  var hint = document.getElementById(hintId);
  if (hint) { hint.textContent = ""; hint.className = "field-hint"; }
}

function setInputState(inputEl, state) {
  if (!inputEl) return;
  inputEl.classList.remove("valid", "invalid");
  if (state) inputEl.classList.add(state);
}

function isValidEmail(v) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
}