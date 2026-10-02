"""Transactional edits to stable graph identifiers with a hash precondition."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .verify import AILError, array, shape, verify


def canonical(module):
    return json.dumps(module, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def fingerprint(module):
    return hashlib.sha256(canonical(module).encode("utf-8")).hexdigest()


def apply_patch(module, patch):
    verify(module)
    shape(patch, {"expected_sha256", "edits"}, "patch")
    if patch["expected_sha256"] != fingerprint(module):
        raise AILError("patch: stale program fingerprint")
    result = copy.deepcopy(module)
    array(patch["edits"], "patch/edits")
    for e in patch["edits"]:
        if not isinstance(e, dict):
            raise AILError("patch edit must be an object")
        op = e.get("op")
        if op == "replace_function":
            shape(e, {"op", "id", "value"}, "patch/replace_function")
            candidates = [(result["functions"], i) for i, f in enumerate(result["functions"]) if f["id"] == e["id"]]
        elif op == "replace_instruction":
            shape(e, {"op", "function", "block", "id", "value"}, "patch/replace_instruction")
            candidates = []
            for f in result["functions"]:
                if f["id"] == e["function"]:
                    for b in f["blocks"]:
                        if b["id"] == e["block"]:
                            candidates += [(b["instructions"], i) for i, ins in enumerate(b["instructions"]) if ins["id"] == e["id"]]
        else:
            raise AILError(f"patch: unknown edit {op}")
        if len(candidates) != 1:
            raise AILError("patch: target does not exist")
        if not isinstance(e["value"], dict) or e["value"].get("id") != e["id"]:
            raise AILError("patch: replacement must preserve the target id")
        container, index = candidates[0]
        container[index] = copy.deepcopy(e["value"])
        # Keep every intermediate graph valid; subsequent edits see verified data.
        verify(result)
    return result


def save(module, output):
    verify(module)
    path = Path(output).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".ail-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(canonical(module))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
