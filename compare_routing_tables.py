#!/usr/bin/env python3
"""
compare_routing_tables.py  —  v2
Compares multiple Juniper routing table JSON files (Junos native JSON format)
and reports ALL differences in structured table output.

Comparison scope
────────────────
Presence changes:
  • Route added / removed across devices

Protocol-level changes (same prefix, different protocol):
  • Protocol switch (BGP → OSPF, LDP → RSVP, …)
  • Preference / administrative distance change

BGP attribute changes:
  • Local-preference, MED
  • AS-path (full + origin AS extracted separately)
  • Learned-from (RR/peer IP change)
  • Peer-type (customer / peer / upstream)
  • Communities added, removed, or changed

OSPF attribute changes:
  • Metric

RSVP / inet.3 attribute changes:
  • Tunnel name, bandwidth

MPLS forwarding (mpls.0) changes:
  • Operation (Pop / Swap / Push)
  • Outgoing label, VPN label
  • Incoming label (destination field in mpls.0)

Next-hop changes (per-hop granularity):
  • Next-hop count (ECMP added / removed)
  • Gateway IP (to=) per hop
  • Egress interface (via=) per hop
  • MPLS label imposition per hop

Usage:
  python compare_routing_tables.py <file1.json> <file2.json> [more...]
  python compare_routing_tables.py rib-data/*.json
  python compare_routing_tables.py rib-data/*.json --table inet.0
  python compare_routing_tables.py rib-data/*.json --output report.txt
  python compare_routing_tables.py rib-data/*.json --csv diffs.csv
  python compare_routing_tables.py rib-data/*.json --presence-only
  python compare_routing_tables.py rib-data/*.json --severity critical
"""

import json
import argparse
import sys
import os
import csv
from dataclasses import dataclass, field
from typing import Optional
from collections import Counter
from itertools import groupby


# ─────────────────────────────────────────────────────────────────────────────
# Severity levels
# ─────────────────────────────────────────────────────────────────────────────
# Each diff category is tagged with a severity so operators can filter noise.
#
#   CRITICAL  — route missing / added; protocol flipped; next-hop gone
#   HIGH      — BGP best-path attributes changed (LP, MED, AS-path origin)
#   MEDIUM    — Communities, learned-from, peer-type, OSPF metric, RSVP BW
#   LOW       — Interface change, label change, AS-path transit change
# ─────────────────────────────────────────────────────────────────────────────

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


# ─────────────────────────────────────────────────────────────────────────────
# Junos JSON envelope helpers
# ─────────────────────────────────────────────────────────────────────────────


def _unwrap(val):
    """[{"data": x}]  ->  x"""
    if isinstance(val, list) and val and isinstance(val[0], dict):
        data = val[0].get("data")
        if isinstance(data, list) and data == [None]:
            return None
        return data
    return val


def _unwrap_str(val) -> str:
    r = _unwrap(val)
    return str(r) if r is not None else ""


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class NextHop:
    to: Optional[str] = None  # gateway IP
    via: Optional[str] = None  # egress interface
    mpls_label: Optional[str] = None  # label operation string


@dataclass
class Route:
    destination: str
    protocol: str
    preference: str
    active: bool

    # ── BGP ──────────────────────────────────────────────────────────────────
    local_pref: Optional[str] = None
    med: Optional[str] = None
    as_path: Optional[str] = None  # full AS-path string
    origin_as: Optional[str] = None  # rightmost AS before path-type token
    as_path_len: Optional[int] = None  # number of AS hops
    learned_from: Optional[str] = None
    peer_type: Optional[str] = None
    communities: list = field(default_factory=list)

    # ── OSPF ─────────────────────────────────────────────────────────────────
    metric: Optional[str] = None

    # ── RSVP / inet.3 ────────────────────────────────────────────────────────
    tunnel_name: Optional[str] = None
    bandwidth_kbps: Optional[str] = None

    # ── MPLS forwarding ──────────────────────────────────────────────────────
    nh_type: Optional[str] = None  # Pop / Swap / Push
    outgoing_label: Optional[str] = None
    vpn_label: Optional[str] = None
    incoming_label: Optional[str] = None  # destination in mpls.0

    # ── Next-hops (structured) ───────────────────────────────────────────────
    next_hops: list = field(default_factory=list)  # list[NextHop]


