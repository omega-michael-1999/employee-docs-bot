#!/usr/bin/env python3
"""Extract text from documents: PDF, DOCX, images, and plain text.
Usage: doc-extract.py <file> [prompt]
  prompt only used for image/vision-based extraction
Outputs robot.txt-style metadata + extracted text to stdout.
"""

import sys, os, json, base64, io, re, zipfile, xml.etree.ElementTree as ET
from datetime import date
import urllib.request, urllib.error

# HEIC/HEIF support (pillow-heif optional — degrades gracefully if missing)
try:
    from pillow_heif import open_heif as _open_heif
    _HAS_HEIF = True
except ImportError:
    _HAS_HEIF = False

def _convert_heic(path):
    """Convert a HEIC/HEIF file to JPEG bytes. Returns (jpeg_bytes, mime) or raises."""
    if not _HAS_HEIF:
        raise RuntimeError("pillow-heif not installed; install it for HEIC/HEIF support")
    heif = _open_heif(path)
    from PIL import Image
    img = Image.frombytes(heif.mode, heif.size, heif.data)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue(), "image/jpeg"

def main():
    if len(sys.argv) < 2:
        print("Usage: doc-extract.py <file> [prompt]", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    prompt = sys.argv[2] if len(sys.argv) > 2 else \
        "Extract all visible text from this document. List every field, name, number, date, and result. Be concise."

    if not os.path.exists(path):
        print(f"FILE_NOT_FOUND:{path}", file=sys.stderr)
        sys.exit(1)

    ext = os.path.splitext(path)[1].lower().lstrip('.')
    fname = os.path.basename(path)

    print(f"SOURCE FILE: {fname}")
    print(f"SOURCE PATH: {os.path.dirname(path)}")
    print(f"EXTRACTED: {date.today()}")
    print()

    result = None

    if ext == 'pdf':
        result = extract_pdf(path, prompt)
    elif ext == 'docx':
        result = extract_docx(path)
    elif ext in ('jpg', 'jpeg', 'png', 'tiff', 'tif', 'bmp', 'gif', 'webp', 'heic', 'heif'):
        result = extract_image(path, prompt)
    elif ext in ('txt', 'html', 'htm', 'xml', 'json', 'csv'):
        result = extract_text(path)
    else:
        result = extract_pdf(path, prompt) or extract_docx(path) or extract_image(path, prompt)

    if result:
        print(result)
    else:
        print("ERROR: No extraction method succeeded")


_NOISE_WORDS = {"camscanner", "scanned by camscanner", "camscanner.com", "powered by camscanner"}


def _is_noise_text(text: str) -> bool:
    """Check if extracted text is just scanner watermark noise."""
    stripped = text.strip().lower()
    if len(stripped) < 50:
        return True  # Too short to be meaningful
    for noise in _NOISE_WORDS:
        if noise in stripped:
            return True
    return False


def extract_pdf(path, prompt):
    """Try PyPDF2 first; if empty or noise-only (scanned), use vision OCR."""
    text = extract_pdf_text(path)
    if text and text.strip() and not _is_noise_text(text):
        return f"METHOD: PDF text extraction (PyPDF2)\n\n--- EXTRACTED TEXT ---\n{text.strip()}"
    # Scanned PDF — render pages and OCR
    return extract_scanned_pdf(path, prompt)


def extract_pdf_text(path):
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(path)
        pages = []
        for p in reader.pages:
            t = p.extract_text()
            if t and t.strip():
                pages.append(t.strip())
        return '\n'.join(pages) if pages else None
    except Exception:
        return None


def extract_scanned_pdf(path, prompt):
    api_key = os.environ.get("ANTHROPIC_VISION_API_KEY")
    if not api_key:
        return None
    try:
        import fitz
        doc = fitz.open(path)
        all_text = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_data = pix.tobytes("jpeg")
            text = vision_ocr(img_data, "image/jpeg", api_key, prompt)
            if text:
                if len(doc) > 1:
                    all_text.append(f"[Page {page_num+1}]\n{text}")
                else:
                    all_text.append(text)
        doc.close()
        if all_text:
            return f"METHOD: VISION OCR (PyMuPDF render + claude-haiku-4-5-20251001)\n\n--- EXTRACTED TEXT ---\n{chr(10).join(all_text)}"
    except ImportError:
        return None
    except Exception as e:
        return f"ERROR: {e}"
    return None


def extract_docx(path):
    try:
        z = zipfile.ZipFile(path)
        xml_content = z.read('word/document.xml')
        root = ET.fromstring(xml_content)
        texts = []
        for p in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
            line = ''.join(t.text or '' for t in p.iter(
                '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t') if t.text)
            if line.strip():
                texts.append(line)
        z.close()
        if texts:
            return f"METHOD: DOCX text extraction (python-docx)\n\n--- EXTRACTED TEXT ---\n{chr(10).join(texts)}"
    except Exception:
        pass
    return None


def extract_image(path, prompt):
    api_key = os.environ.get("ANTHROPIC_VISION_API_KEY")
    if not api_key:
        return None

    ext = path.lower()
    # HEIC/HEIF → convert to JPEG
    if ext.endswith(('.heic', '.heif')):
        try:
            img_data, mime = _convert_heic(path)
        except Exception as e:
            return f"ERROR: HEIC conversion failed: {e}"
    else:
        mime = "image/jpeg"
        if ext.endswith('.png'):
            mime = "image/png"
        elif ext.endswith(('.tiff', '.tif')):
            mime = "image/tiff"
        elif ext.endswith('.webp'):
            mime = "image/webp"
        elif ext.endswith('.bmp'):
            mime = "image/bmp"
        elif ext.endswith('.gif'):
            mime = "image/gif"

        with open(path, "rb") as f:
            img_data = f.read()

    text = vision_ocr(img_data, mime, api_key, prompt)
    if text:
        return f"METHOD: ANTHROPIC VISION OCR (claude-haiku-4-5-20251001)\n\n--- EXTRACTED TEXT ---\n{text}"
    return None


def extract_text(path):
    with open(path, 'r', errors='replace') as f:
        content = f.read()
    return f"METHOD: Direct text read\n\n--- EXTRACTED TEXT ---\n{content}"


def vision_ocr(img_data, mime, api_key, prompt):
    b64 = base64.b64encode(img_data).decode()
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 2048,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                {"type": "text", "text": prompt}
            ]
        }]
    })
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload.encode(),
            headers={
                "content-type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        if "content" in data:
            return "\n".join(c["text"] for c in data["content"] if c.get("type") == "text")
        elif "error" in data:
            return f"ERROR[{data['error']['type']}]: {data['error']['message']}"
        return json.dumps(data, indent=2)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return f"ERROR[HTTP {e.code}]: {body[:200]}"
    except Exception as e:
        return f"ERROR: {e}"


if __name__ == '__main__':
    main()
