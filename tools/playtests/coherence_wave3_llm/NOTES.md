# Coherence wave 3 notes (LLM)

Live Ollama (`mistral`) panel: 10 personas + `long_serious`.

## Architecture shipped this loop
- `NarrativeSceneContext` fed into narrator as `scene_context`
- Intention/enactment fields stripped from LLM narrator prompt; prosecutor blocks intention-meta prose
- Stock “room remains / does not hurry” facts replaced with in-scene lines
- Staff motive facts on door refuse/escalate; wash refuse reads as routine force
- Book interrupt strips dungeon bleed facts and leads with return-to-cell
- `scripts/coherence_judge.py` hard-gates player-facing short transcripts

## Gate
`python scripts/coherence_judge.py tools/playtests/coherence_wave3_llm` → **OK, 0 actionable defects** across 11 runs.

Serious benchmark: `long_serious_seed201/short_transcript.txt` — location, presence, door escalation motives, and book→cell interrupt are readable without debug.

## Not pursued further this loop
- Literary compression / less “thin and broken” repetition (style, not comprehension)
- Interpreter accuracy chasing
- Absurd-persona beauty
