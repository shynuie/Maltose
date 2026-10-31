import { expect, test } from 'vitest';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import { readFileSync } from 'node:fs';
const load = (p:string) => JSON.parse(readFileSync(new URL('../../packages/mup-protocol/'+p,import.meta.url),'utf8'));
const ajv = new Ajv2020({strict:false}); addFormats(ajv);
const validate = ajv.compile(load('command.schema.json'));
for(const [i, fixture] of load('fixtures/valid.json').entries()) test(`accept golden ${i}`,()=>expect(validate(fixture)).toBe(true));
for(const [i, fixture] of load('fixtures/invalid.json').entries()) test(`reject golden ${i}`,()=>expect(validate(fixture)).toBe(false));
