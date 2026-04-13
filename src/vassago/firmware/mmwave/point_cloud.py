"""Point-cloud decoding helpers built on top of mmWave packet parsing."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vassago.firmware.mmwave.protocol import MmwavePacket
from vassago.firmware.mmwave.protocol import MmwavePacketParser
from vassago.firmware.mmwave.protocol import MmwaveTlv

if TYPE_CHECKING:
    from collections.abc import Iterable

POINT_CLOUD_TLV_TYPE = 1
POINT_CLOUD_POINT_FORMAT = "<4f"
POINT_CLOUD_POINT_SIZE = struct.calcsize(POINT_CLOUD_POINT_FORMAT)


@dataclass(slots=True, frozen=True)
class PointCloudPoint:
    """One decoded point-cloud point."""

    x: float
    y: float
    z: float
    velocity: float


@dataclass(slots=True, frozen=True)
class PointCloudFrame:
    """One decoded point-cloud frame derived from a mmWave packet."""

    frame_number: int
    sub_frame_number: int
    time_cpu_cycles: int
    points: tuple[PointCloudPoint, ...]

    @property
    def point_count(self) -> int:
        """Return the number of decoded points."""
        return len(self.points)


class PointCloudStreamDecoder:
    """Decode point-cloud frames directly from a raw mmWave byte stream."""

    def __init__(
        self,
        *,
        packet_parser: MmwavePacketParser | None = None,
        point_cloud_tlv_type: int = POINT_CLOUD_TLV_TYPE,
    ) -> None:
        """Initialize the decoder with an optional shared packet parser."""
        self._packet_parser = packet_parser or MmwavePacketParser()
        self._point_cloud_tlv_type = point_cloud_tlv_type

    @property
    def buffered_byte_count(self) -> int:
        """Return the buffered byte count held by the shared packet parser."""
        return self._packet_parser.buffered_byte_count

    @property
    def invalid_packet_count(self) -> int:
        """Return the invalid packet count observed by the shared parser."""
        return self._packet_parser.invalid_packet_count

    def feed(self, data: bytes) -> list[PointCloudFrame]:
        """Decode any point-cloud frames found in the streamed bytes."""
        return list(
            iter_point_cloud_frames(
                self._packet_parser.feed(data),
                point_cloud_tlv_type=self._point_cloud_tlv_type,
            )
        )


def decode_point_cloud_tlv(
    tlv: MmwaveTlv,
    *,
    point_cloud_tlv_type: int = POINT_CLOUD_TLV_TYPE,
) -> tuple[PointCloudPoint, ...]:
    """Decode one point-cloud TLV payload into semantic points."""
    if tlv.tlv_type != point_cloud_tlv_type:
        msg = (
            f"Expected point-cloud TLV type {point_cloud_tlv_type}, got {tlv.tlv_type}."
        )
        raise ValueError(msg)
    if tlv.payload_length % POINT_CLOUD_POINT_SIZE != 0:
        msg = (
            "Point-cloud TLV payload length must be a multiple of "
            f"{POINT_CLOUD_POINT_SIZE}, got {tlv.payload_length}."
        )
        raise ValueError(msg)

    return tuple(
        PointCloudPoint(*values)
        for values in struct.iter_unpack(POINT_CLOUD_POINT_FORMAT, tlv.payload)
    )


def extract_point_cloud_frame(
    packet: MmwavePacket,
    *,
    point_cloud_tlv_type: int = POINT_CLOUD_TLV_TYPE,
) -> PointCloudFrame | None:
    """Return the first decoded point-cloud frame found in one packet."""
    for tlv in packet.tlvs:
        if tlv.tlv_type != point_cloud_tlv_type:
            continue
        return PointCloudFrame(
            frame_number=packet.frame_number,
            sub_frame_number=packet.sub_frame_number,
            time_cpu_cycles=packet.time_cpu_cycles,
            points=decode_point_cloud_tlv(
                tlv,
                point_cloud_tlv_type=point_cloud_tlv_type,
            ),
        )

    return None


def iter_point_cloud_frames(
    packets: Iterable[MmwavePacket],
    *,
    point_cloud_tlv_type: int = POINT_CLOUD_TLV_TYPE,
) -> tuple[PointCloudFrame, ...]:
    """Decode point-cloud frames from an iterable of parsed packets."""
    return tuple(
        frame
        for packet in packets
        if (
            frame := extract_point_cloud_frame(
                packet,
                point_cloud_tlv_type=point_cloud_tlv_type,
            )
        )
        is not None
    )
