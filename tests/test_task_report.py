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


if __name__ == '__main__':
    unittest.main()
