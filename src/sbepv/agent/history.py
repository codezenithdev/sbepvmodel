"""Read-only history discovery contracts; TEA evidence stays bound to the visible job."""
SEARCH_TOOL = {
    'type': 'function', 'name': 'find_analysis_records', 'strict': True,
    'description': 'Search shared analysis history metadata by literal name, stable job ID or date substring, not natural-language questions. For previous/oldest/chronological questions use query="", inspect returned timestamps, and paginate with next_offset; never put phrases like "the previous run" in query. This does not select, modify or run anything. Do not guess the newest run. TEA evidence still requires selecting that TEA analysis in the dashboard.',
    'parameters': {'type': 'object', 'properties': {
        'query': {'type': 'string'},
        'workflow': {'type': 'string', 'enum': ['all', 'validation', 'annual', 'technoeconomic']},
        'offset': {'type': 'integer', 'minimum': 0},
    }, 'required': ['query', 'workflow', 'offset'], 'additionalProperties': False},
}

MODEL_EVIDENCE_TOOL = {
    'type': 'function', 'name': 'get_model_run_evidence', 'strict': True,
    'description': 'Read stored Calibration or Annual evidence by an exact job ID from the user or history index. Does not run or change selection. Never use for TEA or retired workflows; select TEA in the dashboard for verified TEA evidence.',
    'parameters': {'type': 'object', 'properties': {'job_id': {'type': 'string'}},
                   'required': ['job_id'], 'additionalProperties': False},
}

TOOL_NAMES = frozenset({SEARCH_TOOL['name'], MODEL_EVIDENCE_TOOL['name']})
