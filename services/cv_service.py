import os
import re
import cv2
import base64
import math
import uuid
import numpy as np
from datetime import datetime
from database import db
from models import ANPRLog, Booking, ParkingSlot, ParkingLocation, Vehicle, User, Blacklist, ActivityLog, Invoice
from services.invoice_service import generate_pdf_invoice
from services.booking_service import generate_invoice_number
from services.socket_service import broadcast_anpr_event

# Global EasyOCR Reader instance (initialized lazily to avoid startup delay)
_easyocr_reader = None

def get_ocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None or _easyocr_reader is False:
        try:
            import easyocr
            # Load English OCR reader on CPU with verbose=False to prevent Windows charmap stdout errors
            _easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            print("[CV Service] EasyOCR Reader initialized successfully.")
        except Exception as e:
            import traceback
            print(f"[CV Service] EasyOCR init warning: {e}")
            traceback.print_exc()
            _easyocr_reader = False
    return _easyocr_reader

def decode_base64_image(base64_str):
    """
    Decodes a base64 encoded image string into an OpenCV BGR numpy array.
    """
    try:
        if not base64_str:
            return None
        if ',' in base64_str:
            base64_str = base64_str.split(',')[1]
        img_bytes = base64.b64decode(base64_str)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        print(f"[CV Service] Base64 decode error: {e}")
        return None

# Recognized Indian State and Union Territory RTO Prefix Codes
INDIAN_STATE_CODES = {
    'AN', 'AP', 'AR', 'AS', 'BR', 'CG', 'CH', 'DD', 'DL', 'DN',
    'GA', 'GJ', 'HR', 'HP', 'JH', 'JK', 'KA', 'KL', 'LA', 'LD',
    'MB', 'MH', 'ML', 'MN', 'MP', 'MZ', 'NL', 'OD', 'PB', 'PY',
    'RJ', 'SK', 'TN', 'TR', 'TS', 'UK', 'UP', 'US', 'WB', 'BH'
}

LETTER_TO_DIGIT = {
    'O': '0', 'Q': '0', 'D': '0', 'I': '1', 'L': '1', 'Z': '2',
    'E': '3', 'A': '4', 'S': '5', 'G': '6', 'T': '7', 'B': '8'
}

DIGIT_TO_LETTER = {
    '0': 'O', '1': 'I', '2': 'Z', '3': 'E', '4': 'A', '5': 'S',
    '6': 'G', '7': 'T', '8': 'B'
}

# Mapping of second character to likely Indian State code when the first character is clipped or missed by camera
STATE_SECOND_LETTER_MAP = {
    'N': ['TN', 'DN', 'AN', 'MN'],
    'H': ['MH', 'CH', 'JH'],
    'J': ['GJ', 'RJ'],
    'L': ['DL', 'KL', 'ML', 'NL'],
    'A': ['KA', 'GA', 'LA'],
    'P': ['UP', 'MP', 'AP', 'HP'],
    'B': ['PB', 'WB'],
    'R': ['HR', 'AR', 'TR', 'BR'],
    'K': ['JK', 'SK', 'UK'],
    'D': ['DD', 'OD'],
    'S': ['TS', 'AS']
}