# ─────────────────────────────────────────────────────────────────────────────
# AS-path helpers
# ─────────────────────────────────────────────────────────────────────────────


def _parse_as_path(as_path_str: str) -> tuple:
    """
    Return (origin_as, path_length) from a Junos AS-path string.
    E.g. "3356 1299 65001 I"  ->  ("65001", 3)
         "65001 I"            ->  ("65001", 1)
         "I"                  ->  (None, 0)   <- locally originated
    """
    if not as_path_str:
        return None, 0
    tokens = as_path_str.split()
    as_tokens = [t for t in tokens if t not in ("I", "E", "?", "Aggregated")]
    if not as_tokens:
        return None, 0
    return as_tokens[-1], len(as_tokens)


# ─────────────────────────────────────────────────────────────────────────────
# JSON parsing
# ─────────────────────────────────────────────────────────────────────────────


def _parse_next_hops(nh_list: list) -> list:
    hops = []
    for nh in nh_list:
        hops.append(
            NextHop(
                to=_unwrap_str(nh.get("to")) or None,
                via=_unwrap_str(nh.get("via")) or None,
                mpls_label=_unwrap_str(nh.get("mpls-label")) or None,
            )
        )
    return hops


def _parse_rt_entry(entry: dict, destination: str) -> "Route":
    active_tag = _unwrap_str(entry.get("active-tag"))
    active = active_tag.strip() == "*"
    protocol = _unwrap_str(entry.get("protocol-name"))
    preference = _unwrap_str(entry.get("preference"))

    route = Route(
        destination=destination,
        protocol=protocol,
        preference=preference,
        active=active,
    )

    # ── BGP ──────────────────────────────────────────────────────────────────
    if protocol == "BGP":
        route.local_pref = _unwrap_str(entry.get("local-preference")) or None
        route.med = _unwrap_str(entry.get("med")) or None
        route.learned_from = _unwrap_str(entry.get("learned-from")) or None
        route.peer_type = _unwrap_str(entry.get("peer-type")) or None
        as_path_raw = _unwrap_str(entry.get("as-path"))
        route.as_path = as_path_raw or None
        route.origin_as, route.as_path_len = _parse_as_path(as_path_raw)
        for c in entry.get("communities", []):
            if isinstance(c, dict):
                route.communities.append(_unwrap_str(c.get("community")))

    # ── OSPF ─────────────────────────────────────────────────────────────────
    elif protocol == "OSPF":
        route.metric = _unwrap_str(entry.get("metric")) or None

    # ── RSVP ─────────────────────────────────────────────────────────────────
    elif protocol == "RSVP":
        route.tunnel_name = _unwrap_str(entry.get("tunnel-name")) or None
        route.bandwidth_kbps = _unwrap_str(entry.get("bandwidth-kbps")) or None

    # ── MPLS forwarding (present regardless of protocol label) ───────────────
    nh_type = entry.get("nh-type")
    if nh_type:
        route.nh_type = _unwrap_str(nh_type) or None
        route.outgoing_label = _unwrap_str(entry.get("outgoing-label")) or None
        route.vpn_label = _unwrap_str(entry.get("vpn-label")) or None

    # mpls.0 destinations are numeric labels
    if destination.isdigit():
        route.incoming_label = destination

    route.next_hops = _parse_next_hops(entry.get("nh", []))
    return route


