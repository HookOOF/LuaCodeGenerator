#!/usr/bin/env python3
"""VRAM peak usage monitor for LocalScript system.

Polls nvidia-smi at configurable intervals, tracks peak memory per GPU,
and optionally sends a test request to the /generate endpoint to measure
VRAM under load.

Usage:
    # Monitor only (press Ctrl+C to stop and see report):
    python scripts/monitor_vram.py

    # Monitor + send a test request to measure peak during generation:
    python scripts/monitor_vram.py --test-endpoint http://localhost:18080/generate

    # Custom poll interval and output:
    python scripts/monitor_vram.py --interval 0.1 --output vram_report.json

    # Monitor a specific GPU:
    python scripts/monitor_vram.py --gpu-id 0
"""

from __future__ import annotations

import argparse
import csv
import json
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path


@dataclass
class GPUSnapshot:
    timestamp: float
    gpu_id: int
    name: str
    memory_used_mb: float
    memory_total_mb: float
    utilization_pct: int


@dataclass
class GPUStats:
    gpu_id: int
    name: str
    memory_total_mb: float
    peak_memory_mb: float = 0.0
    peak_timestamp: float = 0.0
    samples: int = 0
    sum_memory_mb: float = 0.0
    history: list[tuple[float, float]] = field(default_factory=list)

    @property
    def avg_memory_mb(self) -> float:
        return self.sum_memory_mb / self.samples if self.samples > 0 else 0.0

    def update(self, snapshot: GPUSnapshot) -> None:
        self.samples += 1
        self.sum_memory_mb += snapshot.memory_used_mb
        self.history.append((snapshot.timestamp, snapshot.memory_used_mb))
        if snapshot.memory_used_mb > self.peak_memory_mb:
            self.peak_memory_mb = snapshot.memory_used_mb
            self.peak_timestamp = snapshot.timestamp


