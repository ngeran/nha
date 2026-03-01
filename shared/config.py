"""
Configuration management for RIB Monitor
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict


@dataclass
class BaselineConfig:
    """Configuration for baseline routing table analysis"""

    file_path: str  # Relative path to baseline file
    device_name: str
    description: str = ""
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaselineConfig":
        return cls(**data)


@dataclass
class AppConfig:
    """Main application configuration"""

    baseline: Optional[BaselineConfig] = None
    data_dir: str = "rib-data"
    auto_refresh: bool = False
    refresh_interval: int = 300  # seconds

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        if "baseline" in data and data["baseline"] is not None:
            data["baseline"] = BaselineConfig.from_dict(data["baseline"])
        return cls(**data)


class ConfigManager:
    """Manages application configuration"""

    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            # Default to project root / config
            self.config_dir = Path(__file__).parent.parent / "config"
        else:
            self.config_dir = Path(config_dir)

        self.config_file = self.config_dir / "config.json"
        self.baseline_file = self.config_dir / "baseline.json"

    def load_config(self) -> AppConfig:
        """Load application configuration"""
        if not self.config_file.exists():
            # Create default config
            config = AppConfig()
            self.save_config(config)
            return config

        try:
            with open(self.config_file, "r") as f:
                data = json.load(f)
            return AppConfig.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error loading config: {e}")
            return AppConfig()

    def save_config(self, config: AppConfig) -> None:
        """Save application configuration"""
        self.config_dir.mkdir(exist_ok=True)

        with open(self.config_file, "w") as f:
            json.dump(config.to_dict(), f, indent=2)

    def load_baseline_config(self) -> Optional[BaselineConfig]:
        """Load baseline configuration"""
        if not self.baseline_file.exists():
            return None

        try:
            with open(self.baseline_file, "r") as f:
                data = json.load(f)
            return BaselineConfig.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error loading baseline config: {e}")
            return None

    def save_baseline_config(self, baseline: BaselineConfig) -> None:
        """Save baseline configuration"""
        self.config_dir.mkdir(exist_ok=True)

        with open(self.baseline_file, "w") as f:
            json.dump(baseline.to_dict(), f, indent=2)

    def get_baseline_path(self) -> Optional[Path]:
        """Get the full path to the baseline file"""
        baseline_config = self.load_baseline_config()
        if baseline_config:
            # Resolve relative path from project root
            project_root = Path(__file__).parent.parent
            return project_root / baseline_config.file_path
        return None

    def set_baseline(
        self, file_path: str, device_name: str, description: str = ""
    ) -> None:
        """Set the baseline configuration"""
        created_at = ""
        if os.path.exists(file_path):
            from datetime import datetime

            timestamp = os.path.getmtime(file_path)
            created_at = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

        baseline = BaselineConfig(
            file_path=file_path,
            device_name=device_name,
            description=description,
            created_at=created_at,
        )
        self.save_baseline_config(baseline)

        # Update main config
        config = self.load_config()
        config.baseline = baseline
        self.save_config(config)
