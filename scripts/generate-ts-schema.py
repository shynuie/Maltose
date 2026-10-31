import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
output='// Generated from packages/mup-protocol; regenerate with scripts/generate-ts-schema.py.\n'
for name in ['command','response','event','context','surface']:
    output+=f'export const {name}Schema = '+json.dumps(json.loads((root/f'packages/mup-protocol/{name}.schema.json').read_text()),separators=(',',':'))+';\n'
(root/'packages/sdk-typescript/src/schemas.ts').write_text(output)
