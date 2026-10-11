"""Flat-file cache keyed by a canonical hash of the request."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

import numpy as np


def request_key(request: dict) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()[:24]


class Cache:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def path(self, namespace: str, request: dict, suffix: str = ".npz") -> Path:
        return self.root / namespace / (request_key(request) + suffix)

    def get_or_compute(self, namespace: str, request: dict, compute: Callable[[], dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
        """`compute` returns a dict of arrays; stored compressed. Sidecar .json records the request."""
        p = self.path(namespace, request)
        if p.exists():
            with np.load(p, allow_pickle=False) as z:
                return {k: z[k] for k in z.files}
        arrays = compute()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **arrays)
        tmp.replace(p)  # atomic: never leave a half-written entry
        p.with_suffix(".json").write_text(json.dumps(request, sort_keys=True, default=str, indent=1))
        return arrays

    def file(self, namespace: str, name: str) -> Path:
        p = self.root / namespace / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