def load_device_tables(filepath: str) -> dict:
    """
    Parse a Junos JSON routing file.
    Returns: { table_name: { route_key: Route } }
    route_key = "<destination>|active" or "<destination>|inactive"
    """
    with open(filepath) as f:
        doc = json.load(f)

    route_info = doc.get("route-information", [{}])[0]
    raw_tables = route_info.get("route-table", [])
    tables = {}

    for tbl in raw_tables:
        table_name = _unwrap_str(tbl.get("table-name"))
        routes = {}
        for rt in tbl.get("rt", []):
            destination = _unwrap_str(rt.get("rt-destination"))
            for entry in rt.get("rt-entry", []):
                route = _parse_rt_entry(entry, destination)
                key = f"{destination}|{'active' if route.active else 'inactive'}"
                routes[key] = route
        tables[table_name] = routes

    return tables


# ─────────────────────────────────────────────────────────────────────────────
# Diff data model
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DiffRow:
    table: str
    destination: str
    path_type: str  # "active" | "inactive"
    category: str  # diff category label
    field: str  # specific field name
    severity: str  # CRITICAL / HIGH / MEDIUM / LOW
    values: dict  # device_name -> displayed value


# ─────────────────────────────────────────────────────────────────────────────
# Comparison engine
# ─────────────────────────────────────────────────────────────────────────────


def _emit(
    table,
    destination,
    path_type,
    category,
    field_label,
    severity,
    device_names,
    field_vals: dict,
) -> Optional[DiffRow]:
    """Return a DiffRow only when values differ across at least two devices."""
    all_vals = {dev: field_vals.get(dev, "N/A") for dev in device_names}
    if len(set(all_vals.values())) > 1:
        return DiffRow(
            table, destination, path_type, category, field_label, severity, all_vals
        )
    return None


