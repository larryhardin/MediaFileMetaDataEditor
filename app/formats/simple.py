import os

import mutagen
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

from . import id3 as id3mod
from . import xmp
from .base import Handler, common_fields, field, sidecar_path


def _read_sidecar(path):
    sp = sidecar_path(path)
    if os.path.exists(sp):
        with open(sp, "rb") as f:
            return xmp.read(f.read())
    return xmp.read(None)


def _write_sidecar(path, changes):
    changes = {k: v for k, v in changes.items() if k.startswith("xmp.")}
    if not changes:
        return
    sp = sidecar_path(path)
    existing = None
    if os.path.exists(sp):
        with open(sp, "rb") as f:
            existing = f.read()
    with open(sp, "wb") as f:
        f.write(xmp.apply(existing, changes))


class Mp3Handler(Handler):
    label = "MP3 (ID3v1/v2 + XMP sidecar)"
    exts = (".mp3",)

    def schema(self):
        return id3mod.SCHEMA + xmp.XMP_SCHEMA

    def read(self, path):
        out = id3mod.read(MP3(path).tags)
        out.update(_read_sidecar(path))
        return out

    def write(self, path, changes):
        id3_changes = {k: v for k, v in changes.items() if not k.startswith("xmp.")}
        if id3_changes:
            audio = MP3(path)
            if audio.tags is None:
                audio.add_tags()
            id3mod.write(audio.tags, id3_changes)
            audio.save()
        _write_sidecar(path, changes)


VORBIS_COMMON = {
    "title": "title",
    "artist": "artist",
    "album": "album",
    "albumartist": "albumartist",
    "genre": "genre",
    "date": "date",
    "track": "tracknumber",
    "disc": "discnumber",
    "composer": "composer",
    "comment": "comment",
}
VORBIS_EXTRA = {
    "vorbis.copyright": ("Copyright", "copyright"),
    "vorbis.isrc": ("ISRC", "isrc"),
    "vorbis.organization": ("Organization / Label", "organization"),
}


class VorbisHandler(Handler):
    label = "FLAC / Ogg (Vorbis comments + XMP sidecar)"
    exts = (".flac", ".ogg", ".oga", ".opus")

    def schema(self):
        extra = [field(k, v[0], "Vorbis Comments") for k, v in VORBIS_EXTRA.items()]
        return common_fields(VORBIS_COMMON) + extra + xmp.XMP_SCHEMA

    def _open(self, path):
        audio = mutagen.File(path)
        if audio is None:
            raise ValueError("unsupported or corrupt file")
        if audio.tags is None:
            audio.add_tags()
        return audio

    def read(self, path):
        audio = self._open(path)
        out = {}
        for k, name in VORBIS_COMMON.items():
            out[f"common.{k}"] = "; ".join(audio.tags.get(name, []))
        for k, (_, name) in VORBIS_EXTRA.items():
            out[k] = "; ".join(audio.tags.get(name, []))
        out.update(_read_sidecar(path))
        return out

    def write(self, path, changes):
        own = {k: v for k, v in changes.items() if not k.startswith("xmp.")}
        if own:
            audio = self._open(path)
            for key, value in own.items():
                name = VORBIS_COMMON.get(key[7:]) if key.startswith("common.") else VORBIS_EXTRA.get(key, (0, None))[1]
                if not name:
                    continue
                if value:
                    audio.tags[name] = [value]
                elif name in audio.tags:
                    del audio.tags[name]
            audio.save()
        _write_sidecar(path, changes)


MP4_TEXT = {
    "title": "\xa9nam",
    "artist": "\xa9ART",
    "album": "\xa9alb",
    "albumartist": "aART",
    "genre": "\xa9gen",
    "date": "\xa9day",
    "composer": "\xa9wrt",
    "comment": "\xa9cmt",
}
MP4_PAIRS = {"track": "trkn", "disc": "disk"}
MP4_EXTRA = {
    "mp4.cprt": ("Copyright (cprt)", "cprt"),
    "mp4.desc": ("Description (desc)", "desc"),
    "mp4.\xa9too": ("Encoding Tool (©too)", "\xa9too"),
}


def _parse_pair(value):
    left, _, right = value.partition("/")
    return int(left or 0), int(right or 0)


class Mp4Handler(Handler):
    label = "MP4 / M4A (iTunes atoms + XMP sidecar)"
    exts = (".m4a", ".mp4", ".m4b")

    def schema(self):
        extra = [field(k, v[0], "iTunes Atoms") for k, v in MP4_EXTRA.items()]
        return common_fields([*MP4_TEXT, *MP4_PAIRS]) + extra + xmp.XMP_SCHEMA

    def read(self, path):
        tags = MP4(path).tags or {}
        out = {}
        for k, atom in MP4_TEXT.items():
            out[f"common.{k}"] = "; ".join(str(v) for v in tags.get(atom, []))
        for k, atom in MP4_PAIRS.items():
            val = ""
            pairs = tags.get(atom)
            if pairs:
                n, total = pairs[0]
                val = (f"{n}/{total}" if total else str(n)) if n or total else ""
            out[f"common.{k}"] = val
        for k, (_, atom) in MP4_EXTRA.items():
            out[k] = "; ".join(str(v) for v in tags.get(atom, []))
        out.update(_read_sidecar(path))
        return out

    def write(self, path, changes):
        own = {k: v for k, v in changes.items() if not k.startswith("xmp.")}
        if own:
            audio = MP4(path)
            if audio.tags is None:
                audio.add_tags()
            for key, value in own.items():
                short = key[7:] if key.startswith("common.") else None
                if short in MP4_PAIRS:
                    atom = MP4_PAIRS[short]
                    if value:
                        audio.tags[atom] = [_parse_pair(value)]
                    else:
                        audio.tags.pop(atom, None)
                    continue
                atom = MP4_TEXT.get(short) if short else MP4_EXTRA.get(key, (0, None))[1]
                if not atom:
                    continue
                if value:
                    audio.tags[atom] = [value]
                else:
                    audio.tags.pop(atom, None)
            audio.save()
        _write_sidecar(path, changes)
