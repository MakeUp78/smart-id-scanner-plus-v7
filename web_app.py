"""
Smart ID Scanner Plus – Web Interface (Mobile-Friendly)
=======================================================
A lightweight Flask web server that exposes the core OCR/card-detection
logic from smart_id_scanner_v7 over HTTP so the feature-set can be tested
from any mobile browser without installing the desktop application.

Usage:
    pip install flask
    python web_app.py

Then open  http://<your-machine-ip>:5000  on your phone (same Wi-Fi).
"""

import io
import os
import re
import json
import shutil
import logging
import base64
import tempfile
from typing import Optional

import cv2
import numpy as np
import pytesseract
from PIL import Image
from flask import Flask, request, jsonify, render_template

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("WebApp")

# ---------- Tesseract auto-detect (same logic as desktop app) ----------
_TESSERACT_X64 = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_TESSERACT_X86 = r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
if shutil.which("tesseract"):
    pytesseract.pytesseract.tesseract_cmd = shutil.which("tesseract")
elif os.path.exists(_TESSERACT_X64):
    pytesseract.pytesseract.tesseract_cmd = _TESSERACT_X64
elif os.path.exists(_TESSERACT_X86):
    pytesseract.pytesseract.tesseract_cmd = _TESSERACT_X86
else:
    logger.warning("Tesseract not found – OCR will fail unless it is installed.")

# ---------- RegEx patterns (same as desktop app) ----------
PATTERNS = {
    "ID Number": re.compile(r'\b([A-Z]{1,2}\s?\d{6,9})\b|\b(\d{10,14})\b'),
    "Date":      re.compile(r'\b(\d{2}[/.-]\d{2}[/.-]\d{4})\b'),
    "Name (Caps)":  re.compile(r'\b([A-Z][A-Z\s\-]{4,})\b'),
    "Name (Title)": re.compile(r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+){1,3})\b'),
}

# ---------- Core functions (ported from smart_id_scanner_v7, no Qt) ----------

