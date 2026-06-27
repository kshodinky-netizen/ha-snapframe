# SnapFrame – HEIC Photo Slideshow for Home Assistant

A Home Assistant addon that monitors a Samba/CIFS share for HEIC photos (uploaded from iPhone), converts them to JPG, and serves a beautiful fullscreen slideshow optimised for **iPad / Safari**.

---

## Features

- 📸 **Automatic HEIC → JPG conversion** – scans your SMB share on a configurable interval and converts every new HEIC/HEIF file
- 🖼️ **Fullscreen slideshow** – clean, minimal web UI designed for iPad mounted on a wall
- 📂 **Albums** – subfolders are automatically shown as albums with cover thumbnails and photo counts
- 📅 **EXIF overlay** – date and GPS location (via Nominatim reverse geocoding) shown on each photo
- ⬆️ **Web upload** – upload photos directly from iPhone Safari without needing SMB access; supports multiple files and creating new albums on the fly
- 🔄 **Background thumbnail pre-generation** – thumbnails are generated in the background after each scan; no waiting on first open
- 🗑️ **Trash** – long-press any photo to move it to `_kos/` subfolder (recoverable via SMB)
- 👆 **Swipe gestures** – left/right to navigate, swipe down to return to album selection
- 🔐 **Optional HTTP Basic Auth** – password-protect the web interface
- 📡 **REST API** – `/status`, `/scan`, `/upload` endpoints for automation

> **Note:** The web interface (slideshow + upload UI) is in **Slovak language**. Pull requests for i18n are welcome.

---

## Requirements

- Home Assistant OS or Supervised
- A Samba/CIFS share accessible from your HA instance (e.g. a NAS, Windows share, or another HA Samba addon)
- iPad or any modern browser for the slideshow

---

## Installation

This addon is not in the official HA addon store. Install it as a **local addon**:

### 1. Copy the addon files

Copy the contents of this repository into `/addons/snapframe/` on your Home Assistant instance.

The easiest ways:
- **Samba** – connect to `\\YOUR_HA_IP\addons\` and create the folder there
- **Studio Code Server addon** – open a terminal and clone the repo:
  ```bash
  cd /addons
  git clone https://github.com/EMO/ha-snapframe snapframe
  ```
- **SSH/Terminal addon**:
  ```bash
  cd /addons && git clone https://github.com/EMO/ha-snapframe snapframe
  ```

### 2. Add the local repository in HA

1. Go to **Settings → Add-ons → Add-on Store → ⋮ (three dots) → Repositories**
2. The "Local add-ons" section should appear automatically if the folder is in the right place
3. Refresh the page

### 3. Install and configure

1. Find **"SnapFrame – HEIC Photo Slideshow for Home Assistant"** in Local add-ons and click **Install**
2. Go to the **Configuration** tab and fill in your SMB details (see [Configuration](#configuration) below)
3. Click **Save**, then **Start**

### 4. Open the slideshow

Navigate to `http://YOUR_HA_IP:8099` in a browser (or set up an ingress panel in Lovelace).

---

## Configuration

| Option | Default | Description |
|---|---|---|
| `smb_server` | `192.168.1.100` | IP address or hostname of your SMB/CIFS server |
| `smb_share` | `Photos` | SMB share name |
| `smb_username` | *(required)* | SMB username |
| `smb_password` | *(required)* | SMB password |
| `watch_folder` | `/sambamount/upload` | Path inside the mounted share to watch for new HEIC files |
| `output_folder` | `/sambamount/converted` | Path inside the mounted share where converted JPGs are stored |
| `delete_original` | `true` | Delete original HEIC after successful conversion |
| `jpg_quality` | `92` | JPEG quality for converted full-size photos (1–100) |
| `thumb_quality` | `82` | JPEG quality for cached thumbnails (1–100) |
| `thumb_max_px` | `1024` | Longest edge in pixels for thumbnails (256–3840) |
| `scan_interval_hours` | `12` | How often to scan the watch folder (1–168 h) |
| `slideshow_seconds` | `30` | Seconds each photo is shown (3–300) |
| `web_port` | `8099` | Port for the web interface |
| `basic_auth_user` | *(empty)* | Username for HTTP Basic Auth; leave empty to disable |
| `basic_auth_password` | *(empty)* | Password for HTTP Basic Auth |

### Example configuration

```yaml
smb_server: "192.168.1.50"
smb_share: "MediaShare"
smb_username: "photouser"
smb_password: "yourpassword"
watch_folder: "/sambamount/iPhone/upload"
output_folder: "/sambamount/slideshow"
delete_original: true
jpg_quality: 92
thumb_quality: 82
thumb_max_px: 1024
scan_interval_hours: 12
slideshow_seconds: 20
web_port: 8099
basic_auth_user: ""
basic_auth_password: ""
```

---

## Folder structure on the SMB share

```
your-smb-share/
├── upload/              ← drop HEIC files here (watch_folder)
└── slideshow/           ← converted JPGs are stored here (output_folder)
    ├── Holidays/        ← subfolder = album
    │   ├── IMG_001.jpg
    │   └── IMG_002.jpg
    ├── Family/
    │   └── ...
    ├── _kos/            ← trash (photos moved here via long-press)
    └── _thumbs/         ← auto-generated thumbnail cache (do not delete manually)
```

Albums are subfolders of `output_folder`. You can create them manually via SMB, or use the **web upload** form to create them on the fly.

---

## Usage

### Slideshow

Open `http://YOUR_HA_IP:8099` on your iPad (or any browser).

