# ===================================================================
# STUDYGENIE - Complete Production Application
# By Sparsh Singhal
# ===================================================================

import os
import sys
import re
import time
import json
import logging
import threading
import hmac
import hashlib
import secrets
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional, Dict, Any, List, Tuple
from functools import wraps
from dataclasses import dataclass, field
from enum import Enum
import queue
from concurrent.futures import ThreadPoolExecutor

# ===================================================================
# Third Party Imports
# ===================================================================
from flask import Flask, request, jsonify, send_from_directory, g, session
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import redis
from redis import ConnectionPool
import google.generativeai as genai
import razorpay
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import bcrypt
import jwt
from werkzeug.middleware.proxy_fix import ProxyFix

# ===================================================================
# Configuration
# ===================================================================
class Config:
    """Thread-safe configuration management."""
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        # Core
        self.SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_urlsafe(32))
        self.ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", secrets.token_urlsafe(32))
        self.PORT = int(os.environ.get("PORT", 5000))
        self.FLASK_ENV = os.environ.get("FLASK_ENV", "production")
        
        # Redis
        self.REDIS_URL = os.environ.get("REDIS_URL") or os.environ.get("UPSTASH_REDIS_URL")
        self.REDIS_POOL_SIZE = int(os.environ.get("REDIS_POOL_SIZE", 50))
        self.REDIS_TIMEOUT = int(os.environ.get("REDIS_TIMEOUT", 5))
        
        # AI
        self.GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
        self.AI_MODEL = "gemini-2.0-flash"
        self.AI_MAX_TOKENS = 200
        self.AI_TIMEOUT = 10
        
        # Payments
        self.RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
        self.RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
        self.RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
        self.PRO_AMOUNT = int(os.environ.get("PRO_AMOUNT", 4900))  # ₹49
        
        # Limits
        self.FREE_ASK_LIMIT = int(os.environ.get("FREE_ASK_LIMIT", 10))
        self.MAX_XP_PER_UPDATE = int(os.environ.get("MAX_XP_PER_UPDATE", 100_000))
        self.RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", 30))
        self.RATE_LIMIT_PER_HOUR = int(os.environ.get("RATE_LIMIT_PER_HOUR", 300))
        self.WORKER_THREADS = int(os.environ.get("WORKER_THREADS", 200))
        
        # Cache
        self.LEADERBOARD_CACHE_TTL = 0.5
        self.USER_CACHE_TTL = 300
        self.SESSION_TIMEOUT = 86400  # 24 hours
        
        # Security
        self.BCRYPT_ROUNDS = 12
        self.JWT_EXPIRATION = 86400  # 24 hours
        
        # Features
        self.ENABLE_ADMIN_DASHBOARD = os.environ.get("ENABLE_ADMIN_DASHBOARD", "true").lower() == "true"
        self.ENABLE_EMAIL_VERIFICATION = os.environ.get("ENABLE_EMAIL_VERIFICATION", "false").lower() == "true"
        self.ENABLE_DEMO_MODE = os.environ.get("ENABLE_DEMO_MODE", "false").lower() == "true"
        
        # Monitoring
        self.ENABLE_METRICS = os.environ.get("ENABLE_METRICS", "true").lower() == "true"
        
        # Logging
        self.LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
        self.LOG_JSON = os.environ.get("LOG_JSON", "false").lower() == "true"

config = Config()

# ===================================================================
# Logging Setup
# ===================================================================
class CustomLogger:
    """Custom logger with rotation and formatting."""
    _instances = {}
    _lock = threading.RLock()
    
    def __new__(cls, name="studygenie"):
        if name not in cls._instances:
            with cls._lock:
                if name not in cls._instances:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instances[name] = instance
        return cls._instances[name]
    
    def __init__(self, name="studygenie"):
        if self._initialized:
            return
        self._initialized = True
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, config.LOG_LEVEL.upper()))
        
        # Remove existing handlers
        self.logger.handlers.clear()
        
        # Console handler
        console = logging.StreamHandler(sys.stdout)
        if config.LOG_JSON:
            formatter = logging.Formatter(
                '{"timestamp":"%(asctime)s","level":"%(levelname)s","name":"%(name)s",'
                '"module":"%(module)s","function":"%(funcName)s","message":"%(message)s"}'
            )
        else:
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
            )
        console.setFormatter(formatter)
        self.logger.addHandler(console)
        
        # File handler with rotation
        try:
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                'studygenie.log', maxBytes=10*1024*1024, backupCount=5
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        except:
            pass
    
    def get(self):
        return self.logger

log = CustomLogger().get()

# ===================================================================
# Redis Connection Pool
# ===================================================================
class RedisManager:
    """Singleton Redis connection manager with connection pooling."""
    _instance = None
    _lock = threading.RLock()
    _pool = None
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._init_pool()
    
    def _init_pool(self):
        """Initialize Redis connection pool."""
        if not config.REDIS_URL:
            log.warning("Redis URL not configured, using fallback storage")
            self._pool = None
            return
        
        try:
            self._pool = ConnectionPool.from_url(
                config.REDIS_URL,
                max_connections=config.REDIS_POOL_SIZE,
                decode_responses=True,
                socket_connect_timeout=config.REDIS_TIMEOUT,
                socket_timeout=config.REDIS_TIMEOUT,
                retry_on_timeout=True,
                health_check_interval=30
            )
            # Test connection
            r = redis.Redis(connection_pool=self._pool)
            r.ping()
            log.info(f"Redis connection pool initialized with {config.REDIS_POOL_SIZE} connections")
        except Exception as e:
            log.error(f"Redis connection failed: {e}")
            self._pool = None
    
    def get_client(self):
        """Get Redis client from pool."""
        if not self._pool:
            return None
        try:
            return redis.Redis(connection_pool=self._pool)
        except Exception as e:
            log.error(f"Failed to get Redis client: {e}")
            return None
    
    def is_available(self):
        """Check if Redis is available."""
        if not self._pool:
            return False
        try:
            r = redis.Redis(connection_pool=self._pool)
            r.ping()
            return True
        except:
            return False

redis_manager = RedisManager()

# ===================================================================
# Data Models
# ===================================================================
class UserPlan(Enum):
    FREE = "free"
    PRO = "pro"
    VIP = "vip"

@dataclass
class User:
    phone: str
    uid: str
    name: str = "Warrior"
    plan: UserPlan = UserPlan.FREE
    xp: int = 0
    level: int = 1
    streak: int = 0
    last_active: datetime = field(default_factory=datetime.utcnow)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    email: Optional[str] = None
    email_verified: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "phone": self.phone,
            "uid": self.uid,
            "name": self.name,
            "plan": self.plan.value,
            "xp": self.xp,
            "level": self.level,
            "streak": self.streak,
            "last_active": self.last_active.isoformat() if self.last_active else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "email": self.email,
            "email_verified": self.email_verified,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        plan = UserPlan(data.get("plan", "free"))
        return cls(
            phone=data["phone"],
            uid=data["uid"],
            name=data.get("name", "Warrior"),
            plan=plan,
            xp=data.get("xp", 0),
            level=data.get("level", 1),
            streak=data.get("streak", 0),
            last_active=datetime.fromisoformat(data["last_active"]) if data.get("last_active") else datetime.utcnow(),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.utcnow(),
            email=data.get("email"),
            email_verified=data.get("email_verified", False),
            metadata=data.get("metadata", {})
        )

@dataclass
class LeaderboardEntry:
    uid: str
    name: str
    xp: int
    level: int
    rank: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "id": self.uid,
            "name": self.name,
            "xp": self.xp,
            "level": self.level
        }
        if self.rank is not None:
            result["rank"] = self.rank
        return result

@dataclass
class PaymentRecord:
    order_id: str
    payment_id: Optional[str]
    uid: str
    phone: str
    amount: int
    currency: str = "INR"
    status: str = "created"
    created_at: datetime = field(default_factory=datetime.utcnow)
    captured_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "payment_id": self.payment_id,
            "uid": self.uid,
            "phone": self.phone,
            "amount": self.amount,
            "currency": self.currency,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None
        }

