import {test,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {validate} from '../../packages/sdk-typescript/src';
const fixtures=(name:string)=>JSON.parse(readFileSync(new URL('../../packages/mup-protocol/fixtures/'+name+'.json',import.meta.url),'utf8'));
test('TypeScript SDK conforms to the full golden corpus',()=>{for(const value of fixtures('valid'))expect(()=>validate(value)).not.toThrow();for(const value of fixtures('invalid'))expect(()=>validate(value)).toThrow();});
