"""ESP32 Controller Service for managing devices over HTTPS.

This service communicates with ESP32 devices using HTTPS only.
"""

import logging
from typing import Dict, Any, Optional, List
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError

logger = logging.getLogger(__name__)


class ESP32Controller:
    """Service for controlling ESP32 devices over HTTPS."""
    
    def __init__(self, timeout: int = 10, retry_count: int = 3):
        """Initialize the ESP32 controller.
        
        Args:
            timeout: Request timeout in seconds
            retry_count: Number of retries for failed requests
        """
        self.timeout = timeout
        self.retry_count = retry_count
        self._session = requests.Session()
    
    def send_command(self, device_url: str, command: str, 
                     payload: Optional[Dict[str, Any]] = None,
                     verify_ssl: bool = False) -> Dict[str, Any]:
        """Send a command to an ESP32 device.
        
        Args:
            device_url: Base URL of the ESP32 device (e.g., https://192.168.1.100)
            command: Command endpoint (e.g., '/relay/on')
            payload: Optional JSON payload to send
            verify_ssl: Whether to verify SSL certificates (default False for self-signed)
            
        Returns:
            Response data as dictionary
            
        Raises:
            RequestException: If the request fails after all retries
        """
        url = f"{device_url.rstrip('/')}{command}"
        
        attempt = 0
        last_error = None
        
        while attempt < self.retry_count:
            try:
                logger.debug(f"Sending command to {url} (attempt {attempt + 1}/{self.retry_count})")
                
                response = self._session.post(
                    url,
                    json=payload,
                    timeout=self.timeout,
                    verify=verify_ssl
                )
                
                # Check if request was successful
                response.raise_for_status()
                
                try:
                    result = response.json()
                except ValueError:
                    result = {'raw_response': response.text}
                
                logger.info(f"Command '{command}' sent successfully to {device_url}")
                return {
                    'success': True,
                    'data': result,
                    'status_code': response.status_code
                }
                
            except Timeout as e:
                last_error = e
                logger.warning(f"Timeout connecting to {url}: {e}")
                
            except ConnectionError as e:
                last_error = e
                logger.warning(f"Connection error to {url}: {e}")
                
            except RequestException as e:
                last_error = e
                logger.error(f"Request error to {url}: {e}")
                # Don't retry on certain errors like 4xx
                if hasattr(e, 'response') and e.response is not None:
                    if 400 <= e.response.status_code < 500:
                        return {
                            'success': False,
                            'error': str(e),
                            'status_code': e.response.status_code
                        }
            
            attempt += 1
        
        # All retries exhausted
        error_msg = f"Failed to send command to {url} after {self.retry_count} attempts: {last_error}"
        logger.error(error_msg)
        return {
            'success': False,
            'error': str(last_error) if last_error else 'Unknown error'
        }
    
    def get_device_status(self, device_url: str, 
                          verify_ssl: bool = False) -> Dict[str, Any]:
        """Get the status of an ESP32 device.
        
        Args:
            device_url: Base URL of the ESP32 device
            verify_ssl: Whether to verify SSL certificates
            
        Returns:
            Device status data
        """
        return self.send_command(device_url, '/status', verify_ssl=verify_ssl)
    
    def control_relay(self, device_url: str, relay_id: int, 
                      state: bool, verify_ssl: bool = False) -> Dict[str, Any]:
        """Control a relay on an ESP32 device.
        
        Args:
            device_url: Base URL of the ESP32 device
            relay_id: ID of the relay to control
            state: True to turn on, False to turn off
            verify_ssl: Whether to verify SSL certificates
            
        Returns:
            Command result
        """
        payload = {'relay': relay_id, 'state': state}
        return self.send_command(device_url, '/relay', payload=payload, verify_ssl=verify_ssl)
    
    def read_sensor(self, device_url: str, sensor_type: str,
                    verify_ssl: bool = False) -> Dict[str, Any]:
        """Read a sensor value from an ESP32 device.
        
        Args:
            device_url: Base URL of the ESP32 device
            sensor_type: Type of sensor to read (e.g., 'temperature', 'humidity')
            verify_ssl: Whether to verify SSL certificates
            
        Returns:
            Sensor reading data
        """
        return self.send_command(device_url, f'/sensor/{sensor_type}', verify_ssl=verify_ssl)
    
    def restart_device(self, device_url: str, 
                       verify_ssl: bool = False) -> Dict[str, Any]:
        """Restart an ESP32 device.
        
        Args:
            device_url: Base URL of the ESP32 device
            verify_ssl: Whether to verify SSL certificates
            
        Returns:
            Command result
        """
        return self.send_command(device_url, '/restart', verify_ssl=verify_ssl)
    
    def close(self):
        """Close the session."""
        self._session.close()
        logger.debug("Session closed")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
