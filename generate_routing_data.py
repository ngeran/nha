"""
generate_routing_data.py  —  v4
Generates synthetic Junos-style RIB data (XML + JSON) for lab/testing use.

Routing tables generated per device:
  inet.0   — standard IPv4 unicast (BGP, OSPF, Static, Direct)
  inet.3   — labeled-unicast / BGP-free core (LDP/RSVP resolved next-hops)
  mpls.0   — MPLS forwarding table (incoming label -> swap/pop/push actions)

Output layout:
  rib-data/
    <hostname>.xml   — all three tables in a single rpc-reply envelope
    <hostname>.json  — structured JSON mirroring the XML hierarchy

Changelog v4:
  - Interactive prompts: route count, overlap mode, device count
  - Overlapping prefix mode: a shared prefix pool is seeded once and
    distributed across all devices so the same destinations appear on
    multiple routers but with *independently randomised* BGP/OSPF/MPLS
    attributes (local-pref, MED, AS-path, communities, next-hop, …)
    — ideal for testing the compare_routing_tables.py diff tool.
  - Overlap ratio: 70 % of routes come from the shared pool by default;
    remaining 30 % are device-unique prefixes.
  - Single-file mode (no overlap): generates exactly one device file.
  - All v3 features preserved (inet.0 / inet.3 / mpls.0, Junos JSON schema).

CLI flags (all optional — script prompts interactively when omitted):
  -n / --routes    inet.0 routes per device
  -d / --devices   number of devices  (overlap mode only; ignored otherwise)
  -o / --overlap   force overlap mode on  (skip prompt)
  -O / --no-overlap force overlap mode off (skip prompt)
  -r / --ratio     shared-prefix ratio 0–100 % (default 70, overlap mode only)
  -s / --seed      RNG seed for reproducible output
"""

import xml.etree.ElementTree as ET
import json
import random
import os
import argparse
from copy import deepcopy


# ---------------------------------------------------------------------------
# Device name pool  (realistic ISP/DC router hostnames)
# ---------------------------------------------------------------------------

DEVICE_NAMES = [
    "pe1-ams-nl",
    "pe2-fra-de",
    "pe1-lon-uk",
    "pe2-par-fr",
    "pe1-nyc-us",
    "pe2-lax-us",
    "p1-core-ams",
    "p2-core-fra",
    "rr1-ctrl-ams",
    "rr2-ctrl-fra",
    "asbr1-ams-nl",
    "asbr2-fra-de",
]


# ---------------------------------------------------------------------------
# Topology constants
# ---------------------------------------------------------------------------

RR_PEERS = [
    "10.100.177.26",
    "10.100.177.27",
    "10.100.177.29",
    "10.100.177.30",
]

INTERFACES = ["ge-1/0/0.0", "ge-1/1/0.0", "xe-0/0/0.0", "xe-0/0/1.0"]

# Tier-1 / Tier-2 transit ASNs
TRANSIT_ASES = [1299, 3356, 174, 6461, 3257, 2914, 5511, 1273]

# Customer / peer origin ASNs
ORIGIN_ASES = [65001, 65010, 65020, 65030, 65100, 65200, 64500, 64510]

# Standard BGP communities
STANDARD_COMMUNITIES = [
    "64512:100",
    "64512:200",
    "64512:300",
    "64512:666",  # blackhole
    "65000:777",
    "no-export",
    "no-advertise",
]

# Large communities (RFC 8092)
LARGE_COMMUNITIES = [
    "64512:100:200",
    "64512:0:65535",
    "65000:1:1",
]

# Peer-type policy -- drives correlated LocalPref + MED
PEER_POLICY = {
    "customer": {
        "local_pref_range": (180, 220),
        "med": 0,
    },
    "peer": {
        "local_pref_range": (90, 110),
        "med_range": (0, 100),
    },
    "upstream": {
        "local_pref_range": (40, 60),
        "med_range": (0, 500),
    },
}

