import csv, io, json, zipfile, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

URL = "https://data.texas.gov/download/r4v4-vz24/application/zip"
DAYS = 30
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday"]

def rows(z, name):
    if name not in z.namelist():
        return []
    with z.open(name) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))

def stream(z, name):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))

req = urllib.request.Request(URL, headers={"User-Agent": "crestview-board"})
z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(req, timeout=180).read()))

# Red Line trips only
rail = {r["route_id"] for r in rows(z, "routes.txt")
        if r.get("route_short_name", "").strip() == "550"
        or r.get("route_type", "").strip() == "2"}
trips = {r["trip_id"]: r["service_id"] for r in rows(z, "trips.txt")
         if r["route_id"] in rail}
stops = {r["stop_id"]: r["stop_name"].lower() for r in rows(z, "stops.txt")}

# Crestview departure + Highland position for each trip (to tell direction)
crest, high = {}, {}
for r in stream(z, "stop_times.txt"):
    tid = r["trip_id"]
    if tid not in trips:
        continue
    name = stops.get(r["stop_id"], "")
    seq = int(r["stop_sequence"])
    if "crestview" in name:
        h, m, _ = (r["departure_time"] or r["arrival_time"]).strip().split(":")
        crest[tid] = (seq, int(h) * 60 + int(m))
    elif "highland" in name:
        high[tid] = seq

svc = {}
for tid, (seq, mins) in crest.items():
    if tid not in high:
        continue
    d = "s" if high[tid] > seq else "n"
    svc.setdefault(trips[tid], {"n": [], "s": []})[d].append(mins)

if not svc:
    raise SystemExit("No Crestview Red Line trips found - not updating file")

cal = rows(z, "calendar.txt")
exc = rows(z, "calendar_dates.txt")

def active(day):
    ds = day.strftime("%Y%m%d")
    s = {c["service_id"] for c in cal
         if c["start_date"] <= ds <= c["end_date"]
         and c[WEEKDAYS[day.weekday()]] == "1"}
    for e in exc:
        if e["date"] == ds:
            if e["exception_type"] == "1":
                s.add(e["service_id"])
            elif e["exception_type"] == "2":
                s.discard(e["service_id"])
    return s

today = datetime.now(ZoneInfo("America/Chicago")).date()
days = {(today + timedelta(i)).isoformat(): {"n": set(), "s": set()}
        for i in range(DAYS)}

for i in range(-1, DAYS):
    day = today + timedelta(i)
    for sid in active(day):
        for d, lst in svc.get(sid, {}).items():
            for m in lst:
                key = (day + timedelta(days=m // 1440)).isoformat()
                if key in days:
                    days[key][d].add(m % 1440)

out = {
    "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    "days": {k: {"n": sorted(v["n"]), "s": sorted(v["s"])}
             for k, v in sorted(days.items())},
}
with open("crestview.json", "w") as f:
    json.dump(out, f, separators=(",", ":"))
print("Wrote", len(out["days"]), "days")
