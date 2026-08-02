/* adminDashboard.js
   Delete user / Delete admin  → plain form POST (handled by HTML)
   Add Admin                   → JS fetch
*/


/* ── Utility helpers ─────────────────────────────────── */
function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function showAlert(id, msg, type) {
  var el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = msg;
  el.className = 'alert' + (type ? ' alert-' + type + ' show' : '');
}

function adToast(msg, type) {
  var t = document.getElementById("adToast");
  if (!t) return;
  t.textContent = msg;
  t.className = "ad-toast show" + (type ? " t-" + type : "");
  setTimeout(function() { t.className = "ad-toast"; }, 3200);
}

function handleAddAdmin() {
  var username = (document.getElementById("newAdminUser").value || "").trim();
  var password = document.getElementById("newAdminPw").value || "";
  var alertEl  = document.getElementById("addAdminAlert");

  // hide previous alert
  if (alertEl) { alertEl.className = "alert"; alertEl.textContent = ""; }

  if (!username || !password) {
    if (alertEl) {
      alertEl.textContent = "Both username and password are required.";
      alertEl.className = "alert alert-err show";
    }
    return;
  }

  fetch("/api/admin/add-admin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: username, password: password })
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.success) {
      adToast(data.message, "ok");
      document.getElementById("newAdminUser").value = "";
      document.getElementById("newAdminPw").value   = "";
      setTimeout(function() { window.location.reload(); }, 900);
    } else {
      if (alertEl) {
        alertEl.textContent = data.message || "Failed to add admin.";
        alertEl.className = "alert alert-err show";
      }
    }
  })
  .catch(function() {
    if (alertEl) {
      alertEl.textContent = "Network error. Please try again.";
      alertEl.className = "alert alert-err show";
    }
  });
}

function handleDeleteUser(btn) {
  var userId       = btn.dataset.uid;
  var userFullName = btn.dataset.uname;
  if (!confirm('Delete "' + userFullName + '"? This cannot be undone.')) return;
  fetch('/api/admin/user/' + userId, {
    method: 'DELETE',
    credentials: 'same-origin'
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.success) {
      adToast('"' + userFullName + '" deleted.', 'ok');
      var row = document.getElementById('user-row-' + userId);
      if (row) row.remove();
    } else {
      adToast(data.message || 'Failed to delete user.', 'err');
    }
  })
  .catch(function() {
    adToast('Network error. Please try again.', 'err');
  });
}

function handleDeleteAdmin(btn) {
  var adminId       = btn.dataset.aid;
  var adminUsername = btn.dataset.aname;
  if (!confirm('Remove admin "' + adminUsername + '"? This cannot be undone.')) return;
  fetch('/api/admin/admin/' + adminId, {
    method: 'DELETE',
    credentials: 'same-origin'
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.success) {
      adToast('Admin "' + adminUsername + '" removed.', 'ok');
      var row = document.getElementById('admin-row-' + adminId);
      if (row) row.remove();
    } else {
      adToast(data.message || 'Failed to remove admin.', 'err');
    }
  })
  .catch(function() {
    adToast('Network error. Please try again.', 'err');
  });
}

/* ══════════════════════════════════════════════════════
   Manage Roles & Skills
══════════════════════════════════════════════════════ */

var _allSkills  = [];   // full skills list
var _allRoles   = [];   // current roles page
var _editRoleId = null; // role open in editor

// ── Skills ───────────────────────────────────────────
/* ═══════════════════════════════════════════════════════════
   DATA MANAGER — CSV-based Skills & Roles
   Matches exactly the HTML structure in AdminDashboard.html
═══════════════════════════════════════════════════════════ */

var _dmSkills    = [];    // all skills loaded from CSV
var _dmRoles     = [];    // all roles loaded from CSV
var _addChips    = [];    // chips staged for new-role form
var _editChips   = [];    // chips staged in edit panel
var _editRoleId  = null;  // role currently being edited
var _acTimerAdd  = null;
var _acTimerEdit = null;

/* ── Init ─────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function() {
  dmLoadSkills();
  dmLoadRoles();

  // Close autocomplete dropdowns on outside click
  document.addEventListener('click', function(e) {
    if (!e.target.closest('.dm-ac-wrap')) {
      var a = document.getElementById('dmRoleSkillAcList');
      var b = document.getElementById('dmEditSkillAcList');
      if (a) a.style.display = 'none';
      if (b) b.style.display = 'none';
    }
  });
});

/* ── Tabs ─────────────────────────────────────────────── */
function dmTab(tab) {
  var skillsPanel = document.getElementById('dmSkillsPanel');
  var rolesPanel  = document.getElementById('dmRolesPanel');
  var tabSkills   = document.getElementById('dmTabSkills');
  var tabRoles    = document.getElementById('dmTabRoles');
  if (!skillsPanel || !rolesPanel) return;
  skillsPanel.style.display = tab === 'skills' ? '' : 'none';
  rolesPanel.style.display  = tab === 'roles'  ? '' : 'none';
  tabSkills.classList.toggle('active', tab === 'skills');
  tabRoles.classList.toggle('active',  tab === 'roles');
}

