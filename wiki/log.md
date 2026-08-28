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
## [2026-08-25] correct | comfyui/this-machine.md | AOTriton gate FAILED on a real render: 75s vs 76s baseline. The 8.2x was isolated SDPA; the extrapolation to rendering was wrong.
## [2026-08-25] lint    | 29 pages clean | session close
## [2026-08-26] compile | practice/seeds | seed distance/magnitude/pattern, saturation, 96 renders
## [2026-08-26] compile | character/faceid-on-this-machine | weight+lora sweep, framing override, realism cost
## [2026-08-26] measure | character/lora-training | first LoRA trained on ROCm: 200 steps 499 s, gate 0.219 -> 0.428; status researched -> measured
## [2026-08-26] compile | comfyui/models | stub -> measured: 34 files by family, drivable/trainable split, both new Base weights byte-verified
## [2026-08-26] compile | comfyui/graph-sources | stub -> measured: the three sources as used, the reference-drop guard, timings
## [2026-08-26] correct | comfyui/graph-sources | Klein is 55-77 s at 832x1216 with a reference, not ~5 s; size now quoted with the number
## [2026-08-26] measure | character/what-we-measured | Klein face-crop -> full body 0.62-0.78 (n=16); face-describing brief 20-37 siblings vs 6-19
## [2026-08-28] compile | character/face-swap | ReActor 0.80-0.88 vs FaceID 0.75-0.84 vs LoRA 0.12-0.46; boost mandatory (sharpness 0.099 -> 0.368)
## [2026-08-28] compile | practice/recasting | replacing a character in a finished VRGDG project: 7 prompt fields + 4 side files, 575+445 edits
## [2026-08-28] compile | vrgdg/video-render | LTX two-pass timings: base 26 s/step, upscale refine 610 s/step; /free is the escape hatch
## [2026-08-28] compile | vrgdg/video-render, vrgdg/traps | final VAE native abort, visual/API decoder mismatch, tiled-256 batch exporter
## [2026-08-28] compile | vrgdg/video-engines | VRGDG-native LTX/H3 and custom Wan/Hunyuan engine adapter research
## [2026-08-28] measure | vrgdg/video-render | unattended scene-5 render and restore: 4.416667 s clip, session marked done
## [2026-08-28] measure | vrgdg/video-render | unattended scenes 6-15 completed; 15/15 videos and thumbnails verified, resumable rerun skipped all
## [2026-08-28] measure | comfyui/image-recipes | 25 renders, 5 families, standalone graphs: Klein 10.6 s, Z-Image 18-28 s (3x the VRGDG route), flux1-dev 52.6 s
## [2026-08-28] compile | comfyui/image-recipes | official recipes read from ComfyUI's installed blueprints; per-family axis matrix
## [2026-08-28] correct | comfyui/this-machine | capacity IS sometimes the constraint: 63.6 GiB system RAM, --disable-mmap, fp8 upcast to bf16
## [2026-08-28] correct | comfyui/models | darkBeast30 is BF16 not INT8 (trainable); both ZPop GGUFs fail to load; Flux.1/Chroma all run; FluxDAIO is schnell-class
## [2026-08-28] compile | comfyui/failure-modes | identical graph returns a 2.0 s cached non-render; second RAM-exhaustion backend kill
## [2026-08-28] compile | practice/image-benchmark | benchmark method: per-family axes, prompt dialects, what may and may not be printed
## [2026-08-28] measure | comfyui/image-recipes | clean warm Z-Image: 14.1 s (n=5, two files); cold after model swap 50-77 s
## [2026-08-28] correct | comfyui/image-recipes | CLIPSetLastLayer -1 is NOT the SDXL default and blacks 3 checkpoints; default == -2, pixel-identical. Retracts the 'never driven correctly' claim made earlier today
## [2026-08-28] correct | comfyui/image-recipes, models | verifier pass: Klein 4-step source named, GGUF claim narrowed to the tested file, fp16-fix VAE claim marked unverified, blueprint provenance split three ways
## [2026-08-28] correct | comfyui/this-machine, failure-modes | t5xxl_fp16 is 9.8 GB not 9.3
## [2026-08-28] correct | practice/image-benchmark | cold-load band replaced with the measured 26-148 s spread; by-model ordering only pays from the standard tier up
