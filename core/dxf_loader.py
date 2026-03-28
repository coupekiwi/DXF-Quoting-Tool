"""Load and parse DXF files, extract geometry and metadata."""

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import ezdxf
from ezdxf.entities import (
    Line, Arc, Circle, LWPolyline, Polyline, Spline, Ellipse,
)
from ezdxf.math import Vec2


@dataclass
class GeomSegment:
    """A drawable segment: line, arc, or circle."""
    kind: str  # "line", "arc", "circle"
    layer: str
    # Line: p1, p2
    # Arc: center, radius, start_angle, end_angle (degrees)
    # Circle: center, radius
    p1: Optional[tuple[float, float]] = None
    p2: Optional[tuple[float, float]] = None
    center: Optional[tuple[float, float]] = None
    radius: float = 0.0
    start_angle: float = 0.0
    end_angle: float = 0.0
    length: float = 0.0


@dataclass
class DxfPart:
    """A loaded DXF part with its geometry."""
    name: str
    filepath: str
    segments: list[GeomSegment] = field(default_factory=list)
    units: str = "mm"  # "mm" or "inch"
    # Bounding box (minx, miny, maxx, maxy)
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    total_cut_length: float = 0.0  # in file units

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def cut_length_m(self) -> float:
        """Cut length in metres."""
        if self.units == "inch":
            return self.total_cut_length * 0.0254
        return self.total_cut_length / 1000.0


# ezdxf $INSUNITS codes to unit strings
_UNIT_MAP = {
    0: "mm",   # unitless - assume mm
    1: "inch",
    2: "mm",   # feet -> treat as mm (rare for flat patterns)
    4: "mm",
    5: "mm",   # centimetres
    6: "mm",   # metres
}


def _arc_length(radius: float, start_deg: float, end_deg: float) -> float:
    """Compute arc length from start/end angles in degrees."""
    sweep = end_deg - start_deg
    if sweep <= 0:
        sweep += 360.0
    return abs(radius * math.radians(sweep))


def _polyline_segments(entity: LWPolyline, layer: str) -> list[GeomSegment]:
    """Convert an LWPolyline into line and arc segments."""
    segments = []
    points = list(entity.get_points(format="xyseb"))
    closed = entity.closed

    for i in range(len(points)):
        x1, y1, _s, _e, bulge = points[i]
        if i + 1 < len(points):
            x2, y2 = points[i + 1][0], points[i + 1][1]
        elif closed:
            x2, y2 = points[0][0], points[0][1]
        else:
            break

        if abs(bulge) < 1e-10:
            # Straight segment
            length = math.hypot(x2 - x1, y2 - y1)
            segments.append(GeomSegment(
                kind="line", layer=layer,
                p1=(x1, y1), p2=(x2, y2),
                length=length,
            ))
        else:
            # Bulge arc segment
            dx, dy = x2 - x1, y2 - y1
            chord = math.hypot(dx, dy)
            sagitta = abs(bulge) * chord / 2.0
            radius = (chord**2 / 4 + sagitta**2) / (2 * sagitta)
            # Sweep angle
            sweep = 4.0 * math.atan(abs(bulge))
            arc_len = radius * sweep

            # Compute arc center
            mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
            dist_to_center = radius - sagitta
            norm = math.hypot(dx, dy)
            if norm < 1e-12:
                continue
            # Normal direction depends on bulge sign
            if bulge > 0:
                nx, ny = -dy / norm, dx / norm
            else:
                nx, ny = dy / norm, -dx / norm
            cx = mid_x + nx * dist_to_center
            cy = mid_y + ny * dist_to_center

            start_angle = math.degrees(math.atan2(y1 - cy, x1 - cx))
            end_angle = math.degrees(math.atan2(y2 - cy, x2 - cx))

            segments.append(GeomSegment(
                kind="arc", layer=layer,
                center=(cx, cy), radius=radius,
                start_angle=start_angle, end_angle=end_angle,
                length=arc_len,
            ))
    return segments


def load_dxf(filepath: str, unit_override: Optional[str] = None) -> DxfPart:
    """Load a DXF file and return a DxfPart with extracted geometry."""
    path = Path(filepath)
    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()

    # Determine units
    insunits = doc.header.get("$INSUNITS", 0)
    units = _UNIT_MAP.get(insunits, "mm")
    if unit_override:
        units = unit_override

    segments: list[GeomSegment] = []

    for entity in msp:
        layer = entity.dxf.layer if hasattr(entity.dxf, "layer") else "0"

        if isinstance(entity, Line):
            p1 = (entity.dxf.start.x, entity.dxf.start.y)
            p2 = (entity.dxf.end.x, entity.dxf.end.y)
            length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            segments.append(GeomSegment(
                kind="line", layer=layer,
                p1=p1, p2=p2, length=length,
            ))

        elif isinstance(entity, Arc):
            # Arc must be checked before Circle since Arc inherits from Circle

            cx, cy = entity.dxf.center.x, entity.dxf.center.y
            r = entity.dxf.radius
            sa = entity.dxf.start_angle
            ea = entity.dxf.end_angle
            length = _arc_length(r, sa, ea)
            segments.append(GeomSegment(
                kind="arc", layer=layer,
                center=(cx, cy), radius=r,
                start_angle=sa, end_angle=ea,
                length=length,
            ))

        elif isinstance(entity, Circle):
            cx, cy = entity.dxf.center.x, entity.dxf.center.y
            r = entity.dxf.radius
            length = 2 * math.pi * r
            segments.append(GeomSegment(
                kind="circle", layer=layer,
                center=(cx, cy), radius=r, length=length,
            ))

        elif isinstance(entity, LWPolyline):
            segments.extend(_polyline_segments(entity, layer))

        elif isinstance(entity, Ellipse):
            # Approximate ellipse perimeter
            cx, cy = entity.dxf.center.x, entity.dxf.center.y
            major = entity.dxf.major_axis
            ratio = entity.dxf.ratio
            a = math.hypot(major.x, major.y)
            b = a * ratio
            # Ramanujan approximation
            length = math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))
            segments.append(GeomSegment(
                kind="circle", layer=layer,
                center=(cx, cy), radius=a, length=length,
            ))

    # Compute bounding box
    all_points: list[tuple[float, float]] = []
    for seg in segments:
        if seg.kind == "line" and seg.p1 and seg.p2:
            all_points.extend([seg.p1, seg.p2])
        elif seg.kind == "circle" and seg.center:
            cx, cy = seg.center
            r = seg.radius
            all_points.extend([
                (cx - r, cy - r), (cx + r, cy + r),
            ])
        elif seg.kind == "arc" and seg.center:
            cx, cy = seg.center
            r = seg.radius
            # Conservative: use full circle extent for bbox
            all_points.extend([
                (cx - r, cy - r), (cx + r, cy + r),
            ])

    if all_points:
        xs = [p[0] for p in all_points]
        ys = [p[1] for p in all_points]
        bbox = (min(xs), min(ys), max(xs), max(ys))
    else:
        bbox = (0, 0, 0, 0)

    total_cut = sum(s.length for s in segments)

    return DxfPart(
        name=path.stem,
        filepath=str(path),
        segments=segments,
        units=units,
        bbox=bbox,
        total_cut_length=total_cut,
    )
