"""API contract snapshot yordamchilari.

Production frontend shu response shakllariga tayanadi. Snapshot fayllar
`common/tests/snapshots/` da saqlanadi va har test ishga tushganda solishtiriladi.

Ataylab (front bilan kelishib) o‘zgartirilganda snapshotlarni yangilash::

    UPDATE_SNAPSHOTS=1 pytest common/tests/test_schema_snapshot.py \
        apps/attempts/tests/test_contract_golden.py

va `git diff common/tests/snapshots/` ni ko‘rib chiqing.
"""

import json
import os
from pathlib import Path

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


def _type_name(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def _merge(a, b):
    """Ikki shaklni birlashtiradi (savollar tartibi random — ro‘yxat elementlari farq qiladi)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return {
            key: _merge(a[key], b[key]) if key in a and key in b else a.get(key, b.get(key))
            for key in sorted(a.keys() | b.keys())
        }
    if isinstance(a, list) and isinstance(b, list):
        if not a or not b:
            return a or b
        return [_merge(a[0], b[0])]
    if a == b:
        return a
    parts = set()
    for item in (a, b):
        parts.update(item.split("|") if isinstance(item, str) else [json.dumps(item)])
    return "|".join(sorted(parts))


def shape(value):
    """JSON qiymatining shakli: kalitlar va tiplar (qiymatlar emas).

    Ro‘yxat uchun — barcha elementlar shakllarining birlashmasi (bo‘sh ro‘yxat — `[]`).
    """
    if isinstance(value, dict):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        merged = None
        for item in value:
            item_shape = shape(item)
            merged = item_shape if merged is None else _merge(merged, item_shape)
        return [] if merged is None else [merged]
    return _type_name(value)


def _update_requested() -> bool:
    return os.environ.get("UPDATE_SNAPSHOTS") == "1"


def assert_matches_snapshot(name: str, actual_text: str) -> None:
    path = SNAPSHOT_DIR / name
    if _update_requested() or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual_text, encoding="utf-8", newline="\n")
        if not _update_requested():
            raise AssertionError(f"Snapshot yaratildi: {path}. Testni qayta ishga tushiring.")
        return
    expected = path.read_text(encoding="utf-8")
    assert actual_text == expected, (
        f"API contract o‘zgardi ({name}). Front buzilishi mumkin! "
        "Ataylab bo‘lsa — UPDATE_SNAPSHOTS=1 bilan yangilang va diffni tekshiring."
    )


def assert_shape_snapshot(name: str, payload) -> None:
    text = json.dumps(shape(payload), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    assert_matches_snapshot(f"{name}.json", text)
