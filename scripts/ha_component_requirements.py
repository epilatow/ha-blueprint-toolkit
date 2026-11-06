# This is AI generated code
"""Print the requirements one Home Assistant component declares.

``scripts/deps-upgrade.py`` runs this inside a throwaway environment
holding the Home Assistant release it is moving to, so the manifest it
reads is that release's. The manifest is read as a file rather than by
importing the component, because importing it needs the very client
library whose version is being resolved.

Usage: python ha_component_requirements.py <component>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import homeassistant


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    if homeassistant.__file__ is None:
        print("homeassistant is not a regular package", file=sys.stderr)
        return 1
    manifest = (
        Path(homeassistant.__file__).parent
        / "components"
        / argv[0]
        / "manifest.json"
    )
    requirements = json.loads(manifest.read_text())["requirements"]
    print("\n".join(requirements))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
