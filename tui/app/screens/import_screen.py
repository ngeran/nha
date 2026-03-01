"""
Import Screen - Import routing table files into rib-data folder.
"""

from pathlib import Path
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Vertical
from textual.widgets import Input, Button, Label, Footer


class ImportScreen(ModalScreen[bool]):
    """
    Modal screen for importing routing table files.
    """

    CSS_PATH = "../../styles/connect.tcss"

    BINDINGS = [
        ("escape", "dismiss", "Back"),
    ]

    def __init__(self, rib_loader=None):
        super().__init__()
        self.rib_loader = rib_loader

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-form"):
            yield Label("IMPORT ROUTING TABLE", id="connect-title")
            yield Label("File Path")
            yield Input(placeholder="/path/to/file.json or .xml", id="import-path")
            yield Label("Save As (optional)")
            yield Input(placeholder="filename (defaults to original)", id="import-name")
            yield Button("Import", id="btn-connect")
        yield Footer()

    def action_dismiss(self) -> None:
        """Dismiss the screen."""
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-connect":
            self._do_import()

    def _do_import(self) -> None:
        """Import a routing table file to rib-data folder."""
        import_path = self.query_one("#import-path", Input).value.strip()
        save_name = self.query_one("#import-name", Input).value.strip()

        if not import_path:
            self.notify("Please enter a file path", severity="warning")
            return

        source_path = Path(import_path).expanduser()
        if not source_path.exists():
            self.notify(f"File not found: {source_path}", severity="error")
            return

        # Determine destination name
        if not save_name:
            save_name = source_path.stem

        # Determine format from source file extension
        suffix = source_path.suffix.lower()
        if suffix not in (".json", ".xml", ".yaml", ".yml"):
            self.notify(
                "Unsupported format. Use .json, .xml, or .yaml", severity="error"
            )
            return

        # Read source file
        try:
            content = source_path.read_text()
        except Exception as e:
            self.notify(f"Failed to read file: {e}", severity="error")
            return

        # Write to rib-data
        dest_dir = Path(__file__).parent.parent.parent.parent / "rib-data"
        dest_dir.mkdir(exist_ok=True)

        dest_path = dest_dir / f"{save_name}{suffix}"

        # Check if file exists
        if dest_path.exists():
            self.notify(f"File already exists: {save_name}{suffix}", severity="warning")
            return

        try:
            dest_path.write_text(content)
            self.notify(f"Imported: {save_name}{suffix}", severity="success")

            # Refresh the loader if available
            if self.rib_loader:
                self.rib_loader.refresh()

            self.dismiss(True)

        except Exception as e:
            self.notify(f"Failed to save: {e}", severity="error")
