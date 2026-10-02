import React from 'react';
import { Link } from 'react-router-dom';
import { useAdmin } from '../hooks/useAdmin';

/** Служебная страница: гостю — короткое объяснение вместо инструментов. */
export default function AdminOnly({ children }: { children: React.ReactElement }) {
  const { isAdmin, checking } = useAdmin();
  if (checking) return null;
  if (isAdmin) return children;
  return (
    <div className="admin-page">
      <section className="admin-card">
        <h2>Раздел для администратора</h2>
        <p className="admin-note">
          Здесь загрузка и правка данных — для администратора. Все компании, оценки и критерии
          открыты в разделе <Link to="/companies">«Компании»</Link>.
        </p>
      </section>
    </div>
  );
}
