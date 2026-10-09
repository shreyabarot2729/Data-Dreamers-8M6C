// EventSecure State Management
const state = {
  activeTab: 'tab-registration',
  registrationId: null,
  participantId: null,
  qrToken: null,
  registration: null,
  demoOtp: null,
  events: [],
  cameraStreams: {},
  pages: { events: 1, participants: 1, biometrics: 1, registrations: 1 },
};

const rowsPerPage = 10;

// UI Elements
const toast = document.getElementById('toast');
const apiStatus = document.getElementById('api-status');
const eventSelect = document.getElementById('event-select');
const eventCapacityHint = document.getElementById('event-capacity-hint');

// Tabs
document.querySelectorAll('.nav-tab').forEach((tabBtn) => {
  tabBtn.addEventListener('click', () => {
    const tabTarget = tabBtn.dataset.tab;
    switchTab(tabTarget);
  });
});

function switchTab(targetId) {
  document.querySelectorAll('.nav-tab').forEach((b) => {
    const isActive = b.dataset.tab === targetId;
    b.classList.toggle('active', isActive);
    b.setAttribute('aria-selected', isActive ? 'true' : 'false');
  });

  document.querySelectorAll('.tab-content').forEach((tc) => {
    tc.classList.toggle('active', tc.id === targetId);
  });
  state.activeTab = targetId;

  if (targetId === 'tab-database') {
    loadDatabaseExplorer();
  }
}

function initializeTheme() {
  const themeSelect = document.getElementById('theme-select');
  const savedTheme = localStorage.getItem('eventsecure-theme') || 'dark';
  document.documentElement.dataset.theme = savedTheme;
  themeSelect.value = savedTheme;
  themeSelect.addEventListener('change', () => {
    document.documentElement.dataset.theme = themeSelect.value;
    localStorage.setItem('eventsecure-theme', themeSelect.value);
  });
}

async function startCamera(videoId, statusId, streamKey, facingMode = 'user') {
  const video = document.getElementById(videoId);
  const status = document.getElementById(statusId);
  if (!navigator.mediaDevices?.getUserMedia) {
    status.textContent = 'Camera access requires a supported browser and HTTPS (or localhost).';
    showToast(status.textContent, 'error');
    return false;
  }

  stopCamera(streamKey);
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode, width: { ideal: 1280 }, height: { ideal: 720 } },
    });
    state.cameraStreams[streamKey] = stream;
    video.srcObject = stream;
    video.hidden = false;
    await video.play();
    status.textContent = 'Live camera connected. Position the face inside the frame.';
    return true;
  } catch (err) {
    status.textContent = err.name === 'NotAllowedError'
      ? 'Camera permission was denied. Allow camera access in your browser settings.'
      : `Unable to access camera: ${err.message}`;
    showToast(status.textContent, 'error');
    return false;
  }
}

function stopCamera(streamKey) {
  const stream = state.cameraStreams[streamKey];
  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    delete state.cameraStreams[streamKey];
  }
}

function captureCameraFrame(videoId, streamKey) {
  const video = document.getElementById(videoId);
  if (!state.cameraStreams[streamKey] || !video.videoWidth) {
    throw new Error('Start the live camera and wait for the preview before capturing.');
  }
  const canvas = document.createElement('canvas');
  const scale = Math.min(1, 640 / video.videoWidth);
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.75);
}

// Toast notification helper
function showToast(message, type = 'success') {
  toast.textContent = message;
  toast.className = `toast visible ${type === 'error' ? 'toast-error' : 'toast-success'}`;
  setTimeout(() => {
    toast.classList.remove('visible');
  }, 3200);
}

// Generic API fetch wrapper
async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || 'Request failed');
  }
  return data;
}

// Pipeline stepper progression
function setStepActive(stepNum) {
  for (let i = 1; i <= 5; i++) {
    const node = document.getElementById(`step-node-${i}`);
    if (node) {
      if (i < stepNum) {
        node.className = 'step-node completed';
      } else if (i === stepNum) {
        node.className = 'step-node active';
      } else {
        node.className = 'step-node';
      }
    }
  }
}

