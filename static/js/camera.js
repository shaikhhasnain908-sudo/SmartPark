/* SmartPark HTML5 Camera, Upload & Auto ANPR Scanner Engine */

let mediaStream = null;
let autoScanInterval = null;
let isScanningActive = false;

function startCameraStream(videoElementId = 'webcam-video', onReady) {
  const video = document.getElementById(videoElementId);
  if (!video) return;

  const hdConstraints = {
    video: {
      width: { ideal: 1920, min: 1280 },
      height: { ideal: 1080, min: 720 },
      facingMode: 'environment'
    },
    audio: false
  };

  const fallbackConstraints = {
    video: { facingMode: 'environment' },
    audio: false
  };

  if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    navigator.mediaDevices.getUserMedia(hdConstraints)
      .catch(() => navigator.mediaDevices.getUserMedia(fallbackConstraints))
      .catch(() => navigator.mediaDevices.getUserMedia({ video: true, audio: false }))
      .then((stream) => {
        mediaStream = stream;
        video.srcObject = stream;
        video.play();
        if (onReady) onReady(true);
      })
      .catch((err) => {
        console.error('[Camera API Error]', err);
        if (onReady) onReady(false, err.message);
      });
  } else {
    if (onReady) onReady(false, "Camera API not supported by this browser.");
  }
}

function stopCameraStream() {
  stopAutoANPRScan();
  if (mediaStream) {
    mediaStream.getTracks().forEach(track => track.stop());
    mediaStream = null;
  }
}

function captureFrameBase64(videoElementId = 'webcam-video') {
  const video = document.getElementById(videoElementId);
  if (!video || !video.videoWidth) return null;

  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  return canvas.toDataURL('image/jpeg', 0.95);
}

function scanFrameForANPR(locationId, cameraType = 'ENTRY', callback, manualPlate = '') {
  const base64Frame = captureFrameBase64();
  if (!base64Frame && !manualPlate) {
    if (callback) callback(false, "Unable to capture frame from camera. Please upload an image or type plate number.", null);
    return;
  }

  fetch('/api/cv/frame', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      location_id: locationId,
      camera_type: cameraType,
      frame: base64Frame,
      manual_plate: manualPlate,
      user_id: window.currentUserId || null
    })
  })
  .then(res => res.json())
  .then(data => {
    if (callback) callback(data.success, data.message, data.data);
  })
  .catch(err => {
    if (callback) callback(false, "Network error during ANPR frame processing.", null);
  });
}

function scanUploadedPlateImage(file, locationId, cameraType = 'ENTRY', manualPlate = '', callback) {
  const formData = new FormData();
  if (file) formData.append('file', file);
  formData.append('location_id', locationId);
  formData.append('camera_type', cameraType);
  if (manualPlate) formData.append('manual_plate', manualPlate);
  if (window.currentUserId) formData.append('user_id', window.currentUserId);

  fetch('/api/cv/upload-scan', {
    method: 'POST',
    body: formData
  })
  .then(res => res.json())
  .then(data => {
    if (callback) callback(data.success, data.message, data.data);
  })
  .catch(err => {
    if (callback) callback(false, "Network error during image upload scan.", null);
  });
}

function scanManualPlateInput(plateNumber, locationId, cameraType = 'ENTRY', callback) {
  if (!plateNumber || !plateNumber.trim()) {
    if (callback) callback(false, "Please enter a valid license plate number.", null);
    return;
  }

  fetch('/api/cv/simulate-anpr', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      location_id: locationId,
      plate_number: plateNumber,
      camera_type: cameraType,
      user_id: window.currentUserId || null
    })
  })
  .then(res => res.json())
  .then(data => {
    if (callback) callback(data.success, data.message, data.data);
  })
  .catch(err => {
    if (callback) callback(false, "Network error processing manual plate.", null);
  });
}

function calculateParkingFee(plateNumber, locationId, durationHours = 1.0, callback) {
  if (!plateNumber || !plateNumber.trim()) {
    if (callback) callback(false, "Please enter a valid license plate number.", null);
    return;
  }

  fetch('/api/cv/calculate-fee', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      location_id: locationId,
      plate_number: plateNumber,
      duration_hours: durationHours
    })
  })
  .then(res => res.json())
  .then(data => {
    if (callback) callback(data.success, data.message, data.data);
  })
  .catch(err => {
    if (callback) callback(false, "Network error calculating parking fee.", null);
  });
}

function startAutoANPRScan(locationId, cameraType = 'ENTRY', onResultCallback) {
  if (isScanningActive) return;
  isScanningActive = true;

  autoScanInterval = setInterval(() => {
    scanFrameForANPR(locationId, cameraType, (success, msg, data) => {
      if (onResultCallback) onResultCallback(success, msg, data);
    });
  }, 2000); // Scans every 2 seconds automatically
}

function stopAutoANPRScan() {
  if (autoScanInterval) {
    clearInterval(autoScanInterval);
    autoScanInterval = null;
  }
  isScanningActive = false;
}
