/* SMARTPARK — Advanced Live Map & Real-Time Proximity Parking Engine
   Supports:
   - Live GPS tracking & continuous updates
   - Map click proximity inspection: 500m & 1000m radius circles
   - Dynamic real-time slot filtering (removes permanently occupied / full hubs)
   - Dual-engine: Google Maps API key integration + Dark Leaflet OpenStreetMap fallback
*/

let gMap = null;
let leafletMap = null;
let allLocations = [];
let currentOrigin = null; // { lat, lng, source: 'GPS' | 'CLICK' | 'SEARCH' }
let radiusFilter = 'ALL'; // 'ALL', '500', '1000'
let hideUnavailable = true; // "remove permanently used / full parking system"

// Drawing layers
let leafletCircle500 = null;
let leafletCircle1000 = null;
let leafletOriginMarker = null;
let leafletMarkers = [];

let gCircle500 = null;
let gCircle1000 = null;
let gOriginMarker = null;
let gMarkers = [];

// Geodesic distance calculation in meters (Haversine formula)
function calculateDistanceMeters(lat1, lon1, lat2, lon2) {
  const R = 6371000; // Earth radius in meters
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = 
    Math.sin(dLat/2) * Math.sin(dLat/2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * 
    Math.sin(dLon/2) * Math.sin(dLon/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return Math.round(R * c);
}

function formatDistance(meters) {
  if (meters === null || meters === undefined) return '';
  if (meters < 1000) return `${meters}m`;
  return `${(meters / 1000).toFixed(2)} km`;
}

function initSmartParkMap(containerId = 'map', locations = [], googleMapsKey = '') {
  const mapElement = document.getElementById(containerId);
  if (!mapElement) return;

  allLocations = locations.map(l => ({ ...l, _distanceMeters: null }));

  // Check localStorage for custom user Google Maps API key
  const savedKey = localStorage.getItem('SMARTPARK_GMAPS_KEY') || googleMapsKey || '';

  const defaultLat = allLocations.length > 0 ? allLocations[0].latitude : 21.1702;
  const defaultLng = allLocations.length > 0 ? allLocations[0].longitude : 72.8311;

  // 1. Google Maps Engine Check
  if (window.google && window.google.maps) {
    try {
      gMap = new google.maps.Map(mapElement, {
        center: { lat: defaultLat, lng: defaultLng },
        zoom: 14,
        mapTypeControl: false,
        streetViewControl: false,
        styles: [
          { elementType: "geometry", stylers: [{ color: "#1e293b" }] },
          { elementType: "labels.text.fill", stylers: [{ color: "#94a3b8" }] },
          { elementType: "labels.text.stroke", stylers: [{ color: "#0f172a" }] },
          { featureType: "road", elementType: "geometry", stylers: [{ color: "#334155" }] },
          { featureType: "road", elementType: "geometry.stroke", stylers: [{ color: "#1e293b" }] },
          { featureType: "water", elementType: "geometry", stylers: [{ color: "#0f172a" }] },
          { featureType: "poi", elementType: "geometry", stylers: [{ color: "#1e293b" }] },
          { featureType: "poi.park", elementType: "geometry", stylers: [{ color: "#064e3b" }] }
        ]
      });

      // Map Click Listener
      gMap.addListener('click', (e) => {
        setOriginLocation(e.latLng.lat(), e.latLng.lng(), 'CLICK');
      });

      renderGoogleMapsMarkers();
      console.log('[Map Engine] Google Maps active with Real-Time Click Radar');
      return;
    } catch (err) {
      console.warn('[Map Engine] Google Maps failed, fallback to Leaflet', err);
    }
  }

  // 2. Leaflet OpenStreetMap Engine Fallback
  if (typeof L !== 'undefined') {
    leafletMap = L.map(containerId).setView([defaultLat, defaultLng], 14);

    // High quality CartoDB Dark Matter / OpenStreetMap tiles
    L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap &copy; CartoDB &copy; SmartPark'
    }).addTo(leafletMap);

    // Map Click Listener
    leafletMap.on('click', (e) => {
      setOriginLocation(e.latlng.lat, e.latlng.lng, 'CLICK');
    });

    renderLeafletMarkers();
    console.log('[Map Engine] Leaflet OpenStreetMap active with Real-Time Click Radar');
  }
}

