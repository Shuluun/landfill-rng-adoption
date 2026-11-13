"""Distances from frozen landfill coordinates to mapped pipeline segments."""

import struct
from zipfile import ZipFile

import numpy as np
from scipy.spatial import cKDTree

R_KM = 6371.0088


def unit_vectors(lon, lat):
    lon, lat = np.radians(lon), np.radians(lat)
    return np.stack((np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)), axis=-1)


def read_arcs(data, mercator=False):
    segments = []
    offset = 100
    while offset + 8 <= len(data):
        size = 2 * struct.unpack_from(">i", data, offset + 4)[0]
        content = memoryview(data)[offset + 8:offset + 8 + size]
        offset += 8 + size
        shape_type = struct.unpack_from("<i", content)[0]
        if shape_type == 0:
            continue
        if shape_type != 3:
            raise ValueError(f"Unexpected pipeline shape type {shape_type}")
        n_parts, n_points = struct.unpack_from("<ii", content, 36)
        if n_parts == 0 or n_points < 2:
            continue
        parts = np.frombuffer(content, dtype="<i4", count=n_parts, offset=44)
        points = np.frombuffer(content, dtype="<f8", count=2 * n_points, offset=44 + 4 * n_parts).reshape(-1, 2)
        if mercator:
            lon = np.degrees(points[:, 0] / 6378137.0)
            lat = np.degrees(2 * np.arctan(np.exp(points[:, 1] / 6378137.0)) - np.pi / 2)
        else:
            lon, lat = points.T
        vertices = unit_vectors(lon, lat)
        for start, stop in zip(parts, [*parts[1:], n_points], strict=True):
            if stop - start >= 2:
                segments.append(np.stack((vertices[start:stop - 1], vertices[start + 1:stop]), axis=1))
    return np.concatenate(segments, axis=0)


def eia_arcs(path):
    with ZipFile(path) as archive:
        members = [n for n in archive.namelist() if n.lower().endswith(".shp")]
        if len(members) != 1:
            raise ValueError(f"Expected one EIA geometry member, found {members}")
        projection = archive.read(members[0][:-4] + ".prj").decode("ascii").strip()
        if not projection.startswith('GEOGCS["GCS_WGS_1984"'):
            raise ValueError(projection)
        return read_arcs(archive.read(members[0])), members[0], projection


class ArcIndex:
    def __init__(self, segments):
        a, b = segments[:, 0], segments[:, 1]
        crosses = np.cross(a, b)
        lengths = np.linalg.norm(crosses, axis=1)
        dot = np.sum(a * b, axis=1)
        self.a, self.b = a, b
        self.normal = crosses / np.where(lengths > 0, lengths, 1)[:, None]
        self.tangent = np.cross(self.normal, a)
        self.angle = np.arctan2(lengths, dot)
        midpoint = a + b
        midpoint /= np.linalg.norm(midpoint, axis=1)[:, None]
        self.size = len(segments)
        self.groups = []
        bins = np.digitize(R_KM * self.angle / 2, [1, 5, 20, 100])
        for group in np.unique(bins):
            idx = np.flatnonzero(bins == group)
            self.groups.append((idx, cKDTree(midpoint[idx]), float(self.angle[idx].max() / 2)))

    def exact(self, point, idx):
        phase = np.arctan2(self.tangent[idx] @ point, self.a[idx] @ point)
        projection_inside = (phase >= 0) & (phase <= self.angle[idx]) & (self.angle[idx] > 0)
        height = np.arcsin(np.clip(np.abs(self.normal[idx] @ point), 0, 1))
        da = np.arctan2(np.linalg.norm(np.cross(self.a[idx], point), axis=1), self.a[idx] @ point)
        db = np.arctan2(np.linalg.norm(np.cross(self.b[idx], point), axis=1), self.b[idx] @ point)
        return float(np.min(np.where(projection_inside, height, np.minimum(da, db))))

    def nearest_km(self, point):
        seeds = [idx[tree.query(point)[1]] for idx, tree, _ in self.groups]
        best = self.exact(point, seeds)
        for idx, tree, half in self.groups:
            # Any closer arc has midpoint distance <= best + its half length.
            radius = 2 * np.sin(min(np.pi, best + half + 1e-12) / 2)
            candidates = idx[tree.query_ball_point(point, radius)]
            if len(candidates):
                best = min(best, self.exact(point, candidates))
        return R_KM * best

    def evaluate(self, points):
        nearest = np.array([self.nearest_km(point) for point in points])
        checks = np.unique(np.linspace(0, len(points) - 1, min(12, len(points)), dtype=int))
        errors = [abs(nearest[i] - R_KM * self.exact(points[i], np.arange(self.size))) for i in checks]
        if max(errors) > 1e-7:
            raise AssertionError("Indexed and full searches disagree")
        return nearest, {"arc_segments": self.size, "exhaustive_checks": len(checks),
                         "max_absolute_difference_km": max(errors)}
