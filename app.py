import os
import datetime
from collections import defaultdict
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

# ================= 配置区域 =================
app = Flask(__name__)
app.secret_key = 'BOSS_SECRET_KEY_888'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///team_performance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ================= 1. 数据库模型 =================
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
    month = db.Column(db.String(20), nullable=False) # 格式: YYYY-MM
    target_loan = db.Column(db.Float, default=100.0)
    target_orders = db.Column(db.Integer, default=10)

class DailyLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20)) 
    name = db.Column(db.String(50))
    total_data_count = db.Column(db.Integer, default=0)
    connected = db.Column(db.Integer, default=0)
    added_wechat = db.Column(db.Integer, default=0)
    pre_audit = db.Column(db.Integer, default=0)
    pre_pass = db.Column(db.Integer, default=0)
    final_audit = db.Column(db.Integer, default=0)
    final_pass = db.Column(db.Integer, default=0)
    loan_orders = db.Column(db.Integer, default=0)
    loan_amount = db.Column(db.Float, default=0.0)
    next_day_est = db.Column(db.Float, default=0.0)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)

# ================= 智能指标继承核心 =================
def get_or_create_target(name, month):
    t = MonthlyTarget.query.filter_by(name=name, month=month).first()
    if not t:
        last_t = MonthlyTarget.query.filter_by(name=name).order_by(MonthlyTarget.id.desc()).first()
        t = MonthlyTarget(
            name=name, month=month, 
            target_loan=last_t.target_loan if last_t else 100.0, 
            target_orders=last_t.target_orders if last_t else 10
        )
        db.session.add(t)
        db.session.commit()
    return t

# ================= 2. 权限拦截 =================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            flash('权限不足！此操作仅限管理员。', 'danger')
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

