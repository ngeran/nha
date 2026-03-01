"""
RIB Engine for fetching and parsing Juniper routing tables via PyEZ.
Uses ConnectionEngine for device connectivity and DisconnectEngine for cleanup.
"""

import logging
from typing import List, Dict, Optional
from jnpr.junos import Device
from jnpr.junos.op.routes import RouteTable

from backend.app.core.connection_engine import ConnectionEngine, ConnectionState
from backend.app.core.disconnect_engine import DisconnectEngine
from shared.schemas import (
    RouteEntry,
    ProtocolType,
    BGPAttributes,
    OSPFAttributes,
    StaticAttributes,
    LocalAttributes,
    DirectAttributes,
    RouteAttributes,
)

logger = logging.getLogger(__name__)


class RIBEngine:
    """
    RIB Engine for fetching and parsing Juniper routing tables via PyEZ.
    Uses dedicated ConnectionEngine and DisconnectEngine for connection management.
    """

    def __init__(
        self,
        host: str,
        user: str,
        password: Optional[str] = None,
        ssh_key: Optional[str] = None,
        port: int = 830,
    ):
        self.host = host
        self.user = user
        self.password = password
        self.ssh_key = ssh_key
        self.port = port

        # Initialize connection engine
        self._connection_engine = ConnectionEngine(
            host=host,
            user=user,
            password=password,
            ssh_key=ssh_key,
            port=port,
        )

    @property
    def is_connected(self) -> bool:
        """Check if device is connected."""
        return self._connection_engine.is_connected

    def connect(self) -> bool:
        """Establish connection to the device."""
        return self._connection_engine.connect()

    def disconnect(self) -> bool:
        """Disconnect from the device."""
        disconnect_engine = DisconnectEngine(self._connection_engine)
        return disconnect_engine.disconnect()

    def fetch_routes(self, table: str = None) -> List[RouteEntry]:
        """
        Fetch routing table entries from the device using PyEZ RouteTable.

        Args:
            table: Optional table name filter (e.g., 'inet.0', 'inet6.0')

        Returns:
            List of RouteEntry objects
        """
        routes = []

        if not self.is_connected:
            if not self.connect():
                logger.error(f"Cannot fetch routes - not connected to {self.host}")
                return routes

        try:
            logger.info(f"Fetching routes from {self.host}...")

            device = self._connection_engine.device
            route_table = RouteTable(device)

            if table:
                route_table.get(table=table)
            else:
                route_table.get()

            for route in route_table:
                entry = self._parse_route(route)
                if entry:
                    routes.append(entry)

            logger.info(f"Retrieved {len(routes)} routes from {self.host}")

        except Exception as e:
            logger.error(f"Failed to fetch routes from {self.host}: {e}", exc_info=True)
        finally:
            self.disconnect()

        return routes

    def fetch_routes_rpc(self, table: str = None) -> List[RouteEntry]:
        """
        Alternative method using direct RPC for more detailed route information.
        """
        routes = []

        if not self.is_connected:
            if not self.connect():
                logger.error(
                    f"Cannot fetch routes via RPC - not connected to {self.host}"
                )
                return routes

        try:
            logger.info(f"Fetching routes via RPC from {self.host}...")

            device = self._connection_engine.device
            rpc_args = {"detail": True}
            if table:
                rpc_args["table"] = table

            route_info = device.rpc.get_route_information(**rpc_args)
            routes = self._parse_route_information(route_info)
            logger.info(f"Retrieved {len(routes)} routes from {self.host}")

        except Exception as e:
            logger.error(
                f"Failed to fetch routes via RPC from {self.host}: {e}", exc_info=True
            )
        finally:
            self.disconnect()

        return routes

    def _parse_route(self, route) -> Optional[RouteEntry]:
        """Parse a single route from RouteTable entry."""
        try:
            prefix = route.key if hasattr(route, "key") else str(route.name)
            protocol_str = getattr(route, "protocol", "")
            protocol = self._map_protocol(protocol_str)

            if protocol is None:
                return None

            next_hop = getattr(route, "nh", "unknown")
            if isinstance(next_hop, list):
                next_hop = next_hop[0] if next_hop else "unknown"

            age = getattr(route, "age", 0)
            if isinstance(age, str):
                age = self._parse_age(age)

            table_name = getattr(route, "rt_table", "inet.0")

            attributes = self._build_attributes_simple(protocol, route)
            if attributes is None:
                attributes = self._build_default_attributes(protocol, route)

            return RouteEntry(
                prefix=prefix,
                table=table_name,
                protocol=protocol,
                next_hop=str(next_hop),
                age=age if isinstance(age, int) else 0,
                attributes=attributes,
            )
        except Exception as e:
            logger.debug(f"Error parsing route {getattr(route, 'key', 'unknown')}: {e}")
            return None

    def _parse_route_information(self, xml_response) -> List[RouteEntry]:
        """Parse the route-information RPC response."""
        routes = []

        for rt_table in xml_response.xpath(".//route-table"):
            table_name = rt_table.findtext("table-name", "unknown")

            for rt in rt_table.xpath(".//rt"):
                prefix = rt.findtext("rt-destination", "")

                for rt_entry in rt.xpath(".//rt-entry"):
                    entry = self._parse_route_entry_xml(prefix, table_name, rt_entry)
                    if entry:
                        routes.append(entry)

        return routes

    def _parse_route_entry_xml(
        self, prefix: str, table: str, rt_entry
    ) -> Optional[RouteEntry]:
        """Parse a single route entry from XML."""
        try:
            protocol_str = rt_entry.findtext("protocol-name", "")
            protocol = self._map_protocol(protocol_str)

            if protocol is None:
                return None

            age = self._parse_age(rt_entry.findtext("age", "0"))
            preference = int(rt_entry.findtext("preference", "0") or "0")

            nh_list = rt_entry.xpath(".//nh")
            next_hop = self._extract_next_hop(nh_list)

            attributes = self._build_attributes_xml(protocol, rt_entry, preference)

            if attributes is None:
                return None

            return RouteEntry(
                prefix=prefix,
                table=table,
                protocol=protocol,
                next_hop=next_hop,
                age=age,
                attributes=attributes,
            )
        except Exception as e:
            logger.debug(f"Error parsing route entry for {prefix}: {e}")
            return None

    def _extract_next_hop(self, nh_list) -> str:
        """Extract next-hop from nh elements."""
        for nh in nh_list:
            to = nh.findtext("to", "")
            if to:
                return to
            via = nh.findtext("via", "")
            if via:
                return via
        return "discard"

    def _parse_age(self, age_str: str) -> int:
        """Parse age string to seconds."""
        if not age_str:
            return 0
        try:
            if ":" in str(age_str):
                parts = str(age_str).split(":")
                if len(parts) == 3:
                    h, m, s = parts
                    return int(h) * 3600 + int(m) * 60 + int(float(s))
                elif len(parts) == 2:
                    m, s = parts
                    return int(m) * 60 + int(float(s))
            return int(float(age_str))
        except (ValueError, TypeError):
            return 0

    def _build_attributes_simple(
        self, protocol: ProtocolType, route
    ) -> Optional[RouteAttributes]:
        """Build attributes from RouteTable entry."""
        try:
            if protocol == ProtocolType.BGP:
                return BGPAttributes(
                    as_path=getattr(route, "as_path", "") or "",
                    local_pref=getattr(route, "local_pref", None),
                    med=getattr(route, "med", None),
                    communities=getattr(route, "communities", []) or [],
                )
            elif protocol == ProtocolType.OSPF:
                return OSPFAttributes(
                    area_id=getattr(route, "area", "0.0.0.0") or "0.0.0.0",
                    metric=getattr(route, "metric", 0) or 0,
                )
            return None
        except Exception:
            return None

    def _build_default_attributes(
        self, protocol: ProtocolType, route
    ) -> RouteAttributes:
        """Build default attributes when specific parsing fails."""
        preference = getattr(route, "preference", 0) or 0

        if protocol == ProtocolType.STATIC:
            return StaticAttributes(preference=int(preference))
        elif protocol == ProtocolType.LOCAL:
            return LocalAttributes()
        elif protocol == ProtocolType.DIRECT:
            return DirectAttributes()
        elif protocol == ProtocolType.BGP:
            return BGPAttributes(as_path="", local_pref=None, med=None, communities=[])
        elif protocol == ProtocolType.OSPF:
            return OSPFAttributes(area_id="0.0.0.0", metric=0)

        return StaticAttributes(preference=int(preference))

    def _build_attributes_xml(
        self, protocol: ProtocolType, rt_entry, preference: int
    ) -> Optional[RouteAttributes]:
        """Build protocol-specific attributes from XML."""
        try:
            if protocol == ProtocolType.BGP:
                return self._build_bgp_attributes_xml(rt_entry)
            elif protocol == ProtocolType.OSPF:
                return self._build_ospf_attributes_xml(rt_entry)
            elif protocol == ProtocolType.STATIC:
                return StaticAttributes(preference=preference)
            elif protocol == ProtocolType.LOCAL:
                return LocalAttributes()
            elif protocol == ProtocolType.DIRECT:
                return DirectAttributes()
            else:
                return None
        except Exception as e:
            logger.debug(f"Error building attributes for {protocol}: {e}")
            return None

    def _build_bgp_attributes_xml(self, rt_entry) -> BGPAttributes:
        """Build BGP-specific attributes from XML."""
        as_path = rt_entry.findtext("as-path", "")

        med = None
        local_pref = None
        communities = []

        bgp_output = rt_entry.xpath(".//bgp-output")
        if bgp_output:
            bgp = bgp_output[0]
            med_str = bgp.findtext("med", "")
            med = int(med_str) if med_str else None
            local_pref_str = bgp.findtext("local-preference", "")
            local_pref = int(local_pref_str) if local_pref_str else None

            for comm in bgp.xpath(".//communities/community"):
                comm_text = comm.text
                if comm_text:
                    communities.append(comm_text)
        else:
            med_str = rt_entry.findtext("metric", "")
            med = int(med_str) if med_str else None
            local_pref_str = rt_entry.findtext("local-preference", "")
            local_pref = int(local_pref_str) if local_pref_str else None

        return BGPAttributes(
            as_path=as_path or "",
            local_pref=local_pref,
            med=med,
            communities=communities,
        )

    def _build_ospf_attributes_xml(self, rt_entry) -> OSPFAttributes:
        """Build OSPF-specific attributes from XML."""
        metric = 0
        area_id = "0.0.0.0"

        ospf_area = rt_entry.xpath(".//ospf-area-id")
        if ospf_area:
            area_id = ospf_area[0].text or area_id

        metric_str = rt_entry.findtext("metric", "0")
        try:
            metric = int(metric_str) if metric_str else 0
        except ValueError:
            metric = 0

        return OSPFAttributes(area_id=area_id, metric=metric)

    def _map_protocol(self, protocol_str: str) -> Optional[ProtocolType]:
        """Map protocol string to ProtocolType enum."""
        if not protocol_str:
            return None

        p = protocol_str.lower().strip()

        protocol_map = {
            "bgp": ProtocolType.BGP,
            "ospf": ProtocolType.OSPF,
            "ospf3": ProtocolType.OSPF,
            "is-is": ProtocolType.ISIS,
            "isis": ProtocolType.ISIS,
            "static": ProtocolType.STATIC,
            "local": ProtocolType.LOCAL,
            "direct": ProtocolType.DIRECT,
        }

        for key, proto in protocol_map.items():
            if key in p:
                return proto

        return None

    def get_route_summary(self) -> Dict[str, int]:
        """Get a summary of routes by protocol."""
        routes = self.fetch_routes()
        summary = {}
        for route in routes:
            proto = route.protocol.value
            summary[proto] = summary.get(proto, 0) + 1
        return summary

    def get_connection_info(self):
        """Get connection information."""
        return self._connection_engine.get_connection_info()
