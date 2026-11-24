"""Validate attachment bytes locally before any provider call."""
import base64
import io
import warnings

MAX_BYTES = 4 * 1024 * 1024


def decode_file(item):
    if not isinstance(item, dict) or set(item) != {"name", "data"}:
        raise ValueError("Provide an attachment name and base64 data.")
    name, data = item["name"], item["data"]
    if not isinstance(name, str) or not 1 <= len(name) <= 255 or not isinstance(data, str) or len(data) > MAX_BYTES * 4 // 3 + 8:
        raise ValueError("Use an attachment under 4 MB.")
    try:
        raw = base64.b64decode(data, validate=True)
    except (ValueError, TypeError):
        raise ValueError("Invalid attachment data.") from None
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Use an attachment under 4 MB.")
    return name, raw


def image(item):
    from PIL import Image, UnidentifiedImageError
    name, raw = decode_file(item)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP", "GIF"} or source.width * source.height > 20_000_000:
                    raise ValueError("Use a PNG, JPEG, WebP or GIF under 20 megapixels.")
                source.seek(0)
                source.load()
                clean = source.convert("RGB")
                clean.thumbnail((2048, 2048))
                full = io.BytesIO()
                clean.save(full, "JPEG", quality=90)
                clean.thumbnail((240, 180))
                preview = io.BytesIO()
                clean.save(preview, "JPEG", quality=80)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("The image could not be read. Use a valid screenshot or image.") from None
    data = base64.b64encode(full.getvalue()).decode()
    block = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}
    card = {"name": name, "size": len(raw), "kind": "image",
            "preview": "data:image/jpeg;base64," + base64.b64encode(preview.getvalue()).decode()}
    return block, card


def pdf(item):
    from pypdf import PdfReader
    name, raw = decode_file(item)
    if not raw.startswith(b"%PDF-"):
        raise ValueError("This file is not a PDF.")
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ValueError("Unlock the PDF before attaching it.")
        if len(reader.pages) > 80:
            raise ValueError("Use a PDF with at most 80 pages.")
        parts = []
        for index, page in enumerate(reader.pages):
            parts.append(f"Page {index + 1}\n{page.extract_text() or ''}")
            if sum(map(len, parts)) > 28000:
                raise ValueError("PDF text exceeds 28,000 characters. Attach selected pages.")
        text = "\n\n".join(parts)
        if not any((page.extract_text() or "").strip() for page in reader.pages):
            raise ValueError("This PDF has no readable text. Attach screenshots of its pages.")
        return {"name": name, "size": len(raw), "kind": "pdf", "text": text}
    except ValueError:
        raise
    except Exception:
        raise ValueError("The PDF could not be read. Try exporting it again.") from None
