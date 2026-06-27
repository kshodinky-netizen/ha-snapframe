#!/usr/bin/env python3
"""
Fotorámik webový server v2.5.
Novinky v2.5: web upload, /status, /scan trigger, LRU EXIF cache,
persistentná geocoding cache, thumbnail kvalita z config,
konfigurovateľná veľkosť thumbnail, počítadlo fotiek, albumové covery,
základná autentifikácia (voliteľná), oprava refresh timera.
Kompatibilné so Safari 9 / iOS 9.
"""

import os
import re
import json as json_module
import logging
import random as random_module
import time
import urllib.request
from collections import OrderedDict
from pathlib import Path
from datetime import datetime

from flask import Flask, send_from_directory, jsonify, Response, request
from PIL import Image, ImageOps
from PIL.ExifTags import TAGS

log = logging.getLogger("ha-snapframe.web")

OUTPUT_FOLDER      = os.environ.get("OUTPUT_FOLDER",  "/sambamount/converted")
SLIDESHOW_SECONDS  = int(os.environ.get("SLIDESHOW_SECONDS", "30"))
WEB_PORT           = int(os.environ.get("WEB_PORT",  "8099"))
def _env_int(key, default):
    try:
        return int(os.environ.get(key, ""))
    except (ValueError, TypeError):
        return default

def _env_str(key, default=""):
    v = os.environ.get(key, "")
    return default if v in ("null", "", None) else v

JPG_QUALITY     = _env_int("JPG_QUALITY",    92)
THUMB_QUALITY   = _env_int("THUMB_QUALITY",  82)
THUMB_MAX_PX    = _env_int("THUMB_MAX_PX",   1024)
BASIC_AUTH_USER = _env_str("BASIC_AUTH_USER")
BASIC_AUTH_PASS = _env_str("BASIC_AUTH_PASSWORD")

GEOCACHE_FILE = "/data/geocode_cache.json"

app = Flask(__name__)

ALLOWED_EXT = (".jpg", ".jpeg", ".png")

# ── Zdieľaný stav (voliteľný – funguje aj bez state.py) ──────────────────────
try:
    import state as _state
    _has_state = True
except ImportError:
    _has_state = False

# ── LRU Cache pre EXIF (250 položiek) ────────────────────────────────────────

class _LRUCache:
    def __init__(self, maxsize=250):
        self._cache   = OrderedDict()
        self._maxsize = maxsize

    def get(self, key):
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return self._cache[key]

    def set(self, key, value):
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)

    def __contains__(self, key):
        return key in self._cache


_exif_cache    = _LRUCache(maxsize=250)
_geocode_cache = {}   # {(lat_round, lon_round): "Miesto, Krajina"}

MONTHS_SK = [
    "januára", "februára", "marca", "apríla", "mája", "júna",
    "júla", "augusta", "septembra", "októbra", "novembra", "decembra"
]
MONTHS_SK_NOM = [
    "január", "február", "marec", "apríl", "máj", "jún",
    "júl", "august", "september", "október", "november", "december"
]
COUNTRY_CODE_SK = {
    "SK": "Slovensko",  "CZ": "Česko",       "HU": "Maďarsko",
    "PL": "Poľsko",     "AT": "Rakúsko",      "DE": "Nemecko",
    "IT": "Taliansko",  "FR": "Francúzsko",   "ES": "Španielsko",
    "PT": "Portugalsko","GR": "Grécko",        "HR": "Chorvátsko",
    "SI": "Slovinsko",  "RS": "Srbsko",        "BA": "Bosna a Hercegovina",
    "ME": "Čierna Hora","MK": "Severné Macedónsko","AL": "Albánsko",
    "RO": "Rumunsko",   "BG": "Bulharsko",     "TR": "Turecko",
    "CH": "Švajčiarsko","NL": "Holandsko",     "BE": "Belgicko",
    "LU": "Luxembursko","DK": "Dánsko",        "SE": "Švédsko",
    "NO": "Nórsko",     "FI": "Fínsko",        "IE": "Írsko",
    "GB": "Spojené kráľovstvo",                "IS": "Island",
    "MT": "Malta",      "CY": "Cyprus",        "AD": "Andorra",
    "MC": "Monako",     "SM": "San Maríno",    "LI": "Lichtenštajnsko",
    "UA": "Ukrajina",   "BY": "Bielorusko",    "RU": "Rusko",
    "MD": "Moldavsko",  "GE": "Gruzínsko",     "AM": "Arménsko",
    "AZ": "Azerbajdžan","LT": "Litva",         "LV": "Lotyšsko",
    "EE": "Estónsko",
    "US": "Spojené štáty","CA": "Kanada",      "MX": "Mexiko",
    "BR": "Brazília",   "AR": "Argentína",     "CL": "Čile",
    "CO": "Kolumbia",   "PE": "Peru",          "CU": "Kuba",
    "MA": "Maroko",     "DZ": "Alžírsko",      "TN": "Tunisko",
    "EG": "Egypt",      "ZA": "Južná Afrika",  "KE": "Keňa",
    "IL": "Izrael",     "AE": "Spojené arabské emiráty",
    "TH": "Thajsko",    "VN": "Vietnam",       "JP": "Japonsko",
    "CN": "Čína",       "IN": "India",         "ID": "Indonézia",
    "PH": "Filipíny",   "AU": "Austrália",
}

# ── Geocoding cache – persistencia ───────────────────────────────────────────

def _load_geocode_cache():
    global _geocode_cache
    try:
        with open(GEOCACHE_FILE, "r", encoding="utf-8") as f:
            raw = json_module.load(f)
        for k, v in raw.items():
            parts = k.split(",")
            if len(parts) == 2:
                _geocode_cache[(float(parts[0]), float(parts[1]))] = v
        log.info("Geocache: načítaných {} lokácií".format(len(_geocode_cache)))
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("Geocache načítanie zlyhalo: {}".format(e))