// Sets the reference origin point (User GPS, Map Click, or Search)
function setOriginLocation(lat, lng, source = 'CLICK') {
  currentOrigin = { lat, lng, source };

  // Calculate distance for all locations and sort by proximity
  allLocations.forEach(loc => {
    loc._distanceMeters = calculateDistanceMeters(lat, lng, loc.latitude, loc.longitude);
  });
  allLocations.sort((a, b) => a._distanceMeters - b._distanceMeters);

  // Update Visual Circles & Markers
  if (leafletMap && typeof L !== 'undefined') {
    updateLeafletRadar(lat, lng, source);
    renderLeafletMarkers();
  }

  if (gMap && window.google) {
    updateGoogleMapsRadar(lat, lng, source);
    renderGoogleMapsMarkers();
  }

  // Update UI sidebar list and stats
  updateLocationsSidebarUI();

  // Toast feedback
  const sourceName = source === 'GPS' ? 'Live GPS Location' : (source === 'SEARCH' ? 'Searched Place' : 'Clicked Map Point');
  const count500 = allLocations.filter(l => l._distanceMeters <= 500 && (!hideUnavailable || l.available_slots > 0)).length;
  const count1000 = allLocations.filter(l => l._distanceMeters <= 1000 && (!hideUnavailable || l.available_slots > 0)).length;

  if (window.showToast) {
    showToast(
      `📍 ${sourceName}`,
      `Found ${count500} hubs within 500m & ${count1000} hubs within 1000m with available slots.`,
      "info"
    );
  }
}

function updateLeafletRadar(lat, lng, source) {
  // Remove previous circles & origin marker
  if (leafletCircle500) leafletMap.removeLayer(leafletCircle500);
  if (leafletCircle1000) leafletMap.removeLayer(leafletCircle1000);
  if (leafletOriginMarker) leafletMap.removeLayer(leafletOriginMarker);

  // 1000m Outer Circle (Indigo/Purple, Dash)
  leafletCircle1000 = L.circle([lat, lng], {
    radius: 1000,
    color: '#818cf8',
    fillColor: '#818cf8',
    fillOpacity: 0.08,
    weight: 2,
    dashArray: '6, 6'
  }).addTo(leafletMap);

  // 500m Inner Circle (Vibrant Cyan, Solid)
  leafletCircle500 = L.circle([lat, lng], {
    radius: 500,
    color: '#06b6d4',
    fillColor: '#06b6d4',
    fillOpacity: 0.16,
    weight: 2
  }).addTo(leafletMap);

  // Animated Origin Marker
  const iconEmoji = source === 'GPS' ? '📍' : (source === 'SEARCH' ? '🔍' : '🎯');
  const labelText = source === 'GPS' ? 'Your Live Location' : (source === 'SEARCH' ? 'Searched Location' : 'Selected Target');

  const originIcon = L.divIcon({
    className: 'custom-origin-pin',
    html: `
      <div style="background:#ef4444; width:36px; height:36px; border-radius:50%; border:3px solid #fff; box-shadow:0 0 16px rgba(239,68,68,0.8); display:flex; align-items:center; justify-content:center; font-size:18px; animation:pulsePin 1.5s infinite;">
        ${iconEmoji}
      </div>
    `,
    iconSize: [36, 36],
    iconAnchor: [18, 18]
  });

  leafletOriginMarker = L.marker([lat, lng], { icon: originIcon }).addTo(leafletMap);
  leafletOriginMarker.bindPopup(`
    <div style="color:#0f172a; padding:6px; min-width:180px;">
      <h4 style="margin:0 0 4px; font-size:0.95rem; color:#ef4444;">${iconEmoji} ${labelText}</h4>
      <div style="font-size:0.8rem; color:#64748b; margin-bottom:6px;">Coordinates: ${lat.toFixed(4)}, ${lng.toFixed(4)}</div>
      <div style="font-size:0.82rem; background:#f1f5f9; padding:4px 8px; border-radius:4px;">
        <span style="color:#06b6d4; font-weight:bold;">● 500m Zone</span> &nbsp;|&nbsp; 
        <span style="color:#818cf8; font-weight:bold;">● 1000m Zone</span>
      </div>
    </div>
  `).openPopup();
}