def clean_plate_text(raw_text):
    """
    Sanitize OCR text into a clean uppercase license plate string (e.g. TN03MF4477, MH12DE5678, GJ09AB1234).
    Handles edge cases:
      - Missing first state letter (e.g. 'N 03 MF 4477' -> 'TN03MF4477')
      - Missing leading zero in RTO (e.g. 'TN 3 MF 4477' -> 'TN03MF4477')
      - Missing / degraded characters from glare (e.g. 'TNO3MF447S' -> 'TN03MF4475')
      - Missing last digit or VIP 3-digit plates (e.g. 'TN 03 MF 447' -> 'TN03MF447')
      - Leading 'IND' hologram badge stripping
    """
    if not raw_text:
        return ""
    cleaned = re.sub(r'[^A-Za-z0-9]', '', raw_text).upper()
    if len(cleaned) < 4:
        return ""

    # Strip leading 'IND' hologram if present
    if cleaned.startswith('IND') and len(cleaned) >= 8:
        cleaned = cleaned[3:]

    # Priority 1: Match standard Indian High Security plate pattern with valid state code
    # Format: [State: 2 letters][RTO: 1-2 digits][Series: 0-3 letters][Number: 3-4 digits]
    for m in re.finditer(r'([A-Z]{2})([0-9]{1,2})([A-Z]{0,3})([0-9]{3,4})', cleaned):
        state = m.group(1)
        rto = m.group(2)
        series = m.group(3)
        num = m.group(4)
        if state in INDIAN_STATE_CODES:
            if len(rto) == 1:
                rto = f"0{rto}"
            return f"{state}{rto}{series}{num}"

    # Priority 2: Bharat series (e.g., 22BH1234AA)
    bh_match = re.search(r'([0-9]{2}BH[0-9]{4}[A-Z]{1,2})', cleaned)
    if bh_match:
        return bh_match.group(1)

    # Priority 3: State code + numerical digits (e.g., GJ091234, MH125678, TN034477)
    for st_match in re.finditer(r'([A-Z]{2})([0-9]{3,8})', cleaned):
        if st_match.group(1) in INDIAN_STATE_CODES:
            return st_match.group(0)

    # Priority 4: Sliding window search with OCR confusion correction for Indian plates
    # (Handles e.g., 'TNO3MF4477' with letter 'O' instead of digit '0', or '7N03MF447S' -> 'TN03MF4475')
    for length in [10, 9, 8, 11, 7]:
        for i in range(0, max(1, len(cleaned) - length + 1)):
            chunk = cleaned[i:i+length]
            s0 = DIGIT_TO_LETTER.get(chunk[0], chunk[0])
            s1 = DIGIT_TO_LETTER.get(chunk[1], chunk[1])
            state = s0 + s1
            if state in INDIAN_STATE_CODES:
                tail_len = 4 if length >= 9 else (3 if length >= 7 else 2)
                tail_raw = chunk[-tail_len:]
                tail_digits = ''.join([LETTER_TO_DIGIT.get(c, c) for c in tail_raw])
                mid_raw = chunk[2:-tail_len]
                if mid_raw:
                    rto_len = 2 if len(mid_raw) >= 3 else (1 if len(mid_raw) == 1 else (2 if mid_raw[:2].isdigit() else 1))
                    rto = ''.join([LETTER_TO_DIGIT.get(c, c) for c in mid_raw[:rto_len]])
                    if len(rto) == 1:
                        rto = f"0{rto}"
                    series = ''.join([DIGIT_TO_LETTER.get(c, c) for c in mid_raw[rto_len:]])
                    cand = f"{state}{rto}{series}{tail_digits}"
                    if re.match(r'^[A-Z]{2}[0-9]{2}[A-Z]{0,3}[0-9]{3,4}$', cand):
                        return cand

    # Priority 5: Recover Missing First State Letter (e.g., 'N03MF4477' -> 'TN03MF4477')
    # If the first letter was clipped by the camera edge: [1 letter][1-2 digits][1-3 letters][3-4 digits]
    miss_first = re.match(r'^([A-Z])([0-9]{1,2})([A-Z]{1,3})([0-9]{3,4})$', cleaned)
    if miss_first:
        end_char = miss_first.group(1)
        rto = miss_first.group(2)
        if len(rto) == 1:
            rto = f"0{rto}"
        series = miss_first.group(3)
        num = miss_first.group(4)
        if end_char in STATE_SECOND_LETTER_MAP:
            recovered_state = STATE_SECOND_LETTER_MAP[end_char][0] # Default to primary state (e.g. 'TN' for 'N')
            return f"{recovered_state}{rto}{series}{num}"

    # Priority 6: Any standard pattern match
    p = re.search(r'([A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{3,4})', cleaned)
    if p:
        return p.group(1)

    # Priority 7: Fallback only for plausible alphanumeric vehicle plate sequences (must have both letters & digits)
    if 5 <= len(cleaned) <= 12:
        letters = len(re.findall(r'[A-Z]', cleaned))
        digits = len(re.findall(r'[0-9]', cleaned))
        if letters >= 1 and digits >= 2:
            # Reject common non-plate words from screen or camera scene
            banned = {'GOOGLE', 'CHROME', 'TAMIL', 'ACKO', 'FANCY', 'GUIDE', 'SCREEN', 'CAMERA', 'SMART', 'PLATE', 'REGISTER'}
            if not any(b in cleaned for b in banned):
                return cleaned

    return ""

