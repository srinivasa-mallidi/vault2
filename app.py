from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps
import os, json

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'smvault-offline-key-2024')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///smvault.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ── MODELS ────────────────────────────────────────────────────────────────────

class Project(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    color       = db.Column(db.String(20), default='#1a5fa8')
    icon        = db.Column(db.String(10), default='📁')
    created     = db.Column(db.DateTime, default=datetime.utcnow)
    updated     = db.Column(db.DateTime, default=datetime.utcnow)
    sites       = db.relationship('Site', backref='project', lazy=True, cascade='all,delete')
    kb_pages    = db.relationship('KBPage', backref='project', lazy=True, cascade='all,delete')

class Site(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    project_id  = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    name        = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    environment = db.Column(db.String(50))   # Production, UAT, Dev, Test
    created     = db.Column(db.DateTime, default=datetime.utcnow)
    updated     = db.Column(db.DateTime, default=datetime.utcnow)
    sections    = db.relationship('SiteSection', backref='site', lazy=True, cascade='all,delete', order_by='SiteSection.order')

class SiteSection(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    site_id    = db.Column(db.Integer, db.ForeignKey('site.id'), nullable=False)
    stype      = db.Column(db.String(50), nullable=False)  # url, server, database, credentials, custom
    title      = db.Column(db.String(200))
    data_json  = db.Column(db.Text, default='{}')
    order      = db.Column(db.Integer, default=0)
    created    = db.Column(db.DateTime, default=datetime.utcnow)

    def get_data(self):
        try: return json.loads(self.data_json or '{}')
        except: return {}
    def set_data(self, d):
        self.data_json = json.dumps(d)

class KBPage(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    title      = db.Column(db.String(300), nullable=False)
    content    = db.Column(db.Text, default='')
    order      = db.Column(db.Integer, default=0)
    created    = db.Column(db.DateTime, default=datetime.utcnow)
    updated    = db.Column(db.DateTime, default=datetime.utcnow)

# ── AUTH ──────────────────────────────────────────────────────────────────────

ADMIN_USER = 'SM_ADMIN'
ADMIN_PASS = 'Welcome@1234'

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET','POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('home'))
    error = None
    if request.method == 'POST':
        u = request.form.get('username','').strip()
        p = request.form.get('password','')
        if u == ADMIN_USER and p == ADMIN_PASS:
            session['logged_in'] = True
            session.permanent = True
            return redirect(url_for('home'))
        error = 'Invalid username or password.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── HOME ──────────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def home():
    projects = Project.query.order_by(Project.updated.desc()).all()
    return render_template('home.html', projects=projects)

# ── PROJECTS ──────────────────────────────────────────────────────────────────

@app.route('/project/new', methods=['GET','POST'])
@login_required
def new_project():
    if request.method == 'POST':
        p = Project(
            name=request.form.get('name','').strip(),
            description=request.form.get('description','').strip(),
            color=request.form.get('color','#1a5fa8'),
            icon=request.form.get('icon','📁')
        )
        if not p.name:
            flash('Project name is required.','error')
            return render_template('project_form.html', project=None)
        db.session.add(p)
        db.session.commit()
        flash(f'Project "{p.name}" created.','success')
        return redirect(url_for('project_detail', pid=p.id))
    return render_template('project_form.html', project=None)

@app.route('/project/<int:pid>')
@login_required
def project_detail(pid):
    p = Project.query.get_or_404(pid)
    return render_template('project_detail.html', project=p)

@app.route('/project/<int:pid>/edit', methods=['GET','POST'])
@login_required
def edit_project(pid):
    p = Project.query.get_or_404(pid)
    if request.method == 'POST':
        p.name = request.form.get('name','').strip()
        p.description = request.form.get('description','').strip()
        p.color = request.form.get('color','#1a5fa8')
        p.icon = request.form.get('icon','📁')
        p.updated = datetime.utcnow()
        db.session.commit()
        flash('Project updated.','success')
        return redirect(url_for('project_detail', pid=p.id))
    return render_template('project_form.html', project=p)

@app.route('/project/<int:pid>/delete', methods=['POST'])
@login_required
def delete_project(pid):
    p = Project.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    flash(f'Project "{p.name}" deleted.','success')
    return redirect(url_for('home'))

# ── SITES ─────────────────────────────────────────────────────────────────────

@app.route('/project/<int:pid>/site/new', methods=['GET','POST'])
@login_required
def new_site(pid):
    p = Project.query.get_or_404(pid)
    if request.method == 'POST':
        s = Site(
            project_id=pid,
            name=request.form.get('name','').strip(),
            description=request.form.get('description','').strip(),
            environment=request.form.get('environment',''),
            updated=datetime.utcnow()
        )
        if not s.name:
            flash('Site name is required.','error')
            return render_template('site_form.html', project=p, site=None)
        db.session.add(s)
        db.session.commit()
        flash(f'Site "{s.name}" created.','success')
        return redirect(url_for('site_detail', pid=pid, sid=s.id))
    return render_template('site_form.html', project=p, site=None)

@app.route('/project/<int:pid>/site/<int:sid>')
@login_required
def site_detail(pid, sid):
    p = Project.query.get_or_404(pid)
    s = Site.query.get_or_404(sid)
    return render_template('site_detail.html', project=p, site=s)

@app.route('/project/<int:pid>/site/<int:sid>/edit', methods=['GET','POST'])
@login_required
def edit_site(pid, sid):
    p = Project.query.get_or_404(pid)
    s = Site.query.get_or_404(sid)
    if request.method == 'POST':
        s.name = request.form.get('name','').strip()
        s.description = request.form.get('description','').strip()
        s.environment = request.form.get('environment','')
        s.updated = datetime.utcnow()
        db.session.commit()
        flash('Site updated.','success')
        return redirect(url_for('site_detail', pid=pid, sid=sid))
    return render_template('site_form.html', project=p, site=s)

@app.route('/project/<int:pid>/site/<int:sid>/delete', methods=['POST'])
@login_required
def delete_site(pid, sid):
    s = Site.query.get_or_404(sid)
    name = s.name
    db.session.delete(s)
    db.session.commit()
    flash(f'Site "{name}" deleted.','success')
    return redirect(url_for('project_detail', pid=pid))

# ── SECTIONS ──────────────────────────────────────────────────────────────────

@app.route('/project/<int:pid>/site/<int:sid>/section/new', methods=['GET','POST'])
@login_required
def new_section(pid, sid):
    p = Project.query.get_or_404(pid)
    s = Site.query.get_or_404(sid)
    if request.method == 'POST':
        stype = request.form.get('stype','custom')
        title = request.form.get('title','').strip() or stype.capitalize()
        data  = build_section_data(stype, request.form)
        count = SiteSection.query.filter_by(site_id=sid).count()
        sec   = SiteSection(site_id=sid, stype=stype, title=title, order=count)
        sec.set_data(data)
        db.session.add(sec)
        s.updated = datetime.utcnow()
        p.updated = datetime.utcnow()
        db.session.commit()
        flash('Section added.','success')
        return redirect(url_for('site_detail', pid=pid, sid=sid))
    stype = request.args.get('stype','url')
    return render_template('section_form.html', project=p, site=s, section=None, stype=stype, data={})

@app.route('/project/<int:pid>/site/<int:sid>/section/<int:secid>/edit', methods=['GET','POST'])
@login_required
def edit_section(pid, sid, secid):
    p   = Project.query.get_or_404(pid)
    s   = Site.query.get_or_404(sid)
    sec = SiteSection.query.get_or_404(secid)
    if request.method == 'POST':
        sec.title = request.form.get('title','').strip() or sec.stype.capitalize()
        data = build_section_data(sec.stype, request.form)
        sec.set_data(data)
        s.updated = datetime.utcnow()
        p.updated = datetime.utcnow()
        db.session.commit()
        flash('Section updated.','success')
        return redirect(url_for('site_detail', pid=pid, sid=sid))
    return render_template('section_form.html', project=p, site=s, section=sec, stype=sec.stype, data=sec.get_data())

@app.route('/project/<int:pid>/site/<int:sid>/section/<int:secid>/delete', methods=['POST'])
@login_required
def delete_section(pid, sid, secid):
    sec = SiteSection.query.get_or_404(secid)
    db.session.delete(sec)
    db.session.commit()
    flash('Section deleted.','success')
    return redirect(url_for('site_detail', pid=pid, sid=sid))

def build_section_data(stype, form):
    if stype == 'url':
        entries = []
        labels = form.getlist('url_label')
        urls   = form.getlist('url_value')
        descs  = form.getlist('url_desc')
        for i,u in enumerate(urls):
            if u.strip():
                entries.append({'label': labels[i] if i<len(labels) else '', 'url': u.strip(), 'desc': descs[i] if i<len(descs) else ''})
        return {'entries': entries}
    elif stype == 'server':
        return {
            'hostname': form.get('hostname','').strip(),
            'ip':       form.get('ip','').strip(),
            'os':       form.get('os','').strip(),
            'version':  form.get('version','').strip(),
            'cpu':      form.get('cpu','').strip(),
            'ram':      form.get('ram','').strip(),
            'disk':     form.get('disk','').strip(),
            'location': form.get('location','').strip(),
            'notes':    form.get('notes','').strip(),
        }
    elif stype == 'database':
        return {
            'db_type':  form.get('db_type','').strip(),
            'host':     form.get('host','').strip(),
            'port':     form.get('port','').strip(),
            'sid':      form.get('sid','').strip(),
            'schema':   form.get('schema','').strip(),
            'version':  form.get('version','').strip(),
            'notes':    form.get('notes','').strip(),
        }
    elif stype == 'credentials':
        entries = []
        labels = form.getlist('cred_label')
        users  = form.getlist('cred_user')
        pwds   = form.getlist('cred_pwd')
        notes  = form.getlist('cred_note')
        for i,u in enumerate(users):
            entries.append({
                'label': labels[i] if i<len(labels) else '',
                'username': u.strip(),
                'password': pwds[i] if i<len(pwds) else '',
                'note': notes[i] if i<len(notes) else ''
            })
        return {'entries': entries}
    elif stype == 'custom':
        pairs = []
        keys  = form.getlist('kv_key')
        vals  = form.getlist('kv_val')
        for i,k in enumerate(keys):
            if k.strip():
                pairs.append({'key': k.strip(), 'value': vals[i] if i<len(vals) else ''})
        return {'pairs': pairs}
    return {}

# ── KNOWLEDGE BASE ────────────────────────────────────────────────────────────

@app.route('/project/<int:pid>/kb')
@login_required
def kb_list(pid):
    p     = Project.query.get_or_404(pid)
    pages = KBPage.query.filter_by(project_id=pid).order_by(KBPage.order, KBPage.created).all()
    return render_template('kb_list.html', project=p, pages=pages)

@app.route('/project/<int:pid>/kb/new', methods=['GET','POST'])
@login_required
def kb_new(pid):
    p = Project.query.get_or_404(pid)
    if request.method == 'POST':
        pg = KBPage(
            project_id=pid,
            title=request.form.get('title','').strip(),
            content=request.form.get('content',''),
            updated=datetime.utcnow()
        )
        if not pg.title:
            flash('Title required.','error')
            return render_template('kb_form.html', project=p, page=None)
        db.session.add(pg)
        p.updated = datetime.utcnow()
        db.session.commit()
        flash('KB page created.','success')
        return redirect(url_for('kb_view', pid=pid, pgid=pg.id))
    return render_template('kb_form.html', project=p, page=None)

@app.route('/project/<int:pid>/kb/<int:pgid>')
@login_required
def kb_view(pid, pgid):
    p  = Project.query.get_or_404(pid)
    pg = KBPage.query.get_or_404(pgid)
    pages = KBPage.query.filter_by(project_id=pid).order_by(KBPage.order, KBPage.created).all()
    return render_template('kb_view.html', project=p, page=pg, pages=pages)

@app.route('/project/<int:pid>/kb/<int:pgid>/edit', methods=['GET','POST'])
@login_required
def kb_edit(pid, pgid):
    p  = Project.query.get_or_404(pid)
    pg = KBPage.query.get_or_404(pgid)
    if request.method == 'POST':
        pg.title   = request.form.get('title','').strip()
        pg.content = request.form.get('content','')
        pg.updated = datetime.utcnow()
        p.updated  = datetime.utcnow()
        db.session.commit()
        flash('KB page updated.','success')
        return redirect(url_for('kb_view', pid=pid, pgid=pg.id))
    return render_template('kb_form.html', project=p, page=pg)

@app.route('/project/<int:pid>/kb/<int:pgid>/delete', methods=['POST'])
@login_required
def kb_delete(pid, pgid):
    pg = KBPage.query.get_or_404(pgid)
    db.session.delete(pg)
    db.session.commit()
    flash('KB page deleted.','success')
    return redirect(url_for('kb_list', pid=pid))

# ── SECTION PASSWORD REVEAL API ───────────────────────────────────────────────

@app.route('/api/section/<int:secid>/passwords')
@login_required
def api_passwords(secid):
    sec = SiteSection.query.get_or_404(secid)
    d = sec.get_data()
    return jsonify(d.get('entries',[]))

# ── INIT ──────────────────────────────────────────────────────────────────────

def init_db():
    with app.app_context():
        db.create_all()
        if Project.query.count() == 0:
            p = Project(name='Maximo MAS 8 — Shell QGC', description='IBM Maximo Application Suite 8 support and administration for Shell QGC.', color='#1a5fa8', icon='⚙️')
            db.session.add(p)
            db.session.flush()
            s = Site(project_id=p.id, name='Production', environment='Production', description='Live production environment', updated=datetime.utcnow())
            db.session.add(s)
            db.session.flush()
            sec1 = SiteSection(site_id=s.id, stype='url', title='Application URLs', order=0)
            sec1.set_data({'entries':[
                {'label':'Maximo UI','url':'https://maximo.shell-qgc.com/maximo','desc':'Main application'},
                {'label':'MAS Admin','url':'https://mas.shell-qgc.com/','desc':'MAS admin console'},
            ]})
            sec2 = SiteSection(site_id=s.id, stype='server', title='App Server', order=1)
            sec2.set_data({'hostname':'mas-app01.shell-qgc.internal','ip':'10.10.1.50','os':'RHEL 8.6','version':'MAS 8.11','cpu':'16 vCPU','ram':'64 GB','disk':'500 GB','location':'Brisbane DC','notes':'Liberty profile. Logs: /var/maximo/logs'})
            sec3 = SiteSection(site_id=s.id, stype='database', title='Maximo DB', order=2)
            sec3.set_data({'db_type':'Oracle','host':'db01.shell-qgc.internal','port':'1521','sid':'MAXDB','schema':'MAXIMO','version':'Oracle 19c','notes':'RAC cluster. DBA: roger.harkness@shell.com'})
            sec4 = SiteSection(site_id=s.id, stype='credentials', title='Credentials', order=3)
            sec4.set_data({'entries':[
                {'label':'Maximo Admin','username':'maxadmin','password':'Change_Me_123!','note':'Application admin'},
                {'label':'DB Admin','username':'MAXIMO','password':'DB_Pass_456!','note':'Schema owner — via CyberArk'},
            ]})
            db.session.add_all([sec1,sec2,sec3,sec4])
            kb = KBPage(project_id=p.id, title='Automation Scripts — BGUPDATEMA & BGWOAPPR', content='<h2>Automation Scripts Overview</h2><p>Key automation scripts running in the Maximo environment:</p><h3>BGUPDATEMA</h3><p>Re-creates material reservations when Work Order status changes. Monitor this if MR count spikes unexpectedly.</p><h3>BGWOAPPR</h3><p>Handles bulk Work Order approval workflows. Stuck instances found in <code>WFINSTANCE</code> table.</p><h3>Useful SQL</h3><pre><code>-- Find stuck workflow instances\nSELECT * FROM WFINSTANCE \nWHERE STATUS=\'ACTIVE\' \nAND COMPLETIONDATE IS NULL\nAND OWNERTABLE=\'WORKORDER\';</code></pre><h3>Resolution Steps</h3><ol><li>Identify the stuck WFID from query above</li><li>Check WFASSIGNMENT for active assignments</li><li>Reassign or stop workflow via Maximo UI</li><li>If stuck in DB, update STATUS=\'COMPLETE\' after approval</li></ol>')
            db.session.add(kb)
            db.session.commit()
            print('Sample data seeded.')



# ── TASKS MODEL (appended) ─────────────────────────────────────────────────────
# NOTE: Already imported above — this extends the existing app

class Task(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    status      = db.Column(db.String(20), default='open')   # open, inprogress, blocked, closed
    priority    = db.Column(db.String(10), default='medium') # low, medium, high, critical
    project_id  = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    due_date    = db.Column(db.String(20))
    closed_at   = db.Column(db.DateTime)
    created     = db.Column(db.DateTime, default=datetime.utcnow)
    updated     = db.Column(db.DateTime, default=datetime.utcnow)
    project_rel = db.relationship('Project', backref='tasks', lazy=True, foreign_keys=[project_id])

# ── TASKS ROUTES ──────────────────────────────────────────────────────────────

STATUSES  = ['open','inprogress','blocked','closed']
PRIORITIES = ['low','medium','high','critical']

@app.route('/tasks')
@login_required
def tasks():
    status_f  = request.args.get('status','')
    project_f = request.args.get('project','')
    priority_f= request.args.get('priority','')
    q         = request.args.get('q','').strip()

    query = Task.query
    if status_f:   query = query.filter_by(status=status_f)
    if project_f:  query = query.filter_by(project_id=int(project_f) if project_f.isdigit() else None)
    if priority_f: query = query.filter_by(priority=priority_f)
    if q:
        query = query.filter(db.or_(Task.title.ilike(f'%{q}%'), Task.description.ilike(f'%{q}%')))

    # Default: non-closed first, then closed; within each group newest first
    tasks_open   = query.filter(Task.status != 'closed').order_by(
        db.case({'critical':0,'high':1,'medium':2,'low':3}, value=Task.priority),
        Task.due_date.asc().nullslast(), Task.created.desc()
    ).all()
    tasks_closed = query.filter(Task.status == 'closed').order_by(Task.closed_at.desc()).all() if not status_f or status_f == 'closed' else []
    if status_f == 'closed':
        tasks_open, tasks_closed = [], tasks_closed

    projects = Project.query.order_by(Project.name).all()
    counts = {
        'all':        Task.query.count(),
        'open':       Task.query.filter_by(status='open').count(),
        'inprogress': Task.query.filter_by(status='inprogress').count(),
        'blocked':    Task.query.filter_by(status='blocked').count(),
        'closed':     Task.query.filter_by(status='closed').count(),
    }
    return render_template('tasks.html',
        tasks_open=tasks_open, tasks_closed=tasks_closed,
        projects=projects, counts=counts,
        status_f=status_f, project_f=project_f, priority_f=priority_f, q=q)

@app.route('/tasks/new', methods=['GET','POST'])
@login_required
def task_new():
    projects = Project.query.order_by(Project.name).all()
    if request.method == 'POST':
        title = request.form.get('title','').strip()
        if not title:
            flash('Title is required.','error')
            return render_template('task_form.html', task=None, projects=projects)
        t = Task(
            title      = title,
            description= request.form.get('description','').strip(),
            status     = request.form.get('status','open'),
            priority   = request.form.get('priority','medium'),
            project_id = int(request.form.get('project_id')) if request.form.get('project_id') else None,
            due_date   = request.form.get('due_date','') or None,
            updated    = datetime.utcnow()
        )
        db.session.add(t)
        db.session.commit()
        flash(f'Task "{t.title}" created.','success')
        return redirect(url_for('tasks'))
    # pre-select project if coming from project page
    preselect = request.args.get('project_id','')
    return render_template('task_form.html', task=None, projects=projects, preselect=preselect)

@app.route('/tasks/<int:tid>/edit', methods=['GET','POST'])
@login_required
def task_edit(tid):
    t = Task.query.get_or_404(tid)
    projects = Project.query.order_by(Project.name).all()
    if request.method == 'POST':
        t.title       = request.form.get('title','').strip()
        t.description = request.form.get('description','').strip()
        old_status    = t.status
        t.status      = request.form.get('status','open')
        t.priority    = request.form.get('priority','medium')
        t.project_id  = int(request.form.get('project_id')) if request.form.get('project_id') else None
        t.due_date    = request.form.get('due_date','') or None
        t.updated     = datetime.utcnow()
        if t.status == 'closed' and old_status != 'closed':
            t.closed_at = datetime.utcnow()
        elif t.status != 'closed':
            t.closed_at = None
        db.session.commit()
        flash(f'Task updated.','success')
        return redirect(url_for('tasks'))
    return render_template('task_form.html', task=t, projects=projects, preselect='')

@app.route('/tasks/<int:tid>/status', methods=['POST'])
@login_required
def task_status(tid):
    t = Task.query.get_or_404(tid)
    new_status = request.form.get('status')
    if new_status in STATUSES:
        old = t.status
        t.status  = new_status
        t.updated = datetime.utcnow()
        if new_status == 'closed' and old != 'closed':
            t.closed_at = datetime.utcnow()
        elif new_status != 'closed':
            t.closed_at = None
        db.session.commit()
    return redirect(request.referrer or url_for('tasks'))

@app.route('/tasks/<int:tid>/delete', methods=['POST'])
@login_required
def task_delete(tid):
    t = Task.query.get_or_404(tid)
    db.session.delete(t)
    db.session.commit()
    flash('Task deleted.','success')
    return redirect(url_for('tasks'))

# ── CONTEXT PROCESSOR ─────────────────────────────────────────────────────────
@app.context_processor
def inject_globals():
    count = 0
    if session.get('logged_in'):
        try:
            count = Task.query.filter(Task.status != 'closed').count()
        except:
            count = 0
    return dict(open_task_count=count, now_date=datetime.utcnow().strftime('%Y-%m-%d'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
