# Wiki log

Append-only. Newest at the bottom. One line per ingest, compile or lint.
Never rewrite an entry — a wrong one gets a later entry correcting it.

Format: `## [YYYY-MM-DD] <op> | <what> | <note>`

---

## [2026-08-25] schema  | CONVENTIONS.md, index.md, log.md | wiki created on the Karpathy LLM-wiki pattern
## [2026-08-25] compile | comfyui/this-machine.md | from HANDOFF.md and the OOM crash of this date
## [2026-08-25] compile | character/what-we-measured.md | from DECISIONS #24 #29 #30 #33 and casting rounds 1-2
## [2026-08-25] compile | character/measuring-identity.md | from DECISIONS #27 #28 #31 and the calibrated axes
## [2026-08-25] compile | character/lora-training.md | from research wf_1deb0755, survey:character-lora + rocm-training
## [2026-08-25] compile | character/reference-conditioning.md | from survey:reference-conditioning + identity-adapters-2026
## [2026-08-25] compile | character/dataset-bootstrap.md | from survey:dataset-craft
## [2026-08-25] compile | character/techniques.md | hand-written synthesis; the synthesis agent failed twice
## [2026-08-25] correct | comfyui/this-machine.md | bitsandbytes DOES work; AOTriton flag measured 8.2x / 24x. HANDOFF was wrong.
## [2026-08-25] compile | character/runbook-first-lora.md | the executable path, machine state verified against disk
## [2026-08-25] execute | runbook phase 0 | AOTriton flag set at User scope; needs a ComfyUI restart
## [2026-08-25] execute | runbook phase 1 | insightface + FaceID PlusV2 installed and verified running on CPU provider
## [2026-08-25] correct | runbook phase 1 | ComfyUI venv has onnxruntime-GPU not plain onnxruntime; install insightface with --no-deps
