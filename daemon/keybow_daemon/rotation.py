"""Maps between the pad's fixed physical key positions and the "logical"
positions used everywhere else (config, web UI, LED addressing), so a
`rotation` setting lets you physically turn the device without having to
redo your key layout — logical position 0 stays "the same key" from your
perspective no matter which physical key currently occupies it.

Uses the exact same clockwise-rotation matrix math as PMK's own
`PMK.rotate()`, just computed once per rotation value instead of re-sorting
key objects on a live device.
"""
from __future__ import annotations

NUM_KEYS = 16


def _build_map(num_quarter_turns: int) -> list[int]:
    matrix = [[(x * 4) + y for y in range(4)] for x in range(4)]
    for _ in range(num_quarter_turns % 4):
        matrix = [list(row) for row in zip(*matrix[::-1])]
    return [v for row in matrix for v in row]


# physical_to_logical[degrees][physical_index] = logical_index
_PHYSICAL_TO_LOGICAL = {
    0: _build_map(0),
    90: _build_map(1),
    180: _build_map(2),
    270: _build_map(3),
}
_LOGICAL_TO_PHYSICAL = {
    degrees: [mapping.index(logical) for logical in range(NUM_KEYS)]
    for degrees, mapping in _PHYSICAL_TO_LOGICAL.items()
}


def physical_to_logical(degrees: int, physical_index: int) -> int:
    return _PHYSICAL_TO_LOGICAL[degrees][physical_index]


def logical_to_physical(degrees: int, logical_index: int) -> int:
    return _LOGICAL_TO_PHYSICAL[degrees][logical_index]