# ===================================================================
# Storage Service - High Performance with Redis + Fallback
# ===================================================================
class StorageService:
    """High-performance storage with Redis primary and in-memory fallback."""
    
    def __init__(self):
        self._state_lock = threading.RLock()
        self._batch_operations = []
        self._batch_lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=config.WORKER_THREADS)
        self._last_save = time.time()
        
        # In-memory fallback (thread-safe)
        self._users: Dict[str, Dict] = {}
        self._leaderboard: Dict[str, Dict] = {}
        self._ask_counts: Dict[str, int] = defaultdict(int)
        self._daily_active: Dict[str, set] = defaultdict(set)
        self._total_asks = 0
        self._payments: List[Dict] = []
        self._sessions: Dict[str, Dict] = {}
        
        # Load initial data
        self._load_from_file()
        
        # Start background tasks
        self._start_background_tasks()
    
    def _start_background_tasks(self):
        """Start background maintenance tasks."""
        def maintenance_worker():
            while True:
                try:
                    time.sleep(60)
                    self._cleanup_expired()
                    self._save_batch()
                except Exception as e:
                    log.error(f"Maintenance worker error: {e}")
        
        threading.Thread(target=maintenance_worker, daemon=True).start()
    
    def _get_redis(self):
        """Get Redis client."""
        return redis_manager.get_client()
    
    def _load_from_file(self):
        """Load data from JSON file (fallback)."""
        try:
            file_path = "data.json"
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    with self._state_lock:
                        self._users = data.get("users", {})
                        self._leaderboard = data.get("leaderboard", {})
                        self._ask_counts = defaultdict(int, data.get("ask_counts", {}))
                        self._daily_active = defaultdict(set, {
                            k: set(v) for k, v in data.get("daily_active", {}).items()
                        })
                        self._total_asks = data.get("total_asks", 0)
                        self._payments = data.get("payments", [])
                        self._sessions = data.get("sessions", {})
                log.info("Loaded data from file")
        except Exception as e:
            log.error(f"Failed to load data: {e}")
    
    def _save_to_file(self, force=False):
        """Save data to JSON file (fallback)."""
        try:
            with self._state_lock:
                data = {
                    "users": self._users,
                    "leaderboard": self._leaderboard,
                    "ask_counts": dict(self._ask_counts),
                    "daily_active": {k: list(v) for k, v in self._daily_active.items()},
                    "total_asks": self._total_asks,
                    "payments": self._payments,
                    "sessions": self._sessions
                }
            
            tmp_path = "data.json.tmp"
            with open(tmp_path, 'w') as f:
                json.dump(data, f)
            os.replace(tmp_path, "data.json")
        except Exception as e:
            log.error(f"Failed to save data: {e}")
    
    def _save_batch(self):
        """Batch save operations."""
        with self._batch_lock:
            if self._batch_operations:
                ops = self._batch_operations[:]
                self._batch_operations = []
                for op in ops:
                    try:
                        op()
                    except Exception as e:
                        log.error(f"Batch operation failed: {e}")
    
    def _cleanup_expired(self):
        """Cleanup expired sessions and data."""
        try:
            r = self._get_redis()
            if r:
                # Clean expired sessions
                now = time.time()
                with self._state_lock:
                    expired = [k for k, v in self._sessions.items() if v.get("expires", 0) < now]
                    for k in expired:
                        del self._sessions[k]
                
                # Clean old daily active
                cutoff = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
                with self._state_lock:
                    old_days = [d for d in self._daily_active.keys() if d < cutoff]
                    for d in old_days:
                        del self._daily_active[d]
                
                self._save_to_file()
        except Exception as e:
            log.error(f"Cleanup failed: {e}")
    
    # ========== User Operations ==========
    def get_user(self, phone: str) -> Optional[User]:
        """Get user by phone with caching."""
        if not phone:
            return None
        
        # Try Redis cache first
        r = self._get_redis()
        if r:
            try:
                key = f"user:{phone}"
                data = r.hgetall(key)
                if data:
                    # Update cache TTL
                    r.expire(key, config.USER_CACHE_TTL)
                    return User.from_dict(data)
            except Exception as e:
                log.error(f"Redis get_user failed: {e}")
        
        # Fallback to in-memory
        with self._state_lock:
            if phone in self._users:
                return User.from_dict(self._users[phone])
        return None
    
    def get_user_by_uid(self, uid: str) -> Optional[User]:
        """Get user by UID."""
        # Try Redis first
        r = self._get_redis()
        if r:
            try:
                phone = r.get(f"uid_to_phone:{uid}")
                if phone:
                    return self.get_user(phone)
            except Exception as e:
                log.error(f"Redis get_user_by_uid failed: {e}")
        
        # Fallback to in-memory
        with self._state_lock:
            for phone, user_data in self._users.items():
                if user_data.get("uid") == uid:
                    return User.from_dict(user_data)
        return None
    
    def save_user(self, user: User) -> bool:
        """Save user with Redis caching."""
        try:
            data = user.to_dict()
            
            # Save to Redis with TTL
            r = self._get_redis()
            if r:
                try:
                    key = f"user:{user.phone}"
                    r.hset(key, mapping=data)
                    r.expire(key, config.USER_CACHE_TTL)
                    r.set(f"uid_to_phone:{user.uid}", user.phone, ex=config.USER_CACHE_TTL)
                except Exception as e:
                    log.error(f"Redis save_user failed: {e}")
            
            # Save to in-memory
            with self._state_lock:
                self._users[user.phone] = data
                self._sessions[user.uid] = {
                    "phone": user.phone,
                    "expires": time.time() + config.SESSION_TIMEOUT
                }
            
            # Schedule file save
            self._schedule_save()
            return True
        except Exception as e:
            log.error(f"Failed to save user: {e}")
            return False
    
    def update_user_plan(self, phone: str, plan: str) -> bool:
        """Update user plan."""
        user = self.get_user(phone)
        if not user:
            return False
        
        user.plan = UserPlan(plan)
        user.updated_at = datetime.utcnow()
        
        # Update leaderboard with new plan
        self.update_leaderboard(user.uid, user.name, user.xp, user.phone, user.level)
        
        return self.save_user(user)
    
    def get_user_plan(self, phone: str) -> str:
        """Get user's plan."""
        user = self.get_user(phone)
        return user.plan.value if user else "free"
    
    # ========== Leaderboard Operations ==========
    def get_leaderboard(self, limit: int = 10) -> List[LeaderboardEntry]:
        """Get leaderboard with Redis sorted set."""
        r = self._get_redis()
        if r:
            try:
                # Get from Redis sorted set
                items = r.zrevrange("leaderboard", 0, limit - 1, withscores=True)
                if items:
                    entries = []
                    for idx, (uid, score) in enumerate(items):
                        # Get user details
                        name = r.hget(f"user:{uid}", "name") or "Warrior"
                        level = int(r.hget(f"user:{uid}", "level") or 1)
                        entries.append(LeaderboardEntry(
                            uid=uid,
                            name=name,
                            xp=int(score),
                            level=level,
                            rank=idx + 1
                        ))
                    return entries
            except Exception as e:
                log.error(f"Redis leaderboard failed: {e}")
        
        # Fallback to in-memory
        with self._state_lock:
            sorted_users = sorted(
                self._leaderboard.values(),
                key=lambda x: x.get("xp", 0),
                reverse=True
            )[:limit]
            
            return [
                LeaderboardEntry(
                    uid=u["id"],
                    name=u["name"],
                    xp=u["xp"],
                    level=u.get("level", 1),
                    rank=i + 1
                )
                for i, u in enumerate(sorted_users)
            ]
    
    def update_leaderboard(self, uid: str, name: str, xp: int, phone: Optional[str] = None, level: int = 1):
        """Update leaderboard with high performance."""
        entry = {"id": uid, "name": name, "xp": xp, "level": level}
        
        # Update Redis sorted set
        r = self._get_redis()
        if r:
            try:
                r.zadd("leaderboard", {uid: xp})
                r.hset(f"user:{uid}", mapping={
                    "uid": uid,
                    "name": name,
                    "xp": xp,
                    "level": level
                })
                if phone:
                    r.hset(f"user:{uid}", "phone", phone)
            except Exception as e:
                log.error(f"Redis leaderboard update failed: {e}")
        
        # Update in-memory
        with self._state_lock:
            self._leaderboard[uid] = entry
            if phone and phone in self._users:
                self._users[phone]["xp"] = xp
                self._users[phone]["name"] = name
                self._users[phone]["level"] = level
        
        self._schedule_save()
    
    # ========== Ask Operations ==========
    def increment_ask_count(self, uid: str) -> int:
        """Increment ask count with atomic operations."""
        r = self._get_redis()
        if r:
            try:
                # Atomic increment in Redis
                new_count = r.hincrby("ask_counts", uid, 1)
                r.incr("total_asks")
                
                # Track daily active
                today = datetime.utcnow().strftime("%Y-%m-%d")
                r.sadd(f"daily_active:{today}", uid)
                r.expire(f"daily_active:{today}", 86400 * 30)  # 30 days
                
                return int(new_count)
            except Exception as e:
                log.error(f"Redis increment_ask_count failed: {e}")
        
        # Fallback to in-memory
        with self._state_lock:
            self._ask_counts[uid] = self._ask_counts.get(uid, 0) + 1
            new_count = self._ask_counts[uid]
            self._total_asks += 1
            
            today = datetime.utcnow().strftime("%Y-%m-%d")
            self._daily_active[today].add(uid)
        
        self._schedule_save()
        return new_count
    
    def get_ask_count(self, uid: str) -> int:
        """Get ask count."""
        r = self._get_redis()
        if r:
            try:
                count = r.hget("ask_counts", uid)
                if count is not None:
                    return int(count)
            except Exception as e:
                log.error(f"Redis get_ask_count failed: {e}")
        
        with self._state_lock:
            return self._ask_counts.get(uid, 0)
    
    # ========== Stats Operations ==========
    def get_stats(self) -> Dict[str, Any]:
        """Get system stats."""
        r = self._get_redis()
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        if r:
            try:
                return {
                    "total_users": int(r.scard("users") or 0),
                    "total_asks": int(r.get("total_asks") or 0),
                    "daily_active": int(r.scard(f"daily_active:{today}") or 0),
                    "date": today,
                    "redis_connected": True
                }
            except Exception as e:
                log.error(f"Redis get_stats failed: {e}")
        
        with self._state_lock:
            return {
                "total_users": len(self._users),
                "total_asks": self._total_asks,
                "daily_active": len(self._daily_active.get(today, set())),
                "date": today,
                "redis_connected": False
            }
    
    # ========== Payment Operations ==========
    def save_payment(self, payment: PaymentRecord):
        """Save payment record."""
        data = payment.to_dict()
        
        r = self._get_redis()
        if r:
            try:
                key = f"payment:{payment.order_id}"
                r.hset(key, mapping=data)
                r.expire(key, 86400 * 90)  # 90 days
            except Exception as e:
                log.error(f"Redis save_payment failed: {e}")
        
        with self._state_lock:
            self._payments.append(data)
        
        self._schedule_save()
    
    # ========== Utility ==========
    def _schedule_save(self):
        """Schedule a save operation."""
        now = time.time()
        if now - self._last_save > 5.0:  # Save every 5 seconds max
            self._last_save = now
            self._executor.submit(self._save_to_file)