def query_nvidia_smi() -> list[GPUSnapshot]:
    """Query nvidia-smi for current GPU memory usage."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []

        now = time.time()
        snapshots = []
        reader = csv.reader(StringIO(result.stdout.strip()))
        for row in reader:
            if len(row) < 5:
                continue
            snapshots.append(GPUSnapshot(
                timestamp=now,
                gpu_id=int(row[0].strip()),
                name=row[1].strip(),
                memory_used_mb=float(row[2].strip()),
                memory_total_mb=float(row[3].strip()),
                utilization_pct=int(row[4].strip()),
            ))
        return snapshots
    except FileNotFoundError:
        print("ERROR: nvidia-smi not found. Is NVIDIA driver installed?", file=sys.stderr)
        return []
    except subprocess.TimeoutExpired:
        return []


class VRAMMonitor:
    """Continuously polls GPU memory and tracks peak usage."""

    def __init__(self, interval: float = 0.2, gpu_id: int | None = None):
        self.interval = interval
        self.gpu_id = gpu_id
        self._stats: dict[int, GPUStats] = {}
        self._running = False
        self._thread: threading.Thread | None = None
        self._start_time: float = 0.0
        self._lock = threading.Lock()

    def start(self) -> None:
        self._running = True
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self) -> None:
        while self._running:
            snapshots = query_nvidia_smi()
            with self._lock:
                for snap in snapshots:
                    if self.gpu_id is not None and snap.gpu_id != self.gpu_id:
                        continue
                    if snap.gpu_id not in self._stats:
                        self._stats[snap.gpu_id] = GPUStats(
                            gpu_id=snap.gpu_id,
                            name=snap.name,
                            memory_total_mb=snap.memory_total_mb,
                        )
                    self._stats[snap.gpu_id].update(snap)
            time.sleep(self.interval)

    def get_stats(self) -> dict[int, GPUStats]:
        with self._lock:
            return dict(self._stats)

    def get_report(self) -> dict:
        elapsed = time.time() - self._start_time
        stats = self.get_stats()
        gpus = []
        for gid in sorted(stats):
            s = stats[gid]
            gpus.append({
                "gpu_id": gid,
                "name": s.name,
                "memory_total_mb": s.memory_total_mb,
                "memory_total_gb": round(s.memory_total_mb / 1024, 2),
                "peak_memory_mb": s.peak_memory_mb,
                "peak_memory_gb": round(s.peak_memory_mb / 1024, 2),
                "avg_memory_mb": round(s.avg_memory_mb, 1),
                "peak_utilization_pct": round(s.peak_memory_mb / s.memory_total_mb * 100, 1)
                if s.memory_total_mb > 0 else 0,
                "samples": s.samples,
                "within_8gb_limit": s.peak_memory_mb <= 8192,
            })

        return {
            "monitoring_duration_sec": round(elapsed, 1),
            "poll_interval_sec": self.interval,
            "gpus": gpus,
            "overall_pass": all(g["within_8gb_limit"] for g in gpus),
        }

    def print_live(self) -> None:
        stats = self.get_stats()
        if not stats:
            return
        parts = []
        for gid in sorted(stats):
            s = stats[gid]
            current = s.history[-1][1] if s.history else 0
            parts.append(
                f"GPU{gid}: {current:.0f}/{s.peak_memory_mb:.0f} MB "
                f"(peak {s.peak_memory_mb / 1024:.2f} GB)"
            )
        elapsed = time.time() - self._start_time
        sys.stdout.write(f"\r[{elapsed:6.1f}s] {' | '.join(parts)}    ")
        sys.stdout.flush()


def send_test_request(endpoint: str, prompt: str | None = None) -> dict:
    """Send a test /generate request and return the response."""
    import urllib.request

    if prompt is None:
        prompt = (
            'Из полученного списка email получи последний.\n'
            '{"wf":{"vars":{"emails":["user1@example.com","user2@example.com","user3@example.com"]}}}'
        )

    payload = json.dumps({"prompt": prompt}).encode()
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    print(f"\nSending test request to {endpoint}...")
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = json.loads(resp.read())
            elapsed = time.time() - start
            print(f"Response received in {elapsed:.1f}s")
            return {"success": True, "elapsed_sec": round(elapsed, 1), "response": body}
    except Exception as exc:
        elapsed = time.time() - start
        print(f"Request failed after {elapsed:.1f}s: {exc}")
        return {"success": False, "elapsed_sec": round(elapsed, 1), "error": str(exc)}


def print_report(report: dict) -> None:
    print("\n" + "=" * 60)
    print("VRAM MONITORING REPORT")
    print("=" * 60)
    print(f"Duration: {report['monitoring_duration_sec']}s")
    print(f"Poll interval: {report['poll_interval_sec']}s")
    print()

    for gpu in report["gpus"]:
        status = "PASS" if gpu["within_8gb_limit"] else "FAIL"
        print(f"  GPU {gpu['gpu_id']}: {gpu['name']}")
        print(f"    Total VRAM:   {gpu['memory_total_mb']:.0f} MB ({gpu['memory_total_gb']:.2f} GB)")
        print(f"    Peak VRAM:    {gpu['peak_memory_mb']:.0f} MB ({gpu['peak_memory_gb']:.2f} GB)")
        print(f"    Avg VRAM:     {gpu['avg_memory_mb']:.0f} MB")
        print(f"    Peak usage:   {gpu['peak_utilization_pct']:.1f}%")
        print(f"    Samples:      {gpu['samples']}")
        print(f"    8 GB limit:   [{status}]")
        print()

    overall = "PASS" if report["overall_pass"] else "FAIL"
    print(f"  Overall 8 GB check: [{overall}]")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Monitor peak VRAM usage during LocalScript operation",
    )
    parser.add_argument(
        "--interval", type=float, default=0.2,
        help="Polling interval in seconds (default: 0.2)",
    )
    parser.add_argument(
        "--gpu-id", type=int, default=None,
        help="Monitor only this GPU index (default: all)",
    )
    parser.add_argument(
        "--test-endpoint", type=str, default=None,
        help="URL of /generate endpoint to send a test request (e.g. http://localhost:18080/generate)",
    )
    parser.add_argument(
        "--test-prompt", type=str, default=None,
        help="Custom prompt to send with --test-endpoint",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Save JSON report to this file",
    )
    parser.add_argument(
        "--duration", type=float, default=None,
        help="Run for this many seconds then stop (default: until Ctrl+C or test completes)",
    )
    args = parser.parse_args()

    initial = query_nvidia_smi()
    if not initial:
        print("No NVIDIA GPUs detected or nvidia-smi unavailable.", file=sys.stderr)
        sys.exit(1)

    print("Starting VRAM monitor...")
    for snap in initial:
        if args.gpu_id is not None and snap.gpu_id != args.gpu_id:
            continue
        print(f"  GPU {snap.gpu_id}: {snap.name} — "
              f"{snap.memory_used_mb:.0f}/{snap.memory_total_mb:.0f} MB")

    monitor = VRAMMonitor(interval=args.interval, gpu_id=args.gpu_id)
    monitor.start()

    stop_event = threading.Event()

    def handle_signal(sig, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    test_result = None

    if args.test_endpoint:
        print(f"\nMonitoring VRAM while sending request to {args.test_endpoint}...")
        test_result = send_test_request(args.test_endpoint, args.test_prompt)
        time.sleep(1)
    elif args.duration:
        print(f"\nMonitoring for {args.duration}s (Ctrl+C to stop early)...")
        deadline = time.time() + args.duration
        while not stop_event.is_set() and time.time() < deadline:
            monitor.print_live()
            stop_event.wait(0.5)
    else:
        print("\nMonitoring (press Ctrl+C to stop and see report)...")
        while not stop_event.is_set():
            monitor.print_live()
            stop_event.wait(0.5)

    monitor.stop()
    print()

    report = monitor.get_report()
    if test_result:
        report["test_request"] = test_result

    print_report(report)

    if args.output:
        out_path = Path(args.output)
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nReport saved to {out_path}")

    sys.exit(0 if report["overall_pass"] else 1)


if __name__ == "__main__":
    main()
