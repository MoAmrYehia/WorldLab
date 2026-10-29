"""Minimal PNG encoder (stdlib zlib only) so the simulator needs no imaging library."""
from __future__ import annotations

import struct
import zlib

import numpy as np


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def encode_png(img: np.ndarray) -> bytes:
    """img: (H, W, 3) uint8 RGB."""
    h, w, _ = img.shape
    raw = np.concatenate([np.zeros((h, 1), np.uint8), img.reshape(h, w * 3)], axis=1).tobytes()
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 6))
            + _chunk(b"IEND", b""))
