import React from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../services/companies.api';
import { AUTH_KEY, useAuth } from '../hooks/useAdmin';
import { Link, Navigate } from 'react-router-dom';
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
  { to: '/securities', title: 'Ценные бумаги (MOEX)', text: 'Справочник бумаг Мосбиржи' },
  { to: '/companies', title: 'Компании (T-Invest)', text: 'Список компаний, проверка отчётов, синхронизация' },
  { to: '/mass-parse', title: 'Массовый парсинг', text: 'Загрузка отчётов пачкой через AI-парсер' },
  { to: '/disclosure', title: 'Отчётность', text: 'Покрытие раскрытия: какие отчёты есть на e-disclosure' },
  { to: '/bonds', title: 'Облигации', text: 'Справочник облигаций' },
  { to: '/valuation', title: 'Множитель рынка', text: 'Рыночный множитель и допущения оценки' },
  { to: '/screen', title: 'Скринер', text: 'Требования Грэма ко всему рынку' },
];

export default function AdminPage() {
  const { user, checking } = useAuth();
  const queryClient = useQueryClient();
  if (checking) return null;
  // Вход общий для всех: администратор — тот же аккаунт, только с ролью.
  if (!user) return <Navigate to="/login?next=/admin" replace />;
  if (user.role !== 'admin') {
    return (
      <div className="admin-page">
        <section className="admin-card">
          <h2>Недостаточно прав</h2>
          <p className="admin-note">
            Служебные разделы — только для администратора. Всё остальное на сайте открыто:
            {' '}<Link to="/companies">компании</Link>, оценки и критерии.
          </p>
        </section>
      </div>
    );
  }
  return (
    <div className="admin-page">
      <div className="admin-head">
        <div>
          <h1>Админ</h1>
          <p>Служебные разделы: данные, отчёты, синхронизация и резервные копии.</p>
        </div>
        <button
          type="button"
          className="admin-logout"
          onClick={async () => {
            try {
              await api.post('/auth/logout');
            } finally {
              queryClient.removeQueries({ queryKey: AUTH_KEY });
              await queryClient.invalidateQueries();
            }
          }}
        >
          Выйти
        </button>
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
