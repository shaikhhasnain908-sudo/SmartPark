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

# Recognized Indian State and Union Territory RTO Prefix Codes (plus old & special series)
INDIAN_STATE_CODES = {
    'AN', 'AP', 'AR', 'AS', 'BR', 'CG', 'CH', 'DD', 'DL', 'DN',
    'GA', 'GJ', 'HR', 'HP', 'JH', 'JK', 'KA', 'KL', 'LA', 'LD',
    'MB', 'MH', 'ML', 'MN', 'MP', 'MZ', 'NL', 'OD', 'OR', 'PB', 'PY',
    'RJ', 'SK', 'TN', 'TR', 'TS', 'UK', 'UA', 'UP', 'US', 'WB', 'BH'
}

LETTER_TO_DIGIT = {
    'O': '0', 'Q': '0', 'D': '0', 'I': '1', 'L': '1', 'Z': '2',
    'E': '3', 'A': '4', 'S': '5', 'G': '6', 'T': '7', 'B': '8'
}

DIGIT_TO_LETTER = {
    '0': 'O', '1': 'I', '2': 'Z', '3': 'E', '4': 'A', '5': 'S',
    '6': 'G', '7': 'T', '8': 'B'
}

STATE_FIRST_LETTER_CORRECTION = {
    '7': 'T', '1': 'I', '0': 'D', '6': 'G', 'V': 'U'
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
    Sanitize and extract clean uppercase license plate string (e.g. TN03MF4477, MH12DE1433, KA81T9874, DL01CA1111).
    Handles real-world conditions:
      - 2-line plates and tokens in scene
      - Stripping leading IND / 1ND / ID hologram badges
      - State prefix recovery & single-digit RTO padding (TN 3 -> TN03)
      - Delhi special vehicle series (DL 3C AY 5244 -> DL03CAY5244)
      - Bharat Series (22BH1234AA)
      - OCR confusion correction (O->0, I->1, S->5, B->8, 7N->TN)
      - Filtering car brand badges & scene noise
    """
    if not raw_text:
        return ""

    raw_str = str(raw_text).upper().strip()

    # 1. Search for State Code as anchor inside token sequence
    tokens = re.findall(r'[A-Za-z0-9]+', raw_str)
    for i, tok in enumerate(tokens):
        st = None
        rem = ''
        if len(tok) >= 2 and tok[:2] in INDIAN_STATE_CODES:
            st = tok[:2]
            rem = tok[2:]
        elif len(tok) >= 4 and tok[:2] in {'EN', 'IN', 'ID'} and tok[2:4] in INDIAN_STATE_CODES:
            st = tok[2:4]
            rem = tok[4:]
        elif len(tok) >= 2 and tok[0] in STATE_FIRST_LETTER_CORRECTION and (STATE_FIRST_LETTER_CORRECTION[tok[0]] + tok[1]) in INDIAN_STATE_CODES:
            st = STATE_FIRST_LETTER_CORRECTION[tok[0]] + tok[1]
            rem = tok[2:]
        elif i + 1 < len(tokens) and tok in {'IND', '1ND', 'ID', 'IN'} and len(tokens[i+1]) >= 2 and tokens[i+1][:2] in INDIAN_STATE_CODES:
            continue

        if st:
            following = [rem] if rem else []
            following.extend(tokens[i+1 : i+6])
            joined_after = ''.join(following)
            if len(joined_after) >= 2:
                c0 = '0' if joined_after[0] in {'O', 'o', 'Q', 'D'} else ('1' if joined_after[0] in {'I', 'i', 'l', 'L'} else joined_after[0])
                c1 = '0' if joined_after[1] in {'O', 'o', 'Q', 'D'} else ('1' if joined_after[1] in {'I', 'i', 'l', 'L'} else joined_after[1])
                joined_after = c0 + c1 + joined_after[2:]

            # Format 1: Glitched 3-digit RTO with leading zero (e.g. '037MF4477' -> '03' + 'MF' + '4477')
            m_g0 = re.search(r'0([0-9])[0-9]\s*([A-Z]{1,3})\s*([0-9]{3,4})', joined_after)
            if m_g0:
                return f"{st}0{m_g0.group(1)}{m_g0.group(2)}{m_g0.group(3)}"

            # Format 2: Standard Indian [RTO: 1-2 digits] [Series: 1-3 letters] [Number: 3-4 digits]
            m_std = re.search(r'([0-9]{1,2})\s*([A-Z]{1,3})\s*([0-9]{3,4})', joined_after)
            if m_std:
                rto = m_std.group(1)
                if len(rto) == 1:
                    rto = '0' + rto
                return f"{st}{rto}{m_std.group(2)}{m_std.group(3)}"

            # Format 3: Delhi Special [RTO: 1-2 digits + 1 letter] [Series: 1-2 letters] [Number: 3-4 digits]
            m_dl = re.search(r'([0-9]{1,2}[A-Z])\s*([A-Z]{1,2})\s*([0-9]{3,4})', joined_after)
            if m_dl:
                rto_dl = m_dl.group(1)
                if len(rto_dl) == 2 and rto_dl[0].isdigit():
                    rto_dl = '0' + rto_dl
                return f"{st}{rto_dl}{m_dl.group(2)}{m_dl.group(3)}"

            # Format 4: Pure numeric RTO + 4-digit Number (no series letters e.g. MH 02 1234)
            m_num = re.search(r'([0-9]{1,2})\s*([0-9]{4})', joined_after)
            if m_num:
                rto = m_num.group(1)
                if len(rto) == 1:
                    rto = '0' + rto
                return f"{st}{rto}{m_num.group(2)}"

            # Format 5: Glitched 3-digit without leading zero (e.g. '120DE1433' -> '12' + 'DE' + '1433')
            m_glitch = re.search(r'([0-9]{2})[0-9]\s*([A-Z]{1,3})\s*([0-9]{3,4})', joined_after)
            if m_glitch:
                return f"{st}{m_glitch.group(1)}{m_glitch.group(2)}{m_glitch.group(3)}"

            # Format 6: Short number fallback (2-3 digits)
            m_short = re.search(r'([0-9]{1,2})\s*([A-Z]{0,3})\s*([0-9]{2,4})', joined_after)
            if m_short:
                rto = m_short.group(1)
                if len(rto) == 1:
                    rto = '0' + rto
                return f"{st}{rto}{m_short.group(2)}{m_short.group(3)}"

    # 2. Compact string fallback search
    cleaned = re.sub(r'[^A-Za-z0-9]', '', raw_str)
    cleaned = re.sub(r'^(IND|1ND|ID)', '', cleaned)
    if cleaned.startswith('IN') and len(cleaned) >= 8 and cleaned[2:4] in INDIAN_STATE_CODES:
        cleaned = cleaned[2:]

    # Bharat Series
    bh_match = re.search(r'([0-9]{2}BH[0-9]{4}[A-Z]{1,2})', cleaned)
    if bh_match:
        return bh_match.group(1)

    # Standard Regex with series letters first
    for m in re.finditer(r'([A-Z]{2})([0-9]{1,2})([A-Z]{1,3})([0-9]{3,4})', cleaned):
        st = m.group(1)
        if st in INDIAN_STATE_CODES:
            rto = m.group(2)
            if len(rto) == 1:
                rto = f"0{rto}"
            return f"{st}{rto}{m.group(3)}{m.group(4)}"

    # Standard Regex without series
    for m in re.finditer(r'([A-Z]{2})([0-9]{1,2})([0-9]{4})', cleaned):
        st = m.group(1)
        if st in INDIAN_STATE_CODES:
            rto = m.group(2)
            if len(rto) == 1:
                rto = f"0{rto}"
            return f"{st}{rto}{m.group(3)}"

    # Sliding window with OCR confusion correction (e.g. 'TNO3MF447S' -> 'TN03MF4475')
    for length in [10, 9, 8, 11, 7]:
        for i in range(0, max(1, len(cleaned) - length + 1)):
            chunk = cleaned[i:i+length]
            s0 = STATE_FIRST_LETTER_CORRECTION.get(chunk[0], chunk[0])
            s1 = chunk[1]
            st = s0 + s1
            if st in INDIAN_STATE_CODES:
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
                    cand = f"{st}{rto}{series}{tail_digits}"
                    if re.match(r'^[A-Z]{2}[0-9]{2}[A-Z]{0,3}[0-9]{2,4}$', cand):
                        return cand

    # Reconstruct Missing First State Letter (e.g., 'N03MF4477' -> 'TN03MF4477')
    miss_first = re.search(r'([A-Z])([0-9]{1,2})([A-Z]{1,3})([0-9]{3,4})', cleaned)
    if miss_first:
        second_char = miss_first.group(1)
        rto = miss_first.group(2)
        if len(rto) == 1:
            rto = f"0{rto}"
        series = miss_first.group(3)
        num = miss_first.group(4)
        if second_char in STATE_SECOND_LETTER_MAP:
            rec_st = STATE_SECOND_LETTER_MAP[second_char][0]
            return f"{rec_st}{rto}{series}{num}"

    # General alphanumeric fallback (rejecting banned brand names)
    banned = {'HONDA', 'HYUNDAI', 'SUZUKI', 'MARUTI', 'TOYOTA', 'MAHINDRA', 'TATA', 'FORD', 'DIESEL', 'PETROL', 'TURBO', 'CAMERA', 'SMART', 'PLATE'}
    if 5 <= len(cleaned) <= 12 and not any(b in cleaned for b in banned):
        if re.search(r'[A-Z]', cleaned) and re.search(r'[0-9]', cleaned):
            return cleaned

    return ""

def sort_results_reading_order(results):
    """
    Sorts OCR bounding boxes in natural 2-line reading order (Top-to-Bottom, Left-to-Right).
    Solves 2-line motorcycle, SUV, and commercial plates where line 1 is above line 2.
    """
    if not results:
        return []
    items = []
    for r in results:
        box = r[0]
        try:
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            yc = sum(ys) / len(ys)
            xc = sum(xs) / len(xs)
            h = max(ys) - min(ys)
            items.append({'res': r, 'xc': xc, 'yc': yc, 'h': max(h, 12)})
        except Exception:
            items.append({'res': r, 'xc': 0, 'yc': 0, 'h': 15})

    items.sort(key=lambda x: x['yc'])

    # Group into lines based on vertical proximity
    lines = []
    for it in items:
        placed = False
        for line in lines:
            avg_y = sum([x['yc'] for x in line]) / len(line)
            avg_h = sum([x['h'] for x in line]) / len(line)
            if abs(it['yc'] - avg_y) < avg_h * 0.65:
                line.append(it)
                placed = True
                break
        if not placed:
            lines.append([it])

    # Sort each line left-to-right
    sorted_res = []
    for line in lines:
        line.sort(key=lambda x: x['xc'])
        for it in line:
            sorted_res.append(it['res'])

    return sorted_res

def perform_anpr_ocr(img):
    """
    Real-world ANPR OCR pipeline optimized for high speed (<1.2s) and high accuracy.
    Evaluates:
      1. Full Frame Normalized (max_dim=1024) with Two-Line Natural Reading Order
      2. Contrast-Enhanced Center/Bumper Region (CLAHE 3.0)
    """
    if img is None:
        return "", 0.0, (0, 0, 0, 0)

    reader = get_ocr_reader()
    if not reader:
        return "", 0.0, (0, 0, img.shape[1], img.shape[0])

    orig_h, orig_w = img.shape[:2]

    # Normalize image resolution to max dimension 1024px for lightning-fast execution (<1.2s)
    max_dim = max(orig_h, orig_w)
    if max_dim > 1024:
        scale = 1024.0 / float(max_dim)
        img_norm = cv2.resize(img, (int(orig_w * scale), int(orig_h * scale)), interpolation=cv2.INTER_AREA)
    else:
        scale = 1.0
        img_norm = img

    nh, nw = img_norm.shape[:2]
    candidates = []

    def evaluate_ocr_results(ocr_results, offset=(0, 0)):
        if not ocr_results:
            return None
        sorted_results = sort_results_reading_order(ocr_results)

        # 1. Check individual tokens first for direct, high-confidence single-line plate detection
        for res in sorted_results:
            raw_t = res[1].strip()
            if any(w in raw_t.upper() for w in ['ALIGN', 'RECEIPT', 'BREAKDOWN', 'ENTER', 'CONFIRM', 'REGISTER', 'GRANT', 'ENTRY', 'CANCEL', 'BUTTON', 'E.G.', 'EG', 'CAMERA', 'CALCULATE', 'AUTO-SCAN']):
                continue
            c_tok = clean_plate_text(raw_t)
            if c_tok and len(c_tok) >= 7 and c_tok[:2] in INDIAN_STATE_CODES:
                score = 3.5 + float(res[2])
                return (c_tok, score, float(res[2]), (int(offset[0] / scale), int(offset[1] / scale), orig_w, orig_h))

        # 2. Check sliding window across adjacent tokens (e.g. ['MH', '12', 'DE', '1433'])
        n_tok = len(sorted_results)
        for w_size in range(2, min(5, n_tok + 1)):
            for start in range(n_tok - w_size + 1):
                window = sorted_results[start : start + w_size]
                w_str = " ".join([t[1] for t in window])
                if any(w in w_str.upper() for w in ['ALIGN', 'RECEIPT', 'BREAKDOWN', 'REGISTER', 'GRANT', 'ENTRY', 'BUTTON', 'E.G.', 'EG']):
                    continue
                c_win = clean_plate_text(w_str)
                if c_win and len(c_win) >= 7 and c_win[:2] in INDIAN_STATE_CODES:
                    avg_c = sum([float(t[2]) for t in window]) / float(w_size)
                    score = avg_c + 2.0
                    return (c_win, score, avg_c, (int(offset[0] / scale), int(offset[1] / scale), orig_w, orig_h))

        # 3. Check joined raw text across reading order
        clean_tokens = [r[1] for r in sorted_results if not any(w in r[1].upper() for w in ['ALIGN', 'RECEIPT', 'BREAKDOWN', 'REGISTER', 'GRANT', 'ENTRY', 'BUTTON', 'E.G.', 'EG'])]
        if clean_tokens:
            joined_raw = " ".join(clean_tokens)
            c_joined = clean_plate_text(joined_raw)
            if c_joined and len(c_joined) >= 6:
                score = 1.8
                if c_joined[:2] in INDIAN_STATE_CODES:
                    score += 0.8
                if re.search(r'[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{3,4}', c_joined) or re.search(r'[0-9]{2}BH', c_joined):
                    score += 1.0
                return (c_joined, score, 0.95, (int(offset[0] / scale), int(offset[1] / scale), orig_w, orig_h))

        # 4. Individual tokens fallback
        for res in sorted_results:
            raw_t = res[1].strip()
            if any(w in raw_t.upper() for w in ['ALIGN', 'RECEIPT', 'BREAKDOWN', 'REGISTER', 'GRANT', 'ENTRY', 'BUTTON', 'E.G.', 'EG']):
                continue
            c_tok = clean_plate_text(raw_t)
            if c_tok and len(c_tok) >= 6:
                score = float(res[2]) + 0.5
                if c_tok[:2] in INDIAN_STATE_CODES:
                    score += 0.6
                candidates.append((c_tok, score, float(res[2]), (int(offset[0] / scale), int(offset[1] / scale), orig_w, orig_h)))

        return None

    try:
        # Pass 1: Full Frame Normalized with standard robust OCR parameters
        res1 = reader.readtext(img_norm)
        best_p1 = evaluate_ocr_results(res1, offset=(0, 0))
        if best_p1 and best_p1[1] >= 2.0:
            return best_p1[0], best_p1[2], best_p1[3]
        if best_p1:
            candidates.append(best_p1)
    except Exception as e:
        print(f"[CV Service] OCR Pass 1 warning: {e}")

    # Pass 2: Contrast-Enhanced Center / Bumper ROI
    try:
        cy1 = int(nh * 0.10)
        cy2 = int(nh * 0.90)
        cx1 = int(nw * 0.08)
        cx2 = int(nw * 0.92)
        center_crop = img_norm[cy1:cy2, cx1:cx2]

        if center_crop.size > 0:
            gray = cv2.cvtColor(center_crop, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            enhanced_gray = clahe.apply(gray)

            res2 = reader.readtext(enhanced_gray)
            best_p2 = evaluate_ocr_results(res2, offset=(cx1, cy1))
            if best_p2 and best_p2[1] >= 2.0:
                return best_p2[0], best_p2[2], best_p2[3]
            if best_p2:
                candidates.append(best_p2)
    except Exception as e:
        print(f"[CV Service] OCR Pass 2 warning: {e}")

    # Return best candidate found across passes
    if candidates:
        best = max(candidates, key=lambda x: x[1])
        return best[0], best[2], best[3]

    return "", 0.0, (0, 0, orig_w, orig_h)

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
