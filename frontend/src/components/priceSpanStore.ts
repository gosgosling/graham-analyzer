/**
 * Живое состояние протяжки по графику цены — вне React-состояния страницы.
 *
 * Причина простая: `setState` на компоненте графика заставляет recharts
 * пересчитать все серии, а их пять по тысяче с лишним точек. Замер на
 * РусГидро показал около 400 мс на одну такую перерисовку — при живой
 * протяжке это сотни движений мыши и график встаёт колом. Само наведение
 * мыши recharts переживает без единой длинной задачи: дорого именно
 * обновление сверху.
 *
 * Поэтому отрезок живёт здесь, а подписаны на него две маленькие части —
 * подсветка и строка свода. Двигается только они, график не трогается вовсе.
 */

export interface LiveSpan {
  /** Пиксели внутри поля графика — из `chartX` событий recharts. */
  fromX: number;
  toX: number;
  fromDate: string;
  toDate: string;
}

export interface SpanStore {
  get(): LiveSpan | null;
  set(next: LiveSpan | null): void;
  subscribe(listener: () => void): () => void;
}

export function createSpanStore(): SpanStore {
  let value: LiveSpan | null = null;
  const listeners = new Set<() => void>();
  return {
    get: () => value,
    set(next) {
      value = next;
      listeners.forEach((listener) => listener());
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };
}
