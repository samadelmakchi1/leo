#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Leo - Lightweight Customer & Module Manager
Core: GitPython + Docker SDK + Flask + SQLite
"""

import os
import sys
import sqlite3
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template_string, request, redirect, url_for, flash, jsonify
import git
import docker
from docker.errors import DockerException, NotFound

# --- Configuration ---
BASE_DIR = Path(__file__).parent.resolve()
DB_PATH = BASE_DIR / "data" / "customers.db"
DEPLOY_ROOT = BASE_DIR / "deployments"
TEMPLATE_DIR = BASE_DIR / "templates"

DB_PATH.parent.mkdir(exist_ok=True)
DEPLOY_ROOT.mkdir(exist_ok=True)
TEMPLATE_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    client = docker.from_env()
    client.ping()
    logger.info("Docker daemon connected successfully.")
except Exception as e:
    logger.error(f"Docker connection failed: {e}")
    client = None

app = Flask(__name__)
app.secret_key = os.urandom(24)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT NOT NULL,
        customer_contact_name TEXT,
        customer_contact_mobile TEXT,
        customer_url TEXT,
        customer_domain TEXT,
        customer_subdomain_file TEXT,
        customer_subdomain_gateway TEXT,
        customer_subdomain_lms TEXT,
        customer_subdomain_portal TEXT,
        customer_containers TEXT NOT NULL,
        customer_state TEXT DEFAULT 'up',
        customer_purchase_date TEXT,
        customer_expiry_date TEXT,
        customer_file_git_branches TEXT,
        customer_file_git_tags TEXT,
        customer_file_update INTEGER DEFAULT 1,
        customer_gateway_git_branches TEXT,
        customer_gateway_git_tags TEXT,
        customer_gateway_update INTEGER DEFAULT 1,
        customer_lms_git_branches TEXT,
        customer_lms_git_tags TEXT,
        customer_lms_update INTEGER DEFAULT 1,
        customer_portal_git_branches TEXT,
        customer_portal_git_tags TEXT,
        customer_portal_update INTEGER DEFAULT 1
    )''')
    conn.commit()
    conn.close()
    logger.info("Database initialized.")

def get_customers():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM customers ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_customer(customer_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def add_customer(data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO customers (
        customer_name, customer_contact_name, customer_contact_mobile,
        customer_url, customer_domain, customer_subdomain_file,
        customer_subdomain_gateway, customer_subdomain_lms, customer_subdomain_portal,
        customer_containers, customer_state, customer_purchase_date, customer_expiry_date,
        customer_file_git_branches, customer_file_git_tags, customer_file_update,
        customer_gateway_git_branches, customer_gateway_git_tags, customer_gateway_update,
        customer_lms_git_branches, customer_lms_git_tags, customer_lms_update,
        customer_portal_git_branches, customer_portal_git_tags, customer_portal_update
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
    (
        data['customer_name'], data['customer_contact_name'], data['customer_contact_mobile'],
        data['customer_url'], data['customer_domain'], data['customer_subdomain_file'],
        data['customer_subdomain_gateway'], data['customer_subdomain_lms'], data['customer_subdomain_portal'],
        data['customer_containers'], data['customer_state'], data['customer_purchase_date'], data['customer_expiry_date'],
        data.get('customer_file_git_branches'), data.get('customer_file_git_tags'), int(data.get('customer_file_update', False)),
        data.get('customer_gateway_git_branches'), data.get('customer_gateway_git_tags'), int(data.get('customer_gateway_update', False)),
        data.get('customer_lms_git_branches'), data.get('customer_lms_git_tags'), int(data.get('customer_lms_update', False)),
        data.get('customer_portal_git_branches'), data.get('customer_portal_git_tags'), int(data.get('customer_portal_update', False))
    ))
    conn.commit()
    conn.close()

def delete_customer(customer_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    conn.commit()
    conn.close()

def deploy_customer(customer):
    cid = customer['customer_containers']
    work_dir = DEPLOY_ROOT / cid
    if not work_dir.exists():
        work_dir.mkdir(parents=True)
    
    logger.info(f"Starting deployment for {cid}...")
    modules = ['file', 'gateway', 'lms', 'portal']
    
    for mod in modules:
        if not customer.get(f'customer_{mod}_update'):
            continue
        branch = customer.get(f'customer_{mod}_git_branches') or 'main'
        tag = customer.get(f'customer_{mod}_git_tags')
        repo_name = f"{cid}-{mod}-repo"
        repo_path = work_dir / repo_name
        
        try:
            if repo_path.exists():
                logger.info(f"Updating {mod} repo...")
                g = git.Repo(repo_path)
                g.remote('origin').fetch()
                if tag:
                    g.git.checkout(tag)
                else:
                    g.git.checkout(branch)
                    g.reset('--hard', f'origin/{branch}')
            # Clone logic would go here with actual URLs from DB
        except Exception as e:
            logger.error(f"Git error for {mod}: {e}")

    compose_file = work_dir / "docker-compose.yml"
    with open(compose_file, 'w') as f:
        f.write(f"# Auto-generated for {customer['customer_name']}\nversion: '3.8'\nservices:\n")
        # Real YAML generation needs pyyaml, simplified here

    try:
        subprocess.run(["docker", "compose", "-f", str(compose_file), "up", "-d"], cwd=work_dir, check=True)
        logger.info(f"Deployment successful for {cid}")
        return True
    except Exception as e:
        logger.error(f"Docker compose failed: {e}")
        return False

def control_container(customer_id, module, action):
    customer = get_customer(customer_id)
    if not customer:
        return False, "Customer not found"
    cid = customer['customer_containers']
    container_name = f"{cid}-{module}"
    if not client:
        return False, "Docker client not available"
    try:
        container = client.containers.get(container_name)
        if action == 'start': container.start()
        elif action == 'stop': container.stop()
        elif action == 'restart': container.restart()
        elif action == 'logs': return True, container.logs(tail=100).decode('utf-8')
        return True, f"Action {action} executed"
    except NotFound:
        return False, f"Container {container_name} not found"
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    customers = get_customers()
    return render_template_string(HTML_INDEX, customers=customers)

@app.route('/add', methods=['GET', 'POST'])
def add_customer_route():
    if request.method == 'POST':
        data = {k: request.form.get(k) for k in [
            'customer_name', 'customer_contact_name', 'customer_contact_mobile',
            'customer_url', 'customer_domain', 'customer_subdomain_file',
            'customer_subdomain_gateway', 'customer_subdomain_lms', 'customer_subdomain_portal',
            'customer_containers', 'customer_purchase_date', 'customer_expiry_date',
            'customer_file_git_branches', 'customer_file_git_tags',
            'customer_gateway_git_branches', 'customer_gateway_git_tags',
            'customer_lms_git_branches', 'customer_lms_git_tags',
            'customer_portal_git_branches', 'customer_portal_git_tags'
        ]}
        data['customer_state'] = request.form.get('customer_state', 'up')
        for mod in ['file', 'gateway', 'lms', 'portal']:
            data[f'customer_{mod}_update'] = request.form.get(f'customer_{mod}_update') == 'on'
        
        if not data['customer_name'] or not data['customer_containers']:
            flash("نام مشتری و شناسه کانتینر الزامی است.", "error")
            return redirect(url_for('add_customer_route'))
        
        add_customer(data)
        flash("مشتری با موفقیت افزوده شد.", "success")
        return redirect(url_for('index'))
    return render_template_string(HTML_FORM)

@app.route('/delete/<int:id>')
def delete_customer_route(id):
    delete_customer(id)
    flash("مشتری حذف شد.", "info")
    return redirect(url_for('index'))

@app.route('/deploy/<int:id>', methods=['POST'])
def deploy_customer_route(id):
    customer = get_customer(id)
    if customer:
        if deploy_customer(customer):
            flash(f"پروژه {customer['customer_name']} دیپلوی شد.", "success")
        else:
            flash("خطا در دیپلوی.", "error")
    return redirect(url_for('index'))

@app.route('/control/<int:id>/<module>/<action>')
def control_route(id, module, action):
    success, msg = control_container(id, module, action)
    flash(msg, "success" if success else "error")
    return redirect(url_for('index'))

HTML_BASE = """
<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><title>لئو</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css" rel="stylesheet">
<style>body{font-family:'Vazirmatn',sans-serif}</style></head>
<body class="bg-gray-100 text-gray-800">
<nav class="bg-blue-600 text-white p-4 shadow-lg"><div class="container mx-auto flex justify-between">
<h1 class="text-2xl font-bold">🚀 لئو | مدیریت مشتریان</h1>
<a href="{{ url_for('add_customer_route') }}" class="bg-white text-blue-600 px-4 py-2 rounded">+ مشتری جدید</a>
</div></nav><div class="container mx-auto p-6">
{% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}
{% for cat, msg in messages %}<div class="p-4 mb-4 rounded {{ 'bg-green-200' if cat=='success' else 'bg-red-200' }}">{{ msg }}</div>{% endfor %}{% endif %}{% endwith %}
{% block content %}{% endblock %}</div></body></html>
"""

HTML_INDEX = """
{% extends "base" %}{% block content %}<div class="grid gap-6">
{% for c in customers %}
<div class="bg-white rounded shadow p-6 border-r-4 {{ 'border-green-500' if c.customer_state=='up' else 'border-red-500' }}">
<div class="flex justify-between mb-4"><div>
<h2 class="text-xl font-bold">{{ c.customer_name }}</h2>
<p class="text-sm text-gray-500">{{ c.customer_contact_mobile }} | {{ c.customer_containers }}</p>
</div><div class="space-x-2 space-x-reverse">
<form action="{{ url_for('deploy_customer_route', id=c.id) }}" method="POST"><button class="bg-blue-600 text-white px-3 py-1 rounded">🔄 دیپلوی</button></form>
<a href="{{ url_for('delete_customer_route', id=c.id) }}" class="bg-red-500 text-white px-3 py-1 rounded" onclick="return confirm('حذف؟')">حذف</a>
</div></div>
<div class="grid grid-cols-4 gap-4">{% for mod in ['file','gateway','lms','portal'] %}{% if c['customer_'+mod+'_update'] %}
<div class="bg-gray-50 p-3 rounded"><h3 class="font-bold capitalize">{{ mod }}</h3>
<p class="text-xs">Branch: {{ c['customer_'+mod+'_git_branches'] or '-' }}</p>
<div class="mt-2 flex gap-2 text-xs">
<a href="{{ url_for('control_route', id=c.id, module=mod, action='start') }}" class="text-green-600">▶️</a>
<a href="{{ url_for('control_route', id=c.id, module=mod, action='stop') }}" class="text-red-600">⏹️</a>
<a href="{{ url_for('control_route', id=c.id, module=mod, action='restart') }}" class="text-blue-600">🔁</a>
</div></div>{% endif %}{% endfor %}</div>
</div>{% endfor %}</div>{% endblock %}
""".replace('{% extends "base" %}', '')

HTML_FORM = """
{% extends "base" %}{% block content %}
<div class="bg-white p-8 rounded shadow max-w-4xl mx-auto"><h2 class="text-2xl font-bold mb-6">افزودن مشتری</h2>
<form method="POST" class="space-y-4">
<div class="grid grid-cols-3 gap-4"><div><label>نام مشتری *</label><input name="customer_name" required class="w-full border p-2 rounded"></div>
<div><label>تماس</label><input name="customer_contact_name" class="w-full border p-2 rounded"></div>
<div><label>موبایل</label><input name="customer_contact_mobile" class="w-full border p-2 rounded"></div></div>
<div class="grid grid-cols-3 gap-4"><div><label>شناسه *</label><input name="customer_containers" required class="w-full border p-2 rounded"></div>
<div><label>دامنه</label><input name="customer_domain" class="w-full border p-2 rounded"></div>
<div><label>IP</label><input name="customer_url" class="w-full border p-2 rounded"></div></div>
<div class="grid grid-cols-4 gap-2 bg-blue-50 p-4 rounded">{% for mod in ['file','gateway','lms','portal'] %}
<div><label class="text-xs">ساب‌دامین {{ mod }}</label><input name="customer_subdomain_{{ mod }}" class="w-full border p-1 rounded"></div>{% endfor %}</div>
<div class="grid grid-cols-2 gap-4"><div><label>تاریخ خرید</label><input type="date" name="customer_purchase_date" class="w-full border p-2 rounded"></div>
<div><label>تاریخ انقضا</label><input type="date" name="customer_expiry_date" class="w-full border p-2 rounded"></div></div>
<div class="border-t pt-4"><h3 class="font-bold mb-4">ماژول‌ها</h3>{% for mod in ['file','gateway','lms','portal'] %}
<div class="bg-gray-50 p-3 rounded mb-2 flex items-center gap-4">
<input type="checkbox" name="customer_{{ mod }}_update" id="u_{{ mod }}" checked><label for="u_{{ mod }}" class="font-bold w-24">{{ mod }}</label>
<input name="customer_{{ mod }}_git_branches" placeholder="برنچ" class="border p-1 rounded flex-1">
<input name="customer_{{ mod }}_git_tags" placeholder="تگ" class="border p-1 rounded flex-1">
</div>{% endfor %}</div>
<button class="w-full bg-green-600 text-white py-3 rounded font-bold">ذخیره</button>
</form></div>{% endblock %}
""".replace('{% extends "base" %}', HTML_BASE.split('<body')[0] + '<body class="bg-gray-100 text-gray-800"><div class="container mx-auto p-6">')

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
