"""
RIB Loader - Loads and manages routing table files from rib-data directory.
"""

import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class RIBFile:
    """Represents a routing table file."""

    name: str
    path: Path
    size: int
    modified: datetime
    format: str  # xml, json, yaml

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "size": self.size,
            "modified": self.modified.strftime("%Y-%m-%d %H:%M:%S"),
            "format": self.format,
        }


class RIBLoader:
    """
    Loads and manages routing table files from the rib-data directory.
    """

    SUPPORTED_FORMATS = {".xml", ".json", ".yaml", ".yml"}

    def __init__(self, data_dir: Optional[Path] = None):
        """
        Initialize the RIB loader.

        Args:
            data_dir: Path to the rib-data directory. Defaults to rib-data/ in project root.
        """
        if data_dir is None:
            # rib_loader.py is in shared/, so go up 1 level to project root
            self.data_dir = Path(__file__).parent.parent / "rib-data"
        else:
            self.data_dir = Path(data_dir)

        self._files: List[RIBFile] = []
        self._load_files()

    def _load_files(self) -> None:
        """Load all routing table files from the data directory."""
        self._files = []

        if not self.data_dir.exists():
            return

        for file_path in self.data_dir.iterdir():
            if (
                file_path.is_file()
                and file_path.suffix.lower() in self.SUPPORTED_FORMATS
            ):
                try:
                    stat = file_path.stat()
                    rib_file = RIBFile(
                        name=file_path.name,
                        path=file_path,
                        size=stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime),
                        format=file_path.suffix.lower().lstrip("."),
                    )
                    self._files.append(rib_file)
                except Exception:
                    pass

        self._files.sort(key=lambda f: f.modified, reverse=True)

    def refresh(self) -> None:
        """Refresh the file list."""
        self._load_files()

    def list_files(self) -> List[RIBFile]:
        """Get list of all routing table files, sorted by modification time (newest first)."""
        return self._files.copy()

    def get_file_count(self) -> int:
        """Get the total number of routing table files."""
        return len(self._files)

    def get_total_size(self) -> int:
        """Get the total size of all files in bytes."""
        return sum(f.size for f in self._files)

    def get_latest_file(self) -> Optional[RIBFile]:
        """Get the most recently modified file."""
        return self._files[0] if self._files else None

    def get_files_by_format(self, fmt: str) -> List[RIBFile]:
        """Get files filtered by format."""
        fmt = fmt.lower().lstrip(".")
        return [f for f in self._files if f.format == fmt]

    def get_formats_summary(self) -> Dict[str, int]:
        """Get count of files per format."""
        summary = {}
        for f in self._files:
            summary[f.format] = summary.get(f.format, 0) + 1
        return summary

    def format_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format."""
        size = float(size_bytes)
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def get_table_data(self) -> List[Dict[str, str]]:
        """
        Get file data formatted for table display.

        Returns:
            List of dicts with: name, format, size, modified
        """
        return [
            {
                "name": f.name,
                "format": f.format.upper(),
                "size": self.format_size(f.size),
                "modified": f.modified.strftime("%Y-%m-%d %H:%M"),
            }
            for f in self._files
        ]