def preprocess_and_detect_plate_region(img):
    """
    OpenCV computer vision pipeline to extract candidate license plate region.
    Finds rectangular contours matching standard license plate aspect ratio (approx 1.5 to 6.5).
    """
    if img is None:
        return None, None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Apply CLAHE contrast enhancement for low lighting conditions
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    
    bfilter = cv2.bilateralFilter(enhanced, 11, 17, 17)
    edged = cv2.Canny(bfilter, 30, 200)

    # Find contours
    keypoints = cv2.findContours(edged.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contours = keypoints[0] if len(keypoints) == 2 else keypoints[1]
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:15]

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if h > 0 and w > 0:
            aspect_ratio = float(w) / float(h)
            area = cv2.contourArea(contour)
            if 1.5 <= aspect_ratio <= 6.5 and area > 400:
                cropped_plate = enhanced[max(0, y-5):min(img.shape[0], y+h+5), max(0, x-5):min(img.shape[1], x+w+5)]
                if cropped_plate.size > 0:
                    return cropped_plate, (x, y, w, h)

    return enhanced, (0, 0, img.shape[1], img.shape[0])

def perform_anpr_ocr(img):
    """
    Runs ANPR OCR on frame image using EasyOCR with robust multi-pass detection.
    Evaluates:
      1. Center Guide ROI with 25px Margin Padding (prevents edge character cut-off)
      2. Super-Resolution 2.2x Upscaled ROI with Bicubic Interpolation
      3. Morphological Stroke-Healing (connects broken or faint character lines)
      4. High-Contrast Unsharp Masking & CLAHE 4.0
      5. Adaptive Binarization (Otsu & Gaussian)
      6. Contour-detected License Plate Box
      7. Full Original Frame
    Extracts, merges, reconstructs, and scores the most accurate license plate string.
    """
    if img is None:
        return "", 0.0, (0, 0, 0, 0)

    reader = get_ocr_reader()
    if not reader:
        return "", 0.0, (0, 0, img.shape[1], img.shape[0])

    candidates = []
    h, w = img.shape[:2]

    # Define Center Overlay Region of Interest (matches UI ALIGN LICENSE PLATE HERE box)
    roi_y1 = max(0, int(h * 0.14))
    roi_y2 = min(h, int(h * 0.86))
    roi_x1 = max(0, int(w * 0.10))
    roi_x2 = min(w, int(w * 0.90))
    center_roi = img[roi_y1:roi_y2, roi_x1:roi_x2]

    passes = []

    if center_roi.size > 0:
        # Add 25px margin padding around center ROI so edge letters (T, 7, etc.) are never clipped
        padded_roi = cv2.copyMakeBorder(center_roi, 25, 25, 30, 30, cv2.BORDER_REPLICATE)
        orig_offset = (max(0, roi_x1 - 30), max(0, roi_y1 - 25))

        # Pass 1: Padded Center ROI
        passes.append(("padded_roi", padded_roi, orig_offset))

        # Pass 2: Super-Resolution 2.2x Upscaled ROI (crucial for small, distant, or thin characters)
        try:
            upscaled_roi = cv2.resize(padded_roi, (0, 0), fx=2.2, fy=2.2, interpolation=cv2.INTER_CUBIC)
            passes.append(("upscaled_roi", upscaled_roi, orig_offset))
        except Exception:
            pass

        # Pass 3: Morphological Stroke Healing (connects thin broken character lines e.g. 0, 8, 4, B)
        try:
            gray_roi = cv2.cvtColor(padded_roi, cv2.COLOR_BGR2GRAY)
            close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            healed_roi = cv2.morphologyEx(gray_roi, cv2.MORPH_CLOSE, close_kernel)
            passes.append(("healed_roi", healed_roi, orig_offset))
        except Exception:
            pass

        # Pass 4: Unsharp Mask Sharpened & Contrast-Enhanced (CLAHE 4.0)
        try:
            if 'gray_roi' in locals():
                clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
                clahe_roi = clahe.apply(gray_roi)
                gaussian = cv2.GaussianBlur(clahe_roi, (0, 0), 2.0)
                sharpened_roi = cv2.addWeighted(clahe_roi, 1.8, gaussian, -0.8, 0)
                passes.append(("sharpened_roi", sharpened_roi, orig_offset))
        except Exception:
            pass

        # Pass 5: Adaptive Gaussian & Otsu Binarization (neutralizes screen backlighting glare)
        try:
            if 'gray_roi' in locals():
                thresh_roi = cv2.adaptiveThreshold(gray_roi, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 17, 7)
                passes.append(("thresh_roi", thresh_roi, orig_offset))
        except Exception:
            pass

    # Pass 6: Contour License Plate Region
    try:
        cropped_plate, c_bbox = preprocess_and_detect_plate_region(img)
        if cropped_plate is not None and cropped_plate.size > 0:
            padded_contour = cv2.copyMakeBorder(cropped_plate, 15, 15, 20, 20, cv2.BORDER_REPLICATE)
            passes.append(("contour_crop", padded_contour, (c_bbox[0], c_bbox[1])))
    except Exception:
        pass

    # Pass 7: Full Original Image
    passes.append(("original", img, (0, 0)))

    # Process passes in order of precision
    for pass_name, img_pass, (offset_x, offset_y) in passes:
        try:
            # Call EasyOCR with sensitive character detection thresholds so no faint characters are dropped
            results = reader.readtext(
                img_pass,
                text_threshold=0.28,
                low_text=0.18,
                link_threshold=0.28,
                mag_ratio=1.5,
                add_margin=0.15,
                slope_ths=0.15,
                ycenter_ths=0.6
            )
            if not results:
                continue

            # Sort detected words horizontally in natural reading order (left-to-right)
            def get_x_center(box):
                try:
                    return (box[0][0] + box[1][0]) / 2.0
                except Exception:
                    return 0.0

            sorted_results = sorted(results, key=lambda r: get_x_center(r[0]))

            # 1. Evaluate Complete Joined String
            joined_raw = " ".join([r[1] for r in sorted_results])
            cleaned_joined = clean_plate_text(joined_raw)
            if cleaned_joined:
                score = 1.0
                if re.search(r'[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{3,4}', cleaned_joined):
                    score += 0.7
                if cleaned_joined[:2] in INDIAN_STATE_CODES:
                    score += 0.4
                candidates.append((cleaned_joined, score, 0.95, (offset_x, offset_y, img_pass.shape[1], img_pass.shape[0])))
                # If high-confidence standard Indian plate match, return immediately for instant responsiveness
                if score >= 1.7:
                    return cleaned_joined, 0.95, (offset_x, offset_y, img_pass.shape[1], img_pass.shape[0])

            # 2. Evaluate Multi-Token Windows (Permutations of 2, 3, 4 tokens to assemble split plates)
            n_tokens = len(sorted_results)
            for window_size in range(2, min(5, n_tokens + 1)):
                for start_idx in range(n_tokens - window_size + 1):
                    sub_tokens = sorted_results[start_idx : start_idx + window_size]
                    sub_spaced = " ".join([t[1] for t in sub_tokens])
                    sub_compact = "".join([t[1] for t in sub_tokens])
                    for text_candidate in [sub_spaced, sub_compact]:
                        cleaned_cand = clean_plate_text(text_candidate)
                        if cleaned_cand:
                            avg_conf = sum([float(t[2]) for t in sub_tokens]) / float(window_size)
                            score = avg_conf
                            if re.search(r'[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{3,4}', cleaned_cand):
                                score += 0.7
                            if cleaned_cand[:2] in INDIAN_STATE_CODES:
                                score += 0.4
                            candidates.append((cleaned_cand, score, avg_conf, (offset_x, offset_y, img_pass.shape[1], img_pass.shape[0])))
                            if score >= 1.7:
                                return cleaned_cand, avg_conf, (offset_x, offset_y, img_pass.shape[1], img_pass.shape[0])

            # 3. Evaluate Individual Word Tokens
            for res in sorted_results:
                raw_txt = res[1]
                conf = float(res[2])
                cleaned = clean_plate_text(raw_txt)
                if cleaned:
                    score = conf
                    if re.search(r'[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{3,4}', cleaned):
                        score += 0.7
                    if cleaned[:2] in INDIAN_STATE_CODES:
                        score += 0.4

                    box = res[0]
                    try:
                        xs = [p[0] for p in box]
                        ys = [p[1] for p in box]
                        bx = int(min(xs)) + offset_x
                        by = int(min(ys)) + offset_y
                        bw = int(max(xs) - min(xs))
                        bh = int(max(ys) - min(ys))
                        item_bbox = (bx, by, bw, bh)
                    except Exception:
                        item_bbox = (offset_x, offset_y, img_pass.shape[1], img_pass.shape[0])

                    candidates.append((cleaned, score, conf, item_bbox))
                    if score >= 1.6:
                        return cleaned, conf, item_bbox

        except Exception as e:
            print(f"[CV Service] EasyOCR pass ({pass_name}) warning: {e}")

    if candidates:
        best = max(candidates, key=lambda x: x[1])
        return best[0], best[2], best[3]

    return "", 0.0, (0, 0, img.shape[1], img.shape[0])

