"""Reversible bundle primitives backed by the shared integration write journal."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .._init_options import load_init_options
from ..integration_state import installed_integration_keys, try_read_integration_json
from ..integrations import INTEGRATION_REGISTRY
from ..integrations._file_changes import file_change_observer
from ..integrations._lifecycle import _FileJournal, _initial_entries, _restore_snapshots
from ..integrations.installer import _trust_store, safe_project_path
from ..shared_infra import _exclusive_project_lock
from . import BundlerError


@contextmanager
def bundle_file_transaction(project_root: Path):
    """Preserve installed component bytes and provenance across bundle failures.

    This shares the integration write journal and project lock. It avoids
    re-downloading previous versions and never eagerly copies user files.
    Unobserved writes to existing files and conflicts fail closed.
    """
    root = Path(project_root).absolute()
    state, error = try_read_integration_json(root)
    if error:
        raise BundlerError(
            f"Cannot read integration state before bundle update: {error.detail}"
        )
    used = set(installed_integration_keys(state or {}))
    configured_ai = load_init_options(root).get("ai")
    if isinstance(configured_ai, str) and configured_ai in INTEGRATION_REGISTRY:
        used.add(configured_ai)

    folders = {".specify"}
    home_scopes: set[Path] = set()
    for key, integration in INTEGRATION_REGISTRY.items():
        config = integration.config or {}
        folder = (config.get("folder") or "").strip("/")
        if folder and (
            key in used or (root / folder).is_dir() and not (root / folder).is_symlink()
        ):
            folders.add(folder)
        directory = (integration.registrar_config or {}).get("dir", "")
        if key in used and directory.startswith("~/"):
            home_scopes.add(
                safe_project_path(Path.home().absolute(), directory[2:].rstrip("/"))
            )
    scopes = [safe_project_path(root, folder) for folder in sorted(folders)]
    scopes.extend(sorted(home_scopes))
    scopes = [
        path
        for path in scopes
        if not any(other != path and other in path.parents for other in scopes)
    ]

    lock_root = _trust_store(root).parent.parent
    lock_id = hashlib.sha256(os.path.normcase(str(root.resolve())).encode()).hexdigest()
    backup = Path(tempfile.mkdtemp(prefix="speckit-bundle-rollback-"))
    preserve = False
    try:
        with _exclusive_project_lock(
            lock_root, f".integration-install-{lock_id}.lock", context="bundle"
        ):
            journal = _FileJournal(
                root, scopes, backup, _initial_entries(scopes), tuple(home_scopes)
            )
            token = file_change_observer.set(journal.observe)
            try:
                yield
            except BaseException as operation_error:
                file_change_observer.reset(token)
                token = None
                try:
                    conflicts = _restore_snapshots(root, journal)
                except Exception as restore_error:  # noqa: BLE001 - preserve recovery data
                    preserve = True
                    raise BundlerError(
                        f"Bundle operation failed ({operation_error}); restore failed ({restore_error}). "
                        f"Recovery snapshots retained at {backup}"
                    ) from operation_error
                if conflicts:
                    preserve = True
                    raise BundlerError(
                        f"Bundle operation failed ({operation_error}); concurrent edits to "
                        f"{', '.join(map(str, conflicts))} were preserved. "
                        f"Recovery snapshots retained at {backup}"
                    ) from operation_error
                raise
            finally:
                if token is not None:
                    file_change_observer.reset(token)
    finally:
        if not preserve:
            shutil.rmtree(backup)
