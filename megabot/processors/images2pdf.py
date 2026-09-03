# Image set → single PDF, lossless where possible, natural order preserved
import logging
import os

from natsort import natsorted

log = logging.getLogger(__name__)


def images_to_pdf(image_paths: list[str], output_path: str) -> str:
    """Merge images into one PDF at output_path.

    Prefers img2pdf (lossless, keeps original JPEG/PNG bytes). Falls back to
    Pillow for formats img2pdf rejects (e.g. RGBA PNGs, webp).
    Input order is re-sorted naturally: page2 before page10.
    """
    image_paths = natsorted(
        [p for p in image_paths if os.path.getsize(p) > 0],
        key=lambda p: os.path.basename(p).lower(),
    )
    if not image_paths:
        raise ValueError("No valid images to merge")

    try:
        import img2pdf
        with open(output_path, "wb") as f:
            f.write(img2pdf.convert(image_paths))
    except Exception as e:
        log.warning("img2pdf failed (%s) — falling back to Pillow", e)
        from PIL import Image
        imgs = []
        for p in image_paths:
            im = Image.open(p)
            if im.mode in ("RGBA", "P", "LA"):
                im = im.convert("RGB")
            elif im.mode != "RGB":
                im = im.convert("RGB")
            imgs.append(im)
        if not imgs:
            raise ValueError("No images could be decoded")
        imgs[0].save(output_path, "PDF", save_all=True, append_images=imgs[1:],
                     resolution=96)
        for im in imgs:
            im.close()

    log.info("Created PDF %s from %s images", output_path, len(image_paths))
    return output_path