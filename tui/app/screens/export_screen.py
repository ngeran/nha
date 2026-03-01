"""
Export Screen - Export routing table data to file.
"""

from pathlib import Path
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Vertical
from textual.widgets import Input, Button, Label, Select, Footer


class ExportScreen(ModalScreen[bool]):
    """
    Modal screen for exporting routing table data.
    """

    CSS_PATH = "../../styles/connect.tcss"

    BINDINGS = [
        ("escape", "dismiss", "Back"),
    ]

    def __init__(self, current_routes=None, rib_loader=None):
        super().__init__()
        self.current_routes = current_routes or []
        self.rib_loader = rib_loader

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-form"):
            yield Label("EXPORT ROUTING TABLE", id="connect-title")
            yield Label("Filename")
            yield Input(placeholder="my-routes", id="export-name")
            yield Label("Format")
            yield Select(
                options=[("JSON", "json"), ("YAML", "yaml"), ("XML", "xml")],
                id="export-format",
                value="json",
            )
            yield Button("Export", id="btn-connect")
        yield Footer()

    def action_dismiss(self) -> None:
        """Dismiss the screen."""
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-connect":
            self._do_export()

    def _do_export(self) -> None:
        """Export current routes to a file."""
        export_name = self.query_one("#export-name", Input).value.strip()
        export_format = self.query_one("#export-format", Select).value

        if not export_name:
            self.notify("Please enter a filename", severity="warning")
            return

        if not self.current_routes:
            self.notify("No routes to export", severity="warning")
            return

        # Prepare data
        data = {
            "device": "export",
            "hostname": "export",
            "timestamp": None,
            "routes": self.current_routes,
            "total_routes": len(self.current_routes),
        }

        # Determine extension
        ext_map = {"json": ".json", "yaml": ".yaml", "xml": ".xml"}
        ext = ext_map.get(export_format, ".json")

        dest_dir = Path(__file__).parent.parent.parent.parent / "rib-data"
        dest_dir.mkdir(exist_ok=True)
        dest_path = dest_dir / f"{export_name}{ext}"

        try:
            if export_format == "json":
                import json

                with open(dest_path, "w") as f:
                    json.dump(data, f, indent=2, default=str)
            elif export_format == "yaml":
                import yaml

                with open(dest_path, "w") as f:
                    yaml.dump(data, f, default_flow_style=False)
            elif export_format == "xml":
                from lxml import etree

                root = etree.Element("rib-data")
                etree.SubElement(root, "device").text = "export"
                etree.SubElement(root, "hostname").text = "export"
                etree.SubElement(root, "timestamp").text = ""
                etree.SubElement(root, "total-routes").text = str(
                    len(self.current_routes)
                )
                routes_elem = etree.SubElement(root, "routes")
                for route in self.current_routes:
                    route_elem = etree.SubElement(routes_elem, "route")
                    for key, value in route.items():
                        elem = etree.SubElement(route_elem, key.replace("_", "-"))
                        elem.text = str(value) if value is not None else ""
                tree = etree.ElementTree(root)
                tree.write(
                    dest_path, pretty_print=True, xml_declaration=True, encoding="UTF-8"
                )

            self.notify(
                f"Exported {len(self.current_routes)} routes to {export_name}{ext}",
                severity="success",
            )

            # Refresh the loader if available
            if self.rib_loader:
                self.rib_loader.refresh()

            self.dismiss(True)

        except Exception as e:
            self.notify(f"Export failed: {e}", severity="error")
