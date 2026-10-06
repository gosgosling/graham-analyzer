import { auditTitle, softMarks } from './auditText';

describe('подсказка аудита', () => {
  it('склоняет число пометок', () => {
    expect(softMarks(1)).toBe('мягкая пометка');
    expect(softMarks(3)).toBe('мягкие пометки');
    expect(softMarks(10)).toBe('мягких пометок');
    expect(softMarks(11)).toBe('мягких пометок');
    expect(softMarks(22)).toBe('мягкие пометки');
  });

  it('перечисляет дефекты по годам', () => {
    const text = auditTitle({
      ticker: 'DVEC',
      defects: [{ year: 2011, message: 'баланс не сходится на 13.6%' }],
      warnings: 3,
    });
    expect(text).toContain('2011: баланс не сходится на 13.6%');
    expect(text).toContain('Ещё 3 мягкие пометки');
  });
});
