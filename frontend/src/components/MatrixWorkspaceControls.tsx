import React, { useEffect, useRef, useState } from 'react';

/** Layout mode keeps the browser window tiled beside a PDF. Native fullscreen
 * is a separate opt-in because it normally occupies the whole monitor. */
export function useMatrixWorkspace() {
  const [workspace, setWorkspace] = useState(false);
  useEffect(() => {
    document.body.classList.toggle('crm-workspace', workspace);
    return () => document.body.classList.remove('crm-workspace');
  }, [workspace]);
  return { workspace, setWorkspace };
}

export default function MatrixWorkspaceControls({ active, onChange }: {
  active: boolean;
  onChange: (active: boolean) => void;
}) {
  const [fullscreen, setFullscreen] = useState(false);
  const [error, setError] = useState('');
  const owned = useRef(false);
  useEffect(() => {
    const change = () => {
      setFullscreen(document.fullscreenElement === document.documentElement);
      if (!document.fullscreenElement) owned.current = false;
    };
    document.addEventListener('fullscreenchange', change);
    return () => {
      document.removeEventListener('fullscreenchange', change);
      if (owned.current && document.fullscreenElement === document.documentElement) {
        void document.exitFullscreen().catch(() => {});
      }
    };
  }, []);

  const toggleFullscreen = async () => {
    setError('');
    try {
      if (document.fullscreenElement === document.documentElement) {
        await document.exitFullscreen();
      } else if (document.documentElement.requestFullscreen) {
        owned.current = true;
        await document.documentElement.requestFullscreen();
      } else {
        setError('Браузер не поддерживает полноэкранный режим. Можно использовать F11.');
      }
    } catch {
      owned.current = false;
      setError('Браузер не разрешил полноэкранный режим. Можно использовать F11.');
    }
  };

  return <div className="crm-workspace-controls">
    {active && <button type="button" className="crm-mini-btn" onClick={() => void toggleFullscreen()}
      title="Скрыть вкладки и адресную строку. Обычно занимает весь монитор; Esc возвращает окно.">
      {fullscreen ? 'Вернуть окно' : 'На весь экран'}
    </button>}
    <button type="button" className="crm-mini-btn crm-workspace-toggle" aria-pressed={active}
      aria-label={active ? 'Свернуть рабочую область' : 'Развернуть рабочую область'}
      title={active ? 'Вернуть шапку сайта и подробные заголовки' : 'Развернуть рабочую область в пределах окна браузера'}
      onClick={() => {
        if (owned.current && document.fullscreenElement === document.documentElement) {
          void document.exitFullscreen().catch(() => {});
        }
        setError('');
        onChange(!active);
      }}>
      <span aria-hidden="true">{active ? '↙' : '[ ]'}</span>
      <span>{active ? 'Свернуть' : 'Рабочая область'}</span>
    </button>
    {error && <span role="status" className="crm-workspace-error">{error}</span>}
  </div>;
}
