/* =====================================================
   dashboard.js — Smart Resume Analyzer
   =====================================================
   1. State
   2. Step navigation
   3. Autocomplete
   4. File upload
   5. Analyse  (POST /api/analyse)
   6. Render results
   7. History  (GET /api/history + /api/result/<id>)
   8. Helpers
   ===================================================== */

'use strict';

/* ── 1. State ─────────────────────────────────────────── */

var _file      = null;   // selected File object
var _roleId    = null;   // selected role id (int)
var _roleName  = '';     // selected role name (string)
var _acResults = [];     // autocomplete items
var _acIndex   = -1;     // keyboard cursor
var _acTimer   = null;   // debounce


/* ── 2. Step navigation ───────────────────────────────── */

function goToStep(n) {
  document.querySelectorAll('.db-step').forEach(function (el) {
    var s = parseInt(el.getAttribute('data-step'), 10);
    el.classList.remove('active', 'done');
    if (s === n) el.classList.add('active');
    if (s < n)   el.classList.add('done');
  });
  document.querySelectorAll('.db-panel').forEach(function (el) {
    el.classList.remove('active');
  });
  var p = document.getElementById('panel' + n);
  if (p) p.classList.add('active');
  hideAlert('dbAlert');
}

function handleNextStep1() {
  var rid = document.getElementById('roleId').value;
  if (!rid || !_roleName) {
    document.getElementById('jobRole').classList.add('invalid');
    showAlert('dbAlert', '⚠ Please select a role from the dropdown list.', 'err');
    document.getElementById('jobRole').focus();
    return;
  }
  document.getElementById('jobRole').classList.remove('invalid');
  closeAc();
  var cr = document.getElementById('chosenRole');
  if (cr) cr.textContent = '"' + _roleName + '"';
  goToStep(2);
}


/* ── 3. Autocomplete ──────────────────────────────────── */

function initAutocomplete() {
  var input = document.getElementById('jobRole');
  var list  = document.getElementById('acList');
  if (!input || !list) return;

  input.addEventListener('input', function () {
    input.classList.remove('invalid');
    hideAlert('dbAlert');
    _roleId   = null;
    _roleName = '';
    document.getElementById('roleId').value = '';
    clearTimeout(_acTimer);
    var q = input.value.trim();
    if (q.length < 1) { closeAc(); return; }
    _acTimer = setTimeout(function () { fetchAc(q); }, 180);
  });

  input.addEventListener('keydown', function (e) {
    if (!list.classList.contains('open')) {
      if (e.key === 'Enter') handleNextStep1();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _acIndex = Math.min(_acIndex + 1, _acResults.length - 1);
      highlightAc();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _acIndex = Math.max(_acIndex - 1, 0);
      highlightAc();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (_acIndex >= 0 && _acResults[_acIndex]) selectAcItem(_acResults[_acIndex]);
      else handleNextStep1();
    } else if (e.key === 'Escape') {
      closeAc();
    }
  });

  document.addEventListener('click', function (e) {
    var wrap = document.getElementById('acWrap');
    if (wrap && !wrap.contains(e.target)) closeAc();
  });
}

function fetchAc(q) {
  fetch('/api/roles?q=' + encodeURIComponent(q))
    .then(function (r) { return r.json(); })
    .then(function (data) {
      _acResults = data || [];
      _acIndex   = -1;
      renderAcList();
    })
    .catch(function () { closeAc(); });
}

function renderAcList() {
  var list = document.getElementById('acList');
  if (!_acResults.length) { closeAc(); return; }
  list.innerHTML = '';
  _acResults.forEach(function (item, i) {
    var li = document.createElement('li');
    li.className   = 'ac-item';
    li.dataset.idx = i;
    li.setAttribute('role', 'option');
    li.innerHTML =
      '<span class="ac-name">' + esc(item.name) + '</span>' +
      '<span class="ac-cat">'  + esc(item.category || '') + '</span>';
    li.addEventListener('mousedown', function (e) {
      e.preventDefault();
      selectAcItem(item);
    });
    list.appendChild(li);
  });
  list.classList.add('open');
}

