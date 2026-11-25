"""Validated optional experiment controls; schema is shared with React."""
import json
import math
from pathlib import Path

SCHEMA = json.loads((Path(__file__).parent/'src/experiment_options.json').read_text())


def validate_options(body):
    result = {}
    for section in SCHEMA:
        for field in section['fields']:
            key, kind = field['key'], field['type']
            value = body.get(key, field['default'])
            if value is None or value == '':
                value = [] if field.get('blank_means_empty') else field['default']
            if value is None:
                result[key] = None
                continue
            label = field['label']

            def numeric(item):
                if isinstance(item, bool):
                    raise ValueError(f'{label}: enter a number')
                try:
                    number = float(item)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f'{label}: enter a number') from exc
                if not math.isfinite(number) or not field['min'] <= number <= field['max']:
                    raise ValueError(f'{label}: must be between {field["min"]} and {field["max"]}')
                if kind.startswith('integer'):
                    if not number.is_integer():
                        raise ValueError(f'{label}: use whole numbers')
                    return int(number)
                return number

            if kind in ('integer','number','percent'):
                number = numeric(value)
                # Explicit units avoid interpreting 0.5% as a fraction of 50%.
                result[key] = f'{number:g}%' if kind == 'percent' else number
            elif kind.endswith('-list'):
                items = [s.strip() for s in value.split(',')] if isinstance(value, str) else value
                if not isinstance(items, list) or (not items and not field.get('blank_means_empty')):
                    raise ValueError(f'{label}: provide a comma-separated list')
                if kind == 'text-list':
                    if any(not isinstance(x,str) or not x.strip() for x in items):
                        raise ValueError(f'{label}: column names must not be empty')
                    converted = [x.strip() for x in items]
                else:
                    converted = [numeric(x) for x in items]
                if len(set(converted)) != len(converted):
                    raise ValueError(f'{label}: duplicate entries are not allowed')
                result[key] = ([f'{x:g}%' for x in converted] if kind == 'percent-list' else converted)
            elif kind == 'boolean':
                if type(value) is not bool:
                    raise ValueError(f'{label}: use true or false')
                result[key] = value
            elif kind == 'choice':
                if value not in [c[0] for c in field['choices']]:
                    raise ValueError(f'{label}: choose a listed option')
                result[key] = value
            elif kind == 'multi':
                choices = [c[0] for c in field['choices']]
                if (not isinstance(value,list) or not value or
                        any(x not in choices for x in value) or len(set(value)) != len(value)):
                    raise ValueError(f'{label}: select at least one distinct listed option')
                result[key] = value
    labels = [round(float(x.rstrip('%'))) for x in result['missingness_thresholds']]
    if len(set(labels)) != len(labels):
        raise ValueError('Missingness cutoffs must have distinct whole-percent labels')
    if 5 not in result['neighbor_k']:
        raise ValueError('Neighbour counts must include 5 for the final TOPSIS criterion')
    if result['distance_samples'] <= max(result['neighbor_k']):
        raise ValueError('Maximum patients for distance evaluation must exceed every neighbour count')
    return result
