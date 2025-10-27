# Smart ID Scanner Plus V7

**Smart ID Scanner Plus** is a powerful desktop application for document and ID card scanning with advanced OCR capabilities. Built with Python and PyQt6, it provides a modern interface for extracting text from identity cards, passports, and other documents.

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)
![PyQt6](https://img.shields.io/badge/PyQt6-6.0%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)

---

## ✨ Features

### 🖼️ Image Processing
- **Dual-side scanning**: Scan both front (Recto) and back (Verso) of ID cards
- **Auto-detection**: Automatic card contour detection with perspective correction
- **Manual cropping**: Interactive ROI selection using OpenCV
- **Image enhancement**: Rotate, sharpen, and adjust contrast
- **Smart preprocessing**: Bilateral filtering and Otsu thresholding for optimal OCR

### 📝 OCR & Text Extraction
- **Pytesseract integration**: Powerful OCR engine with multi-language support
- **Configurable PSM modes**: Page Segmentation Mode (0-13) for different document types
- **Async processing**: Non-blocking OCR with threaded workers
- **Smart parsing**: Automatic extraction of ID numbers, dates, and names using regex patterns

### 📤 Export Formats
- **Word (.docx)**: Export with images and extracted text
- **PDF (.pdf)**: Three text modes - Full, Short (4 lines), or No Text
- **JSON**: Structured data export for parsed information
- **CSV**: Tabular export of extracted fields
- **Merged images**: Combine front and back into a single image

### 🎨 User Interface
- **Modern PyQt6 design**: Clean, responsive interface
- **Light/Dark themes**: Toggle between themes
- **Real-time preview**: Immediate visual feedback for all operations
- **Session persistence**: Auto-save last session (images + settings)

### 🔍 Data Parsing (Experimental)
- ID Number detection
- Date extraction (multiple formats)
- Name recognition (Title case and CAPS)
- Structured table display

---

## 📋 Requirements

### System Requirements
- **OS**: Windows, macOS, or Linux
- **Python**: 3.8 or higher
- **Tesseract OCR**: Must be installed separately

### Python Dependencies
```
PyQt6>=6.0.0
opencv-python>=4.5.0
numpy>=1.19.0
pytesseract>=0.3.8
Pillow>=8.0.0
python-docx>=0.8.11
```

---

## 🚀 Installation

### 1. Install Tesseract OCR

#### Windows
Download and install from: [https://github.com/UB-Mannheim/tesseract/wiki](https://github.com/UB-Mannheim/tesseract/wiki)

Default installation paths supported:
- `C:\Program Files\Tesseract-OCR\tesseract.exe`
- `C:\Program Files (x86)\Tesseract-OCR\tesseract.exe`

#### macOS
```bash
brew install tesseract
```

#### Linux (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install tesseract-ocr
```

### 2. Install Python Dependencies

```bash
pip install PyQt6 opencv-python numpy pytesseract Pillow python-docx
```

Or create a `requirements.txt` file:
```
PyQt6>=6.0.0
opencv-python>=4.5.0
numpy>=1.19.0
pytesseract>=0.3.8
Pillow>=8.0.0
python-docx>=0.8.11
```

Then install:
```bash
pip install -r requirements.txt
```

### 3. Download and Run

```bash
# Clone or download the script
python smart_id_scanner_v7.py
```

---

## 🎯 Usage

### Basic Workflow

1. **Launch the application**
   ```bash
   python smart_id_scanner_v7.py
   ```

2. **Load images**
   - Click "Load" for individual sides (Recto/Verso)
   - Or use "Load Both" to select front and back together

3. **Process images**
   - **Auto Detect**: Automatic card detection and cropping
   - **Manual Crop**: Interactive rectangular selection
   - **Enhance**: Use Rotate L/R, Sharpen, or Contrast buttons

4. **Extract text**
   - Click "OCR" on each side to extract text
   - Wait for processing (non-blocking UI)
   - View extracted text in the text area

5. **Parse data** (Optional)
   - Click "Parse Data" to extract structured information
   - Review ID numbers, dates, and names in the table

6. **Export**
   - Choose your format: `.docx`, `.pdf`, `.json`, `.csv`, or merged image
   - Use "Register" to auto-save to Documents folder

### Advanced Features

#### Settings (Click "Settings" button)
- **OCR Language**: e.g., `eng`, `ara`, `eng+ara` (requires Tesseract language packs)
- **PSM Mode**: Page Segmentation Mode (6 = uniform block, 11 = sparse text, etc.)
- **Theme**: Light or Dark mode
- **Word Export**: Separate pages for front/back
- **PDF Text Mode**:
  - `full`: Complete extracted text
  - `short`: First 4 lines only
  - `none`: Images only, no text

#### Session Management
- Last loaded images are automatically saved to `~/.smart_id_scanner_plus/`
- Settings are persisted across sessions
- Clear all data with "Clear" button

---

## 📁 File Structure

```
~/.smart_id_scanner_plus/
├── config.json          # User settings (OCR lang, PSM, theme, etc.)
├── last_recto.png       # Last loaded front image
└── last_verso.png       # Last loaded back image
```

---

## 🛠️ Configuration

### Default Configuration
The application uses the following defaults (can be changed in Settings):

```json
{
  "ocr_lang": "eng",
  "psm": 6,
  "theme": "light",
  "word_separate_pages": false,
  "pdf_text_mode": "full"
}
```

### OCR Languages
To use languages other than English, install Tesseract language packs:

#### Windows
Download `.traineddata` files from [tessdata](https://github.com/tesseract-ocr/tessdata) and place in:
```
C:\Program Files\Tesseract-OCR\tessdata\
```

#### macOS/Linux
```bash
# Arabic example
sudo apt-get install tesseract-ocr-ara

# Or manually download to /usr/share/tesseract-ocr/4.00/tessdata/
```

Then set language in Settings: `eng+ara`, `fra`, etc.

---

## 🧩 Regex Patterns

The application uses the following patterns to parse data (experimental):

| Field | Pattern |
|-------|---------|
| **ID Number** | `([A-Z]{1,2}\s?\d{6,9})` or `(\d{10,14})` |
| **Date** | `(\d{2}[/.-]\d{2}[/.-]\d{4})` |
| **Name (Caps)** | `([A-Z][A-Z\s\-]{4,})` |
| **Name (Title)** | `([A-Z][a-z]+(?:\s[A-Z][a-z]+){1,3})` |

*Note: Patterns may require customization for specific document types or regions.*

---

## 📸 Screenshots

*(Add screenshots here to showcase your UI, e.g., main window, dark theme, export dialog)*

Example:
```markdown
### Light Theme
![Light Theme](screenshots/light_theme.png)

### Dark Theme
![Dark Theme](screenshots/dark_theme.png)

### Parsed Data
![Parsed Data](screenshots/parsed_data.png)
```

---

## 🐛 Troubleshooting

### "Tesseract not found"
- Ensure Tesseract is installed and in your system PATH
- Or manually set path in the script:
  ```python
  pytesseract.pytesseract.tesseract_cmd = r'C:\Path\To\tesseract.exe'
  ```

### OCR returns empty text
- Check image quality (use Sharpen/Contrast)
- Try different PSM modes (Settings → PSM)
- Ensure correct language is selected

### "Could not read image"
- Verify image format is supported (PNG, JPG, JPEG, BMP, TIFF)
- Check file path doesn't contain special characters

### Application freezes during OCR
- OCR runs in background threads and shouldn't freeze UI
- If frozen, check console for error messages
- Try simpler images first to verify Tesseract installation

---

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

1. **Report bugs**: Open an issue with details and screenshots
2. **Suggest features**: Describe your use case and proposed solution
3. **Submit pull requests**: 
   - Fork the repository
   - Create a feature branch (`git checkout -b feature/AmazingFeature`)
   - Commit your changes (`git commit -m 'Add some AmazingFeature'`)
   - Push to the branch (`git push origin feature/AmazingFeature`)
   - Open a Pull Request

### Development Guidelines
- Follow PEP 8 style guide
- Add docstrings to new functions
- Test with multiple image types before submitting
- Update README if adding new features

---

## 📄 License

This project is licensed under the MIT License - see below for details:

```
MIT License

Copyright (c) 2025 Amine Marino

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 🙏 Acknowledgments

- **Tesseract OCR**: [https://github.com/tesseract-ocr/tesseract](https://github.com/tesseract-ocr/tesseract)
- **PyQt6**: [https://www.riverbankcomputing.com/software/pyqt/](https://www.riverbankcomputing.com/software/pyqt/)
- **OpenCV**: [https://opencv.org/](https://opencv.org/)
- **Pytesseract**: [https://github.com/madmaze/pytesseract](https://github.com/madmaze/pytesseract)

---

## 📞 Contact & Support

- **Issues**: Open an issue on GitHub
- **Discussions**: Use GitHub Discussions for questions
- **Email**: amine47994@gmail.com

---

## 🗺️ Roadmap

### V7 (Current)
- ✅ PDF text control (full/short/none)
- ✅ Session persistence
- ✅ Light/Dark themes

### Future Versions
- [ ] Batch processing for multiple documents
- [ ] Cloud storage integration (Google Drive, Dropbox)
- [ ] Advanced data validation (Luhn algorithm for ID numbers)
- [ ] Multi-language UI
- [ ] Database integration for document management
- [ ] QR code and barcode scanning
- [ ] Face detection and cropping
- [ ] PDF import (scan from existing PDFs)

---

## ⭐ Star History

If you find this project useful, please consider giving it a star ⭐

---

**Made with ❤️ using Python and PyQt6**