def process_anpr_frame(location_id, base64_frame, camera_type='ENTRY', manual_plate=None, user_id=None):
    """
    Main ANPR API processing pipeline.
    Decodes frame, performs ANPR OCR, checks database, registers vehicle, updates booking/slot, logs event.
    """
    img = decode_base64_image(base64_frame) if base64_frame else None
    bbox = (0, 0, 0, 0)
    plate_number = ""
    confidence = 0.0

    if img is not None:
        plate_number, confidence, bbox = perform_anpr_ocr(img)

    # Use manual plate if provided or fallback when OCR fails
    if manual_plate and manual_plate.strip():
        plate_number = clean_plate_text(manual_plate)
        confidence = 1.0

    if not plate_number or len(plate_number) < 4:
        return False, "Unable to read license plate from image. Please enter vehicle number below to register & grant entry:", {
            'requires_manual_entry': True,
            'camera_type': camera_type,
            'location_id': location_id,
            'confidence': 0.0,
            'plate': '',
            'bbox': {'x': 0, 'y': 0, 'w': 0, 'h': 0}
        }

    success, message, result = process_anpr_plate_logic(location_id, plate_number, confidence, camera_type, user_id=user_id)
    if result:
        result['bbox'] = {'x': bbox[0], 'y': bbox[1], 'w': bbox[2], 'h': bbox[3]}
    return success, message, result

