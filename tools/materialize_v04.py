from __future__ import annotations

import base64
import io
from pathlib import Path
import tarfile


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def main() -> None:
    parts = sorted(TOOLS.glob(".v04_payload_*"))
    if len(parts) != 5:
        raise SystemExit(f"Expected 5 payload parts, found {len(parts)}")

    encoded = "".join(part.read_text(encoding="utf-8").strip() for part in parts)
    payload = base64.b64decode(encoded, validate=True)

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive.getmembers():
            name = Path(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise SystemExit(f"Unsafe archive path: {member.name}")
        archive.extractall(ROOT)

    for part in parts:
        part.unlink()

    for path in [
        TOOLS / ".v04_ready",
        TOOLS / "materialize_v04.py",
        ROOT / ".github" / "workflows" / "materialize-v04.yml",
    ]:
        if path.exists():
            path.unlink()


if __name__ == "__main__":
    main()
