"""
Diff Engine - Compare routing tables across multiple files.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from pathlib import Path
from collections import Counter

from shared.rib_reader import RIBReader, RouteInfo


# Severity levels for differences
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
SEVERITY_COLORS = {
    "CRITICAL": "red",
    "HIGH": "orange",
    "MEDIUM": "yellow",
    "LOW": "blue",
}


@dataclass
class DiffResult:
    """Represents a single difference between routing tables."""

    table: str
    prefix: str
    is_active: bool
    category: str
    field: str
    severity: str
    values: Dict[str, str]  # device_name -> value

    def to_row(self, devices: List[str]) -> List[str]:
        """Convert to table row format."""
        active_marker = "*" if self.is_active else ""
        row = [
            f"[{SEVERITY_COLORS.get(self.severity, 'white')}]{self.severity}[/]",
            self.table,
            f"{active_marker}{self.prefix}",
            self.category,
            self.field,
        ]
        for dev in devices:
            val = self.values.get(dev, "N/A")
            if val == "MISSING":
                val = "[red]MISSING[/]"
            elif val == "PRESENT":
                val = "[green]PRESENT[/]"
            row.append(val)
        return row


@dataclass
class DiffSummary:
    """Summary of comparison results."""

    total_diffs: int = 0
    by_severity: Dict[str, int] = field(default_factory=dict)
    by_table: Dict[str, int] = field(default_factory=dict)
    by_category: Dict[str, int] = field(default_factory=dict)


class DiffEngine:
    """Engine for comparing routing tables across multiple files."""

    def __init__(self):
        self.devices: Dict[str, List[RouteInfo]] = {}  # device_name -> routes
        self.readers: Dict[str, RIBReader] = {}

    def load_file(self, file_path: Path, device_name: Optional[str] = None) -> bool:
        """Load a routing table file."""
        reader = RIBReader()
        if not reader.read_file(file_path):
            return False

        name = device_name or file_path.stem
        self.devices[name] = reader.get_routes()
        self.readers[name] = reader
        return True

    def unload_file(self, device_name: str) -> None:
        """Remove a loaded file."""
        self.devices.pop(device_name, None)
        self.readers.pop(device_name, None)

    def get_loaded_devices(self) -> List[str]:
        """Get list of loaded device names."""
        return list(self.devices.keys())

    def get_available_tables(self) -> List[str]:
        """Get list of all tables across loaded files."""
        tables = set()
        for routes in self.devices.values():
            for route in routes:
                tables.add(route.table)
        return sorted(tables)

    def compare(
        self,
        table_filter: Optional[str] = None,
        min_severity: Optional[str] = None,
        include_inactive: bool = True,
    ) -> List[DiffResult]:
        """
        Compare loaded routing tables and return differences.

        Args:
            table_filter: Only compare this table (e.g., "inet.0")
            min_severity: Minimum severity to include
            include_inactive: Include inactive routes in comparison

        Returns:
            List of DiffResult objects
        """
        if len(self.devices) < 2:
            return []

        device_names = list(self.devices.keys())
        diffs = []

        # Build route index: (table, prefix, active) -> {device: RouteInfo}
        route_index: Dict[tuple, Dict[str, RouteInfo]] = {}

        for device_name, routes in self.devices.items():
            for route in routes:
                if table_filter and route.table != table_filter:
                    continue
                if not include_inactive and not route.active:
                    continue

                key = (route.table, route.prefix, route.active)
                if key not in route_index:
                    route_index[key] = {}
                route_index[key][device_name] = route

        # Compare each route across devices
        for (table, prefix, is_active), device_routes in route_index.items():
            route_diffs = self._compare_route(
                table, prefix, is_active, device_routes, device_names
            )
            diffs.extend(route_diffs)

        # Filter by severity
        if min_severity:
            threshold = SEVERITY_ORDER.get(min_severity.upper(), 3)
            diffs = [
                d for d in diffs if SEVERITY_ORDER.get(d.severity, 99) <= threshold
            ]

        # Sort by severity, table, prefix
        diffs.sort(
            key=lambda d: (SEVERITY_ORDER.get(d.severity, 99), d.table, d.prefix)
        )

        return diffs

    def _compare_route(
        self,
        table: str,
        prefix: str,
        is_active: bool,
        device_routes: Dict[str, RouteInfo],
        device_names: List[str],
    ) -> List[DiffResult]:
        """Compare a single route across devices."""
        diffs = []

        def emit(category: str, field: str, severity: str, values: Dict[str, str]):
            unique_vals = set(values.values())
            if len(unique_vals) > 1:
                diffs.append(
                    DiffResult(
                        table=table,
                        prefix=prefix,
                        is_active=is_active,
                        category=category,
                        field=field,
                        severity=severity,
                        values=values,
                    )
                )

        # 1. Presence check
        presence = {}
        for dev in device_names:
            presence[dev] = "PRESENT" if dev in device_routes else "MISSING"
        emit("Presence", "Status", "CRITICAL", presence)

        if len(device_routes) < 2:
            return diffs

        # 2. Protocol comparison
        protocols = {dev: r.protocol for dev, r in device_routes.items()}
        emit("Protocol", "Protocol", "CRITICAL", protocols)

        # 3. Preference
        prefs = {dev: str(r.preference) for dev, r in device_routes.items()}
        emit("Protocol", "Preference", "HIGH", prefs)

        # 4. BGP-specific attributes
        if any(r.protocol == "BGP" for r in device_routes.values()):
            # Local Preference
            local_prefs = {dev: r.local_pref or "" for dev, r in device_routes.items()}
            emit("BGP", "Local-Pref", "HIGH", local_prefs)

            # MED
            meds = {dev: r.med or "" for dev, r in device_routes.items()}
            emit("BGP", "MED", "HIGH", meds)

            # Origin AS
            origin_as = {dev: r.origin_as or "" for dev, r in device_routes.items()}
            emit("BGP", "Origin-AS", "HIGH", origin_as)

            # AS Path
            as_paths = {dev: r.as_path or "" for dev, r in device_routes.items()}
            emit("BGP", "AS-Path", "MEDIUM", as_paths)

            # Learned-From
            learned_from = {
                dev: r.learned_from or "" for dev, r in device_routes.items()
            }
            emit("BGP", "Learned-From", "MEDIUM", learned_from)

            # Peer-Type
            peer_types = {dev: r.peer_type or "" for dev, r in device_routes.items()}
            emit("BGP", "Peer-Type", "MEDIUM", peer_types)

            # Communities
            communities = {
                dev: "|".join(sorted(r.communities)) if r.communities else ""
                for dev, r in device_routes.items()
            }
            emit("BGP", "Communities", "MEDIUM", communities)

        # 5. Next-hop (for all protocols)
        next_hops = {dev: r.next_hop or "" for dev, r in device_routes.items()}
        emit("Next-Hop", "Gateway", "CRITICAL", next_hops)

        return diffs

    def get_summary(self, diffs: List[DiffResult]) -> DiffSummary:
        """Generate summary statistics from diff results."""
        summary = DiffSummary()
        summary.total_diffs = len(diffs)

        for diff in diffs:
            summary.by_severity[diff.severity] = (
                summary.by_severity.get(diff.severity, 0) + 1
            )
            summary.by_table[diff.table] = summary.by_table.get(diff.table, 0) + 1
            summary.by_category[diff.category] = (
                summary.by_category.get(diff.category, 0) + 1
            )

        return summary

    def get_route_counts(
        self, table_filter: Optional[str] = None
    ) -> Dict[str, Dict[str, int]]:
        """Get route counts per device per table."""
        counts = {}

        for device_name, routes in self.devices.items():
            counts[device_name] = {}
            for route in routes:
                if table_filter and route.table != table_filter:
                    continue
                table = route.table
                counts[device_name][table] = counts[device_name].get(table, 0) + 1

        return counts