# ===================================================================
# Global Storage Instance
# ===================================================================
storage = StorageService()

# ===================================================================
# Authentication Service
# ===================================================================
class AuthService:
    """Authentication and authorization service."""
    
    @staticmethod
    def clean_phone(phone: str) -> str:
        """Validate and clean phone number."""
        if not phone:
            return ""
        phone = re.sub(r'[^0-9]', '', str(phone))[:10]
        return phone if re.match(r"^\d{10}$", phone) else ""
    
    @staticmethod
    def clean_name(name: str) -> str:
        """Sanitize name."""
        return re.sub(r'[<>"]', '', str(name))[:50]
    
    @staticmethod
    def generate_uid() -> str:
        """Generate unique user ID."""
        return secrets.token_urlsafe(16)
    
    @staticmethod
    def register_user(phone: str, name: str, uid: Optional[str] = None) -> Tuple[bool, str, Optional[User]]:
        """Register a new user."""
        phone = AuthService.clean_phone(phone)
        if not phone:
            return False, "Invalid phone number", None
        
        name = AuthService.clean_name(name) or "Warrior"
        
        # Check if user exists
        existing = storage.get_user(phone)
        if existing:
            return True, "User already exists", existing
        
        # Create new user
        if not uid:
            uid = AuthService.generate_uid()
        
        user = User(
            phone=phone,
            uid=uid,
            name=name,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        if storage.save_user(user):
            # Initialize leaderboard
            storage.update_leaderboard(uid, name, 0, phone, 1)
            log.info(f"New user registered: {phone} - {name} (UID: {uid})")
            return True, "User registered successfully", user
        
        return False, "Failed to save user", None
    
    @staticmethod
    def update_user_plan(phone: str, plan: str) -> bool:
        """Update user plan."""
        return storage.update_user_plan(phone, plan)
    
    @staticmethod
    def get_user_plan(phone: str) -> str:
        """Get user's plan."""
        return storage.get_user_plan(phone)

auth_service = AuthService()

# ===================================================================
# AI Service with Retry and Fallback
# ===================================================================
class AIService:
    """AI service with retry logic and fallback responses."""
    
    def __init__(self):
        self.client = None
        self._init_client()
        self.fallback_responses = [
            "Oye Warrior! 💪 Sparsh Singhal ka Genie bol raha hai - thoda technical glitch ho gaya. Dobara try karo!",
            "StudyGenie by Sparsh Singhal is reloading! 🔫 Give it a sec and fire again!",
            "Ammo reloading! 🔥 Sparsh Singhal's Genie will be back in a flash!"
        ]
        self._fallback_index = 0
    
    def _init_client(self):
        """Initialize Gemini client."""
        if config.GOOGLE_API_KEY:
            try:
                genai.configure(api_key=config.GOOGLE_API_KEY)
                self.client = genai.GenerativeModel(config.AI_MODEL)
                log.info("AI client initialized successfully")
            except Exception as e:
                log.error(f"Failed to initialize AI client: {e}")
                self.client = None
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception)
    )
    def generate_response(self, question: str, user_name: str = "Warrior", is_pro: bool = False) -> Tuple[bool, str]:
        """Generate AI response with retry logic."""
        if not self.client:
            return False, self._get_fallback_response()
        
        try:
            # Build prompt based on user tier
            pro_features = "You have access to advanced features including detailed explanations, practice problems, and study tips." if is_pro else "You provide quick, savage, and engaging responses."
            
            prompt = f"""You are StudyGenie - an AI educational assistant created by Sparsh Singhal.

User: {user_name}
User Tier: {"PRO" if is_pro else "FREE"}
Features: {pro_features}

Style Guidelines:
- Use Hinglish (Hindi + English mix)
- Be savage but encouraging
- Maximum 180 words
- Include emojis for engagement
- Be educational and helpful
- Reference Sparsh Singhal when appropriate

Question: {question}

Response:"""
            
            response = self.client.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": config.AI_MAX_TOKENS,
                    "temperature": 0.8,
                    "top_p": 0.95
                }
            )
            
            if response and response.text:
                # Clean and truncate response
                text = response.text.strip()
                words = text.split()
                if len(words) > 180:
                    text = ' '.join(words[:180]) + "..."
                return True, text
            
            return False, self._get_fallback_response()
            
        except Exception as e:
            log.error(f"AI generation failed: {e}")
            return False, self._get_fallback_response()
    
    def _get_fallback_response(self) -> str:
        """Get a fallback response."""
        response = self.fallback_responses[self._fallback_index % len(self.fallback_responses)]
        self._fallback_index += 1
        return response

ai_service = AIService()

