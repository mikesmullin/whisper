"""
IPC client for communicating with perception-voice server

Lightweight client to send requests and receive responses
from the perception-voice Unix domain socket.
"""

import json
import logging
import socket
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Message framing: 4-byte length prefix (big-endian) + JSON payload
HEADER_SIZE = 4
MAX_MESSAGE_SIZE = 1024 * 1024  # 1MB max message


class PerceptionVoiceClient:
    """Client for perception-voice server communication"""
    
    def __init__(self, socket_path: Path):
        """
        Initialize client
        
        Args:
            socket_path: Path to the perception-voice Unix socket
        """
        self.socket_path = socket_path
        self._uid = "whisper-keyboard"
    
    def is_server_running(self) -> bool:
        """Check if the perception-voice server is running"""
        return self.socket_path.exists()
    
    def _connect(self) -> socket.socket:
        """
        Create and connect a Unix domain socket
        
        Returns:
            Connected socket
        
        Raises:
            ConnectionError: If server is not running
        """
        if not self.socket_path.exists():
            raise ConnectionError(f"Server socket not found: {self.socket_path}")
        
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(self.socket_path))
        return sock
    
    def _send_message(self, sock: socket.socket, message: Dict[str, Any]) -> None:
        """
        Send a JSON message over the socket
        
        Args:
            sock: Connected socket
            message: Dictionary to send as JSON
        """
        payload = json.dumps(message).encode('utf-8')
        
        if len(payload) > MAX_MESSAGE_SIZE:
            raise ValueError(f"Message too large: {len(payload)} bytes")
        
        header = struct.pack('>I', len(payload))
        sock.sendall(header + payload)
    
    def _recv_exact(self, sock: socket.socket, size: int) -> Optional[bytes]:
        """
        Receive exactly `size` bytes from socket
        
        Args:
            sock: Connected socket
            size: Number of bytes to receive
            
        Returns:
            Received bytes, or None if connection closed
        """
        data = b''
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                return None
            data += chunk
        return data
    
    def _recv_message(self, sock: socket.socket) -> Optional[Dict[str, Any]]:
        """
        Receive a JSON message from the socket
        
        Args:
            sock: Connected socket
        
        Returns:
            Parsed message dictionary, or None if connection closed
        """
        header = self._recv_exact(sock, HEADER_SIZE)
        if not header:
            return None
        
        payload_size = struct.unpack('>I', header)[0]
        
        if payload_size > MAX_MESSAGE_SIZE:
            raise ValueError(f"Message too large: {payload_size} bytes")
        
        payload = self._recv_exact(sock, payload_size)
        if not payload:
            return None
        
        return json.loads(payload.decode('utf-8'))
    
    def set_read_marker(self) -> bool:
        """
        Set read marker to now
        
        Returns:
            True if successful, False otherwise
        """
        try:
            sock = self._connect()
        except ConnectionError as e:
            logger.error(f"Cannot connect to server: {e}")
            return False
        
        try:
            self._send_message(sock, {"command": "set", "uid": self._uid})
            response = self._recv_message(sock)
            
            if not response:
                logger.error("No response from server")
                return False
            
            if response.get("status") != "ok":
                logger.error(f"Server error: {response.get('message', 'unknown')}")
                return False
            
            logger.debug(f"Read marker set for {self._uid}")
            return True
        
        except Exception as e:
            logger.error(f"Communication error: {e}")
            return False
        finally:
            try:
                sock.close()
            except Exception:
                pass
    
    def get_transcriptions(self) -> List[Dict[str, str]]:
        """
        Get transcriptions since last read marker
        
        Returns:
            List of transcription dicts with 'ts' and 'text' keys
        """
        try:
            sock = self._connect()
        except ConnectionError as e:
            logger.error(f"Cannot connect to server: {e}")
            return []
        
        try:
            self._send_message(sock, {"command": "get", "uid": self._uid})
            response = self._recv_message(sock)
            
            if not response:
                logger.error("No response from server")
                return []
            
            if response.get("status") != "ok":
                logger.error(f"Server error: {response.get('message', 'unknown')}")
                return []
            
            # Parse JSONL text from response
            text = response.get("text", "")
            if not text:
                return []
            
            transcriptions = []
            for line in text.strip().split('\n'):
                if line:
                    try:
                        transcriptions.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSONL line: {line}")
            
            return transcriptions
        
        except Exception as e:
            logger.error(f"Communication error: {e}")
            return []
        finally:
            try:
                sock.close()
            except Exception:
                pass
