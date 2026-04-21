"""Serial-port discovery helpers for mmWave workflows."""

from __future__ import annotations

from dataclasses import dataclass

from serial.tools import list_ports

type PhysicalDeviceKey = tuple[int | None, int | None, str | None, str | None]


@dataclass(slots=True, frozen=True)
class SerialPortInfo:
    """Human-readable details for one visible serial port."""

    device: str
    description: str
    manufacturer: str | None
    product: str | None = None
    serial_number: str | None = None
    location: str | None = None
    vid: int | None = None
    pid: int | None = None

    @property
    def search_blob(self) -> str:
        """Return one normalized string used for candidate matching."""
        manufacturer = self.manufacturer or ""
        product = self.product or ""
        return f"{self.description} {manufacturer} {product}".lower()

    @property
    def physical_device_key(
        self,
    ) -> PhysicalDeviceKey | None:
        """Return a stable USB identity when the host exposes one."""
        if (
            self.vid is None
            and self.pid is None
            and self.serial_number is None
            and self.location is None
        ):
            return None
        return (self.vid, self.pid, self.serial_number, self.location)


def list_serial_ports() -> list[SerialPortInfo]:
    """Return visible serial ports in a stable order."""
    return sorted(
        [
            SerialPortInfo(
                device=port.device,
                description=port.description or "unknown",
                manufacturer=port.manufacturer,
                product=getattr(port, "product", None),
                serial_number=getattr(port, "serial_number", None),
                location=getattr(port, "location", None),
                vid=getattr(port, "vid", None),
                pid=getattr(port, "pid", None),
            )
            for port in list_ports.comports()
        ],
        key=lambda port: port.device,
    )


def list_candidate_mmwave_ports(
    port_infos: list[SerialPortInfo] | None = None,
) -> list[SerialPortInfo]:
    """Return ports that look like likely mmWave UART candidates."""
    infos = port_infos if port_infos is not None else list_serial_ports()
    return [port for port in infos if _looks_like_mmwave_candidate(port)]


def _looks_like_mmwave_candidate(port: SerialPortInfo) -> bool:
    """Return whether a visible port looks like a radar bring-up candidate."""
    search_blob = port.search_blob
    markers = (
        "cp210",
        "silicon labs",
        "usb serial",
        "usb-to-uart",
        "slab_usb",
    )
    return any(marker in search_blob for marker in markers)
