import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import './SharesCapHover.css';

interface SharesCapHoverProps {
  explanation: string | null | undefined;
  children: React.ReactNode;
}

/**
 * Подсказка по базе капитализации при наведении.
 * Без пунктира и иконок — только hover-курсор и portal-тултип в стиле CR.
 */
const SharesCapHover: React.FC<SharesCapHoverProps> = ({
  explanation,
  children,
}) => {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0 });

  const hasTip = Boolean(explanation);

  const onMove = (e: React.MouseEvent) => {
    setPos({ x: e.clientX + 14, y: e.clientY + 14 });
  };

  if (!hasTip) {
    return <>{children}</>;
  }

  return (
    <>
      <span
        className="shares-cap-hover-target"
        onMouseEnter={(e) => {
          onMove(e);
          setOpen(true);
        }}
        onMouseMove={(e) => {
          if (open) onMove(e);
        }}
        onMouseLeave={() => setOpen(false)}
      >
        {children}
      </span>
      {open
        ? createPortal(
            <div
              className="shares-cap-tooltip"
              style={{ left: pos.x, top: pos.y }}
              role="tooltip"
            >
              <div className="shares-cap-tooltip-title">База капитализации</div>
              <div className="shares-cap-tooltip-body">{explanation}</div>
            </div>,
            document.body,
          )
        : null}
    </>
  );
};

export default SharesCapHover;