def _save_geocode_cache():
    try:
        raw = {"{},{}".format(k[0], k[1]): v for k, v in _geocode_cache.items()}
        with open(GEOCACHE_FILE, "w", encoding="utf-8") as f:
            json_module.dump(raw, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning("Geocache uloženie zlyhalo: {}".format(e))

# ── EXIF helpers ──────────────────────────────────────────────────────────────

def _load_exif(path: Path):
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}

    cache_key = (str(path), mtime)
    cached = _exif_cache.get(cache_key)
    if cached is not None:
        return cached

    result = {"date": None, "gps": None}

    try:
        img  = Image.open(path)
        exif = img.getexif()
        if exif:
            for tag_id, value in exif.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag in ("DateTimeOriginal", "DateTime", "DateTimeDigitized"):
                    try:
                        result["date"] = datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
                        break
                    except ValueError:
                        pass
            gps_ifd = exif.get_ifd(0x8825)
            if gps_ifd:
                lat_ref = gps_ifd.get(1)
                lat     = gps_ifd.get(2)
                lon_ref = gps_ifd.get(3)
                lon     = gps_ifd.get(4)
                if all([lat_ref, lat, lon_ref, lon]):
                    def to_deg(val):
                        d, m, s = val
                        return float(d) + float(m) / 60.0 + float(s) / 3600.0
                    lat_deg = to_deg(lat)
                    lon_deg = to_deg(lon)
                    if lat_ref == "S": lat_deg = -lat_deg
                    if lon_ref == "W": lon_deg = -lon_deg
                    result["gps"] = (lat_deg, lon_deg)
    except Exception as e:
        log.debug("EXIF chyba {}: {}".format(path.name, e))

    _exif_cache.set(cache_key, result)
    return result


def get_exif_date(path: Path):
    return _load_exif(path).get("date")


def get_gps_coords(path: Path):
    return _load_exif(path).get("gps")


