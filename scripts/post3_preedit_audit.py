from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [Path(line) for line in subprocess.check_output(['git','ls-files'], cwd=ROOT, text=True).splitlines()]
production = [
    Path('app/simulation/perception.py'), Path('app/simulation/actions.py'), Path('app/simulation/engine.py'),
    Path('app/simulation/scheduler.py'), Path('app/simulation/agent.py'), Path('app/simulation/cognition.py'),
    Path('app/llm/prompts.py'), Path('app/llm/fallback.py'), Path('app/storage/snapshots.py'),
]
keywords = ('version','update','release','manifest','installer','install')
related = sorted(str(p) for p in FILES if any(k in str(p).lower() for k in keywords))

rows=[]
ops=(ast.BinOp,ast.Compare,ast.Call,ast.Subscript,ast.Attribute,ast.For,ast.ListComp,ast.DictComp,ast.SetComp)
for path in production:
    if not (ROOT/path).exists():
        continue
    tree=ast.parse((ROOT/path).read_text(encoding='utf-8'))
    parents={}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node): parents[child]=node
    for node in ast.walk(tree):
        if isinstance(node, ops):
            text=ast.get_source_segment((ROOT/path).read_text(encoding='utf-8'), node) or type(node).__name__
            low=text.lower()
            tracked=('hunger','hydration','health','energy','temperature','sleep_pressure','pain','priority','created_at','updated_at','confidence','salience','sim_time','agent.x','agent.y','movement_speed','quantity','nutrition','known_locations','map_markers','beliefs','notes','tasks','recent_events','json.dumps','sort','round(','int(','float(')
            if any(x in low for x in tracked):
                fn='module'
                cur=node
                while cur in parents:
                    cur=parents[cur]
                    if isinstance(cur,(ast.FunctionDef,ast.AsyncFunctionDef)):
                        fn=cur.name; break
                kind=type(node).__name__
                rows.append((str(path),fn,node.lineno,kind,' '.join(text.split())[:220]))
# tightly related by file/function/kind, unique source snippet
unique=[]; seen=set()
for row in rows:
    key=(row[0],row[1],row[3],row[4])
    if key not in seen:
        seen.add(key); unique.append(row)

out=[]
out.append(f'OPERATION_GROUP_COUNT={len(unique)}')
out.append('PRODUCTION_FILES_AUDITED=' + ','.join(str(p) for p in production if (ROOT/p).exists()))
out.append('RELATED_FILES:')
out.extend(related)
out.append('OPERATION_GROUPS:')
for i,row in enumerate(unique,1): out.append(f'{i:03d}|{row[0]}|{row[1]}|L{row[2]}|{row[3]}|{row[4]}')

# Compatibility evidence using actual packaging dependency and repository code.
from packaging.version import Version
versions=['0.4.0','0.4.0.post1','0.4.0.post2','0.4.0.post3']
out.append('VERSION_ORDER=' + '<'.join(v for v in versions if Version(v)))
out.append('POST3_GT_ALL=' + str(all(Version('0.4.0.post3') > Version(v) for v in versions[:-1])))
out.append('TAG_PARSE=' + str(Version('v0.4.0.post3'.removeprefix('v'))))

for path in related:
    p=ROOT/path
    if p.is_file() and p.stat().st_size < 300000:
        text=p.read_text(encoding='utf-8', errors='replace')
        if any(token in text for token in ('packaging.version','Version(','update-manifest.json','tag_name','releases/latest','__version__','project.version','RELEASE_TAG')):
            out.append(f'--- {path} ---')
            for n,line in enumerate(text.splitlines(),1):
                if any(token.lower() in line.lower() for token in ('packaging.version','Version(','update-manifest.json','tag_name','releases/latest','__version__','project.version','release_tag','latest')):
                    out.append(f'{n}: {line[:300]}')

(ROOT/'post3-preedit-audit.txt').write_text('\n'.join(out)+'\n', encoding='utf-8')
