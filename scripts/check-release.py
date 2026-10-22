#!/usr/bin/env python3
"""Check release boundaries and smoke-install a built wheel outside the checkout."""
import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def clean_names(names):
    for name in names:
        parts = PurePosixPath(name).parts
        require(not any(part in ("..", ".git", ".venv", ".validation", "__pycache__") for part in parts), f"Private/generated archive path: {name}")
        require(not name.lower().endswith((".exe", ".dll", ".pdb", ".log", ".pem", ".key", ".pyc")), f"Unexpected runtime artifact: {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    profile = json.loads((root / "RELEASE-PROFILE.json").read_text())
    wheels = list(args.artifacts.glob("*.whl"))
    sources = list(args.artifacts.glob("*.tar.gz"))
    require(len(wheels) == len(sources) == 1, "Expected one wheel and one source distribution")
    wheel = wheels[0].resolve()
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        clean_names(names)
        require(f"{profile['package']}/mcp_server.py" in names, "Expansion MCP module missing")
        require(f"{profile['core_package']}/_release_profile.py" in names, "Release build fence missing")
        require(any(name.endswith("/LICENSE") for name in names), "License missing")
        require(any(name.endswith("/NOTICE.md") for name in names), "Attribution missing")
        require(not any(name.endswith((".cpp", ".conf")) for name in names), "Native/runtime files in Python wheel")
        other = "wotlk_context" if profile["profile"] == "cata" else "cata_context"
        require(not any(name.startswith(other + "/") for name in names), "Other expansion bundled in wheel")
    with tarfile.open(sources[0]) as archive:
        names = archive.getnames()
        clean_names(names)
        require(any(name.endswith("/server-module/src/ContextModule.cpp") for name in names), "Native source missing from sdist")
        require(any(name.endswith("/SHARED-SOURCE.json") for name in names), "Shared source identity missing")
    with tempfile.TemporaryDirectory(prefix="context-wheel-check-") as temporary:
        sandbox = Path(temporary)
        environment = sandbox / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", "--no-deps", "--no-index", str(wheel)],
                       cwd=sandbox, check=True, capture_output=True, text=True, timeout=120)
        code = f'''from importlib.metadata import version
import {profile['package']} as api
from {profile['core_package']}._release_profile import BUILD
assert version({profile['distribution']!r}) == api.__version__ == {profile['version']!r}
assert BUILD == {profile['build']}
print("Isolated installed wheel identity and expansion fence passed")
'''
        subprocess.run([str(python), "-I", "-c", code], cwd=sandbox, check=True, timeout=15)
        subprocess.run([str(python), "-I", "-m", profile["package"], "--help"],
                       cwd=sandbox, check=True, capture_output=True, timeout=15)
    print(f"{profile['distribution']} {profile['version']}: wheel/source boundaries and isolated installation passed")


if __name__ == "__main__":
    main()
