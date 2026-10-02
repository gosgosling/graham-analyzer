import React from 'react';
import { FORMAT_LABEL, type ExportFormat } from '../utils/tableExport';
import './DownloadLinks.css';

const FORMATS: ExportFormat[] = ['xlsx', 'csv', 'txt'];

/** «Скачать: Excel · CSV · TXT» — тихая строка рядом с переключателями. */
export default function DownloadLinks({ onPick, what }: { onPick: (f: ExportFormat) => void; what: string }) {
  return (
    <span className="dl-links" role="group" aria-label={`Скачать ${what}`}>
      <span className="dl-label">Скачать</span>
      {FORMATS.map((f, i) => (
        <React.Fragment key={f}>
          {i > 0 && <span className="dl-sep" aria-hidden>·</span>}
          <button type="button" onClick={() => onPick(f)} title={`Скачать ${what} — ${FORMAT_LABEL[f]}`}>
            {FORMAT_LABEL[f]}
          </button>
        </React.Fragment>
      ))}
    </span>
  );
}
