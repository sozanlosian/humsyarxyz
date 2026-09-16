import {
  useUIStore,
} from '../../stores/uiStore';


const CONFIG = {
  success: {
    icon:
      '✓',

    color:
      'var(--t-ok)',

    soft:
      'var(--soft-ok)',

    border:
      'var(--bd-ok)',
  },

  error: {
    icon:
      '!',

    color:
      'var(--t-err)',

    soft:
      'var(--soft-err-2)',

    border:
      'var(--bd-err)',
  },

  warning: {
    icon:
      '!',

    color:
      'var(--t-warn)',

    soft:
      'var(--soft-warn-2)',

    border:
      'var(--bd-warn)',
  },

  info: {
    icon:
      'i',

    color:
      'var(--t-acc)',

    soft:
      'var(--soft-acc-2)',

    border:
      'var(--bdg)',
  },
};


export default function Toast() {
  const toasts =
    useUIStore(
      (state) =>
        state.toasts
    );


  if (
    !Array.isArray(toasts) ||
    toasts.length === 0
  ) {
    return null;
  }


  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      style={{
        position:
          'fixed',

        top:
          'calc(10px + env(safe-area-inset-top))',

        left:
          '50%',

        zIndex:
          1000,

        display:
          'grid',

        width:
          'calc(100% - 24px)',

        maxWidth:
          470,

        gap: 'var(--sp-2)',

        transform:
          'translateX(-50%)',

        pointerEvents:
          'none',
      }}
    >
      {toasts.map(
        (
          toast,
          index
        ) => {
          const config =
            CONFIG[
              toast.type
            ] ||
            CONFIG.info;

          return (
            <div
              key={toast.id}
              role={
                toast.type ===
                'error'
                  ? 'alert'
                  : 'status'
              }
              className={
                'glass pop-in'
              }
              style={{
                display:
                  'flex',

                alignItems:
                  'center',

                minHeight:
                  52,

                gap: 'var(--sp-3)',

                padding:
                  '9px 11px',

                color:
                  'var(--tx)',

                border:
                  `1px solid ${
                    config.border
                  }`,

                borderRadius: 'var(--r-lg)',

                boxShadow:
                  'var(--shd-3)',

                animationDelay:
                  `${
                    index * 35
                  }ms`,

                pointerEvents:
                  'auto',
              }}
            >
              <span
                style={{
                  display:
                    'grid',

                  flex:
                    '0 0 34px',

                  height:
                    34,

                  placeItems:
                    'center',

                  color:
                    config.color,

                  background:
                    config.soft,

                  borderRadius: 'var(--r-md)',

                  fontSize: 'var(--fs-lg)',

                  fontWeight:
                    900,
                }}
              >
                {config.icon}
              </span>

              <span
                style={{
                  flex:
                    1,

                  fontSize: 'var(--fs-meta)',

                  fontWeight:
                    650,

                  lineHeight:
                    1.7,
                }}
              >
                {/* 🧯 uiStore متن را ایمن
                    می‌کند؛ این گارد اضافی هم
                    سندِ دفاع است */}
                {typeof toast.msg ===
                'string'
                  ? toast.msg
                  : ''}
              </span>

              <span
                style={{
                  width:
                    4,

                  alignSelf:
                    'stretch',

                  background:
                    config.color,

                  borderRadius: 'var(--r-pill)',

                  opacity:
                    .7,
                }}
              />
            </div>
          );
        }
      )}
    </div>
  );
}
