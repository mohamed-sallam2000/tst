import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file
load_dotenv()

# Get the base directory (project root)
BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """Application configuration class."""
    
    # Security
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # Database - use absolute path for SQLite
    instance_dir = BASE_DIR / 'instance'
    instance_dir.mkdir(exist_ok=True)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'SQLALCHEMY_DATABASE_URI', 
        f'sqlite:///{instance_dir}/app.db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Excel Configuration
    EXCEL_FILE_PATH = os.environ.get('EXCEL_FILE_PATH', str(BASE_DIR / 'data' / 'responses.xlsx'))
    EXCEL_SHEET_NAME = os.environ.get('EXCEL_SHEET_NAME', 'Sheet1')
    EXCEL_HEADER_ROW = int(os.environ.get('EXCEL_HEADER_ROW', '1'))
    
    # Storage Paths - use absolute paths
    STORAGE_PATH = os.environ.get('STORAGE_PATH', str(BASE_DIR / 'storage'))
    PHOTO_STORAGE_PATH = os.environ.get('PHOTO_STORAGE_PATH', str(BASE_DIR / 'storage' / 'photos'))
    
    # ESP32 Configuration
    ESP_TIMEOUT_SECONDS = int(os.environ.get('ESP_TIMEOUT_SECONDS', '10'))
    ESP_RETRY_COUNT = int(os.environ.get('ESP_RETRY_COUNT', '3'))
    
    # Photo Retention
    PHOTO_RETENTION_DAYS = int(os.environ.get('PHOTO_RETENTION_DAYS', '30'))
    PHOTO_DELETION_HOUR = int(os.environ.get('PHOTO_DELETION_HOUR', '2'))
    
    # Logging
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