def reverse_geocode(lat, lon):
    key = (round(lat, 2), round(lon, 2))
    if key in _geocode_cache:
        return _geocode_cache[key]

    result = ""
    try:
        url = (
            "https://nominatim.openstreetmap.org/reverse"
            "?format=json&lat={}&lon={}&zoom=10&accept-language=sk,cs,en".format(lat, lon)
        )
        req = urllib.request.Request(url, headers={"User-Agent": "SnapFrame/2.5"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json_module.loads(resp.read().decode("utf-8"))
        address = data.get("address", {})
        place   = (
            address.get("city") or address.get("town") or
            address.get("village") or address.get("county") or ""
        )
        cc      = address.get("country_code", "").upper()
        country = COUNTRY_CODE_SK.get(cc, address.get("country", ""))
        if place and country:
            result = "{}, {}".format(place, country)
        else:
            result = place or country or ""
    except Exception as e:
        log.debug("Geocoding chyba ({}, {}): {}".format(lat, lon, e))

    _geocode_cache[key] = result
    _save_geocode_cache()
    return result

# ── Foto helpers ──────────────────────────────────────────────────────────────

def list_albums():
    """Vráti abecedne zoradený zoznam albumov s počtom fotiek."""
    folder = Path(OUTPUT_FOLDER)
    if not folder.exists():
        return []
    HIDDEN = {"_kos", "_thumbs"}
    result = []
    for d in sorted(folder.iterdir()):
        if d.is_dir() and d.name not in HIDDEN:
            count = sum(
                1 for f in d.iterdir()
                if f.is_file() and f.suffix.lower() in ALLOWED_EXT
            )
            result.append({"name": d.name, "count": count})
    return result


def list_photos(album=""):
    folder = Path(OUTPUT_FOLDER)
    if not folder.exists():
        return []

    if album and album != "all":
        search = folder / album
        if not search.is_dir():
            return []
        files = [f for f in search.iterdir()
                 if f.is_file() and f.suffix.lower() in ALLOWED_EXT]
    else:
        HIDDEN = {"_kos", "_thumbs"}
        files  = [f for f in folder.rglob("*")
                  if f.is_file() and f.suffix.lower() in ALLOWED_EXT
                  and not any(p in HIDDEN for p in f.relative_to(folder).parts)]

    def sort_key(f):
        d = get_exif_date(f)
        return d.timestamp() if d is not None else f.stat().st_mtime

    files.sort(key=sort_key)
    return [str(f.relative_to(folder)) for f in files]

# ── Thumbnail helper ──────────────────────────────────────────────────────────

def _get_or_create_thumb(filename: str):
    """Vráti (directory, name) pre send_from_directory, alebo None pri chybe."""
    src        = Path(OUTPUT_FOLDER) / filename
    if not src.is_file():
        return None
    thumb_path = Path(OUTPUT_FOLDER) / "_thumbs" / filename
    try:
        if thumb_path.exists() and thumb_path.stat().st_mtime >= src.stat().st_mtime:
            return (str(thumb_path.parent), thumb_path.name)
    except OSError:
        pass
    try:
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.open(src)
        img = ImageOps.exif_transpose(img)
        img.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX), Image.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(thumb_path, "JPEG", quality=THUMB_QUALITY, optimize=True)
        log.debug("Thumbnail vytvorený: {}".format(filename))
    except Exception as e:
        log.warning("Thumbnail chyba {}: {}".format(filename, e))
        if src.is_file():
            return (OUTPUT_FOLDER, filename)
        return None
    return (str(thumb_path.parent), thumb_path.name)

# ── Autentifikácia ────────────────────────────────────────────────────────────

@app.before_request
def check_auth():
    if not BASIC_AUTH_USER:
        return   # auth vypnutá
    auth = request.authorization
    if not auth or auth.username != BASIC_AUTH_USER or auth.password != BASIC_AUTH_PASS:
        return Response(
            "Prístup zamietnutý",
            401,
            {"WWW-Authenticate": 'Basic realm="Fotorámik"'},
        )

# ── Upload helper ─────────────────────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w\-_.()\s]", "_", name, flags=re.UNICODE)
    return name.strip() or "upload"


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return "{} sekúnd".format(seconds)
    elif seconds < 3600:
        return "{} minút".format(seconds // 60)
    elif seconds < 86400:
        return "{:.1f} hodín".format(seconds / 3600)
    else:
        return "{:.1f} dní".format(seconds / 86400)

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/albums")
def albums_route():
    return jsonify({"albums": list_albums()})


@app.route("/photos")
def photos_route():
    album      = request.args.get("album", "")
    order      = request.args.get("order", "date")
    photo_list = list_photos(album)
    if order == "random":
        random_module.shuffle(photo_list)
    return jsonify({"photos": photo_list})


@app.route("/thumb/<path:filename>")
def thumb(filename):
    result = _get_or_create_thumb(filename)
    if result is None:
        return ("not found", 404)
    return send_from_directory(result[0], result[1])


@app.route("/album-cover/<path:album>")
def album_cover(album):
    """Vráti thumbnail prvej fotky z albumu (pre pozadie tlačidla)."""
    photos = list_photos(album)
    if not photos:
        return ("", 404)
    result = _get_or_create_thumb(photos[0])
    if result is None:
        return ("", 404)
    return send_from_directory(result[0], result[1])


@app.route("/photo/<path:filename>")
def photo(filename):
    return send_from_directory(OUTPUT_FOLDER, filename)


@app.route("/exif/<path:filename>")
def exif_route(filename):
    path     = Path(OUTPUT_FOLDER) / filename
    date_str = ""
    loc_str  = ""

    exif_date = get_exif_date(path)
    if exif_date is None and path.exists():
        exif_date = datetime.fromtimestamp(path.stat().st_mtime)
    if exif_date:
        date_str = "{} {}".format(MONTHS_SK_NOM[exif_date.month - 1], exif_date.year)

    coords = get_gps_coords(path)
    if coords:
        loc_str = reverse_geocode(coords[0], coords[1])

    return jsonify({"date": date_str, "location": loc_str})


@app.route("/delete/<path:filename>", methods=["POST"])
def delete_photo(filename):
    src = Path(OUTPUT_FOLDER) / filename
    if not src.is_file():
        return jsonify({"ok": False, "error": "not found"}), 404
    kos_dir = Path(OUTPUT_FOLDER) / "_kos" / Path(filename).parent
    kos_dir.mkdir(parents=True, exist_ok=True)
    dest    = kos_dir / src.name
    counter = 1
    while dest.exists():
        dest = kos_dir / "{}_{}.{}".format(src.stem, counter, src.suffix.lstrip("."))
        counter += 1
    src.rename(dest)
    log.info("Presunuté do koša: {} -> {}".format(filename, dest.relative_to(Path(OUTPUT_FOLDER))))
    thumb_p = Path(OUTPUT_FOLDER) / "_thumbs" / filename
    if thumb_p.exists():
        try:
            thumb_p.unlink()
        except Exception as e:
            log.warning("Thumbnail zmazanie zlyhalo {}: {}".format(filename, e))
    return jsonify({"ok": True})


@app.route("/upload", methods=["POST"])
def upload_file():
    """Prijme jeden súbor (HEIC → skonvertuje, JPG/PNG → uloží priamo)."""
    f     = request.files.get("file")
    album = request.form.get("album", "").strip()

    if not f or not f.filename:
        return jsonify({"ok": False, "error": "žiadny súbor"}), 400

    original_name = _safe_filename(f.filename)
    ext           = Path(original_name).suffix.lower()

    if album:
        target_dir = Path(OUTPUT_FOLDER) / album
    else:
        target_dir = Path(OUTPUT_FOLDER)
    target_dir.mkdir(parents=True, exist_ok=True)

    if ext in (".heic", ".heif"):
        try:
            img  = Image.open(f.stream)
            exif = img.info.get("exif")
            stem = Path(original_name).stem
            dest = target_dir / (stem + ".jpg")
            c    = 1
            while dest.exists():
                dest = target_dir / "{}_{}.jpg".format(stem, c)
                c += 1
            img = ImageOps.exif_transpose(img)
            if img.mode != "RGB":
                img = img.convert("RGB")
            kw = {"quality": JPG_QUALITY, "optimize": True}
            if exif:
                kw["exif"] = exif
            img.save(dest, "JPEG", **kw)
            log.info("Upload+konverzia: {} -> {}".format(original_name, dest.name))
            return jsonify({"ok": True, "saved": str(dest.relative_to(Path(OUTPUT_FOLDER)))})
        except Exception as e:
            log.error("Upload konverzia zlyhala {}: {}".format(original_name, e))
            return jsonify({"ok": False, "error": str(e)}), 500

    elif ext in (".jpg", ".jpeg", ".png"):
        dest = target_dir / original_name
        c    = 1
        while dest.exists():
            dest = target_dir / "{}_{}.{}".format(Path(original_name).stem, c, ext.lstrip("."))
            c += 1
        f.save(str(dest))
        log.info("Upload: {}".format(dest.relative_to(Path(OUTPUT_FOLDER))))
        return jsonify({"ok": True, "saved": str(dest.relative_to(Path(OUTPUT_FOLDER)))})

    else:
        return jsonify({"ok": False, "error": "nepodporovaný formát (HEIC/JPG/PNG)"}), 400


@app.route("/scan", methods=["POST"])
def trigger_scan():
    """Vyžiada okamžitý scan bez čakania na interval."""
    if _has_state:
        _state.request_scan()
        return jsonify({"ok": True, "message": "Scan naplánovaný"})
    return jsonify({"ok": False, "message": "State modul nedostupný"}), 503


@app.route("/status")
def status_route():
    if not _has_state:
        return jsonify({"error": "state modul nedostupný"}), 503
    s   = _state.get_status()
    now = time.time()
    out = {
        "converted_total": s["converted_total"],
        "scan_pending":    s["scan_pending"],
        "last_scan":       None,
        "last_scan_ago":   None,
        "next_scan":       None,
        "next_scan_in":    None,
    }
    if s["last_scan_time"]:
        out["last_scan"]     = datetime.fromtimestamp(s["last_scan_time"]).strftime("%Y-%m-%d %H:%M:%S")
        out["last_scan_ago"] = _format_duration(int(now - s["last_scan_time"]))
    if s["next_scan_time"]:
        out["next_scan"]    = datetime.fromtimestamp(s["next_scan_time"]).strftime("%Y-%m-%d %H:%M:%S")
        out["next_scan_in"] = _format_duration(max(0, int(s["next_scan_time"] - now)))
    ts = _state.get_thumb_status()
    out["thumbs"] = ts
    if ts["running"] and ts["total"] > 0:
        out["thumbs"]["percent"] = int(100 * ts["done"] / ts["total"])
    else:
        out["thumbs"]["percent"] = 100 if not ts["running"] else 0
    return jsonify(out)


# ── HTML ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    html = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<title>Fotorámik</title>
<style>
html, body {
  margin: 0; padding: 0;
  width: 100%; height: 100%;
  background: #0c0c0c;
  font-family: -apple-system, Helvetica, Arial, sans-serif;
  color: #eee;
  overflow: hidden;
}

/* ===== VÝBERNÁ OBRAZOVKA ===== */
#screen-select {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding: 48px 24px 48px;
  -webkit-box-sizing: border-box;
  box-sizing: border-box;
  text-align: center;
}
.sel-title {
  font-size: 26px;
  font-weight: 200;
  letter-spacing: 8px;
  text-transform: uppercase;
  color: #fff;
  margin-bottom: 4px;
}
.sel-subtitle {
  font-size: 13px;
  color: #444;
  letter-spacing: 2px;
  margin-bottom: 18px;
}
.top-actions {
  margin-bottom: 32px;
}
.scan-btn {
  background: transparent;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  color: #555;
  font-size: 12px;
  letter-spacing: 1px;
  padding: 7px 16px;
  cursor: pointer;
  outline: none;
  -webkit-tap-highlight-color: transparent;
  -webkit-transition: color 0.15s, border-color 0.15s;
  transition: color 0.15s, border-color 0.15s;
}
.scan-btn.done { color: #4caf50; border-color: #4caf50; }

.order-label {
  font-size: 11px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: #555;
  margin-bottom: 10px;
}
.order-row {
  display: inline-block;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 40px;
}
.order-btn {
  display: inline-block;
  padding: 10px 24px;
  background: transparent;
  border: none;
  color: #666;
  font-size: 14px;
  cursor: pointer;
  outline: none;
  -webkit-tap-highlight-color: transparent;
  -webkit-transition: background 0.15s, color 0.15s;
  transition: background 0.15s, color 0.15s;
}
.order-btn.active { background: #222; color: #fff; }

.album-list {
  text-align: left;
  max-width: 460px;
  margin: 0 auto 32px;
}
.album-btn {
  display: block;
  width: 100%;
  padding: 15px 18px;
  margin-bottom: 10px;
  background: #161616;
  border: 1px solid #242424;
  border-radius: 10px;
  color: #ddd;
  font-size: 16px;
  text-align: left;
  cursor: pointer;
  outline: none;
  position: relative;
  overflow: hidden;
  -webkit-box-sizing: border-box;
  box-sizing: border-box;
  -webkit-tap-highlight-color: transparent;
  -webkit-transition: background 0.15s;
  transition: background 0.15s;
  background-size: cover;
  background-position: center;
}
.album-btn:active { background-color: #222; }
.album-btn.all-btn { border-color: #333; color: #fff; }
/* Tmavý overlay pre čitateľnosť textu nad cover obrázkom */
.album-btn-overlay {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.62);
}
.album-btn-inner {
  position: relative;
  z-index: 1;
}
.album-icon { margin-right: 10px; opacity: 0.6; }
.all-icon   { opacity: 0.9; }
.album-count { float: right; color: #999; font-size: 13px; margin-top: 2px; }
.sel-empty { color: #444; font-size: 14px; padding: 20px 0; text-align: center; }

/* ===== UPLOAD SEKCIA ===== */
.upload-toggle {
  background: transparent;
  border: 1px solid #222;
  border-radius: 8px;
  color: #555;
  font-size: 13px;
  letter-spacing: 1px;
  padding: 10px 22px;
  cursor: pointer;
  outline: none;
  -webkit-tap-highlight-color: transparent;
  margin-bottom: 16px;
  display: block;
  width: 100%;
  max-width: 460px;
  margin-left: auto;
  margin-right: auto;
  text-align: center;
  -webkit-box-sizing: border-box;
  box-sizing: border-box;
}
#upload-section {
  display: none;
  max-width: 460px;
  margin: 0 auto 32px;
  background: #111;
  border: 1px solid #222;
  border-radius: 12px;
  padding: 20px 18px;
  text-align: left;
}
.upload-label {
  font-size: 11px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: #555;
  margin-bottom: 8px;
  display: block;
}
.upload-select {
  width: 100%;
  background: #1c1c1c;
  border: 1px solid #2c2c2c;
  border-radius: 7px;
  color: #ccc;
  font-size: 14px;
  padding: 10px 12px;
  -webkit-box-sizing: border-box;
  box-sizing: border-box;
  margin-bottom: 16px;
  outline: none;
  -webkit-appearance: none;
}
.upload-file-btn {
  display: block;
  width: 100%;
  padding: 12px;
  background: #1c1c1c;
  border: 1px dashed #333;
  border-radius: 8px;
  color: #777;
  font-size: 14px;
  text-align: center;
  cursor: pointer;
  -webkit-box-sizing: border-box;
  box-sizing: border-box;
  margin-bottom: 14px;
  -webkit-tap-highlight-color: transparent;
  outline: none;
}
.upload-file-btn.has-files { border-color: #555; color: #bbb; }
#upload-files { display: none; }
.upload-go-btn {
  display: block;
  width: 100%;
  padding: 13px;
  background: #1a3a2a;
  border: 1px solid #2a5a3a;
  border-radius: 8px;
  color: #5dba7e;
  font-size: 15px;
  text-align: center;
  cursor: pointer;
  outline: none;
  -webkit-tap-highlight-color: transparent;
  -webkit-box-sizing: border-box;
  box-sizing: border-box;
  -webkit-transition: background 0.15s;
  transition: background 0.15s;
}
.upload-go-btn:disabled { opacity: 0.4; }
.upload-status {
  margin-top: 12px;
  font-size: 13px;
  color: #666;
  min-height: 20px;
  text-align: center;
}
.upload-status.ok  { color: #5dba7e; }
.upload-status.err { color: #c0392b; }

/* ===== SLIDESHOW ===== */
#screen-slideshow {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  background: #000;
  display: none;
}
.photo {
  position: absolute;
  top: 0; left: 0; width: 100%; height: 100%;
  background-position: center center;
  background-repeat: no-repeat;
  background-size: contain;
  opacity: 0;
  -webkit-transition: opacity 1.5s ease-in-out, -webkit-transform 1.8s ease-in-out;
  transition: opacity 1.5s ease-in-out, transform 1.8s ease-in-out;
}
.photo.fade-start      { -webkit-transform: scale(1);        transform: scale(1); }
.photo.fade-end        { -webkit-transform: scale(1);        transform: scale(1); }
.photo.zoomin-start    { -webkit-transform: scale(1.0);      transform: scale(1.0); }
.photo.zoomin-end      { -webkit-transform: scale(1.12);     transform: scale(1.12); }
.photo.zoomout-start   { -webkit-transform: scale(1.12);     transform: scale(1.12); }
.photo.zoomout-end     { -webkit-transform: scale(1.0);      transform: scale(1.0); }
.photo.slideleft-start { -webkit-transform: translateX(4%);  transform: translateX(4%); }
.photo.slideleft-end   { -webkit-transform: translateX(0);   transform: translateX(0); }
.photo.slideup-start   { -webkit-transform: translateY(4%);  transform: translateY(4%); }
.photo.slideup-end     { -webkit-transform: translateY(0);   transform: translateY(0); }
.photo.visible { opacity: 1; }

/* Počítadlo fotiek */
#photo-counter {
  position: absolute;
  top: 14px; right: 18px;
  z-index: 90;
  color: rgba(255,255,255,0.32);
  font-size: 13px;
  letter-spacing: 1px;
  pointer-events: none;
  text-shadow: 0 1px 4px rgba(0,0,0,0.8);
}

/* EXIF overlay */
#overlay {
  position: absolute;
  bottom: 18px; left: 18px; right: 18px;
  z-index: 90;
  pointer-events: none;
}
#overlay-date {
  font-size: 26px;
  font-weight: 300;
  line-height: 1.1;
  letter-spacing: 1px;
  color: rgba(255,255,255,0.80);
  margin-bottom: 5px;
  text-shadow: 0 2px 10px rgba(0,0,0,0.95), 0 0 24px rgba(0,0,0,0.8);
}
#overlay-location {
  font-size: 36px;
  font-weight: 200;
  line-height: 1.1;
  color: rgba(255,255,255,0.93);
  text-shadow: 0 2px 10px rgba(0,0,0,0.95), 0 0 24px rgba(0,0,0,0.8);
}

/* Delete dialog */
#delete-dialog {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  z-index: 200;
  background: rgba(0,0,0,0.68);
}
.del-box {
  position: absolute;
  top: 50%; left: 50%;
  -webkit-transform: translate(-50%, -50%);
  transform: translate(-50%, -50%);
  background: #1c1c1e;
  border-radius: 14px;
  padding: 30px 26px 24px;
  text-align: center;
  min-width: 270px; max-width: 340px;
}
.del-title { font-size: 17px; color: #fff; margin-bottom: 8px; }
.del-sub   { font-size: 13px; color: #888; margin-bottom: 26px; }
.del-yes {
  background: #c0392b; color: #fff; border: none;
  border-radius: 9px; padding: 12px 28px; font-size: 16px;
  margin-right: 10px; cursor: pointer; outline: none;
  -webkit-tap-highlight-color: transparent;
}
.del-no {
  background: #2c2c2e; color: #ccc; border: none;
  border-radius: 9px; padding: 12px 28px; font-size: 16px;
  cursor: pointer; outline: none;
  -webkit-tap-highlight-color: transparent;
}

#ss-msg {
  position: absolute;
  top: 50%; left: 0; right: 0;
  text-align: center;
  color: #444;
  font-size: 17px;
  -webkit-transform: translateY(-50%);
  transform: translateY(-50%);
  display: none;
}
</style>
</head>
<body>

<!-- ========== VÝBERNÁ OBRAZOVKA ========== -->
<div id="screen-select">
  <div class="sel-title">Fotorámik</div>
  <div class="sel-subtitle">FOTO RÁMIK</div>

  <div class="top-actions">
    <button id="scan-btn" class="scan-btn" onclick="triggerScan()">↻ Skenuj teraz</button>
  </div>

  <div class="order-label">Poradie fotiek</div>
  <div class="order-row">
    <button class="order-btn active" id="btn-order-date" onclick="setOrder('date')">Chronologicky</button>
    <button class="order-btn"        id="btn-order-rand" onclick="setOrder('random')">Náhodne</button>
  </div>

  <div class="album-list" id="album-list">
    <div class="sel-empty">Načítavam albumy…</div>
  </div>

  <!-- Upload sekcia -->
  <button class="upload-toggle" onclick="toggleUpload()">&#8679; Nahrať fotky</button>
  <div id="upload-section">
    <label class="upload-label">Cieľový album</label>
    <select id="upload-album" class="upload-select" onchange="onAlbumChange(this)">
      <option value="">Koreňový priečinok</option>
      <option value="__new__">— Nový album… —</option>
    </select>
    <input type="text" id="upload-new-album" class="upload-select"
           placeholder="Názov nového albumu"
           style="display:none;margin-top:-6px"
           oninput="onNewAlbumInput(this)">
    <label class="upload-label">Súbory (HEIC, JPG, PNG)</label>
    <button class="upload-file-btn" id="upload-file-btn" onclick="document.getElementById('upload-files').click()">
      Vybrať súbory…
    </button>
    <input type="file" id="upload-files" multiple accept=".heic,.heif,.jpg,.jpeg,.png,image/*"
           onchange="onFilesSelected(this)">
    <button class="upload-go-btn" id="upload-go-btn" onclick="startUpload()">Nahrať</button>
    <div class="upload-status" id="upload-status"></div>
  </div>
</div>

<!-- ========== SLIDESHOW ========== -->
<div id="screen-slideshow" style="display:none">
  <div class="photo" id="photoA"></div>
  <div class="photo" id="photoB"></div>
  <div id="photo-counter"></div>
  <div id="overlay">
    <div id="overlay-date"></div>
    <div id="overlay-location"></div>
  </div>
  <div id="ss-msg">Žiadne fotky v tomto albume</div>
  <div id="delete-dialog" style="display:none">
    <div class="del-box">
      <div class="del-title">Odstrániť túto fotku?</div>
      <div class="del-sub">Fotka bude presunutá do koša</div>
      <button class="del-yes" onclick="confirmDelete()">Odstrániť</button>
      <button class="del-no"  onclick="hideDeleteDialog()">Zrušiť</button>
    </div>
  </div>
</div>

<script>
var SLIDESHOW_SECONDS = __SLIDESHOW_SECONDS__;

var currentOrder   = "date";
var currentAlbum   = "";
var photos         = [];
var currentIndex   = -1;
var activeIsA      = true;
var advanceTimer   = null;
var refreshTimer   = null;
var slideshowActive = false;

// Zoznam albumov pre bezpečné indexovanie
var albumNames = [];

// ── Pomocné funkcie ───────────────────────────────────────────────────────────

function xhrGet(url, callback) {
  var xhr = new XMLHttpRequest();
  xhr.open("GET", url, true);
  xhr.onreadystatechange = function () {
    if (xhr.readyState === 4) {
      if (xhr.status === 200) { callback(null, xhr.responseText); }
      else { callback(new Error("HTTP " + xhr.status), null); }
    }
  };
  xhr.send();
}

function escHtml(s) {
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function encodePath(path) {
  var parts = path.split("/"), out = [];
  for (var i = 0; i < parts.length; i++) { out.push(encodeURIComponent(parts[i])); }
  return out.join("/");
}

// ── Trigger manuálneho skenu ──────────────────────────────────────────────────

function triggerScan() {
  var btn = document.getElementById("scan-btn");
  var xhr = new XMLHttpRequest();
  xhr.open("POST", "/scan", true);
  xhr.onreadystatechange = function () {
    if (xhr.readyState !== 4) { return; }
    btn.innerHTML = "✓ Spustené";
    btn.className = "scan-btn done";
    setTimeout(function () {
      btn.innerHTML = "↻ Skenuj teraz";
      btn.className = "scan-btn";
    }, 3000);
  };
  xhr.send();
}

// ── Výberná obrazovka ─────────────────────────────────────────────────────────

function setOrder(order) {
  currentOrder = order;
  document.getElementById("btn-order-date").className = (order === "date") ? "order-btn active" : "order-btn";
  document.getElementById("btn-order-rand").className = (order === "random") ? "order-btn active" : "order-btn";
}

function loadAlbums() {
  xhrGet("/albums", function (err, text) {
    var listEl = document.getElementById("album-list");
    if (err) {
      listEl.innerHTML = "<div class='sel-empty'>Chyba: " + escHtml(err.message) + "</div>";
      return;
    }
    var data;
    try { data = JSON.parse(text); } catch (e) { return; }

    var albums = data.albums || [];
    albumNames = [];
    for (var i = 0; i < albums.length; i++) { albumNames.push(albums[i].name); }

    // Celkový počet
    var totalCount = 0;
    for (var i = 0; i < albums.length; i++) { totalCount += (albums[i].count || 0); }

    var html = "<button class='album-btn all-btn' onclick='startSlideshow(\"all\")'>"
             + "<div class='album-btn-overlay'></div>"
             + "<div class='album-btn-inner'>"
             + "<span class='album-icon all-icon'>&#9654;</span>Všetko"
             + "<span class='album-count'>" + totalCount + "</span>"
             + "</div></button>";

    for (var i = 0; i < albums.length; i++) {
      html += "<button class='album-btn' id='album-btn-" + i + "' onclick='startSlideshowIdx(" + i + ")'>"
            + "<div class='album-btn-overlay'></div>"
            + "<div class='album-btn-inner'>"
            + "<span class='album-icon'>&#128193;</span>"
            + escHtml(albums[i].name)
            + "<span class='album-count'>" + (albums[i].count || 0) + "</span>"
            + "</div></button>";
    }
    if (albums.length === 0) {
      html += "<div class='sel-empty'>Žiadne albumy (podpriečinky)</div>";
    }
    listEl.innerHTML = html;

    // Načítaj covery albumov
    loadAlbumCovers();
    // Naplň upload select
    populateUploadAlbums(albums);
  });
}

function loadAlbumCovers() {
  for (var i = 0; i < albumNames.length; i++) {
    (function (name, idx) {
      var btn = document.getElementById("album-btn-" + idx);
      if (!btn) { return; }
      var img = new Image();
      img.onload = function () {
        btn.style.backgroundImage = "url('/album-cover/" + encodeURIComponent(name) + "')";
      };
      img.src = "/album-cover/" + encodeURIComponent(name);
    })(albumNames[i], i);
  }
}

function startSlideshowIdx(i) { startSlideshow(albumNames[i]); }

function goBack() {
  if (advanceTimer) { clearInterval(advanceTimer); advanceTimer = null; }
  if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }

  photos = []; currentIndex = -1; activeIsA = true;

  var a = document.getElementById("photoA");
  var b = document.getElementById("photoB");
  a.style.backgroundImage = ""; a.className = "photo";
  b.style.backgroundImage = ""; b.className = "photo";

  document.getElementById("overlay-date").innerHTML     = "";
  document.getElementById("overlay-location").innerHTML = "";
  document.getElementById("photo-counter").innerHTML    = "";

  slideshowActive = false;
  document.getElementById("screen-slideshow").style.display = "none";
  document.getElementById("screen-select").style.display    = "";
  loadAlbums();
}

// ── Slideshow ─────────────────────────────────────────────────────────────────

function startSlideshow(album) {
  currentAlbum    = album;
  slideshowActive = true;
  document.getElementById("screen-select").style.display    = "none";
  document.getElementById("screen-slideshow").style.display = "block";
  document.getElementById("ss-msg").style.display           = "none";

  fetchPhotosAndStart();

  // Každých 5 minút aktualizuj zoznam (opravené: vždy, nielen pri pribúdaní)
  refreshTimer = setInterval(function () {
    fetchPhotos(function (newList) {
      if (newList.length === 0) { return; }
      var oldLen = photos.length;
      photos = newList;
      // Uprav index ak sa zoznam skrátil
      if (currentIndex >= photos.length) {
        currentIndex = photos.length - 1;
      }
      if (oldLen === 0 && photos.length > 0) {
        document.getElementById("ss-msg").style.display = "none";
        currentIndex = 0;
        showPhoto(0);
        startAdvanceTimer();
      }
    });
  }, 5 * 60 * 1000);
}

function fetchPhotos(callback) {
  var url = "/photos?album=" + encodeURIComponent(currentAlbum) + "&order=" + currentOrder;
  xhrGet(url, function (err, text) {
    if (err) { if (callback) { callback([]); } return; }
    try {
      var data = JSON.parse(text);
      if (callback) { callback(data.photos || []); }
    } catch (e) { if (callback) { callback([]); } }
  });
}

function fetchPhotosAndStart() {
  fetchPhotos(function (list) {
    photos = list;
    if (photos.length === 0) {
      document.getElementById("ss-msg").style.display = "block";
      return;
    }
    currentIndex = 0; activeIsA = true;
    showPhoto(0);
    startAdvanceTimer();
  });
}

var EFFECTS = ["fade", "zoomin", "zoomout", "slideleft", "slideup"];
function pickEffect() { return EFFECTS[Math.floor(Math.random() * EFFECTS.length)]; }

function showPhoto(index) {
  if (photos.length === 0) { return; }
  var idx      = ((index % photos.length) + photos.length) % photos.length;
  var filename = photos[idx];
  var url      = "/thumb/" + encodePath(filename);
  var nextEl   = activeIsA ? document.getElementById("photoB") : document.getElementById("photoA");
  var prevEl   = activeIsA ? document.getElementById("photoA") : document.getElementById("photoB");
  var effect   = pickEffect();

  nextEl.style.backgroundImage = "url(" + url + ")";
  nextEl.className = "photo " + effect + "-start";

  setTimeout(function () {
    nextEl.className = "photo visible " + effect + "-end";
    prevEl.className = "photo";
  }, 50);

  activeIsA = !activeIsA;

  // Počítadlo
  document.getElementById("photo-counter").innerHTML = (idx + 1) + " / " + photos.length;

  loadExifOverlay(filename);
}

function loadExifOverlay(filename) {
  document.getElementById("overlay-date").innerHTML     = "";
  document.getElementById("overlay-location").innerHTML = "";
  xhrGet("/exif/" + encodePath(filename), function (err, text) {
    if (err) { return; }
    try {
      var data = JSON.parse(text);
      document.getElementById("overlay-date").innerHTML     = escHtml(data.date     || "");
      document.getElementById("overlay-location").innerHTML = escHtml(data.location || "");
    } catch (e) {}
  });
}

function startAdvanceTimer() {
  if (advanceTimer) { clearInterval(advanceTimer); }
  advanceTimer = setInterval(function () {
    currentIndex = (currentIndex + 1) % photos.length;
    showPhoto(currentIndex);
  }, SLIDESHOW_SECONDS * 1000);
}

// ── Swipe + dlhý tap ──────────────────────────────────────────────────────────

var swipeTouchStartX = 0;
var swipeTouchStartY = 0;
var longPressTimer   = null;
var longPressFired   = false;

function isSlideshow() { return slideshowActive; }

document.addEventListener("touchstart", function (e) {
  swipeTouchStartX = e.touches[0].clientX;
  swipeTouchStartY = e.touches[0].clientY;
  longPressFired   = false;
  if (isSlideshow()) {
    longPressTimer = setTimeout(function () {
      longPressFired = true;
      showDeleteDialog();
    }, 750);
  }
}, false);

document.addEventListener("touchmove", function (e) {
  if (!longPressTimer) { return; }
  var dx = e.touches[0].clientX - swipeTouchStartX;
  var dy = e.touches[0].clientY - swipeTouchStartY;
  if (Math.abs(dx) > 10 || Math.abs(dy) > 10) {
    clearTimeout(longPressTimer); longPressTimer = null;
  }
}, false);

document.addEventListener("touchend", function (e) {
  if (longPressTimer) { clearTimeout(longPressTimer); longPressTimer = null; }
  if (longPressFired || !isSlideshow()) { return; }
  var dx = e.changedTouches[0].clientX - swipeTouchStartX;
  var dy = e.changedTouches[0].clientY - swipeTouchStartY;
  if (Math.abs(dy) > 80 && Math.abs(dx) < 80) { goBack(); return; }
  if (dx > 80 && Math.abs(dy) < 60) {
    if (advanceTimer) { clearInterval(advanceTimer); }
    currentIndex = ((currentIndex - 1) + photos.length) % photos.length;
    showPhoto(currentIndex); startAdvanceTimer(); return;
  }
  if (dx < -80 && Math.abs(dy) < 60) {
    if (advanceTimer) { clearInterval(advanceTimer); }
    currentIndex = (currentIndex + 1) % photos.length;
    showPhoto(currentIndex); startAdvanceTimer(); return;
  }
}, false);

// ── Mazanie ───────────────────────────────────────────────────────────────────

function showDeleteDialog()  { document.getElementById("delete-dialog").style.display = "block"; }
function hideDeleteDialog()  { document.getElementById("delete-dialog").style.display = "none";  }

function confirmDelete() {
  hideDeleteDialog();
  if (photos.length === 0) { return; }
  var filename = photos[currentIndex];
  var xhr = new XMLHttpRequest();
  xhr.open("POST", "/delete/" + encodePath(filename), true);
  xhr.onreadystatechange = function () {
    if (xhr.readyState !== 4 || xhr.status !== 200) { return; }
    photos.splice(currentIndex, 1);
    if (photos.length === 0) {
      document.getElementById("photoA").className = "photo";
      document.getElementById("photoB").className = "photo";
      document.getElementById("photo-counter").innerHTML = "";
      document.getElementById("ss-msg").style.display = "block";
      return;
    }
    currentIndex = currentIndex % photos.length;
    document.getElementById("photoA").className = "photo";
    document.getElementById("photoB").className = "photo";
    activeIsA = true;
    showPhoto(currentIndex);
  };
  xhr.send();
}

// ── Upload ────────────────────────────────────────────────────────────────────

function toggleUpload() {
  var sec = document.getElementById("upload-section");
  sec.style.display = (sec.style.display === "none" || sec.style.display === "") ? "block" : "none";
}

function populateUploadAlbums(albums) {
  var sel = document.getElementById("upload-album");
  // Ponechaj koreň (index 0) + Nový album (posledný), obnov prostredné
  while (sel.options.length > 2) { sel.remove(1); }
  for (var i = 0; i < albums.length; i++) {
    var opt = document.createElement("option");
    opt.value       = albums[i].name;
    opt.textContent = albums[i].name;
    sel.insertBefore(opt, sel.options[sel.options.length - 1]);
  }
}

function onAlbumChange(sel) {
  var newInput = document.getElementById("upload-new-album");
  if (sel.value === "__new__") {
    newInput.style.display = "block";
    newInput.focus();
  } else {
    newInput.style.display = "none";
    newInput.value = "";
  }
}

function onNewAlbumInput(input) {
  var v = "", s = input.value;
  for (var i = 0; i < s.length; i++) {
    var c = s[i];
    if (c !== "/" && c !== "\\") { v += c; }
  }
  input.value = v;
}

function _getTargetAlbum() {
  var sel = document.getElementById("upload-album");
  if (sel.value === "__new__") {
    return document.getElementById("upload-new-album").value.trim();
  }
  return sel.value;
}

function onFilesSelected(input) {
  var btn = document.getElementById("upload-file-btn");
  if (input.files && input.files.length > 0) {
    btn.className = "upload-file-btn has-files";
    btn.innerHTML = input.files.length + " súbor" + (input.files.length > 1 ? "y vybraté" : " vybratý");
  } else {
    btn.className = "upload-file-btn";
    btn.innerHTML = "Vybrať súbory…";
  }
  document.getElementById("upload-status").innerHTML  = "";
  document.getElementById("upload-status").className  = "upload-status";
}

function startUpload() {
  var input = document.getElementById("upload-files");
  var files = input.files;
  if (!files || files.length === 0) {
    var statusEl = document.getElementById("upload-status");
    statusEl.innerHTML = "Najprv vyber súbory.";
    statusEl.className = "upload-status err";
    return;
  }
  document.getElementById("upload-go-btn").disabled = true;
  var album = _getTargetAlbum();
  if (document.getElementById("upload-album").value === "__new__" && !album) {
    var statusEl = document.getElementById("upload-status");
    statusEl.innerHTML = "Zadaj názov nového albumu."; statusEl.className = "upload-status err";
    document.getElementById("upload-go-btn").disabled = false; return;
  }
  _uploadNext(files, 0, album, 0);
}

function _uploadNext(files, idx, album, errCount) {
  var statusEl = document.getElementById("upload-status");
  if (idx >= files.length) {
    var msg = "✓ " + files.length + " fotiek nahraných";
    if (errCount > 0) { msg += " (" + errCount + " chýb)"; }
    statusEl.innerHTML = msg;
    statusEl.className = "upload-status " + (errCount > 0 ? "err" : "ok");
    document.getElementById("upload-go-btn").disabled = false;
    document.getElementById("upload-files").value = "";
    var btn = document.getElementById("upload-file-btn");
    btn.className = "upload-file-btn";
    btn.innerHTML = "Vybrať súbory…";
    loadAlbums();  // obnov zoznam albumov
    return;
  }
  statusEl.className = "upload-status";
  statusEl.innerHTML = "Nahrávam " + (idx + 1) + " / " + files.length + ": " + escHtml(files[idx].name);

  var fd = new FormData();
  fd.append("file",  files[idx]);
  fd.append("album", album);

  var xhr = new XMLHttpRequest();
  xhr.open("POST", "/upload", true);
  xhr.onreadystatechange = function () {
    if (xhr.readyState !== 4) { return; }
    var newErrCount = errCount + (xhr.status === 200 ? 0 : 1);
    _uploadNext(files, idx + 1, album, newErrCount);
  };
  xhr.send(fd);
}

// ── Start ─────────────────────────────────────────────────────────────────────
loadAlbums();
</script>
</body>
</html>"""
    html = html.replace("__SLIDESHOW_SECONDS__", str(SLIDESHOW_SECONDS))
    return Response(html, mimetype="text/html; charset=utf-8")


def pregenerate_thumbs():
    """
    Vygeneruje chybajuce thumbnaile pre vsetky fotky v OUTPUT_FOLDER.
    Vola sa z watcher.py vo vlakne na pozadi.
    """
    HIDDEN = {"_kos", "_thumbs"}
    folder = Path(OUTPUT_FOLDER)
    if not folder.exists():
        return
    all_photos = [
        f for f in folder.rglob("*")
        if f.is_file()
        and f.suffix.lower() in ALLOWED_EXT
        and not any(p in HIDDEN for p in f.relative_to(folder).parts)
    ]
    total = len(all_photos)
    if total == 0:
        return
    log.info("Pregeneracia thumbnailov: {} fotiek".format(total))
    if _has_state:
        _state.thumb_start(total)
    done = 0
    skipped = 0
    for src in all_photos:
        filename = str(src.relative_to(folder))
        thumb_path = folder / "_thumbs" / filename
        try:
            if thumb_path.exists() and thumb_path.stat().st_mtime >= src.stat().st_mtime:
                skipped += 1
                done += 1
                if _has_state:
                    _state.thumb_progress(done)
                continue
        except OSError:
            pass
        _get_or_create_thumb(filename)
        done += 1
        if _has_state:
            _state.thumb_progress(done)
        if done % 50 == 0:
            log.info("Thumbnaile: {}/{} ({} preskocených ako hotové)".format(done, total, skipped))
    if _has_state:
        _state.thumb_finish()
    log.info("Thumbnaile hotové: {}/{} ({} preskocených)".format(done, total, skipped))


def run_web_server():
    _load_geocode_cache()
    log.info("Spústam web server na porte {} (thumb {}px, kvalita {})".format(
        WEB_PORT, THUMB_MAX_PX, THUMB_QUALITY))
    if BASIC_AUTH_USER:
        log.info("HTTP Basic Auth zapnuta pre uzivatela: {}".format(BASIC_AUTH_USER))
    from waitress import serve
    serve(app, host="0.0.0.0", port=WEB_PORT, threads=8)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_web_server()
