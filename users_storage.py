# users_storage.py
import logging

logger = logging.getLogger(__name__)

# تهيئة users_data كمتغير عالمي
users_data = {
    "144262846": {
        "alias": "FJUJ",
        "blocked": False,
        "joined": True,
        "pwd_ok": True,
        "last_msgs": []
    }
}

logger.debug(f"Initialized users_data with {len(users_data)} entries")

def save_users():
    logger.debug(f"Users data preserved in memory, current count: {len(users_data)}")
    return True
