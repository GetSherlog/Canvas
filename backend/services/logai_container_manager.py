"""
LogAI MCP Container Manager - Manages Docker containers for LogAI MCP SSE servers
"""

import asyncio
import logging
import docker
import aiohttp
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
import time

logger = logging.getLogger(__name__)


@dataclass
class ContainerInfo:
    """Information about a running LogAI MCP container"""
    container_id: str
    name: str
    port: int
    sse_url: str
    notebook_id: str
    config: Dict[str, Any]
    started_at: float


class LogAIContainerManager:
    """Manages LogAI MCP Docker containers"""
    
    def __init__(self):
        self.docker_client = docker.from_env()
        self.containers: Dict[str, ContainerInfo] = {}
        self._next_port = 8200  # Starting port for SSE servers
        self._port_lock = asyncio.Lock()
        
    async def _get_next_port(self) -> int:
        """Get the next available port for SSE server"""
        async with self._port_lock:
            port = self._next_port
            self._next_port += 1
            return port
    
    async def start_container(self, notebook_id: str, config: Dict[str, Any]) -> ContainerInfo:
        """Start a LogAI MCP container for a notebook"""
        
        # Check if container already exists in memory
        if notebook_id in self.containers:
            logger.info(f"Container already exists in memory for notebook {notebook_id}")
            return self.containers[notebook_id]
        
        # Check if container already exists in Docker
        container_name = f"logai-mcp-{notebook_id}"
        try:
            existing_container = self.docker_client.containers.get(container_name)
            if existing_container.status == 'running':
                logger.info(f"Found existing running container {container_name}")
                # Get the port from the container
                port_bindings = existing_container.attrs['NetworkSettings']['Ports']
                port = None
                if '8000/tcp' in port_bindings and port_bindings['8000/tcp']:
                    port = int(port_bindings['8000/tcp'][0]['HostPort'])
                
                if port:
                    # Recreate container info and add to memory
                    container_info = ContainerInfo(
                        container_id=existing_container.id,
                        name=container_name,
                        port=port,
                        sse_url=f"http://localhost:{port}/sse",
                        notebook_id=notebook_id,
                        config=config,
                        started_at=time.time()
                    )
                    self.containers[notebook_id] = container_info
                    return container_info
        except docker.errors.NotFound:
            logger.info(f"No existing container found for {container_name}")
        except Exception as e:
            logger.warning(f"Error checking for existing container: {e}")
        
        try:
            # Get configuration
            github_token = config.get('github_token', '')
            filesystem_paths = config.get('filesystem_paths', [])
            # Use /app as working dir - this is where the LogAI MCP code is located in the container
            working_dir = '/app'  # Ignore config value, always use /app
            extra_args = config.get('extra_args', '')
            
            # Get next available port
            port = await self._get_next_port()
            
            # Build docker command
            container_name = f"logai-mcp-{notebook_id}"
            
            # Environment variables
            environment = {}
            if github_token:
                environment['GITHUB_PAT_TOKEN'] = github_token
                
            # Volume mounts
            volumes = {
                '/var/run/docker.sock': {
                    'bind': '/var/run/docker.sock',
                    'mode': 'rw'
                }
            }
            
            # Add filesystem path mounts
            for path in filesystem_paths:
                if path.strip():
                    volumes[path] = {
                        'bind': path,
                        'mode': 'ro'
                    }
            
            # Parse extra args if provided
            extra_docker_args = {}
            if extra_args:
                # Parse extra args (simple key=value format)
                for arg in extra_args.split():
                    if '=' in arg:
                        key, value = arg.split('=', 1)
                        if key.startswith('--'):
                            key = key[2:]
                        extra_docker_args[key] = value
            
            # Get image from settings
            from backend.config import get_settings
            settings = get_settings()
            image = settings.logai_mcp_image
            
            logger.info(f"Starting LogAI MCP container {container_name} on port {port}")
            
            # Run container
            container = self.docker_client.containers.run(
                image=image,
                name=container_name,
                detach=True,
                remove=False,
                stdin_open=True,
                tty=False,
                environment=environment,
                volumes=volumes,
                ports={'8000/tcp': port},  # Map container's SSE port to host
                working_dir=working_dir,
                **extra_docker_args
            )
            
            # Wait for container to be ready
            await self._wait_for_container_ready(container, port)
            
            # Store container info
            container_info = ContainerInfo(
                container_id=container.id,
                name=container_name,
                port=port,
                sse_url=f"http://localhost:{port}/sse",
                notebook_id=notebook_id,
                config=config,
                started_at=time.time()
            )
            
            self.containers[notebook_id] = container_info
            logger.info(f"LogAI MCP container {container_name} started successfully on port {port}")
            
            return container_info
            
        except Exception as e:
            logger.error(f"Failed to start LogAI MCP container for notebook {notebook_id}: {e}", exc_info=True)
            raise
    
    async def _wait_for_container_ready(self, container, port: int, timeout: int = 30):
        """Wait for container's SSE endpoint to be ready"""
        start_time = time.time()
        url = f"http://localhost:{port}/health"  # Assuming there's a health endpoint
        
        async with aiohttp.ClientSession() as session:
            while time.time() - start_time < timeout:
                try:
                    # Check container is still running
                    container.reload()
                    if container.status != 'running':
                        raise RuntimeError(f"Container exited with status: {container.status}")
                    
                    # Try to connect to health endpoint
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as response:
                        if response.status == 200:
                            logger.info(f"Container SSE endpoint ready on port {port}")
                            return
                            
                except aiohttp.ClientError:
                    # Connection failed, wait and retry
                    await asyncio.sleep(0.5)
                except docker.errors.NotFound:
                    raise RuntimeError("Container was removed while waiting for it to be ready")
        
        raise TimeoutError(f"Container SSE endpoint did not become ready within {timeout} seconds")
    
    async def stop_container(self, notebook_id: str) -> bool:
        """Stop and remove a LogAI MCP container"""
        
        if notebook_id not in self.containers:
            logger.warning(f"No container found for notebook {notebook_id}")
            return False
        
        container_info = self.containers[notebook_id]
        
        try:
            container = self.docker_client.containers.get(container_info.container_id)
            
            logger.info(f"Stopping container {container_info.name}")
            container.stop(timeout=10)
            
            logger.info(f"Removing container {container_info.name}")
            container.remove()
            
            del self.containers[notebook_id]
            
            logger.info(f"Container {container_info.name} stopped and removed successfully")
            return True
            
        except docker.errors.NotFound:
            logger.warning(f"Container {container_info.name} not found, removing from tracking")
            del self.containers[notebook_id]
            return True
        except Exception as e:
            logger.error(f"Failed to stop container for notebook {notebook_id}: {e}", exc_info=True)
            return False
    
    async def get_container_info(self, notebook_id: str) -> Optional[ContainerInfo]:
        """Get information about a running container"""
        return self.containers.get(notebook_id)
    
    async def list_containers(self) -> List[ContainerInfo]:
        """List all managed containers"""
        return list(self.containers.values())
    
    async def cleanup_all(self):
        """Stop and remove all managed containers"""
        logger.info("Cleaning up all LogAI MCP containers")
        
        notebook_ids = list(self.containers.keys())
        for notebook_id in notebook_ids:
            await self.stop_container(notebook_id)
    
    def get_sse_client_params(self, notebook_id: str) -> Optional[Dict[str, Any]]:
        """Get SSE client connection parameters for a notebook"""
        
        container_info = self.containers.get(notebook_id)
        if not container_info:
            return None
        
        return {
            'sse_url': container_info.sse_url,
            'headers': {
                'Accept': 'text/event-stream',
                'Cache-Control': 'no-cache'
            }
        }


# Global instance
_container_manager: Optional[LogAIContainerManager] = None


def get_container_manager() -> LogAIContainerManager:
    """Get the global container manager instance"""
    global _container_manager
    if _container_manager is None:
        _container_manager = LogAIContainerManager()
    return _container_manager