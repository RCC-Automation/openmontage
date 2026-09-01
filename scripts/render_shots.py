"""Render shots with Wan in WSL, from the hero stills, and deliver to the Builder.

    .venv/Scripts/python.exe scripts/render_shots.py --project the-man-watches --only sc01 sc02 sc03
    .venv/Scripts/python.exe scripts/render_shots.py --project the-man-watches --dry-run

Why not the Builder
-------------------

VRGDG's Music Video Builder could not render this film's clips - it stalled on
its own internal settings. So the render is driven here instead: the same still
and the same prompt, through Wan 2.2 image-to-video on the WSL install, and the
finished clip copied into the Builder project so its timeline is complete.

Wan lives in WSL because that is 33% faster warm (905 s against 1360 s) and
where its weights are. The Builder project lives on Windows. So every path
crossing that boundary is translated, and the delivered file is copied back
across it - `lib.comfy_routing.to_wsl_paths` exists because a model name with a
backslash silently selects a *different* file on Linux.

Memory
------

A Wan video job peaked at 43.7 GiB when it was measured, on a 63.6 GiB machine
where GPU memory IS system RAM. Both servers may now run at once (Raul,
2026-08-30), but two video jobs never fit. This checks what is available and
says so rather than discovering it as an access violation mid-load.

Length
------

Every shot renders at ITS OWN length, taken from the scene plan. That length
came from the song's measured section boundaries with each cut snapped to a
beat, and the Builder cuts to exactly those numbers - so a clip that is not that
long is either trimmed or leaves a gap.

Frames snap up to 4n+1, the shape Wan's temporal layers expect. Snapping up
means a clip is never short of its slot: a few frames over can be trimmed, a gap
cannot be filled.

`--frames` forces a fixed count and exists only for benchmarking, where every
clip has to be identical to be comparable.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.comfy_routing import to_wsl_paths, upload_image  # noqa: E402
from lib.machine_paths import project_dir, repo_root, wsl_path  # noqa: E402

WORKFLOW = "local_workflows/my_video_wan2_2_14B_i2v.json"

#: 2.39:1 at a size Wan handles. The stills are 1536x640; rendering at their
#: full width would cost memory this machine does not have spare.
WIDTH, HEIGHT = 832, 352
BENCH_FRAMES = 81    # the benchmark configuration, for --frames only
FPS = 16             # what the FLF capability test produced

#: Peak resident memory for a Wan video job, measured (bench-suite, 2026-08-30).
PEAK_GIB = 43.7

#: The shared negative. Every shot in a film renders against the same one, so
#: that a difference between two clips is the prompt and not the recipe.
NEGATIVE = ("static, still, frozen, no motion, flicker, morphing, warping, "
            "extra limbs, deformed hands, watermark, text")


def available_gib() -> float | None:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Counter '\\Memory\\Available MBytes').CounterSamples[0].CookedValue"],
            capture_output=True, text=True, timeout=60)
        return round(float(out.stdout.strip()) / 1024, 1)
    except Exception:
        return None


def frames_for(seconds: float, fps: int = FPS) -> int:
    """Frames for a shot of this length, snapped UP to 4n+1.

    Wan's temporal architecture works in 4n+1 (81 is 4x20+1). Rounding up
    rather than down keeps every clip at least as long as its slot - a frame or
    two over is trimmed by the timeline, a gap is a hole in the film.
    """
    n = int(seconds * fps + 1)
    return n if (n - 1) % 4 == 0 else ((n - 1) // 4 + 1) * 4 + 1


#: Wan 2.2's native clip length. Not a hard limit - `WanImageToVideo.length`
#: accepts up to 16384 - but it is what the model was trained on, and asking it
#: to sample more than this in one window is what makes it loop.
WINDOW = 81
OVERLAP = 30


def last_frame(clip: Path, dest: Path) -> Path:
    """The final frame of a clip, as a PNG for the next segment to start from."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-sseof", "-1", "-i", str(clip),
                    "-update", "1", "-frames:v", "1", str(dest)], check=True)
    return dest


