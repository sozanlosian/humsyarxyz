import {
  useEffect,
  useState,
} from 'react';

import {
  haptic,
} from '../../lib/telegram';

import ConvActionSheet from './ConvActionSheet';
import ConvRows from './ConvRows';

import SearchField from '../shared/SearchField';


/* ─────────────────────────────────────────────
   شیت سوییچ سریع گفت‌وگوها — داخل صفحه‌ی چت
   (دسترسی کامل به فهرست تاریخچه در خود صفحه‌ی
   /ai است؛ این شیت برای پرش سریع بدون ترک چت
   به‌کار می‌رود)
───────────────────────────────────────────── */


export default function ChatHistorySheet({
  conversations = [],
  activeId,
  loading = false,
  showArchived = false,
  busy = false,
  onToggleArchived,
  onClose,
  onSelect,
  onNew,
  onRename,
  onAction,
}) {
  const [query, setQuery] = useState('');

  // ردیفِ در حال تغییرنام (فقط یکی در هر لحظه)
  const [renameId, setRenameId] =
    useState(null);

  // گفت‌وگویی که اکشن‌شیتش باز است
  const [actionItem, setActionItem] =
    useState(null);


  // قفل اسکرول بدنه + بستن با Escape
  useEffect(() => {
    const previousOverflow =
      document.body.style.overflow;

    const closeWithEscape = (event) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    document.body.style.overflow = 'hidden';

    window.addEventListener(
      'keydown',
      closeWithEscape,
    );

    return () => {
      document.body.style.overflow =
        previousOverflow;

      window.removeEventListener(
        'keydown',
        closeWithEscape,
      );
    };
  }, [onClose]);


  const normalizedQuery = query.trim();

  const filtered = normalizedQuery
    ? conversations.filter((item) =>
        (
          String(item.title || '') +
          '\n' +
          String(item.preview || '')
        )
          .toLowerCase()
          .includes(
            normalizedQuery.toLowerCase(),
          ),
      )
    : conversations;


  const handleAction = (actionId) => {
    if (!actionItem) {
      return;
    }

    // تغییرنام این‌لاین در خودِ ردیف انجام می‌شود
    if (actionId === 'rename') {
      haptic('light');

      setRenameId(actionItem.id);

      return;
    }

    onAction(actionItem, actionId);
  };


  return (
    <div
      className="more-sheet"
      role="presentation"
      onClick={onClose}
    >
      <div
        className={
          'more-sheet__panel ' +
          'glass sheet-in'
        }
        role="dialog"
        aria-modal="true"
        aria-label="تاریخچه‌ی گفت‌وگوها"
        onClick={(event) =>
          event.stopPropagation()
        }
      >
        <div className="more-sheet__handle" />

        <div className="more-sheet__title">
          گفت‌وگوها
        </div>

        <button
          type="button"
          className="conv-new"
          onClick={onNew}
          disabled={busy}
        >
          ＋ گفت‌وگوی جدید
        </button>

        <div
          style={{ marginBottom: 9 }}
        >
          <SearchField
            value={query}
            onChange={(event) =>
              setQuery(
                event.target.value
              )
            }
            placeholder="جست‌وجو در گفت‌وگوها..."
            ariaLabel="جست‌وجو در گفت‌وگوها"
          />
        </div>

        <div className="conv-list">
          {
            loading
              ? [0, 1, 2].map((key) => (
                  <div
                    key={key}
                    className="skeleton"
                    style={{
                      height: 56,
                      borderRadius: 'var(--r-md)',
                    }}
                  />
                ))
              : filtered.length === 0
                ? (
                  <div className="conv-empty">
                    {
                      normalizedQuery
                        ? 'چیزی با این عبارت پیدا نشد'
                        : 'هنوز گفت‌وگویی نساخته‌ای؛ از دکمه‌ی بالا شروع کن'
                    }
                  </div>
                )
                : (
                  <ConvRows
                    items={filtered}
                    activeId={activeId}
                    renameId={renameId}
                    onRenameDone={() =>
                      setRenameId(null)
                    }
                    onRename={onRename}
                    onSelect={onSelect}
                    onOpenActions={(item) => {
                      haptic('light');

                      setActionItem(item);
                    }}
                    busy={busy}
                  />
                )
          }
        </div>

        <button
          type="button"
          className="conv-arch-toggle"
          onClick={onToggleArchived}
        >
          {
            showArchived
              ? '▾ پنهان‌کردن بایگانی‌شده‌ها'
              : '▸ نمایش بایگانی‌شده‌ها'
          }
        </button>
      </div>

      {
        actionItem
        && (
          <ConvActionSheet
            conv={actionItem}
            busy={busy}
            onClose={() =>
              setActionItem(null)
            }
            onAction={handleAction}
          />
        )
      }
    </div>
  );
}
