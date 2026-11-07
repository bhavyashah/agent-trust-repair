"""Generate the demo photos once with Gemini's image model into agent/assets/raw/.

Run make_assets.py afterwards: it adds the camera metadata (time, place) and
builds agent/assets/, which reset.py copies into the agent's files folder.

    python agent/gen_photos.py [name ...]     # regenerate some or all
"""
import base64, io, sys
from pathlib import Path
import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from agent import KEY  # noqa: E402

RAW = Path(__file__).parent / "assets" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
MODEL = "gemini-3-pro-image"

TABLE = ("a small round light-oak café table by a window with daylight, a sage-green ceramic mug, "
         "a small potted succulent, and a little green table card that reads 'Café Verde'")

PHOTOS = {
    "food": dict(prompt=f"Casual smartphone photo, slightly from above: a chicken pesto panini cut in half on a white plate "
                        f"and a glass of sparkling water, on {TABLE}. Midday light. Realistic phone photo, no people."),
    "woman": dict(prompt=f"Casual smartphone photo taken across the table at lunch: a woman in her thirties with shoulder-length "
                         f"dark hair and a mustard sweater, smiling and mid-conversation, sitting at {TABLE}. A half-eaten "
                         f"panini on a white plate in front of her. Realistic, candid, natural light, slight motion blur.",
                  ref="food"),
    "receipt": dict(prompt=f"Casual smartphone photo looking down at the paper receipt from the first image lying flat on "
                           f"the café table shown in the second image ({TABLE}), next to the plate's edge. Reproduce every "
                           f"word and number on the receipt exactly as in the first image; it must stay fully legible. "
                           f"Realistic phone photo, slight curl in the paper.",
                    src="receipt_render", ref="food"),
    "taxi": dict(prompt="Casual smartphone photo of the paper receipt in the image, held in one hand in the back seat of a "
                        "car at dusk. Reproduce every word and number exactly; keep it fully legible. Realistic phone photo.",
                 src="taxi_render"),
}


def b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def generate(name):
    spec = PHOTOS[name]
    parts = []
    for key in ("src", "ref"):
        if key in spec:
            p = RAW / f"{spec[key]}.png"
            if not p.exists():
                p = RAW / f"{spec[key]}.jpeg"
            parts.append({"inlineData": {"mimeType": "image/png" if p.suffix == ".png" else "image/jpeg", "data": b64(p)}})
    parts.append({"text": spec["prompt"]})
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
                      headers={"x-goog-api-key": KEY},
                      json={"contents": [{"role": "user", "parts": parts}],
                            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "4:3"}}},
                      timeout=300)
    r.raise_for_status()
    for p in r.json()["candidates"][0]["content"]["parts"]:
        if "inlineData" in p:
            img = Image.open(io.BytesIO(base64.b64decode(p["inlineData"]["data"]))).convert("RGB")
            img.save(RAW / f"{name}.jpeg", "JPEG", quality=88)
            print("wrote", name, img.size)
            return
    raise RuntimeError(f"no image for {name}: {r.text[:300]}")


if __name__ == "__main__":
    for n in (sys.argv[1:] or PHOTOS):
        generate(n)
