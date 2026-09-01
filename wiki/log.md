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
- 2026-08-29 compile: practice/the-song.md - ACE-Step at 150 s, tempo accuracy, and the sub-second-line check that film 1 lacked
## [2026-08-29] compile | character/choosing-a-mechanism | four identity mechanisms ranked in one run: swap 0.77-0.79, Klein ref 0.72, FaceID 0.62-0.70, LoRA 0.36-0.39, any description 0.18-0.42
## [2026-08-29] measure | character/faceid-on-this-machine | the embedding path DOES survive a framing change: 0.696 at full body where Klein reference went unmeasurable. Closes that page's open question
## [2026-08-29] measure | character/what-we-measured | 19 models incl. Qwen-Image 2512 cannot render her from her description; best 0.418, Qwen 8th at 0.399. The ceiling is text-to-image, not this pool
## [2026-08-29] compile | character/measuring-identity | face-fraction gate: refuse to score identity below 1% of frame. 7 of 18 full-body cells unscoreable, one negative
## [2026-08-29] correct | practice/prompting | RETRACTS the ControlNet recommendation for subject count. Crowd terms in the negative fix it 3-for-3, free and faster; pose control with a verified single-skeleton map did not
## [2026-08-29] correct | practice/prompting | RETRACTS 'several models ignored full body and gave a medium shot'. All 18 obeyed the framing; the failure was subject count
## [2026-08-29] compile | comfyui/image-recipes | Qwen-Image 2512 as a sixth family, 24.2 s warm at 1664x928; and the cfg-1.0 consequence - 10 of 19 models have no working negative prompt
## [2026-08-29] measure | vrgdg/routes | Krea-2 and ERNIE rendered for the first time: 129.6 s / 422.1 s / 78.8 s against Z-Image standalone at 14.1 s. Builder-native, worth having, not worth a render loop
## [2026-08-29] compile | vrgdg/routes | stub filled: the three route classes, the seven image routes, and the three-alias chain Krea-2 needed before it would build
- 2026-08-30 compile: comfyui/two-platforms.md - the engine split measured across three workloads, the mmap flag, and the both-at-once crash
- 2026-08-30 compile: comfyui/two-platforms.md - Wan weights moved to WSL only (116.5 GiB), routing in lib/comfy_routing.py, launcher scripts
## [2026-08-30] compile | practice/checkpoints | gates run live on the-man-watches, DECISIONS #43
## [2026-08-30] compile | character/placing-her | 10 renders, the negative prompt wins again (DECISIONS #42)
## [2026-08-31] compile | practice/directing-the-generator | the word-ratio mechanism, 4 failures, 2 levers
## [2026-08-31] compile | comfyui/wsl-memory | memory=96GB on 63.6 GiB; 26.5 GiB reclaimed
## [2026-08-31] compile | practice/cutting-to-the-song | beat snap 12->29 of 33; true-length clips 11% cheaper
## [2026-08-31] compile | practice/directing-the-generator | word-ratio mechanism, 4 failures, 2 levers
## [2026-08-31] compile | character/placing-her | live negative puts her at 57 px; 6 of 19 models have one
## [2026-09-01] compile | practice/directing-the-generator | Wan loops past its window; 8 of 10 long clips held, the 2 that broke asked for a completing event
## [2026-09-01] compile | character/video-identity | stub filled: stills 0.48-0.84 vs clips 0.09-0.76; swap the clip, +0.31 to +0.52
## [2026-09-01] compile | practice/directing-the-generator | context windows restart i2v every window; chaining seams at every join; the stretch is what survives
## [2026-09-01] compile | character/video-identity | framing rule: toward camera, upright, unoccluded — sc06 -0.02→0.85, sc27 0.04→0.84, sc08 0.09→0.80
## [2026-09-01] compile | character/video-identity | inswapper is 128x128: a close-up gets half the frame's detail and reads as vibration. Strength per shot size; sc16/sc31/sc15 off, sc08 40%, sc18 70%