# Prefix length distribution
PREFIX_LENGTHS = [16, 20, 22, 24]
PREFIX_WEIGHTS = [5, 15, 20, 60]

# MPLS label range (user-space: 16 - 1048575)
MPLS_LABEL_MIN = 16
MPLS_LABEL_MAX = 1_048_575


# ---------------------------------------------------------------------------
# Prefix helpers
# ---------------------------------------------------------------------------


def _random_prefix(used: set) -> str:
    """Unique public IPv4 prefix, host-bits zeroed to match prefix length."""
    prefix_len = random.choices(PREFIX_LENGTHS, weights=PREFIX_WEIGHTS)[0]
    for _ in range(2000):
        a = random.randint(1, 223)
        b = random.randint(0, 255)
        c = random.randint(0, 255)
        if prefix_len == 24:
            prefix = f"{a}.{b}.{c}.0/24"
        elif prefix_len == 22:
            c = (c >> 2) << 2
            prefix = f"{a}.{b}.{c}.0/22"
        elif prefix_len == 20:
            b = (b >> 4) << 4
            prefix = f"{a}.{b}.0.0/20"
        else:  # /16
            prefix = f"{a}.{b}.0.0/16"
        if prefix not in used:
            used.add(prefix)
            return prefix
    raise RuntimeError("Prefix space exhausted after 2000 attempts")


def _random_mpls_label() -> int:
    """Random user-space MPLS label (avoids reserved 0-15)."""
    return random.randint(MPLS_LABEL_MIN, MPLS_LABEL_MAX)


# ---------------------------------------------------------------------------
# BGP / path helpers
# ---------------------------------------------------------------------------


def _build_as_path() -> str:
    origin_as = random.choice(ORIGIN_ASES)
    n_transit = random.randint(0, 4)
    transit = random.sample(TRANSIT_ASES, min(n_transit, len(TRANSIT_ASES)))
    return " ".join(str(a) for a in transit + [origin_as]) + " I"


def _build_communities() -> list:
    comms = random.sample(STANDARD_COMMUNITIES, random.randint(1, 3))
    if random.random() < 0.20:
        comms.append(random.choice(LARGE_COMMUNITIES))
    return comms


def _next_hop_from_peer(peer_ip: str) -> str:
    prefix = peer_ip.rsplit(".", 1)[0]
    return f"{prefix}.{random.randint(1, 254)}"


# ---------------------------------------------------------------------------
# inet.0 route builders
# ---------------------------------------------------------------------------


def _make_bgp_route(destination: str) -> dict:
    peer_type = random.choice(list(PEER_POLICY.keys()))
    policy = PEER_POLICY[peer_type]
    learned_from = random.choice(RR_PEERS)
    local_pref = random.randint(*policy["local_pref_range"])
    med = (
        policy["med"]
        if peer_type == "customer"
        else random.randint(*policy["med_range"])
    )
    return {
        "destination": destination,
        "protocol": "BGP",
        "preference": "170",
        "active": True,
        "peer_type": peer_type,
        "local_pref": local_pref,
        "med": med,
        "learned_from": learned_from,
        "as_path": _build_as_path(),
        "communities": _build_communities(),
        "next_hops": [
            {
                "to": _next_hop_from_peer(learned_from),
                "via": random.choice(INTERFACES),
                "mpls_label": f"Push {_random_mpls_label()}",
            }
        ],
    }


def _make_ospf_route(index: int) -> dict:
    return {
        "destination": f"10.255.{random.randint(0, 255)}.{index % 256}/32",
        "protocol": "OSPF",
        "preference": "10",
        "active": True,
        "metric": random.randint(1, 65535),
        "next_hops": [{"via": "lo0.0"}],
    }


