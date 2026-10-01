import React from 'react';
import { Link } from 'react-router-dom';
import DbBackupButton from '../components/DbBackupButton';
import TInvestSyncBar from '../components/TInvestSyncBar';
import ThemeToggle from '../components/ThemeToggle';
import './AdminPage.css';

/**
 * Служебная страница: всё, чем пользуется только аналитик. Читателю эти
 * разделы не нужны, и в общей шапке они только мешали — восемь кнопок
 * вместо трёх.
 */

const TOOLS: { to: string; title: string; text: string }[] = [
  { to: '/', title: 'Ценные бумаги (MOEX)', text: 'Справочник бумаг Мосбиржи' },
  { to: '/companies', title: 'Компании (T-Invest)', text: 'Список компаний, проверка отчётов, синхронизация' },
  { to: '/mass-parse', title: 'Массовый парсинг', text: 'Загрузка отчётов пачкой через AI-парсер' },
  { to: '/disclosure', title: 'Отчётность', text: 'Покрытие раскрытия: какие отчёты есть на e-disclosure' },
  { to: '/bonds', title: 'Облигации', text: 'Справочник облигаций' },
  { to: '/valuation', title: 'Множитель рынка', text: 'Рыночный множитель и допущения оценки' },
  { to: '/screen', title: 'Консервативные критерии', text: 'Свод критериев по всему рынку' },
];

export default function AdminPage() {
  return (
    <div className="admin-page">
      <div className="admin-head">
        <h1>Админ</h1>
        <p>Служебные разделы: данные, отчёты, синхронизация и резервные копии.</p>
      </div>

      <section className="admin-card">
        <h2>Разделы</h2>
        <div className="admin-tools">
          {TOOLS.map((t) => (
            <Link key={t.to} to={t.to} className="admin-tool">
              <span className="admin-tool-title">{t.title}</span>
              <span className="admin-tool-text">{t.text}</span>
            </Link>
          ))}
        </div>
      </section>

      <section className="admin-card">
        <h2>Синхронизация с T-Invest</h2>
        <TInvestSyncBar />
      </section>

      <section className="admin-card admin-row">
        <div>
          <h2>Резервная копия базы</h2>
          <p className="admin-note">Дамп Postgres в папку бэкапов на сервере.</p>
        </div>
        <DbBackupButton />
      </section>

      <section className="admin-card admin-row">
        <div>
          <h2>Тема оформления</h2>
          <p className="admin-note">Светлая, тёмная или по настройке системы.</p>
        </div>
        <ThemeToggle />
      </section>
    </div>
  );
}
