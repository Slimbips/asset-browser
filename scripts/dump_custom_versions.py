import re
import struct
from collections import Counter
from pathlib import Path

LOG = Path(r"D:\Games\test\Stalingrad\Saved\Logs\Stalingrad.log")
OURS_IDLE = Path(r"D:\Games\test\Stalingrad\Content\MOHAA\characters\AS_1St_Ranger_Engineer_idle.uasset")
OURS_MESH = Path(r"D:\Games\test\Stalingrad\Content\MOHAA\characters\SK_1St_Ranger_Engineer.uasset")
PACK_IDLE = Path(r"D:\Games\test\Stalingrad\Content\MOH\Characters\AlliedAssault\Animations\idle\standidle01.uasset")
PACK_MESH = Path(r"D:\Games\test\Stalingrad\Content\MOH\Characters\AlliedAssault\SkeletalMeshes\NPCs\1st-ranger_engineer.uasset")
PACK_PHYS = Path(r"D:\Games\test\Stalingrad\Content\MOH\Characters\AlliedAssault\PhysicsAssets\human_physicsAsset.uasset")
PACK_MAT = Path(r"D:\Games\test\Stalingrad\Content\MOH\Characters\AlliedAssault\Materials\Masters\M_BaseMaterial.uasset")


def extract_cv(path: Path, limit: int = 1024):
    d = path.read_bytes()[:limit]
    found = []
    i = 0
    while i + 20 <= len(d):
        ver = struct.unpack_from("<i", d, i + 16)[0]
        if 1 <= ver <= 500:
            guid = d[i : i + 16]
            if guid.count(0) < 6:
                found.append((i, guid, ver))
                i += 20
                continue
        i += 1
    return found


def show(label, path):
    print("====", label, path.name if path.exists() else "MISSING")
    if not path.exists():
        return
    for i, g, v in extract_cv(path)[:30]:
        print("  %4d %s %s" % (i, g.hex(), v))


for label, p in [
    ("ours idle", OURS_IDLE),
    ("pack idle", PACK_IDLE),
    ("ours mesh", OURS_MESH),
    ("pack mesh", PACK_MESH),
    ("pack phys", PACK_PHYS),
    ("pack mat", PACK_MAT),
]:
    show(label, p)

text = LOG.read_text(encoding="utf-8", errors="replace")
pat = re.compile(
    r"newer custom version of ([A-Za-z0-9_-]+): Package: (\d+), HeadCode: (\d+)"
)
counts = Counter()
pairs = {}
for name, pkg, head in pat.findall(text):
    key = (name, int(pkg), int(head))
    counts[key] += 1
    pairs[name] = (int(pkg), int(head))
print("==== LOG unique version mismatches")
for name, (pkg, head) in sorted(pairs.items()):
    print("  %s pack=%s head=%s hits=%s" % (name, pkg, head, counts[(name, pkg, head)]))
