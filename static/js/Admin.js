/* admin.js */

function liveValidateAdminUser() {
  var v = document.getElementById("adminUser").value.trim();
  setInputState(document.getElementById("adminUser"), v.length > 0 ? "valid" : "");
}

function liveValidateAdminPw() {
  var v = document.getElementById("adminPw").value;
  setInputState(document.getElementById("adminPw"), v.length >= 1 ? "valid" : "");
}

function handleAdminLogin() {
  var username = document.getElementById("adminUser").value.trim();
  var password = document.getElementById("adminPw").value;
  var btn      = document.getElementById("adminBtn");

  hideAlert("adminAlert");

  if (!username) {
    showAlert("adminAlert", "Please enter admin username.", "err");
    return;
  }
  if (!password) {
    showAlert("adminAlert", "Please enter admin password.", "err");
    return;
  }

  btn.disabled = true;
  btn.textContent = "Verifying…";

  fetch("/api/admin-login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: username, password: password })
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.success) {
      window.location.href = data.redirect || "/admin/dashboard";
    } else {
      showAlert("adminAlert", data.message || "Invalid credentials.", "err");
      btn.disabled = false;
      btn.textContent = "Access Admin Panel";
    }
  })
  .catch(function() {
    showAlert("adminAlert", "Network error. Please try again.", "err");
    btn.disabled = false;
    btn.textContent = "Access Admin Panel";
  });
}