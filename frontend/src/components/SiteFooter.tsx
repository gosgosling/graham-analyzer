import React from 'react';
import { Link } from 'react-router-dom';
import './SiteFooter.css';

/**
 * Подвал сайта.
 *
 * Пока макет: Telegram и почта — заглушки, их адреса вписываются перед
 * публикацией. Оговорка про инвестиционную рекомендацию — не украшение: на
 * публичном сайте с «дёшево» и «дорого» у каждой компании она обязательна.
 */

// TODO: вписать настоящие адреса перед публикацией.
const TELEGRAM = { label: '@graham_analyzer', href: '#' };
const EMAIL = { label: 'hello@example.ru', href: '#' };
const GITHUB = 'https://github.com/gosgosling/graham-analyzer';

export default function SiteFooter() {
  const year = new Date().getFullYear();

  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <div className="site-footer-top">
          <div className="site-footer-about">
            <span className="site-footer-name">Graham Analyzer</span>
            <p>Стоимость российских акций по методу Грэма и Додда — из отчётов МСФО, без прогнозов.</p>
          </div>

          <nav className="site-footer-links" aria-label="Ссылки в подвале">
            <div>
              <span className="site-footer-heading">Проект</span>
              <Link to="/valuation">Как считается стоимость</Link>
              <Link to="/screen">Скринер</Link>
              <a href={GITHUB} target="_blank" rel="noreferrer">Исходный код</a>
              <Link to="/privacy">Какие данные храним</Link>
            </div>
            <div>
              <span className="site-footer-heading">Связь</span>
              <a href={TELEGRAM.href}>Telegram {TELEGRAM.label}</a>
              <a href={EMAIL.href}>{EMAIL.label}</a>
            </div>
          </nav>
        </div>

        <div className="site-footer-bottom">
          <span>© {year} · Данные: Мосбиржа, e-disclosure, Банк России</span>
          <span>Не является индивидуальной инвестиционной рекомендацией.</span>
        </div>
      </div>
    </footer>
  );
}
