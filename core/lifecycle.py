"""
Lifecycle Manager - Handles startup, shutdown, and component initialization
"""

import logging
import signal
import sys
from typing import List, Callable

from core.runtime import runtime
from core.event_bus import event_bus

logger = logging.getLogger(__name__)


class LifecycleManager:
    """Manages application lifecycle"""
    
    def __init__(self):
        self._startup_hooks: List[Callable] = []
        self._shutdown_hooks: List[Callable] = []
        self._initialized = False
    
    def add_startup_hook(self, hook: Callable, priority: int = 0):
        """Add startup hook"""
        self._startup_hooks.append((priority, hook))
        self._startup_hooks.sort(key=lambda x: x[0])
    
    def add_shutdown_hook(self, hook: Callable, priority: int = 0):
        """Add shutdown hook"""
        self._shutdown_hooks.append((priority, hook))
        self._shutdown_hooks.sort(key=lambda x: x[0], reverse=True)
    
    def startup(self):
        """Run startup sequence"""
        if self._initialized:
            return
        
        logger.info("JARVIS starting up...")
        event_bus.publish('system.startup', {}, source='lifecycle')
        
        # Run startup hooks
        for priority, hook in self._startup_hooks:
            try:
                hook()
                logger.debug(f"Startup hook completed: {hook.__name__}")
            except Exception as e:
                logger.error(f"Startup hook failed {hook.__name__}: {e}")
        
        # Start runtime
        runtime.start()
        
        self._initialized = True
        logger.info("JARVIS startup complete")
        event_bus.publish('system.ready', {}, source='lifecycle')
    
    def shutdown(self):
        """Run shutdown sequence"""
        if not self._initialized:
            return
        
        logger.info("JARVIS shutting down...")
        event_bus.publish('system.shutdown', {}, source='lifecycle')
        
        # Stop runtime first
        runtime.stop()
        
        # Run shutdown hooks
        for priority, hook in self._shutdown_hooks:
            try:
                hook()
                logger.debug(f"Shutdown hook completed: {hook.__name__}")
            except Exception as e:
                logger.error(f"Shutdown hook failed {hook.__name__}: {e}")
        
        self._initialized = False
        logger.info("JARVIS shutdown complete")
    
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, shutting down...")
            self.shutdown()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


# Global lifecycle manager instance
lifecycle = LifecycleManager()
