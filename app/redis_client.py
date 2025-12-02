import redis
import json
import os
from typing import Optional
from dotenv import load_dotenv

# Carga variables del archivo .env
load_dotenv()

class RedisClient:
    def __init__(self):
        """
        Inicializa el cliente de Redis leyendo del .env
        """
        self.host = os.getenv('REDIS_HOST')
        self.port = os.getenv('REDIS_PORT')
        self.password = os.getenv('REDIS_PASSWORD')
        self.client = None
        self._connect()
    
    def _connect(self):
        """Conecta a Redis"""
        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                password=self.password,
                decode_responses=True,
                socket_connect_timeout=5
            )
            self.client.ping()
            print(f"✓ Redis conectado en {self.host}:{self.port}")
        except Exception as e:
            print(f"✗ Error conectando a Redis: {e}")
            self.client = None
    
    def check_connection(self) -> bool:
        """Verifica si Redis está conectado"""
        if not self.client:
            return False
        try:
            return self.client.ping()
        except Exception as e:
            print(f"Redis connection error: {e}")
            return False
    
    def get(self, key: str) -> Optional[dict]:
        """Obtiene valor de Redis"""
        if not self.client:
            return None
        try:
            value = self.client.get(key)
            return json.loads(value) if value else None
        except Exception as e:
            print(f"Error getting key '{key}': {e}")
            return None
    
    def set(self, key: str, value: dict, ttl: Optional[int] = None) -> bool:
        """Guarda valor en Redis"""
        if not self.client:
            return False
        try:
            serialized = json.dumps(value, default=str)
            if ttl:
                self.client.setex(key, ttl, serialized)
            else:
                self.client.set(key, serialized)
            return True
        except Exception as e:
            print(f"Error setting key '{key}': {e}")
            return False
    
    def delete(self, *keys: str) -> int:
        """Elimina una o más keys"""
        if not self.client:
            return 0
        try:
            return self.client.delete(*keys)
        except Exception as e:
            print(f"Error deleting keys: {e}")
            return 0
    
    def exists(self, key: str) -> bool:
        """Verifica si una key existe"""
        if not self.client:
            return False
        try:
            return self.client.exists(key) > 0
        except Exception as e:
            print(f"Error checking key: {e}")
            return False

# Instancia global
redis_client = RedisClient()