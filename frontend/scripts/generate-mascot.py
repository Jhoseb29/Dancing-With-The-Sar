#!/usr/bin/env python3
"""
Generador de los sprites animados de Jucu (Jucumari / Oso Andino del Tunari)
para "Dancing with the SARs" usando Google Gemini Interactions API (gemini-nano-banana-2.1)
y recorte alfa por inundación exterior con alineación de caja envolvente común.

Ejecución con uv desde la raíz del repositorio:
    uv run --with "google-genai>=2.30.1" --with python-dotenv --with pillow --with numpy --with scipy python frontend/scripts/generate-mascot.py
"""

import base64
import io
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
import numpy as np
from PIL import Image
from scipy import ndimage

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "frontend" / "src" / "assets" / "mascot"


def make_rgba(raw_bytes: bytes) -> np.ndarray:
    """Convierte el fondo negro exterior (fuera del borde blanco tipo sticker) en alfa 0."""
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
    arr = np.array(img)
    rgb = arr[:, :, :3].astype(np.float32)
    brightness = rgb.max(axis=2)

    dark_mask = brightness < 45
    labeled, _ = ndimage.label(dark_mask)
    border_labels = (
        set(np.unique(labeled[0, :]))
        | set(np.unique(labeled[-1, :]))
        | set(np.unique(labeled[:, 0]))
        | set(np.unique(labeled[:, -1]))
    )
    border_labels.discard(0)

    bg_mask = np.isin(labeled, list(border_labels))
    dilated_bg = ndimage.binary_dilation(bg_mask, iterations=1)
    edge_band = dilated_bg & (~bg_mask)

    alpha = np.full(brightness.shape, 255, dtype=np.uint8)
    alpha[bg_mask] = 0
    alpha[edge_band] = np.clip(
        (brightness[edge_band] - 15) * (255.0 / 180.0), 0, 255
    ).astype(np.uint8)
    arr[:, :, 3] = alpha
    return arr


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY no está configurada en .env")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = genai.Client(api_key=api_key)

    prompt_talk = (
        "Full-body character illustration of a cute, friendly Bolivian Andean Spectacled Bear (Jucumari) "
        "mascot named Jucu, wearing a sleek futuristic NASA-style monochrome space vest with subtle Bolivian "
        "Andean geometric line patterns, a small L-band SAR radar dish antenna on its backpack, and glowing "
        "white spectacle markings around its eyes like high-tech telemetry visor goggles. "
        "The bear is happily dancing and waving one paw in greeting with its mouth open speaking. "
        "Clean vector mascot style, high contrast white and silver lines on a pure solid pitch-black (#000000) background, "
        "centered full body, no text, no watermarks."
    )

    res1 = client.interactions.create(
        model="gemini-nano-banana-2.1",
        input=prompt_talk,
        response_format={"type": "image"},
    )
    img1 = res1.output_image
    if not img1 or not img1.data:
        raise RuntimeError("No se recibió imagen para el fotograma 1")
    raw1 = base64.b64decode(img1.data) if isinstance(img1.data, str) else img1.data
    raw1_b64 = base64.b64encode(raw1).decode("utf-8")

    res2 = client.interactions.create(
        model="gemini-nano-banana-2.1",
        input=[
            {"type": "image", "data": raw1_b64, "mime_type": img1.mime_type or "image/jpeg"},
            {
                "type": "text",
                "text": (
                    "Keep this exact same Bolivian Jucumari bear character, same style, same white sticker outline, "
                    "same space vest, radar dish, and visor on a pure solid pitch-black (#000000) background. "
                    "Change ONLY the expression slightly for a 2-frame talking animation: close its mouth into a happy warm smile."
                ),
            },
        ],
        response_format={"type": "image"},
    )
    img2 = res2.output_image
    if not img2 or not img2.data:
        raise RuntimeError("No se recibió imagen para el fotograma 2")
    raw2 = base64.b64decode(img2.data) if isinstance(img2.data, str) else img2.data

    arr1 = make_rgba(raw1)
    arr2 = make_rgba(raw2)

    union_alpha = np.maximum(arr1[:, :, 3], arr2[:, :, 3])
    ys, xs = np.where(union_alpha > 10)
    pad = 14
    y0, y1 = max(0, int(ys.min()) - pad), min(arr1.shape[0], int(ys.max()) + pad)
    x0, x1 = max(0, int(xs.min()) - pad), min(arr1.shape[1], int(xs.max()) + pad)

    target_h = 520
    target_w = round((x1 - x0) * (target_h / (y1 - y0)))

    for arr, filename in [(arr1, "jucu-talk.webp"), (arr2, "jucu-smile.webp")]:
        cropped = Image.fromarray(arr[y0:y1, x0:x1], "RGBA")
        resized = cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)
        out_path = OUT_DIR / filename
        resized.save(out_path, format="WEBP", quality=92, method=6)
        print(f"[generate-mascot] {filename} guardado ({resized.size}, {out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