def get_or_create_walkin_user_and_vehicle(plate_number, user_id=None):
    """
    Ensures a valid User and Vehicle exist and are registered in the database for manual or ANPR entries.
    If user_id is provided, associates the vehicle with that specific user.
    """
    plate_number = clean_plate_text(plate_number)
    target_user = None
    if user_id:
        target_user = db.session.get(User, user_id) if hasattr(db.session, 'get') else User.query.get(user_id)

    vehicle = Vehicle.query.filter_by(vehicle_number=plate_number).first()
    if vehicle:
        if target_user and vehicle.owner and vehicle.owner.email == 'walkin@smartpark.com':
            vehicle.user_id = target_user.id
            db.session.flush()
            return target_user, vehicle
        return vehicle.owner, vehicle

    if not target_user:
        target_user = User.query.filter_by(email='walkin@smartpark.com').first()
        if not target_user:
            target_user = User(
                full_name="Walk-In Guest",
                email="walkin@smartpark.com",
                phone="+91 0000000000",
                role="user",
                is_active=True
            )
            target_user.set_password("walkin123")
            db.session.add(target_user)
            db.session.flush()

    vehicle = Vehicle(
        user_id=target_user.id,
        vehicle_number=plate_number,
        vehicle_type="Car",
        model="Auto-Registered Vehicle",
        nickname=f"Vehicle {plate_number[-4:] if len(plate_number)>=4 else plate_number}"
    )
    db.session.add(vehicle)
    db.session.flush()
    return target_user, vehicle

