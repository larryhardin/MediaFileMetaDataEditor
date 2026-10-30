"""RIFF/WAVE (BWF, iXML, INFO, XMP, ID3) and AIFF/IFF (text chunks, XMP, ID3) handlers."""
import os
import struct
import xml.etree.ElementTree as ET

from mutagen.aiff import AIFF
from mutagen.wave import WAVE

from . import id3 as id3mod
from . import xmp
from .base import Handler, common_fields, field

MAX_META_CHUNK = 16 * 1024 * 1024


# ---------------------------------------------------------------- chunk I/O
def _chunk_key(f, cid, size, pos):
    name = cid.decode("latin-1")
    if name == "LIST" and size >= 4:
        f.seek(pos + 8)
        return "LIST:" + f.read(4).decode("latin-1")
    return name


def _iter_chunks(f, size, be):
    pos = 12
    while pos + 8 <= size:
        f.seek(pos)
        cid = f.read(4)
        (sz,) = struct.unpack(">I" if be else "<I", f.read(4))
        yield pos, cid, sz
        pos += 8 + sz + (sz & 1)


def read_chunks(path, big_endian, keys):
    """Return {key: payload bytes} for the first occurrence of each requested chunk key."""
    out = {}
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        for pos, cid, sz in _iter_chunks(f, size, big_endian):
            key = _chunk_key(f, cid, sz, pos)
            if key in keys and key not in out and sz <= MAX_META_CHUNK:
                f.seek(pos + 8)
                out[key] = f.read(sz)
    return out


def _chunk_id(key):
    return b"LIST" if key.startswith("LIST:") else key.encode("latin-1")


def rewrite_chunks(path, big_endian, repl, after=None):
    """Stream-copy `path`, replacing/removing chunks named in `repl` (key -> payload or None).

    Chunks missing from the file are appended at the end, except the keys listed in
    `after=(chunk_id, [keys])`, which are inserted right after that chunk.
    """
    fmt = ">I" if big_endian else "<I"
    tmp = path + ".tmp"
    done = set()

    def emit(dst, key):
        done.add(key)
        payload = repl[key]
        if payload is None:
            return
        dst.write(_chunk_id(key) + struct.pack(fmt, len(payload)) + payload)
        if len(payload) & 1:
            dst.write(b"\0")

    try:
        with open(path, "rb") as src, open(tmp, "wb") as dst:
            src.seek(0, 2)
            size = src.tell()
            src.seek(0)
            dst.write(src.read(12))
            for pos, cid, sz in _iter_chunks(src, size, big_endian):
                key = _chunk_key(src, cid, sz, pos)
                if key in repl:
                    if key not in done:
                        emit(dst, key)
                else:
                    src.seek(pos)
                    remaining = min(8 + sz + (sz & 1), size - pos)
                    while remaining > 0:
                        block = src.read(min(remaining, 1 << 20))
                        if not block:
                            break
                        dst.write(block)
                        remaining -= len(block)
                if after and cid == after[0]:
                    for k in after[1]:
                        if k in repl and k not in done:
                            emit(dst, k)
            for key in repl:
                if key not in done:
                    emit(dst, key)
            end = dst.tell()
            dst.seek(4)
            dst.write(struct.pack(fmt, end - 8))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ---------------------------------------------------------------- BWF bext
BEXT_FIELDS = {
    "bext.description": ("Description", 0, 256),
    "bext.originator": ("Originator", 256, 32),
    "bext.originator_reference": ("Originator Reference", 288, 32),
    "bext.origination_date": ("Origination Date (yyyy-mm-dd)", 320, 10),
    "bext.origination_time": ("Origination Time (hh:mm:ss)", 330, 8),
}
BEXT_TIMEREF = (338, 8)
BEXT_FIXED = 602


def _str(b):
    return b.split(b"\0", 1)[0].decode("latin-1").rstrip()


def bext_read(data):
    out = {k: "" for k in BEXT_FIELDS}
    out["bext.time_reference"] = ""
    out["bext.coding_history"] = ""
    if not data or len(data) < BEXT_FIXED:
        return out
    for k, (_, off, ln) in BEXT_FIELDS.items():
        out[k] = _str(data[off:off + ln])
    out["bext.time_reference"] = str(struct.unpack("<Q", data[338:346])[0])
    out["bext.coding_history"] = data[BEXT_FIXED:].split(b"\0", 1)[0].decode("latin-1").replace("\r\n", "\n")
    return out