def compare_routes(
    table_name: str,
    destination: str,
    path_type: str,
    routes: dict,  # device -> Route | None
    device_names: list,
) -> list:
    """
    Deep comparison of one prefix/path across all devices.
    Returns list[DiffRow].
    """
    diffs = []

    def emit(category, field_label, severity, field_vals):
        d = _emit(
            table_name,
            destination,
            path_type,
            category,
            field_label,
            severity,
            device_names,
            field_vals,
        )
        if d:
            diffs.append(d)

    # ── 1. Presence ──────────────────────────────────────────────────────────
    presence = {
        dev: "PRESENT" if r is not None else "MISSING" for dev, r in routes.items()
    }
    emit("Presence", "Route present", "CRITICAL", presence)

    existing = {dev: r for dev, r in routes.items() if r is not None}
    if len(existing) < 2:
        return diffs

    # ── 2. Protocol & administrative distance ────────────────────────────────
    emit(
        "Protocol", "Protocol", "CRITICAL", {d: r.protocol for d, r in existing.items()}
    )
    emit(
        "Protocol", "Preference", "HIGH", {d: r.preference for d, r in existing.items()}
    )

    # ── 3. BGP attributes ────────────────────────────────────────────────────
    if any(r.protocol == "BGP" for r in existing.values()):
        emit(
            "BGP",
            "Local-Pref",
            "HIGH",
            {d: r.local_pref or "" for d, r in existing.items()},
        )
        emit("BGP", "MED", "HIGH", {d: r.med or "" for d, r in existing.items()})
        emit(
            "BGP",
            "Origin-AS",
            "HIGH",
            {d: r.origin_as or "" for d, r in existing.items()},
        )
        emit(
            "BGP",
            "AS-Path-Len",
            "MEDIUM",
            {
                d: str(r.as_path_len) if r.as_path_len is not None else ""
                for d, r in existing.items()
            },
        )
        emit(
            "BGP",
            "AS-Path",
            "MEDIUM",
            {d: r.as_path or "" for d, r in existing.items()},
        )
        emit(
            "BGP",
            "Learned-From",
            "MEDIUM",
            {d: r.learned_from or "" for d, r in existing.items()},
        )
        emit(
            "BGP",
            "Peer-Type",
            "MEDIUM",
            {d: r.peer_type or "" for d, r in existing.items()},
        )

        # Communities — full set comparison
        emit(
            "BGP",
            "Communities",
            "MEDIUM",
            {
                d: "|".join(sorted(r.communities)) if r.communities else ""
                for d, r in existing.items()
            },
        )

        # Per-community presence diff (shows exactly which community changed)
        all_comms = set()
        for r in existing.values():
            all_comms.update(r.communities)
        if all_comms:
            comm_sets = {dev: set(r.communities) for dev, r in existing.items()}
            intersection = set.intersection(*comm_sets.values())
            for comm in sorted(all_comms - intersection):
                comm_presence = {
                    dev: "YES" if comm in comm_sets.get(dev, set()) else "NO"
                    for dev in device_names
                }
                if len(set(comm_presence.values())) > 1:
                    diffs.append(
                        DiffRow(
                            table_name,
                            destination,
                            path_type,
                            "BGP",
                            f"Community [{comm}]",
                            "MEDIUM",
                            comm_presence,
                        )
                    )

    # ── 4. OSPF attributes ───────────────────────────────────────────────────
    if any(r.protocol == "OSPF" for r in existing.values()):
        emit("OSPF", "Metric", "HIGH", {d: r.metric or "" for d, r in existing.items()})

    # ── 5. RSVP / inet.3 attributes ──────────────────────────────────────────
    if any(r.protocol == "RSVP" for r in existing.values()):
        emit(
            "RSVP",
            "Tunnel",
            "MEDIUM",
            {d: r.tunnel_name or "" for d, r in existing.items()},
        )
        emit(
            "RSVP",
            "Bandwidth (kbps)",
            "MEDIUM",
            {d: r.bandwidth_kbps or "" for d, r in existing.items()},
        )

    # ── 6. MPLS forwarding attributes ────────────────────────────────────────
    if any(r.nh_type for r in existing.values()):
        emit(
            "MPLS",
            "Operation",
            "CRITICAL",
            {d: r.nh_type or "" for d, r in existing.items()},
        )
        emit(
            "MPLS",
            "Outgoing-Label",
            "HIGH",
            {d: r.outgoing_label or "" for d, r in existing.items()},
        )
        emit(
            "MPLS",
            "VPN-Label",
            "HIGH",
            {d: r.vpn_label or "" for d, r in existing.items()},
        )

    # ── 7. Next-hop analysis ──────────────────────────────────────────────────

    # 7a. NH count — ECMP change
    emit(
        "Next-Hop",
        "NH Count (ECMP)",
        "CRITICAL",
        {d: str(len(r.next_hops)) for d, r in existing.items()},
    )

    # 7b. Per-hop detail — compare by index position
    max_hops = max((len(r.next_hops) for r in existing.values()), default=0)
    for i in range(max_hops):
        n = i + 1
        to_vals = {
            dev: (r.next_hops[i].to if i < len(r.next_hops) else "N/A")
            for dev, r in existing.items()
        }
        via_vals = {
            dev: (r.next_hops[i].via if i < len(r.next_hops) else "N/A")
            for dev, r in existing.items()
        }
        lbl_vals = {
            dev: (r.next_hops[i].mpls_label if i < len(r.next_hops) else "N/A")
            for dev, r in existing.items()
        }
        # Fill N/A for devices that have no route at all
        for dev in device_names:
            to_vals.setdefault(dev, "N/A")
            via_vals.setdefault(dev, "N/A")
            lbl_vals.setdefault(dev, "N/A")

        emit(
            "Next-Hop",
            f"NH{n} Gateway",
            "CRITICAL",
            {k: v or "" for k, v in to_vals.items()},
        )
        emit(
            "Next-Hop",
            f"NH{n} Interface",
            "LOW",
            {k: v or "" for k, v in via_vals.items()},
        )
        emit(
            "Next-Hop",
            f"NH{n} MPLS-Label",
            "LOW",
            {k: v or "" for k, v in lbl_vals.items()},
        )

    return diffs