# ===================================================================
# Payment Service
# ===================================================================
class PaymentService:
    """Payment processing service with Razorpay."""
    
    def __init__(self):
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """Initialize Razorpay client."""
        if config.RAZORPAY_KEY_ID and config.RAZORPAY_KEY_SECRET:
            try:
                self.client = razorpay.Client(
                    auth=(config.RAZORPAY_KEY_ID, config.RAZORPAY_KEY_SECRET)
                )
                log.info("Razorpay client initialized")
            except Exception as e:
                log.error(f"Failed to initialize Razorpay: {e}")
                self.client = None
    
    def create_order(self, uid: str, phone: str, name: str) -> Tuple[bool, Optional[Dict], str]:
        """Create a Razorpay order."""
        if not self.client:
            return False, None, "Payment service not configured"
        
        try:
            order = self.client.order.create({
                "amount": config.PRO_AMOUNT,
                "currency": "INR",
                "receipt": f"sg_{uid}_{int(time.time())}",
                "notes": {
                    "uid": uid,
                    "name": name,
                    "phone": phone,
                    "product": "StudyGenie Pro"
                }
            })
            
            # Save payment record
            payment = PaymentRecord(
                order_id=order["id"],
                payment_id=None,
                uid=uid,
                phone=phone,
                amount=order["amount"],
                status="created"
            )
            storage.save_payment(payment)
            
            return True, {
                "order_id": order["id"],
                "amount": order["amount"],
                "currency": order["currency"],
                "key_id": config.RAZORPAY_KEY_ID
            }, ""
            
        except Exception as e:
            log.error(f"Create order failed: {e}")
            return False, None, str(e)
    
    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """Verify webhook signature."""
        if not config.RAZORPAY_WEBHOOK_SECRET:
            return False
        
        expected = hmac.new(
            config.RAZORPAY_WEBHOOK_SECRET.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected, signature)
    
    def process_payment_captured(self, payment_data: Dict[str, Any]) -> bool:
        """Process captured payment."""
        try:
            notes = payment_data.get("notes", {})
            phone = auth_service.clean_phone(notes.get("phone", ""))
            uid = str(notes.get("uid", ""))
            name = str(notes.get("name", "Warrior"))
            payment_id = payment_data.get("id")
            order_id = payment_data.get("order_id")
            
            if not phone or not uid:
                log.error(f"Invalid payment data: {payment_data}")
                return False
            
            # Update user plan to PRO
            user = storage.get_user(phone)
            if user:
                user.plan = UserPlan.PRO
                user.updated_at = datetime.utcnow()
                user.metadata["payment_id"] = payment_id
                user.metadata["order_id"] = order_id
                storage.save_user(user)
                storage.update_leaderboard(uid, user.name, user.xp, phone, user.level)
            else:
                # Create new user with PRO plan
                user = User(
                    phone=phone,
                    uid=uid,
                    name=name,
                    plan=UserPlan.PRO,
                    metadata={"payment_id": payment_id, "order_id": order_id}
                )
                storage.save_user(user)
                storage.update_leaderboard(uid, name, 0, phone, 1)
            
            # Update payment record
            payment = PaymentRecord(
                order_id=order_id,
                payment_id=payment_id,
                uid=uid,
                phone=phone,
                amount=config.PRO_AMOUNT,
                status="captured",
                captured_at=datetime.utcnow()
            )
            storage.save_payment(payment)
            
            log.info(f"✅ PRO unlocked for: {phone} - {name} (Payment: {payment_id})")
            return True
            
        except Exception as e:
            log.error(f"Process payment failed: {e}")
            return False

payment_service = PaymentService()

# ===================================================================
# Flask Application
# ===================================================================
app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# CORS
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-Admin-Token"]
    }
})

# Rate Limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[
        f"{config.RATE_LIMIT_PER_MINUTE} per minute",
        f"{config.RATE_LIMIT_PER_HOUR} per hour"
    ],
    storage_uri=config.REDIS_URL or "memory://",
    strategy="fixed-window"
)

# ===================================================================
# Middleware
# ===================================================================
@app.before_request
def before_request():
    """Request middleware."""
    g.start_time = time.time()
    g.request_id = secrets.token_hex(8)
    
    # Add CORS headers for all responses
    if request.method == "OPTIONS":
        return jsonify({})

@app.after_request
def after_request(response):
    """Response middleware with metrics."""
    if hasattr(g, 'start_time'):
        duration = time.time() - g.start_time
        log.info(f"Request {g.get('request_id', 'unknown')} completed in {duration:.3f}s")
    
    response.headers['X-Request-ID'] = g.get('request_id', 'unknown')
    return response

# ===================================================================
# Routes
# ===================================================================
@app.route("/")
def home():
    """Serve the main HTML page."""
    return HTML_PAGE

@app.route("/sparsh.jpg")
def photo():
    """Serve the founder's photo."""
    try:
        return send_from_directory(".", "sparsh.jpg")
    except Exception:
        return "", 204

# ===================================================================
# User Routes
# ===================================================================
@app.route("/register_user", methods=["POST"])
@limiter.limit("10 per minute")
def register_user():
    """Register a new user."""
    try:
        data = request.get_json(silent=True) or {}
        phone = auth_service.clean_phone(data.get("phone"))
        name = auth_service.clean_name(data.get("name", "Warrior"))
        uid = data.get("uid")
        
        if not phone:
            return jsonify({"error": "Valid 10-digit phone required"}), 400
        
        success, message, user = auth_service.register_user(phone, name, uid)
        
        if success and user:
            return jsonify({
                "ok": True,
                "uid": user.uid,
                "name": user.name,
                "phone": user.phone,
                "plan": user.plan.value
            })
        else:
            return jsonify({"error": message}), 400
            
    except Exception as e:
        log.error(f"Register user error: {e}")
        return jsonify({"error": str(e)}), 500

# ===================================================================
# Leaderboard Routes
# ===================================================================
@app.route("/leaderboard")
@limiter.limit("60 per minute")
def get_leaderboard():
    """Get the leaderboard."""
    try:
        limit = min(int(request.args.get("limit", 10)), 100)
        entries = storage.get_leaderboard(limit)
        return jsonify([e.to_dict() for e in entries])
    except Exception as e:
        log.error(f"Leaderboard error: {e}")
        return jsonify([]), 200