def bext_apply(data, changes):
    buf = bytearray(data[:BEXT_FIXED]) if data and len(data) >= BEXT_FIXED else bytearray(BEXT_FIXED)
    if not data or len(data) < BEXT_FIXED:
        buf[346:348] = struct.pack("<H", 1)
    history = data[BEXT_FIXED:] if data and len(data) > BEXT_FIXED else b""
    for key, value in changes.items():
        if key in BEXT_FIELDS:
            _, off, ln = BEXT_FIELDS[key]
            raw = value.encode("latin-1", "replace")[:ln]
            buf[off:off + ln] = raw.ljust(ln, b"\0")
        elif key == "bext.time_reference":
            n = int(value or 0)
            buf[338:346] = struct.pack("<Q", n)
        elif key == "bext.coding_history":
            history = value.replace("\n", "\r\n").encode("latin-1", "replace")
    return bytes(buf) + history


BEXT_SCHEMA = [field(k, v[0], "BWF bext") for k, v in BEXT_FIELDS.items()] + [
    field("bext.time_reference", "Time Reference (samples since midnight)", "BWF bext"),
    field("bext.coding_history", "Coding History", "BWF bext"),
]

# ---------------------------------------------------------------- iXML
IXML_KEYS = {
    "ixml.PROJECT": "Project",
    "ixml.SCENE": "Scene",
    "ixml.TAPE": "Tape",
    "ixml.TAKE": "Take",
    "ixml.NOTE": "Note",
}
IXML_SCHEMA = [field(k, v, "iXML") for k, v in IXML_KEYS.items()]


def ixml_read(data):
    out = {k: "" for k in IXML_KEYS}
    if not data:
        return out
    try:
        root = ET.fromstring(data.rstrip(b"\0"))
    except ET.ParseError:
        return out
    for k in IXML_KEYS:
        el = root.find(k[5:])
        out[k] = (el.text or "").strip() if el is not None else ""
    return out


def ixml_apply(data, changes):
    if data:
        try:
            root = ET.fromstring(data.rstrip(b"\0"))
        except ET.ParseError as e:
            raise ValueError(f"existing iXML chunk is not valid XML: {e}")
    else:
        root = ET.Element("BWFXML")
        ET.SubElement(root, "IXML_VERSION").text = "1.5"
    for key, value in changes.items():
        tag = key[5:]
        el = root.find(tag)
        if not value:
            if el is not None:
                root.remove(el)
            continue
        if el is None:
            el = ET.SubElement(root, tag)
        el.text = value
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------- RIFF INFO
INFO_COMMON = {
    "title": "INAM",
    "artist": "IART",
    "album": "IPRD",
    "genre": "IGNR",
    "date": "ICRD",
    "track": "ITRK",
    "comment": "ICMT",
    "composer": "IMUS",
}
INFO_EXTRA = {
    "info.ICOP": "Copyright (ICOP)",
    "info.ISFT": "Software (ISFT)",
    "info.IENG": "Engineer (IENG)",
    "info.ISRC": "Source (ISRC)",
}


def info_parse(data):
    items = []  # preserves unknown ids and order
    if not data or data[:4] != b"INFO":
        return items
    pos = 4
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4].decode("latin-1")
        (sz,) = struct.unpack("<I", data[pos + 4:pos + 8])
        raw = data[pos + 8:pos + 8 + sz]
        items.append([cid, raw.split(b"\0", 1)[0].decode("utf-8", "replace")])
        pos += 8 + sz + (sz & 1)
    return items


def info_build(items):
    out = bytearray(b"INFO")
    for cid, text in items:
        raw = text.encode("utf-8") + b"\0"
        out += cid.encode("latin-1") + struct.pack("<I", len(raw)) + raw
        if len(raw) & 1:
            out += b"\0"
    return bytes(out)


def info_apply(data, changes):
    items = info_parse(data)
    for cid, value in changes.items():
        items = [i for i in items if i[0] != cid]
        if value:
            items.append([cid, value])
    return info_build(items) if items else None


