# smart_id_scanner_plus_v7.py
"""
Smart ID Scanner Plus (V7 - PDF Text Control)
- Modern PyQt6 UI
- Light / Dark theme toggle
- Manual crop via OpenCV ROI
- Export to Word and PDF
- Auto-save last session (images + OCR settings)
- Uses pytesseract for OCR; Pillow for image handling; python-docx for docx export

NEW FEATURES (V7):
- PDF Export Options: Control whether to include extracted text in PDF
- 3 Modes: Full Text, Short Text, No Text
"""

import sys
import os
import json
import tempfile
import shutil
import logging
import re
import csv
from datetime import datetime
from typing import Optional, Tuple, List

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.shared import Cm
from PyQt6 import QtCore, QtGui, QtWidgets

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SmartIDPlus")

# ---------- Tesseract autodetect ----------
TESSERACT_CMD_X64 = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSERACT_CMD_X86 = r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
if shutil.which("tesseract"):
    pytesseract.pytesseract.tesseract_cmd = shutil.which("tesseract")
elif os.path.exists(TESSERACT_CMD_X64):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD_X64
elif os.path.exists(TESSERACT_CMD_X86):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD_X86
else:
    logger.warning("Tesseract not found. OCR will likely fail unless installed.")

# ---------- Config / Auto-save ----------
APP_DIR = os.path.join(os.path.expanduser("~"), ".smart_id_scanner_plus")
os.makedirs(APP_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LAST_RECTO = os.path.join(APP_DIR, "last_recto.png")
LAST_VERSO = os.path.join(APP_DIR, "last_verso.png")

DEFAULT_CONFIG = {
    "ocr_lang": "eng",
    "psm": 6,
    "theme": "light",
    "word_separate_pages": False,
    "pdf_text_mode": "full"  # NEW: "full", "short", "none"
}

# ---------- RegEx Patterns for Parsing ----------
PATTERNS = {
    "ID Number": re.compile(r'\b([A-Z]{1,2}\s?\d{6,9})\b|\b(\d{10,14})\b'),
    "Date": re.compile(r'\b(\d{2}[/.-]\d{2}[/.-]\d{4})\b'),
    "Name (Caps)": re.compile(r'\b([A-Z][A-Z\s\-]{4,})\b'),
    "Name (Title)": re.compile(r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+){1,3})\b')
}


def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        logger.info("Config saved.")
    except Exception as e:
        logger.warning("Could not save config: %s", e)

def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception as e:
            logger.warning("Failed to load config, using defaults: %s", e)
    return DEFAULT_CONFIG.copy()

# ---------- Utilities ----------
def cv2_to_qpixmap(cv_img: Optional[np.ndarray]) -> QtGui.QPixmap:
    if cv_img is None:
        return QtGui.QPixmap()
    h, w = cv_img.shape[:2]
    if h == 0 or w == 0:
        return QtGui.QPixmap()
    if cv_img.ndim == 2:
        fmt = QtGui.QImage.Format.Format_Grayscale8
        qimg = QtGui.QImage(cv_img.data, w, h, cv_img.strides[0], fmt)
    else:
        rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        qimg = QtGui.QImage(rgb.data, w, h, rgb.strides[0], QtGui.QImage.Format.Format_RGB888)
    return QtGui.QPixmap.fromImage(qimg)

def save_image_file(path: str, cv_img: np.ndarray):
    pil = Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))
    pil.save(path)

