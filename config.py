import os
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv

# Load environment variables from .env file
root_dir = Path(__file__).parent.resolve()
env_path = root_dir / '.env'
load_dotenv(dotenv_path=env_path)

if not os.environ.get('ENCRYPTION_KEY'):
    # Default development key (also set in .env but this is a fallback)
    os.environ['ENCRYPTION_KEY'] = 'Ow6ktlaGMZ2cYK2DskXsJe0xi39e_Mur_rw-z2OgVVI='


class Config:
    """Base configuration class"""
    
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Database configuration
    # Support both old DATABASE_URL format and new separate PostgreSQL variables
    if os.environ.get('DATABASE_URL'):
        SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    elif all([
        os.environ.get('POSTGRESQL_HOST'),
        os.environ.get('POSTGRESQL_USER'),
        os.environ.get('POSTGRESQL_PASSWORD'),
        os.environ.get('POSTGRESQL_DBNAME')
    ]):
        # Build PostgreSQL connection string from separate variables
        host = os.environ.get('POSTGRESQL_HOST')
        port = os.environ.get('POSTGRESQL_PORT', '5432')
        user = os.environ.get('POSTGRESQL_USER')
        password = os.environ.get('POSTGRESQL_PASSWORD')
        dbname = os.environ.get('POSTGRESQL_DBNAME')
        # URL-encode password to handle special characters
        password_encoded = quote_plus(password)
        # Use require mode - requires SSL but doesn't verify certificate
        # This is safer than disable but works without certificate files
        SQLALCHEMY_DATABASE_URI = f'postgresql://{user}:{password_encoded}@{host}:{port}/{dbname}?sslmode=require'
        # SQLALCHEMY connection pool settings for PostgreSQL
        # These settings help handle connection drops and timeouts
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_size': 5,  # Number of connections to maintain
            'max_overflow': 10,  # Maximum number of connections beyond pool_size
            'pool_timeout': 20,  # Seconds to wait before giving up on getting a connection
            'pool_recycle': 3600,  # Recycle connections after 1 hour (prevents stale connections)
            'pool_pre_ping': True,  # Verify connections before using them (handles dropped connections)
            'connect_args': {
                'connect_timeout': 10,  # Connection timeout in seconds
                'keepalives': 1,  # Enable TCP keepalives
                'keepalives_idle': 30,  # Seconds before sending first keepalive
                'keepalives_interval': 10,  # Seconds between keepalives
                'keepalives_count': 5,  # Number of keepalives before considering connection dead
            }
        }
    else:
        SQLALCHEMY_DATABASE_URI = 'sqlite:///darkzone.db'
        SQLALCHEMY_ENGINE_OPTIONS = {}
    
    # Security
    CSRF_ENABLED = os.environ.get('CSRF_ENABLED', 'True').lower() == 'true'
    WTF_CSRF_ENABLED = CSRF_ENABLED
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = os.environ.get('SESSION_COOKIE_HTTPONLY', 'True').lower() == 'true'
    SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
    WTF_CSRF_TIME_LIMIT = None
    
    # Encryption
    ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
    
    # Telegram
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    TELEGRAM_ADMIN_IDS = [int(uid.strip()) for uid in os.environ.get('TELEGRAM_ADMIN_IDS', '').split(',') if uid.strip()]
    
    # Site Configuration
    SITE_NAME = os.environ.get('SITE_NAME', 'DarkZone')
    SITE_URL = os.environ.get('SITE_URL', 'http://localhost:5000')
    CURRENCY_NAME = os.environ.get('CURRENCY_NAME', 'Ядра')
    
    # Payment Systems
    YOOKASSA_SHOP_ID = os.environ.get('YOOKASSA_SHOP_ID')
    YOOKASSA_SECRET_KEY = os.environ.get('YOOKASSA_SECRET_KEY')
    YOOKASSA_ENABLED = os.environ.get('YOOKASSA_ENABLED', 'False').lower() == 'true'
    
    # Crypto Bot Payment System
    CRYPTO_BOT_API_TOKEN = os.environ.get('CRYPTO_BOT_API_TOKEN')  # Format: APP_ID:BOT_TOKEN
    CRYPTO_BOT_ENABLED = os.environ.get('CRYPTO_BOT_ENABLED', 'False').lower() == 'true'
    
    # Platega Payment System
    PLATEGA_MERCHANT_ID = os.environ.get('PLATEGA_MERCHANT_ID') or '394cba79-219f-4d48-8c16-cd78bf9fe48c'
    PLATEGA_API_KEY = os.environ.get('PLATEGA_API_KEY') or 'Yg4dY8msqqCozVdRskqwUhqNffUIIwYrhFmNvAgqm2HSFQ841EmasBBGqUCvCTuzQC7vYuVb9euA9mpM2I0D5VpYeBK7eDDe3zo2'
    PLATEGA_ENABLED = os.environ.get('PLATEGA_ENABLED', 'True').lower() == 'true'
    
    # Digiseller
    DIGISELLER_API_KEY = os.environ.get('DIGISELLER_API_KEY')
    DIGISELLER_SELLER_ID = os.environ.get('DIGISELLER_SELLER_ID', '0')
    DIGISELLER_ENABLED = os.environ.get('DIGISELLER_ENABLED', 'False').lower() == 'true'
    
    # Email Configuration
    SMTP_HOST = os.environ.get('SMTP_HOST')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    SMTP_USER = os.environ.get('SMTP_USER')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
    SMTP_USE_TLS = os.environ.get('SMTP_USE_TLS', 'True').lower() == 'true'
    
    # Uploads
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    
    # Security - Admin IP Whitelist
    ADMIN_IP_WHITELIST = os.environ.get('ADMIN_IP_WHITELIST', '').split(',') if os.environ.get('ADMIN_IP_WHITELIST') else []
    
    # Security - Re-authentication threshold (balance change amount)
    REAUTH_BALANCE_THRESHOLD = float(os.environ.get('REAUTH_BALANCE_THRESHOLD', 1000.0))
    
    # Security - Rate Limiting
    RATELIMIT_STORAGE_URL = os.environ.get('RATELIMIT_STORAGE_URL', 'memory://')
    
    # Security - Talisman (HTTP Headers)
    TALISMAN_FORCE_HTTPS = os.environ.get('TALISMAN_FORCE_HTTPS', 'False').lower() == 'true'
    
    # Bot Protection (Cloudflare Turnstile)
    TURNSTILE_SITE_KEY = os.environ.get('TURNSTILE_SITE_KEY', '0x4AAAAAAAxL-X-y-X-y-X-y') # Default testing key
    TURNSTILE_SECRET_KEY = os.environ.get('TURNSTILE_SECRET_KEY', '1x0000000000000000000000000000000AA') # Default testing key


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
