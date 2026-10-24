"""Validated profile, page recognition, extraction and evidence-preserving merge."""
import hashlib, json, re
from pathlib import Path
from datetime import datetime
from jsonschema import Draft202012Validator

def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:20]

def norm(text):
    return re.sub(r'\s+', '', text).casefold()

def load_profile(path):
    profile = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    schema = json.loads(Path(__file__).with_name('profile.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator(schema).validate(profile)
    ids=[p['id'] for p in profile['pages']]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate page IDs')
    for page in profile['pages']:
        region = page['region']
        if region[0] >= region[2] or region[1] >= region[3]:
            raise ValueError('Invalid content region')
        for pattern in page['required_patterns'] + page['reject_patterns'] + [page.get('item_start', '')] + [f['pattern'] for f in page['fields']]:
            if pattern:
                re.compile(pattern)
        route_ids=[]
        for route in page.get('routes',[]):
            route_ids.append(route['id'])
            if route['target_page'] not in ids:raise ValueError('Navigation target page is undefined')
            if route['target_page']==page['id'] and route['relation']=='child':raise ValueError('Child route cannot target itself')
            r=route['region']
            if r[0]>=r[2] or r[1]>=r[3]:raise ValueError('Invalid navigation region')
            for key in ('selector','target_key_pattern','verify_pattern'):
                if route.get(key):re.compile(route[key])
            if route['mode']=='each' and re.compile(route['selector']).groups!=1:raise ValueError('Repeated entry selector needs exactly one identity capture group')
            if route.get('target_key_pattern') and re.compile(route['target_key_pattern']).groups!=1:raise ValueError('Target identity needs exactly one capture group')
        if len(route_ids)!=len(set(route_ids)):raise ValueError('Duplicate navigation route IDs')
    overlay_ids=[]
    for rule in profile.get('overlays',[]):
        overlay_ids.append(rule['id'])
        for key in ('region','close_region','identity_region'):
            r=rule[key]
            if r[0]>=r[2] or r[1]>=r[3]:raise ValueError('Invalid overlay region')
        for pattern in rule['patterns']:re.compile(pattern)
        if re.compile(rule['identity_pattern']).groups!=1:raise ValueError('Overlay identity needs one capture group')
    if len(set(overlay_ids))!=len(overlay_ids):raise ValueError('Duplicate overlay IDs')
    return profile

def in_region(lines, size, region):
    w, h = size
    return [x for x in lines if region[0]*w <= (x['box'][0]+x['box'][2])/2 <= region[2]*w
            and region[1]*h <= (x['box'][1]+x['box'][3])/2 <= region[3]*h]

def join_rows(lines):
    """Join neighbouring OCR boxes on the same baseline, preserving originals in cache."""
    rows=[]
    for line in sorted(lines,key=lambda x:(x['box'][1],x['box'][0])):
        target=next((r for r in reversed(rows[-4:]) if abs((r['box'][1]+r['box'][3]-line['box'][1]-line['box'][3])/2)< min(r['box'][3]-r['box'][1],line['box'][3]-line['box'][1])*.4 and -20<=line['box'][0]-r['box'][2]<60 and line['box'][0]>r['box'][0]),None)
        if target:
            overlap=next((n for n in range(min(8,len(target['text']),len(line['text'])),0,-1) if target['text'][-n:]==line['text'][:n]),0) if line['box'][0]<target['box'][2] else 0
            target['text']+=('' if overlap else ' ')+line['text'][overlap:];target['conf']=min(target['conf'],line['conf'])
            target['box']=[min(target['box'][0],line['box'][0]),min(target['box'][1],line['box'][1]),max(target['box'][2],line['box'][2]),max(target['box'][3],line['box'][3])]
        else:rows.append({**line,'box':list(line['box'])})
    return rows

def recognize(profile, ocr):
    from wa_overlays import matching,suspected
    if matching(profile,ocr) or suspected(ocr):return None,'overlay_requires_review'
    full = '\n'.join(x['text'] for x in ocr['lines'])
    matches = []
    for page in profile['pages']:
        if not all(t in norm(full) for t in map(norm,page.get('identity_texts',profile['identity_texts']))):continue
        lines = join_rows(in_region(ocr['lines'], ocr['size'], page['region']))
        text = '\n'.join(x['text'] for x in lines)
        if any(re.search(p, full, re.I) for p in page['reject_patterns']):
            continue
        if not all(re.search(p, text, re.I) for p in page['required_patterns']):
            continue
        if page['kind'] == 'list' and sum(bool(re.search(page['item_start'], l['text'], re.I)) for l in lines) < page['min_items']:
            continue
        matches.append(page)
    return (matches[0], 'matched') if len(matches) == 1 else (None, 'ambiguous_page' if matches else 'unknown_page')

def extract(profile, page, ocr, shot, collection):
    lines = join_rows(in_region(ocr['lines'], ocr['size'], page['region']))
    groups = []
    if page['kind'] == 'list':
        for line in lines:
            if re.search(page['item_start'], line['text'], re.I):
                groups.append([])
            if groups:
                groups[-1].append(line)
    else:
        groups = [lines] if lines else []
    result = []
    for group in groups:
        body = '\n'.join(x['text'] for x in group)
        fields, confidences = {}, {}
        for field in page['fields']:
            for line in group:
                found = re.search(field['pattern'], line['text'], re.I)
                if found:
                    fields[field['name']] = found.group(1) if found.lastindex else found.group(0)
                    confidences[field['name']] = line['conf']
                    break
        title = fields.get('title') or (group[1]['text'] if len(group)>1 else group[0]['text'])
        id_field = page.get('id_field')
        strong_id = fields.get(id_field) if confidences.get(id_field, 0) >= page.get('id_min_confidence', .9) else None
        key = strong_id or norm(title+'|'+body)
        scope = profile['profile_id'] + '|' + collection
        # Weak IDs preserve uncertain repeats for later review.
        identifier = digest(scope+'|'+str(key)+(('|' + ocr['hash']) if not strong_id else ''))
        issues = [] if strong_id else ['weak_identity_possible_duplicate']
        if page['kind'] == 'list' and group is groups[-1]:
            issues.append('last_visible_item_may_be_partial')
        if min(x['conf'] for x in group) < .8:
            issues.append('low_ocr_confidence')
        result.append({'id': identifier, 'title': title, 'body': body, 'fields': fields,
            'confidence': min(x['conf'] for x in group), 'field_confidence': confidences,
            'page_type': page['kind'], 'profile_id': profile['profile_id'], 'collection': collection,
            'identity_field':id_field, 'identity_confident':bool(strong_id),
            'sources': [{'shot': str(shot), 'frame_hash': ocr['hash'], 'page_rule': page['id'],
                         'captured_at': datetime.fromtimestamp(Path(shot).stat().st_mtime).isoformat(timespec='seconds'),
                         'text_boxes': group}], 'issues': issues})
    return result

def merge(existing, incoming):
    by_id = {x['id']: x for x in existing}
    for row in incoming:
        if row['id'] not in by_id:
            for prior in by_id.values():
                if norm(prior['title']) == norm(row['title']) and not (prior.get('identity_confident') and row.get('identity_confident')):
                    row['issues'].append('possible_duplicate_of:'+prior['id'])
            by_id[row['id']] = row
            continue
        old = by_id[row['id']]
        for source in row['sources']:
            if source not in old['sources']:
                old['sources'].append(source)
        for name, value in row['fields'].items():
            if name in old['fields'] and norm(old['fields'][name]) != norm(value):
                issue = 'field_conflict:'+name
                if issue not in old['issues']:
                    old['issues'].append(issue)
            elif name not in old['fields']:
                old['fields'][name] = value
                old['field_confidence'][name] = row.get('field_confidence',{}).get(name,0)
        if len(row['body']) > len(old['body']):
            old['body'], old['title'] = row['body'], row['title']
        old['title']=old['fields'].get('title') or old['title']
        old['issues'] = sorted(set(old['issues'] + row['issues']))
    return list(by_id.values())
