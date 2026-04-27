import asyncio
import json
import logging
from typing import Optional, Callable, Any, Dict
from contextlib import asynccontextmanager
from dataclasses import dataclass

import aio_pika
from aio_pika import Message, ExchangeType, connect_robust
from aio_pika.abc import AbstractRobustConnection, AbstractRobustChannel, AbstractRobustQueue

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class RabbitMQConfig:
    """RabbitMQ configuration"""
    host: str = "localhost"
    port: int = 5672
    username: str = "admin"
    password: str = "password"
    virtual_host: str = "/"
    heartbeat: int = 0
    
    @property
    def url(self) -> str:
        return f"amqp://{self.username}:{self.password}@{self.host}:{self.port}/{self.virtual_host}"

class RabbitMQClient:
    """RabbitMQ client for FastAPI and workers"""
    
    def __init__(self, config: Optional[RabbitMQConfig] = None):
        self.config = config or RabbitMQConfig()
        self.connection: Optional[AbstractRobustConnection] = None
        self.channel: Optional[AbstractRobustChannel] = None
        self._consumers: Dict[str, Callable] = {}
        
    async def connect(self) -> None:
        """Establish connection to RabbitMQ"""
        try:
            logger.info(f"[RabbitMQ] attempting to connect to: {self.config.url}")
            self.connection = await connect_robust(self.config.url)
            self.channel = await self.connection.channel()
            logger.info(f"Connected to RabbitMQ at {self.config.host}:{self.config.port}")
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise
    
    async def close(self) -> None:
        """Close connection"""
        if self.channel and not self.channel.is_closed:
            await self.channel.close()
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
        logger.info("RabbitMQ connection closed")
    
    async def declare_queue(
        self, 
        queue_name: str, 
        durable: bool = True,
        exclusive: bool = False,
        auto_delete: bool = False
    ) -> AbstractRobustQueue:
        """Declare a queue"""
        return await self.channel.declare_queue(
            queue_name,
            durable=durable,
            exclusive=exclusive,
            auto_delete=auto_delete
        )
    
    async def publish(
        self,
        queue_name: str,
        message: Any,
        routing_key: Optional[str] = None,
        exchange_name: str = "",
        message_type: str = "text/plain",
        headers: Optional[Dict] = None,
        expiration: Optional[int] = None,
        priority: int = 0
    ) -> None:
        """
        Publish a message to a queue
        
        Args:
            queue_name: Target queue name
            message: Message content (str, dict, or bytes)
            routing_key: Routing key (defaults to queue_name)
            exchange_name: Exchange name (empty string for default exchange)
            message_type: MIME type of message
            headers: Message headers
            expiration: TTL in milliseconds
            priority: Message priority (0-9)
        """
        if routing_key is None:
            routing_key = queue_name
            
        # Convert message to appropriate format
        if isinstance(message, dict):
            import json
            body = json.dumps(message).encode()
            content_type = "application/json"
        elif isinstance(message, str):
            body = message.encode()
            content_type = message_type
        else:
            body = message if isinstance(message, bytes) else str(message).encode()
            content_type = message_type
        
        if exchange_name == "" or exchange_name is None:
            # Use the pre-existing default exchange proxy
            exchange = self.channel.default_exchange
        else:
            # Only call get_exchange if a custom name is provided
            exchange = await self.channel.get_exchange(exchange_name)
        
        msg = Message(
            body,
            content_type=content_type,
            headers=headers or {},
            priority=priority,
            expiration=expiration,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT if expiration is None else aio_pika.DeliveryMode.NOT_PERSISTENT
        )
        
        await exchange.publish(msg, routing_key=routing_key)
        logger.debug(f"Published message to {queue_name}: {message[:100] if len(str(message)) > 100 else message}")
    
    async def consume(
        self,
        queue_name: str,
        callback: Callable,
        auto_ack: bool = False,
        prefetch_count: int = 1,
        postgres_session: Any = None,
        neo4j_session: Any = None
    ) -> None:
        """
        Consume messages from a queue
        
        Args:
            queue_name: Queue to consume from
            callback: Async function that receives message body
            auto_ack: Auto-acknowledge messages
            prefetch_count: Number of messages to prefetch
        """
        queue = await self.declare_queue(queue_name, durable=True)
        
        # Set prefetch count for QoS
        await self.channel.set_qos(prefetch_count=prefetch_count)
        
        async def on_message(message: aio_pika.IncomingMessage):
            try:
                if message.content_type == "application/json":
                    body = json.loads(message.body.decode())
                else:
                    body = message.body.decode()
                
                # Pass the sessions or services here
                result = await callback(body, message, postgres_session, neo4j_session)
                
                if result is False or result is None:
                    await message.reject(requeue=True)
                else:
                    await message.ack()
                    
            except Exception as e:
                logger.error(f"Callback failed: {e}")
                # Crucial: nack the message so it doesn't get stuck in 'Unacked' state
                if not message.processed:
                    await message.nack(requeue=True)
        
        await queue.consume(on_message)
        logger.info(f"Started consuming from queue: {queue_name}")
    
    @asynccontextmanager
    async def get_channel(self):
        """Context manager for getting a channel"""
        if not self.channel or self.channel.is_closed:
            await self.connect()
        yield self.channel

# Global client instance
rabbitmq_client = RabbitMQClient()