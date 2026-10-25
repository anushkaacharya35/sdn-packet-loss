"""Shared packet format for the sender and receiver."""
import struct

# type (1B) | retransmit flag (1B) | sequence number (4B) | send timestamp (8B)
HDR = struct.Struct("!BBId")
DATA, ACK, FIN = 1, 2, 3
PAYLOAD = b"x" * 100
CTRL_SOCK = "/tmp/sdn_ctrl.sock"   # receiver -> controller alert channel