/* ══════════════════════════════════════════════════════
   SKILLS
══════════════════════════════════════════════════════ */
function dmLoadSkills() {
  fetch('/admin/api/dm/skills')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d.success) return;
      _dmSkills = d.skills;
      var badge = document.getElementById('dmSkillCount');
      if (badge) badge.textContent = d.skills.length + ' skills';
      dmRenderSkills(_dmSkills);
    })
    .catch(function(e) { console.error('dmLoadSkills:', e); });
}

function dmRenderSkills(list) {
  var tb = document.getElementById('dmSkillsTbody');
  if (!tb) return;
  if (!list || !list.length) {
    tb.innerHTML = '<tr><td colspan="3" class="dm-loading">No skills found</td></tr>';
    return;
  }
  tb.innerHTML = list.map(function(s) {
    return '<tr>' +
      '<td>' + s.skill_id + '</td>' +
      '<td>' + esc(s.skill_name) + '</td>' +
      '<td>' + esc(s.category) + '</td>' +
    '</tr>';
  }).join('');
}

function dmFilterSkills(q) {
  if (!q || !q.trim()) {
    dmRenderSkills(_dmSkills);
    return;
  }
  var lower = q.toLowerCase();
  dmRenderSkills(_dmSkills.filter(function(s) {
    return s.skill_name.toLowerCase().indexOf(lower) !== -1 ||
           s.category.toLowerCase().indexOf(lower) !== -1;
  }));
}

function dmAddSkill() {
  var nameEl = document.getElementById('dmSkillName');
  var catEl  = document.getElementById('dmSkillCat');
  var name   = nameEl.value.trim();
  var cat    = catEl.value;
  if (!name) { showAlert('dmAddSkillAlert', 'Enter a skill name.', 'err'); return; }
  if (!cat)  { showAlert('dmAddSkillAlert', 'Select a category.', 'err'); return; }

  fetch('/admin/api/dm/skills/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name, category: cat })
  })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d.success) { showAlert('dmAddSkillAlert', d.error, 'err'); return; }
      showAlert('dmAddSkillAlert',
        '✓ <b>' + esc(d.skill.skill_name) + '</b> added — ID: <b style="color:var(--indigo)">' +
        d.skill.skill_id + '</b>  (use this ID when mapping to a role)', 'ok');
      nameEl.value = '';
      catEl.value  = '';
      var searchEl = document.getElementById('dmSkillSearch');
      if (searchEl) searchEl.value = '';
      _dmSkills.push(d.skill);
      _dmSkills.sort(function(a, b) { return a.skill_id - b.skill_id; });
      var badge = document.getElementById('dmSkillCount');
      if (badge) badge.textContent = _dmSkills.length + ' skills';
      dmRenderSkills(_dmSkills);
      dmSetSyncDirty();
    })
    .catch(function(e) { showAlert('dmAddSkillAlert', 'Press the sync to db to complete the process', 'err'); });
}

/* ══════════════════════════════════════════════════════
   ROLES
══════════════════════════════════════════════════════ */
function dmLoadRoles() {
  fetch('/admin/api/dm/roles')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d.success) return;
      _dmRoles = d.roles;
      var badge = document.getElementById('dmRoleCount');
      if (badge) badge.textContent = d.roles.length + ' roles';
      dmRenderRoles(_dmRoles);
    })
    .catch(function(e) { console.error('dmLoadRoles:', e); });
}

