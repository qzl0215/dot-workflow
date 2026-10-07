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
    issue = dict(id='TASK-1', title='独立任务', statusType='started', updatedAt='2026-01-01T10:00:00Z',
                 description=report.encode(value or row()))
    result = dict(now='2026-01-01T11:00:00Z', issues=[issue], threads=[],
                  coverage=dict(issues_complete=True, threads_complete=True, label='已核原任务范围'))
    result.update(changes)
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
        data = snapshot(threads=[dict(id='new-thread', updatedAt='2026-01-01T10:00:00Z')],
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
        data = snapshot(tasks=[task])
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
        self.assertIn('thread_metadata_unavailable', result['report'])
        data['coverage']['unchanged_gap'] = True
        result = report.build(data)
        self.assertTrue(result['routine_ready'])
        self.assertEqual(result['baseline']['TASK-1']['row']['observed_at'], '2026-01-01T10:00:00Z')
        data['now'] = '2026-01-01T11:00:01Z'
        self.assertFalse(report.build(data)['routine_ready'])

    def test_verified_terminal_without_head_or_executor_is_not_recover(self):
        data = snapshot()
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
        data = snapshot()
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
                                 dict(id='new-thread'), dict(id='unverified-old', scope='historical_nonbusiness')])
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


if __name__ == '__main__':
    unittest.main()
