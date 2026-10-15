/* Global SmartPark Client App & Socket.IO Listener */

document.addEventListener('DOMContentLoaded', () => {
  initSocketIO();
});

function showToast(title, message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <div style="font-weight:700; font-size:0.9rem; margin-bottom:2px;">${title}</div>
    <div style="font-size:0.85rem; color:var(--text-muted);">${message}</div>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4500);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function initSocketIO() {
  if (typeof io === 'undefined') return;

  const socket = io();

  socket.on('connect', () => {
    console.log('[SmartPark Socket] Real-time gateway connected');
  });

  socket.on('new_booking_alert', (data) => {
    showToast(data.title, data.message, 'success');
    const feed = document.getElementById('activity-feed');
    if (feed) {
      const item = document.createElement('div');
      item.className = 'glass-card';
      item.style.padding = '10px 14px';
      item.style.marginBottom = '8px';
      item.innerHTML = `<strong>${escapeHtml(data.title)}</strong>: ${escapeHtml(data.message)}`;
      feed.prepend(item);
    }
  });

  socket.on('booking_cancelled_alert', (data) => {
    showToast(data.title, data.message, 'danger');
  });

  // REAL-TIME ANPR DETECTION EVENT FOR DASHBOARDS
  socket.on('anpr_detection_alert', (evt) => {
    const d = evt.data || {};
    const alertLevel = d.alert_level === 'HIGH' ? 'danger' : (d.action_taken === 'ENTRY_GRANTED' ? 'success' : 'info');
    showToast(evt.title || `🚗 Vehicle ${d.detected_plate}`, evt.message || `Action: ${d.action_taken}`, alertLevel);

    handleAdminRealtimeUpdates(d);
    handleUserRealtimeUpdates(d);
  });
}

function handleAdminRealtimeUpdates(d) {
  // 1. Update KPI counters
  if (d.kpis) {
    const kpiAvail = document.getElementById('admin-kpi-available-slots');
    if (kpiAvail) kpiAvail.innerText = `${d.kpis.available_slots} / ${d.kpis.total_slots}`;

    const kpiOcc = document.getElementById('admin-kpi-occupied-slots');
    if (kpiOcc) kpiOcc.innerText = `${d.kpis.occupied_slots} / ${d.kpis.reserved_slots}`;

    const kpiActive = document.getElementById('admin-kpi-active-bookings');
    if (kpiActive) kpiActive.innerText = d.kpis.active_bookings;

    const kpiRev = document.getElementById('admin-kpi-today-revenue');
    if (kpiRev) kpiRev.innerText = `₹${Number(d.kpis.today_revenue).toFixed(2)}`;
  }

  // 2. Prepend to Admin Live Booking Stream Table
  const adminTableBody = document.getElementById('admin-booking-stream-body');
  if (adminTableBody && d.action_taken === 'ENTRY_GRANTED') {
    const tr = document.createElement('tr');
    tr.className = 'realtime-highlight';
    tr.innerHTML = `
      <td><strong>#${escapeHtml(d.booking_ref || 'ANPR-GATE')}</strong> <span class="badge badge-info" style="font-size:0.65rem;">LIVE</span></td>
      <td>${escapeHtml(d.user_name || 'Walk-In Guest')}</td>
      <td><span style="font-weight:700; color:var(--accent-cyan);">${escapeHtml(d.detected_plate)}</span></td>
      <td>${escapeHtml(d.location_name || 'N/A')}</td>
      <td><span class="badge badge-info">${escapeHtml(d.slot_number || 'N/A')}</span></td>
      <td>₹${d.total_fee || 0}</td>
      <td><span class="badge badge-success">ACTIVE</span></td>
    `;
    adminTableBody.prepend(tr);
  }

  // Prepend to Admin All Bookings Table (if on /admin/bookings page)
  const allBookingsBody = document.getElementById('admin-all-bookings-body');
  if (allBookingsBody && d.action_taken === 'ENTRY_GRANTED') {
    const tr = document.createElement('tr');
    tr.className = 'realtime-highlight';
    tr.innerHTML = `
      <td><strong>#${escapeHtml(d.booking_ref || 'ANPR-GATE')}</strong></td>
      <td>${escapeHtml(d.user_name || 'Walk-In Guest')}</td>
      <td><span style="font-weight:700; color:var(--accent-cyan);">${escapeHtml(d.detected_plate)}</span></td>
      <td>${escapeHtml(d.location_name || 'N/A')}</td>
      <td><span class="badge badge-info">${escapeHtml(d.slot_number || 'N/A')}</span></td>
      <td>${escapeHtml(d.entry_time || 'Just now')}</td>
      <td>-</td>
      <td>₹${d.total_fee || 0}</td>
      <td><span class="badge badge-success">ACTIVE</span></td>
      <td>
        ${d.booking_id ? `<button onclick="openCancelModal(${d.booking_id}, '${escapeHtml(d.booking_ref)}')" class="btn btn-danger" style="padding: 4px 10px; font-size: 0.75rem;"><i class="fa-solid fa-ban"></i> Cancel</button>` : '-'}
      </td>
    `;
    allBookingsBody.prepend(tr);
  }

  // 3. Prepend to Live Activity Feed
  const feed = document.getElementById('activity-feed');
  if (feed) {
    const item = document.createElement('div');
    item.className = 'realtime-highlight';
    const isEntry = d.action_taken === 'ENTRY_GRANTED';
    const borderColor = isEntry ? 'var(--success)' : (d.alert_level === 'HIGH' ? 'var(--danger)' : 'var(--accent-cyan)');
    item.style.background = 'rgba(30, 41, 59, 0.7)';
    item.style.padding = '10px 14px';
    item.style.borderRadius = 'var(--radius-sm)';
    item.style.borderLeft = `3px solid ${borderColor}`;
    item.style.fontSize = '0.85rem';
    item.style.marginBottom = '8px';
    item.innerHTML = `
      <div style="font-weight: 700; color: #fff;">ANPR ${escapeHtml(d.action_taken || 'SCAN')}</div>
      <div style="color: var(--text-muted); margin-top: 2px;">Plate <strong>${escapeHtml(d.detected_plate)}</strong> at ${escapeHtml(d.location_name || '')}. Slot: ${escapeHtml(d.slot_number || 'N/A')}. Fee: ₹${d.total_fee || 0}</div>
      <div style="font-size: 0.75rem; color: var(--text-dark); margin-top: 4px;">${d.timestamp || new Date().toLocaleTimeString()}</div>
    `;
    feed.prepend(item);
  }
}

