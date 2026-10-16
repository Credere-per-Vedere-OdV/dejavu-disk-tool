"""Render the original PNGs at the current display density, without subsampling."""
from PIL import Image, ImageTk

from .resources import asset_path


def display_scale(root):
    # Tk's scaling is pixels per typographic point; 96 dpi is the Windows
    # reference density. Query after the process has enabled DPI awareness.
    return max(1.0, min(3.0, float(root.winfo_fpixels("1i")) / 96.0))


def render_logo(name, max_width, max_height):
    with Image.open(asset_path(name)) as source:
        source.load()  # Decode the full PNG, never an embedded metadata thumbnail.
        image = source.convert("RGBA")
    image.thumbnail((round(max_width), round(max_height)), Image.Resampling.LANCZOS,
                    reducing_gap=3.0)
    return image


def logo_photo(root, name, max_width, max_height):
    return ImageTk.PhotoImage(render_logo(name, max_width, max_height), master=root)
