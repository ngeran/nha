"""
Get RIB - Retrieve routing table from Juniper device using PyEZ.
Saves the routing table to rib-data folder in multiple formats.
"""

import sys
import os
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from jnpr.junos import Device
    from jnpr.junos.utils.start_shell import StartShell

    PYEZ_AVAILABLE = True
except ImportError:
    PYEZ_AVAILABLE = False
    print("ERROR: PyEZ not installed. Run: pip install junos-eznc")
    sys.exit(1)

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


def get_rib_pyez(
    host: str,
    user: str,
    password: Optional[str] = None,
    ssh_key: Optional[str] = None,
    port: int = 830,
    table: str = "inet.0",
) -> Dict[str, Any]:
    """
    Retrieve routing table from Juniper device using PyEZ.

    Args:
        host: Device hostname or IP
        user: Username
        password: Password (optional if using SSH key)
        ssh_key: Path to SSH private key
        port: NETCONF port
        table: Routing table to retrieve (default: inet.0)

    Returns:
        Dictionary with routes and device info
    """
    result = {
        "device": host,
        "table": table,
        "timestamp": datetime.now().isoformat(),
        "routes": [],
        "hostname": host,
    }

    device_params = {
        "host": host,
        "user": user,
        "port": port,
    }

    if password:
        device_params["password"] = password
    if ssh_key:
        device_params["ssh_private_key_file"] = ssh_key

    dev = Device(**device_params)

    try:
        print(f"Connecting to {host}...")
        dev.open()

        # Get device facts
        facts = dev.facts
        result["hostname"] = facts.get("hostname", host)
        result["device_info"] = {
            "hostname": facts.get("hostname", "unknown"),
            "model": facts.get("model", "unknown"),
            "version": facts.get("version", "unknown"),
            "serial": facts.get("serialnumber", "unknown"),
        }

        print(f"Connected to {result['hostname']}")
        print(f"Retrieving routing table '{table}'...")

        # Get routes using RPC
        # Use get-route-information RPC
        route_info = dev.rpc.get_route_information(
            table=table,
            extensive=True,
        )

        # Parse routes from XML
        routes = []
        for route_entry in route_info.xpath(".//rt-entry"):
            route_data = {
                "prefix": "",
                "table": table,
                "protocol": "Unknown",
                "next_hop": "",
                "age": 0,
                "preference": 0,
                "metric": 0,
                "as_path": "",
                "active": False,
            }

            # Get destination prefix
            dest = route_entry.getparent()
            if dest is not None:
                rt_dest = dest.find("rt-destination")
                if rt_dest is not None:
                    route_data["prefix"] = rt_dest.text or ""

            # Get protocol
            proto = route_entry.find("protocol-name")
            if proto is not None:
                route_data["protocol"] = proto.text or "Unknown"

            # Check if active
            active_tag = route_entry.find("active-tag")
            if active_tag is not None:
                route_data["active"] = active_tag.text == "*"

            # Get next hop
            nh = route_entry.find(".//nh")
            if nh is not None:
                via = nh.find("via")
                if via is not None:
                    route_data["next_hop"] = via.text or ""
                to = nh.find("to")
                if to is not None and not route_data["next_hop"]:
                    route_data["next_hop"] = to.text or ""

            # Get preference (admin distance)
            pref = route_entry.find("preference")
            if pref is not None:
                try:
                    route_data["preference"] = int(pref.text or 0)
                except ValueError:
                    pass

            # Get metric
            metric = route_entry.find("metric")
            if metric is not None:
                try:
                    route_data["metric"] = int(metric.text or 0)
                except ValueError:
                    pass

            # Get age
            age = route_entry.find("age")
            if age is not None:
                try:
                    # Age is in seconds
                    route_data["age"] = int(age.text or 0)
                except ValueError:
                    pass

            # Get AS path for BGP routes
            as_path = route_entry.find(".//as-path")
            if as_path is not None:
                route_data["as_path"] = as_path.text or ""

            if route_data["prefix"]:
                routes.append(route_data)

        result["routes"] = routes
        result["total_routes"] = len(routes)
        print(f"Retrieved {len(routes)} routes")

        dev.close()
        print("Disconnected")

    except Exception as e:
        result["error"] = str(e)
        print(f"ERROR: {e}")
        try:
            dev.close()
        except:
            pass

    return result


