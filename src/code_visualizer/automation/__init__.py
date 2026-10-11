"""Authenticated local automation transports over the semantic authority."""

from code_visualizer.automation.host import LocalAutomationHost
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationService,
)
from code_visualizer.automation.websocket import AccessGrant, AutomationWebSocketServer

__all__ = [
    "AccessGrant",
    "AccessMode",
    "AutomationCapability",
    "AutomationService",
    "AutomationWebSocketServer",
    "LocalAutomationHost",
]
