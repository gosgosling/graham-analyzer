import React, { useState } from 'react';
import { logoCandidatesFromUrl } from '../utils/companyLogo';

/**
 * Логотип компании по ссылке из API.
 *
 * CDN Тинькофф отдаёт только объекты с суффиксом размера (`…x160.png`), а
 * T-Invest возвращает ссылку без него — прямой `src` даёт 403. Поэтому
 * кандидаты перебираются по очереди, и если не подошёл ни один, элемент
 * просто исчезает: пустой кружок с иконкой битой картинки хуже, чем ничего.
 */
const CompanyLogo: React.FC<{
  url: string | null | undefined;
  /** Тикер — для копии логотипа на нашем сервере; без него только CDN. */
  ticker?: string | null;
  alt?: string;
  className?: string;
}> = ({ url, ticker, alt = '', className }) => {
  const candidates = React.useMemo(() => logoCandidatesFromUrl(url, ticker), [url, ticker]);
  const [attempt, setAttempt] = useState(0);

  React.useEffect(() => setAttempt(0), [url, ticker]);

  if (attempt >= candidates.length) return null;
  return (
    <img
      className={className}
      src={candidates[attempt]}
      alt={alt}
      loading="lazy"
      onError={() => setAttempt((a) => a + 1)}
    />
  );
};

export default CompanyLogo;
