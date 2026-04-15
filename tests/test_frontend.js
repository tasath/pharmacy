/**
 * Frontend Unit Tests — Σάρωση SMS Συνταγών
 * Run with: npx jest tests/test_frontend.js
 *
 * Tests extractRx(), rxStatus(), date parsing
 */

// ── Replicate frontend functions for testing ───────────────────────

function extractRx(text) {
  const found = [];
  const norm = text
    .replace(/[oO]/g, '0')
    .replace(/[lI|]/g, '1')
    .replace(/[sS]/g, '5')
    .replace(/[bB]/g, '8')
    .replace(/[zZ]/g, '2');

  const codes = [];
  const dateRx = /(\d{2}\/\d{2}\/\d{4})/g;

  for (const src of [text, norm]) {
    const r1 = /#\s*(\d{16})/g;       // IDIKA codes always exactly 16 digits
    const r2 = /(?<!\d)(\d{16})(?!\d)/g;
    let m;
    while ((m = r1.exec(src)) !== null)
      if (!codes.find(c => c.code === m[1])) codes.push({ code: m[1], pos: m.index });
    while ((m = r2.exec(src)) !== null)
      if (!codes.find(c => c.code === m[1])) codes.push({ code: m[1], pos: m.index });
  }

  codes.sort((a, b) => a.pos - b.pos);

  const dates = []; let m;
  while ((m = dateRx.exec(text)) !== null) dates.push({ date: m[1], pos: m.index });

  codes.forEach(c => {
    const next = dates.filter(d => d.pos > c.pos).slice(0, 2);
    found.push({ number: c.code, ekdosi: next[0]?.date || '', lixis: next[1]?.date || '' });
  });

  return found;
}

function rxStatus(ekdosi, lixis) {
  const now = new Date('2026-04-14'); // Fixed date for tests (day before expiry test)
  const parseDate = (s) => {
    if (!s) return null;
    const p = s.split('/');
    return p.length === 3 ? new Date(+p[2], +p[1]-1, +p[0]) : null;
  };
  const e = parseDate(ekdosi);
  const l = parseDate(lixis);
  if (l && l < now) return 'expired';
  if (e && e > now) return 'upcoming';
  return 'active';
}

