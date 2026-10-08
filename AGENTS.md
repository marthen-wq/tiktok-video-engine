# AGENTS.md — Instructions for AI coding agents

Project: TikTok Shorts Video Engine. Start with `CLAUDE.md`, then `ARCHITECTURE-ESSENTIALS.md`. Check `MEMORY.md` for decisions and open questions before changing behaviour.

## Layout
- `generator.py` — single-file engine, `main()` runs the pipeline serially.
- `.github/workflows/generate.yml` — CI runner (Ubuntu, Python 3.10, 15 min timeout).
- `tests/test_sequencing.py` — offline tests (`python3 -m unittest discover -s tests -v`).
- Docs: `PRD.md`, `ARCHITECTURE.md`, `ARCHITECTURE-ESSENTIALS.md`, `MEMORY.md`, `CLAUDE.md`.

## Commands
```bash
python3 -m py_compile generator.py                 # syntax check
python3 -m unittest discover -s tests -v           # tests (needs ffmpeg, requests)
QUOTE_INPUT="Teks uji" python3 generator.py        # local run, skips Google Sheets
```

## Rules
1. **Verify before claiming.** Run the tests after touching `generator.py`. If something could not be run (network, credentials, edge-tts), say so; do not describe it as working.
2. **Degrade, except with no footage at all.** A failed clip or BGM download falls back and the render continues. If every clip fails, `prepare_background_video` raises so the run goes red and the Sheet row stays `READY` (owner's decision).
3. **Sequencing invariant.** Background length must equal `total`: `n*seg - (n-1)*xf == total`, with 3–4 clips. Keep `plan_sequence` tests green.
4. **Secrets.** Never print, log or commit `GCP_SERVICE_ACCOUNT_KEY` or other secrets. Do not add a credentials file to the repo.
5. **Subprocess safety.** Call `ffmpeg`/`ffprobe` with argument lists, never `shell=True`; quote text comes from the Sheet and is untrusted.
6. **Style.** Match the file: Indonesian log messages and comments, `[*]` progress, `[+]` success, `[!]` warning. Keep `generator.py` importable without Google packages (imports live inside `get_sheets_service`).
7. **Docs stay true.** When behaviour changes, update `ARCHITECTURE.md` (and the Essentials summary if a critical decision changed), the "real vs. not yet" list in `CLAUDE.md`, and add a dated entry to `MEMORY.md`.
9. **No paid services.** Never add or propose a paid API/service unless the owner explicitly says they want to pay. Prefer free, keyless sources.
10. **Footage follows the narration.** Do not offer alternative themes; footage must match what is being said.
8. **Git.** Work on the branch you were given; do not push to `main` or open a PR unless asked. Commit messages: imperative, one concern per commit.

## Do not
- Rewrite the pipeline wholesale; make targeted changes.
- Add heavy dependencies (e.g. PyTorch via Whisper) without a measured need, since install time counts against the 15 minute limit.
- Change the Sheet column contract (A quote, B environment, E result, F status) without updating `ARCHITECTURE.md` section 4.1.

## Known open work (see PRD roadmap)
Tune ducking levels by ear, optional per-word `\k` highlight, footage by Sheet column B, clickable artifact link and `DONE` after upload, verified footage/BGM sources, larger footage pool (currently 3 URLs for up to 4 clips).
