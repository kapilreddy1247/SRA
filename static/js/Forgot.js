/* forgot.js */

function liveValidateForgotEmail() {
  var v   = document.getElementById("forgotEmail").value.trim();
  var inp = document.getElementById("forgotEmail");
  if (v.length === 0) { setInputState(inp, ""); return; }
  setInputState(inp, isValidEmail(v) ? "valid" : "invalid");
}

function handleForgotPassword() {
  var email = document.getElementById("forgotEmail").value.trim();
  var btn   = document.getElementById("forgotBtn");

  hideAlert("forgotAlert");

  if (!email || !isValidEmail(email)) {
    showAlert("forgotAlert", "Please enter a valid email address.", "err");
    return;
  }

  btn.disabled = true;
  btn.textContent = "Sending…";

  fetch("/api/forgot-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email })
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    showAlert("forgotAlert", data.message, data.success ? "ok" : "err");
    btn.disabled = false;
    btn.textContent = "Send Reset Link";
  })
  .catch(function() {
    showAlert("forgotAlert", "Network error. Please try again.", "err");
    btn.disabled = false;
    btn.textContent = "Send Reset Link";
  });
}