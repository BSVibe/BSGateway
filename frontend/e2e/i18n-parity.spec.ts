/**
 * Message-catalog parity test.
 *
 * The BSGateway frontend has no standalone unit-test runner (only the
 * Playwright e2e suite), so the `gateway.en.json` / `gateway.ko.json`
 * parity assertion lives here as a plain Playwright spec. It does NOT open
 * a browser — it just imports both JSON catalogs and asserts:
 *
 *   1. Both files expose the identical key tree (no missing / extra keys).
 *   2. Every leaf value is a non-empty string.
 *
 * This guards against the classic i18n drift bug where a new key is added
 * to one locale but forgotten in the other.
 */
import { test, expect } from '@playwright/test';
import en from '../messages/gateway.en.json' with { type: 'json' };
import ko from '../messages/gateway.ko.json' with { type: 'json' };

type Json = { [key: string]: Json | string };

/** Collect every dotted leaf path in a nested message object, sorted. */
function leafPaths(obj: Json, prefix = ''): string[] {
  const paths: string[] = [];
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'string') {
      paths.push(path);
    } else {
      paths.push(...leafPaths(value, path));
    }
  }
  return paths.sort();
}

/** Resolve a dotted path to its leaf value. */
function leafValue(obj: Json, path: string): unknown {
  return path
    .split('.')
    .reduce<unknown>((acc, seg) => (acc as Json)?.[seg], obj);
}

test.describe('i18n: gateway message catalog parity', () => {
  test('en and ko have an identical key tree', () => {
    const enPaths = leafPaths(en as Json);
    const koPaths = leafPaths(ko as Json);
    expect(koPaths).toEqual(enPaths);
  });

  test('every en leaf is a non-empty string', () => {
    for (const path of leafPaths(en as Json)) {
      const value = leafValue(en as Json, path);
      expect(typeof value, `en leaf ${path} must be a string`).toBe('string');
      expect((value as string).trim().length, `en leaf ${path} is empty`).toBeGreaterThan(0);
    }
  });

  test('every ko leaf is a non-empty string', () => {
    for (const path of leafPaths(ko as Json)) {
      const value = leafValue(ko as Json, path);
      expect(typeof value, `ko leaf ${path} must be a string`).toBe('string');
      expect((value as string).trim().length, `ko leaf ${path} is empty`).toBeGreaterThan(0);
    }
  });
});
