from typing import Optional
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Vertical
from textual.widgets import Static
from textual.binding import Binding


class RouteDetailScreen(ModalScreen[None]):
    """
    A modal screen showing detailed information about a route.
    """

    CSS_PATH = "../../styles/detail.tcss"

    BINDINGS = [
        Binding("escape", "dismiss", "Back", show=False),
    ]

    def __init__(self, route_data: dict):
        super().__init__()
        self.route_data = route_data

    def compose(self) -> ComposeResult:
        with Vertical(id="route-detail-container"):
            yield Static(
                f"Route Details: {self.route_data.get('prefix', 'Unknown')}",
                id="detail-title",
            )
            yield Static(self._format_route_info(), id="route-info")
            yield Static("ESC: Return to routing table", id="detail-footer")

    def _format_route_info(self) -> str:
        """Format route data for display."""
        # Debug: Print the raw data
        print(f"DEBUG: Route data received: {self.route_data}")

        lines = []

        lines.append("[bold]◉ Basic Information[/bold]")
        lines.append(
            f"  [bright_blue]┃[/bright_blue] Prefix:     {self.route_data.get('prefix', 'N/A')}"
        )
        lines.append(
            f"  [cyan]┃[/cyan] Table:      {self.route_data.get('table', 'N/A')}"
        )
        lines.append(
            f"  [bright_white]┃[/bright_white] Protocol:   {self.route_data.get('protocol', 'N/A')}"
        )
        lines.append(
            f"  [green]┃[/green] Next-Hop:   {self.route_data.get('next_hop', 'N/A')}"
        )
        lines.append(
            f"  [yellow]┃[/yellow] Age:        {self._format_age(self.route_data.get('age', 0))}"
        )
        lines.append("")

        attributes = self.route_data.get("attributes", {})
        print(f"DEBUG: Attributes: {attributes}")

        if attributes:
            lines.append("[bold]◉ Protocol Attributes[/bold]")
            proto = attributes.get("protocol", "Unknown")
            lines.append(f"  [bright_magenta]┃[/bright_magenta] Type: {proto}")

            if proto == "BGP":
                lines.append(
                    f"  [red]┃[/red] AS Path:     {attributes.get('as_path', 'N/A')}"
                )
                lines.append(
                    f"  [bright_red]┃[/bright_red] Local Pref:  {attributes.get('local_pref', 'N/A')}"
                )
                lines.append(
                    f"  [magenta]┃[/magenta] MED:         {attributes.get('med', 'N/A')}"
                )
                communities = attributes.get("communities", [])
                if communities:
                    lines.append(
                        f"  [purple]┃[/purple] Communities: {', '.join(communities)}"
                    )

            elif proto == "OSPF":
                lines.append(
                    f"  [blue]┃[/blue] Area ID:  {attributes.get('area_id', 'N/A')}"
                )
                lines.append(
                    f"  [bright_blue]┃[/bright_blue] Metric:   {attributes.get('metric', 'N/A')}"
                )

            elif proto == "Static":
                lines.append(
                    f"  [green]┃[/green] Preference: {attributes.get('preference', 'N/A')}"
                )
        else:
            lines.append("[bold]◉ Protocol Attributes[/bold]")
            lines.append("  [bright_magenta]┃[/bright_magenta] Type: N/A")
            lines.append("  ┃ No protocol data available")

        return "\n".join(lines)

    def _format_age(self, age: int) -> str:
        """Format age in seconds to human readable format."""
        if age < 60:
            return f"{age}s"
        elif age < 3600:
            return f"{age // 60}m {age % 60}s"
        elif age < 86400:
            h = age // 3600
            m = (age % 3600) // 60
            return f"{h}h {m}m"
        else:
            d = age // 86400
            h = (age % 86400) // 3600
            return f"{d}d {h}h"