function updateGoogleMapsRadar(lat, lng, source) {
  if (gCircle500) gCircle500.setMap(null);
  if (gCircle1000) gCircle1000.setMap(null);
  if (gOriginMarker) gOriginMarker.setMap(null);

  gCircle1000 = new google.maps.Circle({
    center: { lat, lng },
    radius: 1000,
    strokeColor: '#818cf8',
    strokeOpacity: 0.8,
    strokeWeight: 2,
    fillColor: '#818cf8',
    fillOpacity: 0.08,
    map: gMap
  });

  gCircle500 = new google.maps.Circle({
    center: { lat, lng },
    radius: 500,
    strokeColor: '#06b6d4',
    strokeOpacity: 0.9,
    strokeWeight: 2,
    fillColor: '#06b6d4',
    fillOpacity: 0.16,
    map: gMap
  });

  const iconEmoji = source === 'GPS' ? '📍' : (source === 'SEARCH' ? '🔍' : '🎯');
  const labelText = source === 'GPS' ? 'Your Live Location' : (source === 'SEARCH' ? 'Searched Location' : 'Selected Target');

  gOriginMarker = new google.maps.Marker({
    position: { lat, lng },
    map: gMap,
    title: labelText,
    icon: {
      path: google.maps.SymbolPath.CIRCLE,
      scale: 10,
      fillColor: "#ef4444",
      fillOpacity: 1,
      strokeWeight: 3,
      strokeColor: "#ffffff"
    }
  });
}

function renderLeafletMarkers() {
  if (!leafletMap || typeof L === 'undefined') return;

  leafletMarkers.forEach(m => leafletMap.removeLayer(m));
  leafletMarkers = [];

  const visibleLocations = getFilteredLocations();

  visibleLocations.forEach(loc => {
    let pinColor = '#10b981'; // Green
    if (loc.available_slots === 0) pinColor = '#ef4444'; // Red
    else if (loc.available_slots <= (loc.total_slots * 0.3)) pinColor = '#f59e0b'; // Amber

    let distanceBadge = '';
    let zoneBadge = '';
    if (loc._distanceMeters !== null) {
      const distStr = formatDistance(loc._distanceMeters);
      if (loc._distanceMeters <= 500) {
        zoneBadge = `<span style="background:rgba(6,186,212,0.15); color:#06b6d4; border:1px solid #06b6d4; padding:2px 6px; border-radius:4px; font-size:0.75rem; font-weight:700;">⚡ Under 500m</span>`;
      } else if (loc._distanceMeters <= 1000) {
        zoneBadge = `<span style="background:rgba(129,140,248,0.15); color:#818cf8; border:1px solid #818cf8; padding:2px 6px; border-radius:4px; font-size:0.75rem; font-weight:700;">🚗 Under 1000m</span>`;
      }
      distanceBadge = `<div style="margin-top:4px;"><strong>Distance:</strong> ${distStr} away ${zoneBadge}</div>`;
    }

    const isInside500 = loc._distanceMeters !== null && loc._distanceMeters <= 500;
    const pulseStyle = isInside500 ? 'animation:pulsePin 1.8s infinite;' : '';

    const svgIcon = L.divIcon({
      className: 'custom-map-pin',
      html: `
        <div style="background:${pinColor}; width:36px; height:36px; border-radius:50%; border:3px solid #fff; box-shadow:0 0 14px ${pinColor}; display:flex; align-items:center; justify-content:center; color:#fff; font-weight:800; font-size:14px; ${pulseStyle}">
          P
        </div>
      `,
      iconSize: [36, 36],
      iconAnchor: [18, 18]
    });

    const marker = L.marker([loc.latitude, loc.longitude], { icon: svgIcon }).addTo(leafletMap);

    const popupContent = `
      <div style="color:#0f172a; padding:6px; min-width:210px;">
        <h4 style="margin:0 0 4px; font-size:1.05rem; color:#0f172a; font-weight:800;">${loc.name}</h4>
        <p style="font-size:0.8rem; color:#64748b; margin-bottom:8px;">${loc.address}</p>
        <div style="font-size:0.85rem; margin-bottom:10px; background:#f8fafc; padding:8px; border-radius:6px; border:1px solid #e2e8f0;">
          <div><strong>Available:</strong> <span style="color:${pinColor}; font-weight:800;">${loc.available_slots} / ${loc.total_slots} Slots</span></div>
          <div><strong>Rate:</strong> ₹${loc.hourly_rate}/hour</div>
          ${distanceBadge}
        </div>
        <a href="/book/${loc.id}" style="display:block; text-align:center; background:#2563eb; color:#fff; padding:8px 14px; border-radius:6px; font-weight:700; text-decoration:none; font-size:0.88rem; box-shadow:0 2px 8px rgba(37,99,235,0.3);">
          ⚡ Book Slot Now
        </a>
      </div>
    `;

    marker.bindPopup(popupContent);
    leafletMarkers.push(marker);
  });
}

