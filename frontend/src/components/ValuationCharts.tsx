import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Brush, CartesianGrid, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { getCompanySeries, type SeriesYear } from '../services/valuation.api';
import { useChartColors } from '../contexts/ThemeContext';

/**
 * Ряды по годам, из которых сложилась оценка.
 *
 * Итоговые числа за окно скрывают главное — как величина себя вела. Средняя
 * EPS 916 ₽ у ЛУКОЙЛа складывается из 1668 в 2023-м и 158 в 2025-м, и это
 * разные истории, хотя средняя одна. Поэтому рядом с каждой средней здесь
 * рисуется ряд, а сама средняя — пунктирной линией через всё поле.
 *
 * Цена берётся на дату отчёта («как торговалось тогда»), а не приводится к
 * сегодняшнему масштабу: так принято во всём проекте, и дробления не
 * переписывают историю задним числом.
 */

type SeriesKey =
  | 'eps'
  | 'fcf_per_share'
  | 'owner_earnings_per_share'
  | 'book_value_per_share'
  | 'price'
  | 'dividends_per_share';

interface SeriesSpec {
  key: SeriesKey;
  label: string;
  /** Индекс цвета из палитры темы: line1…line6. */
  tone: 1 | 2 | 3 | 4 | 5 | 6;
  /** Есть ли для этой величины средняя за окно. */
  averaged?: boolean;
}

const SERIES: SeriesSpec[] = [
  { key: 'eps', label: 'Прибыль на акцию', tone: 1, averaged: true },
  { key: 'fcf_per_share', label: 'Свободный поток', tone: 2, averaged: true },
  { key: 'owner_earnings_per_share', label: 'Прибыль владельца', tone: 3, averaged: true },
  { key: 'book_value_per_share', label: 'Балансовая стоимость', tone: 4 },
  { key: 'price', label: 'Цена', tone: 5 },
  { key: 'dividends_per_share', label: 'Дивиденд', tone: 6 },
];

/** Что показываем по умолчанию: три лестницы оценки. */
const DEFAULT_VISIBLE: SeriesKey[] = ['eps', 'fcf_per_share', 'owner_earnings_per_share'];

const money = (v: number | null | undefined) =>
  v === null || v === undefined
    ? '—'
    : `${v.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ₽`;