def segment_lengths(total: int, window: int = WINDOW) -> list[int]:
    """Split `total` frames into chained segments of at most `window`.

    Each segment after the first *begins on the previous segment's last frame*,
    so it contributes `length - 1` new frames.

    Segments are **balanced, not greedy**. Filling windows first would split 85
    frames into 81 + 5, and a 5-frame Wan render has no room to produce motion -
    it would join a real shot to a twitch. Equal segments give every one of them
    enough length to move: 85 becomes 45 + 45, and 281 becomes four of 73.

    The last segment may overshoot; the caller trims the join to `total`.
    """
    if total <= window:
        return [total]
    n = -(-(total - 1) // (window - 1))        # fewest segments that reach it
    each = -(-(total - 1) // n) + 1            # even split, then 4n+1
    each += (-(each - 1)) % 4
    return [min(each, window)] * n


def add_context_windows(graph: dict, length: int = WINDOW,
                        overlap: int = OVERLAP) -> int:
    """Patch every sampler's model with `WanContextWindowsManual`.

    **Do not use this for image-to-video.** Kept because it is the right tool
    for text-to-video, and because the reason it is wrong here is worth having
    written down next to it.

    Context windows re-feed the *start image* conditioning into every window, so
    each window generates motion beginning from the still again. On `The Man
    Watches` sc11 the scarf whipped forward, snapped back to its opening
    position at the window seam (frame 52, exactly the 81-30 stride) and
    repeated - Raul's "breaking and repeating". It is architectural, not a
    setting: `retain_first_frame` off does not fix it, because the I2V embed
    reaches every window regardless.

    Use `segment_lengths` + `last_frame` chaining instead, which continues from
    where the previous segment ended rather than restarting.

    Both samplers must be patched when it *is* used. Wan 2.2 splits denoising
    across a high-noise and a low-noise model, and a window applied to only one
    of them leaves the other unwindowed - so this walks every sampler in the
    graph rather than naming node ids, which also survives a re-export.

    Returns the number of samplers patched; 0 means nothing matched and the
    caller should not claim the clip was windowed.
    """
    samplers = [nid for nid, n in graph.items()
                if "KSampler" in (n.get("class_type") or "")
                and isinstance((n.get("inputs") or {}).get("model"), list)]
    nid = max(int(k) for k in graph) + 1
    for sid in samplers:
        graph[str(nid)] = {
            "class_type": "WanContextWindowsManual",
            "inputs": {
                "model": graph[sid]["inputs"]["model"],
                "context_length": length,
                "context_overlap": overlap,
                "context_schedule": "standard_uniform",
                "context_stride": 1,
                "closed_loop": False,
                "fuse_method": "pyramid",
                "freenoise": True,
                "retain_first_frame": True,
                "split_conds_to_windows": False,
            },
        }
        graph[sid]["inputs"]["model"] = [str(nid), 0]
        nid += 1
    return len(samplers)


def queued_prefixes(server: str) -> set[str]:
    """Every `filename_prefix` the server is already running or holding pending.

    The disk check below ("is <sid>.mp4 there?") only protects a *sequential*
    re-run. It cannot see work that is in flight: on 2026-08-31 a killed runner
    and the batch that replaced it both submitted sc01, and the server rendered
    it three times - about 80 minutes of GPU spent on a clip that already
    existed. The queue is the only place that in-flight work is visible, so ask
    it before submitting.

    Returns an empty set when the queue cannot be read. A guard that cannot see
    must not block the shoot; the duplicate is the cheaper failure.
    """
    try:
        q = json.loads(urllib.request.urlopen(f"{server}/queue", timeout=30).read())
    except Exception as exc:
        print(f"  (queue unreadable, duplicate guard off: {exc})")
        return set()
    seen: set[str] = set()
    for bucket in ("queue_running", "queue_pending"):
        for item in q.get(bucket) or []:
            # An entry is [number, prompt_id, graph, extra, outputs]; the graph
            # is the only element whose shape we depend on.
            graph = next((e for e in item if isinstance(e, dict)), {})
            for node in graph.values():
                if not isinstance(node, dict):
                    continue
                prefix = (node.get("inputs") or {}).get("filename_prefix")
                if isinstance(prefix, str):
                    seen.add(prefix)
    return seen


def free_models(server: str) -> None:
    """Unload between scenes. One render should never carry the previous one's
    weights - that accumulation is what left Windows with 1.7 GiB free."""
    try:
        req = urllib.request.Request(
            f"{server}/free",
            data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=120).read()
    except Exception:
        pass


def render(server: str, graph: dict, dest: Path, minutes: float) -> dict:
    graph, _ = to_wsl_paths(graph)
    start = time.time()
    req = urllib.request.Request(f"{server}/prompt",
                                 data=json.dumps({"prompt": graph}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=120).read())["prompt_id"]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            d = json.loads(body)
            errs = [f"node {n} ({v.get('class_type')}): {e.get('details') or e.get('message')}"
                    for n, v in (d.get("node_errors") or {}).items()
                    for e in v.get("errors") or []]
            body = "; ".join(errs) or body
        except Exception:
            pass
        return {"ok": False, "error": body[:300]}

    # Print the FULL id. Truncating it to 8 chars once cost an hour:
    # /history/<8 chars> matches nothing, so a finished render reads
    # as still-running and the clip is never fetched.
    print(f" [{pid}]", end="", flush=True)
    while time.time() - start < minutes * 60:
        try:
            hist = json.loads(urllib.request.urlopen(
                f"{server}/history/{pid}", timeout=60).read())
            if pid in hist:
                break
        except Exception:
            pass
        time.sleep(10)
    else:
        # The prompt keeps running after we stop waiting. Say so, so a re-run
        # does not queue the same work behind it.
        return {"ok": False, "error": f"still running after {minutes:.0f} min",
                "prompt_id": pid}

    entry = hist[pid]
    for node in (entry.get("outputs") or {}).values():
        for kind in ("videos", "gifs", "images"):
            for item in node.get(kind) or []:
                q = urllib.parse.urlencode({
                    "filename": item["filename"], "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output")})
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(urllib.request.urlopen(
                    f"{server}/view?{q}", timeout=1800).read())
                return {"ok": True, "seconds": round(time.time() - start, 1),
                        "prompt_id": pid}
    return {"ok": False, "error": "finished but produced no video",
            "status": (entry.get("status") or {}).get("status_str"), "prompt_id": pid}


def render_chain(args, scene: dict, still: Path, graph_src: dict, frames: int,
                 out: Path, idx: int, total_scenes: int) -> dict:
    """Render a long shot as chained segments and join them.

    Segment 1 starts on the hero still. Every later segment starts on the
    **last frame of the previous one**, so the model is always continuing a
    motion it can see rather than inventing one, and never asked for more than
    its window.

    The join drops each later segment's first frame, because that frame *is*
    the previous segment's last frame - keeping it would stutter.
    """
    sid = scene["id"]
    lengths = segment_lengths(frames)
    work = out / f".{sid}_segments"
    work.mkdir(parents=True, exist_ok=True)
    print(f"  [{idx}/{total_scenes}] {sid} ({frames}f as "
          f"{'+'.join(str(x) for x in lengths)}) ...", flush=True)

    start = still
    parts, spent = [], 0.0
    for n, length in enumerate(lengths, 1):
        graph = json.loads(json.dumps(graph_src))
        graph["97"]["inputs"]["image"] = upload_image(args.server, start)
        graph["165"]["inputs"].update(width=args.width, height=args.height)
        graph["192"]["inputs"]["value"] = round((length - 1) / FPS, 4)
        graph["193"]["inputs"]["value"] = FPS
        graph["171"]["inputs"]["text"] = scene["description"]
        graph["168"]["inputs"]["text"] = NEGATIVE
        # A different seed per segment. The same one re-runs the same motion
        # from a near-identical frame, which is its own kind of repeat.
        graph["181"]["inputs"]["noise_seed"] = 4402 + n
        graph["108"]["inputs"]["filename_prefix"] = f"shots/{sid}_p{n}"

        part = work / f"{sid}_p{n}.mp4"
        wait = args.minutes or max(20.0, length / BENCH_FRAMES * 870 / 60 * 2.5)
        print(f"      segment {n}/{len(lengths)} ({length}f, up to {wait:.0f}m)",
              end="", flush=True)
        r = render(args.server, graph, part, wait)
        if not r.get("ok"):
            return {"ok": False, "error": f"segment {n}: {r.get('error')}",
                    "segments": lengths}
        spent += r.get("seconds", 0)
        print(f" {r['seconds']}s", flush=True)
        parts.append(part)
        if n < len(lengths):
            start = last_frame(part, work / f"{sid}_p{n}_end.png")
            if not args.no_free:
                free_models(args.server)

    # Join: everything from segment 1, then every later segment minus its
    # first frame, then trim to the exact count the slot needs.
    lst = work / "join.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    joined = work / "joined.mp4"
    trimmed = [parts[0]]
    for p in parts[1:]:
        cut = p.with_name(p.stem + "_cut.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p),
                        "-vf", "select='gt(n\\,0)',setpts=N/16/TB",
                        "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
                        str(cut)], check=True)
        trimmed.append(cut)
    lst.write_text("".join(f"file '{p.name}'\n" for p in trimmed), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c:v", "libx264", "-crf", "12",
                    "-pix_fmt", "yuv420p", str(joined)],
                   check=True, cwd=str(work))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(joined),
                    "-frames:v", str(frames), "-c:v", "libx264", "-crf", "12",
                    "-pix_fmt", "yuv420p", str(out / f"{sid}.mp4")], check=True)
    return {"ok": True, "seconds": round(spent, 1), "segments": lengths,
            "segment_dir": str(work)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--only", nargs="+", help="scene ids, e.g. sc01 sc02 sc03")
    ap.add_argument("--server", default="http://127.0.0.1:8189")
    ap.add_argument("--builder", default=None,
                    help="Builder project folder to deliver the clips into")
    ap.add_argument("--frames", type=int, default=None,
                    help="force a fixed frame count. For benchmarking "
                         "only - a real shot renders at its own length")
    ap.add_argument("--width", type=int, default=WIDTH)
    ap.add_argument("--height", type=int, default=HEIGHT)
    # A 209-frame clip takes ~48 min at the measured rate. 45 marked two
    # finished renders as FAILED and one of them was recovered by hand.
    # The wait must scale with the work, not be a constant.
    ap.add_argument("--minutes", type=float, default=None,
                    help="wait per shot. Default scales with frame count.")
    ap.add_argument("--isolate", action="store_true",
                    help="run each scene in its own process, so a crash costs "
                         "one scene and not the rest of the shoot")
    ap.add_argument("--long", choices=("chain", "window", "single"),
                    default="chain",
                    help="how to render past Wan's %d-frame window. 'chain' "
                         "renders segments that each start on the previous "
                         "one's last frame (the only one that keeps motion "
                         "continuous for i2v); 'window' uses context windows "
                         "(t2v only - it restarts the shot every window); "
                         "'single' asks the model for the whole clip and lets "
                         "it loop" % WINDOW)
    ap.add_argument("--stop-file", default=None,
                    help="path checked between scenes; when it appears the "
                         "shoot finishes the scene in hand and stops. Defaults "
                         "to <project>/artifacts/STOP")
    ap.add_argument("--force", action="store_true",
                    help="re-render scenes whose clip already exists")
    ap.add_argument("--no-free", action="store_true",
                    help="do not unload models between scenes")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    project = project_dir(args.project)
    plan = json.loads((project / "artifacts" / "scene_plan.json").read_text(encoding="utf-8"))
    scenes = plan["scenes"]
    if args.only:
        want = set(args.only)
        scenes = [s for s in scenes if s["id"] in want]

    # Per-scene negative terms live in the plan, not in this script, so they
    # travel with the film and survive a re-run of the batch. The scene schema
    # forbids extra keys; `metadata` does not.
    negatives = (plan.get("metadata") or {}).get("negative_prompt_overrides") or {}

    heroes = project / "scene_look" / "heroes"
    out = project / "assets" / "video"
    out.mkdir(parents=True, exist_ok=True)
    graph_src = json.loads((repo_root() / WORKFLOW).read_text(encoding="utf-8"))

    free = available_gib()
    total_frames = (args.frames * len(scenes) if args.frames
                    else sum(frames_for(s["end_seconds"] - s["start_seconds"])
                             for s in scenes))
    print(f"{len(scenes)} shot(s), {args.width}x{args.height}, "
          + (f"{args.frames} frames each (FIXED - benchmark mode)"
             if args.frames else "each at its own length")
          + f"\n{total_frames} frames total, ~"
          f"{total_frames / BENCH_FRAMES * 870 / 3600:.1f} h at the measured rate")
    print(f"memory: {free} GiB available, a Wan video job peaked at {PEAK_GIB} GiB "
          "when measured\n")
    if free is not None and free < PEAK_GIB:
        print(f"  !! {free} GiB is below the measured peak. GPU memory here is system\n"
              "     RAM and loading into too little has crashed the backend mid-load.\n"
              "     Proceeding anyway - the failure mode is a crashed server, not lost work.\n")

    ledger = project / "artifacts" / "shoot_log.jsonl"

    # Already done? Skip. A shoot is hours long and gets interrupted.
    if not args.force:
        before = len(scenes)
        scenes = [s for s in scenes if not (out / f"{s['id']}.mp4").exists()]
        if before != len(scenes):
            print(f"{before - len(scenes)} already rendered, skipping those\n")

        # ...and skip what the server is already working on. Disk cannot see
        # a render that is in flight; the queue can.
        if not args.dry_run:
            in_flight = queued_prefixes(args.server)
            busy = [s for s in scenes if f"shots/{s['id']}" in in_flight]
            if busy:
                print(f"{len(busy)} already queued on the server, skipping those: "
                      f"{', '.join(s['id'] for s in busy)}\n")
                scenes = [s for s in scenes if s not in busy]
    if not scenes:
        print("nothing left to render")
        return 0

    # One process per scene. A failure inside one cannot reach the others -
    # not an OOM kill, not a crashed server, not a killed shell.
    if args.isolate and not args.dry_run:
        import subprocess as sp
        # Asked for between scenes, never mid-scene. Killing a runner does not
        # stop the render - that happens on the server, and the clip is lost
        # rather than saved. So stopping means "submit nothing more", and the
        # scene in hand is allowed to land.
        stop = Path(args.stop_file) if args.stop_file else (
            project / "artifacts" / "STOP")
        done, failed = [], []
        for i, s in enumerate(scenes, 1):
            sid = s["id"]
            if stop.exists():
                print(f"\nSTOP file at {stop} - finishing here.\n"
                      f"{len(done)} rendered this run, {len(scenes) - i + 1} "
                      "not started. Delete the file and re-run to continue.",
                      flush=True)
                break
            print(f"\n=== [{i}/{len(scenes)}] {sid} "
                  f"({available_gib()} GiB available) ===", flush=True)
            cmd = [sys.executable, __file__, "--project", project.name,
                   "--only", sid, "--server", args.server,
                   "--width", str(args.width), "--height", str(args.height),
                   "--minutes", str(args.minutes or 0)]
            if args.frames:
                cmd += ["--frames", str(args.frames)]
            if args.builder:
                cmd += ["--builder", args.builder]
            rc = sp.run(cmd).returncode
            (done if rc == 0 else failed).append(sid)
            if not args.no_free:
                free_models(args.server)
        print(f"\n{len(done)} rendered, {len(failed)} failed"
              + (f": {', '.join(failed)}" if failed else ""))
        print("Re-run the same command to retry only what failed.")
        return 0 if not failed else 1

    rows = []
    for i, s in enumerate(scenes, 1):
        sid = s["id"]
        still = heroes / f"{sid}.png"
        if not still.exists():
            print(f"  {sid}: no hero still")
            continue
        want_s = s["end_seconds"] - s["start_seconds"]
        if args.frames:
            frames = args.frames
            secs = frames / FPS
        else:
            frames = frames_for(want_s)
            secs = frames / FPS
        gap = (f"{want_s:.2f} s slot -> {frames} frames = {secs:.2f} s"
               + ("" if secs >= want_s else "  !! SHORT"))

        if args.dry_run:
            print(f"  {sid}  {gap}")
            print(f"        {s['description'][:100]}")
            continue

        # A clip longer than the window is rendered as chained segments, each
        # starting on the last frame of the one before, then joined. Nothing
        # here asks the model for more than it was trained on, which is why the
        # motion continues instead of restarting.
        if frames > WINDOW and args.long == "chain":
            r = render_chain(args, s, still, graph_src, frames, out, i, len(scenes))
            r.update(id=sid, engine="wan_i2v chained", platform="wsl",
                     frames=frames, clip_seconds=round(secs, 2),
                     shot_seconds=round(want_s, 2))
            print(f" -> {sid}.mp4" if r.get("ok")
                  else f" FAILED: {str(r.get('error'))[:90]}")
            ledger.parent.mkdir(parents=True, exist_ok=True)
            with ledger.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(r) + "\n")
            rows.append(r)
            continue

        graph = json.loads(json.dumps(graph_src))
        # Uploading contacts the server, so it happens AFTER the dry-run
        # bail: a plan should never need the renderer to be up.
        # Uploading contacts the server, so it must happen AFTER the dry-run
        # bail - a plan should never need the renderer to be up.
        graph["97"]["inputs"]["image"] = upload_image(args.server, still)
        graph["165"]["inputs"].update(width=args.width, height=args.height)
        # Node 194 computes length as floor(seconds * fps + 1) from 192 and
        # 193, so the duration is what is set and the frame count follows.
        graph["192"]["inputs"]["value"] = round((frames - 1) / FPS, 4)
        graph["193"]["inputs"]["value"] = FPS
        graph["171"]["inputs"]["text"] = s["description"]
        # A scene may add its own negative terms. sc02's truck oscillated -
        # grew, shrank, grew - because the prompt asked it to approach and to
        # never arrive at once; naming the reverse motion is the cheap fix, and
        # DECISIONS #42 says reach for the negative prompt before the machinery.
        # Scoped per scene rather than folded into NEGATIVE so the other shots
        # keep rendering against the recipe sc01 and sc03 were rendered with.
        extra = (negatives.get(sid) or "").strip()
        graph["168"]["inputs"]["text"] = f"{NEGATIVE}, {extra}" if extra else NEGATIVE
        graph["181"]["inputs"]["noise_seed"] = 4402
        graph["108"]["inputs"]["filename_prefix"] = f"shots/{sid}"

        windowed = 0
        if args.long == "window" and frames > WINDOW:
            windowed = add_context_windows(graph)
            if not windowed:
                print(f"  {sid}: no sampler matched, NOT windowed")

        dest = out / f"{sid}.mp4"
        if args.dry_run:
            print(f"  {sid}  {gap}\n        {s['description'][:110]}")
            continue

        # 870 s for 81 frames measured, x2.5 headroom, never under 20 min.
        wait = args.minutes or max(20.0, frames / BENCH_FRAMES * 870 / 60 * 2.5)
        print(f"  [{i}/{len(scenes)}] {sid} ({frames}f"
              + (f", {windowed}x windowed" if windowed else "")
              + f", up to {wait:.0f}m) ...", end="", flush=True)
        r = render(args.server, graph, dest, wait)
        r.update(id=sid, engine="wan_i2v", platform="wsl", frames=frames,
                 clip_seconds=round(secs, 2), shot_seconds=round(want_s, 2))
        if windowed:
            r["context_windows"] = {"samplers": windowed, "length": WINDOW,
                                    "overlap": OVERLAP}
        if extra:
            # Which shots were rendered against a different negative, and what
            # it was. Without this the ledger says two clips share a recipe
            # when they do not.
            r["negative_extra"] = extra
        print(f" {r['seconds']}s -> {dest.name}" if r.get("ok")
              else f" FAILED: {str(r.get('error'))[:90]}")
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(r) + "\n")
        rows.append(r)

    if args.dry_run:
        return 0

    ok = [r for r in rows if r.get("ok")]
    print(f"\n{len(ok)}/{len(rows)} rendered")

    if args.builder and ok:
        target = Path(args.builder) / "rendered_scene_videos"
        target.mkdir(parents=True, exist_ok=True)
        order = [s["id"] for s in plan["scenes"]]
        for r in ok:
            n = order.index(r["id"]) + 1
            landed = target / f"scene_{n:04d}.mp4"
            shutil.copyfile(out / f"{r['id']}.mp4", landed)
            print(f"  {r['id']} -> {landed}")

    for r in rows:
        if r.get("ok"):
            print(f"  {r['id']}: shot {r['shot_seconds']} s, clip "
                  f"{r['clip_seconds']:.2f} s")
    return 0 if len(ok) == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
