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
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB

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

# ── GLOBAL SEARCH ─────────────────────────────────────────────────────────────

@app.route('/search')
@login_required
def global_search():
    q = request.args.get('q', '').strip()
    results = {
        'projects': [], 'sites': [], 'sections': [], 'kb': [], 'tasks': []
    }
    total = 0

    if q and len(q) >= 2:
        like = f'%{q}%'

        # Projects
        projs = Project.query.filter(
            db.or_(Project.name.ilike(like), Project.description.ilike(like))
        ).order_by(Project.updated.desc()).limit(20).all()
        results['projects'] = projs
        total += len(projs)

        # Sites
        sites = Site.query.filter(
            db.or_(Site.name.ilike(like), Site.description.ilike(like), Site.environment.ilike(like))
        ).order_by(Site.updated.desc()).limit(20).all()
        results['sites'] = sites
        total += len(sites)

        # Sections — search title and the JSON blob (covers URLs, server names, DB names, custom keys/values)
        secs = SiteSection.query.filter(
            db.or_(SiteSection.title.ilike(like), SiteSection.data_json.ilike(like))
        ).order_by(SiteSection.created.desc()).limit(30).all()
        results['sections'] = secs
        total += len(secs)

        # Knowledge Base
        kb = KBPage.query.filter(
            db.or_(KBPage.title.ilike(like), KBPage.content.ilike(like))
        ).order_by(KBPage.updated.desc()).limit(20).all()
        results['kb'] = kb
        total += len(kb)

        # Tasks
        tasks_r = Task.query.filter(
            db.or_(Task.title.ilike(like), Task.description.ilike(like))
        ).order_by(Task.created.desc()).limit(30).all()
        results['tasks'] = tasks_r
        total += len(tasks_r)

    return render_template('search_results.html', q=q, results=results, total=total)

@app.route('/api/search-suggest')
@login_required
def search_suggest():
    """Lightweight JSON endpoint for live dropdown suggestions."""
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify([])
    like = f'%{q}%'
    out = []

    for p in Project.query.filter(Project.name.ilike(like)).limit(4).all():
        out.append({'type':'Project','icon':p.icon or '📁','title':p.name,
                     'subtitle':'Project','url':url_for('project_detail', pid=p.id)})

    for s in Site.query.filter(Site.name.ilike(like)).limit(4).all():
        out.append({'type':'Site','icon':'🌐','title':s.name,
                     'subtitle':(s.project.name if s.project else 'Site'),
                     'url':url_for('site_detail', pid=s.project_id, sid=s.id)})

    for sec in SiteSection.query.filter(
            db.or_(SiteSection.title.ilike(like), SiteSection.data_json.ilike(like))).limit(4).all():
        site = sec.site
        out.append({'type':'Section','icon':'🔑','title':sec.title or sec.stype,
                     'subtitle': (site.name if site else 'Section'),
                     'url': url_for('site_detail', pid=site.project_id, sid=site.id) if site else '#'})

    for k in KBPage.query.filter(db.or_(KBPage.title.ilike(like), KBPage.content.ilike(like))).limit(4).all():
        out.append({'type':'KB Article','icon':'📄','title':k.title,
                     'subtitle':(k.project.name if k.project else 'Knowledge Base'),
                     'url':url_for('kb_view', pid=k.project_id, pgid=k.id)})

    for t in Task.query.filter(db.or_(Task.title.ilike(like), Task.description.ilike(like))).limit(4).all():
        out.append({'type':'Task','icon':'✅','title':t.title,
                     'subtitle': t.status.capitalize(), 'url': url_for('tasks') + '#task-'+str(t.id)})

    return jsonify(out[:14])

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
        title   = request.form.get('title','').strip()
        content = request.form.get('content','').strip()
        # fallback: if content empty but raw html textarea has data
        if not content:
            content = request.form.get('_html_raw','').strip()
        # fallback: if html file uploaded
        html_file = request.files.get('html_file')
        if html_file and html_file.filename:
            try:
                content = html_file.read().decode('utf-8', errors='replace')
            except Exception:
                pass
        if not title:
            flash('Title required.','error')
            return render_template('kb_form.html', project=p, page=None)
        pg = KBPage(
            project_id=pid,
            title=title,
            content=content,
            updated=datetime.utcnow()
        )
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
        content    = request.form.get('content','').strip()
        if not content:
            content = request.form.get('_html_raw','').strip()
        html_file = request.files.get('html_file')
        if html_file and html_file.filename:
            try:
                content = html_file.read().decode('utf-8', errors='replace')
            except Exception:
                pass
        pg.content = content
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

