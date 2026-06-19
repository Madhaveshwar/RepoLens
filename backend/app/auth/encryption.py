from cryptography.fernet import Fernet
from backend.app.config import settings

class Encryptor:
    def __init__(self):
        self._initialized = False
        self._cipher = None
        if settings.ENCRYPTION_KEY:
            try:
                self._cipher = Fernet(settings.ENCRYPTION_KEY.encode())
                self._initialized = True
            except Exception:
                self._initialized = False

    def encrypt(self, plain_text: str) -> str:
        if not plain_text:
            return ""
        if not self._initialized:
            raise RuntimeError(
                "ENCRYPTION_KEY is not configured. "
                "Please set a valid Fernet key in your .env file."
            )
        return self._cipher.encrypt(plain_text.encode()).decode()

    def decrypt(self, cipher_text: str) -> str:
        if not cipher_text:
            return ""
        if not self._initialized:
            raise RuntimeError(
                "ENCRYPTION_KEY is not configured. "
                "Please set a valid Fernet key in your .env file."
            )
        try:
            return self._cipher.decrypt(cipher_text.encode()).decode()
        except Exception:
            return ""

    @property
    def is_initialized(self) -> bool:
        return self._initialized

encryptor = Encryptor()