def compare_tables(
    device_tables: dict,
    table_filter: Optional[str] = None,
    min_severity: Optional[str] = None,
    presence_only: bool = False,
) -> list:
    device_names = list(device_tables.keys())
    all_tables = set()
    for dt in device_tables.values():
        all_tables.update(dt.keys())
    if table_filter:
        all_tables = {t for t in all_tables if t == table_filter}

    diffs = []
    for table_name in sorted(all_tables):
        all_keys = set()
        for dev in device_names:
            all_keys.update(device_tables[dev].get(table_name, {}).keys())

        for route_key in sorted(all_keys):
            destination, path_type = route_key.rsplit("|", 1)
            routes = {
                dev: device_tables[dev].get(table_name, {}).get(route_key)
                for dev in device_names
            }
            diffs.extend(
                compare_routes(table_name, destination, path_type, routes, device_names)
            )

    # ── Filters ───────────────────────────────────────────────────────────────
    if presence_only:
        diffs = [d for d in diffs if d.category == "Presence"]
    if min_severity:
        threshold = SEVERITY_ORDER.get(min_severity.upper(), 3)
        diffs = [d for d in diffs if SEVERITY_ORDER.get(d.severity, 99) <= threshold]

    return diffs


# ─────────────────────────────────────────────────────────────────────────────
# Summary statistics
# ─────────────────────────────────────────────────────────────────────────────


def build_summary(device_tables: dict, table_filter: Optional[str]) -> list:
    all_tables = set()
    for dt in device_tables.values():
        all_tables.update(dt.keys())
    if table_filter:
        all_tables = {t for t in all_tables if t == table_filter}

    rows = []
    for table_name in sorted(all_tables):
        row = {"Table": table_name}
        for dev, dt in device_tables.items():
            tbl = dt.get(table_name, {})
            total = len(tbl)
            active = sum(1 for r in tbl.values() if r.active)
            row[dev] = f"{total} total / {active} active"
        rows.append(row)
    return rows


