from typing import List, Dict, Optional, AsyncIterator
from datetime import datetime, timedelta
import asyncio
from dataclasses import dataclass, asdict
import json
from ..utils.errors import ConversationError

@dataclass
class Message:
    """Represents a single message in the conversation.
    
    Attributes:
        role: The role of the message sender ('user' or 'assistant')
        content: The content of the message
        timestamp: When the message was sent
        metadata: Optional additional message metadata
    """
    role: str
    content: str
    timestamp: datetime
    metadata: Dict = None
    
    def to_dict(self) -> Dict:
        """Convert message to dictionary format."""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Message":
        """Create message from dictionary format."""
        if 'timestamp' in data:
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)

class ConversationManager:
    """Manages conversation histories for users across channels."""
    
    def __init__(self, max_history: int = 10, expiry_hours: int = 24):
        """Initialize conversation manager.
        
        Args:
            max_history: Maximum number of messages per conversation
            expiry_hours: Hours before messages expire
        """
        self.max_history = max_history
        self.expiry_hours = expiry_hours
        self.conversations: Dict[str, List[Message]] = {}
        self.locks: Dict[str, asyncio.Lock] = {}
        
    def _get_conversation_key(self, user_id: int, channel_id: int) -> str:
        """Generate a unique key for the conversation."""
        return f"{user_id}:{channel_id}"
    
    async def _get_lock(self, key: str) -> asyncio.Lock:
        """Get or create a lock for a conversation."""
        if key not in self.locks:
            self.locks[key] = asyncio.Lock()
        return self.locks[key]
    
    async def add_message(
        self, 
        user_id: int, 
        channel_id: int, 
        content: str, 
        role: str,
        metadata: Dict = None
    ) -> None:
        """Add a message to the conversation history."""
        try:
            key = self._get_conversation_key(user_id, channel_id)
            lock = await self._get_lock(key)
            
            async with lock:
                if key not in self.conversations:
                    self.conversations[key] = []
                    
                message = Message(
                    role=role,
                    content=content,
                    timestamp=datetime.now(),
                    metadata=metadata
                )
                
                self.conversations[key].append(message)
                
                # Trim history if needed
                if len(self.conversations[key]) > self.max_history:
                    self.conversations[key] = self.conversations[key][-self.max_history:]
                    
        except Exception as e:
            raise ConversationError(f"Failed to add message: {str(e)}")
    
    async def get_conversation_history(
        self, 
        user_id: int, 
        channel_id: int,
        include_metadata: bool = False
    ) -> List[Dict[str, str]]:
        """Get the conversation history in a format suitable for the model."""
        try:
            key = self._get_conversation_key(user_id, channel_id)
            
            if key not in self.conversations:
                return []
                
            # Filter out expired messages
            cutoff_time = datetime.now() - timedelta(hours=self.expiry_hours)
            messages = [
                msg for msg in self.conversations[key]
                if msg.timestamp > cutoff_time
            ]
            
            # Update the conversation with only valid messages
            self.conversations[key] = messages
            
            # Convert to format expected by the model
            return [
                {
                    "role": msg.role, 
                    "content": msg.content,
                    **({"metadata": msg.metadata} if include_metadata and msg.metadata else {})
                }
                for msg in messages
            ]
            
        except Exception as e:
            raise ConversationError(f"Failed to get conversation history: {str(e)}")
    
    async def clear_conversation(self, user_id: int, channel_id: int) -> None:
        """Clear the conversation history for a specific user/channel."""
        try:
            key = self._get_conversation_key(user_id, channel_id)
            lock = await self._get_lock(key)
            
            async with lock:
                if key in self.conversations:
                    del self.conversations[key]
                if key in self.locks:
                    del self.locks[key]
                    
        except Exception as e:
            raise ConversationError(f"Failed to clear conversation: {str(e)}")
    
    async def cleanup_expired(self) -> None:
        """Remove expired conversations."""
        try:
            cutoff_time = datetime.now() - timedelta(hours=self.expiry_hours)
            keys_to_remove = []
            
            for key, messages in self.conversations.items():
                # Check if all messages in conversation are expired
                if all(msg.timestamp < cutoff_time for msg in messages):
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                await self.clear_conversation(
                    *map(int, key.split(':'))
                )
                
        except Exception as e:
            raise ConversationError(f"Failed to cleanup expired conversations: {str(e)}")
    
    async def export_conversations(self) -> Dict[str, List[Dict]]:
        """Export all conversations in serializable format."""
        return {
            key: [msg.to_dict() for msg in messages]
            for key, messages in self.conversations.items()
        }
    
    async def import_conversations(self, data: Dict[str, List[Dict]]) -> None:
        """Import conversations from serialized format."""
        try:
            for key, messages in data.items():
                self.conversations[key] = [
                    Message.from_dict(msg) for msg in messages
                ]
        except Exception as e:
            raise ConversationError(f"Failed to import conversations: {str(e)}")
