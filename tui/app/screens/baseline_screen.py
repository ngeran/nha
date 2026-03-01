"""
Screen for setting and managing baseline configuration
"""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.containers import Vertical, Horizontal, Grid
from textual.widgets import (
    Header,
    Footer,
    Static,
    DataTable,
    Button,
    Input,
    Label,
)
from textual.reactive import reactive

from shared.config import ConfigManager
from shared.rib_reader import RIBReader


class BaselineScreen(Screen):
    """Screen for setting baseline configuration"""

    CSS = """
    Screen {
        background: #1a1b26;
    }
    
    Header {
        dock: top;
        height: 1;
        background: #24283b;
        color: #c0caf5;
    }
    
    Footer {
        dock: bottom;
        height: 1;
        background: #24283b;
    }
    
    .container {
        padding: 1;
    }
    
    .title {
        text-align: center;
        color: #7aa2f7;
        text-style: bold;
        background: #1f2335;
        padding: 0 2;
        height: 1;
        margin-bottom: 1;
    }
    
    .subtitle {
        color: #9aa5ce;
        text-align: center;
        margin-bottom: 1;
    }
    
    .files-table {
        height: 1fr;
        margin-bottom: 1;
    }
    
    .baseline-info {
        background: #1f2335;
        padding: 1;
        margin-bottom: 1;
        height: auto;
    }
    
    .info-title {
        color: #7aa2f7;
        text-style: bold;
        margin-bottom: 1;
    }
    
    .info-content {
        color: #9aa5ce;
    }
    
    .button-row {
        height: 3;
        dock: bottom;
        padding: 0 2;
        background: #1f2335;
    }
    
    .set-btn {
        color: #7aa2f7;
        background: #24283b;
        border: solid #3b4261;
        margin-right: 1;
    }
    
    .set-btn:hover {
        color: #c0caf5;
        background: #3b4261;
    }
    
    .cancel-btn {
        color: #9aa5ce;
        background: #24283b;
        border: solid #3b4261;
    }
    
    .cancel-btn:hover {
        color: #c0caf5;
        background: #3b4261;
    }
    """

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self, rib_loader):
        super().__init__()
        self.rib_loader = rib_loader
        self.config_manager = ConfigManager()
        self.selected_file = reactive(None)
        self.device_name = reactive("")

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="container"):
            yield Static("SELECT BASELINE FILE", classes="title")
            yield Static(
                "Choose a routing table file to use as the baseline for comparison",
                classes="subtitle",
            )

            # Current baseline info
            current_baseline = self.config_manager.load_baseline_config()
            if current_baseline:
                with Vertical(classes="baseline-info"):
                    yield Static("Current Baseline:", classes="info-title")
                    yield Static(
                        f"File: {current_baseline.file_path}", classes="info-content"
                    )
                    yield Static(
                        f"Device: {current_baseline.device_name}",
                        classes="info-content",
                    )
                    if current_baseline.description:
                        yield Static(
                            f"Description: {current_baseline.description}",
                            classes="info-content",
                        )
            else:
                with Vertical(classes="baseline-info"):
                    yield Static("No baseline configured", classes="info-title")
                    yield Static(
                        "Select a file below to set as baseline", classes="info-content"
                    )

            # Files table
            yield DataTable(
                id="baseline-files-table",
                classes="files-table",
                cursor_type="row",
                zebra_stripes=True,
            )

            # Device name input
            with Horizontal():
                yield Static("Device Name:", classes="info-title")
                yield Input(
                    placeholder="Enter device name...",
                    id="device-name-input",
                    value=self.device_name,
                )

            # Buttons
            with Horizontal(classes="button-row"):
                yield Button(
                    "Set Baseline",
                    id="set-baseline-btn",
                    classes="set-btn",
                    disabled=True,
                )
                yield Button("Cancel", id="cancel-btn", classes="cancel-btn")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize the screen"""
        self._populate_files_table()

    def _populate_files_table(self) -> None:
        """Populate the files table with available routing table files"""
        table = self.query_one("#baseline-files-table", DataTable)
        table.clear()

        if not table.columns:
            table.add_columns("File", "Type", "Size", "Modified")

        files = self.rib_loader.list_files()

        for rib_file in files:
            # Format size
            size = rib_file.size
            if size > 1024 * 1024:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            elif size > 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"

            # Format modified time
            mod_str = rib_file.modified.strftime("%Y-%m-%d %H:%M")

            table.add_row(
                rib_file.name,
                rib_file.format.upper(),
                size_str,
                mod_str,
                key=rib_file.path,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle file selection"""
        if event.row_key is None:
            return

        table = self.query_one("#baseline-files-table", DataTable)
        row_data = table.get_row(event.row_key)

        if row_data:
            self.selected_file = row_data[0]  # File name

            # Enable the set baseline button if device name is entered
            device_input = self.query_one("#device-name-input", Input)
            set_btn = self.query_one("#set-baseline-btn", Button)

            if device_input.value:
                set_btn.disabled = False

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle device name input changes"""
        if event.input.id == "device-name-input":
            self.device_name = event.value

            # Enable the set baseline button if a file is selected
            set_btn = self.query_one("#set-baseline-btn", Button)
            if self.selected_file:
                set_btn.disabled = not bool(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses"""
        if event.button.id == "set-baseline-btn":
            if self.selected_file and self.device_name:
                # Get the relative path
                files = self.rib_loader.list_files()
                file_path = None

                for rib_file in files:
                    if rib_file.name == self.selected_file:
                        file_path = str(
                            rib_file.path.relative_to(self.rib_loader.data_dir)
                        )
                        break

                if file_path:
                    self.config_manager.set_baseline(
                        file_path=file_path, device_name=self.device_name
                    )
                    self.app.notify(
                        f"Baseline set: {self.selected_file}", severity="information"
                    )
                    self.app.pop_screen()
                else:
                    self.app.notify("Error: File not found", severity="error")

        elif event.button.id == "cancel-btn":
            self.app.pop_screen()
