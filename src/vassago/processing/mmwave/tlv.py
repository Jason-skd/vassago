"""Strict TLV decoding helpers for offline RD extraction."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vassago.processing.mmwave.uart_packets import UartTlv

RANGE_DOPPLER_HEATMAP_TLV_TYPE = 5
UINT16_SIZE_BYTES = 2


class TlvDecodeError(ValueError):
    """Raised when a known TLV payload cannot be decoded strictly."""


@dataclass(slots=True, frozen=True)
class DecodedRangeDopplerHeatmap:
    """Strictly decoded RD heatmap from TLV type 5."""

    tlv_type: int
    range_bin_count: int
    doppler_bin_count: int
    heatmap_u16: tuple[tuple[int, ...], ...]

    @property
    def shape(self) -> tuple[int, int]:
        """Return the canonical 2D RD shape."""
        return (self.range_bin_count, self.doppler_bin_count)


def decode_range_doppler_heatmap(
    tlv: UartTlv,
    *,
    range_bin_count: int,
    doppler_bin_count: int,
) -> DecodedRangeDopplerHeatmap:
    """Decode TLV type 5 as a little-endian uint16 RD heatmap."""
    expected_value_count = range_bin_count * doppler_bin_count
    expected_payload_length = expected_value_count * UINT16_SIZE_BYTES
    if tlv.payload_length != expected_payload_length:
        msg = (
            "Range-Doppler heatmap payload length does not match the "
            "configured shape: "
            f"{tlv.payload_length} != {expected_payload_length}"
        )
        raise TlvDecodeError(msg)

    flat_values = struct.unpack(f"<{expected_value_count}H", tlv.payload)
    heatmap = tuple(
        tuple(flat_values[row_start : row_start + doppler_bin_count])
        for row_start in range(0, expected_value_count, doppler_bin_count)
    )
    return DecodedRangeDopplerHeatmap(
        tlv_type=tlv.tlv_type,
        range_bin_count=range_bin_count,
        doppler_bin_count=doppler_bin_count,
        heatmap_u16=heatmap,
    )
