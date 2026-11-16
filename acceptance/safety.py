"""Acceptance-only admission at the workers' persisted pre-provider boundary.

No production composition uses this store. One RunGuard spans the serialized
matrix, including separate attempt databases. A trace admission is conservatively
counted even if the process dies before the transport actually sends it.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
from threading import Lock

from common.timestamps import utc_now
from workflow.model_budget import ModelBudgetExceeded
from workflow.model_trace import invocation_cost
from workflow.store import WorkflowStore


@dataclass
class RunGuard:
    max_calls: int
    max_image_calls: int
    max_text_calls: int
    max_micro_usd: int
    calls: int = 0
    images: int = 0
    accounted_micro_usd: int = 0
    stopped: bool = False
    lock: Lock = field(default_factory=Lock, repr=False)

    def attempt(self, case, cost_limit):
        return AttemptGuard(self, dict(case.live_budget['calls_by_stage']), cost_limit)


@dataclass
class AttemptGuard:
    run: RunGuard
    limits: dict[str, int]
    max_micro_usd: int
    counts: Counter = field(default_factory=Counter)
    blocked: str | None = None

    def refusal(self, phase, accounted):
        if self.blocked:
            return self.blocked
        if self.run.stopped:
            return 'acceptance accounting is unresolved'
        if self.counts[phase] >= self.limits.get(phase, 0):
            return 'acceptance case provider-attempt cap reached'
        image = phase == 'image_rendering'
        if (self.run.calls >= self.run.max_calls
            or image and self.run.images >= self.run.max_image_calls
            or not image and self.run.calls - self.run.images >= self.run.max_text_calls):
            return 'acceptance run provider-attempt cap reached'
        if accounted > self.max_micro_usd or self.run.accounted_micro_usd + accounted > self.run.max_micro_usd:
            return 'acceptance estimated cost budget exhausted'
        return None


class AcceptanceStore(WorkflowStore):
    def __init__(self, *args, attempt_guard: AttemptGuard, **kwargs):
        super().__init__(*args, **kwargs)
        self.attempt_guard = attempt_guard

    def record_model_request(self, invocation_id, prompt, schema, configuration):
        # Every text, metadata-repair and image attempt reaches this seam after
        # production reservation and before generate_json/generate_image. Frozen
        # fixture setup uses an ordinary WorkflowStore and never reaches it.
        guard = self.attempt_guard
        with guard.run.lock:
            row = self.connection.execute(
                'SELECT phase FROM model_invocations WHERE model_invocation_id=? AND outcome=\'started\'',
                (invocation_id,)).fetchone()
            if row is None:
                raise RuntimeError('acceptance request requires a started invocation')
            accounted = self.connection.execute(
                "SELECT COALESCE(SUM(CASE WHEN status IN ('settled','released') "
                "THEN settled_micro_usd ELSE worst_case_micro_usd END),0) FROM gemini_budget_reservations"
            ).fetchone()[0]
            reason = guard.refusal(row['phase'], accounted)
            super().record_model_request(invocation_id, prompt, schema, {
                **configuration, 'acceptance': {'provider_attempt_admitted': reason is None},
            })
            if reason:
                guard.blocked = reason
                with self.transaction():
                    self.connection.execute(
                        "UPDATE model_invocations SET outcome='blocked',safe_error=?,completed_at=? "
                        "WHERE model_invocation_id=? AND outcome='started'", (reason, utc_now(), invocation_id))
                    self.connection.execute(
                        "UPDATE gemini_budget_reservations SET status='released',settled_micro_usd=0,settled_at=? "
                        "WHERE model_invocation_id=? AND status='reserved'", (utc_now(), invocation_id))
                raise ModelBudgetExceeded(reason)
            guard.counts[row['phase']] += 1
            guard.run.calls += 1
            guard.run.images += row['phase'] == 'image_rendering'

    def finish_model_invocation(self, invocation_id, **kwargs):
        # Text workers catch pre-dispatch refusal within their provider boundary.
        # Preserve our audited zero-dispatch block instead of finalizing twice or
        # converting it to an uncertain provider error.
        row = self.connection.execute(
            'SELECT outcome,trace_json FROM model_invocations WHERE model_invocation_id=?',
            (invocation_id,)).fetchone()
        if row and row['outcome'] == 'blocked' and row['trace_json']:
            admission = json.loads(row['trace_json']).get('generation_configuration', {}).get('acceptance', {})
            if admission.get('provider_attempt_admitted') is False:
                return
        return super().finish_model_invocation(invocation_id, **kwargs)


def read_accounting(database: Path) -> dict:
    """Read evidence even when execution never returned. Missing is not free."""
    result = dict(schema_version=1, count_basis='pre_dispatch_admissions_may_overcount_sends',
                  cost_basis='priced_usage_and_reservation_holds_not_invoice',
                  calls=None, image_calls=None, text_calls=None,
                  settled_micro_usd=None, active_reservation_micro_usd=None,
                  uncertain_micro_usd=None, accounted_micro_usd=None,
                  accounting_incomplete=True, unresolved=True, invocations=[],
                  diagnostic='ledger_unavailable')
    try:
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as connection:
            connection.row_factory = sqlite3.Row
            ids = connection.execute(
                "SELECT model_invocation_id FROM model_invocations "
                "WHERE model_id != 'acceptance-frozen-stage-fixture' ORDER BY model_invocation_id").fetchall()
            values = [invocation_cost(connection, row[0]) for row in ids]
            traces = {r['model_invocation_id']: r for r in connection.execute(
                "SELECT model_invocation_id,trace_json FROM model_invocations WHERE model_id != 'acceptance-frozen-stage-fixture'")}
            # Query the ledger even for an empty invocation table, detecting a
            # partial schema and reservations whose invocation evidence is lost.
            orphan = connection.execute(
                'SELECT COUNT(*) FROM gemini_budget_reservations r LEFT JOIN model_invocations i '
                'USING(model_invocation_id) WHERE i.model_invocation_id IS NULL').fetchone()[0]
            incomplete = bool(orphan)
            attempted = []
            for value in values:
                trace = json.loads(traces[value['model_invocation_id']]['trace_json'] or '{}')
                admitted = trace.get('generation_configuration', {}).get('acceptance', {}).get('provider_attempt_admitted')
                value['provider_attempt_admitted'] = admitted
                if value['outcome'] != 'blocked':
                    attempted.append(value)
                    if (admitted is not True or value['accounting_status'] is None
                        or value['reservation_micro_usd'] is None
                        or (value['accounting_status'] in {'settled', 'released'}
                            and value['actual_micro_usd'] is None)):
                        incomplete = True
            settled = sum(v['actual_micro_usd'] or 0 for v in values)
            active = sum(v['active_reservation_micro_usd'] or 0 for v in values)
            uncertain = sum(v['uncertain_micro_usd'] or 0 for v in values)
            unresolved = incomplete or any(v['outcome'] == 'started' or v['accounting_status'] not in {'settled', 'released'}
                                           or v['actual_micro_usd'] is None
                                           or (v['accounting_status'] != 'released' and
                                               (v['input_tokens'] is None or v['output_tokens'] is None))
                                           for v in attempted)
            result.update(calls=None if incomplete else len(attempted),
                          image_calls=None if incomplete else sum(v['phase'] == 'image_rendering' for v in attempted),
                          text_calls=None if incomplete else sum(v['phase'] != 'image_rendering' for v in attempted),
                          settled_micro_usd=None if incomplete else settled,
                          active_reservation_micro_usd=None if incomplete else active,
                          uncertain_micro_usd=None if incomplete else uncertain,
                          accounted_micro_usd=None if incomplete else settled + active + uncertain,
                          accounting_incomplete=incomplete, unresolved=unresolved,
                          invocations=values, diagnostic='partial_ledger' if incomplete else None)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        pass  # Do not export exception bodies, connection strings or raw responses.
    return result


def total_known(values):
    values = list(values)
    return None if any(v is None for v in values) else sum(values)
