"""Restart the dashboard whenever the code changes.

The dashboard builds the graph from the codebook once, when it starts, so a
change to the code shows only after a restart. This runs the server as a child
process and restarts it whenever a file under appeals/ changes. Standard
library only: it compares modification times once a second.
"""
from pathlib import Path
import subprocess
import sys
import time

WATCHED = Path(__file__).resolve().parents[1]          # the appeals package
SUFFIXES = {'.py', '.toml'}


def _snapshot():
    files = [p for p in WATCHED.rglob('*') if p.suffix in SUFFIXES and '__pycache__' not in p.parts]
    files.append(WATCHED.parent / 'config.toml')
    return {p: p.stat().st_mtime for p in files if p.exists()}


def run(args):
    """Run `appeals <args>` and restart it on every change; stop on Ctrl-C."""
    command = [sys.executable, '-m', 'appeals', *args]
    seen = _snapshot()
    child = subprocess.Popen(command)
    try:
        while True:
            time.sleep(1)
            now = _snapshot()
            if now != seen:
                changed = sorted(str(p.relative_to(WATCHED.parent)) for p in set(now) ^ set(seen) | {
                    p for p in now if p in seen and now[p] != seen[p]})
                seen = now
                print(f'code changed ({", ".join(changed[:3])}{"…" if len(changed) > 3 else ""}): restarting the dashboard',
                      flush=True)
                child.terminate()
                child.wait()
                child = subprocess.Popen(command)
            elif child.poll() is not None:
                time.sleep(1)                            # it crashed, e.g. on a syntax error: retry after the next change
    except KeyboardInterrupt:
        pass
    finally:
        child.terminate()
        child.wait()
