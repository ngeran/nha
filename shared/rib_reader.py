"""
RIB Reader - Reads and parses routing table files.
Supports JSON, XML, and YAML formats.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

try:
    from lxml import etree

    LXML_AVAILABLE = True
except ImportError:
    LXML_AVAILABLE = False


@dataclass
class RouteInfo:
    """Represents a single route entry."""

    prefix: str
    table: str
    protocol: str
    next_hop: str
    age: int
    preference: int
    metric: int
    active: bool
    as_path: str = ""
    local_pref: str = ""
    med: str = ""
    origin_as: str = ""
    learned_from: str = ""
    peer_type: str = ""
    communities: List[str] = None

    def __post_init__(self):
        if self.communities is None:
            self.communities = []

    def to_table_row(self) -> List[str]:
        """Convert to table row format."""
        return [
            "*" if self.active else "",
            self.prefix,
            self.table,
            self.protocol,
            self.next_hop,
            str(self.preference),
            self.as_path,
        ]


class RIBReader:
    """
    Reads and parses routing table files.
    """

    def __init__(self):
        self.routes: List[RouteInfo] = []
        self.metadata: Dict[str, Any] = {}

    def read_file(self, file_path: Path) -> bool:
        """
        Read a routing table file.

        Args:
            file_path: Path to the routing table file

        Returns:
            True if successful, False otherwise
        """
        file_path = Path(file_path)

        if not file_path.exists():
            return False

        suffix = file_path.suffix.lower()

        if suffix == ".json":
            return self._read_json(file_path)
        elif suffix in (".yaml", ".yml"):
            return self._read_yaml(file_path)
        elif suffix == ".xml":
            return self._read_xml(file_path)

        return False

    def _read_json(self, file_path: Path) -> bool:
        """Read JSON routing table file."""
        try:
            with open(file_path, "r") as f:
                data = json.load(f)

            # Check if it's Junos JSON format (has route-information key)
            if "route-information" in data:
                return self._read_junos_json(file_path, data)

            # Check if it's a list format (like routes.json)
            if isinstance(data, list):
                self.metadata = {
                    "device": "unknown",
                    "hostname": "unknown",
                    "timestamp": "",
                    "total_routes": len(data),
                    "format": "JSON",
                }

                self.routes = []
                for route_data in data:
                    # Handle both "prefix" and "destination" field names
                    prefix = route_data.get("prefix", route_data.get("destination", ""))
                    if not prefix:
                        continue

                    # Handle next_hop extraction from next_hops array
                    next_hop = route_data.get("next_hop", "")
                    if (
                        not next_hop
                        and "next_hops" in route_data
                        and route_data["next_hops"]
                    ):
                        next_hop_obj = route_data["next_hops"][0]
                        next_hop = next_hop_obj.get("to", next_hop_obj.get("via", ""))

                    route = RouteInfo(
                        prefix=prefix,
                        table=route_data.get("table", "inet.0"),
                        protocol=route_data.get("protocol", "Unknown"),
                        next_hop=next_hop,
                        age=route_data.get("age", 0),
                        preference=int(route_data.get("preference", 0)),
                        metric=int(route_data.get("med", route_data.get("metric", 0))),
                        active=route_data.get("active", False),
                        as_path=route_data.get("as_path", ""),
                        local_pref=str(route_data.get("local_pref", "")),
                        med=str(route_data.get("med", "")),
                        learned_from=route_data.get("learned_from", ""),
                        peer_type=route_data.get("peer_type", ""),
                        communities=route_data.get("communities", []),
                    )
                    self.routes.append(route)
                return True

            # Our custom format (dict with routes key)
            self.metadata = {
                "device": data.get("device", "unknown"),
                "hostname": data.get("hostname", "unknown"),
                "timestamp": data.get("timestamp", ""),
                "total_routes": data.get("total_routes", 0),
                "format": "JSON",
            }

            self.routes = []
            for route_data in data.get("routes", []):
                route = RouteInfo(
                    prefix=route_data.get("prefix", ""),
                    table=route_data.get("table", "inet.0"),
                    protocol=route_data.get("protocol", "Unknown"),
                    next_hop=route_data.get("next_hop", ""),
                    age=route_data.get("age", 0),
                    preference=route_data.get("preference", 0),
                    metric=route_data.get("metric", 0),
                    active=route_data.get("active", False),
                    as_path=route_data.get("as_path", ""),
                )
                self.routes.append(route)

            return True
        except Exception as e:
            print(f"Error reading JSON: {e}")
            return False

    def _get_junos_json_value(self, item) -> str:
        """Extract value from Junos JSON format item."""
        if item is None:
            return ""
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            return item.get("data", "")
        if isinstance(item, list) and len(item) > 0:
            return self._get_junos_json_value(item[0])
        return str(item) if item else ""

    def _parse_origin_as(self, as_path: str) -> str:
        """Extract origin AS from AS path string."""
        if not as_path:
            return ""
        tokens = as_path.split()
        as_tokens = [t for t in tokens if t not in ("I", "E", "?", "Aggregated")]
        if as_tokens:
            return as_tokens[-1]
        return ""

    def _read_junos_json(self, file_path: Path, data: dict) -> bool:
        """Read Junos JSON format routing table."""
        try:
            self.metadata = {
                "device": file_path.stem,
                "hostname": file_path.stem,
                "timestamp": "",
                "total_routes": 0,
                "format": "Junos JSON",
            }

            self.routes = []

            route_info_list = data.get("route-information", [])
            for route_info in route_info_list:
                route_tables = route_info.get("route-table", [])
                for route_table in route_tables:
                    table_name = self._get_junos_json_value(
                        route_table.get("table-name", ["inet.0"])
                    )

                    for rt in route_table.get("rt", []):
                        rt_destination = rt.get("rt-destination", [])
                        prefix = self._get_junos_json_value(rt_destination)

                        for rt_entry in rt.get("rt-entry", []):
                            route = RouteInfo(
                                prefix=prefix,
                                table=table_name,
                                protocol="Unknown",
                                next_hop="",
                                age=0,
                                preference=0,
                                metric=0,
                                active=False,
                            )

                            # Protocol
                            proto = rt_entry.get("protocol-name", [])
                            route.protocol = (
                                self._get_junos_json_value(proto) or "Unknown"
                            )

                            # Active
                            active_tag = rt_entry.get("active-tag", [])
                            route.active = self._get_junos_json_value(active_tag) == "*"

                            # Preference
                            pref = rt_entry.get("preference", [])
                            try:
                                route.preference = int(
                                    self._get_junos_json_value(pref) or 0
                                )
                            except ValueError:
                                pass

                            # Metric
                            metric = rt_entry.get("metric", [])
                            try:
                                route.metric = int(
                                    self._get_junos_json_value(metric) or 0
                                )
                            except ValueError:
                                pass

                            # Age - check for junos:seconds attribute
                            age = rt_entry.get("age", [])
                            if isinstance(age, list) and len(age) > 0:
                                age_item = age[0]
                                if isinstance(age_item, dict):
                                    attrs = age_item.get("attributes", {})
                                    age_seconds = attrs.get("junos:seconds")
                                    if age_seconds:
                                        try:
                                            route.age = int(age_seconds)
                                        except ValueError:
                                            pass

                            # Next hop
                            nh_list = rt_entry.get("nh", [])
                            if isinstance(nh_list, list) and len(nh_list) > 0:
                                nh = nh_list[0]
                                via = nh.get("via", [])
                                to = nh.get("to", [])
                                if via:
                                    route.next_hop = self._get_junos_json_value(via)
                                elif to:
                                    route.next_hop = self._get_junos_json_value(to)

                            # AS Path (for BGP routes)
                            as_path = rt_entry.get("as-path", [])
                            route.as_path = self._get_junos_json_value(as_path)

                            # BGP attributes
                            local_pref = rt_entry.get("local-preference", [])
                            route.local_pref = self._get_junos_json_value(local_pref)

                            med = rt_entry.get("med", [])
                            route.med = self._get_junos_json_value(med)

                            learned_from = rt_entry.get("learned-from", [])
                            route.learned_from = self._get_junos_json_value(
                                learned_from
                            )

                            peer_type = rt_entry.get("peer-type", [])
                            route.peer_type = self._get_junos_json_value(peer_type)

                            # Parse origin AS from AS path
                            if route.as_path:
                                origin_as = self._parse_origin_as(route.as_path)
                                route.origin_as = origin_as

                            # Communities
                            comm_list = rt_entry.get("communities", [])
                            if isinstance(comm_list, list):
                                for c in comm_list:
                                    if isinstance(c, dict):
                                        comm = self._get_junos_json_value(
                                            c.get("community")
                                        )
                                        if comm:
                                            route.communities.append(comm)
                                    elif isinstance(c, str):
                                        route.communities.append(c)

                            if route.prefix:
                                self.routes.append(route)

            self.metadata["total_routes"] = len(self.routes)
            return True
        except Exception as e:
            print(f"Error reading Junos JSON: {e}")
            return False

    def _read_yaml(self, file_path: Path) -> bool:
        """Read YAML routing table file."""
        if not YAML_AVAILABLE:
            print("YAML support not available. Install: pip install pyyaml")
            return False

        try:
            with open(file_path, "r") as f:
                data = yaml.safe_load(f)

            self.metadata = {
                "device": data.get("device", "unknown"),
                "hostname": data.get("hostname", "unknown"),
                "timestamp": data.get("timestamp", ""),
                "total_routes": data.get("total_routes", 0),
                "format": "YAML",
            }

            self.routes = []
            for route_data in data.get("routes", []):
                route = RouteInfo(
                    prefix=route_data.get("prefix", ""),
                    table=route_data.get("table", "inet.0"),
                    protocol=route_data.get("protocol", "Unknown"),
                    next_hop=route_data.get("next_hop", ""),
                    age=route_data.get("age", 0),
                    preference=route_data.get("preference", 0),
                    metric=route_data.get("metric", 0),
                    active=route_data.get("active", False),
                    as_path=route_data.get("as_path", ""),
                )
                self.routes.append(route)

            return True
        except Exception as e:
            print(f"Error reading YAML: {e}")
            return False

    def _read_xml(self, file_path: Path) -> bool:
        """Read XML routing table file."""
        if not LXML_AVAILABLE:
            print("XML support not available. Install: pip install lxml")
            return False

        try:
            tree = etree.parse(file_path)
            root = tree.getroot()

            # Check if it's a Junos RPC reply format
            if (
                root.tag.endswith("rpc-reply")
                or root.find(".//route-table") is not None
            ):
                return self._read_junos_xml(file_path, root)

            # Our custom format
            self.metadata = {
                "device": root.findtext("device", "unknown"),
                "hostname": root.findtext("hostname", "unknown"),
                "timestamp": root.findtext("timestamp", ""),
                "total_routes": root.findtext("total-routes", "0"),
                "format": "XML",
            }

            self.routes = []
            for route_elem in root.xpath(".//route"):
                route = RouteInfo(
                    prefix=route_elem.findtext("prefix", ""),
                    table=route_elem.findtext("table", "inet.0"),
                    protocol=route_elem.findtext("protocol", "Unknown"),
                    next_hop=route_elem.findtext("next-hop", ""),
                    age=int(route_elem.findtext("age", "0") or "0"),
                    preference=int(route_elem.findtext("preference", "0") or "0"),
                    metric=int(route_elem.findtext("metric", "0") or "0"),
                    active=route_elem.findtext("active", "false").lower() == "true",
                    as_path=route_elem.findtext("as-path", ""),
                )
                self.routes.append(route)

            return True
        except Exception as e:
            print(f"Error reading XML: {e}")
            return False

    def _read_junos_xml(self, file_path: Path, root) -> bool:
        """Read Junos RPC reply XML format."""
        try:
            # Get table info
            route_table = root.xpath('.//*[local-name()="route-table"]')
            table_name = "inet.0"
            total_routes = 0

            if route_table:
                route_table = route_table[0]
                table_name_elem = route_table.xpath('./*[local-name()="table-name"]')
                if table_name_elem:
                    table_name = table_name_elem[0].text or "inet.0"
                total_routes_elem = route_table.xpath(
                    './*[local-name()="total-route-count"]'
                )
                if total_routes_elem:
                    try:
                        total_routes = int(total_routes_elem[0].text or 0)
                    except ValueError:
                        pass

            self.metadata = {
                "device": file_path.stem,
                "hostname": file_path.stem,
                "timestamp": "",
                "total_routes": total_routes,
                "format": "Junos XML",
            }

            self.routes = []

            # Parse routes using local-name() to handle namespaces
            for rt in root.xpath('.//*[local-name()="rt"]'):
                rt_dest = rt.xpath('./*[local-name()="rt-destination"]')
                prefix = rt_dest[0].text if rt_dest else ""

                for rt_entry in rt.xpath('./*[local-name()="rt-entry"]'):
                    route = RouteInfo(
                        prefix=prefix,
                        table=table_name,
                        protocol="Unknown",
                        next_hop="",
                        age=0,
                        preference=0,
                        metric=0,
                        active=False,
                    )

                    # Protocol
                    proto = rt_entry.xpath('./*[local-name()="protocol-name"]')
                    if proto:
                        route.protocol = proto[0].text or "Unknown"

                    # Active
                    active_tag = rt_entry.xpath('./*[local-name()="active-tag"]')
                    if active_tag:
                        route.active = active_tag[0].text == "*"

                    # Preference
                    pref = rt_entry.xpath('./*[local-name()="preference"]')
                    if pref:
                        try:
                            route.preference = int(pref[0].text or 0)
                        except ValueError:
                            pass

                    # Metric
                    metric = rt_entry.xpath('./*[local-name()="metric"]')
                    if metric:
                        try:
                            route.metric = int(metric[0].text or 0)
                        except ValueError:
                            pass

                    # Age - check for junos:seconds attribute
                    age = rt_entry.xpath('./*[local-name()="age"]')
                    if age:
                        age_elem = age[0]
                        # Try junos:seconds attribute
                        for attr in age_elem.attrib:
                            if "seconds" in attr.lower():
                                try:
                                    route.age = int(age_elem.attrib[attr])
                                except ValueError:
                                    pass
                                break
                        if route.age == 0 and age_elem.text:
                            # Try parsing text
                            try:
                                route.age = int(age_elem.text)
                            except ValueError:
                                pass

                    # Next hop - get first one
                    nh = rt_entry.xpath('./*[local-name()="nh"]')
                    if nh:
                        via = nh[0].xpath('./*[local-name()="via"]')
                        to = nh[0].xpath('./*[local-name()="to"]')
                        if via:
                            route.next_hop = via[0].text or ""
                        elif to:
                            route.next_hop = to[0].text or ""

                    # BGP attributes
                    as_path_elem = rt_entry.xpath('./*[local-name()="as-path"]')
                    if as_path_elem:
                        route.as_path = as_path_elem[0].text or ""
                        route.origin_as = self._parse_origin_as(route.as_path)

                    local_pref_elem = rt_entry.xpath(
                        './*[local-name()="local-preference"]'
                    )
                    if local_pref_elem:
                        route.local_pref = local_pref_elem[0].text or ""

                    med_elem = rt_entry.xpath('./*[local-name()="med"]')
                    if med_elem:
                        route.med = med_elem[0].text or ""

                    learned_from_elem = rt_entry.xpath(
                        './*[local-name()="learned-from"]'
                    )
                    if learned_from_elem:
                        route.learned_from = learned_from_elem[0].text or ""

                    peer_type_elem = rt_entry.xpath('./*[local-name()="peer-type"]')
                    if peer_type_elem:
                        route.peer_type = peer_type_elem[0].text or ""

                    communities_elem = rt_entry.xpath('./*[local-name()="communities"]')
                    if communities_elem:
                        for comm_elem in communities_elem[0].xpath(
                            './*[local-name()="community"]'
                        ):
                            if comm_elem.text:
                                route.communities.append(comm_elem.text)

                    if route.prefix:
                        self.routes.append(route)

            self.metadata["total_routes"] = len(self.routes)
            return True
        except Exception as e:
            print(f"Error reading Junos XML: {e}")
            return False

    def get_routes(self) -> List[RouteInfo]:
        """Get all routes."""
        return self.routes

    def get_metadata(self) -> Dict[str, Any]:
        """Get file metadata."""
        return self.metadata

    def get_table_data(self) -> List[List[str]]:
        """
        Get routes as table data.

        Returns:
            List of rows, each row is a list of strings
        """
        return [route.to_table_row() for route in self.routes]

    def get_table_columns(self) -> List[str]:
        """Get table column headers."""
        return ["Act", "Prefix", "Table", "Protocol", "Next-Hop", "Pref", "AS Path"]

    def filter_by_protocol(self, protocol: str) -> List[RouteInfo]:
        """Filter routes by protocol."""
        return [r for r in self.routes if r.protocol.lower() == protocol.lower()]

    def filter_by_prefix(self, prefix: str) -> List[RouteInfo]:
        """Filter routes by prefix (partial match)."""
        return [r for r in self.routes if prefix.lower() in r.prefix.lower()]

    def get_summary(self) -> Dict[str, Any]:
        """Get routing table summary."""
        protocols = {}
        active_count = 0

        for route in self.routes:
            proto = route.protocol
            protocols[proto] = protocols.get(proto, 0) + 1
            if route.active:
                active_count += 1

        return {
            "total_routes": len(self.routes),
            "active_routes": active_count,
            "protocols": protocols,
            **self.metadata,
        }
