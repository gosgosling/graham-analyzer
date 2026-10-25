import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';

/**
 * Яндекс Метрика: сколько людей пришло, откуда и по каким запросам.
 *
 * Включается номером счётчика в сборке (REACT_APP_YM_ID); без него — ничего
 * не грузится, в разработке тоже. Вебвизор и карта кликов выключены: для
 * вопроса «по каким запросам находят сайт» запись действий посетителя не
 * нужна, а в политике конфиденциальности тогда пришлось бы описывать и её.
 *
 * Сайт одностраничный: переходы между страницами браузер не перезагружает,
 * поэтому каждый переход отправляется в счётчик отдельным просмотром.
 */

export const YM_ID = Number(process.env.REACT_APP_YM_ID) || null;

type Ym = ((id: number, method: string, ...args: unknown[]) => void) & { a?: unknown[]; l?: number };

declare global {
  interface Window { ym?: Ym }
}

function load(id: number) {
  if (window.ym) return;
  const ym: Ym = (...args: unknown[]) => { (ym.a = ym.a || []).push(args); };
  ym.l = Date.now();
  window.ym = ym;
  const script = document.createElement('script');
  script.async = true;
  script.src = 'https://mc.yandex.ru/metrika/tag.js';
  document.head.appendChild(script);
  ym(id, 'init', {
    defer: true,          // первый просмотр отправляем сами, как и остальные
    clickmap: false,
    trackLinks: true,
    accurateTrackBounce: true,
    webvisor: false,
  });
}

export default function Metrika() {
  const { pathname, search } = useLocation();
  const previous = useRef<string | null>(null);
  useEffect(() => {
    if (!YM_ID) return;
    load(YM_ID);
    const url = pathname + search;
    window.ym?.(YM_ID, 'hit', window.location.origin + url, {
      title: document.title,
      referer: previous.current ? window.location.origin + previous.current : document.referrer,
    });
    previous.current = url;
  }, [pathname, search]);
  return null;
}