@app.errorhandler(413)
def too_large(e):
    return '''<!DOCTYPE html><html><head><title>Content Too Large</title>
    <style>body{font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f4f3f1}
    .box{background:#fff;border-radius:12px;padding:36px 32px;max-width:480px;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,.1)}
    h1{font-size:20px;margin-bottom:10px;color:#1a1a18}p{font-size:13px;color:#5a5852;margin-bottom:20px;line-height:1.6}
    a{display:inline-block;padding:9px 20px;background:#1a5fa8;color:#fff;border-radius:6px;font-size:13px;text-decoration:none}</style></head>
    <body><div class="box"><div style="font-size:36px;margin-bottom:12px">📄</div>
    <h1>Content Too Large</h1>
    <p>The content you are trying to save exceeds the maximum allowed size.<br><br>
    <strong>Tip:</strong> If pasting large HTML, try splitting into multiple KB pages, or remove large embedded images/base64 data.</p>
    <a href="javascript:history.back()">← Go Back</a></div></body></html>''', 413

@app.route('/tools/timezone', methods=['GET'])
@login_required
def timezone_converter():
    return render_template('timezone_converter.html')

@app.route('/tools/csr')
@login_required
def csr_generator():
    return render_template('csr_generator.html')


# ══════════════════════════════════════════════════════════════════════════════
# TOOL: POSTMAN-LIKE HTTP CLIENT
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/tools/postman')
@login_required
def postman():
    configs = PostmanConfig.query.order_by(PostmanConfig.updated.desc()).all()
    return render_template('postman.html', configs=configs)

@app.route('/tools/postman/config/save', methods=['POST'])
@login_required
def postman_config_save():
    data = request.get_json()
    cid = data.get('id')
    if cid:
        cfg = PostmanConfig.query.get_or_404(cid)
    else:
        cfg = PostmanConfig()
        db.session.add(cfg)
    cfg.name        = data.get('name','Untitled')
    cfg.method      = data.get('method','GET')
    cfg.url         = data.get('url','')
    cfg.headers     = data.get('headers','{}')
    cfg.body        = data.get('body','')
    cfg.body_type   = data.get('body_type','json')
    cfg.auth_type   = data.get('auth_type','none')
    cfg.auth_data   = data.get('auth_data','{}')
    cfg.description = data.get('description','')
    cfg.updated     = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok':True,'id':cfg.id,'name':cfg.name})

@app.route('/tools/postman/config/<int:cid>', methods=['GET'])
@login_required
def postman_config_get(cid):
    cfg = PostmanConfig.query.get_or_404(cid)
    return jsonify({
        'id':cfg.id,'name':cfg.name,'method':cfg.method,'url':cfg.url,
        'headers':cfg.headers,'body':cfg.body,'body_type':cfg.body_type,
        'auth_type':cfg.auth_type,'auth_data':cfg.auth_data,'description':cfg.description
    })

@app.route('/tools/postman/config/<int:cid>/delete', methods=['POST'])
@login_required
def postman_config_delete(cid):
    cfg = PostmanConfig.query.get_or_404(cid)
    db.session.delete(cfg)
    db.session.commit()
    return jsonify({'ok':True})

