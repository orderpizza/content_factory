"""Read-only one-destination report. Internal estimates are never invoice totals."""
from collections import Counter, defaultdict
import json

from common.timestamps import serialize_timestamp, utc_now
from .measurement import INSIGHTS, destination, latest_observations, publication


MODEL_ENTITIES = {
    'generation_run': ('generation_runs', 'generation_run_id'),
    'adaptation_run': ('adaptation_runs', 'adaptation_run_id'),
    'render_run': ('render_runs', 'render_run_id'),
}


def _job(store, invocation):
    entity = MODEL_ENTITIES.get(invocation['entity_type'])
    if entity is None:
        return None
    table, key = entity
    row = store.connection.execute(f'SELECT * FROM {table} WHERE {key}=?', (invocation['entity_id'],)).fetchone()
    return store._model_job_id(table, row) if row else None


def _destinations(store, job_id, invocation):
    # Output-specific work can be attributed even when its canonical job is shared.
    if invocation and invocation['entity_type'] in {'adaptation_run', 'render_run'}:
        if invocation['entity_type'] == 'adaptation_run':
            query = ('SELECT b.social_destination_id FROM adaptation_runs a JOIN output_requests o USING(output_request_id) '
                     'JOIN output_bindings b USING(output_binding_id) WHERE adaptation_run_id=?')
        else:
            query = ('SELECT b.social_destination_id FROM render_runs r JOIN content_packages k USING(content_package_id) '
                     'JOIN output_requests o USING(output_request_id) JOIN output_bindings b USING(output_binding_id) WHERE render_run_id=?')
        return {r[0] for r in store.connection.execute(query, (invocation['entity_id'],))}
    if job_id is None:
        return set()
    row = store.connection.execute('SELECT output_plan_json FROM content_jobs WHERE content_job_id=?', (job_id,)).fetchone()
    if row is None:
        return set()
    result = {r[0] for r in store.connection.execute(
        'SELECT b.social_destination_id FROM canonical_contents c JOIN output_requests o USING(canonical_content_id) '
        'LEFT JOIN output_bindings b USING(output_binding_id) WHERE c.content_job_id=?', (job_id,))}
    for output in json.loads(row[0]):
        bound = store.connection.execute('SELECT social_destination_id FROM output_bindings WHERE output_binding_id=?',
                                         (output.get('output_binding_id'),)).fetchone()
        result.add(bound[0] if bound else None)
    return result


def _aggregate(rows):
    amounts = [r['internal_cost_micro_usd'] for r in rows if r['internal_cost_micro_usd'] is not None]
    holds = [r['reservation_estimate_micro_usd'] for r in rows if r['status'] in {'reserved', 'uncertain'}]
    incomplete = sum(r['incomplete'] for r in rows)
    return {'entries': len(rows), 'known_internal_micro_usd': sum(amounts) if amounts else None,
            'outstanding_reservation_estimate_micro_usd': sum(holds) if holds else None,
            'incomplete_entries': incomplete, 'recorded_entries_complete': bool(rows) and not incomplete,
            'invoice_cost_micro_usd': None,
            'statuses': dict(Counter(r['status'] for r in rows))}


