from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import User, AuditLog
from app.extensions import db
from app.routes.auth import admin_required, engineer_required, manager_or_above
import datetime

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Home page."""
    return render_template('index.html')


@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Dashboard - accessible by all authenticated users."""
    return render_template('dashboard/dashboard.html')


@main_bp.route('/requests')
@login_required
def requests():
    """Requests page - accessible by admin, engineer, manager."""
    return render_template('requests/requests.html')


@main_bp.route('/import')
@login_required
@engineer_required
def import_data():
    """Import page - accessible by admin, engineer."""
    return render_template('import/import.html')


@main_bp.route('/print-jobs')
@login_required
@engineer_required
def print_jobs():
    """Print Jobs page - accessible by admin, engineer."""
    return render_template('print_jobs/print_jobs.html')


@main_bp.route('/devices')
@login_required
@engineer_required
def devices():
    """Devices page - accessible by admin, engineer."""
    return render_template('devices/devices.html')


@main_bp.route('/reports')
@login_required
@manager_or_above
def reports():
    """Reports page - accessible by admin, manager."""
    return render_template('reports/reports.html')


@main_bp.route('/settings')
@login_required
@admin_required
def settings():
    """Settings page - accessible by admin only."""
    return render_template('settings/settings.html')


@main_bp.route('/users', methods=['GET', 'POST'])
@login_required
@admin_required
def users():
    """User management page - accessible by admin only.
    
    Admin can:
    - Create new users
    - Reset passwords
    - Activate/deactivate users
    - Cannot delete the last active admin
    """
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'create':
            return _create_user()
        elif action == 'reset_password':
            return _reset_password()
        elif action == 'toggle_active':
            return _toggle_user_active()
    
    # GET request - list all users
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('users/users.html', users=users)


def _create_user():
    """Handle user creation."""
    username = request.form.get('username', '').strip()
    full_name = request.form.get('full_name', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role', 'engineer')
    
    # Validate inputs
    if not username or not full_name or not password:
        flash('Username, full name, and password are required.', 'danger')
        return redirect(url_for('main.users'))
    
    if role not in ['admin', 'engineer', 'manager']:
        flash('Invalid role selected.', 'danger')
        return redirect(url_for('main.users'))
    
    # Check if username already exists
    if User.query.filter_by(username=username).first():
        flash(f'Username "{username}" already exists.', 'danger')
        return redirect(url_for('main.users'))
    
    # Create new user
    user = User(
        username=username,
        full_name=full_name,
        role=role,
        is_active=True
    )
    user.set_password(password)
    
    db.session.add(user)
    db.session.commit()
    
    # Log the action
    AuditLog.log_action(
        action='user_created',
        entity_type='User',
        entity_id=user.id,
        new_values={'username': username, 'role': role},
        user_id=current_user.id,
        ip_address=request.remote_addr
    )
    
    flash(f'User "{username}" created successfully.', 'success')
    return redirect(url_for('main.users'))


def _reset_password():
    """Handle password reset."""
    user_id = request.form.get('user_id')
    new_password = request.form.get('new_password', '')
    
    if not user_id or not new_password:
        flash('User ID and new password are required.', 'danger')
        return redirect(url_for('main.users'))
    
    user = User.query.get(int(user_id))
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('main.users'))
    
    old_role = user.role
    user.set_password(new_password)
    db.session.commit()
    
    # Log the action
    AuditLog.log_action(
        action='password_reset',
        entity_type='User',
        entity_id=user.id,
        new_values={'username': user.username},
        user_id=current_user.id,
        ip_address=request.remote_addr
    )
    
    flash(f'Password reset for user "{user.username}".', 'success')
    return redirect(url_for('main.users'))


def _toggle_user_active():
    """Handle activating/deactivating a user."""
    user_id = request.form.get('user_id')
    
    if not user_id:
        flash('User ID is required.', 'danger')
        return redirect(url_for('main.users'))
    
    user = User.query.get(int(user_id))
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('main.users'))
    
    # Prevent deactivating the last active admin
    if user.role == 'admin' and not user.is_active:
        # This is actually activating, which is fine
        pass
    elif user.role == 'admin' and user.is_active:
        # Check if this is the last active admin
        active_admins = User.query.filter_by(role='admin', is_active=True).count()
        if active_admins <= 1:
            flash('Cannot deactivate the last active admin.', 'danger')
            return redirect(url_for('main.users'))
    
    user.is_active = not user.is_active
    db.session.commit()
    
    status = 'activated' if user.is_active else 'deactivated'
    
    # Log the action
    AuditLog.log_action(
        action=f'user_{status}',
        entity_type='User',
        entity_id=user.id,
        new_values={'username': user.username, 'is_active': user.is_active},
        user_id=current_user.id,
        ip_address=request.remote_addr
    )
    
    flash(f'User "{user.username}" {status}.', 'success')
    return redirect(url_for('main.users'))
