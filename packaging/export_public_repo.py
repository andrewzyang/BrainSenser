#!/usr/bin/env python3
"""Make the public BrainSenser repository from this private one.

This repository's history and several of its folders hold participant data, so
the public repository is never a fork, subtree or filtered copy of it. It is
built from scratch out of one commit's files that are on ALLOWLIST (tracked
files only, via git archive, so untracked data can't slip in), minus DROP, plus
the public .gitignore and .gitattributes kept in packaging/public_repo/.

    python packaging/export_public_repo.py OUT_DIR [--commit REF]

OUT_DIR is either new (it is created) or a clone of the public repository,
whose files are replaced while its .git is kept, so each export becomes one
new commit there. Afterwards run packaging/scan_identifiers.py on OUT_DIR: it
must report 0 failing hits before anything is pushed.
"""
import argparse
import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ["main.py", "src", "assets", "packaging", "tests", "tools", "code_release",
             "requirements.txt", "requirements-dev.txt", "pytest.ini", "LICENSE",
             "THIRD_PARTY_NOTICES.txt", "README.md", "CITATION.cff", "HOW_TO_OPEN.txt",
             ".github/workflows/release.yml"]
DROP = [
    "code_release/extract_csvs_from_sqlite.py",   # reads the private databases
    # Parity tests against research code in results/, which stays private
    "tests/integration/test_serial_cancellable_helpers.py",
    "tests/integration/test_timeline_amplitude_threshold_parity.py",
    "tests/integration/test_timeline_threshold_vendor_parity.py",
    "tests/integration/test_timeline_lfp_threshold_event_filter.py",
    "packaging/public_repo",                      # becomes the root files below
    # No test data in the public repository: the synthetic Percept exports and the
    # recorded golden outputs stay private, with the tests that read them.
    "tests/fixtures",
    "tests/integration/test_upload_workflow.py",
    "tests/ui/scaling/goldens",
    "tests/ui/scaling/_golden.py",
    "tests/ui/scaling/test_scale1_golden.py",
    "tests/ui/views/test_copy_table_scale_invariance.py",
]
PUBLIC_ROOT_FILES = {"packaging/public_repo/gitignore": ".gitignore",
                     "packaging/public_repo/gitattributes": ".gitattributes"}
KNOWN_FAILURE_LISTS = ["tests/known_failures.txt", "tests/ui/responsive/known_sweep_failures.txt"]


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True,
                          capture_output=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--commit", default="HEAD")
    args = parser.parse_args()
    commit = git("rev-parse", "--verify", f"{args.commit}^{{commit}}").decode().strip()
    out = args.out_dir.resolve()
    if out == ROOT or ROOT in out.parents:
        sys.exit("OUT_DIR must be outside this repository.")
    if out.exists() and not (out / ".git").is_dir():
        sys.exit(f"{out} exists and isn't a git clone; give a new folder or a clone of the public repo.")

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        archive = git("archive", "--format=tar", commit, "--", *ALLOWLIST)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(stage, filter="data")
        for rel, name in PUBLIC_ROOT_FILES.items():
            shutil.copy2(stage / rel, stage / name)
        for rel in DROP:
            target = stage / rel
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        dropped_tests = [Path(rel).name for rel in DROP if rel.startswith("tests/") and rel.endswith(".py")]
        for rel in KNOWN_FAILURE_LISTS:
            path = stage / rel
            if path.exists():
                lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
                path.write_text("".join(l for l in lines if not any(t in l for t in dropped_tests)),
                                encoding="utf-8")

        if out.exists():          # a clone: replace everything but .git
            for child in out.iterdir():
                if child.name != ".git":
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
        else:
            out.mkdir(parents=True)
        for child in stage.iterdir():
            shutil.move(str(child), out / child.name)

    files = sorted(p.relative_to(out) for p in out.rglob("*")
                   if p.is_file() and ".git" not in p.relative_to(out).parts[:1])
    (out.parent / f"{out.name}-files.txt").write_text("\n".join(map(str, files)) + "\n", encoding="utf-8")
    print(f"Exported {len(files)} files from {commit[:10]} to {out}")
    print(f"File list for review: {out.parent / (out.name + '-files.txt')}")


if __name__ == "__main__":
    main()