def detect_card_contour(image: np.ndarray) -> Optional[np.ndarray]:
    """Detect the ID card outline and return a perspective-corrected crop."""
    img = image.copy()
    h, w = img.shape[:2]
    if h == 0 or w == 0:
        return None
    ratio = max(1.0, max(h, w) / 1000.0)
    small = cv2.resize(img, (int(w / ratio), int(h / ratio)))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 75, 75)
    edged = cv2.Canny(gray, 50, 100)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    closed = cv2.morphologyEx(edged, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(closed.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:10]
    screen_cnt = None
    img_area = small.shape[0] * small.shape[1]
    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            area = cv2.contourArea(approx)
            if img_area * 0.05 < area < img_area * 0.98:
                screen_cnt = approx
                break
    if screen_cnt is None:
        return None
    pts = screen_cnt.reshape(4, 2) * ratio
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    tl, tr, br, bl = rect
    max_width  = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    max_height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if max_width <= 0 or max_height <= 0:
        return image
    dst = np.array([[0, 0], [max_width - 1, 0],
                    [max_width - 1, max_height - 1], [0, max_height - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, M, (max_width, max_height))


def perform_ocr_sync(cv_image: np.ndarray, lang: str = "eng", psm: int = 6) -> str:
    """Run Tesseract OCR on a BGR numpy array and return the extracted text."""
    if cv_image is None:
        return ""
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
    if gray.var() > 10:
        gray = cv2.bilateralFilter(gray, 9, 75, 75)
    scale = 2
    large = cv2.resize(gray, (gray.shape[1] * scale, gray.shape[0] * scale),
                       interpolation=cv2.INTER_CUBIC)
    _, th = cv2.threshold(large, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cfg = f"--psm {psm}"
    try:
        return pytesseract.image_to_string(th, lang=lang, config=cfg).strip()
    except Exception as e:
        logger.warning("OCR failed (%s), retrying without config: %s", lang, e)
        try:
            return pytesseract.image_to_string(th, lang=lang).strip()
        except Exception as e2:
            logger.error("Fallback OCR failed: %s", e2)
            return ""


def parse_text(text: str) -> list[dict]:
    """Run regex patterns over OCR text and return a list of {field, value} dicts."""
    results = []
    for field, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            value = next((g for g in match.groups() if g), None)
            if value:
                results.append({"field": field, "value": value.strip()})
    return results


def file_to_cv2(file_storage) -> Optional[np.ndarray]:
    """Convert a Flask FileStorage object to a BGR numpy array."""
    data = file_storage.read()
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


def cv2_to_b64(img: np.ndarray) -> str:
    """Encode a BGR numpy array as a base64 PNG data-URI."""
    _, buf = cv2.imencode(".png", img)
    return "data:image/png;base64," + base64.b64encode(buf).decode()


# ---------- Flask application ----------
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload limit


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scan", methods=["POST"])
def api_scan():
    """
    POST /api/scan
    Form fields:
        image    – image file (required)
        lang     – Tesseract language code, e.g. "eng", "fra", "eng+ara"  (default: eng)
        psm      – Tesseract PSM mode 0-13 (default: 6)
        auto_detect – "true" / "false" (default: false)
    Returns JSON:
        {
            "ok": true,
            "text": "…extracted text…",
            "parsed": [{"field": "…", "value": "…"}, …],
            "preview": "data:image/png;base64,…"
        }
    """
    if "image" not in request.files or request.files["image"].filename == "":
        return jsonify({"ok": False, "error": "No image provided."}), 400

    lang        = request.form.get("lang", "eng").strip() or "eng"
    psm         = int(request.form.get("psm", 6))
    auto_detect = request.form.get("auto_detect", "false").lower() == "true"

    img = file_to_cv2(request.files["image"])
    if img is None:
        return jsonify({"ok": False, "error": "Could not decode image."}), 400

    if auto_detect:
        detected = detect_card_contour(img)
        if detected is not None:
            img = detected

    text   = perform_ocr_sync(img, lang=lang, psm=psm)
    parsed = parse_text(text)

    return jsonify({
        "ok":      True,
        "text":    text,
        "parsed":  parsed,
        "preview": cv2_to_b64(img),
    })


@app.route("/api/scan-both", methods=["POST"])
def api_scan_both():
    """
    POST /api/scan-both
    Form fields:
        recto    – front image file (required)
        verso    – back image file  (optional)
        lang     – Tesseract language code (default: eng)
        psm      – Tesseract PSM mode (default: 6)
        auto_detect – "true" / "false"
    Returns JSON with recto/verso results combined.
    """
    if "recto" not in request.files or request.files["recto"].filename == "":
        return jsonify({"ok": False, "error": "No recto image provided."}), 400

    lang        = request.form.get("lang", "eng").strip() or "eng"
    psm         = int(request.form.get("psm", 6))
    auto_detect = request.form.get("auto_detect", "false").lower() == "true"

    def process_side(file_storage):
        img = file_to_cv2(file_storage)
        if img is None:
            return None
        if auto_detect:
            detected = detect_card_contour(img)
            if detected is not None:
                img = detected
        text   = perform_ocr_sync(img, lang=lang, psm=psm)
        parsed = parse_text(text)
        return {"text": text, "parsed": parsed, "preview": cv2_to_b64(img)}

    recto_result = process_side(request.files["recto"])
    if recto_result is None:
        return jsonify({"ok": False, "error": "Could not decode recto image."}), 400

    verso_result = None
    if "verso" in request.files and request.files["verso"].filename != "":
        verso_result = process_side(request.files["verso"])

    return jsonify({
        "ok":    True,
        "recto": recto_result,
        "verso": verso_result,
    })


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Smart ID Scanner – Web Interface")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Bind address (default: 0.0.0.0 – accessible on LAN)")
    parser.add_argument("--port", type=int, default=5000,
                        help="Port number (default: 5000)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable Flask debug mode")
    args = parser.parse_args()

    print(f"\n  Smart ID Scanner Web Interface")
    print(f"  Open http://localhost:{args.port} in your browser")
    print(f"  On the same Wi-Fi, open http://<your-IP>:{args.port} on your phone\n")
    app.run(host=args.host, port=args.port, debug=args.debug)
