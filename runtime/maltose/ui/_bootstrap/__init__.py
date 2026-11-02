"""Small, stdlib-only bridge installed once in each Agent framework."""
from .discovery import discover
from .wire import WireClient,MUPFailure
from .client import Bootstrap,SidecarClient
