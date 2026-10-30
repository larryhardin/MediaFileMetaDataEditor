import struct
import wave

import pytest
from fastapi.testclient import TestClient

from app.formats import handler_for
from app.formats.riff import read_chunks
from app.main import app


def make_wav(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes(b"\x01\x00" * 800)
    return str(path)


def make_aiff(path):
    comm = b"COMM" + struct.pack(">I", 18) + struct.pack(">hIh", 1, 100, 16) + b"\x40\x0b\xfa\x00\x00\x00\x00\x00\x00\x00"
    ssnd = b"SSND" + struct.pack(">I", 8 + 200) + b"\0" * 8 + b"\0" * 200
    body = b"AIFF" + comm + ssnd
    path.write_bytes(b"FORM" + struct.pack(">I", len(body)) + body)
    return str(path)


def make_mp3(path):
    frame = b"\xff\xfb\x90\x00" + b"\0" * 413
    path.write_bytes(frame * 10)
    return str(path)


def test_wav_roundtrip(tmp_path):
    p = make_wav(tmp_path / "a.wav")
    h = handler_for(p)
    h.write(p, {"common.title": "Hello", "bext.description": "Desc", "bext.originator": "Me",
                "bext.time_reference": "48000", "ixml.SCENE": "12", "xmp.title": "XT",
                "xmp.subject": "a, b", "info.ICOP": "(c) me"})
    v = h.read(p)
    assert v["common.title"] == "Hello" and v["bext.description"] == "Desc"
    assert v["bext.time_reference"] == "48000" and v["ixml.SCENE"] == "12"
    assert v["xmp.title"] == "XT" and v["xmp.subject"] == "a, b" and v["info.ICOP"] == "(c) me"
    with wave.open(p) as w:  # audio still intact
        assert w.getnframes() == 800
    h.write(p, {"common.title": "", "bext.description": "New"})
    v = h.read(p)
    assert v["common.title"] == "" and v["bext.description"] == "New" and v["bext.originator"] == "Me"
    assert read_chunks(p, False, ["bext"])["bext"][:3] == b"New"


def test_aiff_roundtrip(tmp_path):
    p = make_aiff(tmp_path / "a.aiff")
    h = handler_for(p)
    h.write(p, {"common.title": "T", "common.artist": "A", "aiff.NAME": "Nm", "aiff.ANNO": "note", "xmp.creator": "X; Y"})
    v = h.read(p)
    assert (v["common.title"], v["common.artist"], v["aiff.NAME"], v["aiff.ANNO"]) == ("T", "A", "Nm", "note")
    assert v["xmp.creator"] == "X; Y"


def test_mp3_and_sidecar(tmp_path):
    p = make_mp3(tmp_path / "a.mp3")
    h = handler_for(p)
    h.write(p, {"common.title": "T", "common.comment": "c", "id3.TBPM": "120", "xmp.rights": "R"})
    v = h.read(p)
    assert v["common.title"] == "T" and v["common.comment"] == "c" and v["id3.TBPM"] == "120"
    assert v["xmp.rights"] == "R" and (tmp_path / "a.xmp").exists()


def test_api_bulk_preview_apply(tmp_path):
    a, b = make_wav(tmp_path / "a.wav"), make_mp3(tmp_path / "b.mp3")
    c = TestClient(app)
    recs = c.post("/api/read", json={"paths": [a, b]}).json()
    assert all("error" in r is False or "fields" in r for r in recs)
    changes = {"common.album": "Alb", "bext.description": "only wav"}
    prev = c.post("/api/preview", json={"paths": [a, b], "changes": changes}).json()
    assert len(prev[0]["diffs"]) == 2 and prev[1]["skipped"] == ["bext.description"]
    res = c.post("/api/apply", json={"paths": [a, b], "changes": changes}).json()
    assert all(r["ok"] for r in res)
    assert list(tmp_path.glob("a.wav.*.bak"))
    assert handler_for(b).read(b)["common.album"] == "Alb"


def test_rejects_foreign_host():
    assert TestClient(app, base_url="http://evil.example").get("/api/browse").status_code == 403