def process_anpr_plate_logic(location_id, plate_number, confidence=0.9, camera_type='ENTRY', user_id=None):
    """
    Business logic for ANPR plate recognition event.
    Auto-registers number plate in database, tracks live entry timestamp, handles online bookings & exit calculations.
    """
    plate_number = clean_plate_text(plate_number)
    if not plate_number:
        return False, "License plate number is required.", None

    location = db.session.get(ParkingLocation, location_id) if hasattr(db.session, 'get') else ParkingLocation.query.get(location_id)
    if not location:
        return False, "Invalid location ID", None

    # Check Blacklist
    blacklisted = Blacklist.query.filter_by(vehicle_number=plate_number).first()
    if blacklisted:
        action_taken = "BLACKLISTED"
        anpr_log = ANPRLog(
            location_id=location_id,
            detected_plate=plate_number,
            confidence=confidence,
            action_taken=action_taken
        )
        db.session.add(anpr_log)
        db.session.commit()
        
        broadcast_anpr_event({
            'detected_plate': plate_number,
            'location_name': location.name,
            'action_taken': action_taken,
            'reason': blacklisted.reason,
            'alert_level': 'HIGH'
        })
        return True, f"⚠️ ALERT: Blacklisted Vehicle Detected ({plate_number})!", {
            'plate': plate_number,
            'action': action_taken,
            'status': 'REJECTED'
        }

    # Auto-register vehicle in database if not present
    vehicle = Vehicle.query.filter_by(vehicle_number=plate_number).first()
    if not vehicle:
        user, vehicle = get_or_create_walkin_user_and_vehicle(plate_number, user_id=user_id)
        db.session.commit()
    else:
        if user_id:
            logged_in_user = db.session.get(User, user_id) if hasattr(db.session, 'get') else User.query.get(user_id)
            if logged_in_user and vehicle.owner and vehicle.owner.email == 'walkin@smartpark.com':
                vehicle.user_id = logged_in_user.id
                db.session.commit()
        user = vehicle.owner

    # Search for active/confirmed booking at this location for this vehicle
    matched_booking = Booking.query.filter(
        Booking.vehicle_id == vehicle.id,
        Booking.location_id == location_id,
        Booking.status.in_(['CONFIRMED', 'ACTIVE', 'RESERVED'])
    ).order_by(Booking.start_time.asc()).first()

    now_utc = datetime.utcnow()
    now_local = datetime.now()
    live_entry_str = now_local.strftime('%b %d, %Y - %I:%M:%S %p')
    action_taken = "PROCESSED"
    message = ""
    status_code = "SUCCESS"
    total_fee = 0.0
    duration_hrs = 1.0

    if camera_type == 'ENTRY':
        if matched_booking:
            # Active or pre-booked reservation
            matched_booking.status = 'ACTIVE'
            matched_booking.start_time = now_utc
            matched_booking.entry_time = now_utc
            slot = ParkingSlot.query.get(matched_booking.slot_id)
            if slot:
                slot.status = 'OCCUPIED'
                slot.current_vehicle_number = plate_number
                slot.current_booking_id = matched_booking.id
            action_taken = "ENTRY_GRANTED"
            total_fee = matched_booking.total_amount
            message = f"✅ Access Granted! Vehicle {plate_number} registered & entered Slot {slot.slot_number if slot else 'N/A'} at {live_entry_str}"
        else:
            # Walk-in / Manual Gate Entry: allocate slot and register entry
            slot = ParkingSlot.query.filter_by(location_id=location_id, status='FREE').first()
            if not slot:
                return False, f"❌ Parking Full! No free slots available at {location.name}.", None

            booking_ref = f"SP-WALKIN-{uuid.uuid4().hex[:6].upper()}"
            matched_booking = Booking(
                booking_reference=booking_ref,
                user_id=user.id,
                vehicle_id=vehicle.id,
                location_id=location_id,
                slot_id=slot.id,
                start_time=now_utc,
                entry_time=now_utc,
                end_time=now_utc, # updated on exit
                duration_hours=1.0,
                hourly_rate=location.hourly_rate,
                total_amount=location.hourly_rate,
                status='ACTIVE'
            )
            db.session.add(matched_booking)
            db.session.flush()

            slot.status = 'OCCUPIED'
            slot.current_vehicle_number = plate_number
            slot.current_booking_id = matched_booking.id
            location.available_slots = max(0, location.available_slots - 1)

            # Generate Invoice
            inv_num = generate_invoice_number()
            invoice = Invoice(
                invoice_number=inv_num,
                booking_id=matched_booking.id,
                user_id=user.id,
                subtotal=location.hourly_rate,
                tax=0.0,
                total_amount=location.hourly_rate,
                payment_status='PENDING',
                invoice_status='GENERATED'
            )
            db.session.add(invoice)
            db.session.flush()

            action_taken = "ENTRY_GRANTED"
            total_fee = location.hourly_rate
            message = f"✅ Registered & Granted Entry! Vehicle {plate_number} assigned to Slot {slot.slot_number}. Live Entry: {live_entry_str}"

    else: # EXIT & FEE CALCULATION
        if matched_booking:
            start_time = matched_booking.entry_time or matched_booking.start_time or now_utc
            matched_booking.exit_time = now_utc
            elapsed_seconds = (now_utc - start_time).total_seconds()
            duration_hrs = max(0.5, round(elapsed_seconds / 3600.0, 2))
            billing_hours = max(1.0, math.ceil(duration_hrs))
            
            total_fee = round(billing_hours * location.hourly_rate, 2)
            
            matched_booking.end_time = now_utc
            matched_booking.duration_hours = duration_hrs
            matched_booking.total_amount = total_fee
            matched_booking.status = 'COMPLETED'

            slot = ParkingSlot.query.get(matched_booking.slot_id)
            if slot:
                slot.status = 'FREE'
                slot.current_vehicle_number = None
                slot.current_booking_id = None

            location.available_slots = min(location.total_slots, location.available_slots + 1)

            # Update Invoice
            invoice = matched_booking.invoice
            if not invoice:
                invoice = Invoice(
                    invoice_number=generate_invoice_number(),
                    booking_id=matched_booking.id,
                    user_id=matched_booking.user_id,
                    subtotal=total_fee,
                    tax=0.0,
                    total_amount=total_fee,
                    payment_status='PAID',
                    invoice_status='GENERATED'
                )
                db.session.add(invoice)
                db.session.flush()
            else:
                invoice.subtotal = total_fee
                invoice.total_amount = total_fee
                invoice.payment_status = 'PAID'

            # Generate PDF Invoice
            try:
                generate_pdf_invoice(matched_booking, invoice)
            except Exception as pe:
                print(f"[CV Service] Invoice PDF generation notice: {pe}")

            action_taken = "EXIT_COMPLETED"
            message = f"🚗 Exit Confirmed for Vehicle {plate_number}! Stay Duration: {duration_hrs} hrs. Total Fee: ₹{total_fee}"
        else:
            # Vehicle exit with no active booking recorded: calculate baseline exit fee
            user, vehicle = get_or_create_walkin_user_and_vehicle(plate_number)
            total_fee = location.hourly_rate
            duration_hrs = 1.0
            action_taken = "EXIT_COMPLETED"
            message = f"🚗 Exit Processed for Vehicle {plate_number}. Direct Parking Fee: ₹{total_fee}"

    db.session.commit()

    # Log ANPR event
    anpr_log = ANPRLog(
        location_id=location_id,
        detected_plate=plate_number,
        confidence=confidence,
        matched_booking_id=matched_booking.id if matched_booking else None,
        action_taken=action_taken
    )
    db.session.add(anpr_log)
    
    # Activity Log
    act_log = ActivityLog(
        user_type='system',
        action=f"ANPR_{camera_type}",
        description=f"ANPR scanned {plate_number} at {location.name}. Action: {action_taken} | Live Entry: {live_entry_str} | Fee: ₹{total_fee}",
        related_id=anpr_log.id
    )
    db.session.add(act_log)
    db.session.commit()

    # Calculate fresh platform KPI metrics for real-time dashboard updates
    all_slots = ParkingSlot.query.all()
    total_slots_count = len(all_slots)
    free_slots_count = sum(1 for s in all_slots if s.status == 'FREE')
    occupied_slots_count = sum(1 for s in all_slots if s.status == 'OCCUPIED')
    reserved_slots_count = sum(1 for s in all_slots if s.status == 'RESERVED')
    active_bks_count = Booking.query.filter(Booking.status.in_(['CONFIRMED', 'ACTIVE', 'RESERVED'])).count()

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_revenue = db.session.query(db.func.sum(Invoice.total_amount))\
        .filter(Invoice.created_at >= today_start, Invoice.invoice_status != 'CANCELLED').scalar() or 0.0

    entry_time_display = live_entry_str
    exit_time_display = now_local.strftime('%b %d, %Y - %I:%M:%S %p') if (camera_type == 'EXIT') else None

    # Real-time WebSocket Alert to Admin and User Dashboards
    broadcast_anpr_event({
        'anpr_id': anpr_log.id,
        'detected_plate': plate_number,
        'location_name': location.name,
        'location_id': location.id,
        'action_taken': action_taken,
        'camera_type': camera_type,
        'entry_time': live_entry_str,
        'exit_time': exit_time_display,
        'total_fee': total_fee,
        'duration_hours': duration_hrs,
        'booking_id': matched_booking.id if matched_booking else None,
        'booking_ref': matched_booking.booking_reference if matched_booking else None,
        'slot_number': matched_booking.slot.slot_number if (matched_booking and matched_booking.slot) else None,
        'slot_id': matched_booking.slot_id if matched_booking else None,
        'user_id': user.id if user else None,
        'user_name': user.full_name if user else 'Walk-In Guest',
        'vehicle_id': vehicle.id if vehicle else None,
        'vehicle_number': vehicle.vehicle_number if vehicle else plate_number,
        'vehicle_type': vehicle.vehicle_type if vehicle else 'Car',
        'vehicle_model': vehicle.model if vehicle else 'Auto-Registered Vehicle',
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'kpis': {
            'total_slots': total_slots_count,
            'available_slots': free_slots_count,
            'occupied_slots': occupied_slots_count,
            'reserved_slots': reserved_slots_count,
            'active_bookings': active_bks_count,
            'today_revenue': float(today_revenue)
        }
    })

    if matched_booking and matched_booking.slot:
        from services.socket_service import socketio
        socketio.emit('slot_updated', {
            'location_id': location.id,
            'slot_id': matched_booking.slot.id,
            'status': matched_booking.slot.status
        })

    return True, message, {
        'anpr_id': anpr_log.id,
        'plate': plate_number,
        'user_id': user.id if user else None,
        'confidence': confidence,
        'action': action_taken,
        'status': status_code,
        'is_registered': True,
        'entry_time': entry_time_display,
        'exit_time': exit_time_display,
        'duration_hours': duration_hrs,
        'hourly_rate': location.hourly_rate,
        'total_fee': total_fee,
        'booking_id': matched_booking.id if matched_booking else None,
        'booking_reference': matched_booking.booking_reference if matched_booking else None,
        'slot_number': matched_booking.slot.slot_number if (matched_booking and matched_booking.slot) else None,
        'invoice_id': matched_booking.invoice.id if (matched_booking and matched_booking.invoice) else None
    }

