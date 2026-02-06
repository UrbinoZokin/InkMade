from __future__ import annotations
from PIL import Image

def show_on_inky(img: Image.Image, rotate_degrees: int = 0, border: str = "white") -> None:
    """
    Displays a PIL image on Inky Impressions.
    Assumes the 'inky' library is installed on the Pi and hardware is connected.
    """
    from inky.auto import auto  # type: ignore

    disp = auto(ask_user=False, verbose=False)
    if disp is None:
        raise RuntimeError("Could not auto-detect Inky display. Check wiring and SPI enabled.")

    if rotate_degrees:
        img = img.rotate(rotate_degrees, expand=True)

    # Convert image to mode expected by inky; many accept RGB directly
    disp.set_border(border)
    disp.set_image(img)
    disp.show()
