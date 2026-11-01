#!/usr/bin/env python3
"""Extract and verify the frozen input data archives into source/data/."""

from hashlib import sha256
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
DATA = SOURCE / "data"
ARCHIVES = sorted(DATA.glob("submission_inputs_part*.zip"))

if len(ARCHIVES) != 3:
    raise SystemExit(f"expected three input archives, found {len(ARCHIVES)}")

members = []
seen = set()
for archive in ARCHIVES:
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            rel = Path(member.filename)
            if rel.is_absolute() or ".." in rel.parts:
                raise SystemExit(f"unsafe archive member: {member.filename}")
            dest = (SOURCE / rel).resolve()
            if SOURCE.resolve() not in dest.parents:
                raise SystemExit(f"unsafe archive member: {member.filename}")
            if member.filename in seen:
                raise SystemExit(f"duplicate archive member: {member.filename}")
            if dest.exists():
                raise SystemExit(f"refusing to overwrite existing input: {dest}")
            seen.add(member.filename)
            members.append((archive, member.filename))

csv_members = sorted(name for _, name in members if name.endswith(".csv"))
if len(csv_members) != 31 or sum(name.endswith(".json") for _, name in members) != 31:
    raise SystemExit("expected 31 CSV inputs and 31 JSON sidecars")

for archive in ARCHIVES:
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(SOURCE)

for csv_name in csv_members:
    csv_path = SOURCE / csv_name
    sidecar = csv_path.with_suffix(csv_path.suffix + ".json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    if metadata.get("out") != csv_name:
        raise SystemExit(f"non-portable or mismatched manifest path in {sidecar}")
    digest = sha256(csv_path.read_bytes()).hexdigest()
    if metadata.get("sha256") != digest:
        raise SystemExit(f"SHA-256 mismatch for {csv_path}")

print(f"Extracted and verified {len(csv_members)} frozen inputs from {len(ARCHIVES)} archives.")
