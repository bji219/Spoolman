"""Bambu Lab MQTT client integration for automatic filament tracking.

This module connects to Bambu Lab 3D printers via MQTT to automatically track
filament usage and update spool weights in real-time.

The client subscribes to the printer's report topic (device/<serial>/report) and
processes AMS (Automatic Material System) data to update corresponding spools.
"""

import asyncio
import json
import logging
import ssl
from typing import TYPE_CHECKING

import aiomqtt

from spoolman.database import spool as spool_db

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class BambuMQTTClient:
    """MQTT client for Bambu Lab printer integration.

    This client connects to a Bambu Lab printer's MQTT broker and listens for
    print status updates. It automatically updates Spoolman spool weights based
    on AMS filament consumption data.

    Attributes:
        host: MQTT broker hostname or IP address
        port: MQTT broker port (default 8883 for Bambu Lab)
        username: MQTT username (typically "bblp" for Bambu Lab)
        password: MQTT password (LAN-Only Mode access code)
        device_serial: Bambu Lab printer serial number
        tls_enabled: Whether to use TLS/SSL connection
        ams_mappings: Dict mapping AMS slot IDs to Spoolman spool IDs
        client: The aiomqtt client instance
        running: Flag indicating if the client is running

    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        device_serial: str,
        tls_enabled: bool,
        ams_mappings: dict[str, int],
    ) -> None:
        """Initialize the Bambu Lab MQTT client.

        Args:
            host: MQTT broker hostname or IP address
            port: MQTT broker port
            username: MQTT username
            password: MQTT password
            device_serial: Bambu Lab printer serial number
            tls_enabled: Whether to use TLS/SSL
            ams_mappings: Mapping of AMS slot to Spoolman spool ID

        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.device_serial = device_serial
        self.tls_enabled = tls_enabled
        self.ams_mappings = ams_mappings
        self.client: aiomqtt.Client | None = None
        self.running = False

        # Store last known remaining percentages to detect changes
        # Format: {slot_id: remaining_percentage}
        self._last_remaining: dict[str, float] = {}

        logger.info(
            "Initialized Bambu Lab MQTT client for device %s at %s:%d with %d AMS mappings",
            self.device_serial,
            self.host,
            self.port,
            len(self.ams_mappings),
        )

    def _create_tls_context(self) -> ssl.SSLContext:
        """Create an SSL context for TLS connection.

        Bambu Lab printers use self-signed certificates, so we need to disable
        certificate verification.

        Returns:
            ssl.SSLContext: Configured SSL context

        """
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    async def _process_ams_data(self, ams_data: list[dict], db: "AsyncSession") -> None:
        """Process AMS (Automatic Material System) data from MQTT message.

        Args:
            ams_data: List of AMS unit data from the printer
            db: Database session for updating spools

        """
        if not ams_data:
            return

        # Iterate through AMS units (typically just one, but printers can have multiple)
        for ams_unit in ams_data:
            if "tray" not in ams_unit:
                continue

            # Each AMS unit has 4 trays/slots (0-3)
            for tray in ams_unit["tray"]:
                if not isinstance(tray, dict):
                    continue

                # Get tray/slot ID (usually "0", "1", "2", "3")
                tray_id = str(tray.get("id", ""))

                # Check if this slot is mapped to a Spoolman spool
                if tray_id not in self.ams_mappings:
                    continue

                spool_id = self.ams_mappings[tray_id]

                # Get remaining filament data
                # Bambu provides "remain" as a percentage (0-100)
                remain_percent = tray.get("remain")
                if remain_percent is None:
                    continue

                # Convert to float
                try:
                    remain_percent = float(remain_percent)
                except (ValueError, TypeError):
                    logger.warning("Invalid remain percentage for tray %s: %s", tray_id, remain_percent)
                    continue

                # Check if the remaining percentage has changed
                last_remain = self._last_remaining.get(tray_id)
                if last_remain is not None and abs(remain_percent - last_remain) < 0.5:
                    # No significant change (less than 0.5%), skip update
                    continue

                # Update last known remaining percentage
                self._last_remaining[tray_id] = remain_percent

                # Get tray info to calculate actual remaining weight
                # Bambu also provides tray_weight (total weight in grams)
                tray_weight = tray.get("tray_weight")
                if tray_weight is None:
                    logger.warning("No tray_weight provided for tray %s, cannot update spool", tray_id)
                    continue

                try:
                    tray_weight = float(tray_weight)
                except (ValueError, TypeError):
                    logger.warning("Invalid tray_weight for tray %s: %s", tray_id, tray_weight)
                    continue

                # Calculate remaining weight in grams
                remaining_weight = (remain_percent / 100.0) * tray_weight

                logger.info(
                    "AMS slot %s (spool %d): %.1f%% remaining = %.2fg",
                    tray_id,
                    spool_id,
                    remain_percent,
                    remaining_weight,
                )

                # Update the spool in Spoolman
                try:
                    await spool_db.update(
                        db=db,
                        spool_id=spool_id,
                        data={"remaining_weight": remaining_weight},
                    )
                    logger.info("Updated spool %d remaining weight to %.2fg", spool_id, remaining_weight)
                except Exception:
                    logger.exception("Failed to update spool %d", spool_id)

    async def _process_message(self, message: aiomqtt.Message, db: "AsyncSession") -> None:
        """Process an incoming MQTT message from the printer.

        Args:
            message: MQTT message from the printer
            db: Database session for updating spools

        """
        try:
            # Parse JSON payload
            payload = json.loads(message.payload.decode())

            # Check if this is a print status message with AMS data
            if "print" not in payload:
                return

            print_data = payload["print"]

            # Look for AMS data
            ams_data = print_data.get("ams", {}).get("ams", [])
            if ams_data:
                await self._process_ams_data(ams_data, db)

        except json.JSONDecodeError:
            logger.warning("Failed to decode MQTT message as JSON")
        except Exception:
            logger.exception("Error processing MQTT message")

    async def run(self, db_session_factory) -> None:  # noqa: ANN001
        """Run the MQTT client main loop.

        This method connects to the MQTT broker, subscribes to the printer's
        report topic, and processes incoming messages. It automatically handles
        reconnection on connection loss.

        Args:
            db_session_factory: Factory function to create database sessions

        """
        self.running = True

        # Create TLS context if enabled
        tls_context = self._create_tls_context() if self.tls_enabled else None

        # MQTT topic to subscribe to
        topic = f"device/{self.device_serial}/report"

        logger.info("Starting Bambu Lab MQTT client...")
        logger.info("Connecting to %s:%d (TLS: %s)", self.host, self.port, self.tls_enabled)
        logger.info("Subscribing to topic: %s", topic)

        # Reconnection loop
        reconnect_delay = 5  # Start with 5 second delay
        max_reconnect_delay = 300  # Max 5 minutes

        while self.running:
            try:
                async with aiomqtt.Client(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    tls_context=tls_context,
                    timeout=10,
                ) as client:
                    self.client = client
                    logger.info("Connected to Bambu Lab printer MQTT broker")

                    # Reset reconnect delay on successful connection
                    reconnect_delay = 5

                    # Subscribe to the printer's report topic
                    await client.subscribe(topic)
                    logger.info("Subscribed to %s", topic)

                    # Process messages
                    async for message in client.messages:
                        if not self.running:
                            break

                        # Create a new database session for each message
                        async with db_session_factory() as db:
                            await self._process_message(message, db)

            except aiomqtt.MqttError as e:
                if not self.running:
                    break

                logger.error("MQTT connection error: %s", e)
                logger.info("Reconnecting in %d seconds...", reconnect_delay)
                await asyncio.sleep(reconnect_delay)

                # Exponential backoff for reconnection
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

            except Exception:
                if not self.running:
                    break

                logger.exception("Unexpected error in MQTT client")
                logger.info("Reconnecting in %d seconds...", reconnect_delay)
                await asyncio.sleep(reconnect_delay)

                # Exponential backoff for reconnection
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

        logger.info("Bambu Lab MQTT client stopped")

    async def stop(self) -> None:
        """Stop the MQTT client gracefully."""
        logger.info("Stopping Bambu Lab MQTT client...")
        self.running = False
        if self.client:
            # The client will disconnect when the context manager exits
            pass


async def create_and_run_client(
    host: str,
    port: int,
    username: str,
    password: str,
    device_serial: str,
    tls_enabled: bool,
    ams_mappings: dict[str, int],
    db_session_factory,  # noqa: ANN001
) -> BambuMQTTClient:
    """Create and run a Bambu Lab MQTT client.

    This is a convenience function to create and start a client in one call.

    Args:
        host: MQTT broker hostname or IP address
        port: MQTT broker port
        username: MQTT username
        password: MQTT password
        device_serial: Bambu Lab printer serial number
        tls_enabled: Whether to use TLS/SSL
        ams_mappings: Mapping of AMS slot to Spoolman spool ID
        db_session_factory: Factory function to create database sessions

    Returns:
        BambuMQTTClient: The running client instance

    """
    client = BambuMQTTClient(
        host=host,
        port=port,
        username=username,
        password=password,
        device_serial=device_serial,
        tls_enabled=tls_enabled,
        ams_mappings=ams_mappings,
    )

    # Run the client (this will block until stopped)
    await client.run(db_session_factory)

    return client
