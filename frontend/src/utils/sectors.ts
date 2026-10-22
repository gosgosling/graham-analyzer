/**
 * Отрасли из справочника T-Invest по-русски.
 *
 * В справочнике они английскими ключами (`materials`, `utilities`), и в
 * списках выбора гость видел именно их.
 */
export const SECTOR_RU: Record<string, string> = {
  materials: 'Сырьё и материалы',
  utilities: 'Электроэнергетика',
  consumer: 'Потребительский сектор',
  financial: 'Финансы',
  energy: 'Нефть и газ',
  it: 'IT',
  industrials: 'Промышленность',
  telecom: 'Телеком',
  health_care: 'Здравоохранение',
  real_estate: 'Недвижимость',
  other: 'Прочее',
};

export const sectorRu = (key: string | null | undefined): string | null =>
  (key ? SECTOR_RU[key] ?? key : null);
