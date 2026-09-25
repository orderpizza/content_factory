"""Execution-time text request capture and existing-ledger cost projections."""
from common.gemini import _vertex_response_schema


def generate_json(store, invocation_id, client, prompt, schema, *, temperature):
    store.record_model_request(invocation_id, prompt, schema, {
        'temperature': temperature,
        'max_output_tokens': getattr(client, 'max_output_tokens', None),
        'thinking_level': getattr(client, 'thinking_level', None),
        'response_mime_type': 'application/json',
        'provider_response_schema': _vertex_response_schema(schema),
    })
    response = None
    client.last_raw_response = None
    try:
        response = client.generate_json(prompt, schema, temperature=temperature)
        return response
    finally:
        store.record_model_response(invocation_id, getattr(client, 'last_raw_response', None), response)


def invocation_cost(connection, invocation_id):
    row = connection.execute('''SELECT i.model_invocation_id,i.phase,i.entity_type,i.entity_id,i.attempt_ordinal,
        i.model_id,i.input_tokens,i.output_tokens,i.outcome,
        r.max_input_tokens reserved_input_tokens,r.max_output_tokens output_token_cap,
        r.worst_case_micro_usd reservation_micro_usd,r.settled_micro_usd actual_micro_usd,
        r.price_snapshot_hash pricing_policy_fingerprint,r.status accounting_status
        FROM model_invocations i LEFT JOIN gemini_budget_reservations r USING(model_invocation_id)
        WHERE i.model_invocation_id=?''', (invocation_id,)).fetchone()
    value = dict(row)
    value['actual_minus_reservation_micro_usd'] = (
        None if value['actual_micro_usd'] is None or value['reservation_micro_usd'] is None
        else value['actual_micro_usd'] - value['reservation_micro_usd'])
    value['reservation_semantics'] = 'admission estimate, not a price ceiling'
    return value


def aggregate_cost(values):
    def total(key):
        return None if any(v[key] is None for v in values) else sum(v[key] for v in values)
    return {key: total(key) for key in ('reservation_micro_usd', 'actual_micro_usd',
                                      'actual_minus_reservation_micro_usd')}


def job_cost(connection, job_id):
    ids = [r[0] for r in connection.execute('SELECT model_invocation_id FROM gemini_budget_reservations WHERE content_job_id=?', (job_id,))]
    values = [invocation_cost(connection, i) for i in ids]
    return {'invocations': values, **aggregate_cost(values)}
