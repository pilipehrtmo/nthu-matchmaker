"""Profile photos: check the upload is a real image, crop it to a square, shrink it and drop its metadata (such as GPS location)."""
import io
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD = 8 * 1024 * 1024    # 8 MB from the phone or laptop
SIZE = 320                      # stored as 320 x 320 pixels, usually 15-30 KB
Image.MAX_IMAGE_PIXELS = 40_000_000   # refuse "decompression bomb" files

class PhotoError(ValueError):
    pass

def make_avatar(data: bytes) -> bytes:
    if not data: raise PhotoError("Choose a photo first.")
    if len(data) > MAX_UPLOAD: raise PhotoError("That photo is too big. Use one under 8 MB.")
    try:
        im = Image.open(io.BytesIO(data))
        if im.format not in ("JPEG", "PNG", "WEBP", "GIF", "MPO"): raise PhotoError("Use a JPG, PNG or WebP photo.")
        im.seek(0); im = ImageOps.exif_transpose(im)   # phone photos: turn them the right way up
        im = ImageOps.fit(im.convert("RGB"), (SIZE, SIZE), Image.LANCZOS, centering=(0.5, 0.4))
    except PhotoError: raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise PhotoError("That file is not a photo we can read. Use a JPG, PNG or WebP.")
    out = io.BytesIO(); im.save(out, "WEBP", quality=82, method=4)   # re-encoding also removes EXIF data
    return out.getvalue()
