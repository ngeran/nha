import json
import os
from typing import Dict, Any, List
from pathlib import Path


class RouteDataManager:
    """
    Manage routing table data import/export operations.
    """

    def __init__(self, data_dir: str = "rib-data"):
        self.data_dir = Path(data_dir)
        self.baseline_files = {
            "xml": self.data_dir / "baseline-routes.xml",
            "json": self.data_dir / "baseline-routes.json",
            "yaml": self.data_dir / "baseline-routes.yaml",
        }

    def save_baseline(self, routes: List[Any], format_type: str = "json") -> bool:
        """
        Save routes to baseline file in specified format.

        Args:
            routes: List of route dictionaries
            format_type: 'xml', 'json', or 'yaml'
        """
        if format_type not in self.baseline_files:
            raise ValueError(f"Unsupported format: {format_type}")

        file_path = self.baseline_files[format_type]

        try:
            if format_type == "json":
                data = {
                    "routes": routes,
                    "metadata": {
                        "description": "Baseline routing table for RIB Monitor",
                        "created": routes[0].get("timestamp") if routes else None,
                        "source": "imported",
                        "format": "json",
                    },
                }
                with open(file_path, "w") as f:
                    json.dump(data, f, indent=2)

            elif format_type == "yaml":
                import yaml

                data = {
                    "routes": routes,
                    "metadata": {
                        "description": "Baseline routing table for RIB Monitor",
                        "created": routes[0].get("timestamp") if routes else None,
                        "source": "imported",
                        "format": "yaml",
                    },
                }
                with open(file_path, "w") as f:
                    yaml.dump(data, f, default_flow_style=False, indent=2)

            elif format_type == "xml":
                # Create simple XML structure
                import xml.etree.ElementTree as ET

                root = ET.Element("routes")

                for route in routes:
                    route_elem = ET.SubElement(root, "route")
                    for key, value in route.items():
                        if isinstance(value, (dict, list)):
                            continue  # Skip complex structures for simple XML
                        elem = ET.SubElement(route_elem, key)
                        elem.text = str(value)

                tree = ET.ElementTree(root)
                tree.write(file_path, encoding="UTF-8", xml_declaration=True)

            print(
                f"Successfully saved {len(routes)} routes to {format_type.upper()} format"
            )
            return True

        except Exception as e:
            print(f"Error saving routes to {format_type}: {e}")
            return False

    def load_baseline(self, format_type: str = "json") -> List[Dict[str, Any]]:
        """
        Load routes from baseline file.

        Args:
            format_type: 'xml', 'json', or 'yaml'

        Returns:
            List of route dictionaries
        """
        if format_type not in self.baseline_files:
            raise ValueError(f"Unsupported format: {format_type}")

        file_path = self.baseline_files[format_type]

        if not file_path.exists():
            print(f"No baseline file found for format: {format_type}")
            return []

        try:
            if format_type == "json":
                with open(file_path, "r") as f:
                    data = json.load(f)
                    return data.get("routes", [])

            elif format_type == "yaml":
                import yaml

                with open(file_path, "r") as f:
                    data = yaml.safe_load(f)
                    return data.get("routes", [])

            elif format_type == "xml":
                import xml.etree.ElementTree as ET

                tree = ET.parse(file_path)
                root = tree.getroot()
                routes = []

                for route_elem in root.findall("route"):
                    route_dict = {}
                    for child in route_elem:
                        if child.text:
                            route_dict[child.tag] = child.text
                    routes.append(route_dict)

                return routes

        except Exception as e:
            print(f"Error loading routes from {format_type}: {e}")
            return []

    def get_available_formats(self) -> List[str]:
        """Return list of available formats."""
        return list(self.baseline_files.keys())

    def export_current_routes(
        self, routes: List[Dict[str, Any]], format_type: str
    ) -> str:
        """
        Export current routes and return the filename.
        """
        timestamp = os.path.basename(__file__)  # Just for filename

        if format_type == "json":
            filename = f"current-routes-{timestamp}.json"
            file_path = self.data_dir / filename

            data = {
                "routes": routes,
                "metadata": {
                    "description": "Current routing table export",
                    "exported_at": str(os.path.getctime(__file__)),
                    "source": "live",
                    "format": "json",
                },
            }

            with open(file_path, "w") as f:
                json.dump(data, f, indent=2)

            return str(file_path)

        # Similar for other formats...
        return None
