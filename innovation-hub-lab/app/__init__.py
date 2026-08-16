import os
import logging
from flask import Flask, flash, redirect, url_for, render_template
from app.config import Config
from app.extensions import db, login_manager, init_extensions
from app.models import User


def create_app(config_class=Config):
    """Application factory for creating Flask app instances."""
    
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Ensure required directories exist
    ensure_directories(app)
    
    # Configure logging
    configure_logging(app)
    
    # Initialize extensions
    init_extensions(app)
    
    # Register blueprints
    register_blueprints(app)
    
    # Register CLI commands
    register_cli_commands(app)
    
    # Create database tables
    with app.app_context():
        db.create_all()
    
    # Error handlers
    register_error_handlers(app)
    
    return app


def ensure_directories(app):
    """Create required directories if they don't exist."""
    directories = [
        app.instance_path,
        app.config['STORAGE_PATH'],
        app.config['PHOTO_STORAGE_PATH'],
        'data'
    ]
    
    for directory in directories:
        if not os.path.isabs(directory):
            directory = os.path.join(app.root_path, '..', directory)
        
        os.makedirs(directory, exist_ok=True)


def configure_logging(app):
    """Configure application logging."""
    log_level = getattr(logging, app.config.get('LOG_LEVEL', 'INFO'))
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    
    # File handler (in instance folder)
    log_file = os.path.join(app.instance_path, 'app.log')
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(log_level)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    
    # Add handlers to app logger
    app.logger.addHandler(console_handler)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(log_level)
    
    app.logger.info('Innovation Hub Lab Management System starting...')


def register_blueprints(app):
    """Register Flask blueprints."""
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')


def register_cli_commands(app):
    """Register Flask CLI commands."""
    
    @app.cli.command('init-db')
    def init_db():
        """Initialize the database, creating all tables."""
        from app.models import (User, Setting, ImportBatch, FormResponseRaw, Request, AuditLog,
                                Resource, Device, DeviceCommandLog, WorkbenchBooking, ToolLoan,
                                HandToolSession, StaffRequest, Complaint, PrintJob, Photo)
        db.create_all()
        print('Database initialized successfully.')
        print('All 16 tables created:')
        print('  - users')
        print('  - settings')
        print('  - import_batches')
        print('  - form_response_raw')
        print('  - requests')
        print('  - audit_logs')
        print('  - resources')
        print('  - devices')
        print('  - device_command_logs')
        print('  - workbench_bookings')
        print('  - tool_loans')
        print('  - hand_tool_sessions')
        print('  - staff_requests')
        print('  - complaints')
        print('  - print_jobs')
        print('  - photos')
    
    @app.cli.command('seed-admin')
    def seed_admin():
        """Create a default admin user if one doesn't exist."""
        import os
        from app.models import User
        
        # Check if admin already exists
        admin = User.query.filter_by(username='admin').first()
        if admin:
            print('Admin user already exists.')
            return
        
        # Get password from environment variable
        password = os.environ.get('ADMIN_DEFAULT_PASSWORD', 'admin123')
        
        # Create admin user
        admin = User(
            username='admin',
            full_name='System Administrator',
            role='admin',
            is_active=True
        )
        admin.set_password(password)
        
        db.session.add(admin)
        db.session.commit()
        
        print(f'Admin user created successfully with username "admin".')
        print(f'Password: {password}')
        print('Please change this password after first login!')


def register_error_handlers(app):
    """Register error handlers."""
    
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('errors/500.html'), 500
