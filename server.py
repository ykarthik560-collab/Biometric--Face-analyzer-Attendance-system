"""
Attendance System — server (cloud-deployable version)

Four pages, one server, zero external dependencies:
    /scanner    — camera check-in (passcode-gated)
    /dashboard  — teacher's live view + session controls + passcode control
    /portal     — attendance % across completed sessions
    /enroll     — add a new person (name + photo) through the browser

Runs identically locally (python server.py -> http://127.0.0.1:8000) and on
a host like Render, which sets a PORT environment variable — this script
reads that automatically, no code changes needed either way.
"""

import csv
import io
import json
import os
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "data", "attendance.json")
HISTORY_FILE = os.path.join(BASE_DIR, "data", "history.json")
ROSTER_FILE = os.path.join(BASE_DIR, "data", "roster.json")
REFERENCE_DIR = os.path.join(BASE_DIR, "reference")

PORT = int(os.environ.get("PORT", 8000))
BIND_ADDRESS = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"

SUBJECT_LABEL = "Signals and Systems"

# Seeded the first time this runs — after that, the roster lives in
# data/roster.json and grows via the /enroll page, not this file.
DEFAULT_ROSTER = [
    {"id": "JUUG25BTECH27494", "name": "Karthik Y", "photo": "reference/karthik-reference.jpg"},
    {"id": "TEAM-PRAFULL", "name": "Prafull Indi", "photo": "reference/prafull-reference.jpg"},
    {"id": "TEAM-SOUMYADEEP", "name": "Soumyadeep Das", "photo": "reference/soumyadeep-reference.jpg"},
    {"id": "TEAM-KRISHNA", "name": "Krishna Charan", "photo": "reference/krishna-reference.jpg"},
    {"id": "TEAM-AASTHA", "name": "Aastha Singh", "photo": "reference/aastha-reference.jpg"},
]

DEFAULT_WINDOW_MS = 20 * 60 * 1000

STATE = {
    "sessionActive": False,
    "sessionStart": None,
    "windowMs": DEFAULT_WINDOW_MS,
    "records": {},
    "scannerPasscode": "",   # empty = scanner is open to anyone with the link
}

ROSTER = []
HISTORY = []


def now_ms():
    return int(time.time() * 1000)


def load_json(path, fallback):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return fallback
    return fallback


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def load_all():
    global STATE, ROSTER, HISTORY
    STATE.update(load_json(STATE_FILE, STATE))
    ROSTER = load_json(ROSTER_FILE, None) or DEFAULT_ROSTER
    if not os.path.exists(ROSTER_FILE):
        save_json(ROSTER_FILE, ROSTER)
    HISTORY = load_json(HISTORY_FILE, [])


def save_state():
    save_json(STATE_FILE, STATE)


def save_roster():
    save_json(ROSTER_FILE, ROSTER)


def save_history():
    save_json(HISTORY_FILE, HISTORY)


def slugify(name):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "person"
    return base


def unique_id(name):
    base = "WEB-" + slugify(name).upper()
    existing = {s["id"] for s in ROSTER}
    if base not in existing:
        return base
    i = 2
    while f"{base}-{i}" in existing:
        i += 1
    return f"{base}-{i}"


def public_state():
    roster_view = []
    for student in ROSTER:
        rec = STATE["records"].get(student["id"])
        if rec:
            status, timestamp = rec["status"], rec["timestamp"]
        elif STATE["sessionStart"] and not STATE["sessionActive"]:
            status, timestamp = "Absent", None
        else:
            status, timestamp = "Not checked in", None
        roster_view.append({
            "id": student["id"], "name": student["name"], "photo": student["photo"],
            "status": status, "timestamp": timestamp,
        })

    counts = {"Present": 0, "Late": 0, "Absent": 0, "Not checked in": 0}
    for r in roster_view:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    return {
        "sessionActive": STATE["sessionActive"],
        "sessionStart": STATE["sessionStart"],
        "windowMs": STATE["windowMs"],
        "now": now_ms(),
        "roster": roster_view,
        "counts": counts,
        "passcodeSet": bool(STATE["scannerPasscode"]),
    }


def portal_data():
    total = len(HISTORY)
    rows = []
    for student in ROSTER:
        attended = sum(1 for s in HISTORY if s["records"].get(student["id"], "Absent") in ("Present", "Late"))
        pct = round((attended / total) * 100, 1) if total > 0 else None
        rows.append({"id": student["id"], "name": student["name"], "attended": attended, "total": total, "pct": pct})
    return {"subject": SUBJECT_LABEL, "totalSessions": total, "rows": rows}


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript",
    ".json": "application/json", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
}


def parse_multipart(body, boundary):
    """Minimal multipart/form-data parser — no external deps. Handles one or
    more text fields and file fields, which is all this app needs."""
    fields, files = {}, {}
    boundary_bytes = ("--" + boundary).encode()
    parts = body.split(boundary_bytes)
    for part in parts:
        if not part or part in (b"--\r\n", b"--", b"\r\n"):
            continue
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if b"\r\n\r\n" not in part:
            continue
        header_bytes, content = part.split(b"\r\n\r\n", 1)
        headers = header_bytes.decode("utf-8", errors="replace")
        name_match = re.search(r'name="([^"]*)"', headers)
        filename_match = re.search(r'filename="([^"]*)"', headers)
        if not name_match:
            continue
        field_name = name_match.group(1)
        if filename_match and filename_match.group(1):
            files[field_name] = {"filename": filename_match.group(1), "data": content}
        else:
            fields[field_name] = content.decode("utf-8", errors="replace")
    return fields, files