function highlightAc() {
  document.querySelectorAll('#acList .ac-item').forEach(function (el, i) {
    el.classList.toggle('active', i === _acIndex);
  });
}

function selectAcItem(item) {
  _roleId   = item.id;
  _roleName = item.name;
  document.getElementById('jobRole').value  = item.name;
  document.getElementById('roleId').value   = item.id;
  closeAc();
}

function closeAc() {
  var list = document.getElementById('acList');
  if (list) { list.classList.remove('open'); list.innerHTML = ''; }
  _acResults = [];
  _acIndex   = -1;
}


/* ── 4. File upload ───────────────────────────────────── */

function initUpload() {
  var dropzone  = document.getElementById('dropzone');
  var fileInput = document.getElementById('resumeFile');
  if (!dropzone || !fileInput) return;

  dropzone.addEventListener('dragover', function (e) {
    e.preventDefault();
    dropzone.classList.add('drag-over');
  });
  dropzone.addEventListener('dragleave', function () {
    dropzone.classList.remove('drag-over');
  });
  dropzone.addEventListener('drop', function (e) {
    e.preventDefault();
    dropzone.classList.remove('drag-over');
    if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener('change', function () {
    if (this.files.length) handleFile(this.files[0]);
  });
  document.getElementById('removeFile').addEventListener('click', clearFile);
}

function handleFile(file) {
  if (file.type !== 'application/pdf') {
    showAlert('dbAlert', '⚠ Please upload a PDF file only.', 'err');
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    showAlert('dbAlert', '⚠ File must be under 5 MB.', 'err');
    return;
  }
  _file = file;
  hideAlert('dbAlert');
  document.getElementById('fileName').textContent = file.name;
  document.getElementById('fileChosen').classList.add('show');
  document.getElementById('analyseBtn').disabled = false;
}

function clearFile() {
  _file = null;
  document.getElementById('resumeFile').value = '';
  document.getElementById('fileChosen').classList.remove('show');
  document.getElementById('analyseBtn').disabled = true;
}


/* ── 5. Analyse ───────────────────────────────────────── */

async function handleAnalyse() {
  if (!_file)   { showAlert('dbAlert', '⚠ Please upload your resume first.', 'err'); return; }
  if (!_roleId) { showAlert('dbAlert', '⚠ Please go back and select a role.', 'err'); return; }

  var btn = document.getElementById('analyseBtn');
  btn.disabled    = true;
  btn.textContent = 'Analysing…';
  hideAlert('dbAlert');

  document.getElementById('uploadCard').style.display  = 'none';
  document.getElementById('resultsCard').style.display = 'none';
  document.getElementById('loadWrap').classList.add('show');

  try {
    var fd = new FormData();
    fd.append('resume',  _file);
    fd.append('role_id', _roleId);

    var res  = await fetch('/api/analyse', { method: 'POST', body: fd });
    var data = await res.json();

    document.getElementById('loadWrap').classList.remove('show');

    if (res.ok && data.success) {
      renderResults(data);
      loadHistory();
    } else {
      document.getElementById('uploadCard').style.display = '';
      btn.disabled    = false;
      btn.textContent = 'Analyse Resume';
      showAlert('dbAlert', '⚠ ' + (data.message || 'Analysis failed. Please try again.'), 'err');
    }
  } catch (e) {
    document.getElementById('loadWrap').classList.remove('show');
    document.getElementById('uploadCard').style.display = '';
    btn.disabled    = false;
    btn.textContent = 'Analyse Resume';
    showAlert('dbAlert', '⚠ Network error. Please try again.', 'err');
  }
}


/* ── 6. Render results ────────────────────────────────── */

function renderResults(data) {
  var card  = document.getElementById('resultsCard');
  var score = data.readiness_score || 0;

  card.style.display = '';

  // Header
  document.getElementById('resTitle').textContent =
    Math.round(score) + '% Readiness — ' + esc(data.selected_role || _roleName || '');
  document.getElementById('resSubtitle').textContent =
    data.resume_filename || (_file ? _file.name : '');

  // Dial
  var dial   = document.getElementById('resDial');
  var offset = 314 - (score / 100) * 314;
  dial.style.stroke          = scoreColor(score);
  dial.style.strokeDashoffset = offset;

  document.getElementById('resScore').textContent      = Math.round(score) + '%';
  document.getElementById('resScore').style.color      = scoreColor(score);
  document.getElementById('resScoreLabel').textContent = scoreLabel(score);

  // Bars (tiny delay so CSS transition fires)
  setTimeout(function () {
    setBar('barCore',  'cntCore',  data.core_matched,      data.core_total);
    setBar('barSec',   'cntSec',   data.secondary_matched, data.secondary_total);
    setBar('barBonus', 'cntBonus', data.bonus_matched,     data.bonus_total);
  }, 80);

  // AI prediction note
  var predBox  = document.getElementById('resPred');
  var predText = document.getElementById('resPredText');
  var sel  = (data.selected_role  || '').toLowerCase().trim();
  var pred = (data.predicted_role || '').toLowerCase().trim();
  if (data.predicted_role && pred && pred !== sel) {
    predText.innerHTML =
      '<b>AI Prediction:</b> Based on your skills, the model also sees a strong match with ' +
      '<b>' + esc(data.predicted_role) + '</b>. Worth exploring!';
    predBox.style.display = '';
  } else {
    predBox.style.display = 'none';
  }

  // Tab badges
  document.getElementById('badgeMatched').textContent = (data.matched_skills || []).length;
  document.getElementById('badgeMissing').textContent = (data.missing_skills || []).length;

  // Scoring breakdown panel
  renderScoringBreakdown(data.scoring_breakdown || null, data);

  // Skills + recs
  renderSkillGroups('matchedSkills', data.matched_skills || [], true);
  renderSkillGroups('missingSkills', data.missing_skills || [], false);
  renderRecs(data.recommendations || []);

  // Report link
  var btn = document.getElementById('resReportBtn');
  if (data.analysis_id) {
    btn.href = '/report/' + data.analysis_id;
    btn.style.display = '';
  } else {
    btn.style.display = 'none';
  }

  switchTab('matched');
  card.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function setBar(fillId, cntId, matched, total) {
  var pct = total > 0 ? (matched / total) * 100 : 0;
  var el  = document.getElementById(fillId);
  if (el) el.style.width = Math.max(0, Math.min(100, pct)) + '%';
  var cnt = document.getElementById(cntId);
  if (cnt) cnt.textContent = matched + '/' + total;
}

function renderSkillGroups(containerId, skills, isMatched) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = '';

  if (!skills.length) {
    container.innerHTML =
      '<div class="res-empty">' +
      (isMatched
        ? 'No matching skills found. Check that your resume spells skill names clearly.'
        : '🎉 You have all required skills for this role — nothing missing!') +
      '</div>';
    return;
  }

  var groups = isMatched
    ? [
        { key:'core',      label:'Core',                   cls:'res-sg-core',  pill:'pill-core'       },
        { key:'secondary', label:'Secondary',              cls:'res-sg-sec',   pill:'pill-sec'        },
        { key:'bonus',     label:'Bonus',                  cls:'res-sg-bonus', pill:'pill-bonus'      },
      ]
    : [
        { key:'core',      label:'Core — High Priority',   cls:'res-sg-err',   pill:'pill-miss-core'  },
        { key:'secondary', label:'Secondary',              cls:'res-sg-warn',  pill:'pill-miss-sec'   },
        { key:'bonus',     label:'Bonus',                  cls:'res-sg-muted', pill:'pill-miss-muted' },
      ];

  groups.forEach(function (g) {
    var items = skills.filter(function (s) { return s.importance === g.key; });
    if (!items.length) return;

    var div   = document.createElement('div');
    div.className = 'res-skill-group';

    var lbl = document.createElement('span');
    lbl.className   = 'res-sg-label ' + g.cls;
    lbl.textContent = g.label;
    div.appendChild(lbl);

    var pills = document.createElement('div');
    pills.className = 'res-pills';
    items.forEach(function (sk) {
      var pill = document.createElement('span');
      pill.className   = 'res-pill ' + g.pill;
      pill.textContent = sk.name;
      pills.appendChild(pill);
    });
    div.appendChild(pills);
    container.appendChild(div);
  });
}

function renderRecs(recs) {
  var list = document.getElementById('recsList');
  if (!list) return;
  list.innerHTML = '';

  if (!recs.length) {
    list.innerHTML = '<div class="res-empty">No recommendations available.</div>';
    return;
  }

  recs.forEach(function (r) {
    var sc  = r.score != null ? r.score : (r.match_score || 0);
    var cls = sc >= 70 ? 'rec-strong' : sc >= 40 ? 'rec-mid' : 'rec-low';
    var row = document.createElement('div');
    row.className = 'res-rec-item ' + cls;
    row.innerHTML =
      '<div class="rec-rank">#' + r.rank + '</div>' +
      '<div class="rec-info">' +
        '<div class="rec-name">' + esc(r.role_name) + '</div>' +
        '<div class="rec-label">' + scoreLabel(sc) + '</div>' +
      '</div>' +
      '<div class="rec-score">' + Math.round(sc) + '%</div>';
    list.appendChild(row);
  });
}

function renderScoringBreakdown(sb, data) {
  var el = document.getElementById('scoringBreakdown');
  if (!el) return;

  // Fallback values if scoring_breakdown missing
  var core_total = data.core_total || 0;
  var core_match = data.core_matched || 0;
  var sec_total  = data.secondary_total || 0;
  var sec_match  = data.secondary_matched || 0;
  var bon_total  = data.bonus_total || 0;
  var bon_match  = data.bonus_matched || 0;

  var skill_score = sb ? sb.skill_gap_score  : 0;
  var nb_score    = sb ? sb.nb_score         : 0;
  var rule_score  = sb ? sb.rule_score       : 0;
  var w_skill     = sb ? sb.weight_skill     : 60;
  var w_nb        = sb ? sb.weight_nb        : 20;
  var w_rule      = sb ? sb.weight_rule      : 20;
  var c_skill     = sb ? sb.skill_contribution : 0;
  var c_nb        = sb ? sb.nb_contribution    : 0;
  var c_rule      = sb ? sb.rule_contribution  : 0;
  var category    = sb ? (sb.role_category || '') : '';

  var core_pct = core_total > 0 ? Math.round(core_match / core_total * 100) : 0;
  var sec_pct  = sec_total  > 0 ? Math.round(sec_match  / sec_total  * 100) : 0;
  var bon_pct  = bon_total  > 0 ? Math.round(bon_match  / bon_total  * 100) : 0;

  function bar(pct, colour) {
    return '<div class="sb-bar-wrap"><div class="sb-bar" style="width:' +
      Math.min(100, pct) + '%;background:' + colour + '"></div>' +
      '<span class="sb-bar-pct">' + Math.round(pct) + '%</span></div>';
  }

  // Colour tiers
  var C_CORE  = '#3730A3'; // indigo
  var C_SEC   = '#7C3AED'; // violet
  var C_BON   = '#A78BFA'; // light violet
  var C_NB    = '#F4622A'; // coral
  var C_RULE  = '#059669'; // green

  el.innerHTML =
    '<div class="sb-title">How your Readiness Score was calculated</div>' +

    // ── STEP 1: Skill Gap ──────────────────────────────────────────────
    '<div class="sb-step">' +
      '<div class="sb-step-head">' +
        '<span class="sb-step-num">Step 1</span>' +
        '<span class="sb-step-label">Skill Gap Analysis</span>' +
        '<span class="sb-step-weight">' + w_skill + '% of final score</span>' +
        '<span class="sb-step-val">' + Math.round(skill_score) + '<small>/100</small></span>' +
      '</div>' +
      '<p class="sb-desc">Your resume was scanned for ' + (core_total + sec_total + bon_total) +
        ' skills required for <b>' + esc(data.selected_role || '') + '</b>. ' +
        'Skills are weighted by importance: Core carries the most weight, then Secondary, then Bonus.</p>' +

      '<div class="sb-tier">' +
        '<div class="sb-tier-row">' +
          '<span class="sb-tier-name">Core Skills <small>(weight 70%)</small></span>' +
          '<span class="sb-tier-count">' + core_match + ' / ' + core_total + ' matched</span>' +
        '</div>' + bar(core_pct, C_CORE) +
      '</div>' +

      '<div class="sb-tier">' +
        '<div class="sb-tier-row">' +
          '<span class="sb-tier-name">Secondary Skills <small>(weight 25%)</small></span>' +
          '<span class="sb-tier-count">' + sec_match + ' / ' + sec_total + ' matched</span>' +
        '</div>' + bar(sec_pct, C_SEC) +
      '</div>' +

      '<div class="sb-tier">' +
        '<div class="sb-tier-row">' +
          '<span class="sb-tier-name">Bonus Skills <small>(weight 5%)</small></span>' +
          '<span class="sb-tier-count">' + bon_match + ' / ' + bon_total + ' matched</span>' +
        '</div>' + bar(bon_pct, C_BON) +
      '</div>' +

      '<div class="sb-formula">' +
        'Skill Gap Score = (Core% × 0.7) + (Secondary% × 0.25) + (Bonus% × 0.05) = ' +
        '<b>' + Math.round(skill_score) + '</b>' +
      '</div>' +
    '</div>' +

    // ── STEP 2: NB Model ──────────────────────────────────────────────
    '<div class="sb-step">' +
      '<div class="sb-step-head">' +
        '<span class="sb-step-num">Step 2</span>' +
        '<span class="sb-step-label">Machine Learning Model</span>' +
        '<span class="sb-step-weight">' + w_nb + '% of final score</span>' +
        '<span class="sb-step-val">' + Math.round(nb_score) + '<small>/100</small></span>' +
      '</div>' +
      '<p class="sb-desc">A Naive Bayes classifier was trained on skill patterns across all ' +
        '683 roles. It reads your full resume and predicts which role it most resembles. ' +
        'The probability assigned to <b>' + esc(data.selected_role || '') + '</b> is scaled ' +
        'relative to the model\'s top prediction — so the best match always scores 100.</p>' +
      bar(nb_score, C_NB) +
      (category ? '<div class="sb-note">Role category: <b>' + esc(category) + '</b> — ' +
        'NB weight is lower for soft-skill roles like Teaching and Healthcare because the ' +
        'model was trained on text patterns that are stronger in technical resumes.</div>' : '') +
    '</div>' +

    // ── STEP 3: Rule Engine ───────────────────────────────────────────
    '<div class="sb-step">' +
      '<div class="sb-step-head">' +
        '<span class="sb-step-num">Step 3</span>' +
        '<span class="sb-step-label">Rule-Based Engine</span>' +
        '<span class="sb-step-weight">' + w_rule + '% of final score</span>' +
        '<span class="sb-step-val">' + Math.round(rule_score) + '<small>/100</small></span>' +
      '</div>' +
      '<p class="sb-desc">28 hand-crafted rules check for combinations of keywords that ' +
        'strongly signal a specific role. Rules have three layers: <b>Must</b> (all required), ' +
        '<b>Any-of groups</b> (at least one per group), and <b>Boosts</b> (optional extras ' +
        'that raise confidence). This corrects cases where the NB model is uncertain.</p>' +
      bar(rule_score, C_RULE) +
    '</div>' +

    // ── STEP 4: Final Blend ──────────────────────────────────────────
    '<div class="sb-step sb-step-final">' +
      '<div class="sb-step-head">' +
        '<span class="sb-step-num">Final</span>' +
        '<span class="sb-step-label">Weighted Blend</span>' +
        '<span class="sb-step-weight">Your Readiness Score</span>' +
        '<span class="sb-step-val" style="color:' + scoreColor(data.readiness_score || 0) + '">' +
          Math.round(data.readiness_score || 0) + '<small>%</small></span>' +
      '</div>' +
      '<div class="sb-formula sb-formula-final">' +
        'Score = ' +
        '(Skill Gap <b>' + Math.round(skill_score) + '</b> × ' + w_skill + '%) + ' +
        '(NB Model <b>' + Math.round(nb_score) + '</b> × ' + w_nb + '%) + ' +
        '(Rules <b>' + Math.round(rule_score) + '</b> × ' + w_rule + '%) = ' +
        '<b style="color:' + scoreColor(data.readiness_score || 0) + '">' +
          Math.round(data.readiness_score || 0) + '%</b>' +
      '</div>' +
      '<div class="sb-contrib-row">' +
        '<div class="sb-contrib" style="background:#EEF2FF">' +
          '<div class="sb-contrib-val" style="color:#3730A3">' + Math.round(c_skill) + '</div>' +
          '<div class="sb-contrib-label">from Skills</div>' +
        '</div>' +
        '<div class="sb-contrib" style="background:#FFF1EC">' +
          '<div class="sb-contrib-val" style="color:#F4622A">' + Math.round(c_nb) + '</div>' +
          '<div class="sb-contrib-label">from NB Model</div>' +
        '</div>' +
        '<div class="sb-contrib" style="background:#ECFDF5">' +
          '<div class="sb-contrib-val" style="color:#059669">' + Math.round(c_rule) + '</div>' +
          '<div class="sb-contrib-label">from Rules</div>' +
        '</div>' +
      '</div>' +
      '<div class="sb-band">' +
        'Score Band: ' +
        (data.readiness_score >= 70
          ? '<span style="color:#059669;font-weight:700">✓ Strong Match — you have the key skills for this role</span>'
          : data.readiness_score >= 40
          ? '<span style="color:#D97706;font-weight:700">⚡ Moderate Match — strengthen the missing core skills</span>'
          : '<span style="color:#DC2626;font-weight:700">✗ Needs Work — significant skill gaps remain</span>') +
      '</div>' +
    '</div>';
}

function switchTab(name) {
  document.querySelectorAll('.res-tab').forEach(function (btn) {
    btn.classList.toggle('active', btn.dataset.tab === name);
  });
  document.querySelectorAll('.res-tab-panel').forEach(function (panel) {
    panel.classList.toggle('active', panel.id === 'tab-' + name);
  });
}

function startNew() {
  _file     = null;
  _roleId   = null;
  _roleName = '';
  document.getElementById('roleId').value  = '';
  document.getElementById('jobRole').value = '';
  clearFile();
  goToStep(1);
  document.getElementById('resultsCard').style.display = 'none';
  document.getElementById('uploadCard').style.display  = '';
  document.getElementById('uploadCard').scrollIntoView({ behavior: 'smooth' });
}


/* ── 7. History ───────────────────────────────────────── */

async function loadHistory() {
  var list = document.getElementById('histList');
  if (!list) return;
  list.innerHTML = '<div class="hist-loading">Loading…</div>';

  try {
    var res  = await fetch('/api/history');
    var data = await res.json();

    if (!data.success || !data.analyses || !data.analyses.length) {
      list.innerHTML =
        '<div class="hist-empty">No analyses yet — upload your first resume above!</div>';
      return;
    }

    list.innerHTML = '';
    data.analyses.forEach(function (a) {
      var sc  = a.readiness_score || 0;
      var cls = sc >= 70 ? 'hist-strong' : sc >= 40 ? 'hist-mid' : 'hist-low';
      var dt  = a.created_at ? fmtDate(a.created_at) : '';

      var row = document.createElement('div');
      row.className = 'hist-row';
      row.title     = 'Click to view this analysis';
      row.innerHTML =
        '<div class="hist-score-pill ' + cls + '">' + Math.round(sc) + '%</div>' +
        '<div class="hist-info">' +
          '<div class="hist-role">'  + esc(a.role_name || '')       + '</div>' +
          '<div class="hist-meta">' +
            '<span>' + dt + '</span>' +
            (dt ? '<span>·</span>' : '') +
            '<span class="hist-file">' + esc(a.resume_filename || '') + '</span>' +
          '</div>' +
        '</div>' +
        (a.report_path
          ? '<a class="hist-dl-btn" href="/report/' + a.analysis_id +
            '" target="_blank" title="Download PDF report"' +
            ' onclick="event.stopPropagation()">⬇</a>'
          : '<div class="hist-dl-none"></div>');

      row.addEventListener('click', function () { loadPastResult(a.analysis_id); });
      list.appendChild(row);
    });

  } catch (e) {
    list.innerHTML = '<div class="hist-empty">Could not load history.</div>';
  }
}

async function loadPastResult(analysisId) {
  document.getElementById('uploadCard').style.display  = 'none';
  document.getElementById('resultsCard').style.display = 'none';
  document.getElementById('loadWrap').classList.add('show');

  try {
    var res  = await fetch('/api/result/' + analysisId);
    var data = await res.json();
    document.getElementById('loadWrap').classList.remove('show');

    if (data.success) {
      // Compute totals from matched + missing
      var imp = function (arr, k) {
        return (arr || []).filter(function (s) { return s.importance === k; }).length;
      };
      renderResults({
        analysis_id       : data.analysis_id,
        readiness_score   : data.readiness_score,
        selected_role     : data.selected_role,
        predicted_role    : data.predicted_role,
        resume_filename   : data.resume_filename,
        core_matched      : imp(data.matched_skills, 'core'),
        core_total        : imp(data.matched_skills, 'core')      + imp(data.missing_skills, 'core'),
        secondary_matched : imp(data.matched_skills, 'secondary'),
        secondary_total   : imp(data.matched_skills, 'secondary') + imp(data.missing_skills, 'secondary'),
        bonus_matched     : imp(data.matched_skills, 'bonus'),
        bonus_total       : imp(data.matched_skills, 'bonus')     + imp(data.missing_skills, 'bonus'),
        matched_skills    : data.matched_skills,
        missing_skills    : data.missing_skills,
        recommendations   : data.recommendations,
        scoring_breakdown : data.scoring_breakdown || null,
      });
    } else {
      document.getElementById('uploadCard').style.display = '';
      showAlert('dbAlert', '⚠ Could not load that analysis.', 'err');
    }
  } catch (e) {
    document.getElementById('loadWrap').classList.remove('show');
    document.getElementById('uploadCard').style.display = '';
    showAlert('dbAlert', '⚠ Network error. Please try again.', 'err');
  }
}


/* ── 8. Helpers ───────────────────────────────────────── */

function scoreColor(s) {
  return s >= 70 ? '#059669' : s >= 40 ? '#D97706' : '#DC2626';
}

function scoreLabel(s) {
  return s >= 70 ? 'Strong Match' : s >= 40 ? 'Moderate Match' : 'Needs Work';
}

function esc(str) {
  return String(str || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function fmtDate(iso) {
  try {
    return new Date(iso.replace(' ', 'T') + 'Z')
      .toLocaleDateString('en-GB', { day:'numeric', month:'short', year:'numeric' });
  } catch (e) { return iso; }
}


/* ── Init ─────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', function () {
  initAutocomplete();
  initUpload();
  loadHistory();
});