import json
import os
import shutil
import string
import subprocess
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .formats import BY_EXT, handler_for

app = FastAPI(title="Media File Metadata Editor")
STATIC = Path(__file__).parent / "static"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "testserver"}


@app.middleware("http")
async def local_only(request: Request, call_next):
    # Blocks DNS-rebinding and cross-site requests against this local file-editing API.
    host = request.headers.get("host", "").rsplit(":", 1)[0].strip("[]")
    if host not in ALLOWED_HOSTS:
        return JSONResponse({"detail": "forbidden host"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin.split("://", 1)[-1].rsplit(":", 1)[0].strip("[]") not in ALLOWED_HOSTS:
        return JSONResponse({"detail": "forbidden origin"}, status_code=403)
    return await call_next(request)


class Files(BaseModel):
    paths: list[str]


class Edit(BaseModel):
    paths: list[str]
    changes: dict[str, str]
    backup: bool = True


def _check(path):
    h = handler_for(path)
    if not h or not os.path.isfile(path):
        raise ValueError("not a supported media file")
    return h


def _read_one(path):
    try:
        h = _check(path)
        return {"path": path, "name": os.path.basename(path), "format": h.label,
                "schema": h.schema(), "fields": h.read(path)}
    except Exception as e:
        return {"path": path, "name": os.path.basename(path), "error": str(e)}


DRIVES = "::drives::"


def _drives():
    if os.name == "nt":
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return [f"{c}:\\" for i, c in enumerate(string.ascii_uppercase) if mask & (1 << i)]
    return ["/"]


# Runs in a child process because Tk must own its main thread.
PICKER = r"""
import json, sys, tkinter as tk
from tkinter import filedialog
mode = sys.argv[1]
exts = " ".join(sys.argv[2:])
root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
if mode == "folder":
    r = filedialog.askdirectory(title="Select folder", mustexist=True)
    out = [r] if r else []
else:
    out = list(filedialog.askopenfilenames(title="Select media files", filetypes=[("Media files", exts), ("All files", "*.*")]))
print(json.dumps(out))
"""


class Pick(BaseModel):
    mode: str = "files"


@app.post("/api/pick")
def pick(body: Pick):
    if body.mode not in ("files", "folder"):
        raise HTTPException(400, "bad mode")
    exts = [f"*{e}" for e in sorted(BY_EXT)]
    try:
        res = subprocess.run([sys.executable, "-c", PICKER, body.mode, *exts],
                             capture_output=True, text=True, timeout=600, check=True)
        paths = json.loads(res.stdout.strip().splitlines()[-1])
    except Exception as e:
        raise HTTPException(500, f"file dialog unavailable: {e}")
    return {"paths": [os.path.normpath(p) for p in paths]}


@app.get("/api/browse")
def browse(path: str = ""):
    if path == DRIVES:
        return {"path": "Drives", "parent": DRIVES, "drives": _drives(), "dirs": [], "files": []}
    p = Path(path or Path.home()).expanduser()
    if not p.is_dir():
        raise HTTPException(404, "not a directory")
    dirs, files = [], []
    try:
        for e in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            if e.name.startswith("."):
                continue
            if e.is_dir():
                dirs.append(e.name)
            elif e.suffix.lower() in BY_EXT:
                files.append(e.name)
    except PermissionError:
        raise HTTPException(403, "permission denied")
    return {"path": str(p.resolve()), "parent": str(p.resolve().parent), "dirs": dirs, "files": files}


@app.post("/api/read")
def read(body: Files):
    return [_read_one(p) for p in body.paths]


@app.post("/api/preview")
def preview(body: Edit):
    out = []
    for p in body.paths:
        item = _read_one(p)
        if "error" in item:
            out.append({"path": p, "name": item["name"], "error": item["error"]})
            continue
        supported = {f["key"] for f in item["schema"]}
        diffs = [{"key": k, "before": item["fields"].get(k, ""), "after": v}
                 for k, v in body.changes.items()
                 if k in supported and item["fields"].get(k, "") != v]
        skipped = [k for k in body.changes if k not in supported]
        out.append({"path": p, "name": item["name"], "diffs": diffs, "skipped": skipped})
    return out


def _backup(path):
    targets = [path]
    sidecar = os.path.splitext(path)[0] + ".xmp"
    if os.path.exists(sidecar):
        targets.append(sidecar)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for t in targets:
        shutil.copy2(t, f"{t}.{stamp}.bak")


@app.post("/api/apply")
def apply(body: Edit):
    results = []
    for p in body.paths:
        try:
            h = _check(p)
            supported = {f["key"] for f in h.schema()}
            before = h.read(p)
            changes = {k: v for k, v in body.changes.items() if k in supported and before.get(k, "") != v}
            if changes:
                if body.backup:
                    _backup(p)
                h.write(p, changes)
            results.append({"path": p, "name": os.path.basename(p), "ok": True, "written": len(changes)})
        except Exception as e:
            results.append({"path": p, "name": os.path.basename(p), "ok": False, "error": str(e)})
    return results


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