@app.route('/tools/postman/send', methods=['POST'])
@login_required
def postman_send():
    import requests as req_lib, json as json_lib, time as time_lib
    data = request.get_json()
    method   = data.get('method','GET').upper()
    url      = data.get('url','').strip()
    hdrs     = {}
    try: hdrs = json_lib.loads(data.get('headers') or '{}')
    except: pass
    body     = data.get('body','')
    btype    = data.get('body_type','json')
    auth_t   = data.get('auth_type','none')
    auth_d   = {}
    try: auth_d = json_lib.loads(data.get('auth_data') or '{}')
    except: pass

    # Auth
    auth_arg = None
    if auth_t == 'basic':
        auth_arg = (auth_d.get('username',''), auth_d.get('password',''))
    elif auth_t == 'bearer':
        hdrs['Authorization'] = 'Bearer ' + auth_d.get('token','')
    elif auth_t == 'apikey':
        key_in = auth_d.get('in','header')
        if key_in == 'header':
            hdrs[auth_d.get('key','X-API-Key')] = auth_d.get('value','')

    # Body
    send_kwargs = {'headers':hdrs, 'auth':auth_arg, 'timeout':30, 'verify':False}
    if method in ('POST','PUT','PATCH','DELETE') and body:
        if btype == 'json':
            try:
                send_kwargs['json'] = json_lib.loads(body)
            except:
                send_kwargs['data'] = body
                hdrs.setdefault('Content-Type','application/json')
        elif btype == 'form':
            import urllib.parse
            send_kwargs['data'] = dict(urllib.parse.parse_qsl(body))
        else:
            send_kwargs['data'] = body

    t0 = time_lib.time()
    try:
        resp = req_lib.request(method, url, **send_kwargs)
        elapsed = round((time_lib.time()-t0)*1000)
        ct = resp.headers.get('Content-Type','')
        body_out = ''
        if 'json' in ct:
            try: body_out = json_lib.dumps(resp.json(), indent=2)
            except: body_out = resp.text
        else:
            body_out = resp.text[:50000]
        resp_hdrs = dict(resp.headers)
        return jsonify({
            'ok':True,'status':resp.status_code,'elapsed':elapsed,
            'body':body_out,'headers':resp_hdrs,'content_type':ct,
            'size':len(resp.content)
        })
    except Exception as e:
        return jsonify({'ok':False,'error':str(e)})


# ══════════════════════════════════════════════════════════════════════════════
# TOOL: SQL QUERY EXECUTOR
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/tools/sql')
@login_required
def sql_tool():
    configs = SqlConfig.query.order_by(SqlConfig.updated.desc()).all()
    queries = SqlQuery.query.order_by(SqlQuery.id.desc()).all()
    return render_template('sql_tool.html', configs=configs, queries=queries)

@app.route('/tools/sql/config/save', methods=['POST'])
@login_required
def sql_config_save():
    data = request.get_json()
    cid = data.get('id')
    if cid:
        cfg = SqlConfig.query.get_or_404(cid)
    else:
        cfg = SqlConfig()
        db.session.add(cfg)
    cfg.name        = data.get('name','Untitled')
    cfg.db_type     = data.get('db_type','oracle')
    cfg.host        = data.get('host','')
    cfg.port        = data.get('port','')
    cfg.database    = data.get('database','')
    cfg.username    = data.get('username','')
    cfg.password    = data.get('password','')
    cfg.description = data.get('description','')
    cfg.updated     = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok':True,'id':cfg.id,'name':cfg.name})

@app.route('/tools/sql/config/<int:cid>', methods=['GET'])
@login_required
def sql_config_get(cid):
    cfg = SqlConfig.query.get_or_404(cid)
    return jsonify({
        'id':cfg.id,'name':cfg.name,'db_type':cfg.db_type,'host':cfg.host,
        'port':cfg.port,'database':cfg.database,'username':cfg.username,
        'password':cfg.password,'description':cfg.description
    })

