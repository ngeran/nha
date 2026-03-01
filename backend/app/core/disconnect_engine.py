"""
Disconnect Engine for Juniper devices using PyEZ.
Handles graceful device disconnection and cleanup.
"""

import traceback
from typing import Optional
from enum import Enum
from datetime import datetime

# Import logging config
try:
    from backend.app.core.logging_config import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)


class DisconnectResult(Enum):
    """Disconnect operation result."""

    SUCCESS = "success"
    NOT_CONNECTED = "not_connected"
    ERROR = "error"


class DisconnectEngine:
    """
    Dedicated engine for graceful Juniper device disconnection via PyEZ.

    Handles:
    - Graceful connection termination
    - Resource cleanup
    - Session management
    - Error recovery during disconnect
    """

    def __init__(self, connection_engine):
        """
        Initialize the disconnect engine.

        Args:
            connection_engine: ConnectionEngine instance to disconnect from
        """
        self._connection_engine = connection_engine
        logger.debug("DisconnectEngine initialized")

    def disconnect(self) -> bool:
        """
        Gracefully disconnect from the Juniper device.

        Returns:
            True if disconnection successful, False otherwise
        """
        result = self._perform_disconnect()
        return result == DisconnectResult.SUCCESS

    def _perform_disconnect(self) -> DisconnectResult:
        """
        Perform the actual disconnection process.

        Returns:
            DisconnectResult indicating the outcome
        """
        logger.info("=" * 60)
        logger.info("DISCONNECT OPERATION STARTED")
        logger.info(f"Timestamp: {datetime.now()}")
        logger.info("=" * 60)

        # Check if already disconnected
        if not self._connection_engine._device:
            logger.debug("No active connection to disconnect")
            self._connection_engine._state = ConnectionState.DISCONNECTED
            logger.info("Device already disconnected")
            return DisconnectResult.NOT_CONNECTED

        device = self._connection_engine._device
        host = self._connection_engine.host

        logger.info(f"Disconnecting from {host}...")

        try:
            # Attempt graceful shutdown
            logger.debug("Performing graceful shutdown...")
            self._graceful_shutdown(device)

            # Close the connection
            logger.debug("Closing device connection...")
            device.close()
            logger.info("Device connection closed")

            # Cleanup
            self._cleanup()

            logger.info("=" * 60)
            logger.info("DISCONNECT SUCCESSFUL")
            logger.info(f"Host: {host}")
            logger.info("=" * 60)

            return DisconnectResult.SUCCESS

        except Exception as e:
            logger.error("=" * 60)
            logger.error("DISCONNECT FAILED!")
            logger.error(f"Error Type: {type(e).__name__}")
            logger.error(f"Error Message: {str(e)}")
            logger.error("Full Traceback:")
            logger.error(traceback.format_exc())
            logger.error("=" * 60)

            # Force cleanup even on error
            self._force_cleanup()

            return DisconnectResult.ERROR

    def _graceful_shutdown(self, device) -> None:
        """
        Perform graceful shutdown operations before disconnecting.

        Args:
            device: PyEZ Device instance
        """
        try:
            # Commit any pending changes (if applicable)
            if hasattr(device, "cu") and device.cu:
                try:
                    device.cu.commit_check()
                    logger.debug("Commit check passed")
                except Exception as e:
                    logger.debug(f"Commit check (ignored): {e}")

            # Close any open configuration sessions
            if hasattr(device, "cu") and device.cu:
                try:
                    device.cu.rescue(action="none")
                except Exception as e:
                    logger.debug(f"Rescue check (ignored): {e}")

            logger.debug("Graceful shutdown completed")

        except Exception as e:
            logger.debug(f"Graceful shutdown warning: {e}")

    def _cleanup(self) -> None:
        """Clean up connection resources."""
        logger.debug("Cleaning up connection resources...")
        self._connection_engine._device = None
        self._connection_engine._state = self._get_disconnected_state()
        self._connection_engine._connection_info = None
        logger.debug("Cleanup completed")

    def _force_cleanup(self) -> None:
        """Force cleanup of connection resources after error."""
        logger.warning("Performing force cleanup")
        self._cleanup()

    def _get_disconnected_state(self):
        """Get the disconnected state enum."""
        try:
            from backend.app.core.connection_engine import ConnectionState

            return ConnectionState.DISCONNECTED
        except ImportError:
            return None

    def disconnect_with_timeout(self, timeout: int = 10) -> bool:
        """
        Disconnect with a timeout to prevent hanging.

        Args:
            timeout: Timeout in seconds for disconnect operation

        Returns:
            True if disconnection successful, False otherwise
        """
        import threading
        import time

        result = [None]

        def _disconnect_thread():
            result[0] = self.disconnect()

        thread = threading.Thread(target=_disconnect_thread)
        thread.daemon = True
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            logger.warning(f"Disconnect timed out after {timeout} seconds")
            self._force_cleanup()
            return False

        return result[0] if result[0] is not None else False

    def emergency_disconnect(self) -> bool:
        """
        Emergency disconnect - force cleanup without graceful shutdown.

        Use this when the application is crashing or needs immediate cleanup.

        Returns:
            True if cleanup successful
        """
        logger.warning("=" * 60)
        logger.warning("EMERGENCY DISCONNECT INITIATED")
        logger.warning("=" * 60)

        try:
            # Just close the socket if possible
            if self._connection_engine._device:
                try:
                    if hasattr(self._connection_engine._device, "_conn"):
                        self._connection_engine._device._conn.close()
                        logger.debug("Underlying connection closed")
                except Exception as e:
                    logger.debug(f"Error closing underlying connection: {e}")

            # Force cleanup
            self._force_cleanup()

            logger.info("Emergency disconnect completed")
            return True

        except Exception as e:
            logger.error(f"Emergency disconnect error: {e}")
            logger.error(traceback.format_exc())
            return False

    def is_disconnected(self) -> bool:
        """
        Check if the device is fully disconnected.

        Returns:
            True if disconnected, False otherwise
        """
        try:
            from backend.app.core.connection_engine import ConnectionState

            return (
                self._connection_engine._state == ConnectionState.DISCONNECTED
                or self._connection_engine._device is None
            )
        except ImportError:
            return self._connection_engine._device is None

    def verify_cleanup(self) -> bool:
        """
        Verify that all resources have been properly cleaned up.

        Returns:
            True if cleanup verified, False if resources remain
        """
        issues = []

        if self._connection_engine._device is not None:
            issues.append("Device reference still exists")

        try:
            from backend.app.core.connection_engine import ConnectionState

            if self._connection_engine._state != ConnectionState.DISCONNECTED:
                issues.append(f"Connection state is {self._connection_engine._state}")
        except ImportError:
            pass

        if self._connection_engine._connection_info is not None:
            if self._connection_engine._connection_info.connected:
                issues.append("Connection info indicates still connected")

        if issues:
            logger.warning(f"Cleanup verification failed: {', '.join(issues)}")
            return False

        logger.debug("Cleanup verification passed")
        return True
