"""Validate references without trusting model-supplied IDs or adding citations ourselves."""
import re


def citations_valid(generated, sources):
    if not isinstance(generated, dict) or not isinstance(generated.get('answer'), str):
        return False
    ids = generated.get('source_ids')
    if not isinstance(ids, list) or not ids:
        return False
    valid = {p['source_id'] for p in sources}
    if not all(isinstance(i, str) and i in valid for i in ids):
        return False
    inline = re.findall(r'\[([^\[\]]+)\]', generated['answer'])
    return bool(generated['answer'].strip()) and set(inline) == set(ids)
