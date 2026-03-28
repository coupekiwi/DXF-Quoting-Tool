"""Rectangular bounding-box nesting using a bottom-left-fill algorithm."""

from dataclasses import dataclass, field


@dataclass
class NestItem:
    """A part to be nested, with its bounding box dimensions."""
    name: str
    width: float   # in file units (mm)
    height: float  # in file units (mm)
    cut_length: float  # total cut length in file units


@dataclass
class PlacedPart:
    """A part placed on a sheet."""
    name: str
    x: float
    y: float
    width: float   # as-placed width
    height: float  # as-placed height
    rotated: bool
    sheet_index: int


@dataclass
class NestResult:
    """Result of a nesting operation."""
    placements: list[PlacedPart] = field(default_factory=list)
    sheets_used: int = 0
    sheet_width: float = 0.0
    sheet_height: float = 0.0
    total_cut_length: float = 0.0  # in file units
    total_part_area: float = 0.0
    total_sheet_area: float = 0.0

    @property
    def utilisation(self) -> float:
        if self.total_sheet_area == 0:
            return 0.0
        return (self.total_part_area / self.total_sheet_area) * 100.0


def _overlaps(x1: float, y1: float, w1: float, h1: float,
              x2: float, y2: float, w2: float, h2: float) -> bool:
    """Check if two rectangles overlap (with tiny tolerance)."""
    return not (x1 + w1 <= x2 + 0.01 or x2 + w2 <= x1 + 0.01 or
                y1 + h1 <= y2 + 0.01 or y2 + h2 <= y1 + 0.01)


def _find_bottom_left(
    w: float, h: float,
    placed: list[PlacedPart],
    sheet_width: float,
    sheet_height: float,
    gap: float,
    edge: float,
) -> tuple[float, float] | None:
    """
    Find the bottom-left-most position for a rectangle of size w x h.

    Scans candidate X positions (left edge of sheet + right edges of all
    placed parts), and for each X scans candidate Y positions (top edge
    of sheet + top edges of placed parts). Returns the position with the
    smallest X, breaking ties by smallest Y.

    edge: offset from sheet edges.
    gap: spacing between parts.
    """
    usable_w = sheet_width - edge
    usable_h = sheet_height - edge
    if edge + w > usable_w or edge + h > usable_h:
        return None

    # Candidate X positions: edge margin, plus right-edge+gap of every placed part
    x_candidates = [edge]
    for p in placed:
        x_candidates.append(p.x + p.width + gap)

    # Remove duplicates and sort
    x_candidates = sorted(set(x_candidates))

    best: tuple[float, float] | None = None

    for cx in x_candidates:
        if cx + w > usable_w + 0.01:
            continue

        # Candidate Y positions for this X
        y_candidates = [edge]
        for p in placed:
            # Only consider parts that overlap in the X range
            if p.x + p.width + gap > cx - 0.01 and p.x < cx + w + gap + 0.01:
                y_candidates.append(p.y + p.height + gap)

        y_candidates = sorted(set(y_candidates))

        for cy in y_candidates:
            if cy + h > usable_h + 0.01:
                continue

            # Check no overlap with any placed part (including gap)
            fits = True
            for p in placed:
                if _overlaps(cx, cy, w, h,
                             p.x - gap, p.y - gap, p.width + gap, p.height + gap):
                    # More precise: check actual gap-expanded rects
                    if _overlaps(cx, cy, w, h,
                                 p.x, p.y, p.width, p.height):
                        fits = False
                        break
                    # Check gap: the part must be at least gap away
                    x_gap_ok = (cx + w <= p.x - gap + 0.01 or p.x + p.width <= cx - gap + 0.01)
                    y_gap_ok = (cy + h <= p.y - gap + 0.01 or p.y + p.height <= cy - gap + 0.01)
                    if not x_gap_ok and not y_gap_ok:
                        fits = False
                        break

            if fits:
                # Bottom-left: prefer smallest X, then smallest Y
                if best is None or (cx < best[0] - 0.01) or (abs(cx - best[0]) < 0.01 and cy < best[1]):
                    best = (cx, cy)
                break  # Found best Y for this X, move to next X

    return best