# ================= 3. 路由与视图 =================
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            return redirect(url_for('dashboard'))
        flash('用户名或密码错误', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    current_month = datetime.date.today().strftime('%Y-%m')
    req_month = request.args.get('month', current_month)
    is_admin = session.get('is_admin', False)
    
    if req_month != current_month and not is_admin:
        flash('⚠️ 仅管理员可查看历史月份数据！', 'warning')
        return redirect(url_for('dashboard', month=current_month))
        
    employees = Employee.query.all()
    logs = DailyLog.query.filter(DailyLog.date.like(f"{req_month}-%")).all()
    user_logs = defaultdict(list)
    for log in logs: user_logs[log.name].append(log)
        
    report =[]
    team_total = {'total_data_count': 0, 'loan_orders': 0, 'loan_amount': 0, 'target_loan': 0, 'target_orders': 0}

    for emp in employees:
        emp_logs = user_logs[emp.name]
        emp_logs.sort(key=lambda x: x.date, reverse=True)
        
        tgt = get_or_create_target(emp.name, req_month)
        
        total_data = sum(l.total_data_count for l in emp_logs)
        loan_amt = sum(l.loan_amount for l in emp_logs)
        orders = sum(l.loan_orders for l in emp_logs)
        
        avg = round(loan_amt / orders, 2) if orders > 0 else 0.00
        achieve = round((loan_amt / tgt.target_loan) * 100, 2) if tgt.target_loan > 0 else 0.00
        convert = round((orders / total_data) * 100, 2) if total_data > 0 else 0.00
        
        report.append({
            'name': emp.name, 'total_data_count': total_data, 'loan_orders': orders,
            'loan_amount': loan_amt, 'avg': avg, 
            'target_loan': tgt.target_loan, 'target_orders': tgt.target_orders, 
            'achieve': achieve, 'convert': convert, 'daily_logs': emp_logs
        })
        
        team_total['total_data_count'] += total_data
        team_total['loan_orders'] += orders
        team_total['loan_amount'] += loan_amt
        team_total['target_loan'] += tgt.target_loan
        team_total['target_orders'] += tgt.target_orders

    team_total['avg'] = round(team_total['loan_amount'] / team_total['loan_orders'], 2) if team_total['loan_orders'] > 0 else 0.00
    team_total['achieve'] = round((team_total['loan_amount'] / team_total['target_loan']) * 100, 2) if team_total['target_loan'] > 0 else 0.00
    team_total['convert'] = round((team_total['loan_orders'] / team_total['total_data_count']) * 100, 2) if team_total['total_data_count'] > 0 else 0.00

    report.sort(key=lambda x: x['loan_amount'], reverse=True)
    return render_template('dashboard.html', report=report, team=team_total, req_month=req_month, is_admin=is_admin)

@app.route('/entry', methods=['GET', 'POST'])
@login_required
def entry():
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    if request.method == 'POST':
        try:
            name = request.form['name']
            date = request.form['date']
            is_admin = session.get('is_admin', False)
            
            # ======== 【BUG修复：核心防篡改拦截】 ========
            # 如果不是管理员，且提交的日期不是今天，立刻拦截！
            if not is_admin and date != today_str:
                flash('⚠️ 权限受限：普通员工只能录入当天的业绩！', 'danger')
                return redirect(url_for('entry'))
            # ==========================================
            
            t_count = int(request.form.get('total_data_count', 0))
            con, add, pre = int(request.form.get('connected', 0)), int(request.form.get('added', 0)), int(request.form.get('pre', 0))
            pre_p, fin, fin_p = int(request.form.get('pre_pass', 0)), int(request.form.get('final', 0)), int(request.form.get('final_pass', 0))
            orders, amt, next_est = int(request.form.get('orders', 0)), float(request.form.get('amount', 0.0)), float(request.form.get('next_est', 0.0))
            
            if not Employee.query.filter_by(name=name).first():
                flash(f'查无此人：{name}', 'warning')
                return redirect(url_for('entry'))
            
            existing_log = DailyLog.query.filter_by(name=name, date=date).first()
            if existing_log:
                existing_log.total_data_count = t_count
                existing_log.connected, existing_log.added_wechat = con, add
                existing_log.pre_audit, existing_log.pre_pass = pre, pre_p
                existing_log.final_audit, existing_log.final_pass = fin, fin_p
                existing_log.loan_orders, existing_log.loan_amount = orders, amt
                existing_log.next_day_est = next_est
                existing_log.timestamp = datetime.datetime.now()
                flash(f'检测到 {date} 已有数据，已执行[覆盖更新]操作！', 'success')
            else:
                db.session.add(DailyLog(date=date, name=name, total_data_count=t_count, connected=con, added_wechat=add,
                    pre_audit=pre, pre_pass=pre_p, final_audit=fin, final_pass=fin_p,
                    loan_orders=orders, loan_amount=amt, next_day_est=next_est))
                flash('数据录入成功！', 'success')
            db.session.commit()
            return redirect(url_for('entry'))
        except ValueError:
            flash('输入格式错误，请确保输入数字！', 'danger')
    
    employees =[e.name for e in Employee.query.all()]
    today_logs = DailyLog.query.filter_by(date=today_str).order_by(DailyLog.timestamp.desc()).all()
    return render_template('entry.html', employees=employees, today=today_str, today_logs=today_logs)

@app.route('/admin', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_panel():
    current_month = datetime.date.today().strftime('%Y-%m')
    target_month = request.args.get('target_month', current_month)

    if request.method == 'POST':
        action, name = request.form.get('action'), request.form.get('name')
        
        if action == 'add':
            if Employee.query.filter_by(name=name).first():
                flash('员工已存在！', 'warning')
            else:
                target_loan = float(request.form.get('target_loan', 100))
                target_orders = int(request.form.get('target_orders', 10))
                db.session.add(Employee(name=name))
                db.session.add(MonthlyTarget(name=name, month=current_month, target_loan=target_loan, target_orders=target_orders))
                db.session.commit()
                flash(f'员工 {name} 添加成功', 'success')
                
        elif action == 'delete':
            Employee.query.filter_by(name=name).delete()
            DailyLog.query.filter_by(name=name).delete()
            MonthlyTarget.query.filter_by(name=name).delete() 
            db.session.commit()
            flash(f'员工 {name} 及其所有数据已彻底删除', 'warning')
            
        elif action == 'update_target':
            update_month = request.form.get('month')
            t = MonthlyTarget.query.filter_by(name=name, month=update_month).first()
            if not t:
                t = MonthlyTarget(name=name, month=update_month)
                db.session.add(t)
            t.target_loan = float(request.form.get('target_loan'))
            t.target_orders = int(request.form.get('target_orders'))
            db.session.commit()
            flash(f'成功更新 {name} 在 {update_month} 的考核指标！', 'success')
            return redirect(url_for('admin_panel', target_month=update_month))

    logs = DailyLog.query.order_by(DailyLog.timestamp.desc()).limit(20).all()
    employees = Employee.query.all()
    targets_info =[get_or_create_target(emp.name, target_month) for emp in employees]
    
    return render_template('admin.html', logs=logs, employees=employees, targets=targets_info, target_month=target_month)

@app.route('/edit_log/<int:log_id>', methods=['GET', 'POST'])
@login_required
def edit_log(log_id):
    log = DailyLog.query.get_or_404(log_id)
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    is_admin = session.get('is_admin', False)
    
    if not is_admin and log.date != today_str:
        flash('⚠️ 仅管理员可修改历史数据！', 'danger')
        return redirect(url_for('entry'))
    
    if request.method == 'POST':
        try:
            log.total_data_count = int(request.form.get('total_data_count', 0))
            log.connected, log.added_wechat = int(request.form.get('connected', 0)), int(request.form.get('added', 0))
            log.pre_audit, log.pre_pass = int(request.form.get('pre', 0)), int(request.form.get('pre_pass', 0))
            log.final_audit, log.final_pass = int(request.form.get('final', 0)), int(request.form.get('final_pass', 0))
            log.loan_orders, log.loan_amount = int(request.form.get('orders', 0)), float(request.form.get('amount', 0.0))
            log.next_day_est = float(request.form.get('next_est', 0.0))
            log.timestamp = datetime.datetime.now()
            
            db.session.commit()
            flash(f'{log.name} 数据修改成功！', 'success')
            return redirect(url_for('admin_panel')) if is_admin else redirect(url_for('entry'))
        except ValueError: flash('输入格式错误！', 'danger')
            
    return render_template('edit_log.html', log=log)

if __name__ == '__main__':
    init_system()
    app.run(debug=True, port=5000)