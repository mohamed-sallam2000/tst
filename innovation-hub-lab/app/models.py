import json
import uuid
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db, login_manager


def utc_now():
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc)


class User(db.Model):
    """User model for authentication and authorization."""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='engineer')  # admin, engineer, manager
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    # Relationships
    import_batches = db.relationship('ImportBatch', backref='triggered_by', lazy='dynamic')
    audit_logs = db.relationship('AuditLog', backref='user', lazy='dynamic')
    
    def __repr__(self):
        return f'<User {self.username}>'
    
    def set_password(self, password):
        """Hash and set the user's password."""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if the provided password matches the hash."""
        return check_password_hash(self.password_hash, password)
    
    def get_id(self):
        return str(self.id)
    
    @property
    def is_authenticated(self):
        return True
    
    @property
    def is_anonymous(self):
        return False


@login_manager.user_loader
def load_user(user_id):
    """Load user by ID for Flask-Login."""
    return User.query.get(int(user_id))


class Setting(db.Model):
    """Key-value settings table for application configuration."""
    __tablename__ = 'settings'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    def __repr__(self):
        return f'<Setting {self.key}>'
    
    @classmethod
    def get_value(cls, key, default=None):
        """Get a setting value by key."""
        setting = cls.query.filter_by(key=key).first()
        if setting is None:
            return default
        return setting.value
    
    @classmethod
    def set_value(cls, key, value):
        """Set or update a setting value."""
        setting = cls.query.filter_by(key=key).first()
        if setting is None:
            setting = cls(key=key, value=value)
            db.session.add(setting)
        else:
            setting.value = value
            setting.updated_at = utc_now()
        db.session.commit()
        return setting


class ImportBatch(db.Model):
    """Track Excel import batches."""
    __tablename__ = 'import_batches'
    
    id = db.Column(db.Integer, primary_key=True)
    file_path = db.Column(db.String(500), nullable=False)
    sheet_name = db.Column(db.String(100), nullable=False)
    triggered_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    started_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    finished_at = db.Column(db.DateTime, nullable=True)
    rows_found = db.Column(db.Integer, default=0)
    new_rows = db.Column(db.Integer, default=0)
    duplicates_skipped = db.Column(db.Integer, default=0)
    error_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(30), default='running', nullable=False)  # running, completed, completed_with_errors, failed
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Relationships
    responses = db.relationship('FormResponseRaw', backref='import_batch', lazy='dynamic')
    
    def __repr__(self):
        return f'<ImportBatch {self.id} - {self.status}>'
    
    def mark_completed(self, with_errors=False):
        """Mark the batch as completed."""
        self.finished_at = utc_now()
        self.status = 'completed_with_errors' if with_errors else 'completed'
        db.session.commit()
    
    def mark_failed(self):
        """Mark the batch as failed."""
        self.finished_at = utc_now()
        self.status = 'failed'
        db.session.commit()


class FormResponseRaw(db.Model):
    """Raw form response data from Excel imports."""
    __tablename__ = 'form_response_raw'
    
    id = db.Column(db.Integer, primary_key=True)
    import_batch_id = db.Column(db.Integer, db.ForeignKey('import_batches.id'), nullable=False, index=True)
    response_unique_key = db.Column(db.String(255), nullable=False, index=True)
    row_number = db.Column(db.Integer, nullable=False)
    raw_json = db.Column(db.Text, nullable=False)  # JSON stored as text
    source_file = db.Column(db.String(500), nullable=False)
    sheet_name = db.Column(db.String(100), nullable=False)
    imported_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    parse_status = db.Column(db.String(30), default='new', nullable=False)  # new, imported, duplicate, parse_error, needs_review
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    
    # Relationships
    request = db.relationship('Request', backref='raw_response', uselist=False, lazy='joined')
    
    def __repr__(self):
        return f'<FormResponseRaw {self.response_unique_key} - {self.parse_status}>'
    
    @property
    def data(self):
        """Deserialize raw_json to dict."""
        if self.raw_json:
            return json.loads(self.raw_json)
        return {}
    
    @data.setter
    def data(self, value):
        """Serialize dict to raw_json."""
        self.raw_json = json.dumps(value)


class Request(db.Model):
    """Lab equipment request from form responses."""
    __tablename__ = 'requests'
    
    id = db.Column(db.Integer, primary_key=True)
    human_readable_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    raw_response_id = db.Column(db.Integer, db.ForeignKey('form_response_raw.id'), nullable=True, unique=True)
    request_type = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(30), default='imported', nullable=False)
        # imported, needs_review, active, approved, in_progress, 
        # checked_out, returned, completed, cancelled, closed, recorded
    requester_name = db.Column(db.String(120), nullable=False)
    university_id = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    role = db.Column(db.String(50), nullable=True)
    department = db.Column(db.String(100), nullable=True)
    supervisor_name = db.Column(db.String(120), nullable=True)
    supervisor_email = db.Column(db.String(120), nullable=True)
    desired_datetime = db.Column(db.DateTime, nullable=True)
    urgency = db.Column(db.String(20), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    branch_data_json = db.Column(db.Text, nullable=True)  # JSON stored as text
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    def __repr__(self):
        return f'<Request {self.human_readable_id} - {self.title}>'
    
    @property
    def branch_data(self):
        """Deserialize branch_data_json to dict."""
        if self.branch_data_json:
            return json.loads(self.branch_data_json)
        return {}
    
    @branch_data.setter
    def branch_data(self, value):
        """Serialize dict to branch_data_json."""
        self.branch_data_json = json.dumps(value)


class AuditLog(db.Model):
    """Audit trail for system actions."""
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)
    old_values_json = db.Column(db.Text, nullable=True)  # JSON stored as text
    new_values_json = db.Column(db.Text, nullable=True)  # JSON stored as text
    ip_address = db.Column(db.String(45), nullable=True)  # IPv6 max length
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)
    
    def __repr__(self):
        return f'<AuditLog {self.action} on {self.entity_type}:{self.entity_id}>'
    
    @property
    def old_values(self):
        """Deserialize old_values_json to dict."""
        if self.old_values_json:
            return json.loads(self.old_values_json)
        return {}
    
    @old_values.setter
    def old_values(self, value):
        """Serialize dict to old_values_json."""
        self.old_values_json = json.dumps(value) if value else None
    
    @property
    def new_values(self):
        """Deserialize new_values_json to dict."""
        if self.new_values_json:
            return json.loads(self.new_values_json)
        return {}
    
    @new_values.setter
    def new_values(self, value):
        """Serialize dict to new_values_json."""
        self.new_values_json = json.dumps(value) if value else None
    
    @classmethod
    def log_action(cls, action, entity_type, entity_id=None, old_values=None, 
                   new_values=None, user_id=None, ip_address=None):
        """Create an audit log entry."""
        log = cls(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_values=old_values,
            new_values=new_values,
            user_id=user_id,
            ip_address=ip_address
        )
        db.session.add(log)
        db.session.commit()
        return log


def generate_human_readable_id():
    """Generate a human-readable request ID like REQ-2024-0001."""
    # Get the current year
    year = datetime.now(timezone.utc).year
    
    # Count existing requests for this year
    prefix = f'REQ-{year}-'
    
    # Find the highest number for this year prefix
    last_request = Request.query.filter(
        Request.human_readable_id.like(prefix + '%')
    ).order_by(Request.human_readable_id.desc()).first()
    
    if last_request:
        # Extract the number from the last ID
        try:
            last_num = int(last_request.human_readable_id.split('-')[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1
    
    return f'{prefix}{next_num:04d}'


# =============================================================================
# OPERATIONAL MODELS FOR LAB BRANCHES
# =============================================================================

class Resource(db.Model):
    """Physical resources in the lab (workbenches, lockers, printers, etc.)."""
    __tablename__ = 'resources'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # electronics_workbench, solder_station, tool_locker, printer_3d, other
    location = db.Column(db.String(100), nullable=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', use_alter=True, name='fk_resource_device'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    # Relationships
    device = db.relationship('Device', backref=db.backref('linked_resource', uselist=False, lazy='joined'), 
                             foreign_keys=[device_id])
    workbench_bookings = db.relationship('WorkbenchBooking', backref='assigned_resource', lazy='dynamic', 
                                          foreign_keys='WorkbenchBooking.assigned_resource_id')
    
    def __repr__(self):
        return f'<Resource {self.name} ({self.type})>'


class Device(db.Model):
    """ESP32 or other controllable devices."""
    __tablename__ = 'devices'
    
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(50), unique=True, nullable=False, index=True)  # ESP32 device identifier
    friendly_name = db.Column(db.String(100), nullable=False)
    device_type = db.Column(db.String(50), nullable=False)  # workbench_power, solder_station_power, tool_locker, printer_3d, generic_switch
    resource_id = db.Column(db.Integer, db.ForeignKey('resources.id', use_alter=True, name='fk_device_resource'), nullable=True)
    endpoint_template = db.Column(db.String(500), nullable=False)  # URL template with placeholders
    auth_type = db.Column(db.String(30), default='none', nullable=False)  # none, api_key_header, basic_auth, bearer_token
    auth_secret_reference = db.Column(db.String(255), nullable=True)  # Reference to secret storage
    enabled = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    # Relationships
    command_logs = db.relationship('DeviceCommandLog', backref='device', lazy='dynamic')
    resource = db.relationship('Resource', backref=db.backref('associated_devices', lazy='dynamic'),
                                foreign_keys=[resource_id])
    
    def __repr__(self):
        return f'<Device {self.friendly_name} ({self.device_id})>'
    
    def get_endpoint_url(self, **kwargs):
        """Generate endpoint URL from template with provided parameters."""
        try:
            return self.endpoint_template.format(**kwargs)
        except KeyError:
            return self.endpoint_template


class DeviceCommandLog(db.Model):
    """Log of all commands sent to devices."""
    __tablename__ = 'device_command_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, index=True)
    command_type = db.Column(db.String(50), nullable=False)  # enable, disable, unlock, lock, status, manual_override
    parent_type = db.Column(db.String(50), nullable=True)  # e.g., 'workbench_booking', 'tool_loan'
    parent_id = db.Column(db.Integer, nullable=True)
    triggered_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    request_url = db.Column(db.String(500), nullable=False)
    http_method = db.Column(db.String(10), nullable=False, default='POST')
    request_payload = db.Column(db.Text, nullable=True)  # JSON stored as text
    http_status_code = db.Column(db.Integer, nullable=True)
    response_body = db.Column(db.Text, nullable=True)
    success = db.Column(db.Boolean, default=False)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)
    
    # Relationships
    triggered_by = db.relationship('User', backref='device_commands', lazy='joined')
    
    def __repr__(self):
        return f'<DeviceCommandLog {self.command_type} on device {self.device_id}>'
    
    @property
    def payload(self):
        """Deserialize request_payload to dict."""
        if self.request_payload:
            return json.loads(self.request_payload)
        return {}
    
    @payload.setter
    def payload(self, value):
        """Serialize dict to request_payload."""
        self.request_payload = json.dumps(value) if value else None
    
    @property
    def response(self):
        """Deserialize response_body to dict."""
        if self.response_body:
            return json.loads(self.response_body)
        return {}
    
    @response.setter
    def response(self, value):
        """Serialize dict to response_body."""
        self.response_body = json.dumps(value) if value else None


class WorkbenchBooking(db.Model):
    """Electronics workbench booking requests."""
    __tablename__ = 'workbench_bookings'
    
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('requests.id'), nullable=False, unique=True)
    resource_type = db.Column(db.String(50), nullable=False, default='electronics_workbench')
    booking_mode = db.Column(db.String(30), nullable=False)  # e.g., 'scheduled', 'walk_in'
    preferred_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    time_flexible = db.Column(db.Boolean, default=False)
    accept_alternative_slot = db.Column(db.Boolean, default=False)
    alternative_periods_json = db.Column(db.Text, nullable=True)  # JSON array of alternative periods
    number_of_users = db.Column(db.Integer, default=1)
    preferred_resource_id = db.Column(db.Integer, db.ForeignKey('resources.id'), nullable=True)
    assigned_resource_id = db.Column(db.Integer, db.ForeignKey('resources.id'), nullable=True)
    activity_type = db.Column(db.String(100), nullable=True)
    activity_description = db.Column(db.Text, nullable=True)
    equipment_needed_json = db.Column(db.Text, nullable=True)  # JSON array
    consumables_needed_json = db.Column(db.Text, nullable=True)  # JSON array
    risk_flags_json = db.Column(db.Text, nullable=True)  # JSON array
    risk_details = db.Column(db.Text, nullable=True)
    safety_training_completed = db.Column(db.Boolean, default=False)
    electronics_training_completed = db.Column(db.Boolean, default=False)
    first_time_user = db.Column(db.Boolean, default=False)
    supervision_required = db.Column(db.Boolean, default=False)
    approval_status = db.Column(db.String(30), default='pending')  # pending, approved, rejected, cancelled
    check_in_at = db.Column(db.DateTime, nullable=True)
    check_out_at = db.Column(db.DateTime, nullable=True)
    actual_start_at = db.Column(db.DateTime, nullable=True)
    actual_end_at = db.Column(db.DateTime, nullable=True)
    no_show_flag = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    # Relationships
    request = db.relationship('Request', backref=db.backref('workbench_booking', uselist=False, lazy='joined'))
    preferred_resource = db.relationship('Resource', foreign_keys=[preferred_resource_id], 
                                          backref='preferred_bookings', lazy='joined')
    
    def __repr__(self):
        return f'<WorkbenchBooking {self.request_id} - {self.preferred_date}>'
    
    @property
    def alternative_periods(self):
        """Deserialize alternative_periods_json to list."""
        if self.alternative_periods_json:
            return json.loads(self.alternative_periods_json)
        return []
    
    @alternative_periods.setter
    def alternative_periods(self, value):
        """Serialize list to alternative_periods_json."""
        self.alternative_periods_json = json.dumps(value) if value else None
    
    @property
    def equipment_needed(self):
        """Deserialize equipment_needed_json to list."""
        if self.equipment_needed_json:
            return json.loads(self.equipment_needed_json)
        return []
    
    @equipment_needed.setter
    def equipment_needed(self, value):
        """Serialize list to equipment_needed_json."""
        self.equipment_needed_json = json.dumps(value) if value else None
    
    @property
    def consumables_needed(self):
        """Deserialize consumables_needed_json to list."""
        if self.consumables_needed_json:
            return json.loads(self.consumables_needed_json)
        return []
    
    @consumables_needed.setter
    def consumables_needed(self, value):
        """Serialize list to consumables_needed_json."""
        self.consumables_needed_json = json.dumps(value) if value else None
    
    @property
    def risk_flags(self):
        """Deserialize risk_flags_json to list."""
        if self.risk_flags_json:
            return json.loads(self.risk_flags_json)
        return []
    
    @risk_flags.setter
    def risk_flags(self, value):
        """Serialize list to risk_flags_json."""
        self.risk_flags_json = json.dumps(value) if value else None
    
    def get_duration_display(self):
        """Return duration as human-readable string."""
        hours = self.duration_minutes // 60
        minutes = self.duration_minutes % 60
        if hours > 0 and minutes > 0:
            return f"{hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{minutes}m"


class ToolLoan(db.Model):
    """Tool loan requests and tracking."""
    __tablename__ = 'tool_loans'
    
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('requests.id'), nullable=False, unique=True)
    tool_requested = db.Column(db.String(200), nullable=False)
    tool_not_listed_details = db.Column(db.Text, nullable=True)
    asset_tag_or_locker_id = db.Column(db.String(50), nullable=True)
    quantity = db.Column(db.Integer, default=1)
    checkout_datetime = db.Column(db.DateTime, nullable=False)
    return_datetime = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    extension_possible = db.Column(db.Boolean, default=False)
    usage_location = db.Column(db.String(100), nullable=True)
    off_campus_reason = db.Column(db.Text, nullable=True)
    loan_purpose_category = db.Column(db.String(50), nullable=True)
    loan_purpose_description = db.Column(db.Text, nullable=True)
    additional_users = db.Column(db.Boolean, default=False)
    additional_users_list = db.Column(db.Text, nullable=True)  # JSON array
    training_completed = db.Column(db.Boolean, default=False)
    staff_assistance_needed = db.Column(db.Boolean, default=False)
    supervisor_approval_required = db.Column(db.Boolean, default=False)
    supervisor_name = db.Column(db.String(120), nullable=True)
    supervisor_email = db.Column(db.String(120), nullable=True)
    risk_flags_json = db.Column(db.Text, nullable=True)  # JSON array
    accessories_needed_json = db.Column(db.Text, nullable=True)  # JSON array
    responsibility_agreement = db.Column(db.Boolean, default=False)
    return_policy_agreement = db.Column(db.Boolean, default=False)
    penalty_agreement = db.Column(db.Boolean, default=False)
    emergency_contact_phone = db.Column(db.String(30), nullable=True)
    loan_status = db.Column(db.String(30), default='pending')  # pending, approved, checked_out, returned, overdue, cancelled
    actual_checkout_at = db.Column(db.DateTime, nullable=True)
    actual_return_at = db.Column(db.DateTime, nullable=True)
    return_condition = db.Column(db.String(50), nullable=True)  # good, damaged, lost
    damage_notes = db.Column(db.Text, nullable=True)
    missing_accessories = db.Column(db.Text, nullable=True)  # JSON array
    late_flag = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    # Relationships
    request = db.relationship('Request', backref=db.backref('tool_loan', uselist=False, lazy='joined'))
    
    def __repr__(self):
        return f'<ToolLoan {self.request_id} - {self.tool_requested}>'
    
    @property
    def additional_users_data(self):
        """Deserialize additional_users_list to list."""
        if self.additional_users_list:
            return json.loads(self.additional_users_list)
        return []
    
    @additional_users_data.setter
    def additional_users_data(self, value):
        """Serialize list to additional_users_list."""
        self.additional_users_list = json.dumps(value) if value else None
    
    @property
    def risk_flags(self):
        """Deserialize risk_flags_json to list."""
        if self.risk_flags_json:
            return json.loads(self.risk_flags_json)
        return []
    
    @risk_flags.setter
    def risk_flags(self, value):
        """Serialize list to risk_flags_json."""
        self.risk_flags_json = json.dumps(value) if value else None
    
    @property
    def accessories_needed(self):
        """Deserialize accessories_needed_json to list."""
        if self.accessories_needed_json:
            return json.loads(self.accessories_needed_json)
        return []
    
    @accessories_needed.setter
    def accessories_needed(self, value):
        """Serialize list to accessories_needed_json."""
        self.accessories_needed_json = json.dumps(value) if value else None
    
    @property
    def missing_accessories_data(self):
        """Deserialize missing_accessories to list."""
        if self.missing_accessories:
            return json.loads(self.missing_accessories)
        return []
    
    @missing_accessories_data.setter
    def missing_accessories_data(self, value):
        """Serialize list to missing_accessories."""
        self.missing_accessories = json.dumps(value) if value else None
    
    def get_duration_display(self):
        """Return duration as human-readable string."""
        hours = self.duration_minutes // 60
        minutes = self.duration_minutes % 60
        if hours > 0 and minutes > 0:
            return f"{hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{minutes}m"
    
    def is_overdue(self):
        """Check if the loan is overdue."""
        if self.actual_return_at:
            return False
        return utc_now() > self.return_datetime


class HandToolSession(db.Model):
    """Hand tool session requests."""
    __tablename__ = 'hand_tool_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('requests.id'), nullable=False, unique=True)
    session_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    number_of_users = db.Column(db.Integer, default=1)
    tools_needed_json = db.Column(db.Text, nullable=True)  # JSON array
    other_tools = db.Column(db.String(200), nullable=True)
    quantity_estimate = db.Column(db.Integer, default=1)
    workspace_needed = db.Column(db.Boolean, default=False)
    existing_workbench_booking = db.Column(db.Boolean, default=False)
    workbench_booking_id = db.Column(db.Integer, db.ForeignKey('workbench_bookings.id'), nullable=True)
    purpose = db.Column(db.Text, nullable=True)
    previous_safe_use = db.Column(db.Boolean, default=False)
    staff_assistance_needed = db.Column(db.Boolean, default=False)
    tools_stay_inside_agreement = db.Column(db.Boolean, default=False)
    cleanup_agreement = db.Column(db.Boolean, default=False)
    damage_reporting_agreement = db.Column(db.Boolean, default=False)
    issue_status = db.Column(db.String(30), default='pending')  # pending, active, completed, cancelled
    return_status = db.Column(db.String(30), default='not_returned')  # not_returned, returned, partial
    missing_items_flag = db.Column(db.Boolean, default=False)
    damage_flag = db.Column(db.Boolean, default=False)
    staff_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    # Relationships
    request = db.relationship('Request', backref=db.backref('hand_tool_session', uselist=False, lazy='joined'))
    workbench_booking = db.relationship('WorkbenchBooking', backref='hand_tool_sessions', lazy='joined')
    
    def __repr__(self):
        return f'<HandToolSession {self.request_id} - {self.session_date}>'
    
    @property
    def tools_needed(self):
        """Deserialize tools_needed_json to list."""
        if self.tools_needed_json:
            return json.loads(self.tools_needed_json)
        return []
    
    @tools_needed.setter
    def tools_needed(self, value):
        """Serialize list to tools_needed_json."""
        self.tools_needed_json = json.dumps(value) if value else None
    
    def get_duration_display(self):
        """Return duration as human-readable string."""
        hours = self.duration_minutes // 60
        minutes = self.duration_minutes % 60
        if hours > 0 and minutes > 0:
            return f"{hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{minutes}m"


class StaffRequest(db.Model):
    """Staff assistance or maintenance requests."""
    __tablename__ = 'staff_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('requests.id'), nullable=False, unique=True)
    category = db.Column(db.String(50), nullable=False)  # e.g., maintenance, setup, support
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    desired_outcome = db.Column(db.Text, nullable=True)
    affected_resource = db.Column(db.String(100), nullable=True)
    preferred_datetime = db.Column(db.DateTime, nullable=True)
    deadline = db.Column(db.DateTime, nullable=True)
    priority = db.Column(db.String(20), default='normal')  # low, normal, high, urgent
    number_of_people = db.Column(db.Integer, default=1)
    on_behalf_of_students = db.Column(db.Boolean, default=False)
    responsible_person = db.Column(db.String(120), nullable=True)
    responsible_email = db.Column(db.String(120), nullable=True)
    approval_needed = db.Column(db.Boolean, default=False)
    approver_name = db.Column(db.String(120), nullable=True)
    budget_code = db.Column(db.String(50), nullable=True)
    safety_risk = db.Column(db.Boolean, default=False)
    safety_risk_details = db.Column(db.Text, nullable=True)
    lab_support_needed = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(30), default='submitted')  # submitted, acknowledged, in_progress, completed, cancelled
    internal_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    # Relationships
    request = db.relationship('Request', backref=db.backref('staff_request', uselist=False, lazy='joined'))
    
    def __repr__(self):
        return f'<StaffRequest {self.request_id} - {self.title}>'


class Complaint(db.Model):
    """Complaints and feedback (view-only, no escalation workflow)."""
    __tablename__ = 'complaints'
    
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('requests.id'), nullable=False, unique=True)
    feedback_type = db.Column(db.String(50), nullable=False)  # complaint, suggestion, incident_report
    severity_text = db.Column(db.String(200), nullable=True)
    emergency_response_requested = db.Column(db.Boolean, default=False)
    anonymous_submission = db.Column(db.Boolean, default=False)
    location = db.Column(db.String(100), nullable=True)
    incident_date = db.Column(db.Date, nullable=True)
    incident_time = db.Column(db.Time, nullable=True)
    description = db.Column(db.Text, nullable=False)
    impact = db.Column(db.Text, nullable=True)
    desired_resolution = db.Column(db.Text, nullable=True)
    people_involved = db.Column(db.Text, nullable=True)  # JSON array
    follow_up_requested = db.Column(db.Boolean, default=False)
    preferred_contact_method = db.Column(db.String(30), nullable=True)  # email, phone, in_person
    contact_consent = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(30), default='recorded', nullable=False)  # recorded, viewed
    internal_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    # Relationships
    request = db.relationship('Request', backref=db.backref('complaint', uselist=False, lazy='joined'))
    
    def __repr__(self):
        return f'<Complaint {self.request_id} - {self.feedback_type}>'
    
    @property
    def people_involved_data(self):
        """Deserialize people_involved to list."""
        if self.people_involved:
            return json.loads(self.people_involved)
        return []
    
    @people_involved_data.setter
    def people_involved_data(self, value):
        """Serialize list to people_involved."""
        self.people_involved = json.dumps(value) if value else None


class PrintJob(db.Model):
    """3D printing job tracking."""
    __tablename__ = 'print_jobs'
    
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('requests.id'), nullable=False, unique=True)
    assigned_printer = db.Column(db.String(100), nullable=True)
    assigned_engineer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    job_status = db.Column(db.String(30), default='queued')  # queued, preparing, printing, completed, failed, cancelled
    job_priority = db.Column(db.String(20), default='normal')  # low, normal, high
    part_name = db.Column(db.String(200), nullable=False)
    print_file_name = db.Column(db.String(255), nullable=True)
    material_requested = db.Column(db.String(50), nullable=True)  # PLA, PETG, ABS, etc.
    color_requested = db.Column(db.String(50), nullable=True)
    quantity = db.Column(db.Integer, default=1)
    estimated_duration_minutes = db.Column(db.Integer, nullable=True)
    actual_start_at = db.Column(db.DateTime, nullable=True)
    actual_end_at = db.Column(db.DateTime, nullable=True)
    actual_print_duration_minutes = db.Column(db.Integer, nullable=True)
    design_preparation_duration_minutes = db.Column(db.Integer, default=0)
    setup_duration_minutes = db.Column(db.Integer, default=0)
    total_reported_duration_minutes = db.Column(db.Integer, nullable=True)
    print_result_status = db.Column(db.String(30), nullable=True)  # success, partial_failure, complete_failure
    actual_material_used = db.Column(db.String(50), nullable=True)
    actual_material_color = db.Column(db.String(50), nullable=True)
    balance_weight_grams = db.Column(db.Float, nullable=True)
    engineer_notes = db.Column(db.Text, nullable=True)
    completed_by_engineer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    # Relationships
    request = db.relationship('Request', backref=db.backref('print_job', uselist=False, lazy='joined'))
    assigned_engineer = db.relationship('User', foreign_keys=[assigned_engineer_id], 
                                         backref='assigned_print_jobs', lazy='joined')
    completed_by = db.relationship('User', foreign_keys=[completed_by_engineer_id], 
                                    backref='completed_print_jobs', lazy='joined')
    
    def __repr__(self):
        return f'<PrintJob {self.request_id} - {self.part_name}>'
    
    def get_estimated_duration_display(self):
        """Return estimated duration as human-readable string."""
        if not self.estimated_duration_minutes:
            return "TBD"
        hours = self.estimated_duration_minutes // 60
        minutes = self.estimated_duration_minutes % 60
        if hours > 0 and minutes > 0:
            return f"{hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{minutes}m"
    
    def get_actual_duration_display(self):
        """Return actual duration as human-readable string."""
        if not self.actual_print_duration_minutes:
            return "N/A"
        hours = self.actual_print_duration_minutes // 60
        minutes = self.actual_print_duration_minutes % 60
        if hours > 0 and minutes > 0:
            return f"{hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{minutes}m"


class Photo(db.Model):
    """Photo attachments for various entities."""
    __tablename__ = 'photos'
    
    id = db.Column(db.Integer, primary_key=True)
    parent_type = db.Column(db.String(50), nullable=False)  # e.g., 'request', 'tool_loan', 'print_job', 'complaint'
    parent_id = db.Column(db.Integer, nullable=False, index=True)
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    storage_path = db.Column(db.String(500), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False)
    file_hash = db.Column(db.String(64), nullable=True, index=True)  # SHA-256 hash
    photo_note = db.Column(db.Text, nullable=True)
    balance_weight_grams = db.Column(db.Float, nullable=True)
    keep_permanently = db.Column(db.Boolean, default=False)
    retention_policy = db.Column(db.String(30), default='temporary_30_days', nullable=False)  # permanent, temporary_30_days
    delete_after_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    deletion_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    # Relationships
    uploaded_by = db.relationship('User', foreign_keys=[uploaded_by_user_id], 
                                   backref='uploaded_photos', lazy='joined')
    deleted_by = db.relationship('User', foreign_keys=[deleted_by_user_id], 
                                  backref='deleted_photos', lazy='joined')
    
    def __repr__(self):
        return f'<Photo {self.id} - {self.original_filename}>'
    
    def get_size_display(self):
        """Return file size in human-readable format."""
        if self.size_bytes < 1024:
            return f"{self.size_bytes} B"
        elif self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        elif self.size_bytes < 1024 * 1024 * 1024:
            return f"{self.size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{self.size_bytes / (1024 * 1024 * 1024):.1f} GB"
    
    def is_deleted(self):
        """Check if the photo has been deleted."""
        return self.deleted_at is not None
    
    def should_be_deleted(self):
        """Check if the photo should be deleted based on retention policy."""
        if self.keep_permanently or self.retention_policy == 'permanent':
            return False
        if self.delete_after_at:
            return utc_now() > self.delete_after_at
        return False