def build_diff_stats(diffs: list) -> str:
    if not diffs:
        return ""
    lines = []

    by_sev = Counter(d.severity for d in diffs)
    lines.append("\nDifferences by severity:")
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        count = by_sev.get(sev, 0)
        if count:
            bar = "█" * min(count, 50)
            lines.append(f"  {sev:<10} {count:>5}  {bar}")

    by_table = Counter(d.table for d in diffs)
    lines.append("\nDifferences by routing table:")
    for tbl, count in sorted(by_table.items()):
        lines.append(f"  {tbl:<12} {count:>5}")

    by_cat = Counter(d.category for d in diffs)
    lines.append("\nDifferences by category:")
    for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        lines.append(f"  {cat:<14} {count:>5}")

    lines.append(f"\nTotal differences: {len(diffs)}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────

SEVERITY_ICON = {"CRITICAL": "[!!]", "HIGH": "[! ]", "MEDIUM": "[. ]", "LOW": "[  ]"}


def _col_widths(headers, rows):
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    return widths


def _render_table(headers, rows, title=""):
    widths = _col_widths(headers, rows)
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    fmt = "| " + " | ".join(f"{{:<{w}}}" for w in widths) + " |"
    lines = []
    if title:
        total_w = sum(widths) + 3 * len(widths) + 1
        lines.append(f"\n{'=' * total_w}")
        lines.append(f"  {title}")
        lines.append(f"{'=' * total_w}")
    lines.append(sep)
    lines.append(fmt.format(*[str(h) for h in headers]))
    lines.append(sep)
    for row in rows:
        lines.append(fmt.format(*[str(c) for c in row]))
    lines.append(sep)
    return "\n".join(lines)


def render_summary(device_tables, table_filter) -> str:
    data = build_summary(device_tables, table_filter)
    devices = list(device_tables.keys())
    headers = ["Table"] + devices
    rows = [[r["Table"]] + [r.get(d, "---") for d in devices] for r in data]
    return _render_table(headers, rows, title="ROUTE COUNT SUMMARY")


def render_diffs_grouped(diffs: list, device_names: list) -> str:
    if not diffs:
        return "\n  No differences found.\n"

    output = []
    total_w = 84
    output.append(f"\n{'=' * total_w}")
    output.append(f"  ROUTING TABLE DIFFERENCES  ({len(diffs)} total)")
    output.append(
        f"  Legend: {' | '.join(f'{SEVERITY_ICON[s]} = {s}' for s in SEVERITY_ORDER)}"
    )
    output.append(f"{'=' * total_w}")

    sorted_diffs = sorted(
        diffs,
        key=lambda x: (
            x.table,
            x.destination,
            x.path_type,
            SEVERITY_ORDER.get(x.severity, 99),
            x.category,
            x.field,
        ),
    )

    for table, tg in groupby(sorted_diffs, key=lambda x: x.table):
        table_diffs = list(tg)
        output.append(f"\n  Table: {table}  ({len(table_diffs)} differences)")
        output.append(f"  {'─' * (total_w - 2)}")

        for (dest, pt), dg in groupby(
            table_diffs, key=lambda x: (x.destination, x.path_type)
        ):
            dest_diffs = list(dg)
            output.append(f"\n    Prefix : {dest}  [{pt}]")

            field_rows = []
            for d in dest_diffs:
                icon = SEVERITY_ICON.get(d.severity, "    ")
                row = [
                    f"{icon} {d.severity}",
                    d.category,
                    d.field,
                ] + [d.values.get(dev, "N/A") for dev in device_names]
                field_rows.append(row)

            headers = ["Severity", "Category", "Field"] + device_names
            widths = _col_widths(headers, field_rows)
            sep = "    +-" + "-+-".join("-" * w for w in widths) + "-+"
            fmt = "    | " + " | ".join(f"{{:<{w}}}" for w in widths) + " |"
            output.append(sep)
            output.append(fmt.format(*headers))
            output.append(sep)
            for row in field_rows:
                output.append(fmt.format(*[str(c) for c in row]))
            output.append(sep)

    return "\n".join(output)


def render_diffs_flat(diffs: list, device_names: list) -> str:
    if not diffs:
        return "\n  No differences found.\n"

    headers = [
        "Sev",
        "Table",
        "Destination",
        "Path",
        "Category",
        "Field",
    ] + device_names
    rows = []
    for d in sorted(
        diffs,
        key=lambda x: (SEVERITY_ORDER.get(x.severity, 99), x.table, x.destination),
    ):
        icon = SEVERITY_ICON.get(d.severity, "    ")
        rows.append(
            [
                f"{icon} {d.severity}",
                d.table,
                d.destination,
                d.path_type,
                d.category,
                d.field,
            ]
            + [d.values.get(dev, "N/A") for dev in device_names]
        )

    return _render_table(
        headers, rows, title=f"ROUTING TABLE DIFFERENCES  ({len(diffs)} total)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CSV export
# ─────────────────────────────────────────────────────────────────────────────


def export_csv(diffs: list, device_names: list, filepath: str) -> None:
    fieldnames = [
        "Severity",
        "Table",
        "Destination",
        "Path",
        "Category",
        "Field",
    ] + device_names
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in diffs:
            row = {
                "Severity": d.severity,
                "Table": d.table,
                "Destination": d.destination,
                "Path": d.path_type,
                "Category": d.category,
                "Field": d.field,
            }
            for dev in device_names:
                row[dev] = d.values.get(dev, "N/A")
            writer.writerow(row)
    print(f"CSV saved to: {filepath}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Compare Juniper routing table JSON files — deep attribute diff.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Severity levels (use with --severity to filter):
  CRITICAL  route added/removed, protocol changed, NH gateway lost, MPLS op changed
  HIGH      BGP LP/MED/origin-AS changed, OSPF metric, outgoing label changed
  MEDIUM    full AS-path, communities, learned-from, peer-type, RSVP bandwidth
  LOW       egress interface change, MPLS label string change

Examples:
  python compare_routing_tables.py rib-data/*.json
  python compare_routing_tables.py rib-data/*.json --table inet.0
  python compare_routing_tables.py rib-data/*.json --severity high
  python compare_routing_tables.py rib-data/*.json --presence-only
  python compare_routing_tables.py rib-data/*.json --flat --output report.txt
  python compare_routing_tables.py rib-data/*.json --csv diffs.csv
        """,
    )
    parser.add_argument(
        "files",
        nargs="+",
        metavar="FILE",
        help="JSON routing table files to compare (min 2)",
    )
    parser.add_argument(
        "--table",
        metavar="TABLE",
        default=None,
        help="Limit to a specific table: inet.0, inet.3, or mpls.0",
    )
    parser.add_argument(
        "--severity",
        metavar="LEVEL",
        default=None,
        help="Minimum severity: critical | high | medium | low",
    )
    parser.add_argument(
        "--presence-only", action="store_true", help="Only report routes added/removed"
    )
    parser.add_argument(
        "--flat",
        action="store_true",
        help="Flat single-table output instead of grouped",
    )
    parser.add_argument(
        "--output", metavar="FILE", default=None, help="Save text report to file"
    )
    parser.add_argument(
        "--csv", metavar="FILE", default=None, help="Save differences as CSV"
    )
    args = parser.parse_args()

    if len(args.files) < 2:
        parser.error("Provide at least 2 JSON files to compare.")

    # ── Load ──────────────────────────────────────────────────────────────────
    device_tables = {}
    print(f"\nLoading {len(args.files)} routing table file(s)...")
    for filepath in args.files:
        if not os.path.isfile(filepath):
            print(f"  ERROR: File not found: {filepath}", file=sys.stderr)
            sys.exit(1)
        device_name = os.path.splitext(os.path.basename(filepath))[0]
        try:
            device_tables[device_name] = load_device_tables(filepath)
            info = ", ".join(
                f"{t}:{len(r)}" for t, r in device_tables[device_name].items()
            )
            print(f"  OK  {device_name:<25} ({info})")
        except Exception as e:
            print(f"  ERROR loading {filepath}: {e}", file=sys.stderr)
            raise

    device_names = list(device_tables.keys())

    # ── Compare ───────────────────────────────────────────────────────────────
    label = f" [{args.table}]" if args.table else ""
    print(f"\nComparing routing tables{label}...")
    diffs = compare_tables(
        device_tables,
        table_filter=args.table,
        min_severity=args.severity,
        presence_only=args.presence_only,
    )

    # ── Build report ──────────────────────────────────────────────────────────
    report_parts = [
        f"\nJuniper Routing Table Comparison Report",
        f"Devices : {', '.join(device_names)}",
        f"Files   : {', '.join(args.files)}",
    ]
    if args.table:
        report_parts.append(f"Table   : {args.table}")
    if args.severity:
        report_parts.append(f"Filter  : severity >= {args.severity.upper()}")
    report_parts.append("")
    report_parts.append(render_summary(device_tables, args.table))

    if args.flat:
        report_parts.append(render_diffs_flat(diffs, device_names))
    else:
        report_parts.append(render_diffs_grouped(diffs, device_names))

    report_parts.append(build_diff_stats(diffs))
    report_text = "\n".join(report_parts)

    print(report_text)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report_text)
        print(f"\nText report saved to: {args.output}")

    if args.csv:
        export_csv(diffs, device_names, args.csv)


if __name__ == "__main__":
    main()
