from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Vertical, Grid
from textual.widgets import Header, Footer, Input, Button, Label, Static
from textual.reactive import reactive

from shared.schemas import ConnectionConfig


class ConnectionScreen(ModalScreen[ConnectionConfig]):
    """
    A modal screen for entering router connection details.
    """

    CSS_PATH = "../../styles/connect.tcss"

    BINDINGS = [
        ("escape", "dismiss", "Back"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-form"):
            yield Label("RIB ANALYZE", id="connect-title")
            yield Label("Router Hostname / IP")
            yield Input(placeholder="e.g. 192.168.1.1", id="host")
            yield Label("Username")
            yield Input(placeholder="admin", id="user")
            yield Label("Password")
            yield Input(placeholder="password", password=True, id="password")
            yield Button("Connect", id="btn-connect")
        yield Footer()

    def action_dismiss(self) -> None:
        """Dismiss the screen."""
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-connect":
            host = self.query_one("#host", Input).value
            user = self.query_one("#user", Input).value
            password = self.query_one("#password", Input).value

            if host and user and password:
                config = ConnectionConfig(host=host, user=user, password=password)
                self.dismiss(config)
            else:
                # Basic validation
                self.notify("Please fill in all fields", severity="error")