export default function ValuationCharts({
  companyId,
  window,
}: {
  companyId: number;
  window: number;
}) {
  const colors = useChartColors();
  const [visible, setVisible] = useState<SeriesKey[]>(DEFAULT_VISIBLE);
  const [showAverages, setShowAverages] = useState(true);

  const { data, isLoading } = useQuery({
    queryKey: ['company-series', companyId, window],
    queryFn: () => getCompanySeries(companyId, window),
  });

  const toneOf = (spec: SeriesSpec) =>
    (colors as unknown as Record<string, string>)[`line${spec.tone}`];

  // Балансовая стоимость и цена на порядок больше прибыли на акцию, и на одной
  // оси прибыль превращается в прямую у нуля. Поэтому крупные величины уходят
  // на правую ось — это честнее, чем нормировать ряды и потерять рубли.
  const bigScale = useMemo(
    () => new Set<SeriesKey>(['book_value_per_share', 'price']),
    [],
  );
  const usesRight = visible.some((k) => bigScale.has(k));
  const usesLeft = visible.some((k) => !bigScale.has(k));

  if (isLoading) return <div className="vc-empty">Строю графики…</div>;
  if (!data?.available || data.years.length === 0) {
    return <div className="vc-empty">Рядов нет: не хватает годовых отчётов.</div>;
  }

  const toggle = (key: SeriesKey) =>
    setVisible((current) =>
      current.includes(key) ? current.filter((k) => k !== key) : [...current, key],
    );

  return (
    <div className="vc">
      <div className="vc-controls">
        {SERIES.map((spec) => {
          const on = visible.includes(spec.key);
          return (
            <button
              key={spec.key}
              type="button"
              className={`vc-chip${on ? ' is-on' : ''}`}
              onClick={() => toggle(spec.key)}
              style={on ? { borderColor: toneOf(spec), color: toneOf(spec) } : undefined}
            >
              <span className="vc-dot" style={{ background: on ? toneOf(spec) : 'transparent',
                                                borderColor: toneOf(spec) }} />
              {spec.label}
            </button>
          );
        })}
        <label className="vc-averages">
          <input
            type="checkbox"
            checked={showAverages}
            onChange={(e) => setShowAverages(e.target.checked)}
          />
          средние за {window} лет
        </label>
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data.years} margin={{ top: 10, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={colors.grid} />
          <XAxis dataKey="year" tick={{ fontSize: 11, fill: colors.axis }} />
          {usesLeft && (
            <YAxis
              yAxisId="left"
              tick={{ fontSize: 11, fill: colors.axis }}
              width={58}
              tickFormatter={(v: number) => v.toLocaleString('ru-RU')}
            />
          )}
          {usesRight && (
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fontSize: 11, fill: colors.axis }}
              width={62}
              tickFormatter={(v: number) => v.toLocaleString('ru-RU')}
            />
          )}
          <Tooltip
            formatter={(value: unknown, name) => [money(value as number), name]}
            labelStyle={{ color: colors.textPrimary, fontWeight: 600 }}
            contentStyle={{
              backgroundColor: colors.tooltipBg,
              border: `1px solid ${colors.tooltipBorder}`,
              borderRadius: 8,
              color: colors.textPrimary,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />

          {/* Средняя за окно — линия через всё поле, а не точка ряда. */}
          {showAverages &&
            SERIES.filter((s) => s.averaged && visible.includes(s.key)).map((spec) => {
              const average = data.averages[spec.key];
              if (!average) return null;
              return (
                <ReferenceLine
                  key={`avg-${spec.key}`}
                  yAxisId={bigScale.has(spec.key) ? 'right' : 'left'}
                  y={average.value}
                  stroke={toneOf(spec)}
                  strokeDasharray="6 4"
                  strokeOpacity={0.7}
                  label={{
                    value: `${average.value.toLocaleString('ru-RU')}`,
                    position: 'insideTopLeft',
                    fontSize: 10,
                    fill: toneOf(spec),
                  }}
                />
              );
            })}

          {SERIES.filter((s) => visible.includes(s.key)).map((spec) => (
            <Line
              key={spec.key}
              yAxisId={bigScale.has(spec.key) ? 'right' : 'left'}
              type="monotone"
              dataKey={spec.key}
              name={spec.label}
              stroke={toneOf(spec)}
              strokeWidth={2}
              dot={{ r: 2.5 }}
              activeDot={{ r: 5 }}
              connectNulls={false}
            />
          ))}

          {/* Диапазон лет: тянется мышью, а не выбирается из списка. */}
          {data.years.length > 4 && (
            <Brush
              dataKey="year"
              height={22}
              travellerWidth={8}
              stroke={colors.axis}
              fill={colors.tooltipBg}
            />
          )}
        </LineChart>
      </ResponsiveContainer>

      <p className="vc-foot">
        Пунктиром — средняя за {window} лет: та самая нормальная величина, на
        которую умножается множитель. Разрыв линии означает, что за этот год
        показателя нет, а не что он равен нулю. Цена — на дату отчёта, как
        торговалась тогда.
        {gapsNote(data.years, visible)}
      </p>
    </div>
  );
}

/** Явно называем годы с пропусками: разрыв линии сам по себе неочевиден. */
function gapsNote(years: SeriesYear[], visible: SeriesKey[]): string {
  const gaps = years
    .filter((y) => visible.some((k) => y[k] === null || y[k] === undefined))
    .map((y) => y.year);
  if (gaps.length === 0) return '';
  return ` Пропуски: ${gaps.join(', ')}.`;
}
