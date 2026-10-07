/* SmartPark HTML5 Camera & Auto ANPR Scanner Engine */

let mediaStream = null;
let autoScanInterval = null;
let isScanningActive = false;

function startCameraStream(videoElementId = 'webcam-video', onReady) {
  const video = document.getElementById(videoElementId);
  if (!video) return;

  if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
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

  return canvas.toDataURL('image/jpeg', 0.85);
}

function scanFrameForANPR(locationId, cameraType = 'ENTRY', callback) {
  const base64Frame = captureFrameBase64();
  if (!base64Frame) {
    if (callback) callback(false, "Unable to capture frame from webcam stream.", null);
    return;
  }

  fetch('/api/cv/frame', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      location_id: locationId,
      camera_type: cameraType,
      frame: base64Frame
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
