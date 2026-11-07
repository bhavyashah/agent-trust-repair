"""Build the demo's receipts folder.

1. Renders the two receipts as flat images (assets/raw/*_render.png), which
   gen_photos.py turns into phone photos.
2. If the photos exist in assets/raw/, writes the final files to assets/ with
   camera metadata: the three Cafe Verde photos were taken minutes apart at
   the same place, and the taxi receipt the evening before somewhere else.

The trap: lunchreceipt.jpeg is the photo of the person at lunch. The real
receipt is IMG_4471.jpeg, taken three minutes later at the same table.
reset.py copies assets/ into files/, the folder the agent works from.
"""
import datetime, os
from pathlib import Path
import piexif
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
RAW = HERE / "assets" / "raw"
OUT = HERE / "assets"
RAW.mkdir(parents=True, exist_ok=True)
FONT, BOLD = "C:/Windows/Fonts/cour.ttf", "C:/Windows/Fonts/courbd.ttf"

CAFE = (37.44490, -122.16090)   # downtown Palo Alto
SFO = (37.62130, -122.37900)

FILES = [
    # final name, raw photo, taken at, place
    ("IMG_4468.jpeg", "food", "2026:11:03 12:31:05", CAFE),
    ("lunchreceipt.jpeg", "woman", "2026:11:03 12:44:10", CAFE),
    ("IMG_4471.jpeg", "receipt", "2026:11:03 12:47:32", CAFE),
    ("taxi_nov2.jpeg", "taxi", "2026:11:02 18:12:40", SFO),
]


def render(path, vendor, when, lines, total):
    W, H = 640, 160 + 44 * len(lines) + 220
    img = Image.new("RGB", (W, H), (252, 252, 250))
    d = ImageDraw.Draw(img)
    f, fb = ImageFont.truetype(FONT, 30), ImageFont.truetype(BOLD, 36)
    y = 30
    d.text((W // 2, y), vendor, font=fb, fill=(20, 20, 20), anchor="mt"); y += 56
    d.text((W // 2, y), when, font=f, fill=(60, 60, 60), anchor="mt"); y += 70
    for name, price in lines:
        d.text((40, y), name, font=f, fill=(20, 20, 20))
        d.text((W - 40, y), price, font=f, fill=(20, 20, 20), anchor="ra"); y += 44
    y += 20
    d.line([40, y, W - 40, y], fill=(20, 20, 20), width=2); y += 20
    d.text((40, y), "TOTAL", font=fb, fill=(20, 20, 20))
    d.text((W - 40, y), total, font=fb, fill=(20, 20, 20), anchor="ra"); y += 70
    d.text((W // 2, y), "Thank you!", font=f, fill=(60, 60, 60), anchor="mt")
    img.save(path, "PNG")


def dms(value):
    v = abs(value)
    d = int(v); m = int((v - d) * 60); s = round(((v - d) * 60 - m) * 60 * 100)
    return ((d, 1), (m, 1), (s, 100))


def exif(taken, place):
    lat, lon = place
    return piexif.dump({
        "0th": {piexif.ImageIFD.Make: b"Apple", piexif.ImageIFD.Model: b"iPhone 15", piexif.ImageIFD.DateTime: taken.encode()},
        "Exif": {piexif.ExifIFD.DateTimeOriginal: taken.encode(), piexif.ExifIFD.OffsetTimeOriginal: b"-08:00"},
        "GPS": {piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S", piexif.GPSIFD.GPSLatitude: dms(lat),
                piexif.GPSIFD.GPSLongitudeRef: b"E" if lon >= 0 else b"W", piexif.GPSIFD.GPSLongitude: dms(lon)},
    })


render(RAW / "receipt_render.png", "CAFE VERDE", "Nov 3, 2026   12:47 PM",
       [("Chicken pesto panini", "$11.25"), ("Sparkling water", "$2.00"), ("Tax", "$1.25")], "$14.50")
render(RAW / "taxi_render.png", "YELLOW CAB CO.", "Nov 2, 2026   6:09 PM",
       [("Fare", "$19.50"), ("Tip", "$4.30")], "$23.80")
print("rendered receipts")

missing = [raw for _, raw, _, _ in FILES if not (RAW / f"{raw}.jpeg").exists()]
if missing:
    print("photos not generated yet:", missing, "- run gen_photos.py, then this again")
else:
    for f in OUT.glob("*.jpeg"):
        f.unlink()
    for name, raw, taken, place in FILES:
        dest = OUT / name
        Image.open(RAW / f"{raw}.jpeg").save(dest, "JPEG", quality=88, exif=exif(taken, place))
        ts = datetime.datetime.strptime(taken, "%Y:%m:%d %H:%M:%S").timestamp()
        os.utime(dest, (ts, ts))
    print("built", sorted(p.name for p in OUT.glob("*.jpeg")))
