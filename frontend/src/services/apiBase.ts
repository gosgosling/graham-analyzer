/**
 * Адрес API. Отдельным модулем без axios: его импортируют утилиты, которые
 * тестируются без сети, а axios в jest как ES-модуль не грузится.
 */
export const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';
