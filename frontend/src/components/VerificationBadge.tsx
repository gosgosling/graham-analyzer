import React from 'react';

interface VerificationBadgeProps {
  autoExtracted?: boolean;
  verifiedByAnalyst?: boolean;
  /** Компактный вариант — точка/миниатюрный лейбл */
  compact?: boolean;
}

/**
 * Значок статуса проверки финансового отчёта.
 *
 * Отображается:
 *  - «Черновик AI» + предупреждение, если auto_extracted && !verified.
 *  - «Требует проверки», если !auto_extracted && !verified (редкий случай,
 *    когда аналитик вручную снял проверку).
 *  - Ничего, если отчёт проверен (verified_by_analyst=true).
 */
const VerificationBadge: React.FC<VerificationBadgeProps> = ({
  autoExtracted,
  verifiedByAnalyst,
  compact = false,
}) => {
  if (verifiedByAnalyst) return null;

  const isAi = Boolean(autoExtracted);
  const label = isAi ? 'Черновик AI' : 'Нужна проверка';
  const title = isAi
    ? 'Отчёт извлечён ИИ-парсером из PDF и ожидает проверки аналитиком'
    : 'Отчёт помечен как требующий повторной проверки аналитиком';
  const icon = isAi ? '🤖' : '⚠️';
  const bg = isAi ? '#fff7e6' : '#fff1f0';
  const border = isAi ? '#ffd591' : '#ffa39e';
  const color = isAi ? '#ad6800' : '#a8071a';

  if (compact) {
    return (
      <span
        title={title}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 20,
          height: 20,
          borderRadius: '50%',
          background: bg,
          border: `1px solid ${border}`,
          color,
          fontSize: 11,
          lineHeight: 1,
        }}
      >
        {isAi ? '🤖' : '⚠'}
      </span>
    );
  }

  return (
    <span
      title={title}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        borderRadius: 12,
        background: bg,
        border: `1px solid ${border}`,
        color,
        fontSize: 12,
        fontWeight: 500,
        whiteSpace: 'nowrap',
      }}
    >
      <span aria-hidden>{icon}</span>
      {label}
    </span>
  );
};

export default VerificationBadge;
