import os
import datetime
from collections import defaultdict
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Numeric, func
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_caching import Cache

app = Flask(__name__)
app.secret_key = 'BOSS_SECRET_KEY_888'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///team_performance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['CACHE_TYPE'] = 'SimpleCache'
app.config['CACHE_DEFAULT_TIMEOUT'] = 600
db = SQLAlchemy(app)
cache = Cache(app)

# ================= 数据库模型 =================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False)

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

class MonthlyTarget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    month = db.Column(db.String(20), nullable=False)
    target_loan = db.Column(Numeric(precision=18, scale=8), default=100.0)
    target_orders = db.Column(db.Integer, default=10)

class DailyLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), index=True)
    name = db.Column(db.String(50), index=True)
    total_data_count = db.Column(db.Integer, default=0)
    connected = db.Column(db.Integer, default=0)
    added_wechat = db.Column(db.Integer, default=0)
    pre_audit = db.Column(db.Integer, default=0)
    pre_pass = db.Column(db.Integer, default=0)
    final_audit = db.Column(db.Integer, default=0)
    final_pass = db.Column(db.Integer, default=0)
    loan_orders = db.Column(db.Integer, default=0)
    loan_amount = db.Column(Numeric(precision=18, scale=8), default=0.0)
    next_day_est = db.Column(Numeric(precision=18, scale=8), default=0.0)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now, index=True)

# ================= 权限与初始化 =================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session: 
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'): 
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def init_system():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            db.session.add(User(username='admin', password_hash=generate_password_hash('admin888'), is_admin=True))
            db.session.add(User(username='user', password_hash=generate_password_hash('123456'), is_admin=False))
            db.session.commit()

