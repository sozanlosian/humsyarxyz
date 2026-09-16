import {
  useEffect,
  useState,
} from 'react';


/* ─────────────────────────────────────────────
   ردیف‌های فهرست گفت‌وگو — به‌اشتراک‌گذاشته‌شده
   بین صفحه‌ی تاریخچه (/ai) و شیت سوییچ سریع
   داخل چت تا طراحی یکدست بماند.

   هر ردیف: آیکون، عنوان، پیش‌نمایش، زمان نسبی،
   شمار پیام، نشان همگام/legacy و دکمه‌ی ⋯ که
   اکشن‌شیت هفت‌عملی را باز می‌کند.
───────────────────────────────────────────── */


// زمان نسبی فارسی برای متا‌خط هر گفت‌وگو
export function relativeTime(value) {
  if (!value) {
    return '—';
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return '—';
  }

  const diffMinutes = Math.floor(
    (Date.now() - date.getTime()) / 60000,
  );

  if (diffMinutes < 1) {
    return 'هم‌اکنون';
  }

  if (diffMinutes < 60) {
    return (
      diffMinutes.toLocaleString('fa-IR') +
      ' دقیقه پیش'
    );
  }

  const diffHours = Math.floor(
    diffMinutes / 60,
  );

  if (diffHours < 24) {
    return (
      diffHours.toLocaleString('fa-IR') +
      ' ساعت پیش'
    );
  }

  const diffDays = Math.floor(
    diffHours / 24,
  );

  if (diffDays === 1) {
    return 'دیروز';
  }

  if (diffDays < 30) {
    return (
      diffDays.toLocaleString('fa-IR') +
      ' روز پیش'
    );
  }

  return date.toLocaleDateString('fa-IR', {
    month: 'short',
    day: 'numeric',
  });
}


export default function ConvRows({
  items = [],
  activeId = null,
  renameId = null,
  onRenameDone,
  onRename,
  onSelect,
  onOpenActions,
  busy = false,
  page = false,
}) {
  // پیش‌نویس تغییرنام — با هر تعویض ردیفِ
  // ویرایش، از عنوان همان گفت‌وگو بذر می‌شود
  const [renameDraft, setRenameDraft] =
    useState('');


  useEffect(() => {
    if (!renameId) {
      return;
    }

    const target = items.find(
      (item) => item.id === renameId,
    );

    setRenameDraft(
      String(target?.title || ''),
    );
  }, [renameId]); // eslint-disable-line
    // react-hooks/exhaustive-deps


  const commitRename = () => {
    const title = renameDraft.trim();

    if (title && renameId) {
      onRename(renameId, title);
    }

    onRenameDone();
  };


  return (
    <>
      {items.map((item, index) => {
        const isActive =
          item.id === activeId;

        const renaming =
          renameId === item.id;

        return (
          <div
            key={item.id}
            className={
              'conv pop-in' +
              (
                page
                  ? ' conv--page'
                  : ''
              ) +
              (
                isActive
                  ? ' conv--active'
                  : ''
              ) +
              (
                item.archived
                  ? ' conv--archived'
                  : ''
              )
            }
            style={{
              animationDelay:
                `${Math.min(
                  index * 34,
                  300,
                )}ms`,
            }}
          >
            <span className="conv__icon">
              {
                item.legacy
                  ? '🤖'
                  : item.archived
                    ? '📦'
                    : '💬'
              }
            </span>

            {
              renaming
                ? (
                  <div className="conv-rename">
                    <input
                      className={
                        'inp ' +
                        'conv-rename__inp'
                      }
                      autoFocus
                      value={renameDraft}
                      maxLength={80}
                      onChange={(event) =>
                        setRenameDraft(
                          event.target
                            .value,
                        )
                      }
                      onKeyDown={(event) => {
                        if (
                          event.key ===
                          'Enter'
                        ) {
                          commitRename();
                        }

                        if (
                          event.key ===
                          'Escape'
                        ) {
                          onRenameDone();
                        }
                      }}
                      aria-label="نام جدید گفت‌وگو"
                    />
                  </div>
                )
                : (
                  <button
                    type="button"
                    className="conv__main"
                    onClick={() =>
                      onSelect(item)
                    }
                  >
                    <span className="conv__body">
                      <span className="conv__title">
                        <span dir="auto">
                          {item.title}
                        </span>

                        {
                          item.pinned
                          && (
                            <span
                              className="conv__pin"
                              title="پین‌شده"
                            >
                              📌
                            </span>
                          )
                        }

                        {
                          item.legacy
                            ? (
                              <span className="badge b-pur">
                                مشترک با ربات
                              </span>
                            )
                            : (
                              <span className="sync-chip">
                                ✓ همگام
                              </span>
                            )
                        }
                      </span>

                      {
                        item.preview
                        && (
                          <span
                            className="conv__preview"
                            dir="auto"
                          >
                            {item.preview}
                          </span>
                        )
                      }

                      <span className="conv__meta">
                        {
                          relativeTime(
                            item.updated_at,
                          )
                        }

                        <span className="conv__count">
                          {
                            Number(
                              item.count || 0,
                            ).toLocaleString(
                              'fa-IR',
                            )
                          }
                          {' پیام'}
                        </span>
                      </span>
                    </span>
                  </button>
                )
            }

            <span className="conv__acts">
              {
                renaming
                  ? (
                    <>
                      <button
                        type="button"
                        className={
                          'conv__act ' +
                          'conv__act--on'
                        }
                        onClick={commitRename}
                        aria-label="ذخیره‌ی نام"
                      >
                        ✓
                      </button>

                      <button
                        type="button"
                        className="conv__act"
                        onClick={onRenameDone}
                        aria-label="انصراف"
                      >
                        ✕
                      </button>
                    </>
                  )
                  : (
                    <button
                      type="button"
                      className="conv__act"
                      onClick={() =>
                        onOpenActions(item)
                      }
                      disabled={busy}
                      aria-label="عملیات گفت‌وگو"
                    >
                      ⋯
                    </button>
                  )
              }
            </span>
          </div>
        );
      })}
    </>
  );
}
