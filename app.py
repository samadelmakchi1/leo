#!/usr/bin/env python3
"""
Leo - Lightweight Customer Management System
Manages customer deployments via Git, Docker Compose and SQLite
"""

import os
import sqlite3
import shutil
import logging
from flask import Flask, render_template_string, request, jsonify, redirect, url_for
from git import Repo, GitCommandError
from docker import DockerClient
from jinja2 import Template

# تنظیم لاگینگ
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'customers.db')
DEPLOY_BASE = '/var/www/customers'  # Base directory for customer deployments

# اتصال به داکر با مدیریت خطا
def get_docker_client():
    try:
        return DockerClient.from_env()
    except Exception as e:
        logger.warning(f"Default docker connection failed: {e}")
        try:
            return DockerClient(base_url='unix:///var/run/docker.sock')
        except Exception as e2:
            logger.error(f"Failed to connect to docker: {e2}")
            raise

try:
    DOCKER_CLIENT = get_docker_client()
    logger.info("Successfully connected to Docker daemon.")
except Exception as e:
    logger.critical(f"CRITICAL: Cannot connect to Docker daemon. Ensure Docker is installed and running. Error: {e}")
    DOCKER_CLIENT = None

# Database initialization
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        git_url TEXT NOT NULL,
        branch TEXT NOT NULL,
        git_commit TEXT,
        domain TEXT NOT NULL,
        subdomain_file TEXT,
        subdomain_base TEXT,
        mysql_root_password TEXT,
        mysql_db_name TEXT,
        mysql_user TEXT,
        mysql_password TEXT,
        modules TEXT DEFAULT 'file',
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# HTML Templates (Inline for simplicity)
BASE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Leo - Customer Manager</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
        h1, h2 { color: #333; }
        .card { background: white; padding: 20px; margin: 20px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        input, select { width: 100%; padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
        button { background: #007bff; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; }
        button:hover { background: #0056b3; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #f8f9fa; }
        .status-pending { color: #ffc107; }
        .status-active { color: #28a745; }
        .status-error { color: #dc3545; }
        .btn-small { padding: 5px 10px; font-size: 12px; }
        .alert { padding: 15px; margin: 10px 0; border-radius: 4px; }
        .alert-success { background: #d4edda; color: #155724; }
        .alert-error { background: #f8d7da; color: #721c24; }
    </style>
</head>
<body>
    <h1>🚀 Leo - Customer Deployment Manager</h1>
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
          <div class="alert alert-{{ category }}">{{ message }}</div>
        {% endfor %}
      {% endif %}
    {% endwith %}
    {{ content|safe }}
</body>
</html>
"""

INDEX_HTML = """
<div class="card">
    <h2>Add New Customer</h2>
    <form method="POST" action="/add">
        <input type="text" name="name" placeholder="Customer Name (e.g., acme)" required>
        <input type="text" name="git_url" placeholder="Git URL (e.g., git@github.com:user/repo.git)" required>
        <input type="text" name="branch" placeholder="Branch (e.g., main)" value="main" required>
        <input type="text" name="git_commit" placeholder="Commit Hash (optional)">
        <input type="text" name="domain" placeholder="Domain (e.g., example.com)" required>
        <input type="text" name="subdomain_file" placeholder="Subdomain for File module (e.g., file)">
        <input type="text" name="subdomain_base" placeholder="Subdomain for Base module (e.g., app)">
        <input type="text" name="mysql_root_password" placeholder="MySQL Root Password">
        <input type="text" name="mysql_db_name" placeholder="MySQL Database Name">
        <input type="text" name="mysql_user" placeholder="MySQL User">
        <input type="text" name="mysql_password" placeholder="MySQL Password">
        <select name="modules">
            <option value="file">File Module</option>
            <option value="base">Base Module</option>
            <option value="file,base">Both</option>
        </select>
        <button type="submit">Deploy Customer</button>
    </form>
</div>

<div class="card">
    <h2>Customers</h2>
    <table>
        <thead>
            <tr>
                <th>Name</th>
                <th>Git URL</th>
                <th>Branch/Commit</th>
                <th>Domain</th>
                <th>Modules</th>
                <th>Status</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for customer in customers %}
            <tr>
                <td>{{ customer['name'] }}</td>
                <td>{{ customer['git_url'][:50] }}{% if customer['git_url']|length > 50 %}...{% endif %}</td>
                <td>{{ customer['branch'] }}{% if customer['git_commit'] %}@{{ customer['git_commit'][:7] }}{% endif %}</td>
                <td>{{ customer['subdomain_file'] or customer['subdomain_base'] }}.{{ customer['domain'] }}</td>
                <td>{{ customer['modules'] }}</td>
                <td class="status-{{ customer['status'] }}">{{ customer['status'] }}</td>
                <td>
                    <a href="/deploy/{{ customer['id'] }}"><button class="btn-small">Redeploy</button></a>
                    <a href="/down/{{ customer['id'] }}"><button class="btn-small" style="background:#dc3545">Stop</button></a>
                    <a href="/delete/{{ customer['id'] }}" onclick="return confirm('Delete?')"><button class="btn-small" style="background:#6c757d">Delete</button></a>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
"""

@app.route('/')
def index():
    conn = get_db()
    customers = conn.execute('SELECT * FROM customers ORDER BY created_at DESC').fetchall()
    conn.close()
    return render_template_string(BASE_HTML.replace('{{ content|safe }}', INDEX_HTML), content=render_template_string(INDEX_HTML, customers=customers))

@app.route('/add', methods=['POST'])
def add_customer():
    try:
        data = request.form
        conn = get_db()
        conn.execute('''INSERT INTO customers 
            (name, git_url, branch, git_commit, domain, subdomain_file, subdomain_base, 
             mysql_root_password, mysql_db_name, mysql_user, mysql_password, modules)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (data['name'], data['git_url'], data['branch'], data.get('git_commit'), data['domain'],
             data.get('subdomain_file'), data.get('subdomain_base'), data.get('mysql_root_password'),
             data.get('mysql_db_name'), data.get('mysql_user'), data.get('mysql_password'),
             data.get('modules', 'file')))
        conn.commit()
        customer_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.close()
        
        # Trigger deployment
        deploy_customer(customer_id)
        return redirect(url_for('index'))
    except Exception as e:
        return render_template_string(BASE_HTML, content=f'<div class="alert alert-error">Error: {str(e)}</div>'), 400

def deploy_customer(customer_id):
    conn = get_db()
    customer = conn.execute('SELECT * FROM customers WHERE id = ?', (customer_id,)).fetchone()
    if not customer:
        return False
    
    try:
        customer_name = customer['name']
        deploy_path = os.path.join(DEPLOY_BASE, customer_name)
        
        # Update status to deploying
        conn.execute('UPDATE customers SET status = ? WHERE id = ?', ('deploying', customer_id))
        conn.commit()
        
        # Clone or update Git repo
        if os.path.exists(deploy_path):
            repo = Repo(deploy_path)
            repo.remotes.origin.fetch()
            if customer['git_commit']:
                repo.git.checkout(customer['git_commit'])
            else:
                repo.git.checkout(customer['branch'])
            repo.remotes.origin.pull()
        else:
            os.makedirs(deploy_path, exist_ok=True)
            Repo.clone_from(customer['git_url'], deploy_path)
            if customer['git_commit']:
                repo = Repo(deploy_path)
                repo.git.checkout(customer['git_commit'])
        
        # Generate docker-compose.yml
        template_file = os.path.join(os.path.dirname(__file__), 'templates', 'docker-compose-file.j2')
        template_base = os.path.join(os.path.dirname(__file__), 'templates', 'docker-compose-base.j2')
        
        context = {
            'customer_name': customer_name,
            'domain': customer['domain'],
            'subdomain_file': customer['subdomain_file'] or customer_name,
            'subdomain_base': customer['subdomain_base'] or customer_name,
            'mysql_root_password': customer['mysql_root_password'] or 'rootpass',
            'mysql_db_name': customer['mysql_db_name'] or f'{customer_name}_db',
            'mysql_user': customer['mysql_user'] or customer_name,
            'mysql_password': customer['mysql_password'] or 'password',
        }
        
        modules = customer['modules'].split(',')
        compose_content = ""
        
        if 'file' in modules:
            with open(template_file) as f:
                tpl = Template(f.read())
            compose_content += tpl.render(**context) + "\n"
        
        if 'base' in modules:
            with open(template_base) as f:
                tpl = Template(f.read())
            compose_content += tpl.render(**context)
        
        compose_path = os.path.join(deploy_path, 'docker-compose.yml')
        with open(compose_path, 'w') as f:
            f.write(compose_content)
        
        # Deploy with Docker Compose
        os.chdir(deploy_path)
        os.system(f'docker compose up -d')
        
        conn.execute('UPDATE customers SET status = ? WHERE id = ?', ('active', customer_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.execute('UPDATE customers SET status = ? WHERE id = ?', ('error', customer_id))
        conn.commit()
        conn.close()
        raise e

@app.route('/deploy/<int:customer_id>')
def deploy(customer_id):
    try:
        deploy_customer(customer_id)
        return redirect(url_for('index'))
    except Exception as e:
        return render_template_string(BASE_HTML, content=f'<div class="alert alert-error">Deploy Error: {str(e)}</div>'), 400

@app.route('/down/<int:customer_id>')
def down(customer_id):
    try:
        conn = get_db()
        customer = conn.execute('SELECT * FROM customers WHERE id = ?', (customer_id,)).fetchone()
        if customer:
            deploy_path = os.path.join(DEPLOY_BASE, customer['name'])
            os.chdir(deploy_path)
            os.system('docker compose down')
            conn.execute('UPDATE customers SET status = ? WHERE id = ?', ('stopped', customer_id))
            conn.commit()
        conn.close()
        return redirect(url_for('index'))
    except Exception as e:
        return render_template_string(BASE_HTML, content=f'<div class="alert alert-error">Error: {str(e)}</div>'), 400

@app.route('/delete/<int:customer_id>')
def delete(customer_id):
    try:
        conn = get_db()
        customer = conn.execute('SELECT * FROM customers WHERE id = ?', (customer_id,)).fetchone()
        if customer:
            deploy_path = os.path.join(DEPLOY_BASE, customer['name'])
            if os.path.exists(deploy_path):
                shutil.rmtree(deploy_path)
            conn.execute('DELETE FROM customers WHERE id = ?', (customer_id,))
            conn.commit()
        conn.close()
        return redirect(url_for('index'))
    except Exception as e:
        return render_template_string(BASE_HTML, content=f'<div class="alert alert-error">Error: {str(e)}</div>'), 400

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