# ---------------------------------------------------------------- WAV
class WavHandler(Handler):
    label = "WAV (BWF bext, iXML, RIFF INFO, XMP, ID3)"
    exts = (".wav", ".bwf")
    KEYS = ("bext", "iXML", "LIST:INFO", "_PMX")

    def schema(self):
        extra = [field(k, v, "RIFF INFO") for k, v in INFO_EXTRA.items()]
        return common_fields(INFO_COMMON) + extra + BEXT_SCHEMA + IXML_SCHEMA + xmp.XMP_SCHEMA

    def read(self, path):
        chunks = read_chunks(path, False, self.KEYS)
        info = dict(info_parse(chunks.get("LIST:INFO")))
        id3_values = id3mod.read(WAVE(path).tags)
        out = {}
        for k, cid in INFO_COMMON.items():
            out[f"common.{k}"] = info.get(cid) or id3_values[f"common.{k}"]
        for k in INFO_EXTRA:
            out[k] = info.get(k[5:], "")
        out.update(bext_read(chunks.get("bext")))
        out.update(ixml_read(chunks.get("iXML")))
        out.update(xmp.read(chunks.get("_PMX")))
        return out

    def write(self, path, changes):
        chunks = read_chunks(path, False, self.KEYS)
        repl = {}
        info_changes = {}
        for k, v in changes.items():
            if k.startswith("common."):
                info_changes[INFO_COMMON[k[7:]]] = v
            elif k.startswith("info."):
                info_changes[k[5:]] = v
        if info_changes:
            repl["LIST:INFO"] = info_apply(chunks.get("LIST:INFO"), info_changes)
        for prefix, key, fn in (("bext.", "bext", bext_apply), ("ixml.", "iXML", ixml_apply), ("xmp.", "_PMX", xmp.apply)):
            sub = {k: v for k, v in changes.items() if k.startswith(prefix)}
            if sub:
                repl[key] = fn(chunks.get(key), sub)
        if repl:
            rewrite_chunks(path, False, repl, after=(b"fmt ", ["bext"]))
        common = {k: v for k, v in changes.items() if k.startswith("common.")}
        if common:
            audio = WAVE(path)
            if audio.tags is not None:  # keep an existing ID3 chunk in sync
                id3mod.write(audio.tags, common)
                audio.save()


# ---------------------------------------------------------------- AIFF
AIFF_TEXT = {
    "aiff.NAME": ("Name (NAME)", "NAME"),
    "aiff.AUTH": ("Author (AUTH)", "AUTH"),
    "aiff.COPY": ("Copyright ((c))", "(c) "),
    "aiff.ANNO": ("Annotation (ANNO)", "ANNO"),
}


class AiffHandler(Handler):
    label = "AIFF (ID3, AIFF text chunks, XMP)"
    exts = (".aif", ".aiff", ".aifc")

    def schema(self):
        native = [field(k, v[0], "AIFF Chunks") for k, v in AIFF_TEXT.items()]
        return id3mod.SCHEMA + native + xmp.XMP_SCHEMA

    def read(self, path):
        chunks = read_chunks(path, True, [v[1] for v in AIFF_TEXT.values()] + ["XMP "])
        out = id3mod.read(AIFF(path).tags)
        for k, (_, cid) in AIFF_TEXT.items():
            out[k] = _str(chunks.get(cid, b""))
        out.update(xmp.read(chunks.get("XMP ")))
        return out

    def write(self, path, changes):
        repl = {}
        chunks = None
        for k, v in changes.items():
            if k in AIFF_TEXT:
                repl[AIFF_TEXT[k][1]] = v.encode("latin-1", "replace") if v else None
            elif k.startswith("xmp."):
                chunks = chunks or read_chunks(path, True, ["XMP "])
                sub = {a: b for a, b in changes.items() if a.startswith("xmp.")}
                repl["XMP "] = xmp.apply(chunks.get("XMP "), sub)
        if repl:
            rewrite_chunks(path, True, repl)
        own = {k: v for k, v in changes.items() if k.startswith("common.") or k.startswith("id3.")}
        if own:
            audio = AIFF(path)
            if audio.tags is None:
                audio.add_tags()
            id3mod.write(audio.tags, own)
            audio.save()