@app.route('/tools/sql/config/<int:cid>/delete', methods=['POST'])
@login_required
def sql_config_delete(cid):
    cfg = SqlConfig.query.get_or_404(cid)
    SqlQuery.query.filter_by(config_id=cid).update({'config_id':None})
    db.session.delete(cfg)
    db.session.commit()
    return jsonify({'ok':True})

@app.route('/tools/sql/query/save', methods=['POST'])
@login_required
def sql_query_save():
    data = request.get_json()
    qid = data.get('id')
    if qid:
        q = SqlQuery.query.get_or_404(qid)
    else:
        q = SqlQuery()
        db.session.add(q)
    q.name        = data.get('name','Untitled Query')
    q.sql_text    = data.get('sql_text','')
    q.description = data.get('description','')
    q.config_id   = data.get('config_id') or None
    db.session.commit()
    return jsonify({'ok':True,'id':q.id,'name':q.name})

@app.route('/tools/sql/queries', methods=['GET'])
@login_required
def sql_queries_list():
    cid = request.args.get('config_id')
    qs = SqlQuery.query
    if cid: qs = qs.filter_by(config_id=int(cid))
    qs = qs.order_by(SqlQuery.id.desc()).all()
    return jsonify([{'id':q.id,'name':q.name,'sql_text':q.sql_text,
                     'description':q.description,'config_id':q.config_id} for q in qs])

@app.route('/tools/sql/query/<int:qid>/delete', methods=['POST'])
@login_required
def sql_query_delete(qid):
    q = SqlQuery.query.get_or_404(qid)
    db.session.delete(q)
    db.session.commit()
    return jsonify({'ok':True})

@app.route('/tools/sql/driver-status', methods=['GET'])
@login_required
def sql_driver_status():
    """Return which DB drivers are installed on the server."""
    import importlib
    DRIVERS = {
        'oracle':   ['oracledb', 'cx_Oracle'],
        'mysql':    ['pymysql', 'MySQLdb'],
        'postgres': ['psycopg2'],
        'mssql':    ['pyodbc'],
        'sqlite':   ['sqlite3'],
    }
    INSTALL = {
        'oracle':   'pip install oracledb',
        'mysql':    'pip install pymysql',
        'postgres': 'pip install psycopg2-binary',
        'mssql':    'pip install pyodbc  (+ ODBC Driver 17)',
        'sqlite':   'built-in',
    }
    status = {}
    for db_type, mods in DRIVERS.items():
        found = None
        for mod in mods:
            try:
                importlib.import_module(mod)
                found = mod
                break
            except ImportError:
                pass
        status[db_type] = {
            'available': found is not None,
            'driver': found,
            'install': INSTALL.get(db_type, ''),
        }
    return jsonify(status)

