"""ID3v2 helpers shared by MP3, WAV ('id3 ' chunk) and AIFF ('ID3 ' chunk)."""
from mutagen import id3

from .base import common_fields, field

COMMON_FRAMES = {
    "title": "TIT2",
    "artist": "TPE1",
    "album": "TALB",
    "albumartist": "TPE2",
    "genre": "TCON",
    "date": "TDRC",
    "track": "TRCK",
    "disc": "TPOS",
    "composer": "TCOM",
}
EXTRA_FRAMES = {
    "id3.TBPM": ("BPM (TBPM)", "TBPM"),
    "id3.TPUB": ("Publisher (TPUB)", "TPUB"),
    "id3.TCOP": ("Copyright (TCOP)", "TCOP"),
    "id3.TSRC": ("ISRC (TSRC)", "TSRC"),
}

COMMON_KEYS = [*COMMON_FRAMES, "comment"]
EXTRA_SCHEMA = [field(k, v[0], "ID3v2") for k, v in EXTRA_FRAMES.items()]
SCHEMA = common_fields(COMMON_KEYS) + EXTRA_SCHEMA


def read(tags):
    out = {f"common.{k}": "" for k in COMMON_KEYS}
    out.update({k: "" for k in EXTRA_FRAMES})
    if tags is None:
        return out

    def text(frame_id):
        frame = tags.get(frame_id)
        return "; ".join(str(t) for t in frame.text) if frame is not None else ""

    for k, fid in COMMON_FRAMES.items():
        out[f"common.{k}"] = text(fid)
    comms = tags.getall("COMM")
    if comms:
        out["common.comment"] = "\n".join(str(t) for t in comms[0].text)
    for k, (_, fid) in EXTRA_FRAMES.items():
        out[k] = text(fid)
    return out


def write(tags, changes):
    for key, value in changes.items():
        if key == "common.comment":
            tags.delall("COMM")
            if value:
                tags.add(id3.COMM(encoding=3, lang="eng", desc="", text=[value]))
            continue
        if key.startswith("common."):
            fid = COMMON_FRAMES.get(key[7:])
        else:
            fid = EXTRA_FRAMES.get(key, (None, None))[1]
        if not fid:
            continue
        tags.delall(fid)
        if value:
            tags.add(getattr(id3, fid)(encoding=3, text=[value]))