# ===================================================================
# XP Routes
# ===================================================================
@app.route("/update_xp", methods=["POST"])
@limiter.limit("20 per minute")
def update_xp():
    """Update user XP."""
    try:
        data = request.get_json(silent=True) or {}
        uid = str(data.get("uid", ""))[:64]
        xp = max(0, min(int(data.get("xp", 0)), config.MAX_XP_PER_UPDATE))
        phone = auth_service.clean_phone(data.get("phone"))
        name = auth_service.clean_name(data.get("name", "Warrior"))
        
        if not uid:
            return jsonify({"error": "UID required"}), 400
        
        # Get user for level calculation
        user = None
        if phone:
            user = storage.get_user(phone)
        
        level = 1
        if user:
            level = user.level
            # Level up based on XP
            new_level = 1 + (xp // 100)
            if new_level > level:
                level = new_level
                log.info(f"User {uid} leveled up to {level}")
        
        # Update leaderboard
        storage.update_leaderboard(uid, name, xp, phone, level)
        
        return jsonify({"ok": True, "level": level})
        
    except Exception as e:
        log.error(f"Update XP error: {e}")
        return jsonify({"error": str(e)}), 500

# ===================================================================
# Ask Route (Main Feature)
# ===================================================================
@app.route("/ask", methods=["POST"])
@limiter.limit("60 per minute")
def ask():
    """Handle user questions with AI."""
    try:
        data = request.get_json(silent=True) or {}
        question = (data.get("q") or "").strip()[:2000]
        name = auth_service.clean_name(data.get("name", "Warrior"))
        uid = str(data.get("uid", "anon"))[:64]
        phone = auth_service.clean_phone(data.get("phone"))
        
        if not question:
            return jsonify({"error": "Empty question"}), 400
        
        # Check quota
        plan = storage.get_user_plan(phone) if phone else "free"
        used = storage.get_ask_count(uid)
        
        if plan == "free" and used >= config.FREE_ASK_LIMIT:
            return jsonify({
                "limit_reached": True,
                "ans": f"""🚀 AMMO KHATAM! 🔫

Oye {name}! Your free ammo is over.

💎 RELOAD NOW - ₹49 Only!
✅ Unlimited Questions
✅ 28+ Features
✅ Priority Support

Payment: Click on "RELOAD" button below!

- BY SPARSH SINGHAL"""
            }), 402
        
        # Process the question
        success, response = ai_service.generate_response(question, name, plan == "pro")
        
        # Update stats
        storage.increment_ask_count(uid)
        
        # Add XP for asking (gamification)
        user = storage.get_user(phone) if phone else None
        if user:
            xp_gain = 10 if plan == "free" else 25  # PRO users get more XP
            user.xp += xp_gain
            # Level up logic
            if user.xp >= user.level * 100:
                user.level += 1
                log.info(f"User {name} leveled up to {user.level}")
            storage.save_user(user)
            storage.update_leaderboard(uid, user.name, user.xp, phone, user.level)
        
        return jsonify({
            "ans": response,
            "xp_gained": xp_gain if user else 0
        })
        
    except Exception as e:
        log.error(f"Ask error: {e}")
        return jsonify({"ans": "⚠️ Technical glitch! Try again - BY SPARSH SINGHAL"}), 500

# ===================================================================
# Payment Routes
# ===================================================================
@app.route("/create_order", methods=["POST"])
@limiter.limit("5 per minute")
def create_order():
    """Create Razorpay order."""
    try:
        data = request.get_json(silent=True) or {}
        phone = auth_service.clean_phone(data.get("phone"))
        name = auth_service.clean_name(data.get("name", "Warrior"))
        uid = str(data.get("uid", ""))[:64]
        
        if not phone:
            return jsonify({"error": "Valid phone required"}), 400
        if not uid:
            return jsonify({"error": "UID required"}), 400
        
        success, result, error = payment_service.create_order(uid, phone, name)
        
        if success:
            return jsonify(result)
        else:
            return jsonify({"error": error}), 500
            
    except Exception as e:
        log.error(f"Create order error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/razorpay/webhook", methods=["POST"])
def razorpay_webhook():
    """Handle Razorpay webhook."""
    try:
        payload = request.get_data()
        signature = request.headers.get("X-Razorpay-Signature", "")
        
        # Verify webhook
        if not payment_service.verify_webhook(payload, signature):
            log.warning("Invalid webhook signature")
            return jsonify({"error": "Invalid signature"}), 400
        
        event = request.get_json(silent=True) or {}
        
        if event.get("event") == "payment.captured":
            payment = event.get("payload", {}).get("payment", {}).get("entity", {})
            if payment:
                payment_service.process_payment_captured(payment)
        
        return jsonify({"status": "ok"})
        
    except Exception as e:
        log.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/check_plan", methods=["POST"])
@limiter.limit("30 per minute")
def check_plan():
    """Check user's plan."""
    try:
        data = request.get_json(silent=True) or {}
        phone = auth_service.clean_phone(data.get("phone"))
        
        if not phone:
            return jsonify({"plan": "free"})
        
        plan = storage.get_user_plan(phone)
        return jsonify({"plan": plan})
        
    except Exception as e:
        log.error(f"Check plan error: {e}")
        return jsonify({"plan": "free"}), 200

# ===================================================================
# Admin Routes
# ===================================================================
def admin_required(f):
    """Admin authentication decorator."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not config.ADMIN_TOKEN:
            return jsonify({"error": "Admin token not configured"}), 500
        
        supplied = request.headers.get("X-Admin-Token") or request.args.get("token")
        if not supplied or not hmac.compare_digest(supplied, config.ADMIN_TOKEN):
            return jsonify({"error": "Unauthorized"}), 401
        
        return f(*args, **kwargs)
    return decorated

@app.route("/admin/stats")
@admin_required
def admin_stats():
    """Get admin statistics."""
    try:
        stats = storage.get_stats()
        return jsonify(stats)
    except Exception as e:
        log.error(f"Admin stats error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/admin/users")
@admin_required
def admin_users():
    """Get all users (admin only)."""
    try:
        # Get from Redis or fallback
        r = redis_manager.get_client()
        users = []
        
        if r:
            try:
                keys = r.keys("user:*")
                for key in keys:
                    data = r.hgetall(key)
                    if data:
                        # Filter out leaderboard entries
                        if data.get("phone"):
                            users.append(data)
            except Exception as e:
                log.error(f"Redis admin users failed: {e}")
        
        if not users:
            with storage._state_lock:
                users = list(storage._users.values())
        
        # Limit response size
        users = users[:100]
        return jsonify({"users": users, "total": len(users)})
        
    except Exception as e:
        log.error(f"Admin users error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/admin/force_pro", methods=["POST"])
@admin_required
def admin_force_pro():
    """Force set user to PRO (admin only)."""
    try:
        data = request.get_json(silent=True) or {}
        phone = auth_service.clean_phone(data.get("phone"))
        
        if not phone:
            return jsonify({"error": "Valid phone required"}), 400
        
        success = auth_service.update_user_plan(phone, "pro")
        
        if success:
            return jsonify({"ok": True, "phone": phone, "plan": "pro"})
        else:
            return jsonify({"error": "Failed to update plan"}), 500
            
    except Exception as e:
        log.error(f"Force PRO error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/admin/metrics")
@admin_required
def admin_metrics():
    """Get system metrics (admin only)."""
    try:
        r = redis_manager.get_client()
        metrics = {
            "timestamp": datetime.utcnow().isoformat(),
            "redis": {
                "available": redis_manager.is_available(),
                "pool_size": config.REDIS_POOL_SIZE
            },
            "config": {
                "free_limit": config.FREE_ASK_LIMIT,
                "max_xp": config.MAX_XP_PER_UPDATE,
                "rate_limit": config.RATE_LIMIT_PER_MINUTE
            }
        }
        
        if r:
            try:
                info = r.info()
                metrics["redis"]["memory_used"] = info.get("used_memory_human", "unknown")
                metrics["redis"]["connected_clients"] = info.get("connected_clients", 0)
            except Exception:
                pass
        
        return jsonify(metrics)
        
    except Exception as e:
        log.error(f"Metrics error: {e}")
        return jsonify({"error": str(e)}), 500

# ===================================================================
# HTML Page with Enhanced UI
# ===================================================================
HTML_PAGE = r"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StudyGenie - Battle Edition 🚀</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@800&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#050507!important;color:#fff;min-height:100vh;background-image:radial-gradient(circle at 50% 0%,#1a1208 0%,#050507 60%)}
.mono{font-family:'JetBrains Mono',monospace}
.hud{background:rgba(17,17,19,0.96);border:1px solid #232326;backdrop-filter:blur(10px)}
.bubble-user{background:#fff;color:#000;border-radius:14px 14px 2px 14px;font-weight:900}
.bubble-ai{background:#17171a;border-left:4px solid #ff4d00;border-radius:4px 16px 16px 16px}
.ammo{width:42px;height:52px;background:#121216;border:1px solid #2e2e33;border-radius:6px;display:flex;align-items:center;justify-content:center;transition:all .3s}
.ammo.used{opacity:.15;transform:scale(.9)}
.ammo:hover{transform:scale(1.05);border-color:#ff4d00}
.progress{height:12px;background:#0f0f11;border:1px solid #2a2a2e;transform:skew(-10deg);border-radius:2px;overflow:hidden}
.progress>div{height:100%;background:linear-gradient(90deg,#ff4d00,#ff8a00);box-shadow:0 0 10px #ff4d00;transition:width .5s}
#chat{max-height:60vh;overflow-y:auto!important;scroll-behavior:smooth}
#chat::-webkit-scrollbar{width:4px}
#chat::-webkit-scrollbar-track{background:#0f0f11}
#chat::-webkit-scrollbar-thumb{background:#ff4d00;border-radius:4px}
.hitpop{animation:pop .3s cubic-bezier(.175,.885,.32,1.275)}
@keyframes pop{0%{transform:scale(.6)}100%{transform:scale(1)}}
.input-glow:focus{border-color:#ff4d00!important;box-shadow:0 0 15px rgba(255,77,0,0.3)}
.glow-pulse{animation:pulse 2s infinite}
@keyframes pulse{0%,100%{box-shadow:0 0 20px rgba(255,77,0,0.3)}50%{box-shadow:0 0 40px rgba(255,77,0,0.6)}}
.xp-float{animation:float 2s ease-out forwards}
@keyframes float{0%{opacity:1;transform:translateY(0)}100%{opacity:0;transform:translateY(-50px)}}
.notif{position:fixed;top:20px;right:20px;z-index:9999;max-width:400px}
.level-up{animation:levelUp 1s cubic-bezier(.175,.885,.32,1.275)}
@keyframes levelUp{0%{transform:scale(0) rotate(-10deg)}50%{transform:scale(1.5) rotate(5deg)}100%{transform:scale(1) rotate(0)}}
</style>
</head>
<body>

<div id="notification" class="notif"></div>

<div id="main" class="max-w-[1500px] mx-auto pb-20">
  <div class="hud rounded-[16px] px-5 py-3 flex justify-between items-center sticky top-2 z-30">
    <div class="flex items-center gap-6">
      <img id="logo" src="/sparsh.jpg" class="w-28 h-28 rounded-[16px] border-[4px] border-[#ff4d00] object-cover shadow-[0_0_40px_rgba(255,77,0,0.7)] cursor-pointer hitpop glow-pulse">
      <div>
        <h1 class="font-black text-[22px] tracking-widest">STUDYGENIE <span class="text-[#ff4d00]">⚔️ BATTLE</span></h1>
        <p class="mono text-[12px] text-[#ff8a00] mt-1">BY SPARSH SINGHAL // FOUNDER</p>
        <div class="flex items-center gap-3 mt-3">
          <span class="mono text-[10px] text-zinc-400">XP</span>
          <div class="w-40 progress"><div id="xpBarTop" style="width:0%"></div></div>
          <span id="xpText" class="mono text-[11px] font-bold">0/100 XP</span>
        </div>
        <p class="mono text-[9px] text-zinc-600 mt-1">LVL <span id="lvlTop">1</span> // <span id="userNameTop" class="text-[#ff4d00]">WARRIOR</span> // RANK #<span id="rankTop">?</span></p>
      </div>
    </div>
    <div class="flex items-center gap-4">
      <div class="mono text-right">
        <div class="text-[10px] text-zinc-500 tracking-widest">🔥 AMMO</div>
        <div class="font-black text-3xl"><span id="wishLeft">10</span>/10</div>
      </div>
      <div class="w-px h-12 bg-zinc-800"></div>
      <div class="mono text-right">
        <div class="text-[10px] text-zinc-500 tracking-widest">💎 PLAN</div>
        <div id="planDisplay" class="font-bold text-[#ff8a00] text-sm">FREE</div>
      </div>
    </div>
  </div>

  <div class="grid grid-cols-12 gap-3 mt-3">
    <div class="col-span-12 lg:col-span-3 space-y-3">
      <div class="hud rounded-[14px] p-4">
        <p class="mono text-[10px] text-zinc-500 tracking-widest">🎯 MISSIONS</p>
        <div class="mt-4 bg-black p-3 rounded-[10px] border-l-[3px] border-[#ff4d00]">
          <div class="flex justify-between mono text-[11px] font-bold"><span>💪 ELIMINATE 3 DOUBTS</span><span id="q1t">0/3</span></div>
          <div class="progress mt-2"><div id="q1b" style="width:0%"></div></div>
        </div>
        <div class="mt-3 bg-black p-3 rounded-[10px] border-l-[3px] border-[#ff8a00]">
          <div class="flex justify-between mono text-[11px] font-bold"><span>🔥 ANSWER 10 QUESTIONS</span><span id="q2t">0/10</span></div>
          <div class="progress mt-2"><div id="q2b" style="width:0%"></div></div>
        </div>
      </div>

      <div class="hud rounded-[14px] p-4">
        <p class="mono text-[10px] text-zinc-500 tracking-widest">🔫 AMMO CRATE</p>
        <div id="lampRow" class="grid grid-cols-5 gap-2 mt-3"></div>
        <button onclick="openPay()" class="w-full mt-4 bg-gradient-to-r from-[#ff4d00] to-[#ff8a00] mono font-black py-3 rounded-[10px] hover:scale-105 transition-transform">
          💎 RELOAD - ₹49
        </button>
      </div>

      <div class="hud rounded-[14px] p-4 border border-[#ff4d00]/30">
        <p class="mono text-[10px] text-[#ff4d00] tracking-widest font-black">🏆 LIVE LEADERBOARD</p>
        <p class="mono text-[9px] text-zinc-500 mt-1">TOP WARRIORS</p>
        <div id="board" class="mt-3 space-y-2 mono text-[11px]"></div>
        <div class="mt-3 mono text-[9px] text-zinc-500 bg-black p-2.5 rounded border border-zinc-800">
          <span class="text-[#ff8a00]">🔒 PRIVATE</span><br>
          <span id="myId"></span><br><span id="myPhone"></span>
        </div>
      </div>
    </div>

    <div class="col-span-12 lg:col-span-9 hud rounded-[16px] p-4 flex flex-col">
      <div id="chat" class="flex-1 space-y-4 pr-2"></div>
      <div class="mt-4 bg-black border-2 border-[#2a2a2e] rounded-[12px] p-1.5 flex items-center gap-2 sticky bottom-2">
        <span class="mono text-xs px-2 text-[#ff4d00] font-black">></span>
        <input id="q" class="flex-1 bg-transparent mono text-[14px] outline-none py-3 px-2 input-glow" placeholder="🔥 ASK YOUR DOUBT..." onkeypress="if(event.key==='Enter')ask()">
        <button onclick="ask()" class="bg-gradient-to-r from-[#ff4d00] to-[#ff8a00] mono font-black w-24 h-11 rounded-[10px] hover:scale-105 transition-transform">🔫 FIRE</button>
      </div>
    </div>
  </div>
</div>

<!-- Onboard Modal -->
<div id="onboardModal" class="fixed inset-0 z-[60] flex items-center justify-center p-4" style="background:rgba(0,0,0,0.92)">
  <div class="hud rounded-[20px] p-7 max-w-[420px] w-full border-2 border-[#ff4d00]/50 animate-pulse">
    <div class="flex items-center gap-4">
      <img src="/sparsh.jpg" class="w-16 h-16 rounded-[12px] border-2 border-[#ff4d00] object-cover">
      <div>
        <h2 class="font-black text-[20px] leading-none">⚔️ WARRIOR REGISTRATION</h2>
        <p class="mono text-[11px] text-[#ff8a00] mt-1 font-bold">BY SPARSH SINGHAL</p>
      </div>
    </div>
    <p class="mono text-[11px] text-zinc-400 mt-4">Name leaderboard pe dikhega. Phone private hai.</p>
    <div class="mt-5 space-y-3">
      <div>
        <label class="mono text-[10px] text-zinc-500">⚡ YOUR WARRIOR NAME *</label>
        <input id="inpName" class="w-full mt-1 bg-black border-2 border-zinc-800 rounded-[10px] px-4 py-3 mono text-[14px] outline-none input-glow" placeholder="Ex: Aman..." maxlength="20">
      </div>
      <div>
        <label class="mono text-[10px] text-zinc-500">📱 PHONE (PRIVATE) *</label>
        <input id="inpPhone" type="tel" class="w-full mt-1 bg-black border-2 border-zinc-800 rounded-[10px] px-4 py-3 mono text-[14px] outline-none input-glow" placeholder="10 digit" maxlength="10" inputmode="numeric">
      </div>
    </div>
    <button onclick="saveOnboard()" class="w-full mt-6 bg-gradient-to-r from-[#ff4d00] to-[#ff8a00] mono font-black py-3.5 rounded-[12px] hover:scale-105 transition-transform">
      🔥 ENTER BATTLEFIELD
    </button>
  </div>
</div>

<script>
// ===================================================================
// XSS Protection
// ===================================================================
function escapeHtml(s){
  const div = document.createElement('div');
  div.textContent = String(s == null ? '' : s);
  return div.innerHTML;
}

// ===================================================================
// Audio System
// ===================================================================
let audioCtx;
function initAudio(){ if(!audioCtx) audioCtx = new (window.AudioContext||window.webkitAudioContext)(); }
function playSound(t){
  try{
    initAudio();
    let o=audioCtx.createOscillator(); let g=audioCtx.createGain();
    o.connect(g); g.connect(audioCtx.destination);
    if(t=='fire'){o.frequency.value=900;o.type='square';g.gain.setValueAtTime(0.4,audioCtx.currentTime);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.12);o.start();o.stop(audioCtx.currentTime+0.12);}
    if(t=='hit'){o.frequency.value=500;o.type='sine';g.gain.setValueAtTime(0.3,audioCtx.currentTime);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.2);o.start();o.stop(audioCtx.currentTime+0.2);}
    if(t=='level'){o.frequency.value=600;o.type='sine';g.gain.setValueAtTime(0.4,audioCtx.currentTime);o.frequency.linearRampToValueAtTime(1200,audioCtx.currentTime+0.5);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.6);o.start();o.stop(audioCtx.currentTime+0.6);}
    if(t=='empty'){o.frequency.value=150;o.type='sawtooth';g.gain.setValueAtTime(0.4,audioCtx.currentTime);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.6);o.start();o.stop(audioCtx.currentTime+0.6);}
    if(t=='click'){o.frequency.value=800;o.type='triangle';g.gain.setValueAtTime(0.2,audioCtx.currentTime);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.1);o.start();o.stop(audioCtx.currentTime+0.1);}
    if(t=='pro'){o.frequency.value=440;o.type='sine';g.gain.setValueAtTime(0.3,audioCtx.currentTime);o.frequency.linearRampToValueAtTime(880,audioCtx.currentTime+0.3);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.4);o.start();o.stop(audioCtx.currentTime+0.4);}
  }catch{}
}

// ===================================================================
// State
// ===================================================================
let userId = localStorage.getItem('genie_userId') || 'user_' + Math.random().toString(36).substr(2,9);
localStorage.setItem('genie_userId', userId);

let userName = localStorage.getItem('genie_name') || '';
let userPhone = localStorage.getItem('genie_phone') || '';
let isPro = localStorage.getItem('genie_plan') === 'pro';
let stats = JSON.parse(localStorage.getItem('genie_stats') || '{"xp":0,"level":1,"wishes":0,"q1":0,"q2":0,"totalXp":0}');
let isDev = localStorage.getItem('isDev') === 'true';
let c = 0;

// ===================================================================
// DOM Ready
// ===================================================================
document.addEventListener('DOMContentLoaded', () => {
  checkOnboard();
  render();
  loadBoard();
  checkMyPlan();
  setInterval(loadBoard, 5000);
  setInterval(save, 30000);
  
  if(localStorage.getItem('genie_name')) document.getElementById('inpName').value = localStorage.getItem('genie_name');
  if(localStorage.getItem('genie_phone')) document.getElementById('inpPhone').value = localStorage.getItem('genie_phone');
});

// ===================================================================
// Core Functions
// ===================================================================
function checkOnboard(){
  userName = localStorage.getItem('genie_name') || '';
  userPhone = localStorage.getItem('genie_phone') || '';
  if(!userName || !userPhone || userPhone.length != 10){
    document.getElementById('onboardModal').classList.remove('hidden');
  } else {
    document.getElementById('onboardModal').classList.add('hidden');
    document.getElementById('userNameTop').textContent = userName.toUpperCase();
    document.getElementById('myId').textContent = `ID: ${userId} (private)`;
    document.getElementById('myPhone').textContent = `📱 ${userPhone.slice(0,2)}******${userPhone.slice(-2)} 🔒`;
  }
}

function saveOnboard(){
  let n = document.getElementById('inpName').value.trim();
  let p = document.getElementById('inpPhone').value.trim().replace(/[^0-9]/g,'');
  if(n.length < 2){ showNotification('⚠️ Naam daal!', 'error'); playSound('empty'); return; }
  if(p.length != 10){ showNotification('📱 10 digit phone daalo!', 'error'); playSound('empty'); return; }
  
  localStorage.setItem('genie_name', n);
  localStorage.setItem('genie_phone', p);
  userName = n; userPhone = p;
  
  playSound('level');
  document.getElementById('onboardModal').classList.add('hidden');
  document.getElementById('userNameTop').textContent = n.toUpperCase();
  document.getElementById('myId').textContent = `ID: ${userId} (private)`;
  document.getElementById('myPhone').textContent = `📱 ${p.slice(0,2)}******${p.slice(-2)} 🔒`;
  
  showNotification('🔥 Welcome to the battlefield, ' + n + '!', 'success');
  
  fetch('/register_user', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({uid:userId, name:n, phone:p})
  }).then(() => {
    updateLeaderboard();
    checkMyPlan();
  });
}

function render(){
  document.getElementById('wishLeft').textContent = (isDev || isPro) ? '∞' : (10 - stats.wishes);
  document.getElementById('lvlTop').textContent = stats.level;
  document.getElementById('xpBarTop').style.width = stats.xp + '%';
  document.getElementById('xpText').textContent = stats.xp + '/100 XP';
  document.getElementById('q1t').textContent = stats.q1 + '/3';
  document.getElementById('q1b').style.width = (stats.q1/3*100) + '%';
  document.getElementById('q2t').textContent = stats.q2 + '/10';
  document.getElementById('q2b').style.width = (stats.q2/10*100) + '%';
  document.getElementById('planDisplay').textContent = isPro ? '💎 PRO' : 'FREE';
  document.getElementById('planDisplay').className = isPro ? 'font-bold text-[#ff4d00] text-sm' : 'font-bold text-[#ff8a00] text-sm';
  lamps();
}

function lamps(){
  let r = document.getElementById('lampRow');
  r.innerHTML = '';
  let used = stats.wishes;
  for(let i=0; i<10; i++){
    let cell = document.createElement('div');
    cell.className = 'ammo' + (i < used && !isDev && !isPro ? ' used' : '');
    cell.textContent = i < used && !isDev && !isPro ? '💨' : '🪔';
    r.appendChild(cell);
  }
}

function save(){ 
  localStorage.setItem('genie_stats', JSON.stringify(stats)); 
  render(); 
  updateLeaderboard(); 
}

function showNotification(msg, type='info'){
  let el = document.getElementById('notification');
  let colors = {
    success: 'bg-green-600 border-green-400',
    error: 'bg-red-600 border-red-400',
    info: 'bg-blue-600 border-blue-400'
  };
  el.innerHTML = `<div class="${colors[type] || colors.info} border-2 p-4 rounded-lg mono text-white shadow-xl">${msg}</div>`;
  el.style.display = 'block';
  clearTimeout(el._timeout);
  el._timeout = setTimeout(() => { el.style.display = 'none'; }, 4000);
}

// ===================================================================
// Leaderboard
// ===================================================================
async function updateLeaderboard(){
  try{
    let n = localStorage.getItem('genie_name') || userName || 'Warrior';
    let ph = localStorage.getItem('genie_phone') || userPhone || '';
    await fetch('/update_xp', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        uid: userId,
        name: n,
        phone: ph,
        xp: stats.totalXp || ((stats.level-1)*100 + stats.xp)
      })
    });
  }catch{}
}

async function loadBoard(){
  try{
    let r = await fetch('/leaderboard?t=' + Date.now());
    let d = await r.json();
    let boardEl = document.getElementById('board');
    boardEl.innerHTML = '';
    
    if(d.length == 0){
      boardEl.innerHTML = '<div class="text-zinc-500 text-center py-2">No warriors yet.</div>';
      return;
    }
    
    let myRank = d.findIndex(u => u.id === userId) + 1;
    document.getElementById('rankTop').textContent = myRank || '-';
    
    d.forEach((u,i) => {
      let isMe = u.id === userId;
      let medal = i==0 ? '👑' : i==1 ? '🥈' : i==2 ? '🥉' : `${i+1}.`;
      let row = document.createElement('div');
      row.className = `flex justify-between items-center p-2.5 rounded-[8px] border ${isMe?'bg-[#ff4d00]/10 border-[#ff4d00]/50 text-white':'bg-black border-zinc-800 text-zinc-300'} hitpop`;
      
      let left = document.createElement('span');
      left.textContent = `${medal} ${u.name} ${isMe?'[YOU]':''} • Lv.${u.level}`;
      
      let right = document.createElement('span');
      right.className = 'text-[#ff4d00] font-black';
      right.textContent = `${u.xp} XP`;
      
      row.appendChild(left);
      row.appendChild(right);
      boardEl.appendChild(row);
    });
  }catch{}
}

// ===================================================================
// Plan Check
// ===================================================================
async function checkMyPlan(){
  let ph = localStorage.getItem('genie_phone');
  if(!ph) return;
  try{
    let r = await fetch('/check_plan', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({phone: ph})
    });
    let d = await r.json();
    if(d.plan === 'pro'){
      localStorage.setItem('genie_plan', 'pro');
      isPro = true;
      render();
      showNotification('💎 PRO UNLOCKED! You are now a legend!', 'success');
      playSound('pro');
    }
  }catch{}
}

// ===================================================================
// Payment
// ===================================================================
async function openPay(){
  playSound('empty');
  let ph = localStorage.getItem('genie_phone') || '';
  let n = localStorage.getItem('genie_name') || userName || 'Warrior';

  if(!ph || ph.length !== 10){
    showNotification('📱 Pehle registration me phone daalo!', 'error');
    return;
  }

  try{
    let res = await fetch('/create_order', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ uid: userId, name: n, phone: ph })
    });
    let order = await res.json();

    if(order.error){
      showNotification('❌ ' + order.error, 'error');
      return;
    }

    const options = {
      key: order.key_id,
      amount: order.amount,
      currency: order.currency,
      name: "StudyGenie Pro 🔥",
      description: "Unlimited Ammo + All Features",
      order_id: order.order_id,
      prefill: { name: n, contact: ph },
      theme: { color: "#ff4d00" },
      handler: function(response){
        playSound('pro');
        showNotification('✅ Payment Successful! PRO Unlocked! 🎉', 'success');
        localStorage.setItem('genie_plan', 'pro');
        isPro = true;
        render();
        setTimeout(() => location.reload(), 1500);
      }
    };

    const rzp = new Razorpay(options);
    rzp.open();
  }catch(e){
    showNotification('❌ Error: ' + e.message, 'error');
  }
}

// ===================================================================
// Ask Function
// ===================================================================
function appendUserBubble(q){
  let chat = document.getElementById('chat');
  let wrap = document.createElement('div');
  wrap.className = 'flex justify-end hitpop';
  let bubble = document.createElement('div');
  bubble.className = 'bubble-user px-4 py-2 text-[14px] mono';
  bubble.textContent = q;
  wrap.appendChild(bubble);
  chat.appendChild(wrap);
}

function appendAiBubble(ans){
  let chat = document.getElementById('chat');
  let wrap = document.createElement('div');
  wrap.className = 'flex gap-3 hitpop';
  let img = document.createElement('img');
  img.src = '/sparsh.jpg';
  img.className = 'w-12 h-12 rounded-[10px] border-2 border-[#ff4d00] object-cover';
  let bubble = document.createElement('div');
  bubble.className = 'bubble-ai p-4 max-w-[78%] text-[14px] whitespace-pre-wrap';
  bubble.textContent = ans;
  wrap.appendChild(img);
  wrap.appendChild(bubble);
  chat.appendChild(wrap);
}

async function ask(){
  if(!localStorage.getItem('genie_name') || !localStorage.getItem('genie_phone')){
    checkOnboard(); return;
  }
  
  let input = document.getElementById('q');
  let q = input.value.trim();
  if(!q) return;

  playSound('fire');
  appendUserBubble(q);
  input.value = '';

  let chat = document.getElementById('chat');
  let typing = document.createElement('div');
  typing.id = 'typing';
  typing.className = 'flex gap-3';
  typing.innerHTML = `<img src="/sparsh.jpg" class="w-12 h-12 rounded-[10px] border-2 border-[#ff4d00] object-cover"><div class="bubble-ai p-4 mono text-[12px] text-zinc-400 animate-pulse">> SPARSH SINGHAL'S GENIE LOCKING TARGET...</div>`;
  chat.appendChild(typing);
  chat.scrollTop = chat.scrollHeight;

  try{
    let res = await fetch('/ask', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({q, name:userName, phone:userPhone, uid:userId})
    });
    
    document.getElementById('typing')?.remove();
    let data = await res.json();

    if(res.status === 402 || data.limit_reached){
      playSound('empty');
      appendAiBubble(data.ans || "🔥 AMMO KHATAM! Reload karo!");
      chat.scrollTop = chat.scrollHeight;
      setTimeout(openPay, 2000);
      return;
    }

    // Update stats
    stats.wishes++;
    stats.q1 = Math.min(3, stats.q1 + 1);
    stats.q2 = Math.min(10, stats.q2 + 1);
    stats.xp += 12;
    stats.totalXp = (stats.totalXp || 0) + 12;
    
    if(stats.xp >= 100){
      stats.level++;
      stats.xp = 0;
      playSound('level');
      showNotification(`🎉 LEVEL UP! You are now Level ${stats.level}!`, 'success');
      
      let lvlEl = document.createElement('div');
      lvlEl.className = 'text-center mono text-[#ff4d00] font-black text-[18px] py-2 level-up';
      lvlEl.textContent = `🔥 LEVEL UP - LVL ${stats.level}`;
      chat.appendChild(lvlEl);
    }
    
    save();

    if(data.xp_gained){
      showNotification(`+${data.xp_gained} XP! 🎯`, 'info');
    }
    
    playSound('hit');
    appendAiBubble(data.ans);
    chat.scrollTop = chat.scrollHeight;
    
  }catch(e){
    document.getElementById('typing')?.remove();
    showNotification('❌ Technical glitch! Try again!', 'error');
    appendAiBubble("⚠️ Thoda glitch ho gaya! Dobara try karo - BY SPARSH SINGHAL");
  }
}

// ===================================================================
// Easter Egg
// ===================================================================
document.getElementById('logo').addEventListener('click', () => {
  playSound('click'); c++;
  if(c >= 5){
    let p = prompt("🔐 DEV ACCESS - Code:");
    if(p === "sparsh123"){
      isDev = !isDev;
      localStorage.setItem('isDev', isDev);
      playSound(isDev ? 'level' : 'empty');
      showNotification(isDev ? '🛡️ GOD MODE ON (display only)' : '⚡ GOD MODE OFF', isDev ? 'success' : 'error');
      render();
    } else if(p !== null){ showNotification('⛔ ACCESS DENIED!', 'error'); }
    c = 0;
  }
  setTimeout(() => c = 0, 2000);
});

// ===================================================================
// Initial Chat Message
// ===================================================================
document.getElementById('chat').innerHTML = `
<div class="flex gap-3 hitpop">
  <img src="/sparsh.jpg" class="w-12 h-12 rounded-[10px] border-2 border-[#ff4d00] object-cover">
  <div class="bubble-ai p-5 max-w-[78%] text-[14px] leading-relaxed">
    🔥 <b>OYE WARRIOR, BATTLEFIELD ME SWAGAT HAI!</b><br><br>
    Main hoon <b>Sparsh Singhal ka StudyGenie</b> — har doubt ko headshot dunga! 🔫<br><br>
    💪 <b>Features:</b><br>
    • Unlimited Questions (PRO)<br>
    • 28+ Features<br>
    • Level Up System<br>
    • XP & Rankings<br>
    • Sound Effects 🎵<br><br>
    <span class="mono text-[10px] text-[#ff4d00]">BY SPARSH SINGHAL | 28 FEATURES | SOUND ON 🔊</span>
  </div>
</div>`;

// Initial render
checkOnboard();
render();
loadBoard();
checkMyPlan();

console.log('🔥 StudyGenie Battle Edition loaded!');
console.log('💎 User:', userId);
console.log('📱 Phone:', userPhone);
console.log('⚡ Plan:', isPro ? 'PRO' : 'FREE');
</script>
</body></html>
"""

# ===================================================================
# Application Entry Point
# ===================================================================
if __name__ == "__main__":
    port = config.PORT
    
    # Print startup banner
    print("\n" + "="*60)
    print("🔥 STUDYGENIE BATTLE EDITION 🔥")
    print("="*60)
    print(f"🚀 Version: 2.0 (Production Ready)")
    print(f"📡 Server: 0.0.0.0:{port}")
    print(f"💾 Storage: {'Redis + File' if redis_manager.is_available() else 'File only'}")
    print(f"🤖 AI: {'Active' if config.GOOGLE_API_KEY else 'Inactive'}")
    print(f"💳 Payments: {'Active' if config.RAZORPAY_KEY_ID else 'Inactive'}")
    print(f"🔐 Admin: {'Configured' if config.ADMIN_TOKEN else 'Not configured'}")
    print("="*60)
    print("\n🔥 Fire up your doubts! - SPARSH SINGHAL\n")
    
    try:
        # Try waitress for production
        from waitress import serve
        log.info(f"Starting with waitress on 0.0.0.0:{port}")
        serve(app, host="0.0.0.0", port=port, threads=config.WORKER_THREADS)
    except ImportError:
        # Fallback to Flask development server
        log.info(f"Starting with Flask development server on 0.0.0.0:{port}")
        app.run(host="0.0.0.0", port=port, threaded=True, debug=False)

# ===================================================================
# END OF FILE
# ===================================================================