function dmRenderRoles(list) {
  var tb = document.getElementById('dmRolesTbody');
  if (!tb) return;
  if (!list || !list.length) {
    tb.innerHTML = '<tr><td colspan="4" class="dm-loading">No roles found</td></tr>';
    return;
  }
  tb.innerHTML = list.map(function(r) {
    return '<tr>' +
      '<td>' + r.role_id + '</td>' +
      '<td>' + esc(r.role_name) + '</td>' +
      '<td>' + esc(r.category) + '</td>' +
      '<td><button class="dm-edit-btn" onclick="dmOpenEdit(' + r.role_id + ',\'' +
        esc(r.role_name).replace(/'/g, "\\'") + '\',\'' +
        esc(r.category).replace(/'/g, "\\'") + '\')">Edit Skills</button></td>' +
    '</tr>';
  }).join('');
}

function dmFilterRoles(q) {
  if (!q || !q.trim()) {
    dmRenderRoles(_dmRoles);
    return;
  }
  var lower = q.toLowerCase();
  dmRenderRoles(_dmRoles.filter(function(r) {
    return r.role_name.toLowerCase().indexOf(lower) !== -1 ||
           r.category.toLowerCase().indexOf(lower) !== -1;
  }));
}

/* ── Show skill section after entering role details ── */
function dmShowAddRole() {
  var name = document.getElementById('dmRoleName').value.trim();
  var cat  = document.getElementById('dmRoleCat').value;
  if (!name) { showAlert('dmAddRoleAlert', 'Enter a role name.', 'err'); return; }
  if (!cat)  { showAlert('dmAddRoleAlert', 'Select a category.', 'err'); return; }
  // clear previous
  document.getElementById('dmAddRoleAlert').className = 'alert';
  document.getElementById('dmAddRoleAlert').textContent = '';
  _addChips = [];
  dmRenderChips('add');
  document.getElementById('dmRoleSkillsSection').style.display = '';
  document.getElementById('dmRoleSkillsSection')
    .scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* ── Save role + skills ── */
function dmSaveRole() {
  var name = document.getElementById('dmRoleName').value.trim();
  var cat  = document.getElementById('dmRoleCat').value;
  if (!_addChips.length) {
    showAlert('dmAddRoleAlert', 'Assign at least one skill before saving.', 'err'); return;
  }

  fetch('/admin/api/dm/roles/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name, category: cat })
  })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d.success) { showAlert('dmAddRoleAlert', d.error, 'err'); return; }
      var roleId  = d.role.role_id;
      var mapping = _addChips.map(function(c) {
        return c.skill_id + ':' + c.importance;
      }).join(', ');
      return fetch('/admin/api/dm/roles/' + roleId + '/map', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mappings: mapping })
      })
        .then(function(r) { return r.json(); })
        .then(function(m) {
          if (!m.success) {
            showAlert('dmAddRoleAlert', 'Role created but mapping failed: ' + m.error, 'err');
            return;
          }
          showAlert('dmAddRoleAlert',
            '✅ <b>' + esc(name) + '</b> (ID: ' + roleId + ') saved with <b>' +
            _addChips.length + '</b> skill(s). Click Sync to activate.', 'ok');
          document.getElementById('dmRoleName').value = '';
          document.getElementById('dmRoleCat').value  = '';
          document.getElementById('dmRoleSkillsSection').style.display = 'none';
          var searchEl = document.getElementById('dmRoleSearch');
          if (searchEl) searchEl.value = '';
          _addChips = [];
          dmRenderChips('add');
          dmSetSyncDirty();
          dmLoadRoles();
        });
    })
    .catch(function() { showAlert('dmAddRoleAlert', 'Network error.', 'err'); });
}