def _make_static_route(destination: str) -> dict:
    proto = random.choice(["Static", "Direct", "LDP", "RSVP"])
    pref_map = {"Static": "5", "Direct": "0", "LDP": "9", "RSVP": "7"}
    return {
        "destination": destination,
        "protocol": proto,
        "preference": pref_map[proto],
        "active": True,
        "next_hops": [
            {
                "to": f"10.247.0.{random.randint(1, 5)}",
                "via": random.choice(INTERFACES),
            }
        ],
    }


def _make_inactive_backup(primary: dict) -> dict:
    backup = deepcopy(primary)
    backup["active"] = False
    backup["local_pref"] = max(0, primary["local_pref"] - random.randint(10, 50))
    alt_peers = [p for p in RR_PEERS if p != primary["learned_from"]]
    backup["learned_from"] = random.choice(alt_peers or RR_PEERS)
    backup["as_path"] = _build_as_path()
    backup["next_hops"] = [
        {
            "to": _next_hop_from_peer(backup["learned_from"]),
            "via": random.choice(INTERFACES),
            "mpls_label": f"Push {_random_mpls_label()}",
        }
    ]
    return backup


def _build_inet0_table(count: int, used_prefixes: set,
                       shared_prefixes: list | None = None) -> list:
    """
    Build the inet.0 route table.

    shared_prefixes (overlap mode)
        When supplied, routes for every prefix in this list are generated
        first using *freshly randomised* attributes so each device sees the
        same destination but with independent BGP/OSPF attributes.
        The remaining slots (count - len(shared_prefixes)) are filled with
        device-unique prefixes as normal.
    """
    routes = []
    ospf_index = 1  # keep a stable counter for OSPF host-route suffixes

    # ── Shared / overlapping prefixes ────────────────────────────────────────
    if shared_prefixes:
        for dest in shared_prefixes:
            used_prefixes.add(dest)   # prevent collision with unique pool
            rv = random.random()
            if rv < 0.75:             # bias heavily towards BGP for richer diffs
                route = _make_bgp_route(dest)
                if random.random() < 0.15:
                    routes.append(_make_inactive_backup(route))
            else:
                route = _make_static_route(dest)
            routes.append(route)

    # ── Device-unique prefixes ────────────────────────────────────────────────
    unique_slots = max(0, count - len(shared_prefixes or []))
    for i in range(1, unique_slots + 1):
        rv = random.random()
        if rv < 0.60:
            dest  = _random_prefix(used_prefixes)
            route = _make_bgp_route(dest)
            if random.random() < 0.15:
                routes.append(_make_inactive_backup(route))
        elif rv < 0.80:
            route = _make_ospf_route(ospf_index)
            ospf_index += 1
        else:
            dest  = _random_prefix(used_prefixes)
            route = _make_static_route(dest)
        routes.append(route)

    return routes


# ---------------------------------------------------------------------------
# inet.3 route builders  (labeled-unicast / BGP-free core)
# ---------------------------------------------------------------------------
# inet.3 holds LSP next-hops used by BGP to resolve PE loopback reachability.
# Entries are typically /32 host routes resolved via LDP or RSVP-TE tunnels.


def _make_inet3_ldp_route(index: int) -> dict:
    dest = f"10.{random.randint(0, 31)}.{random.randint(0, 255)}.{index % 256}/32"
    return {
        "destination": dest,
        "protocol": "LDP",
        "preference": "9",
        "active": True,
        "next_hops": [
            {
                "to": f"10.247.0.{random.randint(1, 60)}",
                "via": random.choice(INTERFACES),
                "mpls_label": f"Push {_random_mpls_label()}",
            }
        ],
    }


