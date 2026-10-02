import React from 'react';

/**
 * Знак сайта — весы. Из афоризма, который Баффет приписывает Грэму:
 * в краткосрочной перспективе рынок голосует, в долгосрочной — взвешивает.
 */
export function ScalesIcon({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3v18M7 21h10M4 7h16M12 5.2 4 7M12 5.2 20 7" />
      <path d="M4 7 1.5 13a2.6 2.6 0 0 0 5 0Z" />
      <path d="M20 7l-2.5 6a2.6 2.6 0 0 0 5 0Z" />
    </svg>
  );
}
