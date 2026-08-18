# Leo - Lightweight Customer Management

Ultra-lightweight customer deployment manager using Git, Docker Compose and SQLite.

## Features
- Add customers with Git repo, branch/commit selection
- Auto-generate docker-compose.yml from templates
- Deploy/Stop/Delete customers via web UI
- SQLite database for customer management
- No Ansible, no monitoring, no bloat

## Setup
```bash
pip install -r requirements.txt
python app.py
```

## Usage
Visit `http://localhost:5000` to add and manage customers.
