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
ZONES = {'decision': '【本人取舍】🔵待你决策', 'followup': '【本人操作或验收】🟠待你跟进',
         'future': '【未来或暂停】📅未来待办', 'dot': '【dot推进与待核】',
         'recover': '【dot恢复与核查】🚨待dot重新跟进'}
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


def cell(value):
    """Keep one business item on one Markdown table row."""
    return str(value).replace('\\', '\\\\').replace('|', '\\|').replace('\r', ' ').replace('\n', ' ')


def current_thread_state(thread, snapshot, now):
    """Only a state read in this report's observation window proves running."""
    if not thread:
        return None
    try:
        checked = timestamp(thread.get('observed_at'))
        start = timestamp(snapshot.get('observation_started_at', snapshot['now']))
        if not start <= checked <= now:
            return None
    except (ValueError, TypeError):
        return None
    status = thread.get('status')
    status = status.get('type') if isinstance(status, dict) else status
    return status if status in ('running', 'queued', 'pending', 'starting', 'idle',
                                'completed', 'failed', 'interrupted') else None


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
    excluded_threads = {key: item for key, item in threads.items()
                        if item.get('scope') == 'historical_nonbusiness' and item.get('scope_evidence')
                        and item.get('new_activity') is not True}
    groups = {key: [] for key in ZONES}
    checks, next_baseline, bound_threads, closed = [], {}, set(), []
    for issue in issues:
        identity = issue['id']
        cached = baseline.get(identity, {})
        row, reasons = None, []
        source_kind = issue.get('source_kind') or 'issue'
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
        # Terminal evidence is a source fact, not a fabricated executor row.
        version_matches = cached.get('issue_updated_at') == issue.get('updatedAt')
        terminal = issue.get('terminal_verified') is True
        evidence = issue.get('terminal_evidence')
        if row and row['zone'] == 'done' and issue.get('statusType') in ('completed', 'canceled'):
            terminal = True
            evidence = evidence or '已核原当前摘要：' + str(row['observed_at'])
        if not terminal and version_matches:
            terminal = cached.get('terminal_verified') is True
            evidence = cached.get('terminal_evidence')
        tid = (row or {}).get('thread') or issue.get('thread') or (cached.get('row') or {}).get('thread') or cached.get('issue', {}).get('thread')
        activity = issue.get('new_activity') is True
        thread = threads.get(tid)
        runtime = current_thread_state(thread, snapshot, now)
        activity = activity or runtime == 'running'
        if thread:
            activity = activity or thread.get('new_activity') is True
            try:
                since = (row or {}).get('observed_at') or issue.get('terminal_observed_at') or (cached.get('row') or {}).get('observed_at') or cached.get('issue', {}).get('terminal_observed_at')
                activity = activity or timestamp(thread['updatedAt']) > timestamp(since)
            except (ValueError, KeyError, TypeError):
                pass
        if terminal and evidence and not activity and identity not in missing and not project_task and source_kind == 'issue' and issue.get('statusType') in ('completed', 'canceled') and (not row or row['zone'] == 'done'):
            if tid:
                bound_threads.add(tid)
            closed.append({'id': identity, 'statusType': issue['statusType'], 'evidence': evidence})
            next_baseline[identity] = {'issue_updated_at': issue.get('updatedAt'),
                                      'terminal_verified': True, 'terminal_evidence': evidence,
                                      'issue': {key: issue.get(key) for key in
                                                ('id', 'title', 'updatedAt', 'statusType', 'url', 'dueDate')}}
            next_baseline[identity]['issue'].update(thread=tid, terminal_observed_at=issue.get('terminal_observed_at') or (row or {}).get('observed_at') or cached.get('issue', {}).get('terminal_observed_at'))
            continue
        if row:
            row = dict(row)
            tid = row['thread']
            thread = threads.get(tid)
            runtime = current_thread_state(thread, snapshot, now)
            if tid:
                bound_threads.add(tid)
                if tid in excluded_threads:
                    reasons.append('scope_binding_conflict')
                    excluded_threads.pop(tid)
            else:
                source = issue.get('source_ref') or issue.get('url')
                if row['running'] or not isinstance(source, str) or not re.fullmatch(r'https?://[^\s<>]+', source):
                    reasons.append('unmapped_thread')
            try:
                observed = timestamp(row['observed_at'])
                progress = timestamp(row['progress_at']) if row['progress_at'] else None
                if observed > now or (progress and progress > observed):
                    reasons.append('time_conflict')
                active = (runtime == 'running' or row['running'] or issue.get('statusType') == 'started') and not row['paused']
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
            if tid and row['zone'] == 'dot' and runtime is None:
                reasons.append('runtime_state_unverified')
            if runtime is not None and row['running'] != (runtime == 'running'):
                reasons.append('runtime_state_conflict')
            next_baseline[identity] = {'issue_updated_at': issue.get('updatedAt'), 'row': row,
                                      'issue': {key: issue.get(key) for key in
                                                ('id', 'title', 'business_title', 'updatedAt', 'statusType', 'url', 'dueDate',
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
        title = issue.get('business_title') or issue.get('title')
        title = str(title) if title and title != identity else '业务事项名称待补'
        title = title.replace('[', '\\[').replace(']', '\\]')
        entry = '【{}】'.format(title)
        if row and row['thread']:
            entry += ' [执行入口](codex://threads/{})'.format(row['thread'])
        original = issue.get('source_ref') or issue.get('url')
        if isinstance(original, str) and re.fullmatch(r'https?://[^\s<>]+', original):
            entry += ' [原任务](<{}>)'.format(original)
        if row:
            fact = row['phase']
            next_action = row['next']
            if row['paused']:
                fact = '📅{}；暂停，未到恢复条件不催'.format(fact)
            elif zone == 'dot':
                if runtime == 'running':
                    fact = '🔧独立线程当前运行；最近进展：{}；状态核对：{}'.format(fact, thread['observed_at'])
                elif runtime in ('queued', 'pending', 'starting'):
                    fact = '⏳请求排队或启动中，尚未核实运行；最近记录：{}'.format(fact)
                elif runtime in ('idle', 'completed', 'failed', 'interrupted'):
                    fact = '⏳线程已停止运行；最近进展：{}'.format(fact)
                elif not tid:
                    fact = '⏳等待回执或具体条件；最近记录：{}'.format(fact)
                else:
                    fact = '⏳等待当前线程状态回执；最近记录：{}'.format(fact)
            else:
                icon = {'decision': '🔵', 'followup': '🟠', 'future': '📅', 'recover': '🚨'}[zone]
                fact = icon + fact
        else:
            fact = '🚨当前结果与责任待核'
            next_action = 'dot 沿原任务补齐证据与下一步'
        if reasons:
            fact += '；证据或可见范围待核'
        groups[zone].append('| {} | {} | {} |'.format(cell(entry), cell(fact), cell(next_action)))
    unmapped = [tid for tid in threads if tid not in bound_threads and tid not in excluded_threads]
    coverage = snapshot.get('coverage', {})
    if not coverage.get('issues_complete'):
        checks.append({'issue': None, 'reasons': ['issue_coverage_gap']})
    if not coverage.get('threads_complete'):
        checks.append({'issue': None, 'reasons': ['thread_coverage_gap']})
    for tid in unmapped:
        checks.append({'issue': None, 'thread': tid, 'reasons': ['unmapped_thread']})
    lines = ['【核对范围】截至 {}；{}。'.format(snapshot['now'], cell(coverage.get('label', '覆盖范围未提供'))), '']
    for key, label in ZONES.items():
        lines.append(label)
        lines.extend(['', '| 事项 | 结果、影响或卡点 | 下一步 |', '| --- | --- | --- |'])
        lines.extend(groups[key] or ['| 暂无事项 | — | — |'])
        lines.append('')
    if checks:
        lines.extend(['【核验缺口】🚨dot 将定向核对缺失证据与可见范围；当前报告不代表全桌面覆盖。', ''])
    if excluded_threads or closed:
        lines.append('【范围说明】已核结束事项和历史非业务目录已退出当前待办；新活动仍会复核。')
    stable_gap = coverage.get('unchanged_gap') is True
    actionable = [item for item in checks if (item.get('issue') is not None or item.get('thread'))
                  and not (stable_gap and set(item['reasons']) <= {'thread_metadata_unavailable', 'source_version_unavailable'})]
    routine = not actionable and (not checks or coverage.get('unchanged_gap') is True)
    scope_checks = [item for item in checks if item.get('issue') is None]
    task_checks = [item for item in actionable if item.get('issue') is not None]
    return {'report': '\n'.join(lines).strip(), 'checks': checks,
            'task_checks': task_checks, 'scope_checks': scope_checks,
            'baseline': next_baseline, 'routine_ready': routine,
            'closed': closed, 'excluded_threads': excluded_threads,
            'thread_observations': threads,
            'sources': {issue['id']: {'source_kind': issue.get('source_kind') or 'issue',
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
