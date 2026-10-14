from __future__ import annotations

import base64
import io
from pathlib import Path
import subprocess
import tarfile


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
WORKFLOWS = ROOT / ".github" / "workflows"


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

    # A workflow token may write ordinary repository files but cannot create or
    # modify workflow YAML without the workflows permission. Keep workflow files
    # unchanged in this bot commit; ChatGPT's authenticated repo connector writes
    # the final workflow YAML immediately afterwards.
    subprocess.run(
        ["git", "checkout", "HEAD", "--", ".github/workflows/windows-check.yml", ".github/workflows/materialize-v04.yml"],
        cwd=ROOT,
        check=True,
    )
    generated_build_workflow = WORKFLOWS / "windows-build.yml"
    if generated_build_workflow.exists():
        generated_build_workflow.unlink()

    for part in parts:
        part.unlink()

    for path in [TOOLS / ".v04_ready", TOOLS / "materialize_v04.py"]:
        if path.exists():
            path.unlink()


if __name__ == "__main__":
    main()
