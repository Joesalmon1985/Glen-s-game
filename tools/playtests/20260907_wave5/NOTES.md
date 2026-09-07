# Wave 5 notes (final)

heuristic=True. Ollama was reachable; the five-wave loop used `--heuristic` so the full ten-persona panel could iterate the same day. Logs match the usual layout.

## Exit criteria

- Sleep does not end the run.
- Scene changes lead (slit, door, leaving the cell, washroom) and no longer dump the stale cell paragraph on same-room beats.
- Staff asks are restated (`They are still waiting: step away from the door`).
- Accept route: cooperative_serious → `research`, `contract=ACCEPT`.
- Refuse + invert: obstructive → Hell, `player_final_intent=REFUSE`, `actual_contract_response=ACCEPT`.
- Language is use-based: language_maximalist 33/10 attempts; look/wait-heavy personas stay near 17/1.
- Cosmetic names differ by seed and are independent of role.

## No further mechanical improvements this loop

One prosecutor hit per persona remains (template narrator / book-dungeon movement claims). It is not a new facility leak and does not bury transitions or misread the contract.

Waves: `tools/playtests/20260907_wave1` … `20260907_wave5`.
