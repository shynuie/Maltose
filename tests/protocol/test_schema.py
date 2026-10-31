import json
from pathlib import Path
import sys
import pytest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'packages/sdk-python'))
from maltose import validate
@pytest.mark.parametrize('case',json.loads((ROOT/'packages/mup-protocol/fixtures/valid.json').read_text()))
def test_valid(case): validate(case)
@pytest.mark.parametrize('case',json.loads((ROOT/'packages/mup-protocol/fixtures/invalid.json').read_text()))
def test_invalid(case):
    with pytest.raises(Exception): validate(case)
def test_copies_and_vocabulary():
    allowed = {'$schema','$id','$defs','$ref','type','properties','required','additionalProperties','allOf','anyOf','oneOf','not','if','then','const','enum','items','minItems','maxItems','minLength','maxLength','minimum','maximum','pattern','format'}
    def walk(s):
        assert set(s) <= allowed
        for k,v in s.items():
            if k in ('$defs','properties'):
                for child in v.values(): walk(child)
            elif k in ('allOf','anyOf','oneOf'):
                for child in v: walk(child)
            elif k in ('items','if','then','not'): walk(v)
    for path in (ROOT/'packages/mup-protocol').glob('*.schema.json'):
        walk(json.loads(path.read_text()))
        assert path.read_bytes() == (ROOT/'native/Protocol/Schemas'/path.name).read_bytes()
        assert path.read_bytes() == (ROOT/'packages/sdk-python/maltose/schemas'/path.name).read_bytes()
def test_typescript_schema_mirror():
    lines=(ROOT/'packages/sdk-typescript/src/schemas.ts').read_text().splitlines()[1:]
    for line in lines:
        name,raw=line.removeprefix('export const ').split('Schema = ',1)
        assert json.loads(raw.rstrip(';')) == json.loads((ROOT/f'packages/mup-protocol/{name}.schema.json').read_text())