function renderGoogleMapsMarkers() {
  if (!gMap || !window.google) return;

  gMarkers.forEach(m => m.setMap(null));
  gMarkers = [];

  const visibleLocations = getFilteredLocations();

  visibleLocations.forEach(loc => {
    let pinColor = "#10b981";
    if (loc.available_slots === 0) pinColor = "#ef4444";
    else if (loc.available_slots <= loc.total_slots * 0.3) pinColor = "#f59e0b";

    let distText = '';
    if (loc._distanceMeters !== null) {
      distText = `<br/><strong>Distance:</strong> ${formatDistance(loc._distanceMeters)} away`;
    }

    const marker = new google.maps.Marker({
      position: { lat: loc.latitude, lng: loc.longitude },
      map: gMap,
      title: loc.name,
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        scale: 12,
        fillColor: pinColor,
        fillOpacity: 1,
        strokeWeight: 3,
        strokeColor: "#ffffff"
      }
    });

    const infoWindow = new google.maps.InfoWindow({
      content: `
        <div style="color:#0f172a; padding:6px; min-width:200px;">
          <h4 style="margin:0 0 4px; font-size:1rem; color:#0f172a;">${loc.name}</h4>
          <p style="font-size:0.8rem; color:#64748b; margin-bottom:8px;">${loc.address}</p>
          <div style="font-size:0.85rem; margin-bottom:10px;">
            <strong>Available:</strong> <span style="color:${pinColor}; font-weight:bold;">${loc.available_slots} / ${loc.total_slots} slots</span><br/>
            <strong>Rate:</strong> ₹${loc.hourly_rate}/hr${distText}
          </div>
          <a href="/book/${loc.id}" style="display:block; text-align:center; background:#2563eb; color:#fff; padding:6px 12px; border-radius:6px; font-weight:600; text-decoration:none; font-size:0.85rem;">Book Parking Slot</a>
        </div>
      `
    });

    marker.addListener('click', () => {
      infoWindow.open(gMap, marker);
    });

    gMarkers.push(marker);
  });
}

function getFilteredLocations() {
  return allLocations.filter(loc => {
    // 1. Availability filter (remove permanently occupied / full parking)
    if (hideUnavailable && loc.available_slots === 0) {
      return false;
    }

    // 2. Proximity Radius filter
    if (currentOrigin && loc._distanceMeters !== null) {
      if (radiusFilter === '500' && loc._distanceMeters > 500) return false;
      if (radiusFilter === '1000' && loc._distanceMeters > 1000) return false;
    }

    return true;
  });
}

