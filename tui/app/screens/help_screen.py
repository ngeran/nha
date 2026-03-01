"""
Help Screen - Display keyboard shortcuts and navigation help.
"""

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.widgets import Label, Footer


class HelpScreen(ModalScreen[None]):
    """
    Modal screen displaying help and keyboard shortcuts.
    """

    CSS_PATH = "../../styles/connect.tcss"

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-form"):
            yield Label("HELP - KEYBOARD SHORTCUTS", id="connect-title")

            with ScrollableContainer(id="help-content"):
                with Horizontal(classes="help-columns"):
                    with Vertical(classes="help-column"):
                        yield Label("[bold cyan]MAIN NAVIGATION[/bold cyan]")
                        yield Label("c      Connect to a device")
                        yield Label("d      Disconnect from device")
                        yield Label("x      Compare routing tables")
                        yield Label("i      Import routing table file")
                        yield Label("e      Export routes to file")
                        yield Label("r      Refresh file list")
                        yield Label("h      Show this help")
                        yield Label("q      Quit application")
                        yield Label("")
                        yield Label("[bold cyan]FILE VIEWER[/bold cyan]")
                        yield Label("Enter  Open selected file")
                        yield Label("f      Focus filter input")
                        yield Label("r      Reset all filters")
                        yield Label("Esc    Back to file list")
                        yield Label("")
                        yield Label("[bold yellow]OFFLINE MODE[/bold yellow]")
                        yield Label("[dim]When WS shows Disconnected:[/dim]")
                        yield Label("[dim]• Cannot connect to devices[/dim]")
                        yield Label("[dim]• Import files for analysis[/dim]")
                        yield Label("[dim]• Compare imported files[/dim]")
                        yield Label("[dim]• Start backend with:[/dim]")
                        yield Label("[green]  docker compose up -d[/green]")

                    with Vertical(classes="help-column"):
                        yield Label("[bold cyan]ANALYSIS CHIPS (2 rows)[/bold cyan]")
                        yield Label("")
                        yield Label("[dim]Row 1 - BGP/AS/Peers:[/dim]")
                        yield Label("BGP - BGP route count")
                        yield Label("Oxxxx:n - Origin AS")
                        yield Label("Txxxx:n - Transit AS")
                        yield Label("Pxxx:n - Peer/neighbor")
                        yield Label("Self - Self-originated")
                        yield Label("")
                        yield Label("[dim]Row 2 - Attributes/Age:[/dim]")
                        yield Label("LP - Non-default Local-Pref")
                        yield Label("MED - Non-default MED")
                        yield Label("Comm - Routes w/ communities")
                        yield Label("Prep - AS path prepending")
                        yield Label("New - Routes < 1 hour old")
                        yield Label("Stable - Routes > 1 day old")
                        yield Label("Spec - Specific /28-/32")
                        yield Label("Agg - Aggregate /8-/16")
                        yield Label("Priv - RFC1918 private")
                        yield Label("Bogon - Invalid ranges")
                        yield Label("NoDef - No default route")
                        yield Label("")
                        yield Label("[bold cyan]COMPARE SCREEN[/bold cyan]")
                        yield Label("c      Run comparison")
                        yield Label("r      Reset all filters")
                        yield Label("Esc    Back to main")
                        yield Label("")
                        yield Label("[bold cyan]STATUS BAR ICONS[/bold cyan]")
                        yield Label("○ / ⚙    WebSocket status")
                        yield Label("⇋        Device count")
                        yield Label("◎        Connected hosts")
                        yield Label("Mode     Online/Offline")
                        yield Label("")
                        yield Label("[bold cyan]COLORS[/bold cyan]")
                        yield Label("Green    Connected / Active")
                        yield Label("Red      Disconnected")
                        yield Label("Orange   Device count")
                        yield Label("Yellow   Offline mode")
                        yield Label("")
                        yield Label("[dim]Press ESC or q to close[/dim]")

        yield Footer()

    def action_dismiss(self) -> None:
        """Dismiss the help screen."""
        self.dismiss(None)
