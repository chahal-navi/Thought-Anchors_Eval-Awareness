"""Parallel ranged download of HF repos into ~/models/<name> (the GPU box throttles single connections).

Usage: python pdownload.py Qwen/Qwen3-32B-FP8 google/gemma-4-26B-A4B-it
"""
import os
import queue
import sys
import threading
import time

import requests
from huggingface_hub import HfApi, hf_hub_url

TOKEN = os.environ.get("HF_TOKEN")
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
CHUNK = 32 * 2**20


def fetch(repo, workers=16):
    root = os.path.expanduser(f"~/models/{repo.split('/')[1]}")
    os.makedirs(root, exist_ok=True)
    info = HfApi().model_info(repo, files_metadata=True)
    files = [(s.rfilename, s.size) for s in info.siblings if not s.rfilename.startswith(("every_eval_ever", "."))]
    jobs = queue.Queue()
    for name, size in files:
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) == size and not os.path.exists(path + ".parts"):
            continue
        with open(path, "ab") as f:
            f.truncate(size)
        open(path + ".parts", "w").close()
        for s in range(0, max(size, 1), CHUNK):
            jobs.put((name, path, s, min(s + CHUNK, size) - 1))
    urls = {n: hf_hub_url(repo, n) for n, _ in files}
    done, failed, t0 = [0], [], time.time()

    def worker():
        while True:
            try:
                name, path, s, e = jobs.get_nowait()
            except queue.Empty:
                return
            if e < s:
                continue
            for _ in range(30):
                try:
                    r = requests.get(urls[name], headers={**HEADERS, "Range": f"bytes={s}-{e}"}, timeout=90)
                    r.raise_for_status()
                    assert len(r.content) == e - s + 1, "short read"
                    with open(path, "r+b") as f:
                        f.seek(s)
                        f.write(r.content)
                    done[0] += len(r.content)
                    break
                except Exception:
                    time.sleep(3)
            else:
                failed.append((name, s))

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        time.sleep(30)
        print(f"{repo}: {done[0] / 1e9:.1f} GB, {done[0] / 1e6 / (time.time() - t0):.0f} MB/s", flush=True)
    if failed:
        print("FAILED chunks:", failed[:5], len(failed), flush=True)
        return
    for name, _ in files:
        if os.path.exists(os.path.join(root, name) + ".parts"):
            os.remove(os.path.join(root, name) + ".parts")
    print("DONE", repo, root, flush=True)


for repo in sys.argv[1:]:
    fetch(repo)
print("ALL_DOWNLOADS_DONE", flush=True)