# ================= 路由视图 =================
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session.update({'user_id': user.id, 'username': user.username, 'is_admin': user.is_admin})
            return redirect(url_for('dashboard'))
        flash('用户名或密码错误', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
@cache.cached(timeout=600, query_string=True)
def dashboard():
    req_month = request.args.get('month', datetime.date.today().strftime('%Y-%m'))
    employees = Employee.query.all()
    
    # 数据库聚合查询
    daily_loan_query = db.session.query(
        DailyLog.date,
        func.sum(DailyLog.loan_amount).label('total_loan')
    ).filter(
        DailyLog.date.like(f"{req_month}-%")
    ).group_by(
        DailyLog.date
    ).order_by(
        DailyLog.date
    ).all()
    
    # 整理图表数据
    chart_dates = []
    chart_values = []
    for date, total_loan in daily_loan_query:
        chart_dates.append(date.split('-')[2] + '日')
        chart_values.append(round(float(total_loan), 2))
    
    # 批量查询日志
    logs = DailyLog.query.filter(DailyLog.date.like(f"{req_month}-%")).all()
    user_logs = {emp.name: [log for log in logs if log.name == emp.name] for emp in employees}
    
    # 报表逻辑
    report = []
    team_total = {'total_data_count': 0, 'loan_orders': 0, 'loan_amount': 0.0, 'target_loan': 0.0, 'target_orders': 0}
    target_dict = {tgt.name: tgt for tgt in MonthlyTarget.query.filter_by(month=req_month).all()}
    
    # 修复：用Python内置的enumerate生成索引，替代Jinja2的loop.index
    for idx, emp in enumerate(employees, 1):  # 从1开始计数
        emp_logs = user_logs.get(emp.name, [])
        tgt = target_dict.get(emp.name, MonthlyTarget(target_loan=100.0, target_orders=10))
        
        loan_amt = float(sum(l.loan_amount for l in emp_logs))
        orders = sum(l.loan_orders for l in emp_logs)
        total_data = sum(l.total_data_count for l in emp_logs)
        
        report.append({
            'name': emp.name, 
            'loan_amount': loan_amt, 
            'loan_orders': orders, 
            'total_data_count': total_data,
            'avg': round(loan_amt/orders, 2) if orders else 0.0,
            'target_loan': float(tgt.target_loan), 
            'target_orders': tgt.target_orders,
            'achieve': round((loan_amt / float(tgt.target_loan) * 100), 2) if tgt.target_loan > 0 else 0,
            'convert': round((orders / total_data * 100), 2) if total_data > 0 else 0,
            'daily_logs': sorted(emp_logs, key=lambda x: x.date, reverse=True),
            # 修复：用Python的idx生成唯一ID，传给前端
            'collapse_id': f"collapse-{idx}"
        })
        team_total['loan_amount'] += loan_amt
        team_total['target_loan'] += float(tgt.target_loan)
        team_total['target_orders'] += tgt.target_orders
        team_total['total_data_count'] += total_data
        team_total['loan_orders'] += orders
    
    team_total['avg'] = round(team_total['loan_amount'] / team_total['loan_orders'], 2) if team_total['loan_orders'] > 0 else 0.0
    team_total['achieve'] = round((team_total['loan_amount'] / team_total['target_loan'] * 100), 2) if team_total['target_loan'] > 0 else 0.0
    team_total['convert'] = round((team_total['loan_orders'] / team_total['total_data_count'] * 100), 2) if team_total['total_data_count'] > 0 else 0.0
    
    return render_template(
        'dashboard.html', 
        report=report, 
        team=team_total, 
        req_month=req_month, 
        is_admin=session.get('is_admin'),
        chart_dates=chart_dates,
        chart_values=chart_values
    )

@app.route('/clear_cache')
@login_required
@admin_required
def clear_cache():
    cache.clear()
    flash('数据缓存已清空，下次访问将加载最新数据', 'success')
    return redirect(url_for('dashboard'))

@app.route('/entry', methods=['GET', 'POST'])
@login_required
def entry():
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    if request.method == 'POST':
        try:
            name, date = request.form['name'], request.form['date']
            log = DailyLog.query.filter_by(name=name, date=date).first() or DailyLog(name=name, date=date)
            log.total_data_count, log.connected, log.added_wechat = int(request.form['total_data_count']), int(request.form['connected']), int(request.form['added'])
            log.pre_audit, log.pre_pass, log.final_audit, log.final_pass = int(request.form['pre']), int(request.form['pre_pass']), int(request.form['final']), int(request.form['final_pass'])
            log.loan_orders, log.loan_amount, log.next_day_est = int(request.form['orders']), float(request.form['amount']), float(request.form['next_est'])
            db.session.add(log)
            db.session.commit()
            cache.clear()
            flash('数据提交成功', 'success')
        except Exception as e:
            print(f"提交数据错误：{e}")
            flash('数据格式错误', 'danger')
        return redirect(url_for('entry'))
    return render_template('entry.html', employees=[e.name for e in Employee.query.all()], today=today_str, today_logs=DailyLog.query.filter_by(date=today_str).all())

@app.route('/admin', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_panel():
    if request.method == 'POST':
        action, name = request.form.get('action'), request.form.get('name')
        try:
            if action == 'add':
                db.session.add(Employee(name=name))
                db.session.add(MonthlyTarget(name=name, month=datetime.date.today().strftime('%Y-%m')))
            elif action == 'delete':
                Employee.query.filter_by(name=name).delete()
                DailyLog.query.filter_by(name=name).delete()
                MonthlyTarget.query.filter_by(name=name).delete()
            elif action == 'update_target':
                t = MonthlyTarget.query.filter_by(name=name, month=request.form.get('month')).first()
                t.target_loan, t.target_orders = float(request.form.get('target_loan')), int(request.form.get('target_orders'))
            db.session.commit()
            cache.clear()
            flash('操作成功', 'success')
        except Exception as e:
            print(f"管理员操作错误：{e}")
            flash('操作失败', 'danger')
    return render_template('admin.html', employees=Employee.query.all(), logs=DailyLog.query.order_by(DailyLog.timestamp.desc()).limit(20).all(), target_month=request.args.get('target_month', datetime.date.today().strftime('%Y-%m')), targets=MonthlyTarget.query.filter_by(month=request.args.get('target_month', datetime.date.today().strftime('%Y-%m'))).all())

@app.route('/edit_log/<int:log_id>', methods=['GET', 'POST'])
@login_required
def edit_log(log_id):
    log = DailyLog.query.get_or_404(log_id)
    if request.method == 'POST':
        try:
            log.total_data_count = int(request.form.get('total_data_count', log.total_data_count))
            log.connected = int(request.form.get('connected', log.connected))
            log.added_wechat = int(request.form.get('added', log.added_wechat))
            log.pre_audit = int(request.form.get('pre', log.pre_audit))
            log.pre_pass = int(request.form.get('pre_pass', log.pre_pass))
            log.final_audit = int(request.form.get('final', log.final_audit))
            log.final_pass = int(request.form.get('final_pass', log.final_pass))
            log.loan_orders = int(request.form.get('orders', log.loan_orders))
            log.loan_amount = float(request.form.get('amount', log.loan_amount))
            log.next_day_est = float(request.form.get('next_est', log.next_day_est))
            log.timestamp = datetime.datetime.now()
            db.session.commit()
            cache.clear()
            flash('修改成功', 'success')
        except Exception as e:
            print(f"修改日志错误：{e}")
            flash('数据错误', 'danger')
        return redirect(url_for('admin_panel'))
    return render_template('edit_log.html', log=log)

if __name__ == '__main__':
    init_system()
    app.run(host='0.0.0.0', port=5000, debug=False)