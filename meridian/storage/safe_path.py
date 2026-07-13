"""Path sandboxing — reject traversal, symlinks outside root, unsafe writes."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath


class PathSecurityError(ValueError):
    """Raised when a path fails sandbox validation."""


def _is_windows() -> bool:
    return os.name == "nt"


def _as_pure(path_str: str) -> PurePosixPath | PureWindowsPath:
    if _is_windows() or "\\" in path_str:
        return PureWindowsPath(path_str)
    return PurePosixPath(path_str)


def contains_traversal(path_str: str) -> bool:
    """Detect ``..`` / absolute escapes in a user-supplied path string."""
    if not path_str or path_str.strip() == "":
        return True
    # Null bytes are never legitimate in Meridian paths.
    if "\x00" in path_str:
        return True
    # Reject absolute forms on both POSIX and Windows (incl. /etc on Win).
    if path_str.startswith(("/", "\\")):
        return True
    if len(path_str) >= 3 and path_str[1] == ":" and path_str[2] in {"/", "\\"}:
        return True
    pure = _as_pure(path_str)
    if pure.is_absolute():
        return True
    return any(part == ".." for part in pure.parts)


class PathSandbox:
    """Restrict all resolved paths to a designated root directory."""

    def __init__(self, root: str | Path, *, allow_symlinks: bool = False) -> None:
        self.root = Path(root).resolve()
        if not self.root.exists():
            self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise PathSecurityError(f"Sandbox root is not a directory: {self.root}")
        self.allow_symlinks = allow_symlinks

    def resolve(self, user_path: str | Path, *, must_exist: bool = False) -> Path:
        """Resolve ``user_path`` under the sandbox root or raise.

        Rejects:
        - path traversal via ``..``
        - absolute paths escaping the root
        - symlinks that resolve outside the root (unless ``allow_symlinks``)
        """
        raw = str(user_path)
        if contains_traversal(raw) or Path(raw).is_absolute():
            # Allow absolute only if it already lives under root after resolve.
            candidate = Path(raw)
            if candidate.is_absolute():
                resolved = candidate.resolve(strict=False)
                self._assert_inside(resolved)
                if must_exist and not resolved.exists():
                    raise PathSecurityError(f"Path does not exist: {raw}")
                if not self.allow_symlinks:
                    self._assert_no_symlink_escape(resolved)
                return resolved
            raise PathSecurityError(f"Path traversal or unsafe path rejected: {raw!r}")

        resolved = (self.root / raw).resolve(strict=False)
        self._assert_inside(resolved)
        if must_exist and not resolved.exists():
            raise PathSecurityError(f"Path does not exist inside sandbox: {raw}")
        if not self.allow_symlinks:
            self._assert_no_symlink_escape(resolved)
        return resolved

    def ensure_parent(self, user_path: str | Path) -> Path:
        """Resolve a write target and create parent directories inside the sandbox."""
        target = self.resolve(user_path, must_exist=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def open_write(self, user_path: str | Path, mode: str = "wb") -> Path:
        """Validate a writable path (caller opens the file). Returns resolved path."""
        if "w" not in mode and "a" not in mode and "x" not in mode and "+" not in mode:
            raise PathSecurityError(f"open_write requires a write mode, got {mode!r}")
        return self.ensure_parent(user_path)

    def _assert_inside(self, resolved: Path) -> None:
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise PathSecurityError(
                f"Resolved path {resolved} escapes sandbox root {self.root}"
            ) from exc

    def _assert_no_symlink_escape(self, resolved: Path) -> None:
        """Walk parents; reject if any symlink component escapes the root."""
        current = resolved
        # If the leaf does not exist yet, inspect parents only.
        chain: list[Path] = []
        probe = current
        while True:
            chain.append(probe)
            if probe == self.root or probe.parent == probe:
                break
            probe = probe.parent

        for item in chain:
            if item.exists() and item.is_symlink():
                link_target = item.resolve(strict=False)
                try:
                    link_target.relative_to(self.root)
                except ValueError as exc:
                    raise PathSecurityError(
                        f"Symlink {item} resolves outside sandbox to {link_target}"
                    ) from exc


@contextmanager
def scratch_directory(
    *,
    prefix: str = "meridian-",
    base_dir: str | Path | None = None,
) -> Iterator[PathSandbox]:
    """Create a temporary scratch sandbox cleaned up even on exceptions.

    Uses ``tempfile.TemporaryDirectory`` so OS temp cleanup is guaranteed when
    the context exits (normal return or error).
    """
    parent = Path(base_dir).resolve() if base_dir is not None else None
    if parent is not None:
        parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=prefix, dir=str(parent) if parent else None) as tmp:
        yield PathSandbox(tmp)


@contextmanager
def scratch_file(
    *,
    suffix: str = "",
    prefix: str = "meridian-",
    base_dir: str | Path | None = None,
) -> Iterator[Path]:
    """Yield a temp file path inside a TemporaryDirectory (auto-cleaned)."""
    with scratch_directory(prefix=prefix, base_dir=base_dir) as sandbox:
        name = f"{prefix}file{suffix}"
        path = sandbox.ensure_parent(name)
        # Touch empty file so callers can open for read/write immediately.
        path.write_bytes(b"")
        yield path
