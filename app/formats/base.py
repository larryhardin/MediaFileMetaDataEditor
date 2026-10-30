import os

COMMON_LABELS = {
    "title": "Title",
    "artist": "Artist",
    "album": "Album",
    "albumartist": "Album Artist",
    "genre": "Genre",
    "date": "Date / Year",
    "track": "Track",
    "disc": "Disc",
    "composer": "Composer",
    "comment": "Comment",
}


def field(key, label, group):
    return {"key": key, "label": label, "group": group}


def common_fields(keys, group="Common"):
    return [field(f"common.{k}", COMMON_LABELS[k], group) for k in keys]


def sidecar_path(path):
    return os.path.splitext(path)[0] + ".xmp"


class Handler:
    label = ""
    exts = ()

    def schema(self):
        raise NotImplementedError

    def read(self, path):
        raise NotImplementedError

    def write(self, path, changes):
        raise NotImplementedError
