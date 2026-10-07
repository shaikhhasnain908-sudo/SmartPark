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

function initSocketIO() {
  if (typeof io === 'undefined') return;

  const socket = io();

  socket.on('connect', () => {
    console.log('[SmartPark Socket] Real-time gateway connected');
  });

  socket.on('new_booking_alert', (data) => {
    showToast(data.title, data.message, 'success');
    // If admin activity feed exists, prepend
    const feed = document.getElementById('activity-feed');
    if (feed) {
      const item = document.createElement('div');
      item.className = 'glass-card';
      item.style.padding = '10px 14px';
      item.style.marginBottom = '8px';
      item.innerHTML = `<strong>${data.title}</strong>: ${data.message}`;
      feed.prepend(item);
    }
  });

  socket.on('booking_cancelled_alert', (data) => {
    showToast(data.title, data.message, 'danger');
  });

  socket.on('anpr_detection_alert', (data) => {
    showToast(data.title, data.message, data.data.alert_level === 'HIGH' ? 'danger' : 'info');
  });
}
