"""Path sandbox / traversal rejection tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from meridian.storage.safe_path import (
    PathSandbox,
    PathSecurityError,
    contains_traversal,
    scratch_directory,
    scratch_file,
)

ATTACK_PATHS = [
    "../etc/passwd",
    "..\\..\\windows\\system32",
    "/etc/passwd",
    "foo/../../etc/passwd",
    "foo/../../../tmp/x",
    "..",
    "./../secret",
    "...\x00/etc/passwd",
]


@pytest.mark.parametrize("attack", ATTACK_PATHS)
def test_contains_traversal_rejects_attacks(attack: str) -> None:
    assert contains_traversal(attack) or Path(attack).is_absolute()


@pytest.mark.parametrize("attack", ATTACK_PATHS)
def test_sandbox_resolve_rejects_traversal(tmp_path: Path, attack: str) -> None:
    sandbox = PathSandbox(tmp_path)
    with pytest.raises(PathSecurityError):
        sandbox.resolve(attack)


def test_sandbox_allows_nested_relative(tmp_path: Path) -> None:
    sandbox = PathSandbox(tmp_path)
    target = sandbox.ensure_parent("clips/a/b.txt")
    target.write_text("ok", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "ok"
    assert sandbox.resolve("clips/a/b.txt", must_exist=True).exists()


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("nope", encoding="utf-8")

    root = tmp_path / "sandbox"
    root.mkdir()
    link = root / "escape"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    sandbox = PathSandbox(root, allow_symlinks=False)
    with pytest.raises(PathSecurityError, match=r"[Ss]ymlink|escapes"):
        sandbox.resolve("escape/secret.txt", must_exist=True)


def test_scratch_directory_cleans_up() -> None:
    retained: str | None = None
    with scratch_directory(prefix="meridian-test-") as sandbox:
        retained = str(sandbox.root)
        f = sandbox.open_write("x.bin")
        f.write_bytes(b"abc")
        assert f.exists()
    assert retained is not None
    assert not Path(retained).exists()


def test_scratch_file_cleans_up() -> None:
    retained: str | None = None
    with scratch_file(suffix=".wav") as path:
        retained = str(path)
        path.write_bytes(b"RIFF")
        assert path.exists()
    assert retained is not None
    assert not Path(retained).exists()


def test_absolute_inside_root_allowed(tmp_path: Path) -> None:
    sandbox = PathSandbox(tmp_path)
    inner = tmp_path / "inner.txt"
    inner.write_text("hi", encoding="utf-8")
    resolved = sandbox.resolve(inner)
    assert resolved == inner.resolve()
