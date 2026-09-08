from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener


# Allow Pillow to decode HEIC / HEIF files from iPhones.
register_heif_opener(thumbnails=False)


MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_LONG_EDGE = 3000


async def normalize_receipt_image(
    file: UploadFile,
    output_dir: Path,
    receipt_id: str,
) -> Path:
    """
    Validate an uploaded image, fix orientation, resize if needed,
    strip metadata, and convert it to a JPEG suitable for the VLM.
    """

    raw = await file.read(MAX_UPLOAD_BYTES + 1)

    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Image is larger than 20 MB.")

    if not raw:
        raise ValueError("Uploaded file is empty.")

    try:
        with Image.open(BytesIO(raw)) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()

            if image.mode != "RGB":
                image = image.convert("RGB")

            if max(image.size) > MAX_LONG_EDGE:
                image.thumbnail(
                    (MAX_LONG_EDGE, MAX_LONG_EDGE),
                    Image.Resampling.LANCZOS,
                )

            # Create a fresh image so metadata such as EXIF/GPS
            # is not carried into the stored receipt image.
            clean_image = Image.new("RGB", image.size)
            clean_image.paste(image)

    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("The uploaded file is not a valid image.") from exc

    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{receipt_id}.jpg"

    clean_image.save(
        output_path,
        format="JPEG",
        quality=92,
        optimize=True,
    )

    return output_path