function handleUserRealtimeUpdates(d) {
  // Check if current page is for the user who owns this vehicle or booking
  const isCurrentUser = window.currentUserId && (Number(d.user_id) === Number(window.currentUserId));
  if (!isCurrentUser) return;

  // 1. UPDATE USER DASHBOARD REGISTERED VEHICLES LIST
  const vehiclesGrid = document.getElementById('user-vehicles-grid');
  if (vehiclesGrid && d.detected_plate) {
    const existingCard = document.getElementById(`vehicle-card-${d.detected_plate}`);
    if (existingCard) {
      existingCard.classList.add('realtime-highlight');
      const statusBadge = existingCard.querySelector('.badge-secondary, .badge-success');
      if (statusBadge) {
        if (d.action_taken === 'ENTRY_GRANTED') {
          statusBadge.className = 'badge badge-success';
          statusBadge.style.fontSize = '0.72rem';
          statusBadge.innerText = `PARKED (${d.slot_number || 'Slot'})`;
        } else if (d.action_taken === 'EXIT_COMPLETED') {
          statusBadge.className = 'badge badge-secondary';
          statusBadge.style.fontSize = '0.72rem';
          statusBadge.innerText = 'READY';
        }
      }
    } else {
      // Vehicle not yet listed on the dashboard: create and prepend vehicle card!
      const emptyMsg = document.getElementById('no-vehicles-msg');
      if (emptyMsg) emptyMsg.remove();

      const newCard = document.createElement('div');
      newCard.className = 'user-vehicle-card realtime-highlight';
      newCard.id = `vehicle-card-${d.detected_plate}`;
      newCard.style.background = 'rgba(30, 41, 59, 0.6)';
      newCard.style.padding = '18px';
      newCard.style.borderRadius = 'var(--radius-sm)';
      newCard.style.border = '1px solid var(--accent-cyan)';
      newCard.style.transition = 'all 0.3s ease';
      newCard.style.boxShadow = '0 0 16px rgba(6, 186, 212, 0.4)';

      newCard.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <span class="badge badge-info">${escapeHtml(d.vehicle_type || 'Car')}</span>
          <span style="font-size: 0.8rem; color: var(--accent-cyan); font-weight:700;"><i class="fa-solid fa-bolt"></i> Scanned</span>
        </div>
        <div style="font-size: 1.35rem; font-weight: 800; color: #fff; letter-spacing: 0.05em; margin-bottom: 4px;">${escapeHtml(d.detected_plate)}</div>
        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.82rem; color: var(--text-muted);">
          <span>${escapeHtml(d.vehicle_model || 'Auto-Registered')}</span>
          <span class="badge badge-success" style="font-size: 0.72rem;">PARKED (${escapeHtml(d.slot_number || 'Assigned')})</span>
        </div>
      `;
      vehiclesGrid.prepend(newCard);

      // Increment vehicle counter badge
      const vCount = document.getElementById('user-vehicles-count');
      if (vCount) {
        const cur = parseInt(vCount.innerText) || 0;
        vCount.innerText = cur + 1;
      }
    }
  }

  // 2. UPDATE USER DASHBOARD ACTIVE BOOKING CONTAINER
  const activeContainer = document.getElementById('user-active-booking-container');
  const activeBody = document.getElementById('user-active-booking-body');
  const activeBadge = document.getElementById('user-active-badge');

  if (activeContainer && activeBody) {
    if (d.action_taken === 'ENTRY_GRANTED') {
      activeContainer.classList.add('realtime-highlight');
      if (activeBadge) {
        activeBadge.className = 'badge badge-success';
        activeBadge.innerText = 'ACTIVE';
      }

      activeBody.innerHTML = `
        <div class="realtime-highlight" style="padding: 12px; border-radius: 8px;">
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 20px;">
            <div>
              <div style="font-size: 0.8rem; color: var(--text-muted);">PARKING LOCATION</div>
              <div style="font-size: 1.1rem; font-weight: 700;">${escapeHtml(d.location_name || 'SmartPark')}</div>
            </div>

            <div>
              <div style="font-size: 0.8rem; color: var(--text-muted);">SLOT ASSIGNED</div>
              <div style="font-size: 1.3rem; font-weight: 800; color: var(--primary);">${escapeHtml(d.slot_number || 'Slot Assigned')}</div>
            </div>

            <div>
              <div style="font-size: 0.8rem; color: var(--text-muted);">VEHICLE NUMBER</div>
              <div style="font-size: 1.1rem; font-weight: 700; color: var(--accent-cyan);">${escapeHtml(d.detected_plate)}</div>
            </div>

            <div>
              <div style="font-size: 0.8rem; color: var(--text-muted);">LIVE ENTRY TIME</div>
              <div style="font-size: 0.95rem; font-weight: 600;">${escapeHtml(d.entry_time || 'Just now')}</div>
            </div>

            <div>
              <div style="font-size: 0.8rem; color: var(--text-muted);">TOTAL AMOUNT / RATE</div>
              <div style="font-size: 1.1rem; font-weight: 700; color: var(--success);">₹${d.total_fee || 20.0}</div>
            </div>
          </div>

          <div style="display: flex; gap: 12px; flex-wrap: wrap;">
            ${d.booking_id ? `
            <a href="/booking/${d.booking_id}" class="btn btn-primary">
              <i class="fa-solid fa-file-invoice"></i> View Booking & Invoice
            </a>
            <form method="POST" action="/booking/${d.booking_id}/cancel" onsubmit="return confirm('Are you sure you want to cancel this booking?');">
              <button type="submit" class="btn btn-danger">
                <i class="fa-solid fa-ban"></i> Cancel Booking
              </button>
            </form>
            ` : ''}
          </div>
        </div>
      `;
    } else if (d.action_taken === 'EXIT_COMPLETED') {
      activeContainer.classList.add('realtime-highlight');
      if (activeBadge) {
        activeBadge.className = 'badge badge-info';
        activeBadge.innerText = 'COMPLETED';
      }

      activeBody.innerHTML = `
        <div class="realtime-highlight" style="padding: 16px; border-radius: 8px; background: rgba(6,186,212,0.1); border-left: 4px solid var(--accent-cyan);">
          <div style="font-weight: 700; font-size: 1.05rem; color: #fff; margin-bottom: 4px;">
            🚗 Vehicle ${escapeHtml(d.detected_plate)} Exit Confirmed
          </div>
          <div style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 12px;">
            Stay Duration: <strong>${d.duration_hours || 1.0} hrs</strong> &bull; Total Paid: <strong>₹${d.total_fee}</strong>
          </div>
          <div style="display: flex; gap: 10px; flex-wrap: wrap;">
            <a href="/find-parking" class="btn btn-secondary" style="padding: 6px 14px; font-size: 0.85rem;">
              <i class="fa-solid fa-magnifying-glass"></i> Search Nearby Parking
            </a>
            <a href="/camera" class="btn btn-primary" style="padding: 6px 14px; font-size: 0.85rem;">
              <i class="fa-solid fa-camera"></i> Scan Another Vehicle
            </a>
          </div>
        </div>
      `;
    }
  }

  // 3. UPDATE USER DASHBOARD RECENT BOOKINGS TABLE
  const recentTable = document.getElementById('user-recent-bookings-body');
  if (recentTable && d.action_taken === 'ENTRY_GRANTED') {
    const emptyRow = document.getElementById('no-bookings-row');
    if (emptyRow) emptyRow.remove();

    const tr = document.createElement('tr');
    tr.className = 'realtime-highlight';
    tr.id = `booking-row-${d.booking_ref || Date.now()}`;
    const todayStr = new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

    tr.innerHTML = `
      <td><strong>#${escapeHtml(d.booking_ref || 'ANPR-GATE')}</strong> <span class="badge badge-info" style="font-size:0.65rem; margin-left:4px;">LIVE</span></td>
      <td>${todayStr}</td>
      <td>${escapeHtml(d.location_name || 'N/A')}</td>
      <td><span class="badge badge-info">${escapeHtml(d.slot_number || 'N/A')}</span></td>
      <td>${d.duration_hours || 1.0} hrs</td>
      <td>₹${d.total_fee || 0}</td>
      <td><span class="badge badge-success">ACTIVE</span></td>
      <td>
        ${d.booking_id ? `<a href="/booking/${d.booking_id}" class="btn btn-secondary" style="padding: 4px 10px; font-size: 0.75rem;">View</a>` : '-'}
      </td>
    `;
    recentTable.prepend(tr);
  }
}
