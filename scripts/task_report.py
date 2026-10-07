#!/usr/bin/env python3
"""Deterministic task report from already-authorized evidence; no I/O or actions."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

START = '<!-- task-report:v1 -->'
END = '<!-- /task-report -->'
ZONES = {'decision': '🔵待你决策', 'followup': '🟠待你跟进',
         'future': '📅未来待办', 'dot': '🔧dot进行中', 'recover': '🚨待dot重新跟进'}
REQUIRED = {'zone', 'phase', 'next', 'owner', 'thread', 'writer',
            'progress_at', 'observed_at', 'running', 'paused'}


def timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, timezone.utc)
    if not isinstance(value, str):
        raise ValueError('unknown_time')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone_required')
    return result


def validate(row):
    if not isinstance(row, dict) or not REQUIRED <= row.keys():
        raise ValueError('incomplete_row')
    if row['zone'] not in {*ZONES, 'done'}:
        raise ValueError('unknown_zone')
    if not all(isinstance(row[k], str) and row[k] for k in ('phase', 'next', 'owner', 'writer')):
        raise ValueError('missing_fact')
    if not all(type(row[k]) is bool for k in ('running', 'paused')):
        raise ValueError('invalid_execution_flags')
    if row['zone'] in ('decision', 'followup') and row['owner'] != 'user':
        raise ValueError('user_zone_owner_conflict')
    if row['paused'] and (row['running'] or row['zone'] != 'future'):
        raise ValueError('pause_conflict')
    if row['running'] and row['zone'] != 'dot':
        raise ValueError('execution_zone_conflict')
    if row['thread'] is not None and not isinstance(row['thread'], str):
        raise ValueError('invalid_thread')
    if row['thread'] and not re.fullmatch(r'[A-Za-z0-9_-]+', row['thread']):
        raise ValueError('invalid_thread')
    for key in ('progress_at', 'observed_at'):
        if row[key] is not None:
            timestamp(row[key])
    return row


def encode(row):
    """Place this in the original current block, before historical details."""
    validate(row)
    result = START + '\n' + json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n' + END
    if len(result) > 420:
        raise ValueError('head_too_long: shorten prose, keep identity/time fields')
    return result


def extract(description):
    if not isinstance(description, str):
        raise ValueError('missing_head')
    start = description.find(START)
    end = description.find(END, start + len(START))
    if start < 0 or end < 0:
        raise ValueError('missing_or_truncated_head')
    if end + len(END) > 460:
        raise ValueError('head_outside_list_prefix')
    return validate(json.loads(description[start + len(START):end]))


def build(snapshot):
    now = timestamp(snapshot['now'])
    issues = list(snapshot.get('issues', [])) + list(snapshot.get('tasks', []))
    ids = [issue['id'] for issue in issues]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate_issue_id')
    baseline = snapshot.get('baseline', {})
    missing = set(baseline) - set(ids)
    issues = list(issues) + [dict(baseline[key].get('issue', {}), id=key) for key in sorted(missing)]
    threads = {item['id']: item for item in snapshot.get('threads', [])}
    groups = {key: [] for key in ZONES}
    checks, next_baseline, bound_threads = [], {}, set()
    for issue in issues:
        identity = issue['id']
        cached = baseline.get(identity, {})
        row, reasons = None, []
        source_kind = issue.get('source_kind', 'issue')
        project_task = source_kind == 'project_task'
        if source_kind not in ('issue', 'project_task'):
            reasons.append('unknown_source_kind')
        if project_task and not issue.get('source_ref'):
            reasons.append('missing_original_task_source')
        if project_task and not issue.get('updatedAt'):
            reasons.append('source_version_unavailable')
        if identity in missing:
            reasons.append('issue_missing_from_current_directory')
        try:
            if project_task and issue.get('row') is not None:
                row = validate(issue['row'])
            elif START in (issue.get('description') or ''):
                row = extract(issue['description'])
            elif cached.get('issue_updated_at') == issue.get('updatedAt') and cached.get('row'):
                row = validate(cached['row'])
            else:
                row = extract(issue.get('description'))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            reasons.append(str(error))
        if row:
            row = dict(row)
            tid = row['thread']
            if tid:
                bound_threads.add(tid)
            else:
                reasons.append('unmapped_thread')
            try:
                observed = timestamp(row['observed_at'])
                progress = timestamp(row['progress_at']) if row['progress_at'] else None
                if observed > now or (progress and progress > observed):
                    reasons.append('time_conflict')
                active = (row['running'] or issue.get('statusType') == 'started') and not row['paused']
                if active and progress is None:
                    reasons.append('unknown_progress_time')
                elif active and (now - progress).total_seconds() > 3600:
                    reasons.append('progress_over_one_hour')
            except (ValueError, TypeError):
                reasons.append('unknown_progress_time')
            native = issue.get('statusType')
            due = issue.get('dueDate')
            if row['zone'] == 'future' and not row['paused'] and due and str(due)[:10] <= now.date().isoformat():
                reasons.append('future_due_date_review')
            if not project_task and native in ('completed', 'canceled') and row['zone'] != 'done':
                reasons.append('native_state_conflict')
            if not project_task and row['zone'] == 'done' and native not in ('completed', 'canceled'):
                reasons.append('native_state_conflict')
            thread = threads.get(tid)
            if thread:
                if thread.get('metadata_available') is False:
                    reasons.append('thread_metadata_unavailable')
                else:
                    try:
                        if timestamp(thread['updatedAt']) > timestamp(row['observed_at']):
                            reasons.append('new_thread_activity')
                    except (ValueError, KeyError, TypeError):
                        reasons.append('unknown_thread_time')
                status = thread.get('status')
                status = status.get('type') if isinstance(status, dict) else status
                if row['running'] and status in ('idle', 'notLoaded', 'completed', 'failed', 'interrupted'):
                    reasons.append('runtime_state_conflict')
            next_baseline[identity] = {'issue_updated_at': issue.get('updatedAt'), 'row': row,
                                      'issue': {key: issue.get(key) for key in
                                                ('id', 'title', 'updatedAt', 'statusType', 'url', 'dueDate',
                                                 'source_kind', 'source_ref')}}
            if project_task:
                next_baseline[identity]['issue']['source_kind'] = 'project_task'
        if reasons:
            checks.append({'issue': identity, 'thread': row.get('thread') if row else None,
                           'reasons': list(dict.fromkeys(reasons))})
        acknowledged = snapshot.get('coverage', {}).get('unchanged_gap') is True
        only_known_gap = acknowledged and set(reasons) <= {'thread_metadata_unavailable', 'source_version_unavailable'}
        if row and row['zone'] == 'done' and (not reasons or only_known_gap):
            continue
        zone = row['zone'] if row and row['zone'] != 'done' else 'recover'
        title = str(issue.get('title') or identity).replace('\n', ' ')
        title = title.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]')
        entry = '[{}](codex://threads/{})'.format(title, row['thread']) if row and row['thread'] else title
        if row:
            text = '{}｜{}；下一步：{}（{}）'.format(entry, row['phase'], row['next'], row['owner'])
            if row['paused']:
                text += '；暂停，未到恢复条件不催'
            elif zone == 'dot' and not row['running']:
                text += '；等待，未计真实执行'
            text += '；进展时间：{}'.format(row['progress_at'] or '未知')
        else:
            text = '{}｜原当前摘要待核，由dot沿原Issue补证'.format(entry)
        if reasons:
            text += '；待核：' + ', '.join(dict.fromkeys(reasons))
        if project_task:
            source = issue.get('source_ref')
            source = '[原Project任务](<{}>)'.format(source) if isinstance(source, str) and re.fullmatch(r'https?://[^\s<>]+', source) else '原Project入口待核'
            text += '；来源：project_task / ' + source
        groups[zone].append(text)
    unmapped = [tid for tid in threads if tid not in bound_threads]
    coverage = snapshot.get('coverage', {})
    if not coverage.get('issues_complete'):
        checks.append({'issue': None, 'reasons': ['issue_coverage_gap']})
    if not coverage.get('threads_complete'):
        checks.append({'issue': None, 'reasons': ['thread_coverage_gap']})
    for tid in unmapped:
        checks.append({'issue': None, 'thread': tid, 'reasons': ['unmapped_thread']})
    lines = ['核对：{}｜{}'.format(snapshot['now'], coverage.get('label', '覆盖范围未提供'))]
    for key, label in ZONES.items():
        lines.append(label)
        lines.extend(groups[key] or ['无'])
        lines.append('')
    if checks:
        lines.append('保留{}项证据/覆盖缺口，dot定向核验；不代表全桌面覆盖。'.format(len(checks)))
    stable_gap = coverage.get('unchanged_gap') is True
    actionable = [item for item in checks if (item.get('issue') is not None or item.get('thread'))
                  and not (stable_gap and set(item['reasons']) <= {'thread_metadata_unavailable', 'source_version_unavailable'})]
    routine = not actionable and (not checks or coverage.get('unchanged_gap') is True)
    return {'report': '\n'.join(lines).strip(), 'checks': checks,
            'baseline': next_baseline, 'routine_ready': routine,
            'sources': {issue['id']: {'source_kind': issue.get('source_kind', 'issue'),
                                     'source_ref': issue.get('source_ref') or issue.get('url')}
                        for issue in issues},
            'action': 'review_checks' if not routine else 'rendered', 'starts': 0, 'writes': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', nargs='?', help='snapshot JSON; default stdin')
    parser.add_argument('--encode-head', action='store_true')
    args = parser.parse_args()
    value = json.loads(Path(args.input).read_text() if args.input else sys.stdin.read())
    output = encode(value) if args.encode_head else build(value)
    print(output if isinstance(output, str) else json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
