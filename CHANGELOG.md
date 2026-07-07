# Changelog

All notable changes to this project will be documented in this file.

## [2.6.0] – 2025

### Added
- **Web upload** – upload HEIC/JPG/PNG photos directly from the browser (including iPhone Safari). Sequential upload with per-file progress indicator (`Uploading 3 / 12: photo.heic`).
- **New album creation on upload** – type a new subfolder name directly in the upload form; the folder is created automatically.
- **Background thumbnail pre-generation** – after every scan, missing thumbnails are generated in a background thread so the slideshow is always responsive. Progress is visible in `/status`.
- **`/status` endpoint** – JSON with last scan time, next scan countdown, total converted count, thumbnail pre-generation progress.
- **`/scan` endpoint (POST)** – triggers an immediate scan without waiting for the interval.
- **"Scan now" button** in the album selection screen.
- **Photo counter overlay** – `12 / 47` shown in the top-right corner of the slideshow.
- **Album cover thumbnails** – album buttons show the first photo of each album as a background image.
- **Photo count per album** – displayed on each album button.
- **Persistent geocoding cache** – GPS reverse-geocoding results are saved to `/data/geocode_cache.json` and survive restarts.
- **LRU EXIF cache** – bounded in-memory cache (250 entries) using `OrderedDict`; prevents unbounded memory growth with large collections.
- **Configurable thumbnail size** (`thumb_max_px`, default 1024) and thumbnail quality (`thumb_quality`, default 82) via addon configuration.
- **Optional HTTP Basic Auth** – set `basic_auth_user` and `basic_auth_password` in configuration to password-protect the web interface.
- **Waitress thread count increased** to 8 to handle concurrent SMB-backed requests.
- **`state.py`** – shared inter-thread state module for scan status and thumbnail pre-generation progress.
- **`.dockerignore`** – excludes `__pycache__` and `.pyc` files from Docker build.

### Fixed
- **Space in generated filename** – duplicate HEIC filenames produced `photo_1. jpg` (with a space); now correctly `photo_1.jpg`.
- **Refresh timer** – previously only updated the photo list when the count *increased*; now always syncs, correctly handling deletions from another client.
- **`bashio::config` returning `"null"`** – new optional config fields return the string `"null"` on existing installations; both `run.sh` and `webserver.py` now handle this gracefully with fallback defaults.
- **JavaScript regex broken by Python string escaping** – replaced regex character class with a character-by-character loop to avoid shell/Python escaping issues.

## [2.0.0] – 2024

### Added
- Recursive subfolder scanning (preserves album structure)
- Fullscreen slideshow web interface optimised for iPad/Safari 9
- EXIF date and GPS location overlay
- Nominatim reverse geocoding with Slovak country name translations
- Album selection screen with random/chronological ordering
- Swipe navigation (left/right = prev/next, swipe down = back)
- Long-press to move photo to trash (`_kos/` subfolder)
- CIFS/SMB auto-mount on addon start
- Configurable scan interval, JPEG quality, slideshow duration

## [1.0.0] – 2024

### Added
- Initial release: watch folder → convert HEIC → save JPG, delete original
