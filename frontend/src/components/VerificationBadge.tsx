import React from 'react';
import './VerificationBadge.css';

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
  const variant = isAi ? 'verification-badge--ai' : 'verification-badge--manual';
  const compactClass = compact ? ' verification-badge--compact' : '';

  if (compact) {
    return (
      <span className={`verification-badge${compactClass} ${variant}`} title={title}>
        {isAi ? '🤖' : '⚠'}
      </span>
    );
  }

  return (
    <span className={`verification-badge ${variant}`} title={title}>
      <span aria-hidden>{icon}</span>
      {label}
    </span>
  );
};

export default VerificationBadge;
