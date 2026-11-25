"""Validate and sanitise user-uploaded images before they go anywhere else."""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_DIMENSION = 2048
MAX_PIXELS = 40_000_000  # decompression-bomb guard
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class ImageError(ValueError):
    """User-safe message."""


def process_image(data: bytes, filename: str, max_bytes: int) -> tuple[bytes, str]:
    """Return (sanitised_bytes, mime). Raises ImageError.

    The file type is decided by decoding the bytes, not by the filename or client content-type.
    The image is re-encoded, which strips EXIF/GPS metadata and any appended payload.
    """
    if not data:
        raise ImageError("The file is empty.")
    if len(data) > max_bytes:
        raise ImageError(f"The image is too large. The limit is {max_bytes // (1024 * 1024)} MB.")
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise ImageError("Unsupported file type. Please upload a JPG, PNG or WEBP image.")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            probe.verify()
        if fmt not in ALLOWED_FORMATS:
            raise ImageError("Unsupported image format. Please upload a JPG, PNG or WEBP image.")
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)  # respect orientation, then drop metadata
            if getattr(img, "is_animated", False):
                img.seek(0)
            img.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
            out = io.BytesIO()
            if fmt == "JPEG":
                img.convert("RGB").save(out, "JPEG", quality=90)
                mime = "image/jpeg"
            else:  # PNG / WEBP screenshots: keep lossless text sharpness
                img.convert("RGBA" if "A" in img.getbands() else "RGB").save(out, "PNG", optimize=True)
                mime = "image/png"
    except ImageError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise ImageError("We couldn't read that image. It may be corrupted or not a real image file.")
    return out.getvalue(), mime