def calculate_parking_fee_for_plate(location_id, plate_number, estimated_hours=1.0):
    """
    Calculates the exact parking fee for a given license plate at a location.
    Checks active booking duration if vehicle is currently parked.
    """
    plate_number = clean_plate_text(plate_number)
    if not plate_number:
        return False, "License plate number is required.", None

    location = db.session.get(ParkingLocation, location_id) if hasattr(db.session, 'get') else ParkingLocation.query.get(location_id)
    if not location:
        return False, "Invalid location ID", None

    vehicle = Vehicle.query.filter_by(vehicle_number=plate_number).first()
    active_booking = None
    if vehicle:
        active_booking = Booking.query.filter(
            Booking.vehicle_id == vehicle.id,
            Booking.location_id == location_id,
            Booking.status == 'ACTIVE'
        ).first()

    now = datetime.utcnow()
    now_local = datetime.now()
    if active_booking:
        entry_time_dt = active_booking.entry_time or active_booking.start_time or now
        elapsed = (now - entry_time_dt).total_seconds()
        duration_hrs = max(0.5, round(elapsed / 3600.0, 2))
        billing_hours = max(1.0, math.ceil(duration_hrs))
        total_fee = round(billing_hours * location.hourly_rate, 2)
        is_parked = True
        entry_time = entry_time_dt.strftime('%b %d, %Y - %I:%M:%S %p')
        slot_number = active_booking.slot.slot_number if active_booking.slot else 'N/A'
    else:
        try:
            duration_hrs = float(estimated_hours)
        except (ValueError, TypeError):
            duration_hrs = 1.0
        billing_hours = max(1.0, math.ceil(duration_hrs))
        total_fee = round(billing_hours * location.hourly_rate, 2)
        is_parked = False
        entry_time = now_local.strftime('%b %d, %Y - %I:%M:%S %p')
        slot_number = 'N/A'

    return True, f"Fee calculated for {plate_number}: ₹{total_fee}", {
        'plate': plate_number,
        'location_name': location.name,
        'hourly_rate': location.hourly_rate,
        'duration_hours': duration_hrs,
        'billing_hours': billing_hours,
        'total_fee': total_fee,
        'is_currently_parked': is_parked,
        'entry_time': entry_time,
        'slot_number': slot_number
    }
