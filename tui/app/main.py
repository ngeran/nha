"""
RIB Analyze - Routing Table Analysis Tool
"""

import os
import sys
import asyncio
from pathlib import Path
from typing import Optional, List, Dict

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Header, Footer, Static, DataTable, Label
from textual.reactive import reactive

from shared.rib_loader import RIBLoader
from shared.schemas import ConnectionConfig
from tui.app.widgets.dashboard import DashboardWidget
from tui.app.screens.rib_file import RIBFileScreen
from tui.app.screens.connect import ConnectionScreen
from tui.app.screens.import_screen import ImportScreen
from tui.app.screens.export_screen import ExportScreen
from tui.app.screens.help_screen import HelpScreen
from tui.app.screens.compare_screen import CompareScreen
from tui.app.screens.offline_screen import OfflineModeScreen

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


class RIBAnalyze(App):
    """RIB Analyze - Routing Table Analysis Tool"""

    CSS_PATH = ["../styles/main.tcss"]
    TITLE = "RIB Analyze"

    BINDINGS = [
        ("c", "connect", "Connect"),
        ("d", "disconnect", "Disconnect"),
        ("x", "show_compare", "Compare"),
        ("i", "show_import", "Import"),
        ("e", "show_export", "Export"),
        ("r", "refresh", "Refresh"),
        ("h", "show_help", "Help"),
        ("q", "quit", "Quit"),
    ]

    # Reactive state
    file_count = reactive(0)
    ws_connected = reactive(False)
    device_count = reactive(0)
    connected_hosts = reactive("")

    rib_loader: RIBLoader = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="app-container"):
            # Connection status bar with icons
            yield Static(
                "⚫ WS: Disconnected │ 📱 Devices: 0 │ 🌐 Hosts: -",
                id="connection-status",
            )
            with Vertical(id="main-content"):
                # Dashboard widget for baseline statistics
                yield DashboardWidget()

                with Vertical(id="files-section-full"):
                    yield Label("ROUTING TABLE FILES", classes="section-header")
                    yield DataTable(
                        id="files-table", cursor_type="row", zebra_stripes=True
                    )
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize the app."""
        self.rib_loader = RIBLoader()
        self._update_files_table()
        self._update_connection_status()

        # Start background task to check connection
        self._monitor_task = asyncio.create_task(self._monitor_connection())

    def _update_connection_status(self) -> None:
        """Update the connection status bar."""
        status = self.query_one("#connection-status", Static)

        if self.ws_connected:
            ws_icon = "⚙  "  # Gear with 2 spaces
            ws_text = "[green]Connected[/green]"
            devices = f"[orange]{self.device_count}[/orange]"
            hosts = (
                f"[green]{self.connected_hosts}[/green]"
                if self.connected_hosts
                else "[green]-[/green]"
            )
            mode = "[dim]Online[/dim]"
        else:
            ws_icon = "○  "  # Empty circle with 2 spaces
            ws_text = "[red]Disconnected[/red]"
            devices = "[red]0[/red]"
            hosts = "[red]-[/red]"
            mode = "[yellow]Offline Mode[/yellow]"

        status.update(
            f"{ws_icon}WS: {ws_text}  │  ⇋ Devices: {devices}  │  ◎ Hosts: {hosts}  │  {mode}"
        )

    async def _monitor_connection(self) -> None:
        """Background task to monitor backend connection."""
        import httpx

        while True:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{BACKEND_URL}/api/status", timeout=2.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        self.ws_connected = True
                        self.device_count = data.get("device_count", 0)

                        # Get connected hosts
                        devices = data.get("devices", [])
                        if devices:
                            hosts = ", ".join([d.get("host", "?") for d in devices[:3]])
                            if len(devices) > 3:
                                hosts += f" +{len(devices) - 3}"
                            self.connected_hosts = hosts
                        else:
                            self.connected_hosts = ""
                    else:
                        self.ws_connected = False
                        self.device_count = 0
                        self.connected_hosts = ""
            except Exception:
                self.ws_connected = False
                self.device_count = 0
                self.connected_hosts = ""

            self._update_connection_status()
            await asyncio.sleep(5)

    def _update_files_table(self) -> None:
        """Update the files table with available routing table files."""
        table = self.query_one("#files-table", DataTable)
        table.clear()

        if not table.columns:
            table.add_columns("File", "Type", "Size", "Modified")

        files = self.rib_loader.list_files()

        for rib_file in files:
            size = rib_file.size
            if size > 1024 * 1024:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            elif size > 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"

            mod_str = rib_file.modified.strftime("%Y-%m-%d %H:%M")

            table.add_row(
                rib_file.name,
                rib_file.format.upper(),
                size_str,
                mod_str,
            )

        self.file_count = len(files)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in files table."""
        if event.data_table.id == "files-table":
            row_key = event.row_key
            row_data = event.data_table.get_row(row_key)

            if row_data:
                file_name = row_data[0]
                file_path = self.rib_loader.data_dir / file_name

                if file_path.exists():
                    self.push_screen(RIBFileScreen(file_path, file_name))
                else:
                    self.notify(f"File not found: {file_name}", severity="error")

    def action_refresh(self) -> None:
        """Refresh the files table."""
        self.rib_loader.refresh()
        self._update_files_table()
        self.notify("Files refreshed", severity="information")

    def action_connect(self) -> None:
        """Show connection screen or offline mode message."""
        if not self.ws_connected:
            self.push_screen(OfflineModeScreen())
        else:
            self.push_screen(ConnectionScreen(), self._handle_connect_result)

    def _handle_connect_result(self, config: Optional[ConnectionConfig]) -> None:
        """Handle connection screen result."""
        if config:
            asyncio.create_task(self._do_connect(config))

    async def _do_connect(self, config: ConnectionConfig) -> None:
        """Connect to device via backend."""
        import httpx

        self.notify("Connecting...", severity="information")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{BACKEND_URL}/api/connect",
                    json={
                        "host": config.host,
                        "user": config.user,
                        "password": config.password,
                        "port": config.port,
                    },
                )

                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "connected":
                        device_info = data.get("device_info", {})
                        hostname = device_info.get("hostname", config.host)
                        self.notify(f"Connected to {hostname}", severity="success")
                        self.ws_connected = True
                        self.device_count = 1
                        self.connected_hosts = hostname
                        self._update_connection_status()
                    else:
                        error = data.get("error") or data.get(
                            "message", "Unknown error"
                        )
                        self.notify(f"Connection failed: {error}", severity="error")
                else:
                    self.notify(f"Backend error: {resp.status_code}", severity="error")

        except Exception as e:
            self.notify(f"Connection error: {e}", severity="error")

    def action_disconnect(self) -> None:
        """Disconnect from backend."""
        asyncio.create_task(self._do_disconnect())

    async def _do_disconnect(self) -> None:
        """Execute disconnect."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(f"{BACKEND_URL}/api/disconnect")
        except Exception:
            pass

        self.ws_connected = False
        self.device_count = 0
        self.connected_hosts = ""
        self._update_connection_status()
        self.notify("Disconnected", severity="information")

    def action_show_import(self) -> None:
        """Show import screen."""
        self.push_screen(
            ImportScreen(rib_loader=self.rib_loader), self._handle_import_result
        )

    def action_show_export(self) -> None:
        """Show export screen."""
        self.push_screen(
            ExportScreen(current_routes=[], rib_loader=self.rib_loader),
            self._handle_import_result,
        )

    def action_show_help(self) -> None:
        """Show help screen."""
        self.push_screen(HelpScreen())

    def action_show_compare(self) -> None:
        """Show compare screen."""
        self.push_screen(CompareScreen(rib_loader=self.rib_loader))

    def _handle_import_result(self, result) -> None:
        """Handle import/export screen result."""
        self.rib_loader.refresh()
        self._update_files_table()


if __name__ == "__main__":
    app = RIBAnalyze()
    app.run()
