# Wave 1 notes

heuristic=True (Ollama reachable; full-panel iteration uses heuristic so five waves can complete).

## Findings

- cooperative_serious reached `contract` but `yes` landed during the interview, so the offer was never signed.
- Several personas parked in `sleep` without waking (fatigue gate too slow).
- Refuse paths reached Heaven but often not Hell / second offer (heaven_turns / time gates too high).
- No persona reached `research`. Stay-in-Hell invert not exercised.

## Fixes before wave 2

- Auto-wake from sleep after 90s in phase.
- Faster Day 2+ gates; interview wait advances two questions; Heaven/Hell expire after 2 turns.
- Keep contract yes/no handling on explanation as well as the offer.
