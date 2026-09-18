# AWS EC2 Deployment Guide

## Overview

This guide provides complete instructions for deploying the OKX SOL/USDT trading bot on AWS EC2.

**Target Configuration**:
- Instance: t3.micro (1 GB RAM) or t3.small (2 GB RAM)
- OS: Ubuntu 22.04 LTS or Amazon Linux 2023
- Python: 3.11+
- Timezone: UTC
- Storage: 20 GB GP2/GP3

**Estimated Cost**: ~$7-15/month depending on instance type and region.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [EC2 Instance Setup](#ec2-instance-setup)
3. [Security Configuration](#security-configuration)
4. [System Preparation](#system-preparation)
5. [Python Environment Setup](#python-environment-setup)
6. [Application Installation](#application-installation)
7. [Systemd Service Configuration](#systemd-service-configuration)
8. [Environment Variables](#environment-variables)
9. [Logging Setup](#logging-setup)
10. [Operations Guide](#operations-guide)
11. [Monitoring & Alerts](#monitoring--alerts)
12. [Backup & Recovery](#backup--recovery)
13. [Troubleshooting](#troubleshooting)

---

## 1. Prerequisites

### Required

- AWS Account with appropriate permissions
- SSH key pair for EC2 access
- OKX API credentials (trade-only permissions)
- Basic Linux command-line knowledge

### Recommended

- AWS CLI installed locally
- IAM user with limited EC2 permissions
- CloudWatch account for log aggregation
- Domain name for potential future use

---

## 2. EC2 Instance Setup

### Step 1: Launch Instance

1. **Navigate to EC2 Console**
   - Go to https://console.aws.amazon.com/ec2/
   - Click "Launch Instance"

2. **Choose AMI**
   - Search for "Ubuntu Server 22.04 LTS"
   - Select 64-bit (x86)
   - Alternative: Amazon Linux 2023

3. **Choose Instance Type**
   - Select `t3.micro` (1 vCPU, 1 GB RAM) minimum
   - Recommended: `t3.small` (1 vCPU, 2 GB RAM)
   - For heavier workloads: `t3.medium` (2 vCPU, 4 GB RAM)

4. **Configure Instance Details**
   - Number of instances: 1
   - Network: Default VPC (or your custom VPC)
   - Subnet: Any (for single instance)
   - Auto-assign Public IP: Enable
   - IAM role: None (or create minimal role if using Secrets Manager)

5. **Add Storage**
   - Root volume: 20 GB GP2/GP3
   - Encryption: Optional (recommended for production)

6. **Add Tags** (Optional but recommended)
   ```
   Key: Name
   Value: okx-sol-bot
   
   Key: Environment
   Value: production
   
   Key: Application
   Value: crypto-trading-bot
   ```

7. **Configure Security Group** (see next section)

8. **Key Pair**
   - Select existing key pair OR create new
   - Download `.pem` file if creating new
   - Set permissions: `chmod 400 your-key.pem`

### Step 2: Note Instance Details

After launch, record:
- Instance ID: `i-xxxxxxxxx`
- Public IP: `xx.xxx.xxx.xxx`
- Public DNS: `ec2-xx-xxx-xxx-xxx.compute-1.amazonaws.com`

---

## 3. Security Configuration

### Security Group Rules

Create security group with these rules:

| Type | Protocol | Port Range | Source | Description |
|------|----------|------------|--------|-------------|
| SSH | TCP | 22 | Your IP only | SSH access from trusted IP |

**DO NOT** open:
- Any other inbound ports
- All traffic from 0.0.0.0/0
- Database ports

### SSH Hardening

After initial connection, harden SSH:

```bash
# SSH into instance
ssh -i your-key.pem ubuntu@your-ec2-ip

# Backup SSH config
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak

# Edit SSH config
sudo nano /etc/ssh/sshd_config

# Ensure these settings:
Port 22
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2

# Restart SSH service
sudo systemctl restart sshd
```

### Additional Security Measures

```bash
# Install fail2ban
sudo apt update
sudo apt install -y fail2ban

# Configure fail2ban for SSH
sudo cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local
sudo nano /etc/fail2ban/jail.local

# Add/modify:
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600

# Start fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

---

## 4. System Preparation

### Update System

```bash
# Update package lists
sudo apt update

# Upgrade installed packages
sudo apt upgrade -y

# Install essential tools
sudo apt install -y \
    git \
    curl \
    wget \
    htop \
    ufw \
    python3-pip \
    sqlite3 \
    jq \
    gnupg
```

### Configure Timezone

```bash
# Set timezone to UTC
sudo timedatectl set-timezone UTC

# Verify
timedatectl status

# Ensure NTP is running
sudo systemctl enable systemd-timesyncd
sudo systemctl start systemd-timesyncd
timedatectl timesync-status
```

### Create Service User

```bash
# Create dedicated user for bot
sudo adduser --disabled-password --gecos "" tradingbot

# Create directories
sudo mkdir -p /opt/okx-sol-bot
sudo mkdir -p /var/log/okx-sol-bot
sudo mkdir -p /var/lib/okx-sol-bot

# Set ownership
sudo chown -R tradingbot:tradingbot /opt/okx-sol-bot
sudo chown -R tradingbot:tradingbot /var/log/okx-sol-bot
sudo chown -R tradingbot:tradingbot /var/lib/okx-sol-bot

# Set permissions
sudo chmod 750 /opt/okx-sol-bot
sudo chmod 750 /var/log/okx-sol-bot
sudo chmod 750 /var/lib/okx-sol-bot
```

### Configure Firewall (UFW)

```bash
# Enable UFW
sudo ufw enable

# Allow SSH (IMPORTANT: do this first!)
sudo ufw allow from YOUR_IP_ADDRESS to any port 22

# Deny all other incoming
sudo ufw default deny incoming

# Allow outgoing
sudo ufw default allow outgoing

# Check status
sudo ufw status verbose
```

---

## 5. Python Environment Setup

### Install Python 3.11

For Ubuntu 22.04:

```bash
# Install Python 3.11
sudo apt install -y python3.11 python3.11-venv python3.11-dev python3.11-distutils

# Verify installation
python3.11 --version

# Set as default alternative (optional)
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
```

For Amazon Linux 2023:

```bash
# Install Python 3.11
sudo dnf install -y python3.11 python3.11-pip python3.11-devel

# Verify
python3.11 --version
```

### Create Virtual Environment

```bash
# Switch to tradingbot user
sudo su - tradingbot

# Navigate to app directory
cd /opt/okx-sol-bot

# Create virtual environment
python3.11 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Verify Python version
python --version  # Should show 3.11.x
pip --version
```

---

## 6. Application Installation

### Clone Repository

```bash
# As tradingbot user
cd /opt/okx-sol-bot

# Clone repository (replace with your repo URL)
git clone <repository-url> .

# Or copy files manually
# Upload via SCP or SFTP
```

### Install Dependencies

```bash
# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install requirements
pip install -r requirements.txt

# Verify installations
python -c "import ccxt; print(ccxt.__version__)"
python -c "import pandas; print(pandas.__version__)"
```

### Initialize Database

```bash
# Run database initialization
python database.py

# Verify database created
ls -la /var/lib/okx-sol-bot/trading.db
```

---

## 7. Systemd Service Configuration

### Create Service File

```bash
# Copy service file to systemd directory
sudo cp /opt/okx-sol-bot/okx_sol_bot.service /etc/systemd/system/

# Review and edit if needed
sudo nano /etc/systemd/system/okx_sol_bot.service
```

Service file content (`okx_sol_bot.service`):

```ini
[Unit]
Description=OKX SOL/USDT Trading Bot
Documentation=https://github.com/your-repo/okx-sol-bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=tradingbot
Group=tradingbot
WorkingDirectory=/opt/okx-sol-bot
Environment="PATH=/opt/okx-sol-bot/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EnvironmentFile=/opt/okx-sol-bot/.env
ExecStart=/opt/okx-sol-bot/venv/bin/python main.py
Restart=on-failure
RestartSec=30
StandardOutput=append:/var/log/okx-sol-bot/bot.log
StandardError=append:/var/log/okx-sol-bot/bot.error.log

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/var/lib/okx-sol-bot /var/log/okx-sol-bot

# Resource limits
MemoryLimit=512M
CPUQuota=50%

[Install]
WantedBy=multi-user.target
```

### Enable and Start Service

```bash
# Reload systemd daemon
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable okx_sol_bot

# Start service
sudo systemctl start okx_sol_bot

# Check status
sudo systemctl status okx_sol_bot

# View logs
sudo journalctl -u okx_sol_bot -f
```

---

## 8. Environment Variables

### Create .env File

```bash
# As tradingbot user
cd /opt/okx-sol-bot
cp .env.example .env
nano .env
```

### Environment Template

```bash
# TRADING MODE (MUST be 'demo' initially)
TRADING_MODE=demo

# OKX API CREDENTIALS (NEVER commit these)
OKX_API_KEY=your_api_key_here
OKX_API_SECRET=your_api_secret_here
OKX_PASSPHRASE=your_passphrase_here

# RISK PARAMETERS (defaults shown)
MAX_CAPITAL_USDT=1000
RISK_PER_TRADE_PCT=1.0
MAX_POSITION_NOTIONAL_PCT=35
DAILY_MAX_LOSS_PCT=2.0
WEEKLY_MAX_LOSS_PCT=4.0
MONTHLY_MAX_DRAWDOWN_PCT=6.0

# STRATEGY PARAMETERS
EMA_SHORT_PERIOD=20
EMA_LONG_PERIOD=50
RSI_PERIOD=14
RSI_MIN=55.0
ADX_MIN=20.0
ATR_MULTIPLIER=1.5

# LOGGING
LOG_LEVEL=INFO
LOG_TO_FILE=true
LOG_DIR=/var/log/okx-sol-bot

# DATABASE
DATABASE_PATH=/var/lib/okx-sol-bot/trading.db
```

### Security Best Practices

**Option A: Environment File (simpler)**
```bash
# Set restrictive permissions
chmod 600 /opt/okx-sol-bot/.env
chown tradingbot:tradingbot /opt/okx-sol-bot/.env
```

**Option B: AWS Secrets Manager (more secure)**

```bash
# Install AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Create secret
aws secretsmanager create-secret \
    --name okx-sol-bot-credentials \
    --secret-string '{"OKX_API_KEY":"xxx","OKX_API_SECRET":"xxx","OKX_PASSPHRASE":"xxx"}'

# Create IAM policy for EC2 role
# Attach role to instance

# Modify application to fetch secrets at startup
```

---

## 9. Logging Setup

### Log Rotation

```bash
# Create logrotate config
sudo nano /etc/logrotate.d/okx-sol-bot

# Content:
/var/log/okx-sol-bot/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 tradingbot tradingbot
    postrotate
        systemctl reload okx_sol_bot 2>/dev/null || true
    endscript
}
```

### CloudWatch Logs Integration (Optional)

```bash
# Install CloudWatch agent
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/arm64/latest/amazon-cloudwatch-agent.deb
sudo dpkg -i amazon-cloudwatch-agent.deb

# Configure agent
sudo /opt/aws/amazoncloudwatchagent/bin/amazon-cloudwatch-agent-config-wizard

# Or manually configure
sudo nano /opt/aws/amazoncloudwatchagent/bin/config.json

# Start agent
sudo systemctl enable amazon-cloudwatch-agent
sudo systemctl start amazon-cloudwatch-agent
```

### Log Monitoring Commands

```bash
# Real-time logs
sudo tail -f /var/log/okx-sol-bot/bot.log

# Last 100 lines
sudo tail -n 100 /var/log/okx-sol-bot/bot.log

# Search for errors
grep ERROR /var/log/okx-sol-bot/bot.log

# Count errors today
grep "$(date +%Y-%m-%d)" /var/log/okx-sol-bot/bot.log | grep ERROR | wc -l

# View error log
sudo tail -f /var/log/okx-sol-bot/bot.error.log
```

---

## 10. Operations Guide

### Service Management

```bash
# Check status
sudo systemctl status okx_sol_bot

# Start service
sudo systemctl start okx_sol_bot

# Stop service
sudo systemctl stop okx_sol_bot

# Restart service
sudo systemctl restart okx_sol_bot

# Reload configuration (if supported)
sudo systemctl reload okx_sol_bot

# Enable on boot
sudo systemctl enable okx_sol_bot

# Disable on boot
sudo systemctl disable okx_sol_bot
```

### View Logs

```bash
# Via journalctl
sudo journalctl -u okx_sol_bot -f

# Via log files
sudo tail -f /var/log/okx-sol-bot/bot.log

# Specific time range
sudo journalctl -u okx_sol_bot --since "2024-01-01 00:00:00" --until "2024-01-01 23:59:59"
```

### Check Current State

```bash
# Active position
sqlite3 /var/lib/okx-sol-bot/trading.db "SELECT * FROM positions WHERE status='ACTIVE';"

# Today's PnL
sqlite3 /var/lib/okx-sol-bot/trading.db "SELECT SUM(net_pnl_usdt) FROM trades WHERE DATE(exit_time) = DATE('now');"

# Recent trades
sqlite3 /var/lib/okx-sol-bot/trading.db "SELECT * FROM trades ORDER BY exit_time DESC LIMIT 10;"

# Risk state
sqlite3 /var/lib/okx-sol-bot/trading.db "SELECT * FROM risk_state ORDER BY timestamp DESC LIMIT 1;"
```

### Emergency Stop

**Method 1: Systemd**
```bash
sudo systemctl stop okx_sol_bot
```

**Method 2: Kill Switch File**
```bash
sudo touch /tmp/okx_bot_killswitch
sudo systemctl restart okx_sol_bot
```

**Method 3: Environment Variable**
```bash
# Edit .env
sudo nano /opt/okx-sol-bot/.env
# Change TRADING_MODE=halt

sudo systemctl restart okx_sol_bot
```

### Manual Restart After Changes

```bash
# After code updates
cd /opt/okx-sol-bot
git pull

# If dependencies changed
source venv/bin/activate
pip install -r requirements.txt

# Restart service
sudo systemctl restart okx_sol_bot

# Verify
sudo systemctl status okx_sol_bot
```

---

## 11. Monitoring & Alerts

### Basic Health Check Script

```bash
# Create health check script
sudo nano /opt/okx-sol-bot/health_check.sh

#!/bin/bash
set -e

# Check if service is running
if ! systemctl is-active --quiet okx_sol_bot; then
    echo "CRITICAL: Bot service is not running"
    exit 2
fi

# Check disk space
DISK_USAGE=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 90 ]; then
    echo "WARNING: Disk usage at ${DISK_USAGE}%"
fi

# Check memory
MEM_USAGE=$(free | grep Mem | awk '{printf("%.0f", $3/$2*100)}')
if [ "$MEM_USAGE" -gt 90 ]; then
    echo "WARNING: Memory usage at ${MEM_USAGE}%"
fi

# Check last log entry
LAST_LOG=$(tail -1 /var/log/okx-sol-bot/bot.log | cut -d' ' -f1,2)
LAST_TIMESTAMP=$(date -d "$LAST_LOG" +%s 2>/dev/null || echo 0)
CURRENT_TIMESTAMP=$(date +%s)
AGE=$((CURRENT_TIMESTAMP - LAST_TIMESTAMP))

if [ "$AGE" -gt 300 ]; then
    echo "WARNING: No log activity for ${AGE} seconds"
fi

echo "OK: All checks passed"
exit 0

# Make executable
chmod +x /opt/okx-sol-bot/health_check.sh
```

### CloudWatch Alarms (Optional)

```bash
# Create alarm for service failure
aws cloudwatch put-metric-alarm \
    --alarm-name "OKX-Bot-Service-Down" \
    --alarm-description "Trading bot service is not running" \
    --metric-name StatusCheckFailed \
    --namespace AWS/EC2 \
    --statistic Maximum \
    --period 60 \
    --threshold 1 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --evaluation-periods 2 \
    --dimensions Name=InstanceId,Value=i-xxxxxxxxx \
    --alarm-actions arn:aws:sns:region:account-id:topic-name
```

### Simple Monitoring Dashboard

Create a simple status page:

```bash
# Create status script
sudo nano /opt/okx-sol-bot/status.sh

#!/bin/bash
echo "=== OKX SOL Bot Status ==="
echo "Service: $(systemctl is-active okx_sol_bot)"
echo "Mode: $(grep TRADING_MODE /opt/okx-sol-bot/.env | cut -d= -f2)"
echo ""
echo "=== Current Position ==="
sqlite3 /var/lib/okx-sol-bot/trading.db "SELECT symbol, entry_price, quantity FROM positions WHERE status='ACTIVE';"
echo ""
echo "=== Today's PnL ==="
sqlite3 /var/lib/okx-sol-bot/trading.db "SELECT COALESCE(SUM(net_pnl_usdt), 0) FROM trades WHERE DATE(exit_time) = DATE('now');"
echo ""
echo "=== Recent Trades ==="
sqlite3 /var/lib/okx-sol-bot/trading.db "SELECT exit_time, net_pnl_usdt FROM trades ORDER BY exit_time DESC LIMIT 5;"

chmod +x /opt/okx-sol-bot/status.sh
```

---

## 12. Backup & Recovery

### Automated Database Backup

```bash
# Create backup script
sudo nano /opt/okx-sol-bot/backup.sh

#!/bin/bash
set -e

BACKUP_DIR="/var/backups/okx-sol-bot"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_PATH="/var/lib/okx-sol-bot/trading.db"

mkdir -p "$BACKUP_DIR"

# Create backup
sqlite3 "$DB_PATH" ".backup '$BACKUP_DIR/trading_backup_$TIMESTAMP.db'"

# Compress backup
gzip "$BACKUP_DIR/trading_backup_$TIMESTAMP.db"

# Delete backups older than 30 days
find "$BACKUP_DIR" -name "*.gz" -mtime +30 -delete

echo "Backup completed: trading_backup_$TIMESTAMP.db.gz"

# Make executable
chmod +x /opt/okx-sol-bot/backup.sh

# Add to crontab
sudo crontab -e

# Add line for daily backup at 3 AM
0 3 * * * /opt/okx-sol-bot/backup.sh >> /var/log/okx-sol-bot/backup.log 2>&1
```

### Manual Backup

```bash
# Create manual backup
sqlite3 /var/lib/okx-sol-bot/trading.db ".backup 'manual_backup.db'"

# Download backup locally
scp -i your-key.pem ubuntu@your-ec2-ip:/var/lib/okx-sol-bot/manual_backup.db ./backups/

# Or compress and download
ssh ubuntu@your-ec2-ip "gzip -c /var/lib/okx-sol-bot/trading.db > /tmp/trading_backup.gz"
scp -i your-key.pem ubuntu@your-ec2-ip:/tmp/trading_backup.gz ./backups/
```

### Restore from Backup

```bash
# Stop service
sudo systemctl stop okx_sol_bot

# Restore database
gunzip < trading_backup.db.gz | sqlite3 /var/lib/okx-sol-bot/trading.db

# Fix permissions
sudo chown tradingbot:tradingbot /var/lib/okx-sol-bot/trading.db

# Start service
sudo systemctl start okx_sol_bot

# Verify
sudo systemctl status okx_sol_bot
```

---

## 13. Troubleshooting

### Service Won't Start

```bash
# Check service status
sudo systemctl status okx_sol_bot

# View detailed logs
sudo journalctl -u okx_sol_bot -n 100

# Common issues:
# 1. Python path wrong
# 2. .env file missing
# 3. Database permissions
# 4. Virtual environment not activated

# Test manual execution
sudo su - tradingbot
cd /opt/okx-sol-bot
source venv/bin/activate
python main.py
```

### High Memory Usage

```bash
# Check memory
free -h
htop

# If memory leak suspected:
# 1. Check for unclosed connections
# 2. Review WebSocket handling
# 3. Consider scheduled restarts

# Add to crontab for weekly restart
sudo crontab -e
0 4 * * 0 systemctl restart okx_sol_bot
```

### Database Corruption

```bash
# Check integrity
sqlite3 /var/lib/okx-sol-bot/trading.db "PRAGMA integrity_check;"

# If corrupted:
# 1. Stop service
sudo systemctl stop okx_sol_bot

# 2. Restore from backup
# (see restore procedure above)

# 3. Or attempt repair
sqlite3 /var/lib/okx-sol-bot/trading.db ".dump" | sqlite3 /var/lib/okx-sol-bot/trading_recovered.db
mv /var/lib/okx-sol-bot/trading_recovered.db /var/lib/okx-sol-bot/trading.db

# 4. Restart service
sudo systemctl start okx_sol_bot
```

### API Connection Issues

```bash
# Test connectivity
curl -I https://www.okx.com

# Check rate limits in logs
grep "429\|rate limit" /var/log/okx-sol-bot/bot.log

# Verify API credentials
python -c "
import ccxt
exchange = ccxt.okx({'apiKey': 'xxx', 'secret': 'xxx'})
print(exchange.fetch_balance())
"

# Check IP whitelist on OKX dashboard
```

### Getting Help

1. Check logs: `sudo tail -f /var/log/okx-sol-bot/bot.log`
2. Review DECISIONS.md for design rationale
3. Check BACKTEST.md for expected behavior
4. Open GitHub issue with logs attached

---

## Final Checklist

Before going live:

```markdown
□ EC2 instance launched and secured
□ SSH hardened (key-only, no root)
□ Security group configured (SSH from trusted IP only)
□ Python 3.11 installed
□ Virtual environment created
□ Dependencies installed
□ Database initialized
□ Systemd service configured and enabled
□ Environment variables set (.env with restricted permissions)
□ Log rotation configured
□ Backup script scheduled
□ Health check script tested
□ Demo mode verified working
□ Emergency stop procedure tested
□ Monitoring/alerting configured (optional)
□ Documentation accessible
```

---

## Cost Estimate

| Component | Specification | Monthly Cost (us-east-1) |
|-----------|--------------|-------------------------|
| EC2 Instance | t3.micro | ~$7.50 |
| EC2 Instance | t3.small | ~$15.00 |
| Storage | 20 GB GP2 | ~$2.00 |
| Data Transfer | Typical usage | ~$1.00 |
| **Total (t3.micro)** | | **~$10.50/month** |
| **Total (t3.small)** | | **~$18.00/month** |

Costs vary by region. Check AWS Pricing Calculator for accurate estimates.

---

## Disclaimer

This guide is for educational purposes. You are responsible for:
- Securing your own infrastructure
- Complying with applicable laws and regulations
- Understanding tax implications of cryptocurrency trading
- Managing risks associated with automated trading

Never trade with money you cannot afford to lose.
