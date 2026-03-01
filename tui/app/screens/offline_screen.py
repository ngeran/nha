"""
Offline Mode Screen - Displayed when backend is not available.
"""

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Vertical
from textual.widgets import Label, Footer, Button


class OfflineModeScreen(ModalScreen[None]):
    """
    Modal screen shown when user tries to connect but backend is not running.
    """

    CSS_PATH = "../../styles/connect.tcss"

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("enter", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-form"):
            yield Label("OFFLINE MODE", id="connect-title")

            yield Label("")
            yield Label("[yellow]The backend service is not running.[/yellow]")
            yield Label("")
            yield Label("[dim]You cannot connect to live devices.[/dim]")
            yield Label("[dim]The app is running in offline analysis mode.[/dim]")
            yield Label("")
            yield Label("[bold cyan]Available offline features:[/bold cyan]")
            yield Label("  • Import routing table files")
            yield Label("  • Analyze routes with smart filters")
            yield Label("  • Compare routing tables")
            yield Label("  • Export analysis results")
            yield Label("")
            yield Label("[dim]To connect to devices, start the backend:[/dim]")
            yield Label("[green]  docker compose up -d backend[/green]")
            yield Label("")
            yield Button("Continue Offline", id="btn-cancel")

        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)

    def action_dismiss(self) -> None:
        self.dismiss(None)