/* ══════════════════════════════════════════════════════
   AUTOCOMPLETE  (shared for add + edit panels)
══════════════════════════════════════════════════════ */
function dmSkillAc(q, mode) {
  var timer  = mode === 'add' ? _acTimerAdd  : _acTimerEdit;
  var listId = mode === 'add' ? 'dmRoleSkillAcList' : 'dmEditSkillAcList';
  var listEl = document.getElementById(listId);
  if (!listEl) return;

  clearTimeout(timer);
  if (!q || !q.trim()) { listEl.style.display = 'none'; return; }

  var t = setTimeout(function() {
    var lower   = q.toLowerCase();
    var matches = _dmSkills.filter(function(s) {
      return s.skill_name.toLowerCase().indexOf(lower) !== -1;
    }).slice(0, 10);

    if (!matches.length) { listEl.style.display = 'none'; return; }

    listEl.innerHTML = matches.map(function(s) {
      return '<div class="dm-ac-item" onmousedown="dmSelectSkill(' +
        s.skill_id + ',\'' + esc(s.skill_name).replace(/'/g, "\\'") + '\',\'' + mode + '\')">' +
        '<span>' + esc(s.skill_name) +
        ' <small style="color:var(--muted)">(' + esc(s.category) + ')</small></span>' +
        '<span class="dm-ac-id">' + s.skill_id + '</span>' +
        '</div>';
    }).join('');
    listEl.style.display = '';
  }, 120);

  if (mode === 'add') _acTimerAdd  = t;
  else                _acTimerEdit = t;
}

function dmSelectSkill(id, name, mode) {
  var inputId = mode === 'add' ? 'dmRoleSkillSearch' : 'dmEditSkillSearch';
  var listId  = mode === 'add' ? 'dmRoleSkillAcList' : 'dmEditSkillAcList';
  var el = document.getElementById(inputId);
  if (el) { el.value = name; el.dataset.skillId = id; }
  var list = document.getElementById(listId);
  if (list) list.style.display = 'none';
}

/* ── Add chip from autocomplete ── */
function dmAddChip(mode) {
  var inputId = mode === 'add' ? 'dmRoleSkillSearch' : 'dmEditSkillSearch';
  var impId   = mode === 'add' ? 'dmRoleSkillImp'    : 'dmEditSkillImp';
  var alertId = mode === 'add' ? 'dmAddRoleAlert'     : 'dmEditAlert';
  var chips   = mode === 'add' ? _addChips : _editChips;
  var inp = document.getElementById(inputId);
  if (!inp) return;

  var sid = parseInt(inp.dataset.skillId || '0');
  var imp = document.getElementById(impId).value;

  if (!sid) { showAlert(alertId, 'Select a skill from the dropdown first.', 'err'); return; }
  if (chips.some(function(c) { return c.skill_id === sid; })) {
    showAlert(alertId, 'That skill is already added.', 'err'); return;
  }
  var skill = _dmSkills.find(function(s) { return s.skill_id === sid; });
  if (!skill) { showAlert(alertId, 'Skill not found.', 'err'); return; }

  chips.push({ skill_id: sid, skill_name: skill.skill_name, importance: imp });
  inp.value = '';
  inp.dataset.skillId = '';
  document.getElementById(alertId).className = 'alert';
  document.getElementById(alertId).textContent = '';
  dmRenderChips(mode);
}

/* ── Parse IDs shortcut ── */
function dmParseIds(mode) {
  var rawEl = document.getElementById('dmRoleSkillIds');
  if (!rawEl) return;
  var raw = rawEl.value.trim();
  if (!raw) { showAlert('dmAddRoleAlert', 'Enter skill IDs first.', 'err'); return; }

  var errors = [];
  var chips  = mode === 'add' ? _addChips : _editChips;

  raw.replace(/\n/g, ',').split(',').forEach(function(t) {
    t = t.trim();
    if (!t) return;
    if (t.indexOf(':') === -1) { errors.push('"' + t + '" — missing colon'); return; }
    var parts = t.split(':');
    var sid   = parseInt(parts[0].trim());
    var imp   = (parts[1] || '').trim().toLowerCase();
    if (isNaN(sid)) { errors.push('"' + parts[0] + '" — not a valid ID'); return; }
    if (['core','secondary','bonus'].indexOf(imp) === -1) {
      errors.push('"' + imp + '" — must be core / secondary / bonus'); return;
    }
    var skill = _dmSkills.find(function(s) { return s.skill_id === sid; });
    if (!skill) { errors.push('ID ' + sid + ' not found'); return; }
    if (chips.some(function(c) { return c.skill_id === sid; })) return; // skip dupe silently
    chips.push({ skill_id: sid, skill_name: skill.skill_name, importance: imp });
  });

  rawEl.value = '';
  if (errors.length) showAlert('dmAddRoleAlert', '⚠ ' + errors.join(' · '), 'err');
  else { document.getElementById('dmAddRoleAlert').className = 'alert'; }
  dmRenderChips(mode);
}

/* ── Remove a chip ── */
function dmRemoveChip(skillId, mode) {
  if (mode === 'add')
    _addChips  = _addChips.filter(function(c) { return c.skill_id !== skillId; });
  else
    _editChips = _editChips.filter(function(c) { return c.skill_id !== skillId; });
  dmRenderChips(mode);
}

/* ── Render chips into the 3-column grid ── */
function dmRenderChips(mode) {
  var chips    = mode === 'add' ? _addChips : _editChips;
  var prefix   = mode === 'add' ? 'dmAdd'  : 'dmEdit';
  var wrapId   = mode === 'add' ? 'dmAddChipsWrap' : null;
  var countId  = mode === 'add' ? 'dmAddChipCount' : null;

  // Show/hide chips wrap for add mode
  if (wrapId) {
    var wrap = document.getElementById(wrapId);
    if (wrap) wrap.style.display = chips.length ? '' : 'none';
  }

  ['core', 'secondary', 'bonus'].forEach(function(imp) {
    var suffix = imp === 'core' ? 'Core' : imp === 'secondary' ? 'Sec' : 'Bonus';
    var colEl  = document.getElementById(prefix + suffix + 'Chips');
    if (!colEl) return;
    var group  = chips.filter(function(c) { return c.importance === imp; });
    if (!group.length) {
      colEl.innerHTML = '<span style="font-size:.74rem;color:var(--muted)">None</span>';
      return;
    }
    colEl.innerHTML = group.map(function(c) {
      return '<div class="dm-chip dm-chip-' + imp + '">' +
        '<span><span class="dm-chip-id">' + c.skill_id + '</span> ' + esc(c.skill_name) + '</span>' +
        '<button class="dm-chip-x" onclick="dmRemoveChip(' + c.skill_id + ',\'' + mode + '\')">✕</button>' +
      '</div>';
    }).join('');
  });

  if (countId) {
    var cEl = document.getElementById(countId);
    if (cEl) cEl.textContent = chips.length ? chips.length + ' skill(s) staged' : '';
  }
}

/* ══════════════════════════════════════════════════════
   EDIT ROLE SKILLS
══════════════════════════════════════════════════════ */
function dmOpenEdit(roleId, roleName, roleCat) {
  _editRoleId = roleId;
  _editChips  = [];

  var nameEl  = document.getElementById('dmEditRoleName');
  var catEl   = document.getElementById('dmEditRoleCat');
  var panel   = document.getElementById('dmEditPanel');
  var alertEl = document.getElementById('dmEditAlert');
  var searchEl = document.getElementById('dmEditSkillSearch');
  var acList   = document.getElementById('dmEditSkillAcList');

  if (nameEl)   nameEl.textContent   = roleName;
  if (catEl)    catEl.textContent    = roleCat;
  if (alertEl)  { alertEl.className = 'alert'; alertEl.textContent = ''; }
  if (searchEl) { searchEl.value = ''; searchEl.dataset.skillId = ''; }
  if (acList)   acList.style.display = 'none';
  if (panel)    panel.style.display  = '';

  dmRenderChips('edit');

  setTimeout(function() {
    if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, 50);

  // Load current skills from CSV
  fetch('/admin/api/dm/roles/' + roleId + '/skills')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d.success) return;
      _editChips = d.skills.map(function(s) {
        return { skill_id: s.skill_id, skill_name: s.skill_name, importance: s.importance };
      });
      dmRenderChips('edit');
    })
    .catch(function(e) { console.error('dmOpenEdit load:', e); });
}

