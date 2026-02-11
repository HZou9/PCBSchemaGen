import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

os.environ.setdefault("PYTHONBREAKPOINT", "0")

STAGE_KEYS = [
    "t_llm_request",
    "t_parse_extract",
    "t_syntax_check",
    "t_erc_runtime",
    "t_topology_verify",
    "t_svg_generate",
    "t_artifacts_generate",
    "t_write_outputs",
]
STAGE_LABELS = {
    "t_llm_request": "llm",
    "t_parse_extract": "parse",
    "t_syntax_check": "syntax",
    "t_erc_runtime": "erc",
    "t_topology_verify": "topo",
    "t_svg_generate": "svg",
    "t_artifacts_generate": "artifacts",
    "t_write_outputs": "write",
}


def _safe_model_name(model):
    return model.replace("/", "_").replace(":", "-")


def _load_tasks(benchmark_path):
    tasks = []
    with open(benchmark_path, "r", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            try:
                tasks.append(int(row["Id"]))
            except Exception:
                continue
    return tasks


def _parse_task_range(text):
    if "-" in text:
        parts = text.split("-", 1)
    elif ":" in text:
        parts = text.split(":", 1)
    else:
        raise ValueError("task-range must be like 1-16")
    start = int(parts[0].strip())
    end = int(parts[1].strip())
    if start > end:
        start, end = end, start
    return list(range(start, end + 1))


def _parse_task_ids(text):
    ids = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        ids.append(int(item))
    return ids


def _select_tasks(args, benchmark_path):
    available = _load_tasks(benchmark_path)
    available_set = set(available)
    tasks = available
    if args.task_range:
        tasks = _parse_task_range(args.task_range)
    if args.task_ids:
        tasks = _parse_task_ids(args.task_ids)
    tasks = [t for t in tasks if t in available_set]
    return sorted(set(tasks))


def _comb(n, k):
    if n < k:
        return 0
    return math.comb(n, k)


def _pass_at_5(c, n=15):
    if c <= 0:
        return 0.0
    if n - c < 5:
        return 1.0
    return 1.0 - (_comb(n - c, 5) / _comb(n, 5))


def _append_summary(summary_path, rows, lock):
    header = [
        "task",
        "feedback",
        "prompt_mode",
        "trial",
        "status",
        "attempts",
        "duration",
        "prompt_tokens",
        "completion_tokens",
        "cost",
    ]
    with lock:
        write_header = not os.path.exists(summary_path)
        with open(summary_path, "a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(header)
            writer.writerows(rows)


def _append_task_timing(timing_path, row, lock):
    header = [
        "task",
        "feedback",
        "trials",
        "duration_seconds",
        "start_time",
        "end_time",
    ]
    with lock:
        write_header = not os.path.exists(timing_path)
        with open(timing_path, "a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(header)
            writer.writerow(row)


def _prune_results_dir(results_dir, task_id, attempts):
    keep = {f"task_{task_id}_stats.json"}
    svg_target = None
    if attempts:
        svg_target = f"attempt_{attempts}.svg"
    svg_candidates = []

    for name in os.listdir(results_dir):
        if name.startswith("attempt_") and name.endswith("_skidl.py"):
            keep.add(name)
        if name.startswith("attempt_") and name.endswith(".svg"):
            svg_candidates.append(name)

    if svg_target and svg_target in svg_candidates:
        keep.add(svg_target)
    elif svg_candidates:
        def _idx(s):
            try:
                return int(s.split("_", 2)[1])
            except Exception:
                return -1
        keep.add(max(svg_candidates, key=_idx))

    for name in os.listdir(results_dir):
        if name in keep:
            continue
        path = os.path.join(results_dir, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass


def _parse_stats(stats_path):
    with open(stats_path, "r") as f:
        stats = json.load(f)
    parsed = {
        "status": stats.get("status", "FAIL"),
        "attempts": stats.get("attempts", 0),
        "duration": float(stats.get("total_duration_seconds", 0.0)),
        "prompt_tokens": int(stats.get("total_prompt_tokens", 0)),
        "completion_tokens": int(stats.get("total_completion_tokens", 0)),
        "cost": float(stats.get("estimated_cost_usd", 0.0)),
    }
    for key in STAGE_KEYS:
        parsed[key] = float(stats.get(key, 0.0))
    return parsed


def _print_progress(completed, total, start_time):
    elapsed = time.time() - start_time
    rate = completed / elapsed if elapsed > 0 else 0.0
    remaining = total - completed
    eta = remaining / rate if rate > 0 else 0.0
    bar_len = 30
    progress = completed / total if total > 0 else 0.0
    filled = int(bar_len * progress)
    bar = "#" * filled + "-" * (bar_len - filled)
    print(
        f"[{bar}] {completed}/{total} ({progress*100:.1f}%) "
        f"{rate:.2f} trials/s, eta {eta/60:.1f}m",
        flush=True,
    )


def _ignore_task_patterns(dirpath, names):
    """
    Ignore patterns for the task directory to ensure clean workspace.

    Must ignore:
    - feedback_runs/ - previous feedback run results
    - p*_results/ - old task results from direct runs
    - p*_*_trials/ - old trial directories (e.g., p17_gemini_trials)
    - __pycache__/ - Python cache
    - *.json - summary files (all_trials_summary.json, etc.)
    - __init__.erc, __init__.log - stray ERC/log files
    - debug_*.py, reverify_*.py - debug scripts not needed for runs
    - *.svg, *.erc, *.log, *.net, *.kicad_* - stray artifacts
    - skidl_repl* - SKiDL temporary files
    - attempt_*.py, attempt_*.svg - stray attempt files
    - extracted_task_* - stray extraction artifacts
    """
    import re
    ignore = set()

    for name in names:
        # Directories to ignore
        if name == "feedback_runs":
            ignore.add(name)
        elif name == "__pycache__":
            ignore.add(name)
        elif re.match(r'^p\d+_results$', name):
            # p1_results, p17_results, etc.
            ignore.add(name)
        elif re.match(r'^p\d+_\w+_?\d*trials$', name):
            # p17_gemini_trials, p17_glm46_trials, p17_gemini_5trials, etc.
            ignore.add(name)
        # Files to ignore
        elif name.endswith('.json') and name != 'component.json' and name != 'kg_component.json':
            ignore.add(name)
        elif name in ('__init__.erc', '__init__.log'):
            ignore.add(name)
        elif name.startswith('debug_') and name.endswith('.py'):
            ignore.add(name)
        elif name.startswith('reverify_') and name.endswith('.py'):
            ignore.add(name)
        elif name.startswith('skidl_repl'):
            ignore.add(name)
        elif name.startswith('attempt_'):
            ignore.add(name)
        elif name.startswith('extracted_task_'):
            ignore.add(name)
        elif any(name.endswith(ext) for ext in ('.svg', '.erc', '.log', '.net')):
            # Stray artifact files in task root
            ignore.add(name)
        elif '.kicad_' in name:
            # KiCad project files
            ignore.add(name)

    return ignore


def _copy_base_tree(base_dir, dest_root, copy_function=shutil.copy2):
    exclude_files = {"code test results.md"}
    for name in os.listdir(base_dir):
        if name in exclude_files:
            continue
        src = os.path.join(base_dir, name)
        dst = os.path.join(dest_root, name)
        if os.path.isdir(src):
            if name == "task":
                shutil.copytree(
                    src,
                    dst,
                    ignore=_ignore_task_patterns,
                    copy_function=copy_function,
                )
            else:
                shutil.copytree(
                    src,
                    dst,
                    ignore=shutil.ignore_patterns("__pycache__"),
                    copy_function=copy_function,
                )
        else:
            copy_function(src, dst)


def _link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _is_template_stale(template_root):
    """
    Check if template contains stale files that should have been ignored.

    Returns True if template needs to be regenerated.
    """
    import re

    task_dir = os.path.join(template_root, "task")
    if not os.path.isdir(task_dir):
        return False  # No task dir, probably okay

    stale_patterns = [
        # Directories that should not exist in clean template
        (r'^p\d+_results$', True),       # p17_results, etc.
        (r'^p\d+_\w+_?\d*trials$', True), # p17_gemini_trials, p17_gemini_5trials, etc.
        (r'^__pycache__$', True),
        # Files that should not exist
        (r'^__init__\.(erc|log)$', False),
        (r'.*_summary\.json$', False),
        (r'^debug_.*\.py$', False),
        (r'^reverify_.*\.py$', False),
    ]

    for name in os.listdir(task_dir):
        path = os.path.join(task_dir, name)
        for pattern, is_dir in stale_patterns:
            if re.match(pattern, name):
                if is_dir and os.path.isdir(path):
                    return True
                elif not is_dir and os.path.isfile(path):
                    return True

    return False


def _make_workspace(base_dir, workspace_root, template_root=None):
    os.makedirs(workspace_root, exist_ok=True)
    if template_root:
        # Check if template exists but is stale (contains files that should be ignored)
        if os.path.exists(template_root):
            if _is_template_stale(template_root):
                print(f"[WARN] Stale template detected, regenerating: {template_root}")
                shutil.rmtree(template_root, ignore_errors=True)

        if not os.path.exists(template_root):
            os.makedirs(template_root, exist_ok=True)
            _copy_base_tree(base_dir, template_root, copy_function=shutil.copy2)
        shutil.rmtree(workspace_root, ignore_errors=True)
        shutil.copytree(template_root, workspace_root, copy_function=_link_or_copy)
        return
    _copy_base_tree(base_dir, workspace_root, copy_function=shutil.copy2)


def _archive_results(task_dir, trial_dir, task_id):
    src = os.path.join(task_dir, f"p{task_id}_results")
    if not os.path.isdir(src):
        return None
    dest = os.path.join(trial_dir, f"p{task_id}_results")
    os.makedirs(trial_dir, exist_ok=True)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.move(src, dest)
    return dest


def _run_single_trial(args, feedback, task_id, trial, run_root, base_dir, template_root, locks, counters):
    trial_dir = os.path.join(run_root, feedback, f"p{task_id}", f"trial_{trial}")
    workspace_root = os.path.join(
        run_root, "workspaces", feedback, f"p{task_id}", f"trial_{trial}"
    )
    os.makedirs(trial_dir, exist_ok=True)

    _make_workspace(base_dir, workspace_root, template_root=template_root)
    task_dir = os.path.join(workspace_root, "task")
    run_path = os.path.join(task_dir, "run.py")

    cmd = [
        sys.executable,
        run_path,
        "--model",
        args.model,
        "--feedback",
        feedback,
        "--num_of_retry",
        str(args.num_of_retry),
        "--component_info_mode",
        args.component_info_mode,
        "--base_url",
        args.base_url,
        "--task_id",
        str(task_id),
    ]
    if args.artifacts:
        cmd.append("--generate-artifacts")
    else:
        cmd.append("--no-artifacts")
    if args.temperature is not None:
        cmd.extend(["--temperature", str(args.temperature)])
    if args.api_key:
        cmd.extend(["--api_key", args.api_key])
    cmd.extend(["--prompt-mode", args.prompt_mode])

    try:
        proc = subprocess.run(
            cmd,
            cwd=task_dir,
            text=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        _append_summary(
            counters["summary_path"],
            [[task_id, feedback, args.prompt_mode, trial, "MISSING", 0, 0.0, 0, 0, 0.0]],
            locks["summary"],
        )
        if args.clean_trials:
            shutil.rmtree(trial_dir, ignore_errors=True)
        if not args.keep_workspaces:
            shutil.rmtree(workspace_root, ignore_errors=True)
        return False, "missing_workspace"
    log_path = os.path.join(trial_dir, "run.log")
    with open(log_path, "w") as f:
        f.write(proc.stdout + "\n" + proc.stderr)

    results_dir = _archive_results(task_dir, trial_dir, task_id)
    if not results_dir:
        _append_summary(
            counters["summary_path"],
            [[task_id, feedback, args.prompt_mode, trial, "MISSING", 0, 0.0, 0, 0, 0.0]],
            locks["summary"],
        )
        if args.clean_trials:
            shutil.rmtree(trial_dir, ignore_errors=True)
        if not args.keep_workspaces:
            shutil.rmtree(workspace_root, ignore_errors=True)
        return False, "missing_results"

    stats_path = os.path.join(results_dir, f"task_{task_id}_stats.json")
    if not os.path.exists(stats_path):
        _append_summary(
            counters["summary_path"],
            [[task_id, feedback, args.prompt_mode, trial, "MISSING", 0, 0.0, 0, 0, 0.0]],
            locks["summary"],
        )
        if args.clean_trials:
            shutil.rmtree(trial_dir, ignore_errors=True)
        if not args.keep_workspaces:
            shutil.rmtree(workspace_root, ignore_errors=True)
        return False, "missing_stats"

    stats = _parse_stats(stats_path)
    summary_row = [
        task_id,
        feedback,
        args.prompt_mode,
        trial,
        stats["status"],
        stats["attempts"],
        stats["duration"],
        stats["prompt_tokens"],
        stats["completion_tokens"],
        stats["cost"],
    ]
    _append_summary(counters["summary_path"], [summary_row], locks["summary"])

    with locks["totals"]:
        counters["totals"][feedback]["prompt"] += stats["prompt_tokens"]
        counters["totals"][feedback]["completion"] += stats["completion_tokens"]
        counters["totals"][feedback]["duration"] += stats["duration"]
        counters["totals"][feedback]["cost"] += stats["cost"]
        for key in STAGE_KEYS:
            counters["stage_totals"][key] += stats.get(key, 0.0)
        if stats["status"] == "PASS":
            counters["totals"][feedback]["pass"] += 1
            counters["counts"][task_id][feedback] += 1

    if not args.keep_workspaces:
        shutil.rmtree(workspace_root, ignore_errors=True)
    if args.clean_trials:
        _prune_results_dir(results_dir, task_id, stats.get("attempts", 0))

    return True, ""


def _write_results_block(
    results_path,
    model,
    num_of_retry,
    run_root,
    start_time,
    end_time,
    totals,
    counts,
    task_ids,
    stage_totals,
    feedbacks,
):
    task_ids_sorted = sorted(task_ids)
    if task_ids_sorted and task_ids_sorted == list(range(task_ids_sorted[0], task_ids_sorted[-1] + 1)):
        task_span = f"p{task_ids_sorted[0]}~p{task_ids_sorted[-1]}"
    else:
        task_span = ",".join(f"p{task_id}" for task_id in task_ids_sorted)

    lines = []
    lines.append(f"## Experiment: {model} ({task_span}, feedback n=15)")
    lines.append("")
    lines.append(f"Start time: {start_time}")
    lines.append(f"Model: `{model}`")
    lines.append(f"num_of_retry: {num_of_retry}")
    feedback_label = ",".join(feedbacks) if feedbacks else "full"
    if set(feedbacks) == {"full", "weak", "none"}:
        lines.append("Note: 15 trials each for full/weak/none; each trial is a single run (max 3 attempts).")
    else:
        lines.append(f"Note: Only running {feedback_label}; each trial is a single run (max 3 attempts).")
    lines.append(f"Archive directory: `{run_root}`")
    lines.append("")
    lines.append(f"End time: {end_time}")
    for fb in ["full", "weak", "none"]:
        if fb not in totals:
            continue
        data = totals[fb]
        lines.append(
            f"- {fb}: trials {data['trials']}, pass {data['pass']}, "
            f"prompt {data['prompt']}, completion {data['completion']}, "
            f"total tokens {data['prompt'] + data['completion']}, "
            f"duration {data['duration']:.2f}s, cost ${data['cost']:.6f}"
        )
    total_trials = sum(totals[fb]["trials"] for fb in totals)
    total_pass = sum(totals[fb]["pass"] for fb in totals)
    total_prompt = sum(totals[fb]["prompt"] for fb in totals)
    total_completion = sum(totals[fb]["completion"] for fb in totals)
    total_duration = sum(totals[fb]["duration"] for fb in totals)
    total_cost = sum(totals[fb]["cost"] for fb in totals)
    lines.append(
        f"- Total: trials {total_trials}, pass {total_pass}, prompt {total_prompt}, "
        f"completion {total_completion}, total tokens {total_prompt + total_completion}, "
        f"duration {total_duration:.2f}s, cost ${total_cost:.6f}"
    )
    stage_total_sum = sum(stage_totals.values()) if stage_totals else 0.0
    if total_duration > 0 and stage_total_sum > 0:
        parts = []
        for key in STAGE_KEYS:
            pct = (stage_totals.get(key, 0.0) / total_duration) * 100
            parts.append(f"{STAGE_LABELS.get(key, key)} {pct:.1f}%")
        other = max(total_duration - stage_total_sum, 0.0)
        if other > 0.01:
            parts.append(f"other {(other / total_duration) * 100:.1f}%")
        lines.append("Stage time distribution (global): " + ", ".join(parts))
    lines.append("")
    lines.append(
        "### Pass@1 / Pass@5 (n=15, by task x feedback) Pass@5 = 1 - C(15-c,5)/C(15,5)"
    )
    lines.append(
        "| Task | full c/15 | full Pass@1 | full Pass@5 | weak c/15 | weak Pass@1 | weak Pass@5 | none c/15 | none Pass@1 | none Pass@5 |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for task_id in task_ids:
        row = [f"p{task_id}"]
        for fb in ["full", "weak", "none"]:
            if fb not in totals:
                row.extend(["N/A", "N/A", "N/A"])
                continue
            c = counts[task_id][fb]
            row.append(f"{c}/15")
            row.append(f"{c/15:.3f}")
            row.append(f"{_pass_at_5(c, n=15):.3f}")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    os.makedirs(os.path.dirname(results_path), exist_ok=True)
    with open(results_path, "a") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="google/gemini-3-flash-preview")
    parser.add_argument("--num-of-retry", type=int, default=3)
    parser.add_argument("--component-info-mode", type=str, default="kg+component")
    parser.add_argument("--base-url", type=str, default="https://openrouter.ai/api/v1")
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--trials", type=int, default=15)
    parser.add_argument("--feedbacks", type=str, default="full,weak,none")
    parser.add_argument("--task-range", type=str, default=None)
    parser.add_argument("--task-ids", type=str, default=None)
    parser.add_argument("--parallel-threads", type=int, default=1)
    parser.add_argument("--trial-workers", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--artifacts", action="store_true", default=False)
    parser.add_argument(
        "--clean-trials",
        dest="clean_trials",
        action="store_true",
        default=True,
        help="Delete per-trial outputs after stats are recorded (default: true).",
    )
    parser.add_argument(
        "--keep-trials",
        dest="clean_trials",
        action="store_false",
        help="Keep per-trial outputs under feedback_runs/.",
    )
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--keep-workspaces", action="store_true", default=False)
    parser.add_argument("--results-path", type=str, default=None)
    parser.add_argument(
        "--prompt-mode",
        type=str,
        default="auto",
        choices=["auto", "simple"],
        help="Prompt template: auto (P1-16 simple, P17-23 complex), simple (always simple).",
    )
    args = parser.parse_args()

    base_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    benchmark_path = os.path.join(base_dir, "benchmark.tsv")
    task_ids = _select_tasks(args, benchmark_path)
    if not task_ids:
        raise RuntimeError("No tasks selected from benchmark.tsv")

    feedbacks = [fb.strip() for fb in args.feedbacks.split(",") if fb.strip()]
    trials = list(range(1, args.trials + 1))
    trial_workers = args.parallel_threads
    if args.trial_workers is not None:
        trial_workers = args.trial_workers
    trial_workers = max(1, trial_workers)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_model = _safe_model_name(args.model)
    run_root = os.path.join(
        base_dir,
        "task",
        "feedback_runs",
        f"{safe_model}_{args.prompt_mode}_{timestamp}",
    )
    os.makedirs(run_root, exist_ok=True)
    summary_path = os.path.join(run_root, "summary.csv")
    template_root = os.path.join(run_root, "template_workspace")
    os.makedirs(template_root, exist_ok=True)
    _copy_base_tree(base_dir, template_root, copy_function=shutil.copy2)

    start_time = datetime.now(timezone.utc).isoformat()
    total_trials = len(task_ids) * len(feedbacks) * len(trials)
    completed = 0
    start_clock = time.time()

    totals = {
        fb: {
            "trials": len(task_ids) * len(trials),
            "pass": 0,
            "prompt": 0,
            "completion": 0,
            "duration": 0.0,
            "cost": 0.0,
        }
        for fb in feedbacks
    }
    counts = {task_id: {fb: 0 for fb in feedbacks} for task_id in task_ids}

    locks = {
        "summary": threading.Lock(),
        "totals": threading.Lock(),
        "progress": threading.Lock(),
        "timing": threading.Lock(),
    }
    counters = {
        "summary_path": summary_path,
        "totals": totals,
        "counts": counts,
        "stage_totals": {key: 0.0 for key in STAGE_KEYS},
    }
    timing_path = os.path.join(run_root, "task_timings.csv")

    for feedback in feedbacks:
        for task_id in task_ids:
            task_start_clock = time.time()
            task_start_iso = datetime.now(timezone.utc).isoformat()
            print(f"==> feedback {feedback} task p{task_id} (parallel {trial_workers})", flush=True)
            with ThreadPoolExecutor(max_workers=trial_workers) as executor:
                futures = [
                    executor.submit(
                        _run_single_trial,
                        args,
                        feedback,
                        task_id,
                        trial,
                        run_root,
                        base_dir,
                        template_root,
                        locks,
                        counters,
                    )
                    for trial in trials
                ]
                for future in as_completed(futures):
                    _ok, _msg = future.result()
                    with locks["progress"]:
                        completed += 1
                        if completed % 5 == 0 or completed == total_trials:
                            _print_progress(completed, total_trials, start_clock)
            task_end_clock = time.time()
            task_end_iso = datetime.now(timezone.utc).isoformat()
            _append_task_timing(
                timing_path,
                [
                    task_id,
                    feedback,
                    len(trials),
                    round(task_end_clock - task_start_clock, 2),
                    task_start_iso,
                    task_end_iso,
                ],
                locks["timing"],
            )
            print(
                f"==> completed feedback {feedback} task p{task_id} "
                f"in {task_end_clock - task_start_clock:.2f}s",
                flush=True,
            )

    end_time = datetime.now(timezone.utc).isoformat()
    if args.results_path:
        results_path = args.results_path
    else:
        results_path = os.path.join(base_dir, "code test results.md")

    _write_results_block(
        results_path=results_path,
        model=args.model,
        num_of_retry=args.num_of_retry,
        run_root=os.path.relpath(run_root, base_dir),
        start_time=start_time,
        end_time=end_time,
        totals=totals,
        counts=counts,
        task_ids=task_ids,
        stage_totals=counters["stage_totals"],
        feedbacks=feedbacks,
    )


if __name__ == "__main__":
    main()
