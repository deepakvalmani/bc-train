"""Keep engine fuel enforcement separate from optional efficiency policy.

The handbook explicitly permits suspend/resume on fuel exhaustion. A relative
audit therefore compares efficiency to a pinned accepted baseline, rather than
claiming every legal suspension is a competition violation.
"""


def judge(cases, reference=None):
    def indexed(rows):
        result={}
        for row in rows:
            key=(row['map'],row['side'])
            if key in result: raise ValueError('Duplicate fuel audit case')
            result[key]=row
        return result
    current=indexed(cases)
    prior=indexed(reference) if reference is not None else None
    if not current or (prior is not None and set(current)!=set(prior)):
        raise ValueError('Incomplete or incompatible fuel audit comparison')
    comparisons=[]
    for key,row in current.items():
        d=row.get('diagnostics',{})
        numeric=all(type(d.get(name)) is int and d[name]>=0
                    for name in ('turns','audit_ends','malformed','fuel_failures'))
        valid=(numeric and d.get('turns',0)>0 and d.get('audit_ends')==d.get('turns')
               and d.get('malformed',1)==0 and not d.get('missing_or_oversized_log')
               and not d.get('log_truncated')
               and row.get('faults',0)==0 and numeric)
        rate=d['fuel_failures']/max(1,d['turns']) if numeric else None
        baseline_rate=None
        if prior is not None:
            previous=prior[key]
            # A bad reference must never become permission for a candidate.
            previous_valid=judge([previous])[0]
            old=previous['diagnostics']
            if previous_valid:
                baseline_rate=old['fuel_failures']/max(1,old['turns'])
            valid=valid and previous_valid and rate<=baseline_rate+1e-12
        comparisons.append(dict(map=key[0],side=key[1],passed=bool(valid),
            fuel_flags_per_turn=rate,baseline_fuel_flags_per_turn=baseline_rate,
            fuel_flags=d.get('fuel_failures'),turns=d.get('turns')))
    return all(row['passed'] for row in comparisons),comparisons
