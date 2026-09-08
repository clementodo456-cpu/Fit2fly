import math
import re
from io import BytesIO
from typing import List, Tuple
from PIL import Image, ImageOps, ImageColor, UnidentifiedImageError

MAX_CANVAS_DIMENSION = 4000
MAX_OUTPUT_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

BG_COLORS = {
    "White": "#FFFFFF",
    "Black": "#000000",
    "Gray": "#808080"
}

def validate_hex_color(hex_code: str) -> str:
    """Validates and formats HEX color string."""
    hex_code = hex_code.strip()
    if not hex_code.startswith("#"):
        hex_code = "#" + hex_code
    if re.match(r"^#(?:[0-9a-fA-F]{3}){1,2}$", hex_code):
        return hex_code.upper()
    raise ValueError("Invalid HEX color code.")

def parse_layout_string(layout: str, num_photos: int) -> Tuple[int, int]:
    """Parses layout string (e.g., '2x3' or 'Auto Grid') into (cols, rows)."""
    if layout == "Auto Grid":
        if num_photos == 2:
            return 2, 1
        elif num_photos <= 4:
            return 2, 2
        elif num_photos <= 6:
            return 3, 2
        else:
            return 3, 3
    
    parts = layout.lower().split("x")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[0]), int(parts[1])
    
    # Fallback to Auto Grid strategy
    return parse_layout_string("Auto Grid", num_photos)

def process_image_orientation(img: Image.Image) -> Image.Image:
    """Corrects image orientation based on EXIF tags."""
    try:
        return ImageOps.exif_transpose(img)
    except Exception:
        return img

def create_collage(
    image_bytes_list: List[BytesIO],
    layout_str: str,
    spacing: int,
    bg_color_input: str,
    fit_mode: str
) -> BytesIO:
    """
    Combines input image BytesIO objects into a single grid collage BytesIO stream.
    """
    if not image_bytes_list:
        raise ValueError("No images provided for collage generation.")

    num_photos = len(image_bytes_list)
    cols, rows = parse_layout_string(layout_str, num_photos)

    # Resolve background color
    hex_color = BG_COLORS.get(bg_color_input)
    if not hex_color:
        hex_color = validate_hex_color(bg_color_input)
    bg_rgb = ImageColor.getrgb(hex_color)

    # Load and auto-rotate images
    images: List[Image.Image] = []
    for bio in image_bytes_list:
        bio.seek(0)
        img = Image.open(bio)
        img = process_image_orientation(img)
        img = img.convert("RGB")
        images.append(img)

    # Determine cell dimensions safely within MAX_CANVAS_DIMENSION bounds
    cell_width = 800
    cell_height = 800

    # Ensure total width and total height don't exceed MAX_CANVAS_DIMENSION
    total_spacing_x = spacing * (cols + 1)
    total_spacing_y = spacing * (rows + 1)

    if (cell_width * cols + total_spacing_x) > MAX_CANVAS_DIMENSION:
        cell_width = (MAX_CANVAS_DIMENSION - total_spacing_x) // cols
    if (cell_height * rows + total_spacing_y) > MAX_CANVAS_DIMENSION:
        cell_height = (MAX_CANVAS_DIMENSION - total_spacing_y) // rows

    canvas_w = (cell_width * cols) + total_spacing_x
    canvas_h = (cell_height * rows) + total_spacing_y

    canvas = Image.new("RGB", (canvas_w, canvas_h), color=bg_rgb)

    for i, img in enumerate(images):
        if i >= cols * rows:
            break

        c = i % cols
        r = i // cols

        x = spacing + c * (cell_width + spacing)
        y = spacing + r * (cell_height + spacing)

        if fit_mode == "Cover":
            # Crop to fill the cell completely while preserving aspect ratio
            processed_cell = ImageOps.fit(img, (cell_width, cell_height), method=Image.Resampling.LANCZOS)
            canvas.paste(processed_cell, (x, y))
        else:
            # Fit: preserve whole image inside cell with background padding
            img_ratio = img.width / img.height
            cell_ratio = cell_width / cell_height

            if img_ratio > cell_ratio:
                new_w = cell_width
                new_h = int(cell_width / img_ratio)
            else:
                new_h = cell_height
                new_w = int(cell_height * img_ratio)

            resized_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            cell_bg = Image.new("RGB", (cell_width, cell_height), color=bg_rgb)
            
            px = (cell_width - new_w) // 2
            py = (cell_height - new_h) // 2
            cell_bg.paste(resized_img, (px, py))
            canvas.paste(cell_bg, (x, y))

    # Close processing image memory buffers
    for img in images:
        img.close()

    # Save output to JPEG stream with optional compression safeguard
    output = BytesIO()
    quality = 90
    canvas.save(output, format="JPEG", quality=quality, optimize=True)
    canvas.close()

    while output.tell() > MAX_OUTPUT_FILE_SIZE and quality > 30:
        output = BytesIO()
        quality -= 10
        canvas.save(output, format="JPEG", quality=quality, optimize=True)

    output.seek(0)
    return output
