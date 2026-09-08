# Canonical portrait geometry

Authoring-only. These guides must **not** appear in player-facing images.

All face component PNGs are **768 × 768 RGBA** with a transparent background.
Assets in this kit are painted at **192 × 192** and nearest-neighbour scaled ×4 so
features stay on the pixel grid. Coordinates below are in **canonical 768 space**.

## Canvas

| Region | Bounds (x0, y0)–(x1, y1) |
|--------|--------------------------|
| Full canvas | (0, 0)–(768, 768) |
| Portrait safe area | (64, 48)–(704, 736) |
| Hair boundary (max) | (80, 40)–(688, 420) |
| Head mass | roughly (160, 160)–(608, 640) |
| Chin boundary | y ≈ 600–656 |
| Neck / shoulders crop | y ≈ 640–736 |

Head is centred on **x = 384**. Camera is frontal / near-frontal. Scale is consistent
across `face_001`–`face_005`; anatomy (jaw, width, age) varies inside these bands.

## Feature bands

| Band | y range | Notes |
|------|---------|--------|
| Eye line | 320–360 | Pupil centres sit on y ≈ 336–348 |
| Eye band | 300–380 | Whites, lids, irises, inner brows |
| Nose region | 360–480 | Bridge through nostrils |
| Mouth region | 488–568 | Lips; does not change jaw width |
| Brow region | 276–324 | Independent left / right brows |

Left eye centre ≈ **(300, 344)**. Right eye centre ≈ **(468, 344)**.
Individual faces may shift spread by about ±32 px (wide-set vs close-set).
Asymmetry (face_005) may offset one eye by a few pixels; both irises still
travel the **same** direction for a given gaze.

## Gaze offsets (iris, canonical px)

| Gaze | dx | dy |
|------|----|----|
| forward | 0 | 0 |
| left | −28 | 0 |
| right | +28 | 0 |
| up | 0 | −20 |
| down | 0 | +20 |
| away_left | −44 | +8 |
| away_right | +44 | +8 |

Closed eyes omit iris layers entirely.

## Layering

Z-order is **data in each manifest**, never inferred from filenames.
Typical back-to-front: hair_back → ears → head → eye_whites → irises → eyelids
→ nose → mouth_base → mouth → facial_hair → wrinkles / freckles / scars → brows
→ hair_front.

Optional identity layers may be absent. Expression layers replace pose, not identity:
the nose and skull do not change because the mouth smiles.
