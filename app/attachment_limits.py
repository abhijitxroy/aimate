"""Document upload policy; disable the higher limit without disabling attachments."""
import os


def document_bytes():
    return (4 if os.environ.get("AIMATE_LARGE_UPLOADS_ENABLED") == "0" else 20) * 1024 * 1024


def upload_body_bytes():
    # Base64 JSON adds one third; leave room for the name and JSON envelope.
    return document_bytes() * 4 // 3 + 4096