def nest_parts(
    items: list[NestItem],
    sheet_width: float,
    sheet_height: float,
    gap: float = 2.0,
    edge_offset: float = 0.0,
) -> NestResult:
    """
    Nest parts onto sheets using a bottom-left-fill algorithm.

    For each part, tries both 0 and 90 degree orientations and places it
    at the leftmost (then lowest) position where it fits without overlapping
    any already-placed part.

    edge_offset: minimum distance from all sheet edges.
    """
    edge = edge_offset if edge_offset > 0 else gap
    # Sort by area descending for better packing
    sorted_items = sorted(items, key=lambda it: it.width * it.height, reverse=True)

    placements: list[PlacedPart] = []
    # Track placements per sheet for collision checking
    sheet_placements: list[list[PlacedPart]] = []

    for item in sorted_items:
        placed = False

        for sheet_idx in range(len(sheet_placements)):
            existing = sheet_placements[sheet_idx]

            best_pos = None
            best_rotated = False
            best_w = 0.0
            best_h = 0.0

            # Try both orientations
            for rotated in [False, True]:
                w = item.height if rotated else item.width
                h = item.width if rotated else item.height

                pos = _find_bottom_left(w, h, existing, sheet_width, sheet_height, gap, edge)
                if pos is not None:
                    if best_pos is None or (pos[0] < best_pos[0] - 0.01) or \
                       (abs(pos[0] - best_pos[0]) < 0.01 and pos[1] < best_pos[1]):
                        best_pos = pos
                        best_rotated = rotated
                        best_w = w
                        best_h = h

            if best_pos is not None:
                p = PlacedPart(
                    name=item.name,
                    x=best_pos[0], y=best_pos[1],
                    width=best_w, height=best_h,
                    rotated=best_rotated,
                    sheet_index=sheet_idx,
                )
                placements.append(p)
                existing.append(p)
                placed = True
                break

        if not placed:
            # New sheet
            sheet_idx = len(sheet_placements)
            sheet_placements.append([])

            best_pos = None
            best_rotated = False
            best_w = item.width
            best_h = item.height

            for rotated in [False, True]:
                w = item.height if rotated else item.width
                h = item.width if rotated else item.height
                pos = _find_bottom_left(w, h, [], sheet_width, sheet_height, gap, edge)
                if pos is not None:
                    if best_pos is None or pos[0] < best_pos[0]:
                        best_pos = pos
                        best_rotated = rotated
                        best_w = w
                        best_h = h

            if best_pos is None:
                best_pos = (edge, edge)

            p = PlacedPart(
                name=item.name,
                x=best_pos[0], y=best_pos[1],
                width=best_w, height=best_h,
                rotated=best_rotated,
                sheet_index=sheet_idx,
            )
            placements.append(p)
            sheet_placements[-1].append(p)

    total_cut = sum(it.cut_length for it in items)
    total_part_area = sum(it.width * it.height for it in items)
    sheets_used = max((p.sheet_index for p in placements), default=-1) + 1

    return NestResult(
        placements=placements,
        sheets_used=sheets_used,
        sheet_width=sheet_width,
        sheet_height=sheet_height,
        total_cut_length=total_cut,
        total_part_area=total_part_area,
        total_sheet_area=sheets_used * sheet_width * sheet_height,
    )


@dataclass
class QuoteResult:
    """Costing result."""
    sheets_needed: int
    sheet_cost_each: float
    sheet_cost_total: float
    cut_length_m: float
    cut_cost_per_m: float
    cut_cost_total: float
    grand_total: float
    utilisation: float


def calculate_quote(
    nest: NestResult,
    sheet_cost: float,
    cut_cost_per_m: float,
    units: str = "mm",
) -> QuoteResult:
    """Calculate a quote from nesting results."""
    if units == "inch":
        cut_length_m = nest.total_cut_length * 0.0254
    else:
        cut_length_m = nest.total_cut_length / 1000.0

    sheet_total = nest.sheets_used * sheet_cost
    cut_total = cut_length_m * cut_cost_per_m

    return QuoteResult(
        sheets_needed=nest.sheets_used,
        sheet_cost_each=sheet_cost,
        sheet_cost_total=sheet_total,
        cut_length_m=cut_length_m,
        cut_cost_per_m=cut_cost_per_m,
        cut_cost_total=cut_total,
        grand_total=sheet_total + cut_total,
        utilisation=nest.utilisation,
    )
