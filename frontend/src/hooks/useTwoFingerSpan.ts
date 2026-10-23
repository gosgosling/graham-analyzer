import { useEffect, type RefObject } from 'react';
import type { SpanStore } from '../components/priceSpanStore';

/**
 * Поле графика recharts в пикселях от левого верхнего угла обёртки `box`.
 *
 * Берётся из прямоугольника обрезки, который recharts кладёт ровно по полю:
 * сетки на телефоне может не быть, а оси бывают внутри поля. Мерить сам
 * прямоугольник через getBoundingClientRect нельзя — внутри <clipPath> он не
 * отрисовывается, и браузер отдаёт нули; поэтому — его атрибуты плюс
 * положение SVG.
 */
export function plotArea(box: HTMLElement): { left: number; top: number; width: number; height: number } | null {
  // Основной график — прямой потомок обёртки; у слоя наложения (если он
  // есть) своё поле той же формы, но мерить надо основное.
  const svg = box.querySelector(':scope > .recharts-responsive-container svg.recharts-surface')
    ?? box.querySelector('svg.recharts-surface');
  const rect = svg?.querySelector('clipPath rect');
  if (!svg || !rect) return null;
  const num = (name: string) => Number(rect.getAttribute(name)) || 0;
  const outer = box.getBoundingClientRect();
  const surface = svg.getBoundingClientRect();
  return {
    left: surface.left - outer.left + num('x'),
    top: surface.top - outer.top + num('y'),
    width: num('width'),
    height: num('height'),
  };
}

/**
 * Выделение отрезка на графике двумя пальцами — телефонная замена протяжки
 * мышью, как в приложениях брокеров.
 *
 * Протяжка одним пальцем на телефоне занята: ею листают страницу и водят
 * подсказку по дням. Отрезок остаётся и после того, как пальцы убраны —
 * свод под графиком надо успеть прочитать, — и снимается касанием одним
 * пальцем.
 *
 * Слушатели — свои, а не React: обработчики касаний у React пассивные, и без
 * preventDefault два пальца увеличивали бы страницу.
 *
 * @param canvas  обёртка графика, от её левого края считаются пиксели отрезка
 * @param points  точки графика в порядке оси X (по одной категории на точку)
 * @param onBegin вызывается в начале жеста — например, чтобы замерить поле
 */
export function useTwoFingerSpan(
  canvas: RefObject<HTMLDivElement | null>,
  points: readonly { date: string }[] | null | undefined,
  store: SpanStore,
  enabled: boolean,
  onBegin?: () => void,
) {
  useEffect(() => {
    const box = canvas.current;
    if (!enabled || !box || !points?.length) return undefined;
    const plot = () => {
      const area = plotArea(box);
      return area && { ...area, outer: box.getBoundingClientRect().left };
    };
    const at = (clientX: number, p: { outer: number; left: number; width: number }) => {
      const x = clientX - p.outer;
      const n = points.length;
      const i = Math.max(0, Math.min(n - 1, Math.floor(((x - p.left) / p.width) * n)));
      // Край подсветки — по центру дня, а не под пальцем: так полоса
      // начинается ровно там, откуда считается свод.
      return { date: points[i].date, x: p.left + ((i + 0.5) / n) * p.width };
    };
    const onTwo = (e: TouchEvent) => {
      if (e.touches.length !== 2) return;
      e.preventDefault();
      const p = plot();
      if (!p || p.width <= 0) return;
      const [a, b] = [e.touches[0].clientX, e.touches[1].clientX].sort((x, y) => x - y).map((x) => at(x, p));
      if (a.date === b.date) return;
      store.set({ fromX: a.x, toX: b.x, fromDate: a.date, toDate: b.date });
    };
    const onStart = (e: TouchEvent) => {
      if (e.touches.length === 1) { store.set(null); return; }
      onBegin?.();
      onTwo(e);
    };
    box.addEventListener('touchstart', onStart, { passive: false });
    box.addEventListener('touchmove', onTwo, { passive: false });
    return () => {
      box.removeEventListener('touchstart', onStart);
      box.removeEventListener('touchmove', onTwo);
    };
  }, [canvas, points, store, enabled, onBegin]);
}

/**
 * Класс `has-span` на обёртке графика, пока выделен отрезок — пальцами или
 * мышью. По нему CSS прячет подсказку по дню: выделение — вопрос «сколько
 * между», а не «сколько в этот день», и окно цены поверх только заслоняло
 * отрезок. Подсказка нужна для одной точки — она вернётся, как только
 * выделение снимут. Класс ставится на обёртку напрямую: перерисовывать ради
 * него график незачем.
 */
export function useSpanMark(canvas: RefObject<HTMLDivElement | null>, store: SpanStore, ready: unknown) {
  useEffect(() => {
    const box = canvas.current;
    if (!box) return undefined;
    const mark = () => box.classList.toggle('has-span', store.get() !== null);
    const unsubscribe = store.subscribe(mark);
    mark();
    return () => {
      unsubscribe();
      box.classList.remove('has-span');
    };
    // ready — обёртка появляется только после загрузки данных графика.
  }, [canvas, store, ready]);
}
