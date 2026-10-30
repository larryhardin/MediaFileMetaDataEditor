import os

from .base import Handler
from .riff import AiffHandler, WavHandler
from .simple import Mp3Handler, Mp4Handler, VorbisHandler

HANDLERS = [Mp3Handler(), WavHandler(), AiffHandler(), VorbisHandler(), Mp4Handler()]
BY_EXT = {ext: h for h in HANDLERS for ext in h.exts}


def handler_for(path) -> Handler | None:
    return BY_EXT.get(os.path.splitext(path)[1].lower())
