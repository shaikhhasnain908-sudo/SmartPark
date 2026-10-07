/* SMARTPARK — Dual Engine Google Maps & Leaflet Interactive Map System */

let gMap = null;
let leafletMap = null;
let gMarkers = [];
let leafletMarkers = [];
let userGpsMarker = null;
let currentUserLat = null;
let currentUserLng = null;

function calculateDistanceKm(lat1, lon1, lat2, lon2) {
  const R = 6371; // Earth radius in KM
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = 
    Math.sin(dLat/2) * Math.sin(dLat/2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * 
    Math.sin(dLon/2) * Math.sin(dLon/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return (R * c).toFixed(1);
}

function initSmartParkMap(containerId = 'map', locations = [], googleMapsKey = '') {
  const mapElement = document.getElementById(containerId);
  if (!mapElement) return;

  const defaultLat = 21.1702;
  const defaultLng = 72.8311;

  // 1. Attempt Google Maps Engine if loaded
  if (window.google && window.google.maps) {
    try {
      gMap = new google.maps.Map(mapElement, {
        center: { lat: defaultLat, lng: defaultLng },
        zoom: 13,
        styles: [
          { elementType: "geometry", stylers: [{ color: "#1d2c4d" }] },
          { elementType: "labels.text.fill", stylers: [{ color: "#8ec3b9" }] },
          { elementType: "labels.text.stroke", stylers: [{ color: "#1a3646" }] },
          { featureType: "road", elementType: "geometry", stylers: [{ color: "#304a7d" }] },
          { featureType: "water", elementType: "geometry", stylers: [{ color: "#0e1626" }] }
        ]
      });

      renderGoogleMapsMarkers(locations);
      console.log('[Map Engine] Google Maps initialized successfully');
      return;
    } catch (err) {
      console.warn('[Map Engine] Google Maps init failed, falling back to Leaflet', err);
    }
  }

  // 2. Leaflet OpenStreetMap Engine Fallback
  if (typeof L !== 'undefined') {
    leafletMap = L.map(containerId).setView([defaultLat, defaultLng], 13);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap & SmartPark'
    }).addTo(leafletMap);

    renderLeafletMarkers(locations);
    console.log('[Map Engine] Leaflet OpenStreetMap initialized successfully');
  }
}