def save_rib(
    data: Dict[str, Any],
    output_dir: Path,
    hostname: str,
    formats: List[str] = None,
) -> List[Path]:
    """
    Save routing table data to files.

    Args:
        data: Routing table data
        output_dir: Output directory
        hostname: Device hostname for filename
        formats: List of formats to save (json, yaml, xml)

    Returns:
        List of created file paths
    """
    if formats is None:
        formats = ["json"]

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{hostname}_rib_{timestamp}"

    created_files = []

    # Save JSON
    if "json" in formats:
        json_path = output_dir / f"{base_name}.json"
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        created_files.append(json_path)
        print(f"Saved: {json_path}")

    # Save YAML
    if "yaml" in formats and YAML_AVAILABLE:
        yaml_path = output_dir / f"{base_name}.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
        created_files.append(yaml_path)
        print(f"Saved: {yaml_path}")

    # Save XML
    if "xml" in formats and LXML_AVAILABLE:
        xml_path = output_dir / f"{base_name}.xml"
        root = etree.Element("rib-data")
        etree.SubElement(root, "device").text = data.get("device", "")
        etree.SubElement(root, "hostname").text = data.get("hostname", "")
        etree.SubElement(root, "timestamp").text = data.get("timestamp", "")
        etree.SubElement(root, "total-routes").text = str(data.get("total_routes", 0))

        routes_elem = etree.SubElement(root, "routes")
        for route in data.get("routes", []):
            route_elem = etree.SubElement(routes_elem, "route")
            for key, value in route.items():
                elem = etree.SubElement(route_elem, key.replace("_", "-"))
                elem.text = str(value) if value is not None else ""

        tree = etree.ElementTree(root)
        tree.write(xml_path, pretty_print=True, xml_declaration=True, encoding="UTF-8")
        created_files.append(xml_path)
        print(f"Saved: {xml_path}")

    return created_files


def main():
    parser = argparse.ArgumentParser(
        description="Retrieve routing table from Juniper device"
    )
    parser.add_argument("host", help="Device hostname or IP address")
    parser.add_argument("-u", "--user", required=True, help="Username")
    parser.add_argument("-p", "--password", help="Password")
    parser.add_argument("-k", "--ssh-key", help="SSH private key file")
    parser.add_argument(
        "--port", type=int, default=830, help="NETCONF port (default: 830)"
    )
    parser.add_argument(
        "-t", "--table", default="inet.0", help="Routing table (default: inet.0)"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="rib-data",
        help="Output directory (default: rib-data)",
    )
    parser.add_argument(
        "-f",
        "--format",
        nargs="+",
        choices=["json", "yaml", "xml"],
        default=["json"],
        help="Output format(s) (default: json)",
    )

    args = parser.parse_args()

    if not args.password and not args.ssh_key:
        print("ERROR: Either password or SSH key is required")
        sys.exit(1)

    # Retrieve RIB
    data = get_rib_pyez(
        host=args.host,
        user=args.user,
        password=args.password,
        ssh_key=args.ssh_key,
        port=args.port,
        table=args.table,
    )

    if "error" in data:
        print(f"Failed to retrieve RIB: {data['error']}")
        sys.exit(1)

    # Save to files
    output_dir = Path(__file__).parent.parent / args.output
    files = save_rib(
        data=data,
        output_dir=output_dir,
        hostname=data.get("hostname", args.host),
        formats=args.format,
    )

    print(f"\nCreated {len(files)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