def _make_inet3_rsvp_route(index: int) -> dict:
    dest = f"10.{random.randint(0, 31)}.{random.randint(0, 255)}.{index % 256}/32"
    # 20% chance of explicit-null (label 0) on egress PE
    use_explicit_null = random.random() < 0.20
    label_str = (
        "Push 0 (Explicit Null)"
        if use_explicit_null
        else f"Push {_random_mpls_label()}"
    )
    return {
        "destination": dest,
        "protocol": "RSVP",
        "preference": "7",
        "active": True,
        "tunnel_name": f"to-{dest.split('/')[0]}",
        "bandwidth_kbps": random.choice([0, 100_000, 500_000, 1_000_000, 10_000_000]),
        "next_hops": [
            {
                "to": f"10.247.0.{random.randint(1, 60)}",
                "via": random.choice(INTERFACES),
                "mpls_label": label_str,
            }
        ],
    }


def _build_inet3_table(count: int) -> list:
    routes = []
    for i in range(1, count + 1):
        if random.random() < 0.55:
            routes.append(_make_inet3_ldp_route(i))
        else:
            routes.append(_make_inet3_rsvp_route(i))
    return routes


# ---------------------------------------------------------------------------
# mpls.0 table builder
# ---------------------------------------------------------------------------
# Each entry: incoming label -> LFIB action
#   Pop  : penultimate-hop pop (PHP), used at egress PE
#   Swap : transit LSR label swap
#   Push : impose extra label stack (VPN-over-TE)

MPLS_OPERATIONS = ["Pop", "Swap", "Push"]
MPLS_OP_WEIGHTS = [20, 55, 25]


def _make_mpls_entry(incoming_label: int) -> dict:
    operation = random.choices(MPLS_OPERATIONS, weights=MPLS_OP_WEIGHTS)[0]
    entry: dict = {
        "destination": str(incoming_label),
        "protocol": random.choice(["LDP", "RSVP"]),
        "preference": "0",
        "active": True,
        "incoming_label": incoming_label,
        "operation": operation,
        "next_hops": [],
    }

    if operation == "Pop":
        entry["next_hops"].append(
            {
                "via": random.choice(INTERFACES),
                "mpls_label": "Pop",
            }
        )

    elif operation == "Swap":
        outgoing = _random_mpls_label()
        entry["outgoing_label"] = outgoing
        entry["next_hops"].append(
            {
                "to": f"10.247.0.{random.randint(1, 60)}",
                "via": random.choice(INTERFACES),
                "mpls_label": f"Swap {outgoing}",
            }
        )

    else:  # Push — VPN label over TE tunnel (two-label stack)
        outer = _random_mpls_label()
        inner = _random_mpls_label()
        entry["outgoing_label"] = outer
        entry["vpn_label"] = inner
        entry["next_hops"].append(
            {
                "to": f"10.247.0.{random.randint(1, 60)}",
                "via": random.choice(INTERFACES),
                "mpls_label": f"Push {inner}, Push {outer}",
            }
        )

    return entry


def _build_mpls_table(count: int, used_labels: set) -> list:
    entries = []
    for _ in range(count):
        for _ in range(500):
            lbl = _random_mpls_label()
            if lbl not in used_labels:
                used_labels.add(lbl)
                entries.append(_make_mpls_entry(lbl))
                break
    return entries


# ---------------------------------------------------------------------------
# Per-device orchestration
# ---------------------------------------------------------------------------


