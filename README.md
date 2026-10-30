# Media File Metadata Editor

Local web UI for editing metadata of media files, individually or in bulk.

## Setup (isolated virtual environment)

Everything is installed into the project's own `.venv` folder. Nothing is installed into your global Python.
Run these from the project folder (PowerShell on Windows):

```powershell
# 1. Create the virtual environment (one time)
python -m venv .venv

# 2. Install dependencies using the venv's own Python (not the global one)
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Run the app
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 4. Run the tests (optional)
.\.venv\Scripts\python.exe -m pytest
```

Then open http://127.0.0.1:8000. The server only accepts localhost requests.

Calling `.\.venv\Scripts\python.exe` directly means you never have to activate anything, so
there's no chance of a command falling back to the global Python. On macOS/Linux use `.venv/bin/python` instead.

Optional: activating the venv (`.\.venv\Scripts\Activate.ps1`) lets you type `python` and `pip` instead,
but check that the prompt shows `(.venv)` before running `pip install`. Never run `pip install` without
the venv active or without using the venv's python path.

To remove everything, delete the `.venv` folder.

## Supported formats

| Type | Frameworks |
|---|---|
| MP3 | ID3v1/v2, XMP sidecar (`name.xmp`) |
| WAV / BWF | BWF `bext`, iXML, RIFF INFO, embedded XMP (`_PMX`); ID3 chunk kept in sync if present |
| AIFF | ID3, AIFF text chunks (NAME/AUTH/(c)/ANNO), embedded XMP (`XMP ` chunk) |
| FLAC / Ogg / Opus | Vorbis comments, XMP sidecar |
| M4A / MP4 | iTunes atoms, XMP sidecar |

Select multiple files to bulk edit the fields common to all of them. Every write goes through a
before/after preview and, by default, a timestamped `.bak` copy. Add a format by implementing
`Handler` in `app/formats` and registering it in `app/formats/__init__.py`.
