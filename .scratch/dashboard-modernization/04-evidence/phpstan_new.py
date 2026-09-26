# Classify PHPStan errors in changed files as new or pre-existing (line text present at HEAD).
import re, subprocess, sys
raw = open(sys.argv[1], encoding='utf-8').read().splitlines()
changed = subprocess.run(['git','-C','D:/Dev/OpenEMRAgent','status','--porcelain','--untracked-files=all'],capture_output=True,text=True).stdout.splitlines()
paths = {}
for l in changed:
    st, p = l[:2], l[3:]
    if p.endswith('.php'): paths[p] = st
root='/var/www/localhost/htdocs/openemr/'
out=[]
for e in raw:
    m = re.match(r'^' + re.escape(root) + r'(.+?):(\d+|\?):(.*)$', e)
    if not m: continue
    p, ln, msg = m.groups()
    if p not in paths: continue
    if ln == '?' :
        out.append(('baseline-note', p, ln, msg)); continue
    cur = open('D:/Dev/OpenEMRAgent/'+p, encoding='utf-8').read().splitlines()
    text = cur[int(ln)-1].strip() if int(ln) <= len(cur) else ''
    if paths[p].strip() == '??':
        out.append(('NEW', p, ln, msg)); continue
    head = subprocess.run(['git','-C','D:/Dev/OpenEMRAgent','show','HEAD:'+p],capture_output=True,text=True,encoding='utf-8').stdout
    out.append(('pre-existing' if text and text in [x.strip() for x in head.splitlines()] else 'NEW', p, ln, msg))
for o in out: print(' | '.join(o))
print('NEW:', sum(1 for o in out if o[0]=='NEW'), 'pre-existing:', sum(1 for o in out if o[0]=='pre-existing'), 'baseline notes:', sum(1 for o in out if o[0]=='baseline-note'))