class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print("  " + (fmt % args))

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, rel_path):
        full = os.path.join(BASE_DIR, rel_path)
        if not os.path.abspath(full).startswith(BASE_DIR) or not os.path.isfile(full):
            self.send_response(404)
            self.end_headers()
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if ext != ".html":
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_raw_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _read_json_body(self):
        raw = self._read_raw_body()
        try:
            return json.loads(raw or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/scanner", "/scanner.html", "/scanner/"):
            self._file("scanner.html")
        elif path in ("/dashboard", "/dashboard.html", "/dashboard/"):
            self._file("dashboard.html")
        elif path in ("/portal", "/portal.html", "/portal/"):
            self._file("portal.html")
        elif path in ("/enroll", "/enroll.html", "/enroll/"):
            self._file("enroll.html")
        elif path == "/api/state":
            self._json(public_state())
        elif path == "/api/portal":
            self._json(portal_data())
        elif path == "/api/export.csv":
            self._export_csv()
        elif path.startswith("/js/") or path.startswith("/models/") or path.startswith("/reference/"):
            self._file(path.lstrip("/"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        content_type = self.headers.get("Content-Type", "")

        if path == "/api/session/start":
            body = self._read_json_body()
            STATE["sessionActive"] = True
            STATE["sessionStart"] = now_ms()
            STATE["windowMs"] = int(body.get("windowMs", DEFAULT_WINDOW_MS))
            STATE["records"] = {}
            save_state()
            self._json(public_state())

        elif path == "/api/session/end":
            snapshot = public_state()
            record_map = {r["id"]: r["status"] for r in snapshot["roster"]}
            HISTORY.append({"endedAt": now_ms(), "records": record_map})
            save_history()
            STATE["sessionActive"] = False
            save_state()
            self._json(public_state())

        elif path == "/api/checkin":
            body = self._read_json_body()
            student_id = body.get("studentId")
            roster_ids = [s["id"] for s in ROSTER]
            if student_id not in roster_ids:
                self._json({"error": "Student ID not in roster."}, 400)
                return
            if not STATE["sessionActive"] or STATE["sessionStart"] is None:
                self._json({"error": "No active session — ask the teacher to start one."}, 400)
                return
            elapsed = now_ms() - STATE["sessionStart"]
            status = "Late" if elapsed > STATE["windowMs"] else "Present"
            STATE["records"][student_id] = {"status": status, "timestamp": now_ms()}
            save_state()
            self._json({"status": status, "elapsedMs": elapsed})

        elif path == "/api/passcode":
            body = self._read_json_body()
            STATE["scannerPasscode"] = str(body.get("passcode", "")).strip()
            save_state()
            self._json({"passcodeSet": bool(STATE["scannerPasscode"])})

        elif path == "/api/verify-passcode":
            body = self._read_json_body()
            ok = (not STATE["scannerPasscode"]) or (str(body.get("passcode", "")) == STATE["scannerPasscode"])
            self._json({"ok": ok})

        elif path == "/api/enroll":
            if "multipart/form-data" not in content_type:
                self._json({"error": "Expected multipart/form-data."}, 400)
                return
            boundary_match = re.search(r'boundary=(.+)', content_type)
            if not boundary_match:
                self._json({"error": "Missing multipart boundary."}, 400)
                return
            boundary = boundary_match.group(1).strip().strip('"')
            raw = self._read_raw_body()
            fields, files = parse_multipart(raw, boundary)

            name = fields.get("name", "").strip()
            photo = files.get("photo")
            if not name:
                self._json({"error": "Name is required."}, 400)
                return
            if not photo or not photo["data"]:
                self._json({"error": "Photo is required."}, 400)
                return

            ext = os.path.splitext(photo["filename"])[1].lower()
            if ext not in (".jpg", ".jpeg", ".png"):
                ext = ".jpg"
            new_id = unique_id(name)
            photo_filename = f"{slugify(name)}-{new_id[-4:].lower()}{ext}"
            photo_rel_path = f"reference/{photo_filename}"

            os.makedirs(REFERENCE_DIR, exist_ok=True)
            with open(os.path.join(BASE_DIR, photo_rel_path), "wb") as f:
                f.write(photo["data"])

            ROSTER.append({"id": new_id, "name": name, "photo": photo_rel_path})
            save_roster()
            self._json({"id": new_id, "name": name, "photo": photo_rel_path})

        else:
            self.send_response(404)
            self.end_headers()

    def _export_csv(self):
        state = public_state()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Student ID", "Name", "Status", "Time"])
        for r in state["roster"]:
            time_str = time.strftime("%H:%M:%S", time.localtime(r["timestamp"] / 1000)) if r["timestamp"] else ""
            writer.writerow([r["id"], r["name"], r["status"], time_str])
        data = buf.getvalue().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Disposition", 'attachment; filename="attendance.csv"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    load_all()
    server = ThreadingHTTPServer((BIND_ADDRESS, PORT), Handler)
    print(f"Attendance server running on {BIND_ADDRESS}:{PORT}")
    print(f"  Scanner:   /scanner")
    print(f"  Dashboard: /dashboard")
    print(f"  Portal:    /portal")
    print(f"  Enroll:    /enroll")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
