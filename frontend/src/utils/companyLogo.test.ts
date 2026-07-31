import type { Company } from '../types';
import { getCompanyLogoCandidates } from './companyLogo';

/**
 * Поведение CDN проверено запросами: объект без суффикса размера отдаёт
 * 403 AccessDenied, тот же объект с `x160` — 200. При этом T-Invest API
 * кладёт в `brand_logo_url` именно ссылку без суффикса, поэтому кандидаты
 * с размером обязаны идти первыми.
 */
function company(fields: Partial<Company>): Company {
  return {
    figi: 'FIGI0001',
    ticker: 'TEST',
    name: 'Тестовая компания',
    currency: 'RUB',
    ...fields,
  } as Company;
}

const CDN = 'https://invest-brands.cdn-tinkoff.ru';

describe('getCompanyLogoCandidates', () => {
  it('к ссылке из API добавляет размеры и ставит их перед исходной', () => {
    const urls = getCompanyLogoCandidates(
      company({ brand_logo_url: `${CDN}/RU000A103X66.png`, isin: 'RU000A103X66', ticker: 'POSI' }),
    );

    expect(urls[0]).toBe(`${CDN}/RU000A103X66x160.png`);
    expect(urls[1]).toBe(`${CDN}/RU000A103X66x640.png`);
    // Исходная ссылка остаётся в списке, но после рабочих вариантов.
    expect(urls.indexOf(`${CDN}/RU000A103X66.png`)).toBeGreaterThan(1);
  });

  it('имя объекта берётся из ссылки, а не собирается из ISIN', () => {
    // У МТС и Сегежи объект назван не по ISIN — вариант из ISIN даёт 403.
    const urls = getCompanyLogoCandidates(
      company({ brand_logo_url: `${CDN}/mtsnew.png`, isin: 'RU0007775219', ticker: 'MTSS' }),
    );

    expect(urls[0]).toBe(`${CDN}/mtsnewx160.png`);
  });

  it('не добавляет второй суффикс, если размер уже указан', () => {
    const urls = getCompanyLogoCandidates(
      company({ brand_logo_url: `${CDN}/segezhax160.png`, ticker: 'SGZH' }),
    );

    expect(urls[0]).toBe(`${CDN}/segezhax160.png`);
    expect(urls.some((u) => u.includes('x160x160'))).toBe(false);
  });

  it('чужой хост не трогает — суффиксы только для CDN Тинькофф', () => {
    const external = 'https://example.com/logos/acme.png';
    const urls = getCompanyLogoCandidates(company({ brand_logo_url: external, ticker: 'ACME' }));

    expect(urls[0]).toBe(external);
    expect(urls.some((u) => u.startsWith('https://example.com') && u.includes('x160'))).toBe(false);
  });

  it('без ссылки из API падает на ISIN и тикер', () => {
    const urls = getCompanyLogoCandidates(company({ isin: 'RU0009029540', ticker: 'SBER' }));

    expect(urls).toContain(`${CDN}/RU0009029540x160.png`);
    expect(urls).toContain(`${CDN}/SBERx160.png`);
  });

  it('у префов пробует и «обычный» тикер', () => {
    const urls = getCompanyLogoCandidates(company({ ticker: 'SBERP' }));

    expect(urls).toContain(`${CDN}/SBERx160.png`);
    expect(urls).toContain(`${CDN}/SBERPx160.png`);
  });

  it('дублей в списке нет — каждая попытка это сетевой запрос', () => {
    const urls = getCompanyLogoCandidates(
      company({ brand_logo_url: `${CDN}/RU0009029540.png`, isin: 'RU0009029540', ticker: 'SBER' }),
    );

    expect(new Set(urls).size).toBe(urls.length);
  });
});