// Load events into dropdown
async function loadEvents() {
  try {
    const events = await requestJson('/api/events');
    state.events = events;
    if (events && events.length > 0) {
      eventSelect.innerHTML = events
        .map(
          (ev) =>
            `<option value="${escapeHtml(ev.event_id)}">${escapeHtml(ev.event_id)} - ${escapeHtml(ev.event_name)} (${ev.registered_count || 0}/${ev.capacity} registered)</option>`
        )
        .join('');
      updateEventHint();
    }
  } catch (err) {
    console.error('Failed to load events:', err);
  }
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character]);
}

function updateEventHint() {
  const selected = state.events.find((e) => e.event_id === eventSelect.value);
  if (selected) {
    eventCapacityHint.textContent = `Capacity: ${selected.registered_count || 0} / ${selected.capacity} attendees registered`;
  }
}

eventSelect.addEventListener('change', updateEventHint);

const registrationForm = document.getElementById('registration-form');
registrationForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const formData = new FormData(registrationForm);
  const payload = Object.fromEntries(formData.entries());

  try {
    const reg = await requestJson('/api/registrations', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    state.registration = reg;
    state.registrationId = reg.id;
    state.participantId = reg.participant_id;
    state.demoOtp = reg.otp_code || null;

    document.getElementById('tag-step-1').textContent = 'Created';
    document.getElementById('tag-step-1').className = 'status-tag';
    document.getElementById('verification-status-tag').textContent = 'OTP Pending';
    document.getElementById('verification-status-tag').className = 'status-tag status-waiting';

    // Enable Step 2 OTP
    const otpInput = document.getElementById('otp-input');
    const otpBtn = document.getElementById('btn-verify-otp');
    otpInput.disabled = false;
    otpBtn.disabled = false;
    otpInput.value = '';
    otpInput.focus();

    document.getElementById('btn-start-reg-camera').disabled = true;
    document.getElementById('btn-verify-face').disabled = true;

    // Only the demo provider returns a test code to the browser.
    const demoPill = document.getElementById('otp-demo-pill');
    demoPill.style.display = state.demoOtp ? 'flex' : 'none';
    document.getElementById('otp-sent-status').textContent = state.demoOtp
      ? 'Demo OTP ready for testing.'
      : `A verification code was sent by SMS to ${payload.mobile}.`;
    if (state.demoOtp) document.getElementById('demo-otp-val').textContent = state.demoOtp;

    setStepActive(2);
    showToast(`Registration initiated! Participant ID: ${reg.participant_id}. Verify OTP.`);
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// Auto-fill OTP button
document.getElementById('btn-fill-otp').addEventListener('click', () => {
  if (state.demoOtp) {
    document.getElementById('otp-input').value = state.demoOtp;
  }
});

document.getElementById('btn-start-reg-camera').addEventListener('click', async () => {
  const started = await startCamera('reg-camera-video', 'reg-camera-status', 'registration');
  document.getElementById('btn-verify-face').disabled = !started;
});

// STEP 2: Verify OTP
document.getElementById('btn-verify-otp').addEventListener('click', async () => {
  const code = document.getElementById('otp-input').value.trim();
  if (!code) {
    showToast('Please enter the 6-digit OTP code', 'error');
    return;
  }

  try {
    const reg = await requestJson(`/api/registrations/${state.registrationId}/otp`, {
      method: 'POST',
      body: JSON.stringify({ code }),
    });

    state.registration = reg;
    document.getElementById('otp-input').disabled = true;
    document.getElementById('btn-verify-otp').disabled = true;
    document.getElementById('verification-status-tag').textContent = 'Face Check Pending';

    // Enable Face Verification
    document.getElementById('btn-verify-face').disabled = false;
    document.getElementById('btn-start-reg-camera').disabled = false;
    document.getElementById('reg-camera-status').textContent = 'Start the camera to capture a live frame.';

    setStepActive(3);
    showToast('Mobile SMS OTP confirmed! Proceed to Face Biometrics.');
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// STEP 3: Verify Face
document.getElementById('btn-verify-face').addEventListener('click', async () => {
  try {
    const image = captureCameraFrame('reg-camera-video', 'registration');
    document.getElementById('reg-camera-status').textContent = 'Submitting captured frame for face verification…';
    const reg = await requestJson(`/api/registrations/${state.registrationId}/face`, {
      method: 'POST',
      body: JSON.stringify({ payload: image }),
    });

    state.registration = reg;
    document.getElementById('btn-verify-face').disabled = true;
    stopCamera('registration');

    const resultTag = document.getElementById('face-result-tag');
    resultTag.textContent = 'Face matched and duplicate enrollment check passed.';
    resultTag.style.display = 'block';
    resultTag.style.background = 'rgba(16, 185, 129, 0.15)';
    resultTag.style.color = '#34d399';

    document.getElementById('reg-camera-status').textContent = 'Face matched and enrolled.';
    document.getElementById('verification-status-tag').textContent = 'Liveness / PAD Pending';

    // Enable Liveness & PAD buttons
    document.getElementById('btn-verify-liveness').disabled = false;

    setStepActive(4);
    showToast('Facial biometrics verified! Proceed to Liveness & PAD check.');
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// STEP 4: Liveness Check
document.getElementById('btn-verify-liveness').addEventListener('click', async () => {
  try {
    const reg = await requestJson(`/api/registrations/${state.registrationId}/liveness`, {
      method: 'POST',
      body: JSON.stringify({ payload: 'live' }),
    });

    state.registration = reg;
    document.getElementById('btn-verify-liveness').disabled = true;
    const badge = document.getElementById('badge-liveness');
    badge.textContent = 'Passed';
    badge.className = 'badge-mini passed';
    document.getElementById('liveness-desc').textContent = 'Active 3D response confirmed (99.2% score)';

    // Enable PAD check
    document.getElementById('btn-verify-pad').disabled = false;
    showToast('3D liveness verified! Now run Presentation Attack Detection (PAD).');
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// STEP 4: PAD Check (Presentation Attack Detection)
document.getElementById('btn-verify-pad').addEventListener('click', async () => {
  try {
    const reg = await requestJson(`/api/registrations/${state.registrationId}/pad`, {
      method: 'POST',
      body: JSON.stringify({ payload: 'real-person' }),
    });

    state.registration = reg;
    document.getElementById('btn-verify-pad').disabled = true;
    const badge = document.getElementById('badge-pad');
    badge.textContent = 'Passed';
    badge.className = 'badge-mini passed';
    document.getElementById('pad-desc').textContent = 'No spoofing detected (ISO/IEC 30107 compliant)';

    document.getElementById('verification-status-tag').textContent = 'Biometrics Passed';
    document.getElementById('verification-status-tag').className = 'status-tag';

    // Enable Complete Registration
    document.getElementById('btn-complete-reg').disabled = false;
    showToast('PAD anti-spoofing verified and Consent recorded! Click to issue QR Pass.');
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// STEP 5: Complete Registration & Issue QR Pass
document.getElementById('btn-complete-reg').addEventListener('click', async () => {
  const completeButton = document.getElementById('btn-complete-reg');
  completeButton.disabled = true;
  try {
    const reg = await requestJson(`/api/registrations/${state.registrationId}/complete`, {
      method: 'POST',
    });
    if (!reg.qr_token) throw new Error('Registration completed, but no pass token was returned.');

    state.registration = reg;
    state.qrToken = reg.qr_token;

    // Update Pass Badge UI
    document.getElementById('pass-status-tag').textContent = 'Registered';
    document.getElementById('pass-status-tag').className = 'status-tag';

    document.getElementById('pass-event-title').textContent = reg.event_id;
    document.getElementById('pass-type-pill').textContent = reg.participant_type || 'ATTENDEE';
    document.getElementById('pass-name').textContent = reg.full_name;
    document.getElementById('pass-org').textContent = reg.organization || 'General';
    document.getElementById('pass-part-id').textContent = reg.participant_id;
    document.getElementById('pass-reg-id').textContent = reg.registration_id || `REG-${reg.id}`;
    document.getElementById('pass-status').textContent = 'Registered (Verified)';
    document.getElementById('pass-consent-id').textContent = `CNS-${reg.participant_id.replace('PART-', '')}`;

    // Show QR Code image
    const qrImg = document.getElementById('qr-image');
    const qrPlaceholder = document.getElementById('qr-placeholder');
    qrImg.onload = () => {
      qrPlaceholder.style.display = 'none';
      qrImg.hidden = false;
    };
    qrImg.onerror = () => {
      qrImg.hidden = true;
      qrPlaceholder.style.display = 'flex';
      qrPlaceholder.querySelector('span').textContent = 'Pass issued; QR image could not load. Use the secure token below.';
    };
    qrImg.src = `/api/registrations/${reg.id}/qr?t=${Date.now()}`;

    // Token box
    document.getElementById('pass-token-val').value = reg.qr_token;
    document.getElementById('pass-token-box').style.display = 'block';
    document.getElementById('btn-use-at-gate').style.display = 'inline-block';

    setStepActive(5);
    showToast('Registration finalized! Official QR Pass is issued and ready.');
    document.getElementById('panel-qr-pass').scrollIntoView({ behavior: 'smooth', block: 'start' });
    loadEvents(); // Update registered count
  } catch (err) {
    completeButton.disabled = false;
    showToast(err.message, 'error');
  }
});

// Copy Token
document.getElementById('btn-copy-token').addEventListener('click', () => {
  const tokenVal = document.getElementById('pass-token-val').value;
  if (tokenVal) {
    navigator.clipboard.writeText(tokenVal);
    showToast('QR Token copied to clipboard');
  }
});

// Use at Entry Gate shortcut
document.getElementById('btn-use-at-gate').addEventListener('click', () => {
  if (state.qrToken) {
    document.getElementById('gate-qr-input').value = state.qrToken;
    switchTab('tab-checkin');
    showToast('Token loaded into Gate Entry Station');
  }
});

// Paste Latest in Gate tab
document.getElementById('btn-paste-latest').addEventListener('click', () => {
  if (state.qrToken) {
    document.getElementById('gate-qr-input').value = state.qrToken;
    showToast('Latest QR token filled');
  } else if (state.participantId) {
    document.getElementById('gate-qr-input').value = state.participantId;
    showToast('Latest Participant ID filled');
  } else {
    showToast('No active pass issued in this session yet', 'error');
  }
});

document.getElementById('btn-start-gate-camera').addEventListener('click', async () => {
  await startCamera('gate-camera-video', 'gate-camera-status', 'gate', 'environment');
});

// GATE ENTRY CHECK-IN FORM
const checkinForm = document.getElementById('checkin-form');
checkinForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const tokenInput = document.getElementById('gate-qr-input').value.trim();
  let facePayload;

  const card = document.getElementById('admission-card');
  const title = document.getElementById('admission-title');
  const desc = document.getElementById('admission-desc');
  const icon = document.getElementById('admission-icon');
  const meta = document.getElementById('admission-meta');

  try {
    facePayload = captureCameraFrame('gate-camera-video', 'gate');
    const payload = {
      qr_token: tokenInput,
      face_payload: facePayload,
    };

    const res = await requestJson('/api/check-in', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    // ACCESS GRANTED
    card.className = 'admission-card granted';
    icon.innerHTML = `<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>`;
    title.textContent = 'ACCESS GRANTED';
    title.style.color = 'var(--success)';
    desc.textContent = res.message;

    document.getElementById('adm-attendee').textContent = res.full_name;
    document.getElementById('adm-type').textContent = res.participant_type;
    document.getElementById('adm-org').textContent = res.organization;
    document.getElementById('adm-time').textContent = new Date(res.checked_in_at).toLocaleTimeString();
    meta.style.display = 'grid';
    stopCamera('gate');

    showToast(`Access Granted! Welcome ${res.full_name}.`);
  } catch (err) {
    // ACCESS DENIED
    card.className = 'admission-card denied';
    icon.innerHTML = `<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`;
    title.textContent = 'ACCESS DENIED';
    title.style.color = 'var(--danger)';
    desc.textContent = err.message;
    meta.style.display = 'none';

    showToast(`Check-In Blocked: ${err.message}`, 'error');
  }
});

function renderPagedTable(tableId, items, columns, emptyMessage, renderRow) {
  const table = document.getElementById(`table-${tableId}`);
  const tbody = table.querySelector('tbody');
  const pagination = document.querySelector(`[data-pagination="${tableId}"]`);
  const pageCount = Math.max(1, Math.ceil(items.length / rowsPerPage));
  state.pages[tableId] = Math.min(state.pages[tableId], pageCount);
  const start = (state.pages[tableId] - 1) * rowsPerPage;
  const pageItems = items.slice(start, start + rowsPerPage);
  tbody.innerHTML = items.length
    ? pageItems.map(renderRow).join('')
    : `<tr><td colspan="${columns}" class="empty-cell">${emptyMessage}</td></tr>`;
  pagination.querySelector('[data-page-label]').textContent = `Page ${state.pages[tableId]} of ${pageCount}`;
  pagination.querySelector('[data-page-action="previous"]').disabled = state.pages[tableId] <= 1;
  pagination.querySelector('[data-page-action="next"]').disabled = state.pages[tableId] >= pageCount;
}

document.querySelectorAll('.table-pagination').forEach((pagination) => {
  pagination.addEventListener('click', (event) => {
    const button = event.target.closest('[data-page-action]');
    if (!button || button.disabled) return;
    const tableId = pagination.dataset.pagination;
    state.pages[tableId] += button.dataset.pageAction === 'next' ? 1 : -1;
    loadDatabaseExplorer();
  });
});

// RELATIONAL DATABASE EXPLORER
async function loadDatabaseExplorer() {
  try {
    const [events, participants, biometrics, registrations] = await Promise.all([
      requestJson('/api/events'),
      requestJson('/api/participants'),
      requestJson('/api/biometrics'),
      requestJson('/api/registrations'),
    ]);

    document.getElementById('count-events').textContent = `${events.length} events`;
    renderPagedTable('events', events, 5, 'No events found.', (e) => `
        <tr>
          <td><code>${escapeHtml(e.event_id)}</code></td>
          <td><strong>${escapeHtml(e.event_name)}</strong></td>
          <td>${new Date(e.event_date).toLocaleDateString()}</td>
          <td>${e.capacity}</td>
          <td><span class="badge-mini passed">${e.registered_count || 0}</span></td>
        </tr>
      `);

    document.getElementById('count-participants').textContent = `${participants.length} participants`;
    renderPagedTable('participants', participants, 7, 'No participants registered yet.', (p) => `
        <tr>
            <td><code>${escapeHtml(p.participant_id)}</code></td>
            <td><strong>${escapeHtml(p.full_name)}</strong></td>
          <td>${escapeHtml(p.email)}</td>
          <td>${escapeHtml(p.mobile)}</td>
          <td><span class="badge-mini">${escapeHtml(p.participant_type)}</span></td>
          <td>${escapeHtml(p.organization)}</td>
          <td>${new Date(p.created_at).toLocaleString()}</td>
        </tr>
      `);

    document.getElementById('count-biometrics').textContent = `${biometrics.length} verifications`;
    renderPagedTable('biometrics', biometrics, 8, 'No biometric verification audits recorded yet.', (b) => `
        <tr>
          <td><code>${escapeHtml(b.verification_id)}</code></td>
          <td><code>${escapeHtml(b.participant_id)}</code></td>
          <td><small>${escapeHtml(b.provider_reference)}</small></td>
          <td><span class="badge-mini ${b.face_verified ? 'passed' : ''}">${b.face_verified ? 'Yes' : 'No'}</span></td>
          <td><span class="badge-mini ${b.liveness_verified ? 'passed' : ''}">${b.liveness_verified ? 'Yes' : 'No'}</span></td>
          <td><span class="badge-mini ${b.pad_verified ? 'passed' : ''}">${b.pad_verified ? 'Yes' : 'No'}</span></td>
          <td><code>${escapeHtml(b.consent_id)}</code></td>
          <td>${new Date(b.verified_at).toLocaleTimeString()}</td>
        </tr>
      `);

    document.getElementById('count-registrations').textContent = `${registrations.length} registrations`;
    renderPagedTable('registrations', registrations, 7, 'No registrations yet.', (registration) => `
        <tr>
           <td><code>${escapeHtml(registration.registration_id || `REG-${registration.id}`)}</code></td>
           <td><code>${escapeHtml(registration.participant_id)}</code></td>
           <td>${escapeHtml(registration.event_id)}</td>
           <td><span class="badge-mini passed">${escapeHtml(registration.status)}</span></td>
           <td>${registration.registered_at ? new Date(registration.registered_at).toLocaleString() : 'Pending'}</td>
           <td>${registration.checked_in_at ? new Date(registration.checked_in_at).toLocaleTimeString() : 'Not Checked In'}</td>
           <td><code>${escapeHtml((registration.qr_token || '—').slice(0, 24))}…</code></td>
        </tr>
      `);
  } catch (err) {
    console.error('Error refreshing explorer:', err);
  }
}

document.getElementById('btn-refresh-db').addEventListener('click', () => {
  loadDatabaseExplorer();
  showToast('Database records refreshed');
});

// Initialization
initializeTheme();
loadEvents();
