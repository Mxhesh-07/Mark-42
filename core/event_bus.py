"""
Event Bus - Central communication system for JARVIS
All components communicate through events, decoupling modules from each other
"""

import asyncio
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Base event structure"""
    type: str
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: f"evt_{int(time.time()*1000000)}")


class EventBus:
    """Thread-safe event bus with sync and async support"""
    
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._async_subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._lock = threading.RLock()
        self._event_history: List[Event] = []
        self._max_history = 1000
        self._loop = None
    
    def set_event_loop(self, loop):
        """Set asyncio event loop for async handlers"""
        self._loop = loop
    
    def subscribe(self, event_type: str, handler: Callable, async_handler: bool = False):
        """Subscribe to an event type"""
        with self._lock:
            if async_handler:
                self._async_subscribers[event_type].append(handler)
            else:
                self._subscribers[event_type].append(handler)
        logger.debug(f"Subscribed {handler.__name__} to {event_type}")
    
    def unsubscribe(self, event_type: str, handler: Callable, async_handler: bool = False):
        """Unsubscribe from an event type"""
        with self._lock:
            try:
                if async_handler:
                    self._async_subscribers[event_type].remove(handler)
                else:
                    self._subscribers[event_type].remove(handler)
            except ValueError:
                pass
    
    def publish(self, event_type: str, data: Dict[str, Any] = None, source: str = "system"):
        """Publish an event (synchronous)"""
        if data is None:
            data = {}
        
        event = Event(type=event_type, data=data, source=source)
        
        with self._lock:
            # Store in history
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)
        
        # Call sync subscribers
        subscribers = []
        with self._lock:
            subscribers = list(self._subscribers.get(event_type, []))
            async_subs = list(self._async_subscribers.get(event_type, []))
        
        # Sync handlers
        for handler in subscribers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Error in sync handler {handler.__name__} for {event_type}: {e}")
        
        # Async handlers
        if async_subs and self._loop and self._loop.is_running():
            for handler in async_subs:
                try:
                    asyncio.run_coroutine_threadsafe(handler(event), self._loop)
                except Exception as e:
                    logger.error(f"Error scheduling async handler {handler.__name__} for {event_type}: {e}")
        elif async_subs:
            # If no loop running, try to run in thread
            for handler in async_subs:
                try:
                    threading.Thread(target=lambda h=handler, e=event: asyncio.run(h(e)), daemon=True).start()
                except Exception as e:
                    logger.error(f"Error in async handler {handler.__name__} for {event_type}: {e}")
        
        logger.debug(f"Published event {event_type} from {source}")
    
    def get_history(self, event_type: str = None, limit: int = 50) -> List[Event]:
        """Get event history"""
        with self._lock:
            if event_type:
                filtered = [e for e in self._event_history if e.type == event_type]
                return filtered[-limit:]
            return self._event_history[-limit:]
    
    def clear_history(self):
        """Clear event history"""
        with self._lock:
            self._event_history.clear()


# Global event bus instance
event_bus = EventBus()
