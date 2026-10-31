import { expect, test } from 'vitest';
import { protocol } from '../../packages/sdk-typescript/src';
test('uses explicit v0.3', () => expect(protocol).toBe('mup/0.3'));
