# Wave 2 notes

## Improvements

- cooperative_serious reached `research` (immediate accept route works).
- Sleep now wakes; `slept=True` on nearly every persona.

## Remaining

- Refuse paths stop at `prep_transfer` or `heaven_expire` (thresholds still too high relative to remaining actions).
- Wait-heavy personas still mid-interview.

## Fixes before wave 3

- Refuse sets `phase_entered_at` so preparation immediately continues into Heaven.
- Heaven expire → Hell after 15s.
- Day 2 retrieval after 15s.
