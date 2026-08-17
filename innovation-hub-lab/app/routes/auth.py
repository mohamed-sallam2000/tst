from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User
from app.extensions import db
from functools import wraps

auth_bp = Blueprint('auth', __name__)


def engineer_required(f):
    """Decorator to require engineer role or above."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))
        
        if current_user.role not in ['admin', 'engineer']:
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('main.index'))
        
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator to require admin role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))
        
        if current_user.role != 'admin':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('main.index'))
        
        return f(*args, **kwargs)
    return decorated_function


def manager_or_above(f):
    """Decorator to require manager role or above (manager, admin)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))
        
        if current_user.role not in ['admin', 'manager']:
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('main.index'))
        
        return f(*args, **kwargs)
    return decorated_function


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login page."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            flash('Please enter both username and password.', 'warning')
            return render_template('auth/login.html')
        
        user = User.query.filter_by(username=username).first()
        
        if user is None:
            flash('Invalid username or password.', 'danger')
            return render_template('auth/login.html')
        
        if not user.check_password(password):
            flash('Invalid username or password.', 'danger')
            return render_template('auth/login.html')
        
        if not user.is_active:
            flash('Your account has been deactivated. Please contact an administrator.', 'danger')
            return render_template('auth/login.html')
        
        login_user(user)
        flash(f'Welcome back, {user.full_name}!', 'success')
        
        # Redirect to dashboard after successful login
        next_page = request.args.get('next')
        if next_page:
            return redirect(next_page)
        return redirect(url_for('main.dashboard'))
    
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """User logout."""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))
