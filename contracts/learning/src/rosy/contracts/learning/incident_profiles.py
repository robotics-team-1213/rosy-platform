"""JSON role binding for new single-primary evidence; grants no source or owner admission."""


def validate_primary_roles(case):
    if type(case) is not dict: raise ValueError('INVALID_PRIMARY_EVIDENCE')
    profiles, budget, attempts = case.get('profiles'), case.get('budget'), case.get('attempts')
    if (type(profiles) is not list or len(profiles) != 1 or type(profiles[0]) is not dict
            or profiles[0].get('role') != 'primary' or type(budget) is not dict
            or type(attempts) is not list or len(attempts) > 16):
        raise ValueError('INVALID_PRIMARY_EVIDENCE')
    maximum, limits = profiles[0].get('max_calls'), budget.get('role_limits')
    if (type(maximum) is not int or not 1 <= maximum <= 8
            or type(limits) not in (tuple, list) or len(limits) != 1
            or type(limits[0]) not in (tuple, list) or len(limits[0]) != 2
            or limits[0][0] != 'primary' or type(limits[0][1]) is not int or limits[0][1] != maximum
            or type(budget.get('max_calls')) is not int or not 0 <= budget['max_calls'] <= maximum):
        raise ValueError('INVALID_PRIMARY_ROLE_BUDGET')
    calls = 0
    for row in attempts:
        if (type(row) is not dict or type(row.get('kind')) is not str
                or row['kind'] not in {'model', 'observation'}
                or row.get('role') != ('primary' if row['kind'] == 'model' else None)):
            raise ValueError('UNBOUND_PRIMARY_ATTEMPT_ROLE')
        calls += row['kind'] == 'model'
    if calls > budget['max_calls']: raise ValueError('PRIMARY_ROLE_BUDGET_EXCEEDED')