def cost_report(store, destination_id, start, end, posts):
    invocations = {r['model_invocation_id']: dict(r) for r in store.connection.execute('SELECT * FROM model_invocations')}
    reservations = [dict(r) for r in store.connection.execute('SELECT * FROM gemini_budget_reservations')]
    linked = {r['model_invocation_id'] for r in reservations}
    entries = [(r, invocations.get(r['model_invocation_id'])) for r in reservations]
    entries.extend((None, i) for key, i in invocations.items() if key not in linked)
    rows, unallocated = [], []
    for reservation, invocation in entries:
        occurred = reservation['created_at'] if reservation else invocation['started_at']
        if not start <= occurred < end:
            continue
        inferred_job = _job(store, invocation) if invocation else None
        job_id = reservation['content_job_id'] if reservation and reservation['content_job_id'] else inferred_job
        conflict = inferred_job is not None and job_id != inferred_job
        destinations = _destinations(store, job_id, invocation)
        if conflict:
            destinations = set()
        if destinations and destination_id not in destinations and None not in destinations:
            continue
        usage = bool(invocation and invocation['input_tokens'] is not None and invocation['output_tokens'] is not None)
        amount, incomplete = None, True
        if reservation:
            status = reservation['status']
            if status == 'settled':
                amount = reservation['settled_micro_usd']
                incomplete = amount is None or not usage
            elif status == 'released':
                amount = reservation['settled_micro_usd']
                incomplete = amount != 0
        elif invocation['outcome'] == 'blocked':
            status, amount, incomplete = 'blocked_before_call', 0, False
        elif usage:
            status = 'usage_estimate_without_ledger'
            # The legacy column defaults to zero even when pricing is absent.
            # Only a positive diagnostic estimate proves an amount was recorded;
            # an explicit zero settlement requires the accounting ledger.
            amount = invocation['estimated_cost_micro_usd'] or None
        else:
            status = 'missing_cost_ledger'
        matching = [p['post_record_id'] for p in posts if job_id is not None and p['content_job_id'] == job_id]
        attributed = destinations == {destination_id} and not conflict
        row = {
            'reservation_id': reservation['gemini_budget_reservation_id'] if reservation else None,
            'invocation_id': invocation['model_invocation_id'] if invocation else None,
            'content_job_id': job_id, 'stage': (reservation and reservation['phase']) or (invocation and invocation['phase']) or 'unknown',
            'occurred_at': occurred, 'status': status,
            'provenance': 'internal_usage_priced_estimate' if usage else 'internal_ledger_unverified',
            'usage_observed': usage, 'internal_cost_micro_usd': amount,
            'reservation_estimate_micro_usd': reservation['worst_case_micro_usd'] if reservation else None,
            'incomplete': incomplete or conflict, 'settled_at': reservation['settled_at'] if reservation else None,
            'post_record_id': matching[0] if attributed and len(matching) == 1 else None,
            'attribution': ('post' if len(matching) == 1 else 'destination_job_shared_or_unpublished') if attributed
                           else 'conflicting_job' if conflict else 'shared_or_unattributed',
        }
        (rows if attributed else unallocated).append(row)
    groups = defaultdict(list)
    for row in rows:
        groups[(row['stage'], row['post_record_id'])].append(row)
    missing_stages = [
        {'post_record_id': p['post_record_id'], 'stage': stage,
         'status': ('recorded' if any(r['post_record_id'] == p['post_record_id'] and r['stage'] == stage for r in rows)
                    else 'not_collected_or_not_attributable')}
        for p in posts for stage in ('generation', 'adaptation', 'image_rendering')]
    total = _aggregate(rows)
    total['ledger_complete'] = (total['recorded_entries_complete'] and not unallocated
                                and all(r['status'] == 'recorded' for r in missing_stages))
    return {'period_basis': 'reservation creation / unreserved invocation start; current settlement at report generation',
            'interpretation': 'Internal usage-priced estimates, not invoices. Reservations are holds, not additional spend. '
                              'Missing pre-job attribution is listed separately and excluded from destination totals.',
            'destination': total, 'entries': rows,
            'by_stage_and_post': [{'stage': stage, 'post_record_id': post, **_aggregate(items)}
                                  for (stage, post), items in groups.items()],
            'shared_or_unattributed_excluded': unallocated,
            'posts_without_cost_entries': [p['post_record_id'] for p in posts
                                          if not any(r['post_record_id'] == p['post_record_id'] for r in rows)],
            'post_stage_coverage': missing_stages,
            'manual_cost_coverage': 'see optional observation windows; absent means not_collected'}


