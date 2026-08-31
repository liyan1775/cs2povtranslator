# CS2 POV Translator

Local-first guided CLI toolkit for generating bilingual CS2 POV subtitles and per-round Comms Overlay assets from `.dem` / `.dem.zst` demo files.

The project focuses on a practical workflow for CS2 video creators:

1. Parse a CS2 demo.
2. Extract team voice comms.
3. Transcribe audio with local faster-whisper models.
4. Group comms by round.
5. Translate with an OpenAI-compatible LLM.
6. Export bilingual SRT subtitles for video editors, including an editing-friendly max-2 stack policy for Jianying/CapCut-style timelines.
7. Build editable per-round comms review YAML files and render right-middle bilingual overlay assets for Jianying/CapCut.

The current recommended interface is the Windows launcher:

```text
Install_CS2_POV_Translator.bat
Start_CS2_POV_Translator.bat
```

Power-user flow:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[all]"
pytest -q
cs2pov setup-check
cs2pov-wizard
```

The 01D-A/01D-B workspace runtime is now active. Initialize or select a
workspace before running a demo; normal Jobs go to its `jobs/` directory and
model/temp-audio caches stay there too:

```powershell
cs2pov workspace init D:\cs2pov-workspace
cs2pov run D:\demos\match.dem.zst
```

Job paths may be omitted for the normal workspace flow. `--output` is an
explicit, warned legacy-compatibility mode for a temporary external output
root; it does not move or migrate existing Jobs.

Common commands:

```powershell
cs2pov inspect-job
cs2pov explain-output
cs2pov players list
cs2pov players alias --name Ebule --as donk
cs2pov export --preset editing
cs2pov comms build-review --rounds 1-3
cs2pov comms render --rounds 1-3 --formats preview,green
cs2pov retranslate --dry-run
cs2pov resume --from-stage translate
cs2pov feedback
cs2pov models recommend
cs2pov glossary list --map de_mirage --scope all
cs2pov glossary list --map de_dust2 --scope all
cs2pov glossary list --map de_anubis --scope all
```

Chinese documentation is the primary documentation for now: see [README.zh.md](README.zh.md).

## Current status

```text
v0.1.x  Stable pipeline baseline
v0.2.x  Guided CLI product entry
v0.3.x  Job tooling: inspect/export/retranslate/resume/feedback
v0.4.x  Release readiness and user onboarding
v0.5.x  Subtitle export presets and editing experience
v0.6.x  Mirage glossary pilot
v0.7.x  GitHub/readme/docs/release-readiness package
v0.8.x  Model management, ASR profiles, benchmark-asr, global/Dust2/Anubis glossary pilots, K-D-A identity hints, player alias mapping, and max-2 stack editing SRT exports
v0.9.x  Comms Overlay MVP: editable per-round comms YAML and right-middle bilingual overlay assets
```

## Privacy

This is a local-first tool. It does not upload demo files or audio by default. LLM translation sends only the text selected for translation to the configured OpenAI-compatible API endpoint. Feedback packages intentionally exclude raw demo files, large audio artifacts, API keys, and local absolute paths.


## v0.9.8 time display note

Comms Overlay now hides round-clock labels by default. Different platforms and even different rounds can have different freeze/preparation timing, and edited POV footage may not preserve the demo's exact round boundary. The overlay still keeps `show_at_seconds` internally so messages appear in order, but the visible card defaults to `Round + player + bilingual comms`. Experimental time labels are available with `cs2pov comms render --time-display elapsed` or `--time-display round-clock`.