# ---------- OCR ----------
def perform_ocr_sync(cv_image: np.ndarray, lang: str = 'eng', psm: int = 6) -> str:
    if cv_image is None:
        return ""
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
    if cv_image.var() > 10:
        gray = cv2.bilateralFilter(gray, 9, 75, 75)
    
    scale_factor = 2
    large = cv2.resize(gray, (gray.shape[1]*scale_factor, gray.shape[0]*scale_factor),
                       interpolation=cv2.INTER_CUBIC)
    
    _, th = cv2.threshold(large, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    config = f'--psm {psm}'
    try:
        text = pytesseract.image_to_string(th, lang=lang, config=config)
        return text.strip()
    except Exception as e:
        logger.exception("OCR failed: %s", e)
        try:
            return pytesseract.image_to_string(th, lang=lang).strip()
        except Exception as e2:
            logger.exception("Fallback OCR failed: %s", e2)
            return ""

class OCRWorker(QtCore.QThread):
    finished = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(str)
    def __init__(self, image: np.ndarray, lang: str = 'eng', psm: int = 6):
        super().__init__()
        self.image = image
        self.lang = lang
        self.psm = psm
    def run(self):
        try:
            txt = perform_ocr_sync(self.image, lang=self.lang, psm=self.psm)
            self.finished.emit(txt)
        except Exception as e:
            self.error.emit(str(e))

# ---------- Card detection ----------
def detect_card_contour(image: np.ndarray, debug: bool = False) -> Optional[np.ndarray]:
    img = image.copy()
    h, w = img.shape[:2]
    if h == 0 or w == 0:
        return None
    ratio = max(1.0, max(h, w) / 1000.0)
    small = cv2.resize(img, (int(w/ratio), int(h/ratio)))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 75, 75)
    edged = cv2.Canny(gray, 50, 100)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    closed = cv2.morphologyEx(edged, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(closed.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:10]
    screenCnt = None
    img_area = small.shape[0] * small.shape[1]
    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            area = cv2.contourArea(approx)
            if area > (img_area * 0.05) and area < (img_area * 0.98):
                screenCnt = approx
                break
    if screenCnt is None:
        return None
    pts = screenCnt.reshape(4,2) * ratio
    rect = np.zeros((4,2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    (tl, tr, br, bl) = rect
    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxWidth = int(max(widthA, widthB))
    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxHeight = int(max(heightA, heightB))
    if maxWidth <= 0 or maxHeight <= 0:
        return image
    dst = np.array([
        [0,0],
        [maxWidth-1, 0],
        [maxWidth-1, maxHeight-1],
        [0, maxHeight-1]
    ], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    return warped

# ---------- UI Widgets ----------
class ImageLabel(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(320, 220)
        self._pixmap = QtGui.QPixmap()
        self.setStyleSheet("""
            QLabel {
                border-radius: 10px;
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(255,255,255,0.6), stop:1 rgba(240,240,240,0.6));
                border: 1px solid rgba(0,0,0,0.08);
            }
        """)
    def setPixmap(self, pixmap: QtGui.QPixmap):
        self._pixmap = pixmap
        self._update_scaled()
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled()
    def _update_scaled(self):
        if self._pixmap.isNull():
            super().setPixmap(QtGui.QPixmap())
            return
        sw, sh = self.width(), self.height()
        scaled = self._pixmap.scaled(sw, sh, QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation)
        super().setPixmap(scaled)

class CardSideWidget(QtWidgets.QWidget):
    ocr_started = QtCore.pyqtSignal()
    ocr_finished = QtCore.pyqtSignal()
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.cv_image: Optional[np.ndarray] = None
        self.ocr_worker: Optional[OCRWorker] = None
        self.setup_ui()

    def setup_ui(self):
        self.setContentsMargins(6,6,6,6)
        layout = QtWidgets.QVBoxLayout(self)
        header = QtWidgets.QLabel(self.title)
        header.setStyleSheet("font-weight:600; font-size:14px;")
        layout.addWidget(header)
        self.image_label = ImageLabel()
        layout.addWidget(self.image_label, 3)

        img_ops_row = QtWidgets.QHBoxLayout()
        self.btn_rotate_l = QtWidgets.QPushButton("Rotate L")
        self.btn_rotate_r = QtWidgets.QPushButton("Rotate R")
        self.btn_sharpen = QtWidgets.QPushButton("Sharpen")
        self.btn_contrast = QtWidgets.QPushButton("Contrast")
        for b in (self.btn_rotate_l, self.btn_rotate_r, self.btn_sharpen, self.btn_contrast):
            b.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            img_ops_row.addWidget(b)
        layout.addLayout(img_ops_row)
        
        main_ops_row = QtWidgets.QHBoxLayout()
        self.btn_load = QtWidgets.QPushButton("Load")
        self.btn_detect = QtWidgets.QPushButton("Auto Detect")
        self.btn_manual = QtWidgets.QPushButton("Manual Crop")
        self.btn_ocr = QtWidgets.QPushButton("OCR")
        for b in (self.btn_load, self.btn_detect, self.btn_manual, self.btn_ocr):
            b.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            main_ops_row.addWidget(b)
        layout.addLayout(main_ops_row)
        
        layout.addWidget(QtWidgets.QLabel("Extracted Text:"))
        self.text_edit = QtWidgets.QPlainTextEdit()
        self.text_edit.setMaximumHeight(160)
        self.text_edit.setPlaceholderText("Detected text will appear here...")
        layout.addWidget(self.text_edit, 2)
        
        self.btn_load.clicked.connect(self.load_image)
        self.btn_detect.clicked.connect(self.auto_detect)
        self.btn_manual.clicked.connect(self.manual_crop)
        self.btn_ocr.clicked.connect(self._start_ocr_clicked)
        self.btn_rotate_l.clicked.connect(self.rotate_left)
        self.btn_rotate_r.clicked.connect(self.rotate_right)
        self.btn_sharpen.clicked.connect(self.sharpen_image)
        self.btn_contrast.clicked.connect(self.increase_contrast)

    def _check_image(self) -> bool:
        if self.cv_image is None:
            QtWidgets.QMessageBox.warning(self, "Warning", "Load an image first.")
            return False
        return True

    def _update_image_display(self):
        self.image_label.setPixmap(cv2_to_qpixmap(self.cv_image))
        self.text_edit.clear()

    def rotate_left(self):
        if not self._check_image(): return
        self.cv_image = cv2.rotate(self.cv_image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        self._update_image_display()

    def rotate_right(self):
        if not self._check_image(): return
        self.cv_image = cv2.rotate(self.cv_image, cv2.ROTATE_90_CLOCKWISE)
        self._update_image_display()

    def sharpen_image(self):
        if not self._check_image(): return
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        self.cv_image = cv2.filter2D(self.cv_image, -1, kernel)
        self._update_image_display()

    def increase_contrast(self):
        if not self._check_image(): return
        self.cv_image = cv2.convertScaleAbs(self.cv_image, alpha=1.2, beta=5)
        self._update_image_display()

    def load_image(self) -> bool:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, f"Select {self.title}", "", "Images (*.png *.jpg *.jpeg *.bmp *.tiff)")
        if not path:
            return False
        try:
            img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("Could not read image.")
            self.cv_image = img
            self._update_image_display()
            QtWidgets.QMessageBox.information(self, "Loaded", f"{self.title} loaded.")
            return True
        except Exception as e:
            logger.exception("Load error")
            QtWidgets.QMessageBox.critical(self, "Load Error", str(e))
            return False

    def auto_detect(self) -> bool:
        if not self._check_image(): return False
        warped = detect_card_contour(self.cv_image, debug=False)
        if warped is None:
            QtWidgets.QMessageBox.information(self, "Not found", "Could not auto-detect card; try manual crop.")
            return False
        self.cv_image = warped
        self._update_image_display()
        QtWidgets.QMessageBox.information(self, "Detected", "Card detected and cropped.")
        return True

    def manual_crop(self):
        if not self._check_image(): return
        tmp = self.cv_image.copy()
        title = f"Manual crop - {self.title} (draw rectangle then press Enter/Space)"
        cv2.namedWindow(title, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(title, 1200, 800)
        cv2.imshow(title, tmp)
        roi = cv2.selectROI(title, tmp, showCrosshair=True, fromCenter=False)
        cv2.destroyWindow(title)
        if roi and roi != (0,0,0,0):
            x, y, w, h = map(int, roi)
            cropped = tmp[y:y+h, x:x+w]
            if cropped.size == 0:
                QtWidgets.QMessageBox.warning(self, "Warning", "Invalid selection.")
                return
            self.cv_image = cropped
            self._update_image_display()
            QtWidgets.QMessageBox.information(self, "Cropped", "Manual crop applied.")

    def _start_ocr_clicked(self):
        self.ocr_started.emit()

    def start_ocr_worker(self, lang: str, psm: int):
        if not self._check_image():
            self.ocr_finished.emit()
            return
        
        self.btn_ocr.setEnabled(False)
        self.ocr_worker = OCRWorker(self.cv_image.copy(), lang=lang, psm=psm)
        self.ocr_worker.finished.connect(self._on_ocr_finished)
        self.ocr_worker.error.connect(self._on_ocr_error)
        self.ocr_worker.start()

    def _on_ocr_finished(self, text: str):
        self.text_edit.setPlainText(text or "(No text found)")
        self.btn_ocr.setEnabled(True)
        self.ocr_finished.emit()
        QtWidgets.QMessageBox.information(self, "OCR", f"OCR finished for {self.title}")

    def _on_ocr_error(self, msg: str):
        self.btn_ocr.setEnabled(True)
        self.ocr_finished.emit()
        QtWidgets.QMessageBox.critical(self, "OCR Error", msg)

    def get_text(self) -> str:
        return self.text_edit.toPlainText().strip()

    def has_image(self) -> bool:
        return self.cv_image is not None

# ---------- Main Window ----------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart ID Scanner Plus V7")
        self.resize(1400, 950)
        self.config = load_config()
        self.ocr_lang = self.config.get("ocr_lang", "eng")
        self.psm = int(self.config.get("psm", 6))
        self.theme = self.config.get("theme", "light")
        self.word_separate_pages = bool(self.config.get("word_separate_pages", False))
        self.pdf_text_mode = self.config.get("pdf_text_mode", "full")  # NEW
        
        self.active_workers = 0
        self.setup_ui()
        self.load_last_session()
        self.apply_theme(self.theme)

    def setup_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main = QtWidgets.QVBoxLayout(central)
        header = QtWidgets.QLabel("Smart ID Scanner Plus V7 – PDF Options")
        header.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet("font-size:20px; font-weight:700; padding:10px;")
        main.addWidget(header)
        
        split = QtWidgets.QHBoxLayout()
        self.recto = CardSideWidget("Recto (Front)")
        self.verso = CardSideWidget("Verso (Back)")
        split.addWidget(self.recto, 1)
        split.addWidget(self.verso, 1)
        main.addLayout(split)
        
        table_header = QtWidgets.QLabel("Parsed Information (Experimental)")
        table_header.setStyleSheet("font-size:14px; font-weight:600; padding-top:10px;")
        main.addWidget(table_header)
        self.parsed_table = QtWidgets.QTableWidget()
        self.parsed_table.setColumnCount(2)
        self.parsed_table.setHorizontalHeaderLabels(["Field", "Value"])
        self.parsed_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.parsed_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.parsed_table.setMaximumHeight(180)
        self.parsed_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        main.addWidget(self.parsed_table)

        controls = QtWidgets.QHBoxLayout()
        self.btn_load_both = QtWidgets.QPushButton("Load Both")
        self.btn_parse = QtWidgets.QPushButton("Parse Data") 
        self.btn_export_merged_img = QtWidgets.QPushButton("Export Merged Image")
        self.btn_export_json = QtWidgets.QPushButton("Export .json") 
        self.btn_export_csv = QtWidgets.QPushButton("Export .csv") 
        self.btn_export_doc = QtWidgets.QPushButton("Export .docx")
        self.btn_export_pdf = QtWidgets.QPushButton("Export .pdf")
        self.btn_register = QtWidgets.QPushButton("Register (Save to Documents)")
        self.btn_clear = QtWidgets.QPushButton("Clear")
        self.btn_settings = QtWidgets.QPushButton("Settings")
        
        self.all_buttons = [
            self.btn_load_both, self.btn_parse, 
            self.btn_export_merged_img,
            self.btn_export_json, self.btn_export_csv,
            self.btn_export_doc, self.btn_export_pdf, self.btn_register,
            self.btn_clear, self.btn_settings
        ]

        for b in self.all_buttons:
            b.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            controls.addWidget(b)
        main.addLayout(controls)
        
        self.btn_load_both.clicked.connect(self.load_both_sides)
        self.btn_export_doc.clicked.connect(self.export_to_word)
        self.btn_export_pdf.clicked.connect(self.export_to_pdf)
        self.btn_register.clicked.connect(self.register_document)
        self.btn_clear.clicked.connect(self.clear_all)
        self.btn_settings.clicked.connect(self.show_settings)
        self.btn_parse.clicked.connect(self.parse_data)
        self.btn_export_json.clicked.connect(self.export_json)
        self.btn_export_csv.clicked.connect(self.export_csv)
        self.btn_export_merged_img.clicked.connect(self.export_merged_image)

        self.recto.ocr_started.connect(lambda: self._on_ocr_start(self.recto))
        self.verso.ocr_started.connect(lambda: self._on_ocr_start(self.verso))
        self.recto.ocr_finished.connect(lambda: self._on_ocr_finish(self.recto))
        self.verso.ocr_finished.connect(lambda: self._on_ocr_finish(self.verso))
        self.recto.ocr_started.connect(lambda: self.recto.start_ocr_worker(self.ocr_lang, self.psm))
        self.verso.ocr_started.connect(lambda: self.verso.start_ocr_worker(self.ocr_lang, self.psm))

    def _on_ocr_start(self, widget):
        self.active_workers += 1
        self._set_enabled(False)

    def _on_ocr_finish(self, widget):
        self.active_workers = max(0, self.active_workers - 1)
        if self.active_workers == 0:
            self._set_enabled(True)
            self.auto_save_session()
            self.parse_data()

    def _set_enabled(self, enabled: bool):
        for w in self.all_buttons:
            w.setEnabled(enabled)
            
        for child in (self.recto, self.verso):
            for btn in (child.btn_load, child.btn_detect, child.btn_manual, 
                        child.btn_rotate_l, child.btn_rotate_r, 
                        child.btn_sharpen, child.btn_contrast):
                btn.setEnabled(enabled)

        if enabled:
            if not (self.recto.ocr_worker and self.recto.ocr_worker.isRunning()):
                self.recto.btn_ocr.setEnabled(True)
            if not (self.verso.ocr_worker and self.verso.ocr_worker.isRunning()):
                self.verso.btn_ocr.setEnabled(True)

    def auto_save_session(self):
        try:
            if self.recto.has_image():
                save_image_file(LAST_RECTO, self.recto.cv_image)
            if self.verso.has_image():
                save_image_file(LAST_VERSO, self.verso.cv_image)
                
            self.config.update({
                "ocr_lang": self.ocr_lang, 
                "psm": self.psm, 
                "theme": self.theme,
                "word_separate_pages": self.word_separate_pages,
                "pdf_text_mode": self.pdf_text_mode  # NEW
            })
            save_config(self.config)
            logger.info("Session auto-saved.")
        except Exception as e:
            logger.warning("Auto-save failed: %s", e)

    def load_last_session(self):
        try:
            if os.path.exists(LAST_RECTO):
                img = cv2.imdecode(np.fromfile(LAST_RECTO, dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    self.recto.cv_image = img
                    self.recto.image_label.setPixmap(cv2_to_qpixmap(img))
            if os.path.exists(LAST_VERSO):
                img = cv2.imdecode(np.fromfile(LAST_VERSO, dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    self.verso.cv_image = img
                    self.verso.image_label.setPixmap(cv2_to_qpixmap(img))
            logger.info("Last session loaded if available.")
        except Exception as e:
            logger.warning("Load last session failed: %s", e)

    def load_both_sides(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Select front then back", "", "Images (*.png *.jpg *.jpeg *.bmp *.tiff)")
        if not paths:
            return
        if len(paths) < 1:
            return
        try:
            if len(paths) >= 1:
                img1 = cv2.imdecode(np.fromfile(paths[0], dtype=np.uint8), cv2.IMREAD_COLOR)
                if img1 is not None:
                    self.recto.cv_image = img1
                    self.recto.image_label.setPixmap(cv2_to_qpixmap(img1))
                    self.recto.text_edit.clear()
            if len(paths) >= 2:
                img2 = cv2.imdecode(np.fromfile(paths[1], dtype=np.uint8), cv2.IMREAD_COLOR)
                if img2 is not None:
                    self.verso.cv_image = img2
                    self.verso.image_label.setPixmap(cv2_to_qpixmap(img2))
                    self.verso.text_edit.clear()
            QtWidgets.QMessageBox.information(self, "Loaded", "Selected images loaded.")
            self.parsed_table.setRowCount(0)
            self.auto_save_session()
        except Exception as e:
            logger.exception("load both sides error")
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def parse_data(self):
        full_text = self.recto.get_text() + "\n" + self.verso.get_text()
        if not full_text.strip():
            QtWidgets.QMessageBox.warning(self, "No Text", "Run OCR first to get text to parse.")
            return

        self.parsed_table.setRowCount(0)
        found_data = {}
        
        for field, pattern in PATTERNS.items():
            try:
                matches = pattern.findall(full_text)
                for match in matches:
                    if isinstance(match, tuple):
                        value = next((g for g in match if g), None)
                    else:
                        value = match
                    
                    if value and len(value) > 3:
                        value = value.strip()
                        if field not in found_data:
                            found_data[field] = set()
                        found_data[field].add(value)
            except Exception as e:
                logger.warning(f"Regex error for {field}: {e}")

        row = 0
        self.parsed_table.setRowCount(sum(len(v) for v in found_data.values()))
        for field, values in found_data.items():
            for value in sorted(list(values)):
                self.parsed_table.setItem(row, 0, QtWidgets.QTableWidgetItem(field))
                self.parsed_table.setItem(row, 1, QtWidgets.QTableWidgetItem(value))
                row += 1
        
        self.parsed_table.resizeRowsToContents()
        logger.info(f"Parsing complete, found: {found_data}")

    def get_parsed_data(self) -> dict:
        data = {}
        for row in range(self.parsed_table.rowCount()):
            try:
                field = self.parsed_table.item(row, 0).text()
                value = self.parsed_table.item(row, 1).text()
                if field not in data:
                    data[field] = []
                data[field].append(value)
            except Exception as e:
                logger.warning(f"Could not read table row {row}: {e}")
        return data

    def export_json(self):
        data = self.get_parsed_data()
        if not data:
            QtWidgets.QMessageBox.warning(self, "No Data", "No parsed data to export.")
            return
        
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save JSON", "parsed_data.json", "JSON Files (*.json)")
        if not path:
            return
        
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            QtWidgets.QMessageBox.information(self, "Saved", f"JSON data saved to: {path}")
        except Exception as e:
            logger.exception("export json error")
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def export_csv(self):
        data = self.get_parsed_data()
        if not data:
            QtWidgets.QMessageBox.warning(self, "No Data", "No parsed data to export.")
            return
            
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save CSV", "parsed_data.csv", "CSV Files (*.csv)")
        if not path:
            return
            
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Field", "Value"])
                for field, values in data.items():
                    for value in values:
                        writer.writerow([field, value])
            QtWidgets.QMessageBox.information(self, "Saved", f"CSV data saved to: {path}")
        except Exception as e:
            logger.exception("export csv error")
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def export_merged_image(self):
        if not self.recto.has_image() or not self.verso.has_image():
            QtWidgets.QMessageBox.warning(self, "Warning", "You must load both Recto (Front) and Verso (Back) images to merge them.")
            return

        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Merged Image", "Merged_ID.png", "Images (*.png *.jpg *.jpeg)")
        if not path:
            return

        try:
            img1 = self.recto.cv_image
            img2 = self.verso.cv_image
            
            h1, w1 = img1.shape[:2]
            h2, w2 = img2.shape[:2]

            target_h = max(h1, h2)
            
            if h1 != target_h:
                ratio = target_h / h1
                img1 = cv2.resize(img1, (int(w1 * ratio), target_h), interpolation=cv2.INTER_LANCZOS4)
            
            if h2 != target_h:
                ratio = target_h / h2
                img2 = cv2.resize(img2, (int(w2 * ratio), target_h), interpolation=cv2.INTER_LANCZOS4)
            
            padding = 10
            canvas = np.full((target_h, img1.shape[1] + img2.shape[1] + padding, 3), 255, dtype=np.uint8)
            
            canvas[0:target_h, 0:img1.shape[1]] = img1
            canvas[0:target_h, img1.shape[1] + padding:] = img2
            
            save_image_file(path, canvas)
            
            QtWidgets.QMessageBox.information(self, "Saved", f"Merged image saved to: {path}")
            
        except Exception as e:
            logger.exception("Export merged image error")
            QtWidgets.QMessageBox.critical(self, "Error", f"Could not save merged image: {e}")

    def _add_parsed_data_to_doc(self, doc: Document):
        parsed_data = self.get_parsed_data()
        if parsed_data:
            doc.add_heading("Parsed Information", level=1)
            try:
                table = doc.add_table(rows=1, cols=2)
                table.style = 'Table Grid'
                hdr_cells = table.rows[0].cells
                hdr_cells[0].text = 'Field'
                hdr_cells[1].text = 'Value'
                for field, values in parsed_data.items():
                    for val in values:
                        row_cells = table.add_row().cells
                        row_cells[0].text = field
                        row_cells[1].text = val
                table.columns[0].width = Cm(4)
                table.columns[1].width = Cm(8)
            except Exception as e:
                logger.warning(f"Could not add table to doc: {e}")
                doc.add_paragraph(f"Error adding table: {e}")

            doc.add_paragraph("\n")
            doc.add_heading("Card Images", level=1)

    def export_to_word(self):
        has_recto = self.recto.has_image()
        has_verso = self.verso.has_image()
        if not has_recto and not has_verso:
            QtWidgets.QMessageBox.warning(self, "Warning", "Load at least one image.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Word Document", "ID_Card.docx", "Word Documents (*.docx)")
        if not path:
            return
        tmp = []
        try:
            doc = Document()
            section = doc.sections[0]
            section.page_height = Cm(21)
            section.page_width = Cm(14.8)
            section.top_margin = Cm(1)
            section.bottom_margin = Cm(1)
            section.left_margin = Cm(1)
            section.right_margin = Cm(1)

            self._add_parsed_data_to_doc(doc)

            def add_side(img: np.ndarray, text: str, title: str):
                t = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                tmp.append(t.name)
                t.close()
                save_image_file(t.name, img)
                
                doc.add_picture(t.name, width=Cm(12))
                
                if text:
                    p = doc.add_paragraph()
                    p.add_run("\nExtracted Text:\n").bold = True
                    doc.add_paragraph(text)

            if has_recto:
                add_side(self.recto.cv_image, self.recto.get_text(), "Recto (Front)")
            
            if has_recto and has_verso:
                if self.word_separate_pages:
                    doc.add_page_break()
                else:
                    doc.add_paragraph("\n")

            if has_verso:
                add_side(self.verso.cv_image, self.verso.get_text(), "Verso (Back)")
            
            doc.save(path)
            QtWidgets.QMessageBox.information(self, "Saved", f"Word saved: {path}")
        except Exception as e:
            logger.exception("export word error")
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
        finally:
            for f in tmp:
                try:
                    os.unlink(f)
                except:
                    pass

    def export_to_pdf(self):
        has_recto = self.recto.has_image()
        has_verso = self.verso.has_image()
        if not has_recto and not has_verso:
            QtWidgets.QMessageBox.warning(self, "Warning", "Load at least one image.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save PDF", "ID_Card.pdf", "PDF Files (*.pdf)")
        if not path:
            return
        pages = []
        try:
            def make_page(img: np.ndarray, text: str) -> Image.Image:
                pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                max_w = 1200
                w_ratio = min(1.0, max_w / pil_img.width)
                new_w = int(pil_img.width * w_ratio)
                new_h = int(pil_img.height * w_ratio)
                pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
                
                # ***** NEW: PDF TEXT MODE CONTROL *****
                if self.pdf_text_mode == "none":
                    text_area_h = 0
                elif self.pdf_text_mode == "short":
                    text_area_h = 120
                else:  # "full"
                    text_area_h = 250
                
                canvas = Image.new("RGB", (new_w + 40, new_h + text_area_h + 40), (255,255,255))
                canvas.paste(pil_img, (20,20))
                
                # Only draw text if mode is not "none"
                if self.pdf_text_mode != "none" and text:
                    draw = ImageDraw.Draw(canvas)
                    try:
                        font_bold = ImageFont.truetype("arialbd.ttf", 16)
                        font = ImageFont.truetype("arial.ttf", 14)
                    except:
                        font_bold = ImageFont.load_default()
                        font = ImageFont.load_default()
                    
                    margin = 24
                    y = new_h + 32
                    draw.text((margin, y), "Extracted Text:", font=font_bold, fill=(0,0,0))
                    y += 24
                    
                    # Prepare text lines
                    lines = []
                    for para in text.split('\n'):
                        words = para.split()
                        cur = ""
                        for w in words:
                            if len(cur + " " + w) > 90:
                                lines.append(cur)
                                cur = w
                            else:
                                cur = (cur + " " + w).strip()
                        if cur:
                            lines.append(cur)
                        lines.append("")
                    
                    # Limit lines based on mode
                    max_lines = 4 if self.pdf_text_mode == "short" else 12
                    for ln in lines[:max_lines]:
                        draw.text((margin, y), ln, font=font, fill=(0,0,0))
                        y += 18
                
                return canvas
            
            if has_recto:
                pages.append(make_page(self.recto.cv_image, self.recto.get_text()))
            if has_verso:
                pages.append(make_page(self.verso.cv_image, self.verso.get_text()))
            
            if len(pages) == 1:
                pages[0].save(path, "PDF", resolution=100.0)
            else:
                pages[0].save(path, "PDF", resolution=100.0, save_all=True, append_images=pages[1:])
            QtWidgets.QMessageBox.information(self, "Saved", f"PDF created: {path}")
        except Exception as e:
            logger.exception("export pdf error")
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def register_document(self):
        has_recto = self.recto.has_image()
        has_verso = self.verso.has_image()
        if not has_recto and not has_verso:
            QtWidgets.QMessageBox.warning(self, "Warning", "Load at least one image.")
            return
        docs = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.DocumentsLocation)
        if not docs:
            docs = os.path.expanduser("~")
        
        id_num = ""
        parsed_data = self.get_parsed_data()
        if "ID Number" in parsed_data:
            id_num = parsed_data["ID Number"][0].replace(" ", "") + "_"
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        fname = f"Registered_ID_{id_num}{timestamp}.docx"
        path = os.path.join(docs, fname)
        tmp = []
        try:
            doc = Document()
            section = doc.sections[0]
            section.page_height = Cm(21)
            section.page_width = Cm(14.8)
            section.top_margin = Cm(1)
            section.bottom_margin = Cm(1)
            section.left_margin = Cm(1)
            section.right_margin = Cm(1)

            self._add_parsed_data_to_doc(doc)

            def add_side(img: np.ndarray, text: str, title: str):
                t = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                tmp.append(t.name)
                t.close()
                save_image_file(t.name, img)
                
                doc.add_picture(t.name, width=Cm(12))

                if text:
                    p = doc.add_paragraph()
                    p.add_run("\nExtracted Text:\n").bold = True
                    doc.add_paragraph(text)
            
            if has_recto:
                add_side(self.recto.cv_image, self.recto.get_text(), "Recto (Front)")
            
            if has_recto and has_verso:
                if self.word_separate_pages:
                    doc.add_page_break()
                else:
                    doc.add_paragraph("\n")
                
            if has_verso:
                add_side(self.verso.cv_image, self.verso.get_text(), "Verso (Back)")
            
            doc.save(path)
            QtWidgets.QMessageBox.information(self, "Saved", f"Registered to: {path}")
            self.auto_save_session()
        except Exception as e:
            logger.exception("register error")
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
        finally:
            for f in tmp:
                try: os.unlink(f)
                except: pass

    def clear_all(self):
        reply = QtWidgets.QMessageBox.question(self, "Confirm", "Clear all loaded data?")
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.recto.cv_image = None
        self.recto.image_label.setPixmap(QtGui.QPixmap())
        self.recto.text_edit.clear()
        self.verso.cv_image = None
        self.verso.image_label.setPixmap(QtGui.QPixmap())
        self.verso.text_edit.clear()
        self.parsed_table.setRowCount(0)
        
        try:
            if os.path.exists(LAST_RECTO): os.unlink(LAST_RECTO)
            if os.path.exists(LAST_VERSO): os.unlink(LAST_VERSO)
        except Exception:
            pass
        QtWidgets.QMessageBox.information(self, "Cleared", "All data cleared.")

    def show_settings(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Settings")
        layout = QtWidgets.QFormLayout(dlg)
        
        lang_edit = QtWidgets.QLineEdit(self.ocr_lang)
        psm_spin = QtWidgets.QSpinBox()
        psm_spin.setRange(0,13)
        psm_spin.setValue(self.psm)
        
        theme_combo = QtWidgets.QComboBox()
        theme_combo.addItems(["light", "dark"])
        theme_combo.setCurrentText(self.theme)
        
        chk_separate_pages = QtWidgets.QCheckBox()
        chk_separate_pages.setChecked(self.word_separate_pages)
        
        # ***** NEW: PDF TEXT MODE SELECTOR *****
        pdf_mode_combo = QtWidgets.QComboBox()
        pdf_mode_combo.addItems(["full", "short", "none"])
        pdf_mode_combo.setCurrentText(self.pdf_text_mode)
        
        layout.addRow(QtWidgets.QLabel("Tesseract languages (e.g., eng or eng+ara):"), lang_edit)
        layout.addRow(QtWidgets.QLabel("PSM (0-13):"), psm_spin)
        layout.addRow(QtWidgets.QLabel("Theme:"), theme_combo)
        layout.addRow(QtWidgets.QLabel("Separate pages on Word/Register export:"), chk_separate_pages)
        layout.addRow(QtWidgets.QLabel("PDF Text Mode:"), pdf_mode_combo)
        
        info_label = QtWidgets.QLabel("PDF Modes:\n• full = Complete extracted text\n• short = First 4 lines only\n• none = No text, images only")
        info_label.setStyleSheet("color: gray; font-size: 11px; padding: 5px;")
        layout.addRow(info_label)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.ocr_lang = lang_edit.text().strip() or "eng"
            self.psm = int(psm_spin.value())
            new_theme = theme_combo.currentText()
            self.theme = new_theme
            self.word_separate_pages = chk_separate_pages.isChecked()
            self.pdf_text_mode = pdf_mode_combo.currentText()  # NEW
            
            self.apply_theme(new_theme)
            self.auto_save_session()
            
            QtWidgets.QMessageBox.information(self, "Settings", 
                f"Saved.\nLang={self.ocr_lang}\nPSM={self.psm}\nTheme={self.theme}\nWord Separate={self.word_separate_pages}\nPDF Mode={self.pdf_text_mode}")

    def apply_theme(self, theme_name: str):
        if theme_name == "dark":
            style = """
            QWidget { background: #0f1115; color: #e6eef8; font-family: Inter, Arial; }
            QPushButton { background: #17181b; border: 1px solid #222426; padding:6px; border-radius:8px; }
            QPushButton:hover { background: #242629; }
            QPlainTextEdit, QTableWidget { background: #0b0b0d; border: 1px solid #222; }
            QLabel { color: #e6eef8; }
            QHeaderView::section { background-color: #17181b; border: 1px solid #222; padding: 4px; }
            QLineEdit, QSpinBox, QComboBox, QCheckBox { background-color: #17181b; border: 1px solid #222; padding: 4px; }
            """
        else:
            style = """
            QWidget { background: #f6f8fb; color: #202020; font-family: Inter, Arial; }
            QPushButton { background: #ffffff; border: 1px solid #e1e4ea; padding:6px; border-radius:8px; }
            QPushButton:hover { background: #f0f4f9; }
            QPlainTextEdit, QTableWidget { background: #ffffff; border: 1px solid #e1e4ea; }
            QLabel { color: #202020; }
            QHeaderView::section { background-color: #f6f8fb; border: 1px solid #e1e4ea; padding: 4px; }
            QLineEdit, QSpinBox, QComboBox, QCheckBox { background-color: #ffffff; border: 1px solid #e1e4ea; padding: 4px; }
            """
        self.theme = theme_name
        QtWidgets.QApplication.instance().setStyleSheet(style)
        
        self.recto.image_label.setStyleSheet(self.recto.image_label.styleSheet())
        self.verso.image_label.setStyleSheet(self.verso.image_label.styleSheet())
        
        self.config["theme"] = self.theme
        save_config(self.config)

    def closeEvent(self, event):
        self.auto_save_session()
        event.accept()

# ---------- main ----------
def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()