"""
Connection Engine for Juniper devices using PyEZ.
Handles device connection establishment, validation, and management.
"""

import sys
import traceback
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

# Import logging config first
try:
    from backend.app.core.logging_config import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)

# Try to import PyEZ
try:
    from jnpr.junos import Device

    PYEZ_AVAILABLE = True
    logger.info("PyEZ library loaded successfully")
except ImportError as e:
    PYEZ_AVAILABLE = False
    logger.error(f"PyEZ library not available: {e}")
    logger.error("Install with: pip install junos-eznc")
    Device = None


class ConnectionState(Enum):
    """Connection state enumeration."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class ConnectionInfo:
    """Connection information container."""

    host: str
    user: str
    port: int
    connected: bool = False
    error_message: Optional[str] = None
    device_info: Optional[Dict[str, Any]] = None
    connection_time: Optional[datetime] = None


class ConnectionEngine:
    """
    Dedicated engine for managing Juniper device connections via PyEZ.

    Handles:
    - Connection establishment
    - Connection validation
    - Connection health checks
    - Connection state management
    """

    def __init__(
        self,
        host: str,
        user: str,
        password: Optional[str] = None,
        ssh_key: Optional[str] = None,
        port: int = 830,
        timeout: int = 30,
    ):
        """
        Initialize the connection engine.

        Args:
            host: Device hostname or IP address
            user: Username for authentication
            password: Password for authentication (optional if using SSH key)
            ssh_key: Path to SSH private key file (optional)
            port: NETCONF port (default: 830)
            timeout: Connection timeout in seconds (default: 30)
        """
        self.host = host
        self.user = user
        self.password = password
        self.ssh_key = ssh_key
        self.port = port
        self.timeout = timeout

        self._device: Optional[Any] = None
        self._state = ConnectionState.DISCONNECTED
        self._connection_info: Optional[ConnectionInfo] = None

        logger.debug(f"ConnectionEngine initialized for {host}:{port}")
        logger.debug(f"  User: {user}")
        logger.debug(f"  Auth method: {'SSH key' if ssh_key else 'password'}")
        logger.debug(f"  Timeout: {timeout}s")

    @property
    def state(self) -> ConnectionState:
        """Get current connection state."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """Check if device is connected."""
        return self._state == ConnectionState.CONNECTED and self._device is not None

    @property
    def device(self) -> Optional[Any]:
        """Get the underlying PyEZ Device object."""
        return self._device

    def connect(self) -> bool:
        """
        Establish connection to the Juniper device.

        Returns:
            True if connection successful, False otherwise
        """
        logger.info("=" * 60)
        logger.info(f"CONNECTION ATTEMPT: {self.host}:{self.port}")
        logger.info(f"Timestamp: {datetime.now()}")
        logger.info("=" * 60)

        if not PYEZ_AVAILABLE:
            error_msg = "PyEZ library not installed. Run: pip install junos-eznc"
            logger.error(error_msg)
            self._handle_connection_error(error_msg)
            return False

        if self.is_connected:
            logger.debug(f"Already connected to {self.host}")
            return True

        self._state = ConnectionState.CONNECTING
        logger.info("Connection state: CONNECTING")

        try:
            logger.info("Creating PyEZ Device instance...")

            # Log connection parameters (hide password)
            safe_params = {
                "host": self.host,
                "user": self.user,
                "port": self.port,
                "timeout": self.timeout,
                "password": "***" if self.password else None,
                "ssh_private_key_file": self.ssh_key,
            }
            logger.debug(f"Connection parameters: {safe_params}")

            # Create device instance
            device_params = {
                "host": self.host,
                "user": self.user,
                "port": self.port,
            }

            if self.password:
                device_params["password"] = self.password
            if self.ssh_key:
                device_params["ssh_private_key_file"] = self.ssh_key

            self._device = Device(**device_params)

            # Set timeout
            if hasattr(self._device, "timeout"):
                self._device.timeout = self.timeout

            logger.info("Opening connection...")
            logger.debug(f"Device object created: {type(self._device)}")

            # Open connection
            self._device.open()
            logger.info("Connection opened successfully!")

            # Validate connection
            logger.info("Validating connection...")
            if not self._validate_connection():
                error_msg = "Connection validation failed - device facts not accessible"
                logger.error(error_msg)
                self._handle_connection_error(error_msg)
                return False

            logger.info("Connection validated successfully!")

            # Gather device info
            logger.info("Gathering device information...")
            device_info = self._gather_device_info()

            # Update state
            self._state = ConnectionState.CONNECTED
            self._connection_info = ConnectionInfo(
                host=self.host,
                user=self.user,
                port=self.port,
                connected=True,
                device_info=device_info,
                connection_time=datetime.now(),
            )

            logger.info("=" * 60)
            logger.info("CONNECTION SUCCESSFUL!")
            logger.info(f"Host: {self.host}")
            if device_info:
                logger.info(f"Hostname: {device_info.get('hostname', 'N/A')}")
                logger.info(f"Model: {device_info.get('model', 'N/A')}")
                logger.info(f"Version: {device_info.get('version', 'N/A')}")
            logger.info("=" * 60)

            return True

        except Exception as e:
            error_msg = f"Connection failed: {str(e)}"
            logger.error("=" * 60)
            logger.error("CONNECTION FAILED!")
            logger.error(f"Error Type: {type(e).__name__}")
            logger.error(f"Error Message: {str(e)}")
            logger.error("Full Traceback:")
            logger.error(traceback.format_exc())
            logger.error("=" * 60)

            self._handle_connection_error(str(e))
            return False

    def _validate_connection(self) -> bool:
        """
        Validate that the connection is working properly.

        Returns:
            True if connection is valid, False otherwise
        """
        if not self._device:
            logger.warning("No device to validate")
            return False

        try:
            logger.debug("Attempting to retrieve device facts...")
            facts = self._device.facts

            if facts:
                logger.debug(f"Facts retrieved: {list(facts.keys())}")
                hostname = facts.get("hostname", "unknown")
                logger.info(f"Device hostname: {hostname}")
                return True

            logger.warning("No facts returned from device")
            return False

        except Exception as e:
            logger.error(f"Connection validation error: {e}")
            logger.debug(traceback.format_exc())
            return False

    def _gather_device_info(self) -> Dict[str, Any]:
        """
        Gather device information from connected device.

        Returns:
            Dictionary containing device information
        """
        info = {}

        if not self._device:
            return info

        try:
            logger.debug("Gathering device facts...")
            facts = self._device.facts

            if facts:
                info = {
                    "hostname": facts.get("hostname", "unknown"),
                    "model": facts.get("model", "unknown"),
                    "serial": facts.get("serialnumber", "unknown"),
                    "version": facts.get("version", "unknown"),
                    "platform": facts.get("platform", "unknown"),
                }
                logger.info(f"Device Info: {info}")
            else:
                logger.warning("No device facts available")

        except Exception as e:
            logger.warning(f"Could not gather device info: {e}")
            logger.debug(traceback.format_exc())

        return info

    def _handle_connection_error(self, error_message: str) -> None:
        """
        Handle connection error and cleanup.

        Args:
            error_message: Error message to log
        """
        logger.error(f"Handling connection error: {error_message}")

        self._state = ConnectionState.ERROR
        self._connection_info = ConnectionInfo(
            host=self.host,
            user=self.user,
            port=self.port,
            connected=False,
            error_message=error_message,
        )

        # Cleanup device
        if self._device:
            try:
                logger.debug("Attempting to close device connection...")
                self._device.close()
                logger.debug("Device connection closed")
            except Exception as e:
                logger.debug(f"Error closing device: {e}")
            finally:
                self._device = None

    def health_check(self) -> bool:
        """
        Perform a health check on the connection.

        Returns:
            True if connection is healthy, False otherwise
        """
        if not self.is_connected:
            return False

        try:
            logger.debug("Performing health check...")
            self._device.rpc.get_system_information()
            logger.debug("Health check passed")
            return True
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            self._state = ConnectionState.ERROR
            return False

    def get_connection_info(self) -> Optional[ConnectionInfo]:
        """
        Get current connection information.

        Returns:
            ConnectionInfo object or None if not connected
        """
        return self._connection_info

    def disconnect(self) -> bool:
        """
        Disconnect from the device.

        Returns:
            True if disconnection successful, False otherwise
        """
        logger.info(f"Disconnecting from {self.host}...")

        from backend.app.core.disconnect_engine import DisconnectEngine

        disconnect_engine = DisconnectEngine(self)
        return disconnect_engine.disconnect()