def generate_device_data(
    device_name: str,
    routes_per_table: int,
    target_dir: str,
    shared_prefixes: list | None = None,
) -> None:
    used_prefixes: set = set()
    used_labels: set = set()

    inet0 = _build_inet0_table(routes_per_table, used_prefixes, shared_prefixes)
    inet3 = _build_inet3_table(max(10, routes_per_table // 5))
    mpls0 = _build_mpls_table(max(10, routes_per_table // 4), used_labels)

    tables = {
        "inet.0": inet0,
        "inet.3": inet3,
        "mpls.0": mpls0,
    }

    xml_path  = os.path.join(target_dir, f"{device_name}.xml")
    json_path = os.path.join(target_dir, f"{device_name}.json")

    _save_xml(device_name, tables, xml_path)
    _save_json(device_name, tables, json_path)

    total  = sum(len(v) for v in tables.values())
    active = sum(1 for v in tables.values() for r in v if r.get("active"))
    shared = len(shared_prefixes) if shared_prefixes else 0

    print(
        f"  {device_name:<20}  "
        f"inet.0={len(inet0):>4}  inet.3={len(inet3):>4}  "
        f"mpls.0={len(mpls0):>4}  total={total:>4}  "
        f"({active} active"
        + (f", {shared} shared prefixes" if shared else "")
        + ")"
    )


# ---------------------------------------------------------------------------
# XML serialiser  — all three tables in one rpc-reply per device
# ---------------------------------------------------------------------------

JUNOS_NS = "http://xml.juniper.net/junos/25.2R1-S1.4/junos"
ROUTING_NS = "http://xml.juniper.net/junos/25.2R0/junos-routing"


def _add_route_entry(table_elem: ET.Element, r: dict) -> None:
    rt = ET.SubElement(table_elem, "rt", {f"{{{JUNOS_NS}}}style": "brief"})
    ET.SubElement(rt, "rt-destination").text = r["destination"]

    entry = ET.SubElement(rt, "rt-entry")
    ET.SubElement(entry, "active-tag").text = "*" if r.get("active") else " "
    ET.SubElement(entry, "protocol-name").text = r["protocol"]
    ET.SubElement(entry, "preference").text = r["preference"]

    proto = r["protocol"]

    if proto == "BGP":
        ET.SubElement(entry, "local-preference").text = str(r["local_pref"])
        ET.SubElement(entry, "med").text = str(r["med"])
        ET.SubElement(entry, "as-path").text = r["as_path"]
        ET.SubElement(entry, "learned-from").text = r["learned_from"]
        ET.SubElement(entry, "peer-type").text = r.get("peer_type", "")
        if r.get("communities"):
            comm_elem = ET.SubElement(entry, "communities")
            for c in r["communities"]:
                ET.SubElement(comm_elem, "community").text = c

    if proto == "OSPF" and "metric" in r:
        ET.SubElement(entry, "metric").text = str(r["metric"])

    if proto == "RSVP" and "tunnel_name" in r:
        ET.SubElement(entry, "tunnel-name").text = r["tunnel_name"]
        ET.SubElement(entry, "bandwidth-kbps").text = str(r["bandwidth_kbps"])

    if r.get("operation"):  # mpls.0 specific fields
        ET.SubElement(entry, "nh-type").text = r["operation"]
        if "outgoing_label" in r:
            ET.SubElement(entry, "outgoing-label").text = str(r["outgoing_label"])
        if "vpn_label" in r:
            ET.SubElement(entry, "vpn-label").text = str(r["vpn_label"])

    for n in r.get("next_hops", []):
        nh = ET.SubElement(entry, "nh")
        if "to" in n:
            ET.SubElement(nh, "to").text = n["to"]
        if "via" in n:
            ET.SubElement(nh, "via").text = n["via"]
        if "mpls_label" in n:
            ET.SubElement(nh, "mpls-label").text = n["mpls_label"]


def _save_xml(device_name: str, tables: dict, path: str) -> None:
    ET.register_namespace("junos", JUNOS_NS)
    ET.register_namespace("", ROUTING_NS)

    root = ET.Element(
        "rpc-reply",
        {
            f"{{{JUNOS_NS}}}junos": "25.2R1-S1.4",
            "device-name": device_name,
        },
    )
    route_info = ET.SubElement(root, "route-information", {"xmlns": ROUTING_NS})

    for table_name, routes in tables.items():
        tbl = ET.SubElement(route_info, "route-table")
        ET.SubElement(tbl, "table-name").text = table_name
        ET.SubElement(tbl, "destination-count").text = str(len(routes))
        ET.SubElement(tbl, "total-route-count").text = str(len(routes))
        for r in routes:
            _add_route_entry(tbl, r)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# JSON serialiser  — native Junos schema (matches `show route | display json`)
# ---------------------------------------------------------------------------
#
# Junos JSON encoding rules (verified against real SRX/MX output):
#   - Every field value is wrapped:  "field": [{"data": "<value>"}]
#   - Null-flag fields use:          "field": [{"data": [null]}]
#   - Attributes live in a sibling:  "attributes": {"junos:key": "val"}
#   - "age" carries both human text and a seconds attribute
#   - Top-level key is "route-information", not a custom wrapper
#
# ---------------------------------------------------------------------------


def _d(value) -> list:
    """Wrap a scalar in Junos data envelope: [{"data": value}]"""
    return [{"data": value}]


def _d_null() -> list:
    """Junos null-flag envelope: [{"data": [null]}]"""
    return [{"data": [None]}]


def _random_age() -> tuple[str, int]:
    """Return (human-readable age string, seconds) for a route age field."""
    seconds = random.randint(60, 7_776_000)  # 1 min to 90 days
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h >= 24:
        days = h // 24
        hrs = h % 24
        age_str = f"{days}d {hrs:02d}:{m:02d}:{s:02d}"
    else:
        age_str = f"{h:02d}:{m:02d}:{s:02d}"
    return age_str, seconds


def _rt_entry_to_junos(r: dict) -> dict:
    """Convert an internal route dict to a Junos-schema rt-entry object."""
    age_str, age_sec = _random_age()

    entry: dict = {
        "active-tag": _d("*" if r.get("active") else " "),
        "current-active": _d_null() if r.get("active") else [],
        "last-active": _d_null() if r.get("active") else [],
        "protocol-name": _d(r["protocol"]),
        "preference": _d(r["preference"]),
        "age": [
            {
                "data": age_str,
                "attributes": {"junos:seconds": str(age_sec)},
            }
        ],
    }

    # Remove empty lists (inactive routes have no current/last-active)
    if not entry["current-active"]:
        del entry["current-active"]
    if not entry["last-active"]:
        del entry["last-active"]

    proto = r["protocol"]

    if proto == "BGP":
        entry["local-preference"] = _d(str(r["local_pref"]))
        entry["med"] = _d(str(r["med"]))
        entry["as-path"] = _d(r["as_path"])
        entry["learned-from"] = _d(r["learned_from"])
        entry["peer-type"] = _d(r.get("peer_type", ""))
        if r.get("communities"):
            entry["communities"] = [{"community": _d(c)} for c in r["communities"]]

    if proto == "OSPF" and "metric" in r:
        entry["metric"] = _d(str(r["metric"]))

    if proto == "RSVP" and "tunnel_name" in r:
        entry["tunnel-name"] = _d(r["tunnel_name"])
        entry["bandwidth-kbps"] = _d(str(r["bandwidth_kbps"]))

    # mpls.0-specific fields
    if r.get("operation"):
        entry["nh-type"] = _d(r["operation"])
        if "outgoing_label" in r:
            entry["outgoing-label"] = _d(str(r["outgoing_label"]))
        if "vpn_label" in r:
            entry["vpn-label"] = _d(str(r["vpn_label"]))

    # Next-hops
    nh_list = []
    for n in r.get("next_hops", []):
        nh: dict = {}
        # selected-next-hop flag on active routes
        if r.get("active"):
            nh["selected-next-hop"] = _d_null()
        if "to" in n:
            nh["to"] = _d(n["to"])
        if "via" in n:
            nh["via"] = _d(n["via"])
        if "mpls_label" in n:
            nh["mpls-label"] = _d(n["mpls_label"])
        # Local routes use nh-local-interface instead of via
        if proto == "Local":
            nh.pop("via", None)
            nh["nh-local-interface"] = _d(n.get("via", "lo0.0"))
        nh_list.append(nh)

    if nh_list:
        entry["nh"] = nh_list

    return entry


def _routes_to_junos_table(table_name: str, routes: list) -> dict:
    """Build a Junos route-table JSON object from internal route list."""
    active_count = sum(1 for r in routes if r.get("active"))

    rt_list = []
    for r in routes:
        rt_obj = {
            "attributes": {"junos:style": "brief"},
            "rt-destination": _d(r["destination"]),
            "rt-entry": [_rt_entry_to_junos(r)],
        }
        rt_list.append(rt_obj)

    return {
        "comment": "keepalive",
        "table-name": _d(table_name),
        "destination-count": _d(str(len(routes))),
        "total-route-count": _d(str(len(routes))),
        "active-route-count": _d(str(active_count)),
        "holddown-route-count": _d("0"),
        "hidden-route-count": _d("0"),
        "rt": rt_list,
    }


def _save_json(device_name: str, tables: dict, path: str) -> None:
    """
    Serialise to native Junos JSON format, matching `show route | display json`.

    Top-level structure:
    {
      "route-information": [{
        "attributes": {"xmlns": "<routing-ns>"},
        "route-table": [ <one object per table> ]
      }]
    }
    """
    route_tables = [
        _routes_to_junos_table(name, routes) for name, routes in tables.items()
    ]

    doc = {
        "route-information": [
            {
                "attributes": {"xmlns": ROUTING_NS},
                "route-table": route_tables,
            }
        ]
    }

    with open(path, "w") as f:
        json.dump(doc, f, indent=4)


# ---------------------------------------------------------------------------
# Shared-prefix pool builder
# ---------------------------------------------------------------------------


def _build_shared_prefix_pool(count: int) -> list:
    """
    Generate `count` unique public IPv4 prefixes that will be seeded into
    every device's inet.0 table (with independently randomised attributes).
    """
    pool: set = set()
    prefixes: list = []
    while len(prefixes) < count:
        p = _random_prefix(pool)
        prefixes.append(p)
    return prefixes


# ---------------------------------------------------------------------------
# Interactive prompt helpers
# ---------------------------------------------------------------------------


def _prompt_int(prompt: str, default: int, min_val: int = 1,
                max_val: int = 10_000) -> int:
    while True:
        raw = input(f"{prompt} [default: {default}]: ").strip()
        if raw == "":
            return default
        try:
            val = int(raw)
            if min_val <= val <= max_val:
                return val
            print(f"  Please enter a value between {min_val} and {max_val}.")
        except ValueError:
            print("  Invalid input — please enter a whole number.")


def _prompt_yes_no(prompt: str) -> bool:
    while True:
        raw = input(f"{prompt} [y/n]: ").strip().lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please answer y or n.")


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def generate_routing_data(
    total_routes:  int | None = None,
    seed:          int | None = None,
    num_devices:   int | None = None,
    overlap:       bool | None = None,  # None = ask interactively
    overlap_ratio: float = 0.70,        # fraction of routes from shared pool
) -> None:
    target_dir = "rib-data"
    if not os.path.exists(target_dir):
        print(f"Creating output directory: '{target_dir}'")
        os.makedirs(target_dir)

    if seed is not None:
        random.seed(seed)
        print(f"RNG seed: {seed}")

    print()

    # ── How many routes? ─────────────────────────────────────────────────────
    if total_routes is None:
        total_routes = _prompt_int(
            "How many inet.0 routes per device?", default=150,
            min_val=10, max_val=10_000,
        )

    # ── Overlapping prefixes? ─────────────────────────────────────────────────
    if overlap is None:
        overlap = _prompt_yes_no(
            "Generate overlapping prefixes across multiple devices?"
        )

    # ── How many devices (overlap mode only)? ────────────────────────────────
    if overlap:
        if num_devices is None:
            num_devices = _prompt_int(
                "How many device files to generate?", default=3,
                min_val=2, max_val=len(DEVICE_NAMES),
            )
        shared_count = max(1, int(total_routes * overlap_ratio))
        unique_count = total_routes - shared_count
        print(
            f"\n  Overlap mode ON  |  ratio={int(overlap_ratio*100)}%  |  "
            f"shared={shared_count}  unique/device={unique_count}"
        )
    else:
        num_devices   = 1
        shared_count  = 0

    devices = random.sample(DEVICE_NAMES, min(num_devices, len(DEVICE_NAMES)))

    # ── Build shared prefix pool once, reused by all devices ─────────────────
    shared_prefixes: list | None = None
    if overlap and shared_count > 0:
        print(f"  Building shared prefix pool ({shared_count} prefixes)…")
        shared_prefixes = _build_shared_prefix_pool(shared_count)

    # ── Generate per-device data ──────────────────────────────────────────────
    print(
        f"\nGenerating data for {len(devices)} device(s), "
        f"~{total_routes} inet.0 routes each:\n"
    )
    print(
        f"  {'Device':<20}  {'inet.0':>8}  {'inet.3':>8}  {'mpls.0':>8}  {'total':>7}"
    )
    print("  " + "-" * 72)

    for device in devices:
        generate_device_data(
            device_name      = device,
            routes_per_table = total_routes,
            target_dir       = target_dir,
            shared_prefixes  = shared_prefixes,
        )

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\nAll files saved to '{target_dir}/'")

    if overlap and shared_prefixes:
        print(
            f"\nOverlap summary:\n"
            f"  {shared_count} prefixes are present on ALL {len(devices)} devices\n"
            f"  Each device has independently randomised attributes for those prefixes\n"
            f"  Use compare_routing_tables.py to diff the generated files:"
        )
        filenames = " ".join(f"{target_dir}/{d}.json" for d in devices)
        print(f"\n    python compare_routing_tables.py {filenames}\n")
    else:
        print(
            f"\n  Single-device file: {target_dir}/{devices[0]}.json\n"
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate synthetic Junos RIB data — inet.0, inet.3, mpls.0.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fully interactive (recommended for first use)
  python generate_routing_data.py

  # 200 routes, overlapping, 4 devices
  python generate_routing_data.py -n 200 -o -d 4

  # 100 routes, no overlap (single file)
  python generate_routing_data.py -n 100 -O

  # 150 routes, overlap, 3 devices, 80 % shared, reproducible
  python generate_routing_data.py -n 150 -o -d 3 -r 80 -s 42
        """,
    )
    parser.add_argument(
        "-n", "--routes",
        type=int, default=None,
        help="Number of inet.0 routes per device (prompts if omitted)",
    )
    parser.add_argument(
        "-d", "--devices",
        type=int, default=None,
        help="Number of device files to generate (overlap mode only; prompts if omitted)",
    )
    parser.add_argument(
        "-o", "--overlap",
        action="store_true", default=False,
        help="Enable overlapping-prefix mode (skip prompt)",
    )
    parser.add_argument(
        "-O", "--no-overlap",
        action="store_true", default=False,
        help="Disable overlapping-prefix mode, generate one file (skip prompt)",
    )
    parser.add_argument(
        "-r", "--ratio",
        type=int, default=70, metavar="PCT",
        help="Percentage of routes to share across devices in overlap mode (default: 70)",
    )
    parser.add_argument(
        "-s", "--seed",
        type=int, default=None,
        help="Random seed for reproducible output",
    )

    args = parser.parse_args()

    # Resolve overlap flag
    if args.overlap and args.no_overlap:
        parser.error("--overlap and --no-overlap are mutually exclusive.")
    overlap_flag: bool | None = None
    if args.overlap:
        overlap_flag = True
    elif args.no_overlap:
        overlap_flag = False

    if not (0 < args.ratio <= 100):
        parser.error("--ratio must be between 1 and 100.")

    generate_routing_data(
        total_routes  = args.routes,
        seed          = args.seed,
        num_devices   = args.devices,
        overlap       = overlap_flag,
        overlap_ratio = args.ratio / 100.0,
    )
