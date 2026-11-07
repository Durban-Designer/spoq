"""Previewed, lossless migration from Markdown/YAML into the new hierarchy."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path

import yaml

from .db import encode, now, transaction, uid
from .store import Store


def database_path(root):
    return Path(root) / '.spoq' / 'spoq.db'


def legacy_files(root):
    root = Path(root).resolve()
    candidates = []
    for base in (root / 'spoq', root / 'factory', root / 'automation', root / 'documents/archive/journals'):
        if base.is_dir():
            candidates.extend(p for p in base.rglob('*') if p.is_file() and p.suffix.lower() in {'.md', '.yml', '.yaml', '.json'})
    candidates.extend(p for p in (root / 'journal.md', root / 'TODO.yml') if p.is_file())
    return sorted({p for p in candidates if p.resolve().is_relative_to(root)})


def status(root):
    root = Path(root)
    files = legacy_files(root)
    exists = database_path(root).is_file()
    return {'database': str(database_path(root)), 'database_exists': exists,
            'migration_required': bool(files) and not exists, 'legacy_files': len(files),
            'prompt': 'Convert journals, tasks, epics, and feature maps to SPOQ 1.0 SQLite? Original files are preserved.',
            'command': f'spoq migrate --root {root}',
            'mapping': 'Feature maps → Project Plans; epics → Features; tasks retain their Feature DAG'}


def get_store(root):
    if database_path(root).is_file():
        return Store(database_path(root))
    info = status(root)
    if info['migration_required']:
        raise ValueError(info['prompt'] + ' Run `spoq migrate` to preview and confirm conversion.')
    return Store(database_path(root))


def _frontmatter(text):
    match = re.match(r'\A\ufeff?---\s*\n(.*?)\n(?:---|\.\.\.)\s*(?:\n|$)', text, re.S)
    if not match:
        return {}
    value = yaml.safe_load(match[1])
    if not isinstance(value, dict):
        raise ValueError('Frontmatter must be a mapping')
    return value


def _slug(path):
    return path.stem if path.is_file() else path.name


def _id(prefix, source):
    return prefix + ':' + hashlib.sha256(str(source).encode()).hexdigest()[:16]


def _task_yaml(text):
    """Recover legacy unquoted checkbox list items without rewriting source bytes."""
    try:
        return yaml.safe_load(text),False
    except yaml.YAMLError:
        repaired=[]
        block_indent=None
        for line in text.splitlines():
            indentation=len(line)-len(line.lstrip())
            if block_indent is not None:
                if not line.strip() or indentation>block_indent:
                    repaired.append(line)
                    continue
                block_indent=None
            match=re.match(r'^(\s*-\s+)(\[(?: |x|X)\]\s+.+)$',line)
            if match:
                line=match[1]+json.dumps(match[2],ensure_ascii=False)
            if re.search(r':\s*[|>](?:[+-][1-9]?|[1-9][+-]?)?\s*(?:#.*)?$',line):
                block_indent=indentation
            repaired.append(line)
        return yaml.safe_load('\n'.join(repaired)+('\n' if text.endswith('\n') else '')),True


def _dependencies(value):
    if value is None:
        return []
    if not isinstance(value,list) or any(not isinstance(item,(str,int)) or isinstance(item,bool) for item in value):
        raise ValueError('dependencies must be a list of task/feature identifiers')
    return [str(item) for item in value]


def preview(root, layout='layer'):
    root = Path(root).resolve()
    if layout != 'layer':
        raise ValueError('Only maps-to-Project-Plans migration is supported')
    epics, maps, warnings = [], [], []
    source_hashes={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in legacy_files(root)}
    for path in legacy_files(root):
        relative = path.relative_to(root).as_posix()
        if path.name == 'EPIC.md':
            text = path.read_text()
            epic_errors=[]
            try:
                metadata = _frontmatter(text)
            except (ValueError, yaml.YAMLError) as exc:
                metadata = {}
                problem=f'{relative}: {exc}; raw source retained'
                warnings.append(problem)
                epic_errors.append(problem)
            task_files = sorted({p for folder in ('tasks', 'stories') for suffix in ('*.yml', '*.yaml')
                                 for p in (path.parent / folder).glob(suffix) if p.resolve().is_relative_to(root)})
            tasks, task_errors = [], list(epic_errors)
            for task_path in task_files:
                try:
                    data, recovered = _task_yaml(task_path.read_text())
                    if recovered:
                        warnings.append(f'{task_path.relative_to(root)}: recovered unquoted checkbox items; original bytes preserved')
                    if not isinstance(data, dict):
                        raise ValueError('Task must be a mapping')
                    try: _dependencies(data.get('dependencies'))
                    except ValueError as exc:
                        task_errors.append(f'{task_path.relative_to(root)}: {exc}')
                    tasks.append({'source': task_path.relative_to(root).as_posix(), 'data': data})
                except (ValueError, yaml.YAMLError) as exc:
                    problem=f'{task_path.relative_to(root)}: {exc}; raw source retained'
                    warnings.append(problem)
                    task_errors.append(problem)
            epics.append({'source': relative, 'slug': metadata.get('slug') or path.parent.name,
                          'title': str(metadata.get('title') or path.parent.name), 'metadata': metadata,
                          'body': text, 'tasks': tasks, 'errors': task_errors})
        elif ('/maps/' in '/' + relative and path.suffix.lower() == '.md' and path.name != 'README.md'
              and (path.name=='MAP.md' or path.parent.parent in
                   {root/base/'maps' for base in ('spoq','factory','automation')})):
            from spoq_server.map_utils import parse_map_md
            parsed = parse_map_md(path)
            if 'error' not in parsed:
                entries=parsed['epics']
                errors=[]
                try: _frontmatter(path.read_text())
                except (ValueError,yaml.YAMLError) as exc: errors.append(f'{relative}: invalid frontmatter: {exc}')
                memberships=parsed.get('frontmatter_epics')
                if memberships is not None and not isinstance(memberships,list):
                    errors.append(f'{relative}: frontmatter epics must be a list')
                    memberships=[]
                if not entries and memberships:
                    for item in memberships:
                        if isinstance(item,str): entries.append({'slug':item,'dependencies':[]})
                        elif isinstance(item,dict) and (item.get('slug') or item.get('id')):
                            try: dependencies=_dependencies(item.get('dependencies',item.get('depends_on')))
                            except ValueError as exc:
                                dependencies=[]
                                errors.append(f'{relative}: {exc}')
                            entries.append({'slug':str(item.get('slug') or item['id']),
                                            'dependencies':dependencies})
                        else: errors.append(f'{relative}: unrecognized frontmatter epic entry {item!r}')
                maps.append({'source': relative, 'slug': path.parent.name if path.name == 'MAP.md' else path.stem,
                             'title': str(parsed['title']), 'body': path.read_text(), 'epics': entries, 'errors':errors})
    # Import orphan task/story directories even when their parent EPIC.md is absent.
    known_tasks={t['source'] for epic in epics for t in epic['tasks']}
    orphan_groups={}
    for path in legacy_files(root):
        relative=path.relative_to(root).as_posix()
        if relative in known_tasks or path.suffix not in {'.yml','.yaml'} or path.parent.name not in {'tasks','stories'}:
            continue
        # A malformed known task is already attached as a blocking error to its epic.
        if any(path.parent.parent==root/epic['source'].rsplit('/',1)[0] for epic in epics):
            continue
        group=path.parent.parent.relative_to(root).as_posix()
        epic=orphan_groups.setdefault(group,{'source':group+'/EPIC.md','slug':path.parent.parent.name,
            'title':path.parent.parent.name,'metadata':{'legacy_directory':group},'body':'','tasks':[],'errors':[]})
        try:
            raw,recovered=_task_yaml(path.read_text())
            if recovered: warnings.append(f'{relative}: recovered unquoted checkbox items; original bytes preserved')
            if not isinstance(raw,dict): raise ValueError('Task must be a mapping')
            try: _dependencies(raw.get('dependencies'))
            except ValueError as exc: epic['errors'].append(f'{relative}: {exc}')
            epic['tasks'].append({'source':relative,'data':raw})
        except (ValueError,yaml.YAMLError) as exc:
            epic['errors'].append(f'{relative}: {exc}; raw source retained')
    epics.extend(orphan_groups.values())
    todo=root/'TODO.yml'
    if todo.is_file():
        errors=[]
        items=[]
        try:
            raw=yaml.safe_load(todo.read_text())
            if raw is None: raw={}
            if not isinstance(raw,dict):
                errors.append('TODO.yml must contain a mapping')
                raw={}
            standalone=raw.get('standalone') or []
            if isinstance(standalone,list): items.extend(standalone)
            else: errors.append('TODO.yml standalone must be a list')
            sections=raw.get('sections') or []
            if not isinstance(sections,list):
                errors.append('TODO.yml sections must be a list')
                sections=[]
            for section in sections:
                if not isinstance(section,dict):
                    errors.append('TODO.yml section must be a mapping')
                    continue
                section_items=section.get('items') or []
                if isinstance(section_items,list): items.extend(section_items)
                else: errors.append('TODO.yml section items must be a list')
        except yaml.YAMLError as exc: errors.append(f'TODO.yml: {exc}; raw source retained')
        tasks=[]
        for i,item in enumerate(items):
            if not isinstance(item,dict):
                errors.append(f'TODO.yml item {i} must be a mapping; original value preserved')
                item={'legacy_value':item,'title':f'Unparsed tracker item {i}'}
            if 'done' in item and not isinstance(item['done'],bool):
                errors.append(f'TODO.yml item {i}: done must be Boolean; completion was not inferred')
            tasks.append({'source':f'TODO.yml#{i}','data':{**item,'id':str(i),
                          'title':item.get('title') or f'Tracker item {i}',
                          'status':'completed' if item.get('done') is True else 'pending','dependencies':[]}})
        if tasks or errors:
            epics.append({'source':'TODO.yml','slug':'task-tracker','title':'Task tracker',
                          'metadata':{'legacy_source':'TODO.yml'},'body':todo.read_text(),'tasks':tasks,'errors':errors})
    warnings=list(dict.fromkeys(warnings+[error for epic in epics for error in epic.get('errors',[])]+[error for item in maps for error in item.get('errors',[])]))
    return {'root': str(root), 'layout': layout, 'epics': epics, 'maps': maps,
            'warnings': warnings, 'source_files': len(legacy_files(root)),
            'source_hashes': source_hashes,
            'counts': {'epics': len(epics), 'feature_maps': len(maps),
                       'tasks': sum(len(e['tasks']) for e in epics)}}


def migrate(root, *, confirmed=False, layout='layer'):
    root = Path(root).resolve()
    plan = preview(root, layout)
    if not confirmed:
        return {'confirmation_required': True, **status(root), 'preview': plan}
    target = database_path(root)
    if target.exists():
        return {'already_migrated': True, **status(root)}
    target.parent.mkdir(parents=True, exist_ok=True)
    # A lock prevents two confirmations from replacing one another's database.
    lock = target.parent / 'migration.lock'
    from .locking import migration_lock
    locks = ExitStack()
    locks.enter_context(migration_lock(lock))
    temporary = target.parent / f'migration-{uid()}.db'
    backup = None
    try:
        if target.exists():
            return {'already_migrated': True, **status(root)}
        store = Store(temporary)
        project = store.create('project_plan', 'workspace', root.name, data={'migrated_at': now()})
        sources = legacy_files(root)
        backup = target.parent / 'backups' / f'pre-v1-{uid()}.zip'
        backup.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(backup, 'w', zipfile.ZIP_DEFLATED) as archive, transaction(temporary, write=True) as db:
            for path in sources:
                content = path.read_bytes()
                name = path.relative_to(root).as_posix()
                if hashlib.sha256(content).hexdigest()!=plan['source_hashes'].get(name):
                    raise ValueError('Legacy sources changed during conversion; retry migration')
                archive.writestr(name, content)
                db.execute('INSERT INTO legacy_sources VALUES(?,?,?)', (name, hashlib.sha256(content).hexdigest(), content))
        epic_by_slug = {}
        for epic in plan['epics']:
            epic_by_slug.setdefault(str(epic['slug']), []).append(epic)
        used, features, task_lookup = set(), {}, {}
        imported_statuses={}
        memberships={}

        def feature(feature_id, title, members, body, metadata):
            errors = [problem for epic in members for problem in epic.get('errors',[])]
            store.create('feature', feature_id, title, project['id'], {'body': body, **metadata})
            for epic in members:
                group = _id('group', epic['source'])
                mapping = {}
                for task in epic['tasks']:
                    raw = task['data']
                    local_id = str(raw.get('id', Path(task['source']).stem))
                    if local_id in mapping:
                        errors.append(f'Duplicate task ID in {epic["source"]}: {local_id}')
                    task_id = _id('task', feature_id + '/' + task['source'])
                    mapping[local_id] = task_id
                    original_status = str(raw.get('status', 'pending'))
                    normalized = {'complete': 'completed', 'done': 'completed'}.get(original_status, original_status)
                    if normalized not in {'pending','in_progress','qa','rework','completed','failed','blocked'}:
                        normalized = 'pending'
                        errors.append(f'Unknown status retained in task metadata: {original_status}')
                    imported_statuses[task_id]=normalized
                    store.create('task', task_id, str(raw.get('title') or local_id), feature_id,
                                 {**raw, 'legacy_epic': epic['slug'], 'legacy_group': group,
                                  'legacy_source': task['source'], 'legacy_id': local_id})
                task_lookup[(feature_id, epic['source'])] = mapping
            for epic in members:
                mapping = task_lookup[(feature_id, epic['source'])]
                for task in epic['tasks']:
                    local_id = str(task['data'].get('id', Path(task['source']).stem))
                    try: dependencies=_dependencies(task['data'].get('dependencies'))
                    except ValueError: dependencies=[]
                    for dependency in dependencies:
                        try:
                            if str(dependency) not in mapping:
                                raise ValueError(f'Unknown task dependency {dependency} in {task["source"]}')
                            store.depend(mapping[local_id], mapping[str(dependency)])
                        except ValueError as exc:
                            errors.append(str(exc))
            features[feature_id] = {'errors': errors, 'members': members}

        for item in plan['maps']:
            members = []
            map_errors = list(item.get('errors',[]))
            for entry in item['epics']:
                matches = epic_by_slug.get(entry['slug'], [])
                if len(matches) == 1:
                    members.append(matches[0])
                    used.add(matches[0]['source'])
                    memberships.setdefault(matches[0]['source'],[]).append(item['source'])
                else:
                    map_errors.append(f'{item["source"]}: missing or ambiguous epic {entry["slug"]}')
            plan_id = _id('plan', item['source'])
            store.create('project_plan', plan_id, item['title'], data={'body': item['body']})
            if not item['epics']:
                map_errors.append(f'{item["source"]}: no parseable epic membership; review the preserved source')
            for epic in members:
                fid = _id('feature', item['source'] + epic['source'])
                feature(fid, epic['title'], [epic], epic['body'], epic['metadata'])
                with transaction(temporary, write=True) as db:
                    db.execute('UPDATE nodes SET parent_id=? WHERE id=?', (plan_id, fid))
            for entry in item['epics']:
                for dep in entry['dependencies']:
                    a = next((e for e in members if e['slug'] == entry['slug']), None)
                    b = next((e for e in members if e['slug'] == dep), None)
                    if a and b:
                        try:
                            store.depend(_id('feature', item['source']+a['source']), _id('feature', item['source']+b['source']))
                        except ValueError as exc:
                            map_errors.append(str(exc))
                    else:
                        map_errors.append(f'{item["source"]}: unresolved dependency {entry["slug"]} -> {dep}')
            if map_errors:
                store.edit(plan_id, {'migration_errors': map_errors})
                store.update(plan_id, 'blocked')
            plan['warnings'].extend(map_errors)
        overlaps={source:owners for source,owners in memberships.items() if len(owners)>1}
        if overlaps:
            for source,owners in overlaps.items():
                problem=f'{source} is shared by multiple legacy maps: {owners}; resolve ownership before execution'
                plan['warnings'].append(problem)
                for owner in owners:
                    plan_id=_id('plan',owner)
                    existing=store.get(plan_id)['data'].get('migration_errors',[])
                    store.edit(plan_id,{'migration_errors':existing+[problem]})
                    store.update(plan_id,'blocked')
        for epic in plan['epics']:
            if epic['source'] not in used:
                feature(_id('feature', epic['source']), epic['title'], [epic], epic['body'], epic['metadata'])
        # Build all dependency edges before restoring completed historical statuses.
        with transaction(temporary,write=True) as db:
            db.executemany('UPDATE nodes SET status=? WHERE id=?',[(value,key) for key,value in imported_statuses.items()])
            for edge in db.execute('''SELECT e.scope_id,e.node_id,e.dependency_id FROM edges e
                    JOIN nodes n ON n.id=e.node_id JOIN nodes d ON d.id=e.dependency_id
                    WHERE n.status='completed' AND d.status<>'completed' '''):
                features[edge['scope_id']]['errors'].append(
                    f'Completed legacy Task {edge["node_id"]} has unfinished prerequisite {edge["dependency_id"]}; review preserved history')
        for fid, info in features.items():
            requested = next((epic['metadata'].get('status') for epic in info['members']
                              if epic['metadata'].get('status') is not None), None)
            requested = None if requested is None else {'complete': 'completed', 'done': 'completed'}.get(str(requested), str(requested))
            children = store.list('task', fid)
            if requested is not None and requested not in {'pending','in_progress','qa','rework','completed','failed','blocked'}:
                info['errors'].append(f'Unknown Feature status preserved in metadata: {requested}')
            if requested == 'completed' and any(t['status']!='completed' for t in children):
                info['errors'].append('Legacy Feature is completed but contains unfinished Tasks; review before execution')
            if info['errors']:
                plan['warnings'].extend(info['errors'])
                with transaction(temporary, write=True) as db:
                    node = store._get(db, fid)
                    node['data']['migration_errors'] = info['errors']
                    db.execute("UPDATE nodes SET status='blocked',data=? WHERE id=?", (encode(node['data']), fid))
            elif requested is not None:
                with transaction(temporary, write=True) as db:
                    db.execute('UPDATE nodes SET status=? WHERE id=?', (requested, fid))
            elif children and all(t['status']=='completed' for t in children):
                # Imported status is provenance; do not invent new validation evidence.
                with transaction(temporary, write=True) as db:
                    db.execute("UPDATE nodes SET status='completed' WHERE id=?", (fid,))
        for item in plan['maps']:
            plan_id = _id('plan', item['source'])
            metadata = _frontmatter(item['body']) if not item.get('errors') else {}
            existing = store.get(plan_id)['data']
            store.edit(plan_id, {**metadata, **existing, 'legacy_source': item['source']})
            errors = list(existing.get('migration_errors', []))
            requested = metadata.get('status')
            requested = None if requested is None else {'complete':'completed','done':'completed'}.get(str(requested),str(requested))
            children = store.list('feature', plan_id)
            if requested is not None and requested not in {'pending','in_progress','qa','rework','completed','failed','blocked'}:
                errors.append(f'Unknown Project Plan status preserved in metadata: {requested}')
            if requested=='completed' and any(child['status']!='completed' for child in children):
                errors.append('Legacy Project Plan is completed but contains unfinished Features')
            with transaction(temporary) as db:
                for edge in db.execute('''SELECT n.id,d.id FROM edges e JOIN nodes n ON n.id=e.node_id
                        JOIN nodes d ON d.id=e.dependency_id WHERE e.scope_id=?
                        AND n.status='completed' AND d.status<>'completed' ''',(plan_id,)):
                    errors.append(f'Completed legacy Feature {edge[0]} has unfinished prerequisite {edge[1]}')
            if errors:
                store.edit(plan_id, {'migration_errors': errors})
                store.update(plan_id, 'blocked')
                plan['warnings'].extend(errors)
            elif requested is not None:
                with transaction(temporary, write=True) as db:
                    db.execute('UPDATE nodes SET status=? WHERE id=?', (requested, plan_id))
        # Preserve all journal text, including non-standard old entries and horizontal rules.
        for path in sources:
            if path.name == 'journal.md' or 'archive/journals/' in path.as_posix():
                text = path.read_text()
                blocks = re.split(r'(?m)(?=^---\nagent:)', text)
                for offset, block in enumerate(blocks):
                    if block.strip():
                        try: metadata=_frontmatter(block)
                        except (ValueError,yaml.YAMLError): metadata={}
                        store.journal(block, str(metadata.get('agent') or 'legacy-import'),
                                      metadata={**metadata,'source': str(path.relative_to(root)), 'block': offset},
                                      entry_id=_id('journal', str(path.relative_to(root))+':'+str(offset)))
        with transaction(temporary, write=True) as db:
            plan['warnings']=list(dict.fromkeys(plan['warnings']))
            db.execute('INSERT INTO meta VALUES(?,?)', ('migration', encode({'layout': layout, 'warnings': plan['warnings'], 'backup': str(backup)})))
        # Every connection is closed; a clean checkpoint guarantees a self-contained file.
        from .db import connect
        db = connect(temporary)
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        db.close()
        current_hashes={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in legacy_files(root)}
        if current_hashes!=plan['source_hashes']:
            raise ValueError('Legacy sources changed during conversion; retry migration')
        # Atomic no-replace publication also protects a store created by another
        # route while conversion was in progress. The staged DB is checkpointed.
        try:
            os.link(temporary, target)
        except FileExistsError:
            return {'already_migrated': True, **status(root)}
        return {'converted': True, 'database': str(target), 'backup': str(backup),
                'counts': plan['counts'], 'warnings': plan['warnings'], 'layout': layout}
    finally:
        temporary.unlink(missing_ok=True)
        for suffix in ('-wal', '-shm'):
            Path(str(temporary)+suffix).unlink(missing_ok=True)
        locks.close()
