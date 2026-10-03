"""Fireagent Host — Firecracker integration layer.

Provides real and mock Firecracker management, guest agent communication,
and a minimal guest image builder.
"""

from .firecracker_api import FirecrackerAPI, FirecrackerAPIError, FirecrackerNotReadyError
from .guest_channel import (
    GuestAgentChannel,
    InProcessChannel,
    SerialChannel,
    VsockChannel,
)
from .microvm import MicroVMInstance, MicroVMManager
from .mock_firecracker import MockFirecrackerProcess, MockFirecrackerServer

__all__ = [
    "FirecrackerAPI",
    "FirecrackerAPIError",
    "FirecrackerNotReadyError",
    "GuestAgentChannel",
    "InProcessChannel",
    "SerialChannel",
    "VsockChannel",
    "MicroVMInstance",
    "MicroVMManager",
    "MockFirecrackerProcess",
    "MockFirecrackerServer",
]