import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('task_report', Path(__file__).resolve().parents[1]/'scripts/task_report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def row(**changes):
    value = dict(zone='dot', phase='正在交付', next='完成原目标', owner='dot',
                 thread='thread-1', writer='thread-1', progress_at='2026-01-01T10:00:00Z',
                 observed_at='2026-01-01T10:00:00Z', running=True, paused=False)
    value.update(changes)
    return value


def snapshot(value=None, **changes):
    value = value or row()
    issue = dict(id='TASK-1', title='独立任务', statusType='started', updatedAt='2026-01-01T10:00:00Z',
                 description=report.encode(value))
    result = dict(now='2026-01-01T11:00:00Z', observation_started_at='2026-01-01T10:59:00Z', issues=[issue],
                  coverage=dict(issues_complete=True, threads_complete=True, label='已核原任务范围'))
    result.update(changes)
    if 'threads' not in result:
        result['threads'] = [dict(id=value['thread'], status='running' if value['running'] else 'idle',
                                  observed_at=result['now'], updatedAt='2026-01-01T10:00:00Z')] if value['thread'] else []
    return result


class ReportTests(unittest.TestCase):
    def test_exact_hour_does_not_restart_or_mark_overdue(self):
        result = report.build(snapshot())
        self.assertTrue(result['routine_ready'])
        self.assertEqual((result['starts'], result['writes']), (0, 0))
        data = snapshot(now='2026-01-01T11:00:01Z')
        self.assertIn('progress_over_one_hour', report.build(data)['checks'][0]['reasons'])

    def test_recent_turn_reopens_review_of_completed_task(self):
        data = snapshot(row(zone='done', running=False), threads=[dict(id='thread-1', updatedAt='2026-01-01T10:05:00Z')])
        data['issues'][0]['statusType'] = 'completed'
        result = report.build(data)
        self.assertIn('new_thread_activity', result['checks'][0]['reasons'])
        self.assertIn('独立任务', result['report'])

    def test_pause_stays_future_without_cue_or_unknown_progress_scan(self):
        data = snapshot(row(zone='future', running=False, paused=True, progress_at=None),
                        now='2026-01-02T11:00:00Z')
        data['issues'][0]['statusType'] = 'unstarted'
        result = report.build(data)
        self.assertTrue(result['routine_ready'])
        self.assertIn('暂停，未到恢复条件不催', result['report'])

    def test_truncated_head_cannot_fall_back_to_stale_cached_fact(self):
        data = snapshot()
        data['issues'][0]['description'] = report.START + '\n{'
        data['baseline'] = {'TASK-1': dict(issue_updated_at=data['issues'][0]['updatedAt'], row=row())}
        result = report.build(data)
        self.assertFalse(result['routine_ready'])
        self.assertIn('missing_or_truncated_head', result['checks'][0]['reasons'])

    def test_changed_issue_requires_new_summary_not_previous_row(self):
        data = snapshot()
        data['issues'][0].pop('description')
        data['baseline'] = {'TASK-1': dict(issue_updated_at='2025-12-31T10:00:00Z', row=row())}
        self.assertFalse(report.build(data)['routine_ready'])

    def test_invisible_task_survives_as_explicit_gap(self):
        first = report.build(snapshot())
        data = snapshot(issues=[], baseline=first['baseline'])
        result = report.build(data)
        self.assertIn('独立任务', result['report'])
        self.assertIn('issue_missing_from_current_directory', result['checks'][0]['reasons'])

    def test_new_unmapped_thread_and_pagination_gap_remain(self):
        data = snapshot(threads=[dict(id='new-thread', updatedAt='2026-01-01T10:00:00Z'),
                                 dict(id='thread-1', status='running', observed_at='2026-01-01T11:00:00Z',
                                      updatedAt='2026-01-01T10:00:00Z')],
                        coverage=dict(issues_complete=False, threads_complete=False))
        result = report.build(data)
        self.assertFalse(result['routine_ready'])
        self.assertEqual(len(result['checks']), 3)

    def test_head_limit_and_owner_conflicts_fail(self):
        with self.assertRaisesRegex(ValueError, 'head_too_long'):
            report.encode(row(phase='a'*500))
        with self.assertRaisesRegex(ValueError, 'owner_conflict'):
            report.encode(row(zone='decision', running=False))

    def test_project_task_is_independent_and_keeps_original_source(self):
        task = dict(id='project-1/existing-task', title='独立演示稿', source_kind='project_task',
                    source_ref='https://example.com/project-1', updatedAt='source-version-1',
                    row=row(thread='ppt-thread', writer='ppt-thread'))
        data = snapshot(tasks=[task], threads=[
            dict(id=tid, status='running', observed_at='2026-01-01T11:00:00Z', updatedAt='2026-01-01T10:00:00Z')
            for tid in ('thread-1', 'ppt-thread')])
        result = report.build(data)
        self.assertTrue(result['routine_ready'])
        self.assertIn('独立演示稿', result['report'])
        self.assertIn('https://example.com/project-1', result['report'])
        self.assertEqual(result['sources'][task['id']]['source_kind'], 'project_task')
        self.assertEqual(result['baseline'][task['id']]['issue']['source_ref'], task['source_ref'])
        data.update(tasks=[], baseline=result['baseline'])
        self.assertIn('独立演示稿', report.build(data)['report'])

    def test_missing_project_source_blocks_routine_ready(self):
        data = snapshot(tasks=[dict(id='project-1/task', source_kind='project_task', row=row())])
        self.assertFalse(report.build(data)['routine_ready'])

    def test_id_only_directory_is_disclosed_without_faking_time(self):
        data = snapshot(threads=[dict(id='thread-1', metadata_available=False)])
        result = report.build(data)
        self.assertFalse(result['routine_ready'])
        self.assertIn('thread_metadata_unavailable', result['checks'][0]['reasons'])
        self.assertNotIn('thread_metadata_unavailable', result['report'])
        self.assertIn('证据或可见范围待核', result['report'])
        data['coverage']['unchanged_gap'] = True
        result = report.build(data)
        self.assertFalse(result['routine_ready'])
        self.assertIn('runtime_state_unverified', result['checks'][0]['reasons'])
        self.assertNotIn('🔧', result['report'])
        self.assertEqual(result['baseline']['TASK-1']['row']['observed_at'], '2026-01-01T10:00:00Z')
        data['now'] = '2026-01-01T11:00:01Z'
        self.assertFalse(report.build(data)['routine_ready'])

    def test_verified_terminal_without_head_or_executor_is_not_recover(self):
        data = snapshot(threads=[])
        data['issues'] = [dict(id='TASK-1', title='已取消初始化', statusType='canceled', updatedAt='v1',
                               terminal_verified=True, terminal_evidence='原取消回执')]
        result = report.build(data)
        self.assertTrue(result['routine_ready'])
        self.assertNotIn('已取消初始化', result['report'])
        self.assertEqual(len(result['closed']), 1)
        self.assertNotIn('row', result['baseline']['TASK-1'])
        data['issues'][0]['statusType'] = 'completed'
        self.assertTrue(report.build(data)['routine_ready'])

    def test_terminal_evidence_does_not_hide_new_business_activity(self):
        data = snapshot()
        data['issues'][0].update(statusType='completed', description='', terminal_verified=True,
                                 terminal_evidence='前轮验收', new_activity=True)
        result = report.build(data)
        self.assertFalse(result['routine_ready'])
        self.assertIn('独立任务', result['report'])
        self.assertEqual(result['closed'], [])

    def test_terminal_without_head_still_checks_previously_bound_new_turn(self):
        data = snapshot()
        data['issues'][0].update(statusType='completed', description='', terminal_verified=True,
                                 terminal_evidence='前轮验收')
        data['baseline'] = {'TASK-1': dict(issue_updated_at='old-version', row=row(zone='done', running=False))}
        data['threads'] = [dict(id='thread-1', updatedAt='2026-01-01T10:01:00Z')]
        result = report.build(data)
        self.assertFalse(result['routine_ready'])
        self.assertEqual(result['closed'], [])

    def test_terminal_cache_invalidates_on_source_version_change(self):
        data = snapshot(threads=[])
        data['issues'][0].update(statusType='completed', description='', terminal_verified=True,
                                 terminal_evidence='原验收')
        previous = report.build(data)['baseline']
        issue = dict(data['issues'][0]);issue.pop('terminal_verified');issue.pop('terminal_evidence')
        data.update(issues=[issue], baseline=previous)
        self.assertTrue(report.build(data)['routine_ready'])
        issue['updatedAt'] = 'new-version'
        self.assertFalse(report.build(data)['routine_ready'])

    def test_only_verified_historical_scope_is_excluded(self):
        data = snapshot(threads=[dict(id='old-thread', scope='historical_nonbusiness', scope_evidence='已核原目录'),
                                 dict(id='new-thread'), dict(id='unverified-old', scope='historical_nonbusiness'),
                                 dict(id='thread-1', status='running', observed_at='2026-01-01T11:00:00Z',
                                      updatedAt='2026-01-01T10:00:00Z')])
        result = report.build(data)
        self.assertEqual(set(result['excluded_threads']), {'old-thread'})
        self.assertEqual({x.get('thread') for x in result['checks']}, {'new-thread', 'unverified-old'})
        data['threads'][0]['new_activity'] = True
        self.assertIn('old-thread', {x.get('thread') for x in report.build(data)['checks']})

    def test_scope_exclusion_cannot_override_a_current_task_binding(self):
        data = snapshot(threads=[dict(id='thread-1', scope='historical_nonbusiness', scope_evidence='旧基线', metadata_available=False)])
        result = report.build(data)
        self.assertIn('scope_binding_conflict', result['checks'][0]['reasons'])
        self.assertFalse(result['routine_ready'])
        self.assertNotIn('thread-1', result['excluded_threads'])

    def test_terminal_cache_keeps_observation_for_later_thread_activity(self):
        data = snapshot(row(zone='done', running=False))
        data['issues'][0]['statusType'] = 'completed'
        cached = report.build(data)['baseline']
        data['issues'][0].pop('description')
        data['baseline'] = cached
        cached = report.build(data)['baseline']
        self.assertEqual(cached['TASK-1']['issue']['terminal_observed_at'], '2026-01-01T10:00:00Z')
        data.update(baseline=cached, threads=[dict(id='thread-1', updatedAt='2026-01-01T10:05:00Z')])
        self.assertFalse(report.build(data)['routine_ready'])

    def test_missing_terminal_task_still_discloses_directory_gap(self):
        data = snapshot(row(zone='done', running=False))
        data['issues'][0]['statusType'] = 'completed'
        cached = report.build(data)['baseline']
        result = report.build(snapshot(issues=[], baseline=cached))
        self.assertIn('issue_missing_from_current_directory', result['checks'][0]['reasons'])
        self.assertFalse(result['routine_ready'])

    def test_waiting_task_uses_original_entry_without_fake_thread(self):
        data = snapshot(row(zone='followup', owner='user', running=False, thread=None))
        data['issues'][0].update(statusType='unstarted', url='https://example.com/task-1')
        result = report.build(data)
        self.assertTrue(result['routine_ready'])
        self.assertIn('https://example.com/task-1', result['report'])
        self.assertIsNone(result['baseline']['TASK-1']['row']['thread'])

    def test_verified_done_without_thread_and_progress_time_needs_no_fake_identity(self):
        data = snapshot(row(zone='done', thread=None, progress_at=None, owner='user', running=False))
        data['issues'][0].update(statusType='completed')
        result = report.build(data)
        self.assertTrue(result['routine_ready'])
        self.assertEqual(result['checks'], [])
        self.assertEqual(len(result['closed']), 1)

    def test_progress_or_saved_running_flag_cannot_prove_current_running(self):
        for phase in ('有新的业务产物', '系统显示 In Progress', '之前已有线程回复'):
            with self.subTest(phase=phase):
                result = report.build(snapshot(row(phase=phase, evidence='真实历史产物'), threads=[]))
                self.assertFalse(result['routine_ready'])
                self.assertIn('runtime_state_unverified', result['checks'][0]['reasons'])
                self.assertIn('⏳等待当前线程状态回执', result['report'])
                self.assertNotIn('🔧', result['report'])
                self.assertEqual(len(report.ZONES), 5)

    def test_queued_or_turn_starting_cannot_reuse_older_business_evidence(self):
        for status in ('queued', 'pending', 'starting'):
            with self.subTest(status=status):
                result = report.build(snapshot(threads=[dict(id='thread-1', status=status,
                                                            observed_at='2026-01-01T11:00:00Z',
                                                            updatedAt='2026-01-01T10:00:00Z')]))
                self.assertFalse(result['routine_ready'])
                self.assertIn('runtime_state_conflict', result['checks'][0]['reasons'])
                self.assertNotIn('🔧', result['report'])

    def test_known_wait_remains_in_dot_zone_without_new_zone_or_restart(self):
        result = report.build(snapshot(row(phase='等待资源释放', running=False, evidence=None)))
        self.assertTrue(result['routine_ready'])
        section = result['report'].split(report.ZONES['dot'])[1].split(report.ZONES['recover'])[0]
        self.assertIn('【独立任务】', section)
        self.assertIn('⏳线程已停止运行', section)
        self.assertNotIn('🔧', result['report'])
        self.assertEqual((result['starts'], result['writes']), (0, 0))

    def test_only_current_independent_thread_state_allows_running(self):
        result = report.build(snapshot(row(phase='已完成页面修改')))
        self.assertTrue(result['routine_ready'])
        self.assertIn('🔧独立线程当前运行；最近进展：已完成页面修改', result['report'])
        self.assertIn('状态核对：2026-01-01T11:00:00Z', result['report'])

    def test_current_thread_state_is_never_restored_from_baseline(self):
        data = snapshot()
        first = report.build(data)
        self.assertTrue(first['routine_ready'])
        data['baseline'] = first['baseline']
        data['threads'] = []
        result = report.build(data)
        self.assertIn('runtime_state_unverified', result['checks'][0]['reasons'])
        self.assertNotIn('🔧', result['report'])

    def test_old_missing_or_future_status_observation_cannot_prove_running(self):
        for checked in (None, '2026-01-01T10:58:59Z', '2026-01-01T11:01:00Z'):
            with self.subTest(checked=checked):
                result = report.build(snapshot(threads=[dict(id='thread-1', status='running',
                    updatedAt='2026-01-01T10:00:00Z', observed_at=checked)]))
                self.assertFalse(result['routine_ready'])
                self.assertNotIn('🔧', result['report'])

    def test_current_stop_wins_over_latest_reply_and_saved_running(self):
        for status in ('idle', 'completed', 'failed', 'interrupted'):
            with self.subTest(status=status):
                result = report.build(snapshot(row(phase='刚交付可用产物', next='dot核对并交付验收'), threads=[
                    dict(id='thread-1', status=status, updatedAt='2026-01-01T11:00:00Z',
                         observed_at='2026-01-01T11:00:00Z')]))
                self.assertNotIn('🔧', result['report'])
                self.assertIn('⏳线程已停止运行', result['report'])
                self.assertIn('dot核对并交付验收', result['report'])
                self.assertEqual((result['starts'], result['writes']), (0, 0))

    def test_ambiguous_or_unloaded_status_and_recent_time_are_not_running(self):
        for status in ('active', 'notLoaded', None):
            with self.subTest(status=status):
                result = report.build(snapshot(threads=[dict(id='thread-1', status=status,
                    observed_at='2026-01-01T11:00:00Z', updatedAt='2026-01-01T11:00:00Z')]))
                self.assertNotIn('🔧', result['report'])
                self.assertIn('runtime_state_unverified', result['checks'][0]['reasons'])

    def test_no_independent_thread_does_not_inherit_old_binding_running(self):
        data = snapshot(row(thread=None, running=False))
        data['issues'][0]['url'] = 'https://example.com/original-task'
        data['baseline'] = {'TASK-1': dict(issue_updated_at=data['issues'][0]['updatedAt'], row=row())}
        data['threads'] = [dict(id='thread-1', status='running', observed_at=data['now'],
                                updatedAt='2026-01-01T10:00:00Z')]
        result = report.build(data)
        self.assertNotIn('🔧', result['report'])
        self.assertIn('等待回执或具体条件', result['report'])

    def test_current_running_reopens_terminal_even_without_new_update_timestamp(self):
        data = snapshot(row(zone='done', running=False), threads=[dict(id='thread-1', status='running',
            observed_at='2026-01-01T11:00:00Z', updatedAt='2026-01-01T10:00:00Z')])
        data['issues'][0]['statusType'] = 'completed'
        result = report.build(data)
        self.assertEqual(result['closed'], [])
        self.assertIn('runtime_state_conflict', result['checks'][0]['reasons'])

    def test_business_table_keeps_details_out_and_one_item_per_row(self):
        data = snapshot(row(phase='需要核对权限\n与入口', next='核对|恢复'), threads=[])
        data['issues'][0].update(title='TASK-1', business_title='服务恢复')
        result = report.build(data)
        self.assertIn('【服务恢复】', result['report'])
        self.assertNotIn('TASK-1', result['report'])
        self.assertNotIn('runtime_state_unverified', result['report'])
        self.assertIn('runtime_state_unverified', result['checks'][0]['reasons'])
        self.assertEqual(result['baseline']['TASK-1']['issue']['title'], 'TASK-1')
        lines = [line for line in result['report'].splitlines() if '【服务恢复】' in line]
        self.assertEqual(len(lines), 1)
        self.assertIn('核对\\|恢复', lines[0])
        self.assertEqual(result['report'].count('| 事项 |'), 5)

    def test_recovery_and_personal_followup_keep_responsibility_distinct(self):
        for zone, owner, icon in [('recover', 'dot', '🚨'), ('followup', 'user', '🟠'),
                                  ('decision', 'user', '🔵')]:
            with self.subTest(zone=zone):
                data = snapshot(row(zone=zone, owner=owner, running=False,
                                    phase='入口权限未满足', next='按已核路径解除限制'))
                result = report.build(data)
                section = result['report'].split(report.ZONES[zone])[1].split('\n\n【')[0]
                self.assertIn('【独立任务】', section)
                self.assertIn(icon + '入口权限未满足', section)


if __name__ == '__main__':
    unittest.main()
