/* login.js */

function liveValidateLoginEmail() {
  var v = document.getElementById("siEmail").value.trim();
  setInputState(document.getElementById("siEmail"), v.length > 0 ? "valid" : "");
}

function liveValidateLoginPw() {
  var v = document.getElementById("siPw").value;
  setInputState(document.getElementById("siPw"), v.length >= 1 ? "valid" : "");
}

function handleSignIn() {
  var identifier = document.getElementById("siEmail").value.trim();
  var password   = document.getElementById("siPw").value;
  var btn        = document.getElementById("siBtn");

  hideAlert("siAlert");

  if (!identifier) {
    showAlert("siAlert", "Please enter your email or username.", "err");
    return;
  }
  if (!password) {
    showAlert("siAlert", "Please enter your password.", "err");
    return;
  }

  btn.disabled = true;
  btn.textContent = "Signing in…";

  fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: identifier, password: password })
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.success) {
      window.location.href = data.redirect || "/dashboard";
    } else {
      showAlert("siAlert", data.message || "Login failed.", "err");
      btn.disabled = false;
      btn.textContent = "Sign In";
    }
  })
  .catch(function() {
    showAlert("siAlert", "Network error. Please try again.", "err");
    btn.disabled = false;
    btn.textContent = "Sign In";
  });
}