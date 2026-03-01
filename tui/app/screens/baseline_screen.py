from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Vertical
from textual.widgets import Header, Footer, Select, Button, Label, Static
from textual.reactive import reactive
from pathlib import Path
import os

from shared.config import ConfigManager


class BaselineScreen(ModalScreen):
    """
    A modal screen for setting baseline routing table.
    """

    CSS_PATH = "../../styles/connect.tcss"

    BINDINGS = [
        ("escape", "dismiss", "Back"),
    ]

    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.selected_file = reactive("")

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-form"):
            yield Label("SET BASELINE", id="connect-title")
            yield Label("Select a routing table file to use as baseline:")

            # Get list of routing table files
            files = self._get_routing_files()
            if files:
                options = [(f"{name}", name) for name in files]
                yield Select(options, id="file-select", value=files[0])
            else:
                yield Static(
                    "No routing table files found in rib-data directory.",
                    classes="error-message",
                )

            yield Button("Set", id="btn-set")
        yield Footer()

    def _get_routing_files(self) -> list[str]:
        """Get list of routing table files from rib-data directory."""
        rib_dir = Path("rib-data")
        if not rib_dir.exists():
            return []

        files = []
        for file in rib_dir.iterdir():
            if file.is_file() and file.suffix.lower() in [
                ".json",
                ".xml",
                ".yaml",
                ".yml",
            ]:
                files.append(file.name)

        # Sort files by name
        return sorted(files)

    def action_dismiss(self) -> None:
        """Dismiss screen."""
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-set":
            try:
                select_widget = self.query_one("#file-select", Select)
                selected_file = select_widget.value

                # Convert to string if needed
                if selected_file and selected_file != "":
                    selected_file_str = str(selected_file)
                    # Save the selected file as baseline
                    self._save_baseline(selected_file_str)
                    self.notify(
                        f"Baseline set to {selected_file_str}", severity="information"
                    )
                    self.dismiss(True)
                else:
                    self.notify("Please select a file", severity="error")
            except Exception as e:
                # Debug the error
                self.notify(f"Error selecting file: {str(e)}", severity="error")
                # Check if files are available
                files = self._get_routing_files()
                if not files:
                    self.notify(
                        "No routing table files found in rib-data directory",
                        severity="error",
                    )

    def _save_baseline(self, filename: str) -> None:
        """Save the selected file as baseline."""
        from shared.config import BaselineConfig
        from datetime import datetime

        # Read the file to get device info
        rib_path = Path("rib-data") / filename
        device_name = "Unknown"
        description = (
            f"Set from {filename} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # Try to extract device name from file
        if rib_path.exists():
            try:
                from shared.rib_reader import RIBReader

                reader = RIBReader()
                if reader.read_file(rib_path):
                    metadata = reader.get_metadata()
                    device_name = metadata.get(
                        "hostname", metadata.get("device", "Unknown")
                    )
            except:
                pass

        # Create and save baseline config
        baseline_config = BaselineConfig(
            device_name=device_name,
            file_path=str(rib_path),
            description=description,
            created_at=datetime.now().isoformat(),
        )

        self.config_manager.save_baseline_config(baseline_config)
