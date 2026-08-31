---
title: WSL memory — why it ate the machine, and the config that stops it
status: measured
updated: 2026-08-31
sources: [https://devblogs.microsoft.com/commandline/memory-reclaim-in-the-windows-subsystem-for-linux-2/, https://github.com/microsoft/WSL/issues/13542]
---

# WSL memory — why it ate the machine, and the config that stops it

GPU memory on this machine **is** system RAM (AMD Strix Halo, unified). So WSL's
memory cap is simultaneously the ceiling on what a render may use and the amount
Windows is denied. The two have to be budgeted together, and for weeks they were
not budgeted at all.

Related: [two platforms](two-platforms.md) · [this machine](this-machine.md)

---

## What we know

### The cause was a configuration error, not a WSL quirk

`C:\Users\<user>\.wslconfig` contained:

```ini
[wsl2]
memory=96GB
swap=16GB
```

**96 GB on a machine with 63.6 GiB of physical RAM.** WSL was told it could use
150% of the machine, so it never met memory pressure, never stopped growing, and
simply took until Windows was down to **1.7 GiB available**. There was no
`autoMemoryReclaim`, so roughly 26 GiB of page cache holding model weights was
never handed back either.

The symptom that led here: `/free` on the WSL server released 11 GiB *inside*
torch and returned **0.3 GiB** to Windows, while `/free` on Windows returned
14.6 GiB. That asymmetry looked like a WSL defect. It was a missing cap.

### Measured, on this machine

| | before | after |
|---|---|---|
| WSL ceiling | 96 GB | 48 GB |
| WSL reports internally | 62 GiB | 47 GiB |
| Windows available, idle | 1.7 GiB | **45.5 GiB** |
| reclaimed by `wsl --shutdown` | — | **26.5 GiB**, instantly |

### The config that works here

```ini
[wsl2]
memory=48GB          # a Wan video job peaked at 43.7 GiB; this clears it
swap=8GB             # a backstop, not working space

[experimental]
autoMemoryReclaim=gradual
sparseVhd=true
```

`memory` and `swap` belong in `[wsl2]`; `autoMemoryReclaim` and `sparseVhd` in
`[experimental]`. Values for `autoMemoryReclaim` are `gradual`, `dropcache` or
`disabled` — `gradual` releases cached memory back to Windows after roughly five
minutes idle.

### What each setting is buying

- **`memory=48GB`** is the whole fix. It is the number that makes WSL feel
  pressure and reclaim rather than grow. **Never set it above physical RAM.**
- **`autoMemoryReclaim=gradual`** returns the page cache without a shutdown.
  Without it, `wsl --shutdown` is the only thing that reclaims anything —
  and that kills the ComfyUI server with it.
- **`swap`** exists so an overshoot fails slowly instead of being OOM-killed.
  It is not working space: swapping a 27 GB model is unusably slow.

---

## What it costs

The cap is 48 GiB and a Wan video job peaked at **43.7 GiB**. It fits, and not
by much. If a render is OOM-killed, raise the cap to 52 and accept less Windows
headroom — do not remove the cap.

---

## Traps

**Keys are rejected silently-ish.** On WSL 2.7.11, `sparseVhd` under `[wsl2]`
and `pageReporting` anywhere produce `wsl: Unknown key ...` on the next
`wsl` invocation and are then ignored. The warning is easy to miss because it is
UTF-16 and scrolls past; check `free -g` inside WSL to confirm the cap actually
bound.

**`autoMemoryReclaim=gradual` has been reported to break WSLg GUI apps**
([microsoft/WSL#13542](https://github.com/microsoft/WSL/issues/13542)). Nothing
here runs a GUI inside WSL — ComfyUI is headless and viewed from a Windows
browser — so it does not apply, but it would to a desktop app.

**`FreePhysicalMemory` is not the render's ceiling.** WSL holds its allocation
from Windows whether or not it is using it, so Windows can report 12 GiB free
while a WSL render has 30 GiB of room. Read `free -g` inside WSL for what a
render can actually take.

**`wsl --shutdown` kills the ComfyUI server.** Restart it with `setsid`, or it
dies with the launching shell:

```bash
setsid nohup env HSA_ENABLE_DXG_DETECTION=1 \
  LD_LIBRARY_PATH=/usr/lib/wsl/lib:$LD_LIBRARY_PATH \
  ~/comfy-venv/bin/python ~/ComfyUI/main.py --listen 0.0.0.0 --port 8189 \
  </dev/null > ~/comfyui.log 2>&1 & disown
```

A plain `nohup ... &` from `wsl.exe -- bash -lc` starts and then dies, leaving no
log — which reads as "it never started".

---

## Open questions

- **Does `gradual` reclaim fast enough between shots?** A 34-shot run unloads
  models between scenes; whether the cache is returned before the next scene
  loads is unmeasured. If not, `dropcache` is the more aggressive option.
- **Is 48 GiB right, or is it just big enough?** The 43.7 GiB peak was measured
  at 640×640×81. Longer clips (209 frames) have not been profiled for peak
  memory, only for wall-clock.