def operator_report(store, destination_id: int, start: str, end: str, *, as_of: str | None = None):
    start, end = serialize_timestamp(start), serialize_timestamp(end)
    if start >= end:
        raise ValueError('report requires a nonempty UTC half-open period')
    as_of = serialize_timestamp(as_of or utc_now())
    # One read transaction makes funnel, metrics and mutable cost settlement coherent.
    store.connection.execute('BEGIN')
    try:
        dest = destination(store, destination_id)
        review_rows = store.connection.execute(
            'SELECT r.*,q.post_request_id,q.created_at AS authorized_at,p.post_record_id,k.package_json '
            'FROM review_requests r JOIN content_packages k USING(content_package_id) '
            'JOIN output_requests o USING(output_request_id) JOIN output_bindings b USING(output_binding_id) '
            'LEFT JOIN post_requests q ON q.review_request_id=r.review_request_id '
            'LEFT JOIN post_records p USING(post_request_id) WHERE b.social_destination_id=?', (destination_id,)).fetchall()
        reviews = [r for r in review_rows if r['delivery_revision_id'] is not None
                   or r['post_request_id'] is not None
                   or json.loads(r['package_json']).get('execution_mode') == 'simulation']
        all_posts = [publication(store, r['post_record_id']) for r in reviews if r['post_record_id'] is not None]
        cohort = [r for r in reviews if start <= r['created_at'] < end]
        cohort_ids = {r['post_record_id'] for r in cohort if r['post_record_id'] is not None}
        cohort_posts = [p for p in all_posts if p['post_record_id'] in cohort_ids]
        observations = latest_observations(store, destination_id, start, end, as_of=as_of)
        insights = [r for r in observations if r['definition_version'] != 'manual_operations_v1']
        manual = [r for r in observations if r['definition_version'] == 'manual_operations_v1']
        # Explicit coverage for every applicable metric and subject. Windows with
        # no row are not guessed from a late or overlapping snapshot.
        subjects = [('account', None), *[('post', p['post_record_id']) for p in all_posts]]
        coverage = []
        for scope, post in subjects:
            for metric, definition in INSIGHTS.items():
                if scope not in definition.scopes:
                    continue
                matching = [r for r in insights if r['metric'] == metric and r['scope'] == scope and r['post_record_id'] == post]
                coverage.append({'scope': scope, 'post_record_id': post, 'metric': metric,
                                 'eligible_observations': len(matching),
                                 'authenticated_status': 'not_collected',
                                 'fixture_or_estimate_statuses': dict(Counter(r['value_status'] for r in matching)) or {'not_collected': 1}})
        reviewed = sum(r['decided_at'] is not None for r in cohort)
        approved_ids = {r[0] for r in store.connection.execute(
            "SELECT result_record_id FROM human_command_receipts WHERE command_kind='approve_jpeg'")}
        approved = sum(r['status'] == 'approved' or r['post_request_id'] is not None
                       or r['review_request_id'] in approved_ids for r in cohort)
        return {
            'report_version': 'offline_measurement_report_v1', 'generated_at': utc_now(),
            'destination': dest, 'period': {'start': start, 'end_exclusive': end},
            'metric_fetched_cutoff': as_of, 'real_account_performance_available': False,
            'notice': 'SYNTHETIC / MANUAL / UNKNOWN evidence only. No authenticated Instagram insights, revenue or profitability claim.',
            'funnel': {
                'basis': 'delivery reviews (including legacy authorized reviews) created in period, current outcomes; counts are not conversion rates',
                'awaiting_or_decided_reviews': len(cohort), 'reviewed': reviewed, 'approved': approved,
                'post_now': len(cohort_posts),
                'published_by_evidence': dict(Counter(p['classification'] for p in cohort_posts if p['status'] == 'published')),
                'delivery_states': dict(Counter(p['status'] for p in cohort_posts)),
                'authenticated_published': 0,
                'review_evidence': [{'review_request_id': r['review_request_id'], 'status': r['status'],
                                     'actor_id': r['actor_id'], 'created_at': r['created_at'], 'decided_at': r['decided_at'],
                                     'review_kind': ('jpeg_revision' if r['delivery_revision_id'] is not None else
                                                     'synthetic' if json.loads(r['package_json']).get('execution_mode') == 'simulation'
                                                     else 'legacy_authorized'),
                                     'authorized_at': r['authorized_at']} for r in cohort]},
            'publication_evidence': [{k: p[k] for k in (
                'post_record_id', 'review_request_id', 'publication_identity', 'status', 'classification',
                'published_at', 'external_post_id', 'authenticated', 'receipt_resource_ids', 'human_decision_ids')}
                for p in all_posts],
            'insights': insights, 'coverage': coverage, 'manual_operations': manual,
            'manual_coverage': [
                {'scope': scope, 'post_record_id': post, 'metric': metric,
                 'status': 'recorded' if any(r['scope'] == scope and r['post_record_id'] == post and r['metric'] == metric
                                           for r in manual) else 'not_collected'}
                for scope, post in subjects for metric in ('operator_minutes', 'storage_cost', 'delivery_cost')],
            'costs': cost_report(store, destination_id, start, end, all_posts),
            'kpis': {'engagement_rate': None, 'cost_per_authenticated_published_micro_usd': None,
                     'revenue_micro_usd': None, 'profit_micro_usd': None,
                     'reason': 'No authenticated publication/engagement denominators or complete external cost/revenue settlement.'},
        }
    finally:
        store.connection.rollback()