1. **Select order** – Chronological or Random
2. **Select album** – tap any album, or "All photos"
3. The slideshow starts immediately

### Gestures (touch)

| Gesture | Action |
|---|---|
| Swipe left | Next photo |
| Swipe right | Previous photo |
| Swipe down | Back to album selection |
| Long press (0.75 s) | Move current photo to trash |

### Web upload

At the bottom of the album selection screen, tap **"↑ Upload photos"** to expand the upload form:

1. Choose a **target album** from the dropdown (existing albums), or select **"— New album… —"** and type a name
2. Tap **"Select files"** – on iPhone this opens the Photos app; you can select multiple photos
3. Tap **"Upload"** – files are uploaded one by one with a progress indicator
4. HEIC files are converted to JPG on upload; JPG and PNG files are saved as-is

### Manual scan

Tap **"↻ Scan now"** on the album selection screen to trigger an immediate scan of the `watch_folder` without waiting for the next scheduled interval.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Slideshow web interface |
| `GET` | `/albums` | JSON list of albums with photo counts |
| `GET` | `/photos?album=X&order=date\|random` | JSON list of photo paths |
| `GET` | `/thumb/<path>` | Cached thumbnail (JPEG, max `thumb_max_px` px) |
| `GET` | `/photo/<path>` | Full-size photo |
| `GET` | `/exif/<path>` | JSON with `date` and `location` strings |
| `GET` | `/album-cover/<album>` | Thumbnail of the first photo in album |
| `POST` | `/delete/<path>` | Move photo to `_kos/` trash folder |
| `POST` | `/upload` | Upload a file (`multipart/form-data`: `file`, `album`) |
| `POST` | `/scan` | Trigger immediate scan |
| `GET` | `/status` | JSON with scan stats and thumbnail pre-generation progress |

### `/status` response example

```json
{
  "last_scan": "2025-06-15 08:02:44",
  "last_scan_ago": "3.2 hours",
  "next_scan": "2025-06-15 20:02:44",
  "next_scan_in": "8.8 hours",
  "converted_total": 47,
  "scan_pending": false,
  "thumbs": {
    "running": true,
    "total": 3500,
    "done": 1240,
    "percent": 35
  }
}
```

---

## How it works

```
iPhone Photos app
      │  (SMB or web upload)
      ▼
 watch_folder/          ← watcher.py polls every N hours
      │  (HEIC → JPG conversion, EXIF preserved)
      ▼
 output_folder/
      │
      ├── Background thread: generate _thumbs/ for all photos
      │
      └── webserver.py (Waitress/Flask)
              │
              ▼
         Browser / iPad
         (slideshow, upload UI)
```

- **`watcher.py`** – main process; mounts SMB share, runs scan loop, spawns webserver thread
- **`webserver.py`** – Flask app served by Waitress (8 threads); handles all HTTP routes
- **`state.py`** – shared in-process state (scan timestamps, thumbnail progress, manual scan flag)

### Thumbnail caching

Thumbnails are stored in `output_folder/_thumbs/` on the SMB share. They are generated:
1. **On first request** (on-demand) if not yet cached
2. **In bulk** after every scan in a background thread – this pre-warms the cache so the slideshow is fast even for large collections (3000+ photos)

On the first ever run with an existing photo collection, pre-generation runs in the background. The slideshow is accessible immediately; photos without a cached thumbnail temporarily serve the full-size image as fallback.

### EXIF and GPS

EXIF metadata is read from the JPG files. GPS coordinates are reverse-geocoded via [Nominatim / OpenStreetMap](https://nominatim.openstreetmap.org/) with a polite 1-request-per-location rate (results are cached persistently in `/data/geocode_cache.json`).

---

## Troubleshooting

**The addon fails to start / SMB mount fails**
- Verify `smb_server`, `smb_share`, `smb_username`, `smb_password` in configuration
- Make sure the SMB share uses protocol version 3.0 (most modern NAS devices do)
- Check the addon log for the exact mount error

**Photos are not being converted**
- Check that the HEIC files land in `watch_folder` (not a subfolder of it)
- Tap "↻ Scan now" to trigger an immediate scan
- Check the addon log for conversion errors

**The web interface does not load**
- Confirm `web_port` (default 8099) is not blocked by a firewall
- Check the addon log – if you see `invalid literal for int()` errors, re-save your configuration to write the new fields

**Thumbnails are slow on first open**
- Normal behaviour for large collections; pre-generation runs in the background
- Check `/status` → `thumbs.percent` to see progress

**`Task queue depth is N` warnings in logs**
- Waitress warning that more requests are queued than can be served immediately
- Usually caused by SMB latency during thumbnail generation; resolves once pre-generation completes

---

## Security notes

- The addon requires `full_access: true` and `SYS_ADMIN` privilege to mount CIFS shares inside the container. This is standard for any addon that needs to call `mount`. It **cannot** be installed from the official HA addon store for this reason.
- SMB credentials are stored in HA's encrypted addon configuration and are never logged.
- The web interface has **no authentication by default** – it is intended for use on a trusted local network. Enable `basic_auth_user` / `basic_auth_password` if you expose it externally.
- The geocoding cache (`/data/geocode_cache.json`) stores GPS coordinates rounded to 2 decimal places (~1 km precision). It does not contain any other personal data.

---

## Contributing

Pull requests are welcome. Some ideas:
- English / multilingual UI (i18n)
- Trash management UI (empty trash, restore from trash)
- Video support
- AppArmor profile to reduce required privileges

---

## License

MIT – see [LICENSE](LICENSE)