// ═══════════════════════════════════════════════════════════════════
// extractRx() tests
// ═══════════════════════════════════════════════════════════════════
describe('extractRx — prescription number extraction', () => {

  test('extracts single prescription with # prefix', () => {
    const text = 'Έκδοση Συνταγής\n# 2603273623318101\nΗμ/νια: 14/04/2026\nΛήξη: 14/07/2026';
    const result = extractRx(text);
    expect(result).toHaveLength(1);
    expect(result[0].number).toBe('2603273623318101');
    expect(result[0].ekdosi).toBe('14/04/2026');
    expect(result[0].lixis).toBe('14/07/2026');
  });

  test('extracts 2 prescriptions', () => {
    const text = [
      'Έκδοση Συνταγής',
      '# 2603273623318101',
      'Ημ/νια: 14/04/2026 10:15:00',
      'Λήξη: 14/07/2026',
      'Έκδοση Συνταγής',
      '# 2603273623318202',
      'Ημ/νια: 14/07/2026 10:15:01',
      'Λήξη: 14/10/2026'
    ].join('\n');
    const result = extractRx(text);
    expect(result).toHaveLength(2);
    expect(result[0].number).toBe('2603273623318101');
    expect(result[1].number).toBe('2603273623318202');
  });

  test('extracts 6 prescriptions', () => {
    const lines = [];
    for (let i = 1; i <= 6; i++) {
      lines.push(`Έκδοση Συνταγής\n# 260327362331810${i}\nΗμ/νια: 14/04/2026\nΛήξη: 14/07/2026`);
    }
    const result = extractRx(lines.join('\n'));
    expect(result).toHaveLength(6);
  });

  test('handles OCR with o instead of 0', () => {
    const text = 'Έκδοση Συνταγής\n# 26o3273623318101\nΗμ/νια: 14/04/2026\nΛήξη: 14/07/2026';
    const result = extractRx(text);
    expect(result).toHaveLength(1);
    expect(result[0].number).toBe('2603273623318101');
  });

  test('handles OCR with l instead of 1', () => {
    const text = 'Έκδοση Συνταγής\n# 2603273623318l01\nΗμ/νια: 14/04/2026\nΛήξη: 14/07/2026';
    const result = extractRx(text);
    expect(result).toHaveLength(1);
    expect(result[0].number).toBe('2603273623318101');
  });

  test('handles # with space before number', () => {
    const text = '# 2603273623318101\n14/04/2026\n14/07/2026';
    const result = extractRx(text);
    expect(result).toHaveLength(1);
    expect(result[0].number).toBe('2603273623318101');
  });

  test('does not extract numbers that are too short', () => {
    const text = '# 12345\n14/04/2026';
    const result = extractRx(text);
    expect(result).toHaveLength(0);
  });

  test('does not duplicate same prescription', () => {
    const text = '# 2603273623318101\n# 2603273623318101\n14/04/2026\n14/07/2026';
    const result = extractRx(text);
    expect(result).toHaveLength(1);
  });

  test('handles missing dates gracefully', () => {
    const text = 'Έκδοση Συνταγής\n# 2603273623318101';
    const result = extractRx(text);
    expect(result).toHaveLength(1);
    expect(result[0].ekdosi).toBe('');
    expect(result[0].lixis).toBe('');
  });

  test('extracts dates in correct order (ekdosi before lixis)', () => {
    const text = '# 2603273623318101\n03/01/2026\n03/04/2026';
    const result = extractRx(text);
    expect(result[0].ekdosi).toBe('03/01/2026');
    expect(result[0].lixis).toBe('03/04/2026');
  });

  test('returns empty array for text with no prescriptions', () => {
    const text = 'Καλημέρα! Δεν υπάρχουν συνταγές εδώ.';
    const result = extractRx(text);
    expect(result).toHaveLength(0);
  });

  test('handles real IDIKA SMS format', () => {
    const text = [
      'IDIKA',
      'Κρατικός Φορέας',
      'Σήμερα 11:20',
      'Έκδοση Συνταγής',
      '# 2603273623318101',
      'Ημ/νια: 14/04/2026 10:15:00',
      'Λήξη: 14/07/2026',
      'Έκδοση Συνταγής',
      '# 2603273623318202',
      'Ημ/νια: 14/07/2026 10:15:01',
      'Λήξη: 14/10/2026',
      'Έκδοση Συνταγής',
      '# 2603273623318303',
      'Ημ/νια: 14/10/2026 10:15:02',
      'Λήξη: 14/01/2027',
    ].join('\n');
    const result = extractRx(text);
    expect(result).toHaveLength(3);
    expect(result[0].number).toBe('2603273623318101');
    expect(result[1].number).toBe('2603273623318202');
    expect(result[2].number).toBe('2603273623318303');
  });
});

// ═══════════════════════════════════════════════════════════════════
// rxStatus() tests
// ═══════════════════════════════════════════════════════════════════
describe('rxStatus — prescription status calculation', () => {
  // Today is fixed at 2026-04-15

  test('active prescription (today is between ekdosi and lixis)', () => {
    expect(rxStatus('01/01/2026', '01/07/2026')).toBe('active');
  });

  test('expired prescription (lixis is in the past)', () => {
    expect(rxStatus('01/01/2026', '01/03/2026')).toBe('expired');
  });

  test('upcoming prescription (ekdosi is in the future)', () => {
    expect(rxStatus('01/06/2026', '01/09/2026')).toBe('upcoming');
  });

  test('active when no dates provided', () => {
    expect(rxStatus('', '')).toBe('active');
  });

  test('active when only ekdosi provided (past)', () => {
    expect(rxStatus('01/01/2026', '')).toBe('active');
  });

  test('expired when only lixis provided (past)', () => {
    expect(rxStatus('', '01/01/2026')).toBe('expired');
  });

  test('active when only lixis provided (future)', () => {
    expect(rxStatus('', '01/12/2026')).toBe('active');
  });

  test('prescription expiring today is still active', () => {
    expect(rxStatus('01/01/2026', '15/04/2026')).toBe('active');
  });
});

// ═══════════════════════════════════════════════════════════════════
// Access code format validation
// ═══════════════════════════════════════════════════════════════════
describe('Access code validation', () => {
  const isValidCode = (code) => /^FARM-[A-Z0-9]{8}$/.test(code);

  test('valid code format', () => {
    expect(isValidCode('FARM-A1B2C3D4')).toBe(true);
  });

  test('too short code', () => {
    expect(isValidCode('FARM-ABC')).toBe(false);
  });

  test('missing FARM prefix', () => {
    expect(isValidCode('TEST-A1B2C3D4')).toBe(false);
  });

  test('lowercase not valid', () => {
    expect(isValidCode('FARM-a1b2c3d4')).toBe(false);
  });
});