function dmCloseEdit() {
  _editRoleId = null;
  var panel = document.getElementById('dmEditPanel');
  if (panel) panel.style.display = 'none';
}

function dmSaveEdit() {
  if (!_editChips.length) {
    showAlert('dmEditAlert', 'Add at least one skill.', 'err'); return;
  }
  var mapping = _editChips.map(function(c) {
    return c.skill_id + ':' + c.importance;
  }).join(', ');

  fetch('/admin/api/dm/roles/' + _editRoleId + '/map', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mappings: mapping })
  })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d.success) { showAlert('dmEditAlert', d.error, 'err'); return; }
      showAlert('dmEditAlert',
        '✅ ' + d.count + ' skill(s) saved successfully. Click <b>Sync to DB</b> to activate.', 'ok');
      dmSetSyncDirty();
    })
    .catch(function() { showAlert('dmEditAlert', 'Network error.', 'err'); });
}

/* ══════════════════════════════════════════════════════
   SYNC
══════════════════════════════════════════════════════ */
function dmSetSyncDirty() {
  var el = document.getElementById('dmSyncStatus');
  if (el) el.textContent = 'CSV updated — click Sync to apply to the live DB.';
}

function dmSync() {
  var btn = document.getElementById('dmSyncBtn');
  if (btn) { btn.disabled = true; btn.textContent = '⟳ Syncing…'; }
  var alertEl = document.getElementById('dmSyncAlert');
  if (alertEl) { alertEl.className = 'alert'; alertEl.textContent = ''; }

  fetch('/admin/api/dm/sync', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (btn) { btn.disabled = false; btn.textContent = '⟳ Sync to DB'; }
      if (!d.success) { showAlert('dmSyncAlert', d.error, 'err'); return; }
      showAlert('dmSyncAlert', '✅ ' + d.message, 'ok');
      var statusEl = document.getElementById('dmSyncStatus');
      if (statusEl) statusEl.textContent = 'DB is up to date with CSV.';
    })
    .catch(function() {
      if (btn) { btn.disabled = false; btn.textContent = '⟳ Sync to DB'; }
      showAlert('dmSyncAlert', 'Network error — please try again.', 'err');
    });
}