function renderGoogleMapsMarkers(locations) {
  if (!gMap || !window.google) return;

  gMarkers.forEach(m => m.setMap(null));
  gMarkers = [];

  locations.forEach(loc => {
    let pinColor = "#10b981"; // Green
    if (loc.available_slots === 0) pinColor = "#ef4444"; // Red
    else if (loc.available_slots <= loc.total_slots * 0.3) pinColor = "#f59e0b"; // Yellow

    let distText = '';
    if (currentUserLat && currentUserLng) {
      const dist = calculateDistanceKm(currentUserLat, currentUserLng, loc.latitude, loc.longitude);
      distText = `<br/><strong>Distance:</strong> ${dist} km away`;
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
        <div style="color:#0f172a; padding:6px; min-width:190px;">
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

function renderLeafletMarkers(locations) {
  if (!leafletMap || typeof L === 'undefined') return;

  leafletMarkers.forEach(m => leafletMap.removeLayer(m));
  leafletMarkers = [];

  locations.forEach(loc => {
    let pinColor = '#10b981';
    if (loc.available_slots === 0) pinColor = '#ef4444';
    else if (loc.available_slots <= (loc.total_slots * 0.3)) pinColor = '#f59e0b';

    let distText = '';
    if (currentUserLat && currentUserLng) {
      const dist = calculateDistanceKm(currentUserLat, currentUserLng, loc.latitude, loc.longitude);
      distText = `<br/><strong>Distance:</strong> ${dist} km away`;
    }

    const svgIcon = L.divIcon({
      className: 'custom-map-pin',
      html: `
        <div style="background:${pinColor}; width:34px; height:34px; border-radius:50%; border:3px solid #fff; box-shadow:0 0 12px ${pinColor}; display:flex; align-items:center; justify-content:center; color:#fff; font-weight:bold; font-size:13px;">
          P
        </div>
      `,
      iconSize: [34, 34],
      iconAnchor: [17, 34]
    });

    const marker = L.marker([loc.latitude, loc.longitude], { icon: svgIcon }).addTo(leafletMap);

    const popupContent = `
      <div style="color:#0f172a; padding:6px; min-width:190px;">
        <h4 style="margin:0 0 4px; font-size:1rem; color:#0f172a;">${loc.name}</h4>
        <p style="font-size:0.8rem; color:#64748b; margin-bottom:8px;">${loc.address}</p>
        <div style="font-size:0.85rem; margin-bottom:10px;">
          <strong>Available:</strong> <span style="color:${pinColor}; font-weight:bold;">${loc.available_slots} / ${loc.total_slots} slots</span><br/>
          <strong>Rate:</strong> ₹${loc.hourly_rate}/hr${distText}
        </div>
        <a href="/book/${loc.id}" style="display:block; text-align:center; background:#2563eb; color:#fff; padding:6px 12px; border-radius:6px; font-weight:600; text-decoration:none; font-size:0.85rem;">Book Parking Slot</a>
      </div>
    `;

    marker.bindPopup(popupContent);
    leafletMarkers.push(marker);
  });
}

function updateLocationDistancesOnPage(locations) {
  if (!currentUserLat || !currentUserLng) return;

  locations.forEach(loc => {
    const dist = calculateDistanceKm(currentUserLat, currentUserLng, loc.latitude, loc.longitude);
    const distBadge = document.getElementById(`dist-badge-${loc.id}`);
    if (distBadge) {
      distBadge.innerText = `📍 ${dist} km away`;
      distBadge.style.display = 'inline-block';
    }
  });
}

function requestUserLocation(onSuccess, onError, locations = []) {
  if (!navigator.geolocation) {
    if (onError) onError("Geolocation is not supported by your browser.");
    return;
  }

  navigator.geolocation.getCurrentPosition(
    (position) => {
      currentUserLat = position.coords.latitude;
      currentUserLng = position.coords.longitude;

      // Google Maps centering
      if (gMap && window.google) {
        gMap.setCenter({ lat: currentUserLat, lng: currentUserLng });
        gMap.setZoom(14);

        if (userGpsMarker) userGpsMarker.setMap(null);

        userGpsMarker = new google.maps.Marker({
          position: { lat: currentUserLat, lng: currentUserLng },
          map: gMap,
          title: "Your GPS Location",
          icon: {
            path: google.maps.SymbolPath.CIRCLE,
            scale: 8,
            fillColor: "#3b82f6",
            fillOpacity: 1,
            strokeWeight: 3,
            strokeColor: "#ffffff"
          }
        });

        renderGoogleMapsMarkers(locations);
      }

      // Leaflet centering
      if (leafletMap && typeof L !== 'undefined') {
        leafletMap.setView([currentUserLat, currentUserLng], 14);

        if (userLocationMarker) leafletMap.removeLayer(userLocationMarker);

        userLocationMarker = L.circleMarker([currentUserLat, currentUserLng], {
          radius: 9,
          fillColor: "#3b82f6",
          color: "#ffffff",
          weight: 3,
          opacity: 1,
          fillOpacity: 0.95
        }).addTo(leafletMap);

        userLocationMarker.bindPopup("<b>📍 Your Live GPS Location</b>").openPopup();
        renderLeafletMarkers(locations);
      }

      updateLocationDistancesOnPage(locations);

      if (onSuccess) onSuccess(currentUserLat, currentUserLng);
    },
    (err) => {
      if (onError) onError("Location access was denied or unavailable.");
    }
  );
}