@app.route('/tools/sql/execute', methods=['POST'])
@login_required
def sql_execute():
    import importlib, time as time_lib

    data     = request.get_json()
    cfg_id   = data.get('config_id')
    db_type  = data.get('db_type', '').strip()
    host     = data.get('host', '').strip()
    port     = data.get('port', '').strip()
    database = data.get('database', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    sql_text = data.get('sql', '').strip()
    max_rows = max(1, min(int(data.get('max_rows', 200) or 200), 5000))

    # Merge saved connection values (form values override)
    if cfg_id:
        cfg = SqlConfig.query.get(int(cfg_id))
        if cfg:
            db_type  = db_type  or cfg.db_type
            host     = host     or cfg.host
            port     = port     or cfg.port
            database = database or cfg.database
            username = username or cfg.username
            password = password or cfg.password

    if not sql_text:
        return jsonify({'ok': False, 'error': 'No SQL provided.', 'elapsed': 0})
    if not db_type:
        return jsonify({'ok': False, 'error': 'No database type selected.', 'elapsed': 0})

    # ── Driver availability map ───────────────────────────────────────────────
    DRIVER_CANDIDATES = {
        'oracle':   ['oracledb', 'cx_Oracle'],
        'mysql':    ['pymysql', 'MySQLdb'],
        'postgres': ['psycopg2'],
        'mssql':    ['pyodbc'],
        'sqlite':   ['sqlite3'],
    }
    INSTALL_HINT = {
        'oracle':   'pip install oracledb --break-system-packages',
        'mysql':    'pip install pymysql --break-system-packages',
        'postgres': 'pip install psycopg2-binary --break-system-packages',
        'mssql':    'pip install pyodbc --break-system-packages  (also needs: ODBC Driver 17 for SQL Server)',
        'sqlite':   'sqlite3 is built-in — no install needed',
    }

    def load_driver(db_t):
        for mod in DRIVER_CANDIDATES.get(db_t, []):
            try:
                return importlib.import_module(mod), mod
            except ImportError:
                continue
        return None, None

    t0 = time_lib.time()
    conn = None

    try:
        # ── Connect ───────────────────────────────────────────────────────────
        if db_type == 'sqlite':
            import sqlite3
            path = database or ':memory:'
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

        elif db_type == 'oracle':
            mod, mod_name = load_driver('oracle')
            if mod is None:
                hint = INSTALL_HINT['oracle']
                return jsonify({'ok': False, 'elapsed': 0,
                    'error': f'Oracle driver not installed.\n\nRun on the server:\n  {hint}\n\n'
                             f'Then restart Flask.\n\n'
                             f'Note: oracledb works in Thin mode (no Oracle Client needed).'})
            if mod_name == 'oracledb':
                # oracledb thin mode — no Oracle Instant Client required
                dsn = f'{host}:{port or 1521}/{database}'
                conn = mod.connect(user=username, password=password, dsn=dsn)
            else:
                # legacy cx_Oracle
                dsn = mod.makedsn(host, int(port or 1521), service_name=database)
                conn = mod.connect(user=username, password=password, dsn=dsn)
            cur = conn.cursor()

        elif db_type == 'mysql':
            mod, _ = load_driver('mysql')
            if mod is None:
                return jsonify({'ok': False, 'elapsed': 0,
                    'error': f'MySQL driver not installed.\n\nRun:\n  {INSTALL_HINT["mysql"]}\n\nThen restart Flask.'})
            conn = mod.connect(
                host=host, port=int(port or 3306),
                user=username, password=password,
                database=database,
                cursorclass=mod.cursors.DictCursor
            )
            cur = conn.cursor()

        elif db_type == 'postgres':
            mod, _ = load_driver('postgres')
            if mod is None:
                return jsonify({'ok': False, 'elapsed': 0,
                    'error': f'PostgreSQL driver not installed.\n\nRun:\n  {INSTALL_HINT["postgres"]}\n\nThen restart Flask.'})
            conn = mod.connect(
                host=host, port=int(port or 5432),
                user=username, password=password, dbname=database
            )
            cur = conn.cursor()

        elif db_type == 'mssql':
            mod, _ = load_driver('mssql')
            if mod is None:
                return jsonify({'ok': False, 'elapsed': 0,
                    'error': f'MS SQL driver not installed.\n\nRun:\n  {INSTALL_HINT["mssql"]}\n\nThen restart Flask.'})
            cs = (f'DRIVER={{ODBC Driver 17 for SQL Server}};'
                  f'SERVER={host},{port or 1433};DATABASE={database};'
                  f'UID={username};PWD={password}')
            conn = mod.connect(cs)
            cur = conn.cursor()

        else:
            return jsonify({'ok': False, 'error': f'Unknown DB type: {db_type}', 'elapsed': 0})

        # ── Execute statements ────────────────────────────────────────────────
        # Split on semicolons but ignore semicolons inside quotes
        import re
        stmts = [s.strip() for s in re.split(r';\s*(?=(?:[^\'"]|\'[^\']*\'|"[^"]*")*$)', sql_text) if s.strip()]
        results = []

        for stmt in stmts:
            verb = stmt.split()[0].upper() if stmt.split() else ''
            cur.execute(stmt)

            is_select = (verb == 'SELECT') or (hasattr(cur, 'description') and cur.description)

            if is_select:
                desc = cur.description or []
                cols = [str(d[0]) for d in desc]

                if db_type == 'mysql':
                    # pymysql DictCursor returns dicts
                    rows_raw = cur.fetchmany(max_rows + 1)
                    has_more = len(rows_raw) > max_rows
                    rows_raw = rows_raw[:max_rows]
                    rows = []
                    for r in rows_raw:
                        row = {}
                        for c in cols:
                            v = r.get(c)
                            row[c] = str(v) if v is not None else None
                        rows.append(row)
                else:
                    rows_raw = cur.fetchmany(max_rows + 1)
                    has_more = len(rows_raw) > max_rows
                    rows_raw = rows_raw[:max_rows]
                    rows = []
                    for r in rows_raw:
                        row = {}
                        for i, c in enumerate(cols):
                            try:
                                v = r[i] if not isinstance(r, (dict, sqlite3.Row if db_type=='sqlite' else dict)) else r[c]
                            except Exception:
                                try: v = r[i]
                                except: v = None
                            row[c] = str(v) if v is not None else None
                        rows.append(row)

                results.append({
                    'type': 'select',
                    'columns': cols,
                    'rows': rows,
                    'truncated': has_more
                })
            else:
                if db_type != 'oracle':
                    conn.commit()
                results.append({'type': 'dml', 'verb': verb, 'rowcount': cur.rowcount or 0})

        if db_type == 'oracle':
            conn.commit()

        conn.close()
        elapsed = round((time_lib.time() - t0) * 1000)
        return jsonify({'ok': True, 'results': results, 'elapsed': elapsed})

    except Exception as e:
        if conn:
            try: conn.close()
            except: pass
        elapsed = round((time_lib.time() - t0) * 1000)
        return jsonify({'ok': False, 'error': str(e), 'elapsed': elapsed})


# ── POSTMAN SAVED CONFIGS ────────────────────────────────────────────────────
class PostmanConfig(db.Model):
    __tablename__ = 'postman_config'
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)
    method      = db.Column(db.String(10), default='GET')
    url         = db.Column(db.Text, nullable=False)
    headers     = db.Column(db.Text, default='{}')   # JSON string
    body        = db.Column(db.Text, default='')
    body_type   = db.Column(db.String(20), default='json')  # json, form, raw, none
    auth_type   = db.Column(db.String(20), default='none')  # none, basic, bearer, apikey
    auth_data   = db.Column(db.Text, default='{}')   # JSON string
    description = db.Column(db.Text, default='')
    created     = db.Column(db.DateTime, default=datetime.utcnow)
    updated     = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ── SQL QUERY SAVED CONFIGS ──────────────────────────────────────────────────
class SqlConfig(db.Model):
    __tablename__ = 'sql_config'
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)
    db_type     = db.Column(db.String(20), default='oracle')  # oracle, mssql, mysql, postgres, sqlite
    host        = db.Column(db.String(300), default='')
    port        = db.Column(db.String(10), default='')
    database    = db.Column(db.String(200), default='')
    username    = db.Column(db.String(200), default='')
    password    = db.Column(db.Text, default='')
    description = db.Column(db.Text, default='')
    created     = db.Column(db.DateTime, default=datetime.utcnow)
    updated     = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SqlQuery(db.Model):
    __tablename__ = 'sql_query'
    id          = db.Column(db.Integer, primary_key=True)
    config_id   = db.Column(db.Integer, db.ForeignKey('sql_config.id'), nullable=True)
    name        = db.Column(db.String(200), nullable=False)
    sql_text    = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, default='')
    created     = db.Column(db.DateTime, default=datetime.utcnow)
    config      = db.relationship('SqlConfig', backref='queries')

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

# ── TASKS ── ─────────────────────────────────────────────────────
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