// Updates sidebar parking cards, distance tags, badges, and counters
function updateLocationsSidebarUI() {
  const container = document.getElementById('locations-sidebar-list');
  const summaryEl = document.getElementById('map-radar-summary');
  const countBadge500 = document.getElementById('filter-count-500');
  const countBadge1000 = document.getElementById('filter-count-1000');
  const countBadgeAll = document.getElementById('filter-count-all');

  const visibleLocations = getFilteredLocations();

  // Update counts
  const availableList = allLocations.filter(l => !hideUnavailable || l.available_slots > 0);
  if (countBadgeAll) countBadgeAll.innerText = availableList.length;

  if (currentOrigin) {
    const under500 = availableList.filter(l => l._distanceMeters !== null && l._distanceMeters <= 500);
    const under1000 = availableList.filter(l => l._distanceMeters !== null && l._distanceMeters <= 1000);

    if (countBadge500) countBadge500.innerText = under500.length;
    if (countBadge1000) countBadge1000.innerText = under1000.length;

    if (summaryEl) {
      summaryEl.style.display = 'block';
      const originName = currentOrigin.source === 'GPS' ? 'Live GPS Location' : (currentOrigin.source === 'SEARCH' ? 'Searched Location' : 'Selected Map Point');
      
      let nearestText = '';
      if (allLocations.length > 0 && allLocations[0]._distanceMeters !== null) {
        const nearest = allLocations[0];
        nearestText = `Nearest: <strong>${nearest.name}</strong> (${formatDistance(nearest._distanceMeters)}, ${nearest.available_slots} slots free)`;
      }

      summaryEl.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
          <div>
            <div style="font-size:0.85rem; font-weight:700; color:var(--accent-cyan);">
              🎯 ${originName} (${currentOrigin.lat.toFixed(4)}, ${currentOrigin.lng.toFixed(4)})
            </div>
            <div style="font-size:0.78rem; color:#fff; margin-top:2px;">
              ${under500.length} hubs within <strong>500m</strong> &nbsp;|&nbsp; ${under1000.length} hubs within <strong>1000m</strong> &nbsp;•&nbsp; ${nearestText}
            </div>
          </div>
          <button onclick="resetOrigin()" class="btn btn-secondary" style="padding:4px 10px; font-size:0.75rem;">
            <i class="fa-solid fa-xmark"></i> Clear Pin
          </button>
        </div>
      `;
    }
  } else {
    if (countBadge500) countBadge500.innerText = '0';
    if (countBadge1000) countBadge1000.innerText = '0';
    if (summaryEl) summaryEl.style.display = 'none';
  }

  // Render cards in sidebar
  if (!container) return;

  if (visibleLocations.length === 0) {
    container.innerHTML = `
      <div class="glass-card" style="padding:28px; text-align:center; color:var(--text-muted);">
        <i class="fa-solid fa-square-parking" style="font-size:2.5rem; color:var(--accent-cyan); margin-bottom:10px; opacity:0.6;"></i>
        <h4 style="color:#fff; margin-bottom:6px;">No Parking Hubs Found</h4>
        <p style="font-size:0.85rem; margin-bottom:12px;">
          ${radiusFilter !== 'ALL' ? `No available parking within ${radiusFilter}m of this point.` : 'No available parking hubs matching your criteria.'}
        </p>
        <button onclick="setRadiusFilter('ALL')" class="btn btn-primary" style="padding:6px 14px; font-size:0.8rem;">
          Show All Distance Hubs
        </button>
      </div>
    `;
    return;
  }

  container.innerHTML = visibleLocations.map(loc => {
    let distBadgeHtml = '';
    let zoneBorder = '';

    if (loc._distanceMeters !== null) {
      const distStr = formatDistance(loc._distanceMeters);
      if (loc._distanceMeters <= 500) {
        distBadgeHtml = `<span class="badge badge-success" style="background:rgba(6,186,212,0.2); color:#06b6d4; border:1px solid #06b6d4;">⚡ ${distStr} (Within 500m)</span>`;
        zoneBorder = 'border-left: 4px solid #06b6d4;';
      } else if (loc._distanceMeters <= 1000) {
        distBadgeHtml = `<span class="badge badge-info" style="background:rgba(129,140,248,0.2); color:#818cf8; border:1px solid #818cf8;">🚗 ${distStr} (Within 1km)</span>`;
        zoneBorder = 'border-left: 4px solid #818cf8;';
      } else {
        distBadgeHtml = `<span class="badge badge-secondary">📍 ${distStr}</span>`;
      }
    }

    const availBadge = loc.available_slots > 5 
      ? `<span class="badge badge-success">${loc.available_slots} Free</span>`
      : (loc.available_slots > 0 
        ? `<span class="badge badge-warning">${loc.available_slots} Free</span>` 
        : `<span class="badge badge-danger">FULL</span>`);

    return `
      <div class="glass-card" style="padding: 18px; transition: all 0.2s ease; ${zoneBorder}" id="loc-card-${loc.id}">
        <div style="display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 8px;">
          <div>
            <h3 style="font-size: 1.05rem; color: #fff; margin-bottom: 4px;">${loc.name}</h3>
            ${distBadgeHtml}
          </div>
          ${availBadge}
        </div>
        
        <p style="color: var(--text-muted); font-size: 0.8rem; margin-bottom: 10px;">${loc.address}</p>
        
        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 0.85rem; margin-bottom: 12px; background: rgba(30,41,59,0.5); padding: 6px 10px; border-radius: 6px;">
          <div>Rate: <strong>₹${loc.hourly_rate}/hr</strong></div>
          <div>Capacity: <strong>${loc.available_slots} / ${loc.total_slots} Slots</strong></div>
        </div>

        <div style="display: flex; gap: 8px;">
          <a href="/book/${loc.id}" class="btn btn-primary" style="flex: 1; padding: 8px 12px; font-size: 0.85rem; text-align: center; text-decoration: none;">
            <i class="fa-solid fa-calendar-check"></i> Book Slot
          </a>
          <button onclick="focusMapLocation(${loc.latitude}, ${loc.longitude}, '${loc.name.replace(/'/g, "\\'")}')" class="btn btn-secondary" style="padding: 8px 12px; font-size: 0.85rem;" title="Show on Map">
            <i class="fa-solid fa-location-dot"></i>
          </button>
        </div>
      </div>
    `;
  }).join('');
}

function setRadiusFilter(filter) {
  radiusFilter = filter;

  // Update button active styling
  document.querySelectorAll('.radius-filter-btn').forEach(btn => {
    btn.className = 'btn btn-secondary radius-filter-btn';
  });
  const activeBtn = document.getElementById(`filter-btn-${filter.toLowerCase()}`);
  if (activeBtn) activeBtn.className = 'btn btn-primary radius-filter-btn';

  if (leafletMap) renderLeafletMarkers();
  if (gMap) renderGoogleMapsMarkers();
  updateLocationsSidebarUI();
}

function toggleHideUnavailable(checkbox) {
  hideUnavailable = checkbox.checked;
  if (leafletMap) renderLeafletMarkers();
  if (gMap) renderGoogleMapsMarkers();
  updateLocationsSidebarUI();
}

function resetOrigin() {
  currentOrigin = null;
  radiusFilter = 'ALL';
  allLocations.forEach(l => l._distanceMeters = null);

  if (leafletCircle500) leafletMap.removeLayer(leafletCircle500);
  if (leafletCircle1000) leafletMap.removeLayer(leafletCircle1000);
  if (leafletOriginMarker) leafletMap.removeLayer(leafletOriginMarker);

  if (gCircle500) gCircle500.setMap(null);
  if (gCircle1000) gCircle1000.setMap(null);
  if (gOriginMarker) gOriginMarker.setMap(null);

  setRadiusFilter('ALL');
  if (leafletMap) renderLeafletMarkers();
  if (gMap) renderGoogleMapsMarkers();
  updateLocationsSidebarUI();
}

function focusMapLocation(lat, lng, name) {
  if (leafletMap) {
    leafletMap.flyTo([lat, lng], 16, { animate: true, duration: 1.2 });
    leafletMarkers.forEach(m => {
      const pos = m.getLatLng();
      if (Math.abs(pos.lat - lat) < 0.0001 && Math.abs(pos.lng - lng) < 0.0001) {
        m.openPopup();
      }
    });
  }
  if (gMap) {
    gMap.panTo({ lat, lng });
    gMap.setZoom(16);
  }
}

// Live GPS Location
function requestUserLocation(onSuccess, onError, locations = []) {
  if (!navigator.geolocation) {
    if (onError) onError("Geolocation is not supported by your browser.");
    return;
  }

  navigator.geolocation.getCurrentPosition(
    (position) => {
      const lat = position.coords.latitude;
      const lng = position.coords.longitude;

      if (gMap) {
        gMap.panTo({ lat, lng });
        gMap.setZoom(15);
      }
      if (leafletMap) {
        leafletMap.flyTo([lat, lng], 15, { animate: true, duration: 1.0 });
      }

      setOriginLocation(lat, lng, 'GPS');
      if (onSuccess) onSuccess(lat, lng);
    },
    (err) => {
      console.warn('[Geolocation Error]', err);
      if (onError) onError("Location access was denied or timed out. Click anywhere on the map to set target point.");
    },
    { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 }
  );
}

// Live Address Geocoding Search (using OpenStreetMap Nominatim)
function searchAddressOnMap(query) {
  if (!query || !query.trim()) return;

  const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=1`;
  
  if (window.showToast) showToast("Searching Map", `Looking up location for "${query}"...`, "info");

  fetch(url)
    .then(res => res.json())
    .then(data => {
      if (data && data.length > 0) {
        const lat = parseFloat(data[0].lat);
        const lng = parseFloat(data[0].lon);

        if (leafletMap) leafletMap.flyTo([lat, lng], 15, { animate: true, duration: 1.2 });
        if (gMap) {
          gMap.panTo({ lat, lng });
          gMap.setZoom(15);
        }

        setOriginLocation(lat, lng, 'SEARCH');
        if (window.showToast) showToast("Location Found", `Centered at ${data[0].display_name.split(',')[0]}`, "success");
      } else {
        if (window.showToast) showToast("Not Found", `Could not find "${query}". Try clicking on the map.`, "warning");
      }
    })
    .catch(err => {
      console.error('[Geocoding Error]', err);
      if (window.showToast) showToast("Search Error", "Unable to connect to geocoding service.", "danger");
    });
}
